"""스캔 결과 저장소.

파일 내용 해시를 키로 쓴다. 파일을 옮기거나 이름을 바꿔도 처리 상태와
직접 고친 분류는 그대로 따라온다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

from classify import analyze
from extract import SUPPORTED, ExtractError, extract_rich
from organize import ROLE_BODY, group_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id              TEXT PRIMARY KEY,
    path            TEXT NOT NULL,
    filename        TEXT NOT NULL,
    modified        TEXT NOT NULL,
    scanned_at      TEXT NOT NULL,
    title           TEXT,
    sender          TEXT,
    doc_number      TEXT,
    category        TEXT,
    category_manual TEXT,
    confidence      TEXT,
    deadline        TEXT,
    deadline_context TEXT,
    event_date      TEXT,
    all_dates       TEXT,
    summary         TEXT,
    body            TEXT,
    body_html       TEXT DEFAULT '',
    group_key       TEXT DEFAULT '',
    role            TEXT DEFAULT '',
    receipt_number  TEXT DEFAULT '',
    archived        TEXT DEFAULT '',
    deadline_edited INTEGER DEFAULT 0,
    done            INTEGER DEFAULT 0,
    memo            TEXT DEFAULT '',
    error           TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_deadline ON docs(deadline);
"""


class Store:
    """SQLite 저장소. 위젯과 브라우저가 같은 객체를 나눠 쓴다.

    커넥션 하나를 여러 스레드가 함께 쓴다 — tkinter 메인 스레드(위젯 그리기),
    위젯의 스캔 스레드, 그리고 HTTP 요청마다 생기는 스레드들. `check_same_thread`
    를 끄는 것만으로는 안전해지지 않아서(파이썬의 검사만 꺼질 뿐 직렬화는 되지
    않는다) 모든 접근을 락 하나로 묶는다. 이게 없으면 스캔이 커밋하기 전 상태를
    다른 쪽이 읽거나, 남의 트랜잭션이 같이 커밋되는 일이 생긴다.

    `rev` 는 내용이 바뀔 때마다 오르는 번호다. 위젯과 브라우저는 이 번호만
    보고 "다시 그릴 일이 있는지" 판단한다. 전체를 다시 읽어 비교할 필요가 없다.
    """

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.rev = 0
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def touch(self) -> int:
        """내용이 바뀌었다고 알린다. 보는 쪽이 다시 그리게 된다."""
        with self._lock:
            self.rev += 1
            return self.rev

    def _migrate(self) -> None:
        """예전 버전에서 만든 파일에 새 칸을 붙인다."""
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(docs)")}
        for column, definition in (("body_html", "TEXT DEFAULT ''"),
                                   ("group_key", "TEXT DEFAULT ''"),
                                   ("role", "TEXT DEFAULT ''"),
                                   ("receipt_number", "TEXT DEFAULT ''"),
                                   ("archived", "TEXT DEFAULT ''"),
                                   ("deadline_edited", "INTEGER DEFAULT 0")):
            if column not in existing:
                self.conn.execute(f"ALTER TABLE docs ADD COLUMN {column} {definition}")

    # ------------------------------------------------------------- 스캔

    def scan(self, folder: Path, force: bool = False) -> dict:
        """폴더를 훑어 새 파일만 분석한다."""
        with self._lock:
            report = self._scan(folder, force)
        return report

    def _scan(self, folder: Path, force: bool = False) -> dict:
        added = skipped = failed = moved = 0
        # 경로까지 같이 들고 온다. 이름만 바뀐 파일을 알아보기 위해서다.
        known = {row["id"]: row["path"]
                 for row in self.conn.execute("SELECT id, path FROM docs")}
        seen: set[str] = set()

        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                continue
            if path.name.startswith("~$") or path.name.startswith("."):
                continue
            doc_id = _file_id(path)
            seen.add(doc_id)
            if doc_id in known and not force:
                # 자리나 이름이 그대로면 아무것도 쓰지 않는다. 쓸데없이 써 두면
                # 바뀐 게 없는데도 rev 가 올라 위젯이 헛되이 다시 그린다.
                if known[doc_id] != str(path):
                    self.conn.execute("UPDATE docs SET path=?, filename=? WHERE id=?",
                                      (str(path), path.name, doc_id))
                    moved += 1
                skipped += 1
                continue
            try:
                body, body_html = extract_rich(path)
                result = analyze(path.stem, body)
                error = ""
            except (ExtractError, Exception) as exc:  # noqa: BLE001
                body, body_html, error = "", "", str(exc)[:200]
                result = {
                    "title": path.stem, "sender": "", "doc_number": "",
                    "receipt_number": "", "category": "other", "confidence": "낮음",
                    "deadline": None, "deadline_context": "", "event_date": None,
                    "all_dates": [], "summary": "",
                }
                failed += 1
            result["group_key"], result["role"] = group_key(
                path, folder, result.get("receipt_number", ""))
            self._upsert(doc_id, path, result, body, body_html, error)
            if not error:
                added += 1

        removed = self._forget_missing(seen, folder)
        self.conn.commit()
        if added or failed or removed or moved:
            self.rev += 1
        return {"added": added, "skipped": skipped, "failed": failed,
                "removed": removed, "moved": moved}

    def _upsert(self, doc_id: str, path: Path, result: dict, body: str,
                body_html: str, error: str) -> None:
        stat = path.stat()
        self.conn.execute(
            """INSERT INTO docs (id, path, filename, modified, scanned_at, title, sender,
                                 doc_number, category, confidence, deadline, deadline_context,
                                 event_date, all_dates, summary, body, body_html,
                                 group_key, role, receipt_number, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 path=excluded.path, filename=excluded.filename, scanned_at=excluded.scanned_at,
                 title=excluded.title, sender=excluded.sender, doc_number=excluded.doc_number,
                 category=excluded.category, confidence=excluded.confidence,
                 deadline_context=excluded.deadline_context,
                 event_date=excluded.event_date, all_dates=excluded.all_dates,
                 deadline=CASE WHEN docs.deadline_edited=1 THEN docs.deadline
                               ELSE excluded.deadline END,
                 summary=excluded.summary, body=excluded.body,
                 body_html=excluded.body_html, group_key=excluded.group_key,
                 role=excluded.role, receipt_number=excluded.receipt_number,
                 error=excluded.error""",
            (
                doc_id, str(path), path.name,
                date.fromtimestamp(stat.st_mtime).isoformat(),
                date.today().isoformat(),
                result["title"], result["sender"], result["doc_number"],
                result["category"], result["confidence"], result["deadline"],
                result["deadline_context"], result["event_date"],
                json.dumps(result["all_dates"], ensure_ascii=False),
                result["summary"], body[:20000], body_html[:120000],
                result.get("group_key", ""), result.get("role", ""),
                result.get("receipt_number", ""), error,
            ),
        )

    def _forget_missing(self, seen: set[str], folder: Path) -> int:
        """이번에 훑은 폴더 밖의 기록을 정리한다.

        월별 폴더로 옮긴 문서는 정리했다는 표시가 있으므로 남긴다.
        그 표시가 없는데 공문 폴더 밖에 있는 것은 실수로 읽어들인
        남의 파일이므로 기록에서 지운다. 파일 자체는 건드리지 않는다.
        """
        rows = self.conn.execute("SELECT id, path, archived FROM docs").fetchall()
        gone: list[str] = []
        for row in rows:
            if row["id"] in seen:
                continue
            path = Path(row["path"])
            if not path.exists():
                gone.append(row["id"])
                continue
            if row["archived"]:              # 우리가 옮긴 것은 그대로 둔다
                continue
            if not _is_inside(path, folder):
                gone.append(row["id"])
        for doc_id in gone:
            self.conn.execute("DELETE FROM docs WHERE id=?", (doc_id,))
        return len(gone)

    # ------------------------------------------------------------- 조회

    def all_docs(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM docs").fetchall()
        return [self._to_dict(row) for row in rows]

    def get(self, doc_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
        return self._to_dict(row, include_body=True) if row else None

    @staticmethod
    def _to_dict(row: sqlite3.Row, include_body: bool = False) -> dict:
        data = dict(row)
        data["all_dates"] = json.loads(data.get("all_dates") or "[]")
        data["done"] = bool(data["done"])
        data["category"] = data["category_manual"] or data["category"]
        data["edited"] = bool(data["category_manual"])
        if not include_body:
            data.pop("body", None)
            data.pop("body_html", None)
        return data

    # ------------------------------------------------------------- 수정

    def _write(self, sql: str, params: tuple) -> None:
        """한 건 고치고 커밋한 뒤 바뀌었다고 알린다."""
        with self._lock:
            self.conn.execute(sql, params)
            self.conn.commit()
            self.rev += 1

    def set_done(self, doc_id: str, done: bool) -> None:
        self._write("UPDATE docs SET done=? WHERE id=?", (1 if done else 0, doc_id))

    def set_category(self, doc_id: str, category: str) -> None:
        self._write("UPDATE docs SET category_manual=? WHERE id=?", (category, doc_id))

    def set_memo(self, doc_id: str, memo: str) -> None:
        self._write("UPDATE docs SET memo=? WHERE id=?", (memo[:500], doc_id))

    def relocate(self, doc_id: str, new_path: str, archived: str) -> None:
        """파일을 옮긴 뒤 기록의 위치를 따라가게 한다."""
        path = Path(new_path)
        self._write("UPDATE docs SET path=?, filename=?, archived=? WHERE id=?",
                    (str(path), path.name, archived, doc_id))

    def set_deadline(self, doc_id: str, deadline: str | None) -> None:
        """손으로 정한 기한은 표시를 남긴다.

        본문과 첨부를 묶을 때 가장 이른 기한을 쓰는데, 손으로 고친 값은
        그 계산에 밀리면 안 되기 때문이다.
        """
        self._write("UPDATE docs SET deadline=?, deadline_edited=1 WHERE id=?",
                    (deadline or None, doc_id))


def _is_inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


def _file_id(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while chunk := handle.read(262144):
            digest.update(chunk)
    return digest.hexdigest()[:16]

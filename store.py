"""스캔 결과 저장소.

파일 내용 해시를 키로 쓴다. 파일을 옮기거나 이름을 바꿔도 처리 상태와
직접 고친 분류는 그대로 따라온다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

from classify import analyze
from extract import SUPPORTED, ExtractError, extract_rich

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
    done            INTEGER DEFAULT 0,
    memo            TEXT DEFAULT '',
    error           TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_deadline ON docs(deadline);
"""


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """예전 버전에서 만든 파일에 새 칸을 붙인다."""
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(docs)")}
        for column, definition in (("body_html", "TEXT DEFAULT ''"),):
            if column not in existing:
                self.conn.execute(f"ALTER TABLE docs ADD COLUMN {column} {definition}")

    # ------------------------------------------------------------- 스캔

    def scan(self, folder: Path, force: bool = False) -> dict:
        """폴더를 훑어 새 파일만 분석한다."""
        added = skipped = failed = 0
        known = {row["id"] for row in self.conn.execute("SELECT id FROM docs")}
        seen: set[str] = set()

        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                continue
            if path.name.startswith("~$") or path.name.startswith("."):
                continue
            doc_id = _file_id(path)
            seen.add(doc_id)
            if doc_id in known and not force:
                self.conn.execute("UPDATE docs SET path=?, filename=? WHERE id=?",
                                  (str(path), path.name, doc_id))
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
                    "category": "other", "confidence": "낮음", "deadline": None,
                    "deadline_context": "", "event_date": None, "all_dates": [],
                    "summary": "",
                }
                failed += 1
            self._upsert(doc_id, path, result, body, body_html, error)
            if not error:
                added += 1

        removed = self._forget_missing(seen)
        self.conn.commit()
        return {"added": added, "skipped": skipped, "failed": failed, "removed": removed}

    def _upsert(self, doc_id: str, path: Path, result: dict, body: str,
                body_html: str, error: str) -> None:
        stat = path.stat()
        self.conn.execute(
            """INSERT INTO docs (id, path, filename, modified, scanned_at, title, sender,
                                 doc_number, category, confidence, deadline, deadline_context,
                                 event_date, all_dates, summary, body, body_html, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 path=excluded.path, filename=excluded.filename, scanned_at=excluded.scanned_at,
                 title=excluded.title, sender=excluded.sender, doc_number=excluded.doc_number,
                 category=excluded.category, confidence=excluded.confidence,
                 deadline=excluded.deadline, deadline_context=excluded.deadline_context,
                 event_date=excluded.event_date, all_dates=excluded.all_dates,
                 summary=excluded.summary, body=excluded.body,
                 body_html=excluded.body_html, error=excluded.error""",
            (
                doc_id, str(path), path.name,
                date.fromtimestamp(stat.st_mtime).isoformat(),
                date.today().isoformat(),
                result["title"], result["sender"], result["doc_number"],
                result["category"], result["confidence"], result["deadline"],
                result["deadline_context"], result["event_date"],
                json.dumps(result["all_dates"], ensure_ascii=False),
                result["summary"], body[:20000], body_html[:120000], error,
            ),
        )

    def _forget_missing(self, seen: set[str]) -> int:
        rows = self.conn.execute("SELECT id, path FROM docs").fetchall()
        gone = [r["id"] for r in rows if r["id"] not in seen and not Path(r["path"]).exists()]
        for doc_id in gone:
            self.conn.execute("DELETE FROM docs WHERE id=?", (doc_id,))
        return len(gone)

    # ------------------------------------------------------------- 조회

    def all_docs(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM docs").fetchall()
        return [self._to_dict(row) for row in rows]

    def get(self, doc_id: str) -> dict | None:
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

    def set_done(self, doc_id: str, done: bool) -> None:
        self.conn.execute("UPDATE docs SET done=? WHERE id=?", (1 if done else 0, doc_id))
        self.conn.commit()

    def set_category(self, doc_id: str, category: str) -> None:
        self.conn.execute("UPDATE docs SET category_manual=? WHERE id=?", (category, doc_id))
        self.conn.commit()

    def set_memo(self, doc_id: str, memo: str) -> None:
        self.conn.execute("UPDATE docs SET memo=? WHERE id=?", (memo[:500], doc_id))
        self.conn.commit()

    def set_deadline(self, doc_id: str, deadline: str | None) -> None:
        self.conn.execute("UPDATE docs SET deadline=? WHERE id=?", (deadline or None, doc_id))
        self.conn.commit()


def _file_id(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while chunk := handle.read(262144):
            digest.update(chunk)
    return digest.hexdigest()[:16]

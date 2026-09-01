"""공문 정리함 — 실행 진입점.

  python app.py                     설정 폴더를 훑고 브라우저를 연다
  python app.py --folder D:/공문     폴더를 지정하고 저장한다
  python app.py --rescan            이미 읽은 파일까지 전부 다시 분석한다
  python app.py --no-browser        서버만 띄운다
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from classify import CATEGORIES, CATEGORY_ORDER, days_left  # noqa: E402
from store import Store  # noqa: E402
import organize  # noqa: E402

def _base_dir() -> Path:
    """exe로 묶이면 파일들이 임시 폴더에 풀린다. 그때는 그쪽을 봐야 한다."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
HOME_DIR = Path.home() / ".gongmun"
CONFIG_PATH = HOME_DIR / "config.json"
DB_PATH = HOME_DIR / "docs.db"
# 버전을 올리고 커밋하면 GitHub이 알아서 새 릴리스를 만든다.
# 이미 깔려 있는 프로그램들은 그 릴리스를 보고 스스로 갱신한다.
VERSION = "1.3.2"

# 업데이트를 받아 올 저장소. "사용자이름/저장소이름" 형태로 적는다.
# 공개 저장소여야 한다. 비공개면 받는 쪽에서 접근하지 못한다.
UPDATE_REPO = "techhyunseo2/gongmun"

PORT = 8777
PORT_TRIES = 12


# ------------------------------------------------------------------ 설정

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_config(config: dict) -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_inbox(chosen: Path) -> tuple[Path, Path]:
    """(업무 루트, 공문 인박스)를 정하고 인박스가 없으면 만든다.

    월별 폴더에는 공문 말고도 제출 자료나 개인정보가 든 파일이 섞여 있다.
    그래서 프로그램이 들여다보는 곳은 오직 공문 인박스 한 곳뿐이다.
    """
    base, inbox = organize.resolve_workspace(chosen)
    try:
        inbox.mkdir(parents=True, exist_ok=True)
    except OSError:
        return chosen.parent, chosen
    return base, inbox


def resolve_folder(cli_folder: str | None, ask: bool = False) -> Path:
    config = load_config()
    if cli_folder:
        folder = Path(cli_folder).expanduser().resolve()
        config["folder"] = str(folder)
        save_config(config)
        return folder
    if config.get("folder") and Path(config["folder"]).is_dir():
        return Path(config["folder"])

    folder = ask_folder() if ask else None
    if folder is None:
        folder = Path.home() / "Documents" / "공문"
        if not folder.exists():
            folder = Path.home() / "Downloads" / "공문"
    folder.mkdir(parents=True, exist_ok=True)
    config["folder"] = str(folder.resolve())
    save_config(config)
    return folder.resolve()


def ask_folder() -> Path | None:
    """첫 실행 때 공문을 모아 둘 폴더를 창으로 고르게 한다."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    try:
        suggested = Path.home() / "Documents" / "공문"
        messagebox.showinfo(
            "공문 정리함",
            "공문을 모아 둘 폴더를 하나 정해 주세요.\n\n"
            "앞으로 에듀파인에서 공문을 내려받아 이 폴더에 넣으면\n"
            "프로그램이 알아서 읽고 기한 순으로 정리해 줍니다.\n\n"
            f"따로 만들어 두신 폴더가 없으면\n{suggested}\n폴더를 새로 만들어 쓰셔도 됩니다.",
        )
        suggested.mkdir(parents=True, exist_ok=True)
        chosen = filedialog.askdirectory(title="공문을 모아 둘 폴더 고르기",
                                         initialdir=str(suggested))
        return Path(chosen) if chosen else suggested
    finally:
        root.destroy()


# -------------------------------------------------------------- 파일 열기

def open_in_os(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ------------------------------------------------------------------ ICS

def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def _ics_fold(line: str) -> str:
    """한 줄이 75옥텟을 넘으면 규격대로 접는다."""
    raw = line.encode("utf-8")
    if len(raw) <= 73:
        return line
    out, chunk = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        limit = 73 if not out else 72
        if len(chunk) + len(encoded) > limit:
            out.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += encoded
    out.append(chunk.decode("utf-8"))
    return "\r\n ".join(out)


def build_ics(docs: list[dict]) -> str:
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//gongmun//KR",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:공문 일정",
    ]
    stamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    for doc in docs:
        when = doc.get("deadline") or doc.get("event_date")
        if not when:
            continue
        prefix = "[마감] " if doc.get("deadline") else "[일정] "
        summary = _ics_escape(prefix + (doc.get("title") or doc["filename"]))[:180]
        detail = _ics_escape((doc.get("summary") or "")[:300])
        lines += [
            "BEGIN:VEVENT",
            f"UID:{doc['id']}@gongmun",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{when.replace('-', '')}",
            _ics_fold(f"SUMMARY:{summary}"),
            _ics_fold(f"DESCRIPTION:{detail}"),
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


# ---------------------------------------------------------------- 서버

class Handler(BaseHTTPRequestHandler):
    store: Store
    folder: Path          # 공문 인박스 — 여기만 읽는다
    base: Path            # 업무 루트 — 월별 폴더를 만드는 곳

    def log_message(self, *args):  # 콘솔을 조용하게
        pass

    # ---------------------------------------------------------- helpers

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: int = 200):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------------------- GET

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route in ("/", "/index.html"):
            html = (BASE_DIR / "ui.html").read_bytes()
            return self._send(200, html, "text/html; charset=utf-8")

        if route == "/api/state":
            return self._json(self._state())

        if route == "/api/scan":
            force = query.get("force", ["0"])[0] == "1"
            report = self.store.scan(self.folder, force=force)
            state = self._state()
            state["report"] = report
            return self._json(state)

        if route == "/api/doc":
            doc = self.store.get(query.get("id", [""])[0])
            return self._json(doc or {"error": "찾을 수 없습니다."}, 200 if doc else 404)

        if route == "/api/open":
            doc = self.store.get(query.get("id", [""])[0])
            if not doc:
                return self._json({"error": "찾을 수 없습니다."}, 404)
            target = Path(doc["path"])
            if not target.exists():
                return self._json({"error": "파일이 폴더에 없습니다."}, 404)
            open_in_os(target)
            return self._json({"ok": True})

        if route == "/api/organize":
            preview = query.get("preview", ["0"])[0] == "1"
            report = organize.organize(self.folder, self._titles(), dry_run=preview)
            if not preview:
                self.store.scan(self.folder)
            state = self._state()
            state["organized"] = report
            return self._json(state)

        if route == "/api/archive":
            preview = query.get("preview", ["0"])[0] == "1"
            state = self._archive(preview)
            return self._json(state)

        if route == "/api/open-folder":
            open_in_os(self.folder)
            return self._json({"ok": True})

        if route == "/api/calendar.ics":
            docs = [d for d in self.store.all_docs() if not d["done"]]
            body = build_ics(docs).encode("utf-8")
            return self._send(200, body, "text/calendar; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="gongmun.ics"'})

        return self._send(404, b"not found", "text/plain; charset=utf-8")

    # ------------------------------------------------------------- POST

    def do_POST(self):  # noqa: N802
        route = urlparse(self.path).path
        payload = self._read_json()
        doc_id = payload.get("id", "")

        if route == "/api/done":
            done = bool(payload.get("done"))
            for member in payload.get("members") or [doc_id]:
                self.store.set_done(member, done)
        elif route == "/api/category":
            category = payload.get("category")
            if category not in CATEGORIES:
                return self._json({"error": "알 수 없는 유형입니다."}, 400)
            self.store.set_category(doc_id, category)
        elif route == "/api/memo":
            self.store.set_memo(doc_id, payload.get("memo", ""))
        elif route == "/api/deadline":
            self.store.set_deadline(doc_id, payload.get("deadline") or None)
        elif route == "/api/folder":
            folder = Path(unquote(payload.get("folder", ""))).expanduser()
            if not folder.is_dir():
                return self._json({"error": "그런 폴더가 없습니다."}, 400)
            base, inbox = resolve_inbox(folder.resolve())
            config = load_config()
            config["folder"] = str(inbox)
            save_config(config)
            Handler.base, Handler.folder = base, inbox
            self.store.scan(inbox)
        else:
            return self._json({"error": "알 수 없는 요청입니다."}, 404)

        return self._json(self._state())

    def _titles(self) -> dict[str, str]:
        """접수번호별 대표 제목. 본문에서 읽은 것을 우선한다."""
        titles: dict[str, str] = {}
        for group in fold_groups(self.store.all_docs()):
            key = group.get("receipt_number") or group.get("group_key") or ""
            if key and group.get("title"):
                titles[key] = group["title"]
        return titles

    def _archive(self, preview: bool) -> dict:
        """끝난 공문을 마감 월 폴더로 옮긴다."""
        base, inbox = self.base, self.folder
        entries, skipped = [], 0
        for group in fold_groups(self.store.all_docs()):
            if not group["done"] or group.get("archived"):
                continue
            month = _month_of(group)
            if month is None:
                skipped += 1
                continue
            entries.append({
                "title": group.get("title") or group["filename"],
                "month": month,
                "receipt": group.get("receipt_number") or "",
                "paths": group["paths"],
                "ids": [m["id"] for m in group["members"]],
            })

        report = organize.archive(base, inbox, entries, dry_run=preview)
        if not preview:
            moved = report.get("relocated", {})
            for entry in entries:
                for member_id, old in zip(entry["ids"], entry["paths"]):
                    if old in moved:
                        self.store.relocate(member_id, moved[old], f"{entry['month']}월")
        report["no_date"] = skipped
        report["base"] = str(base)
        state = self._state()
        state["archived_report"] = report
        return state

    # -------------------------------------------------------------- 상태

    def _state(self) -> dict:
        today = date.today()
        docs = fold_groups(self.store.all_docs())
        for doc in docs:
            doc["days_left"] = days_left(doc.get("deadline"), today)
        docs.sort(key=_sort_key)
        counts = {key: 0 for key in CATEGORY_ORDER}
        for doc in docs:
            if not doc["done"]:
                counts[doc["category"]] = counts.get(doc["category"], 0) + 1
        urgent = [d for d in docs if not d["done"] and d["days_left"] is not None and d["days_left"] <= 3]
        return {
            "folder": str(self.folder),
            "base": str(self.base),
            "inbox": str(self.folder),
            "months": sorted(organize.month_dirs(self.base)),
            "today": today.isoformat(),
            "categories": CATEGORIES,
            "order": CATEGORY_ORDER,
            "counts": counts,
            "urgent": len(urgent),
            "docs": docs,
        }


def fold_groups(docs: list[dict]) -> list[dict]:
    """같은 접수번호끼리 하나로 묶는다.

    본문이 대표가 되고 첨부는 딸린 문서로 붙는다. 기한과 날짜는 묶음 전체에서
    모으는데, 첨부의 제출 서식에만 기한이 적힌 경우가 흔하기 때문이다.
    """
    buckets: dict[str, list[dict]] = {}
    for doc in docs:
        buckets.setdefault(doc.get("group_key") or doc["id"], []).append(doc)

    folded: list[dict] = []
    for key, members in buckets.items():
        members.sort(key=lambda d: (d.get("role") != organize.ROLE_BODY, d["filename"]))
        lead = _pick_lead(members)
        entry = dict(lead)
        entry["group_key"] = key
        entry["members"] = [
            {"id": m["id"], "filename": m["filename"], "role": m.get("role") or "",
             "error": m.get("error") or "", "path": m.get("path") or ""}
            for m in members
        ]
        entry["attachments"] = sum(1 for m in members
                                   if m.get("role") == organize.ROLE_ATTACH)
        entry["paths"] = [m["path"] for m in members]
        entry["archived"] = next((m.get("archived") for m in members if m.get("archived")), "")

        deadlines = sorted({m["deadline"] for m in members if m.get("deadline")})
        if deadlines:
            entry["deadline"] = deadlines[0]
            if not entry.get("deadline_context"):
                source = next(m for m in members if m["deadline"] == deadlines[0])
                entry["deadline_context"] = source.get("deadline_context") or ""
        events = sorted({m["event_date"] for m in members if m.get("event_date")})
        entry["event_date"] = events[0] if events else None
        entry["all_dates"] = sorted({d for m in members for d in (m.get("all_dates") or [])})
        entry["done"] = all(m["done"] for m in members)
        folded.append(entry)
    return folded


def _pick_lead(members: list[dict]) -> dict:
    """묶음을 대표할 문서. 본문이 있으면 본문, 없으면 판단이 가장 또렷한 것."""
    for member in members:
        if member.get("role") == organize.ROLE_BODY:
            return member
    ranking = {"높음": 0, "보통": 1, "낮음": 2}
    return min(members, key=lambda m: (ranking.get(m.get("confidence"), 3),
                                       not m.get("deadline")))


def _month_of(group: dict) -> int | None:
    """어느 달 폴더로 보낼지 정한다. 마감 → 행사일 → 파일 날짜 순으로 본다."""
    for key in ("deadline", "event_date", "modified"):
        value = group.get(key)
        if value:
            try:
                return int(str(value).split("-")[1])
            except (IndexError, ValueError):
                continue
    return None


def _sort_key(doc: dict):
    """마감 임박한 것부터, 마감 없는 것은 파일 날짜 최신순."""
    if doc["done"]:
        return (2, 0, "")
    if doc["days_left"] is not None:
        return (0, doc["days_left"], doc["title"] or "")
    return (1, 0, "-" + (doc.get("modified") or ""))


# ------------------------------------------------------------------ main

def already_running(port: int) -> bool:
    """같은 프로그램이 이미 떠 있는지 본다.

    포트가 열려 있다는 것만으로는 부족하다. 다른 프로그램이 그 번호를
    쓰고 있을 수 있으므로, 우리 응답이 오는지까지 확인한다.
    """
    import json as _json
    import urllib.error
    import urllib.request
    for offset in range(PORT_TRIES):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port + offset}/api/state",
                                        timeout=0.5) as response:
                data = _json.loads(response.read().decode("utf-8"))
                if "categories" in data and "docs" in data:
                    return True
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue
    return False


def start_server(store: Store, folder: Path, port: int = PORT,
                 base: Path | None = None) -> tuple[ThreadingHTTPServer, int]:
    """API 서버를 띄우고 (서버, 실제로 쓴 포트)를 돌려준다.

    포트가 이미 쓰이고 있으면 옆 번호로 옮겨 간다.
    """
    Handler.store = store
    Handler.folder = folder
    Handler.base = base or getattr(Handler, "base", folder.parent)
    last: OSError | None = None
    for offset in range(PORT_TRIES):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port + offset), Handler)
        except OSError as exc:
            last = exc
            continue
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, port + offset
    raise RuntimeError(f"쓸 수 있는 포트를 찾지 못했습니다: {last}")


def main() -> None:
    parser = argparse.ArgumentParser(description="공문 정리함")
    parser.add_argument("--folder", help="공문을 모아 두는 폴더")
    parser.add_argument("--rescan", action="store_true", help="전부 다시 분석")
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않음")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    folder = resolve_folder(args.folder)
    if not folder.is_dir():
        print(f"폴더를 찾을 수 없습니다: {folder}")
        sys.exit(1)

    base, folder = resolve_inbox(folder)
    store = Store(DB_PATH)
    print(f"업무 폴더: {base}")
    print(f"공문 폴더를 읽는 중: {folder}")
    report = store.scan(folder, force=args.rescan)
    print(f"새로 분석 {report['added']}건 · 그대로 {report['skipped']}건 · 실패 {report['failed']}건")

    server, port = start_server(store, folder, args.port, base=base)
    url = f"http://127.0.0.1:{port}/"
    print(f"주소: {url}   (종료는 Ctrl+C)")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n종료합니다.")
        server.shutdown()


if __name__ == "__main__":
    main()

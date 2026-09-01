"""공문 정리함 — 바탕화면 위젯.

테두리 없는 작은 창을 띄워 놓고 기한이 가까운 공문만 보여 준다.
같은 프로세스 안에서 API 서버도 돌기 때문에, 자세히 보기를 누르면
브라우저에 전체 화면이 바로 열린다.

  python widget.py                  위젯을 띄운다
  python widget.py --folder "경로"   폴더를 지정한다

머리말을 끌면 창이 움직이고, 위치는 다음 실행 때 그대로 복원된다.
오른쪽 버튼을 누르면 항상 위, 투명도, 자동 새로고침을 바꿀 수 있다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime
from pathlib import Path
from tkinter import font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import (DB_PATH, PORT, already_running, load_config, open_in_os,  # noqa: E402
                 resolve_folder, save_config, start_server)
from classify import CATEGORIES, days_left  # noqa: E402
from store import Store  # noqa: E402

PAPER = "#DDE1DC"
CARD = "#FBFBF8"
INK = "#16201B"
SOFT = "#5C685F"
RULE = "#C3CAC3"
SEAL = "#A6301F"
SLATE = "#3A5560"

CAT_COLOR = {
    "submit": "#A6301F", "event": "#3A5560", "apply": "#8A6A1F",
    "distribute": "#3C5A46", "notice": "#7B8480", "other": "#A6ADA7",
}

WIDTH, ROWS = 320, 7
REFRESH_MINUTES = 10


class Widget:
    def __init__(self, store: Store, folder: Path, port: int):
        self.store = store
        self.folder = folder
        self.port = port
        self.config = load_config()
        self.collapsed = False
        self.scanning = False

        self.root = tk.Tk()
        self.root.title("공문 정리함")
        self.root.overrideredirect(True)
        self.root.configure(bg=RULE)
        self.root.attributes("-topmost", bool(self.config.get("on_top", True)))
        self.root.attributes("-alpha", float(self.config.get("opacity", 0.96)))

        self._pick_fonts()
        self._build()
        self._place()
        self._bind()

        self.refresh(scan=True)
        self._tick()

    # ------------------------------------------------------------- 준비

    def _pick_fonts(self):
        families = set(tkfont.families())
        for name in ("Pretendard", "맑은 고딕", "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic", "나눔고딕"):
            if name in families:
                base = name
                break
        else:
            base = "TkDefaultFont"
        self.f_title = tkfont.Font(family=base, size=10, weight="bold")
        self.f_head = tkfont.Font(family=base, size=9)
        self.f_row = tkfont.Font(family=base, size=9)
        self.f_dday = tkfont.Font(family=base, size=10, weight="bold")
        self.f_small = tkfont.Font(family=base, size=8)

    def _build(self):
        outer = tk.Frame(self.root, bg=PAPER)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        # 머리말 — 여기를 끌면 창이 움직인다
        self.head = tk.Frame(outer, bg=PAPER)
        self.head.pack(fill="x", padx=12, pady=(9, 2))
        tk.Label(self.head, text="공문 정리함", font=self.f_title, bg=PAPER, fg=INK).pack(side="left")
        self.btn_close = tk.Label(self.head, text="✕", font=self.f_head, bg=PAPER, fg=SOFT, cursor="hand2")
        self.btn_close.pack(side="right", padx=(6, 0))
        self.btn_fold = tk.Label(self.head, text="—", font=self.f_head, bg=PAPER, fg=SOFT, cursor="hand2")
        self.btn_fold.pack(side="right")

        self.summary = tk.Label(outer, text="읽는 중", font=self.f_head, bg=PAPER, fg=SOFT, anchor="w")
        self.summary.pack(fill="x", padx=12, pady=(0, 8))

        self.body = tk.Frame(outer, bg=PAPER)
        self.body.pack(fill="both", expand=True)

        self.rows = tk.Frame(self.body, bg=PAPER)
        self.rows.pack(fill="both", expand=True, padx=8)

        foot = tk.Frame(self.body, bg=PAPER)
        foot.pack(fill="x", padx=12, pady=(8, 10))
        self.btn_open = self._foot_button(foot, "자세히 보기", self.open_browser)
        self.btn_open.pack(side="left")
        self.btn_scan = self._foot_button(foot, "다시 훑기", lambda e=None: self.refresh(scan=True))
        self.btn_scan.pack(side="left", padx=(6, 0))
        self.stamp = tk.Label(foot, text="", font=self.f_small, bg=PAPER, fg=SOFT)
        self.stamp.pack(side="right")

    def _foot_button(self, parent, text, command):
        label = tk.Label(parent, text=text, font=self.f_small, bg=CARD, fg=INK,
                         padx=9, pady=4, cursor="hand2",
                         highlightbackground=RULE, highlightthickness=1)
        label.bind("<Button-1>", command)
        label.bind("<Enter>", lambda e: label.config(highlightbackground=INK))
        label.bind("<Leave>", lambda e: label.config(highlightbackground=RULE))
        return label

    def _place(self):
        saved = self.config.get("widget_pos")
        if saved:
            x, y = saved
        else:
            self.root.update_idletasks()
            x = self.root.winfo_screenwidth() - WIDTH - 40
            y = 80
        self.x, self.y = int(x), int(y)
        self.root.geometry(f"{WIDTH}x300+{self.x}+{self.y}")

    def _fit_height(self):
        """내용을 다 그린 뒤 실제 필요한 높이로 창을 맞춘다."""
        if self.collapsed:
            return
        self.root.update_idletasks()
        height = min(self.root.winfo_reqheight(), self.root.winfo_screenheight() - 120)
        self.root.geometry(f"{WIDTH}x{height}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def _bind(self):
        for target in (self.head, self.summary):
            target.bind("<Button-1>", self._drag_start)
            target.bind("<B1-Motion>", self._drag_move)
            target.bind("<ButtonRelease-1>", self._drag_end)
        for child in self.head.winfo_children():
            if child not in (self.btn_close, self.btn_fold):
                child.bind("<Button-1>", self._drag_start)
                child.bind("<B1-Motion>", self._drag_move)
                child.bind("<ButtonRelease-1>", self._drag_end)
        self.btn_close.bind("<Button-1>", lambda e: self.quit())
        self.btn_fold.bind("<Button-1>", lambda e: self.toggle_fold())
        self.root.bind("<Button-3>", self._menu)
        self.root.bind("<Escape>", lambda e: self.quit())

    # ------------------------------------------------------------- 이동

    def _drag_start(self, event):
        self._dx, self._dy = event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        self.root.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")

    def _drag_end(self, _event):
        self.config["widget_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_config(self.config)

    # ------------------------------------------------------------- 갱신

    def refresh(self, scan: bool = False):
        if scan and not self.scanning:
            self.scanning = True
            self.btn_scan.config(text="읽는 중")
            threading.Thread(target=self._scan_then_draw, daemon=True).start()
        else:
            self.draw()

    def _scan_then_draw(self):
        try:
            self.store.scan(self.folder)
        except Exception as exc:  # noqa: BLE001
            print("스캔 실패:", exc)
        finally:
            self.scanning = False
            self.root.after(0, self._after_scan)

    def _after_scan(self):
        self.btn_scan.config(text="다시 훑기")
        self.draw()

    def draw(self):
        today = date.today()
        docs = [d for d in self.store.all_docs() if not d["done"]]
        for doc in docs:
            doc["left"] = days_left(doc.get("deadline"), today)
        docs.sort(key=_widget_sort)

        urgent = sum(1 for d in docs if d["left"] is not None and d["left"] <= 3)
        text = f"처리할 것 {len(docs)}건"
        if urgent:
            text += f" · 사흘 안 마감 {urgent}건"
        self.summary.config(text=text, fg=SEAL if urgent else SOFT)
        self.stamp.config(text=f"{today.month}월 {today.day}일 기준")

        for child in self.rows.winfo_children():
            child.destroy()

        if not docs:
            total = len(self.store.all_docs())
            message = "처리할 공문이 없습니다" if total else "폴더에 공문을 넣고\n다시 훑기를 눌러 주세요"
            tk.Label(self.rows, text=message, font=self.f_row, justify="center",
                     bg=PAPER, fg=SOFT, pady=22).pack(fill="x")
            self._fit_height()
            return

        for doc in docs[:ROWS]:
            self._row(doc)
        if len(docs) > ROWS:
            more = tk.Label(self.rows, text=f"그 밖에 {len(docs) - ROWS}건", font=self.f_small,
                            bg=PAPER, fg=SOFT, anchor="w", cursor="hand2", pady=6)
            more.pack(fill="x", padx=4)
            more.bind("<Button-1>", self.open_browser)
        self._fit_height()

    def _row(self, doc):
        left = doc["left"]
        if left is None:
            badge = doc["event_date"][5:].replace("-", ".") if doc.get("event_date") else "—"
            color = SOFT
        elif left < 0:
            badge, color = f"D+{-left}", SEAL
        elif left == 0:
            badge, color = "오늘", SEAL
        else:
            badge, color = f"D-{left}", SEAL if left <= 3 else SLATE

        frame = tk.Frame(self.rows, bg=CARD, highlightbackground=RULE, highlightthickness=1)
        frame.pack(fill="x", pady=2)

        bar = tk.Frame(frame, bg=CAT_COLOR.get(doc["category"], SOFT), width=3)
        bar.pack(side="left", fill="y")

        inner = tk.Frame(frame, bg=CARD)
        inner.pack(side="left", fill="both", expand=True, padx=(8, 8), pady=5)

        top = tk.Frame(inner, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text=badge, font=self.f_dday, bg=CARD, fg=color, width=5, anchor="w").pack(side="left")
        tk.Label(top, text=CATEGORIES[doc["category"]], font=self.f_small,
                 bg=CARD, fg=SOFT).pack(side="right")

        title = doc["title"] or doc["filename"]
        tk.Label(inner, text=_shorten(title, 24), font=self.f_row, bg=CARD, fg=INK,
                 anchor="w", justify="left").pack(fill="x")

        for target in (frame, inner, top) + tuple(inner.winfo_children()) + tuple(top.winfo_children()):
            target.bind("<Button-1>", self.open_browser)
            target.configure(cursor="hand2")

    # ------------------------------------------------------------- 동작

    def open_browser(self, _event=None):
        webbrowser.open(f"http://127.0.0.1:{self.port}/")

    def toggle_fold(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.body.pack_forget()
            self.root.geometry(f"{WIDTH}x62")
            self.btn_fold.config(text="□")
        else:
            self.body.pack(fill="both", expand=True)
            self.btn_fold.config(text="—")
            self._fit_height()

    def _menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        on_top = bool(self.config.get("on_top", True))
        menu.add_command(label="항상 위에 두기 " + ("끄기" if on_top else "켜기"),
                         command=self._toggle_top)
        for value, label in ((1.0, "선명하게"), (0.92, "조금 투명하게"), (0.8, "많이 투명하게")):
            menu.add_command(label=label, command=lambda v=value: self._set_opacity(v))
        menu.add_separator()
        menu.add_command(label="공문 폴더 열기", command=lambda: open_in_os(self.folder))
        menu.add_command(label="공문 폴더 바꾸기", command=self._change_folder)
        menu.add_command(label="전체 화면 열기", command=self.open_browser)
        menu.add_separator()
        menu.add_command(label="컴퓨터 켤 때 자동 실행 " + ("끄기" if startup_enabled() else "켜기"),
                         command=self._toggle_startup)
        menu.add_command(label="닫기", command=self.quit)
        menu.tk_popup(event.x_root, event.y_root)

    def _toggle_startup(self):
        from tkinter import messagebox
        message = set_startup(not startup_enabled())
        messagebox.showinfo("공문 정리함", message)

    def _change_folder(self):
        from tkinter import filedialog
        chosen = filedialog.askdirectory(title="공문을 모아 둘 폴더 고르기",
                                         initialdir=str(self.folder))
        if not chosen:
            return
        self.folder = Path(chosen)
        self.config["folder"] = str(self.folder)
        save_config(self.config)
        from app import Handler
        Handler.folder = self.folder
        self.refresh(scan=True)

    def _toggle_top(self):
        value = not bool(self.config.get("on_top", True))
        self.config["on_top"] = value
        save_config(self.config)
        self.root.attributes("-topmost", value)

    def _set_opacity(self, value: float):
        self.config["opacity"] = value
        save_config(self.config)
        self.root.attributes("-alpha", value)

    def _tick(self):
        self.root.after(REFRESH_MINUTES * 60_000, self._on_tick)

    def _on_tick(self):
        self.refresh(scan=True)
        self._tick()

    def quit(self):
        self.config["widget_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_config(self.config)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def _widget_sort(doc: dict):
    """기한이 있는 것 먼저, 그 다음 날짜만 있는 것, 마지막이 날짜 없는 것."""
    if doc["left"] is not None:
        return (0, doc["left"], "")
    if doc.get("event_date"):
        return (1, 0, doc["event_date"])
    return (2, 0, "")


def _shorten(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _startup_dir() -> Path:
    return Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"


def _startup_shortcut() -> Path:
    return _startup_dir() / "공문정리함.lnk"


def startup_enabled() -> bool:
    return _startup_shortcut().exists() or (_startup_dir() / "공문정리함.bat").exists()


def _launch_target() -> tuple[str, str, str]:
    """(실행할 파일, 인수, 작업 폴더)를 돌려준다."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return str(exe), "", str(exe.parent)
    script = Path(__file__).resolve()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else Path(sys.executable)
    return str(runner), f'"{script}"', str(script.parent)


def set_startup(enable: bool) -> str:
    """윈도우 시작 폴더에 바로가기를 넣거나 뺀다."""
    link = _startup_shortcut()
    legacy = _startup_dir() / "공문정리함.bat"
    if not enable:
        link.unlink(missing_ok=True)
        legacy.unlink(missing_ok=True)
        return "컴퓨터를 켤 때 자동으로 뜨지 않습니다."
    if not link.parent.is_dir():
        return "이 컴퓨터에서는 자동 시작을 설정할 수 없습니다."

    target, arguments, workdir = _launch_target()
    if _make_shortcut(link, target, arguments, workdir):
        legacy.unlink(missing_ok=True)
        return "이제 컴퓨터를 켜면 자동으로 뜹니다."
    return "자동 시작을 설정하지 못했습니다. 바탕화면 바로가기를 시작 폴더에 직접 넣어 주세요."


def _make_shortcut(link: Path, target: str, arguments: str, workdir: str) -> bool:
    """윈도우 스크립트 호스트를 빌려 .lnk 파일을 만든다. 창은 뜨지 않는다."""
    if not sys.platform.startswith("win"):
        return False
    import tempfile
    script = (
        'Set shell = CreateObject("WScript.Shell")\n'
        f'Set link = shell.CreateShortcut("{link}")\n'
        f'link.TargetPath = "{target}"\n'
        f'link.Arguments = "{arguments}"\n'
        f'link.WorkingDirectory = "{workdir}"\n'
        'link.WindowStyle = 7\n'
        'link.Save\n'
    )
    path = Path(tempfile.gettempdir()) / "gongmun_link.vbs"
    try:
        path.write_text(script, encoding="utf-8-sig")
        subprocess.run(["cscript", "//nologo", str(path)], check=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return link.exists()
    except Exception:  # noqa: BLE001
        return False
    finally:
        path.unlink(missing_ok=True)


def first_run_guide(folder: Path) -> None:
    from tkinter import messagebox
    messagebox.showinfo(
        "공문 정리함",
        "설치가 끝났습니다.\n\n"
        f"공문 폴더\n{folder}\n\n"
        "이 폴더에 공문 파일을 넣으면 화면 오른쪽 위 작은 창에\n"
        "기한이 가까운 순서로 나타납니다.\n\n"
        "· 창을 끌면 원하는 자리로 옮길 수 있습니다\n"
        "· 목록을 누르면 전체 화면이 열립니다\n"
        "· 오른쪽 버튼을 누르면 설정이 나옵니다",
    )


def _install_error_handler() -> None:
    """콘솔이 없는 exe에서는 오류가 그냥 사라진다. 창으로 알리고 기록을 남긴다."""
    import traceback

    log_path = DB_PATH.parent / "오류기록.txt"

    def report(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{detail}")
        except OSError:
            pass
        try:
            from tkinter import messagebox
            messagebox.showerror(
                "공문 정리함",
                "문제가 생겨 작업을 멈췄습니다.\n\n"
                f"{exc_type.__name__}: {exc}\n\n"
                f"자세한 기록을 남겨 두었습니다.\n{log_path}",
            )
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = report
    tk.Tk.report_callback_exception = lambda self, *args: report(*args)


def main():
    _install_error_handler()
    parser = argparse.ArgumentParser(description="공문 정리함 위젯")
    parser.add_argument("--folder", help="공문을 모아 두는 폴더")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    config = load_config()
    is_first_run = not config.get("folder")

    if already_running(args.port) and not args.folder:
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("공문 정리함",
                            "이미 실행 중입니다.\n\n화면 구석에 작은 창이 떠 있는지 살펴보세요.\n"
                            "보이지 않으면 다른 창 뒤에 가려져 있을 수 있습니다.")
        root.destroy()
        return

    folder = resolve_folder(args.folder, ask=is_first_run)
    store = Store(DB_PATH)
    _server, port = start_server(store, folder, args.port)

    widget = Widget(store, folder, port)
    if is_first_run:
        widget.root.after(700, lambda: first_run_guide(folder))
    widget.run()


if __name__ == "__main__":
    main()

"""화면 비교의 창 부분 — 드래그로 자리 고르기, 결과 보여 주기.

판단은 `screen_compare.py` 가 한다. 여기는 tkinter 만 다룬다.

쓰는 흐름은 이렇다. 한글 창 두 개를 나란히 띄워 둔 채로,

1. 위젯 우클릭 → "결재 전후 비교"
2. 화면이 살짝 어두워진다. 원본 쪽을 드래그
3. 다시 어두워진다. 수정본 쪽을 드래그
4. 수정본 그림에 달라진 자리가 빨간 상자로 뜬다

**DPI 를 건드리지 않는다.** `SetProcessDPIAware` 를 중간에 켜면 이미 떠
있는 tkinter 가 보는 좌표와 화면 좌표가 어긋나 엉뚱한 곳을 찍는다.
화면 배율이 걸려 있으면 두 장 모두 똑같이 흐려지므로 비교에는 지장이 없다.

**찍은 그림은 메모리에만 둔다.** 파일로 쓰지 않는다 — 화면에 무엇이
있을지 프로그램은 알 수 없기 때문이다. 자세한 것은 `screen_compare` 의
머리말 참고.
"""

from __future__ import annotations

import base64
import ctypes
import struct
import time
import tkinter as tk
import zlib

import screen_compare

# 고를 때 화면을 덮는 막의 짙기. 너무 짙으면 무엇을 고르는지 안 보인다.
VEIL = 0.28

# 막을 걷고 화면이 다시 그려지기를 기다리는 시간(초).
SETTLE = 0.15

# 표시 상자를 글자에서 이만큼 띄운다.
MARGIN = 3

# 결과 창이 화면을 다 잡아먹지 않도록 하는 한도.
MAX_VIEW = (1200, 760)


def _virtual_screen() -> tuple[int, int, int, int]:
    """모니터 여러 대를 합친 전체 화면 범위. 두 창이 다른 모니터에 있어도 되게."""
    metric = ctypes.windll.user32.GetSystemMetrics
    return metric(76), metric(77), metric(78), metric(79)


class _Picker:
    """화면을 살짝 덮고 사각형 하나를 끌게 한다."""

    def __init__(self, root: tk.Misc, message: str):
        left, top, width, height = _virtual_screen()
        self.root = root
        self.start = None            # 막 위에 사각형을 그리는 자리 (tkinter)
        self.from_screen = None      # 실제로 찍을 자리 (윈도우 좌표)
        self.picked = None

        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.geometry(f"{width}x{height}+{left}+{top}")
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", VEIL)
        self.window.configure(bg="black")

        self.canvas = tk.Canvas(self.window, bg="black", highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            width // 2, 40, fill="white", font=("맑은 고딕", 15),
            text=f"{message}    (그만두려면 Esc)")

        self.canvas.bind("<Button-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.window.bind("<Escape>", lambda _event: self._finish())
        self.window.focus_force()
        self.canvas.focus_set()

    def _down(self, event):
        # 그리는 자리는 tkinter 좌표, 찍을 자리는 윈도우 좌표. 둘을 따로
        # 둔다 — 화면 배율이 걸린 컴퓨터에서는 두 좌표계가 어긋나서, 섞어
        # 쓰면 끌어낸 데가 아니라 엉뚱한 곳이 찍힌다.
        self.start = (event.x, event.y)
        self.from_screen = screen_compare.cursor_at()
        self.canvas.delete("box")

    def _move(self, event):
        if not self.start:
            return
        self.canvas.delete("box")
        self.canvas.create_rectangle(*self.start, event.x, event.y,
                                     outline="white", width=2, tags="box")

    def _up(self, _event):
        if not self.start:
            return
        x0, y0 = self.from_screen
        x1, y1 = screen_compare.cursor_at()
        self.picked = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        self._finish()

    def _finish(self):
        self.window.destroy()

    def run(self) -> screen_compare.Shot | None:
        """고르게 하고, 고른 자리만 찍어서 돌려준다."""
        self.window.wait_window()
        if not self.picked:
            return None

        # 막이 화면에서 실제로 걷힐 때까지 기다린다. `destroy()` 는 요청일
        # 뿐이라, 바로 찍으면 그 아래가 아니라 막이 덮인 화면이 찍힌다.
        # 윈도우가 가려졌던 자리를 다시 그릴 틈을 줘야 한다.
        self.root.update_idletasks()
        self.root.update()
        time.sleep(SETTLE)
        self.root.update()

        # 이미 윈도우 좌표다. 여기에 무엇을 더하면 안 된다.
        return screen_compare.capture(*self.picked)


def _as_png(shot: screen_compare.Shot) -> str:
    """tkinter 가 바로 읽는 그림 자료로. 회색 그대로 둬야 빨강이 눈에 띈다.

    PPM 은 안 된다 — Tk 는 base64 로 넘긴 PPM 을 못 알아본다(PNG 는
    읽는다). 회색 한 겹짜리로 만들면 자료도 3분의 1 로 준다. 만드는 데
    쓰는 zlib 은 표준 라이브러리다.
    """
    rows = bytearray()
    for y in range(shot.height):
        rows.append(0)               # 줄마다 '거르기 없음' 표시
        rows += shot.grey[y * shot.width:(y + 1) * shot.width]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff))

    png = (bytes([137, 80, 78, 71, 13, 10, 26, 10])
           + chunk(b"IHDR", struct.pack(">IIBBBBB", shot.width, shot.height,
                                        8, 0, 0, 0, 0))      # 8비트 회색 한 겹
           + chunk(b"IDAT", zlib.compress(bytes(rows), 1))   # 한 번 보고 마니 빠르게
           + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


class _Result:
    """수정본 그림 위에 달라진 자리를 표시해 보여 준다."""

    def __init__(self, root: tk.Misc, shot: screen_compare.Shot, changes: list):
        marks = [c for c in changes if c.state != screen_compare.SAME]

        self.window = tk.Toplevel(root)
        self.window.title("결재 전후 비교")
        self.window.attributes("-topmost", True)

        tk.Label(self.window, anchor="w", font=("맑은 고딕", 11),
                 padx=12, pady=8,
                 text=self._headline(marks)).pack(fill="x")

        view = (min(shot.width, MAX_VIEW[0]), min(shot.height, MAX_VIEW[1]))
        holder = tk.Frame(self.window)
        holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(holder, width=view[0], height=view[1],
                           highlightthickness=0, bg="white",
                           scrollregion=(0, 0, shot.width, shot.height))
        # 실제로 찍은 화면은 창보다 넓고 높다. 가로도 움직일 수 있어야 한다 —
        # 세로만 있으면 오른쪽에 있는 표시를 영영 못 본다.
        down = tk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        across = tk.Scrollbar(holder, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        down.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        canvas.grid(row=0, column=0, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)

        # PhotoImage 는 참조가 끊기면 그림이 사라진다. 창에 붙들어 둔다.
        self.image = tk.PhotoImage(data=_as_png(shot))
        canvas.create_image(0, 0, image=self.image, anchor="nw")
        for change in marks:
            self._draw(canvas, change, shot.width)

        tk.Button(self.window, text="닫기",
                  command=self.window.destroy).pack(pady=8)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())

    @staticmethod
    def _headline(marks: list) -> str:
        if not marks:
            return "달라진 곳을 찾지 못했습니다. 두 화면이 같습니다."
        added = sum(1 for c in marks if c.state == screen_compare.ADDED)
        removed = sum(1 for c in marks if c.state == screen_compare.REMOVED)
        edited = len(marks) - added - removed
        parts = []
        if edited:
            parts.append(f"고쳐진 곳 {edited}")
        if added:
            parts.append(f"새로 들어온 줄 {added}")
        if removed:
            parts.append(f"빠진 줄 {removed}")
        return "달라진 곳: " + ", ".join(parts) + "   (빨간 상자)"

    @staticmethod
    def _draw(canvas: tk.Canvas, change, width: int) -> None:
        top = max(0, change.top - MARGIN)
        bottom = change.bottom + MARGIN
        if change.state == screen_compare.REMOVED:
            # 빠진 줄은 수정본에 자리가 없다. 그 높이에 선만 그어 알린다.
            canvas.create_line(0, top, width, top, fill="#c81e1e",
                               width=2, dash=(6, 4))
            return
        for start, end in change.spans:
            canvas.create_rectangle(max(0, start - MARGIN), top,
                                    end + MARGIN, bottom,
                                    outline="#c81e1e", width=2)


def run(root: tk.Misc, warn, hide=None, show=None) -> None:
    """원본 → 수정본 순서로 고르게 하고 결과를 띄운다.

    `warn(제목, 내용)` 은 알릴 때 부르는 함수. 창을 띄우는 방식을 위젯이
    정하도록 넘겨받는다.

    `hide` / `show` 는 고르는 동안 위젯을 감췄다 되돌리는 함수. 위젯은
    항상 위에 떠 있어서, 그대로 두면 화면을 찍을 때 **자기가 같이 찍힌다.**
    실사용에서 바로 그렇게 됐다. 감추는 방법은 위젯이 정하도록 넘겨받는다
    — 투명도·항상 위 설정을 되돌려 놓는 일은 위젯의 몫이다.
    """
    try:
        if hide:
            hide()
        try:
            before = _Picker(root, "① 원본(기안한 것) 쪽을 끌어 주세요").run()
            if before is None:
                return
            after = _Picker(root, "② 수정본(결재된 것) 쪽을 끌어 주세요").run()
            if after is None:
                return
        finally:
            if show:
                show()
        # 종이만 남기고 견준다. 창 부속(상태표시줄·스크롤바)이 빠지고,
        # 드래그 범위가 서로 달라도 같은 자리가 잘려 나온다.
        before, after = screen_compare.prepare(before, after)
        changes = screen_compare.compare(before, after)
    except screen_compare.ScreenError as exc:
        warn("결재 전후 비교", str(exc))
        return
    _Result(root, after, changes)

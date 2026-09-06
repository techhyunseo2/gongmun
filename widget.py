"""공문 정리함 — 바탕화면 위젯.

테두리 없는 작은 창을 띄워 놓고 기한이 가까운 공문만 보여 준다.
같은 프로세스 안에서 API 서버도 돌기 때문에, 자세히 보기를 누르면
브라우저에 전체 화면이 바로 열린다.

  python widget.py                  위젯을 띄운다
  python widget.py --folder "경로"   폴더를 지정한다

머리말을 끌면 창이 움직이고, 위치는 다음 실행 때 그대로 복원된다.
머리말 아이콘으로 항상 위·결재 전후 비교·커스텀 클립보드를 켜고, 바로
아래 슬라이더로 투명도를 맞춘다. 오른쪽 버튼에는 업데이트 확인만 남는다.
"""

from __future__ import annotations

import argparse
import ctypes
import random
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import (BASE_DIR, DB_PATH, PORT, VERSION, Handler, ask_to_surface,  # noqa: E402
                 fold_groups, load_config, open_in_os, raise_running_widget,
                 resolve_folder, resolve_inbox, running_port, save_config,
                 start_server)
from classify import CATEGORIES, days_left  # noqa: E402
from store import Store  # noqa: E402
import changelog  # noqa: E402
import updater  # noqa: E402

PAPER = "#DDE1DC"
CARD = "#FBFBF8"
INK = "#16201B"
SOFT = "#5C685F"
RULE = "#C3CAC3"
SEAL = "#A6301F"
SLATE = "#3A5560"
MOSS = "#3C5A46"          # 결재 전후 비교 아이콘의 '원본' 쪽
GLOW = "#FFFFFF"          # 마우스를 올렸을 때 살짝 더 밝아지는 바탕

CAT_COLOR = {
    "submit": "#A6301F", "event": "#3A5560", "apply": "#8A6A1F",
    "distribute": "#3C5A46", "notice": "#7B8480", "other": "#A6ADA7",
}

WIDTH, ROWS = 320, 7
REFRESH_MINUTES = 10        # 폴더에 새 파일이 들어왔는지 훑는 주기 (디스크를 읽는다)
LIVE_SECONDS = 2.5          # 브라우저에서 고친 게 있는지 보는 주기 (번호만 본다)
UPDATE_GAP_HOURS = 4        # 이만큼 지나면 새 버전이 있는지 다시 본다
OPACITY_MIN = 0.5           # 더 흐려지면 위젯을 찾지 못해 되돌릴 길이 없어진다
CLIP_MAX = 12               # 담아 둔 글은 이만큼만 두고 오래된 것부터 밀어낸다
GLYPH_MAX = 40              # 고정해 둘 특수문자·문구 개수 상한
TOOL_MAX = 18              # 도구 서랍에 등록해 둘 프로그램·폴더·파일 개수 상한

# 결재 전후 비교 서랍의 안내 문구. 사용자가 그대로 정한 것 — 다듬지 말 것.
COMPARE_NOTE = ("결재 창의 '이력보기' 탭에서 활용 가능하며 픽셀 단위로 결재 "
                "문서 전후를 비교하여 줍니다. 결재 문서의 내용은 읽지 못하며 "
                "픽셀이 변경된 부분만 감지하기 때문에 오차가 있을 수 있습니다.")


class Widget:
    def __init__(self, store: Store, folder: Path, port: int, base: Path | None = None):
        self.store = store
        self.folder = folder
        self.base = base or folder.parent
        self.port = port
        self.config = load_config()
        self.collapsed = False
        self.scanning = False
        self._seen_rev = -1     # 마지막으로 반영한 저장소 번호
        self._drawn = None      # 마지막으로 그린 내용. 같으면 다시 그리지 않는다
        self._icon_cache = {}   # 도구 서랍이 뽑아 온 실제 아이콘 (경로별로 한 번만)

        self.root = tk.Tk()
        self.root.title("공문 정리함")
        self.root.overrideredirect(True)
        self.root.configure(bg=RULE)
        self.root.attributes("-topmost", bool(self.config.get("on_top", True)))
        self.root.attributes("-alpha", clamp_opacity(self.config.get("opacity", 0.96)))

        self._pick_fonts()
        self._set_window_icon()
        self._build()
        self._place()
        self._bind()
        self._render_drawers()
        self._draw_opacity_slider()
        self._claim_taskbar_button()

        self.refresh(scan=True)
        self._tick()
        self._seen_calls = Handler.show_calls
        self._live_tick()
        self._watch_for_calls()
        # 같은 학교 여러 대가 한꺼번에 몰리지 않도록 조금 흩어 놓는다
        self.root.after(random.randint(5, 90) * 1000, self._maybe_check_update)

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

        # 머리말 — 빈 자리를 끌면 창이 움직인다. 아이콘은 저마다 동작이 있다.
        self.head = tk.Frame(outer, bg=PAPER)
        self.head.pack(fill="x", padx=12, pady=(9, 2))
        tk.Label(self.head, text="공문 정리함", font=self.f_title, bg=PAPER, fg=INK).pack(side="left")

        self._tip = None
        self._tip_after = None
        self._no_drag = set()

        self.btn_close = self._text_button("✕", "닫기", self.quit)
        self.btn_close.pack(side="right", padx=(6, 0))
        self.btn_fold = self._text_button("—", "접기", self.toggle_fold)
        self.btn_fold.pack(side="right", padx=(2, 0))
        self.btn_quick = self._icon_button(self._draw_clip, "커스텀 클립보드",
                                           self._toggle_quick,
                                           active=bool(self.config.get("quickbar_open", False)))
        self.btn_quick.pack(side="right", padx=(6, 0))
        self.btn_tools = self._icon_button(self._draw_tools, "도구 서랍",
                                           self._toggle_tools,
                                           active=bool(self.config.get("tools_open", False)))
        self.btn_tools.pack(side="right", padx=(6, 0))
        self.btn_compare = self._icon_button(self._draw_compare, "결재 전후 비교",
                                             self._toggle_compare,
                                             active=bool(self.config.get("compare_open", False)))
        self.btn_compare.pack(side="right", padx=(6, 0))
        self.btn_top = self._icon_button(self._draw_ontop, "항상 위에 두기",
                                         self._toggle_top,
                                         active=bool(self.config.get("on_top", True)))
        self.btn_top.pack(side="right", padx=(6, 0))

        # 접으면 머리말만 남기고 이 아래가 통째로 사라진다
        self.shell = tk.Frame(outer, bg=PAPER)
        self.shell.pack(fill="both", expand=True)

        # 한 줄에: 투명도 슬라이더(절반) + 남은 자리를 폴더 경로 박스가 채운다.
        # 폴더 박스는 눌러서 경로 확인·열기·바꾸기를 할 수 있고, 칸에 안
        # 들어가면 말줄임표로 자른다.
        self.opacity_row = tk.Frame(self.shell, bg=PAPER)
        self.opacity_row.pack(fill="x", padx=12, pady=(3, 5))
        tk.Label(self.opacity_row, text="투명도", font=self.f_small,
                 bg=PAPER, fg=SOFT).pack(side="left", padx=(0, 6))
        # 슬라이더는 작게 두고(대충 맞추는 용도), 남은 폭은 폴더 박스가 쓴다.
        self.opacity_slider = tk.Canvas(self.opacity_row, height=22, width=40,
                                        bg=PAPER, highlightthickness=0, cursor="hand2")
        self.opacity_slider.pack(side="left")
        self._wire_opacity_slider()

        self.folderchip = tk.Canvas(self.opacity_row, height=22, bg=PAPER,
                                    highlightthickness=0, cursor="hand2")
        self.folderchip.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._folder_text = ""
        self._folder_hover = False
        self.folderchip.bind("<Button-1>", lambda e: self.show_folder())
        self.folderchip.bind("<Enter>", lambda e: self._paint_folder(hover=True))
        self.folderchip.bind("<Leave>", lambda e: self._paint_folder(hover=False))
        self.folderchip.bind("<Configure>", lambda e: self._paint_folder())
        self._paint_folder()

        # "처리할 것 N건" 은 공문 목록 바로 위에 붙인다.
        self.summary = tk.Label(self.shell, text="읽는 중", font=self.f_head,
                                bg=PAPER, fg=SOFT, anchor="w")
        self.summary.pack(fill="x", padx=12, pady=(0, 3))

        self.body = tk.Frame(self.shell, bg=PAPER)
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

        # 커스텀 클립보드 — 복사한 글을 담아 두고, 자주 쓰는 특수문자를 고정한다.
        # foot 아래에 서랍처럼 붙는다. 열림 여부는 기억해 둔다.
        self.quick = tk.Frame(self.body, bg=PAPER)
        self._quick_open = bool(self.config.get("quickbar_open", False))

        # 도구 서랍 — 등록해 둔 프로그램·폴더·파일·웹 주소를 눌러 연다.
        # 커스텀 클립보드와 같은 방식으로 열고 닫는다(_render_drawers 가 관리).
        self.tools = tk.Frame(self.body, bg=PAPER)
        self._tools_open = bool(self.config.get("tools_open", False))

        # 결재 전후 비교 — 안내 문구와, 누르면 비교가 시작되는 단추가 든 서랍.
        self.compare = tk.Frame(self.body, bg=PAPER)
        self._compare_open = bool(self.config.get("compare_open", False))

    # ------------------------------------------------------- 머리말 아이콘

    def _text_button(self, text, tip, command):
        """— 나 ✕ 처럼 글자 하나로 된 머리말 단추. 설명풍선이 붙는다."""
        label = tk.Label(self.head, text=text, font=self.f_head, bg=PAPER,
                         fg=SOFT, cursor="hand2")
        label.bind("<Button-1>", lambda e: command())
        label.bind("<Enter>", lambda e: (label.config(fg=INK),
                                         self._tip_schedule(label, tip)))
        label.bind("<Leave>", lambda e: (label.config(fg=SOFT), self._tip_cancel()))
        self._no_drag.add(label)
        return label

    def _icon_button(self, draw, tip, command, active=False):
        """Canvas 로 직접 그리는 머리말 아이콘. active 면 눌린 듯 진하게."""
        icon = tk.Canvas(self.head, width=18, height=18, bg=PAPER,
                         highlightthickness=0, cursor="hand2")
        icon._draw, icon._active = draw, active
        draw(icon, active)
        icon.bind("<Button-1>", lambda e: command())
        icon.bind("<Enter>", lambda e: (draw(icon, True),
                                        self._tip_schedule(icon, tip)))
        icon.bind("<Leave>", lambda e: (draw(icon, icon._active), self._tip_cancel()))
        self._no_drag.add(icon)
        return icon

    def _set_icon_active(self, icon, active):
        icon._active = active
        icon._draw(icon, active)

    def _draw_ontop(self, c, on):
        """페이지 여러 장을 겹쳐 놓은 모양. 맨 앞 장이 차 있으면 '맨 앞에
        고정'(항상 위에 두기 켜짐), 비어 있으면 꺼짐."""
        c.delete("all")
        line = INK if on else SOFT
        for x, y in ((1, 1), (4, 3)):                 # 뒤에 깔린 두 장
            c.create_rectangle(x, y, x + 9, y + 11, outline=line, width=1.2,
                               fill=PAPER)
        c.create_rectangle(7, 6, 16, 17, outline=line, width=1.5,
                           fill=(SLATE if on else PAPER))   # 맨 앞 장

    def _draw_compare(self, c, hover):
        """가운데가 갈린 직사각형. 왼쪽 원본(초록), 오른쪽 수정(빨강)."""
        c.delete("all")
        c.create_rectangle(2, 3, 9, 16, fill=MOSS, width=0)
        c.create_rectangle(9, 3, 16, 16, fill=SEAL, width=0)
        c.create_line(9, 2, 9, 17, fill=PAPER, width=2)
        c.create_rectangle(2, 3, 16, 16, outline=(INK if hover else SOFT), width=1.4)

    def _draw_clip(self, c, on):
        """집게 달린 클립보드."""
        c.delete("all")
        line = INK if on else SOFT
        c.create_rectangle(3, 4, 15, 17, outline=line, width=1.4)
        c.create_rectangle(6, 2, 12, 5, outline=line, width=1.4, fill=PAPER)
        c.create_line(6, 9, 12, 9, fill=line, width=1.2)
        c.create_line(6, 12, 11, 12, fill=line, width=1.2)

    def _draw_tools(self, c, on):
        """3×3 칸이 격자로 놓인 모양(구글 앱 메뉴처럼). 켜지면 칸이 찬다."""
        c.delete("all")
        fill = SLATE if on else SOFT
        for r in range(3):
            for col in range(3):
                x, y = 2 + col * 6, 2 + r * 6
                c.create_rectangle(x, y, x + 4, y + 4, fill=fill, width=0)

    def _draw_crop(self, c, on):
        """사진 편집 프로그램의 '자르기' 표시 — ㄱ자 두 개가 어긋나게 겹친 모양."""
        c.delete("all")
        line = INK if on else SOFT
        c.create_line(3, 6, 15, 6, fill=line, width=1.6)      # 위 걸침
        c.create_line(6, 3, 6, 15, fill=line, width=1.6)      # 왼쪽 걸침
        c.create_line(3, 12, 12, 12, fill=line, width=1.6)    # 아래 걸침
        c.create_line(12, 6, 12, 16, fill=line, width=1.6)    # 오른쪽 걸침

    # -------------------------------------------------------- 설명풍선

    def _tip_schedule(self, widget, text):
        self._tip_cancel()
        self._tip_after = self.root.after(350, lambda: self._tip_show(widget, text))

    def _tip_cancel(self):
        if self._tip_after is not None:
            try:
                self.root.after_cancel(self._tip_after)
            except (ValueError, tk.TclError):
                pass
            self._tip_after = None
        self._tip_hide()

    def _tip_show(self, widget, text):
        self._tip_hide()
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=text, font=self.f_small, bg=INK, fg=CARD,
                 padx=6, pady=2).pack()
        tip.update_idletasks()
        x = widget.winfo_rootx() + widget.winfo_width() // 2 - tip.winfo_width() // 2
        y = widget.winfo_rooty() + widget.winfo_height() + 5
        tip.geometry(f"+{x}+{y}")
        self._tip = tip

    def _tip_hide(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None

    # -------------------------------------------------------- 투명도 슬라이더

    def _wire_opacity_slider(self):
        s = self.opacity_slider
        s.bind("<Configure>", lambda e: self._draw_opacity_slider())
        s.bind("<Button-1>", lambda e: self._drag_opacity(e, done=False))
        s.bind("<B1-Motion>", lambda e: self._drag_opacity(e, done=False))
        s.bind("<ButtonRelease-1>", lambda e: self._drag_opacity(e, done=True))
        s.bind("<Enter>", lambda e: self._tip_schedule(
            s, "최대 50%까지 투명도를 조절할 수 있습니다"))
        s.bind("<Leave>", lambda e: self._tip_cancel())

    def _slider_span(self):
        w = self.opacity_slider.winfo_width()
        if w <= 10:                       # 아직 배치 전이면 지정 폭을 쓴다
            w = int(self.opacity_slider["width"])
        return 8, max(9, w - 8)          # 조작점 반지름만큼 안쪽으로

    def _draw_opacity_slider(self):
        s = self.opacity_slider
        s.delete("all")
        left, right = self._slider_span()
        mid = (int(s["height"]) or 22) // 2
        value = clamp_opacity(self.config.get("opacity", 0.96))
        frac = (value - OPACITY_MIN) / (1.0 - OPACITY_MIN)
        knob = left + frac * (right - left)
        s.create_line(left, mid, right, mid, fill=RULE, width=3, capstyle="round")
        s.create_line(left, mid, knob, mid, fill=SLATE, width=3, capstyle="round")
        s.create_oval(knob - 6, mid - 6, knob + 6, mid + 6, fill=CARD,
                      outline=SLATE, width=1.6)

    def _drag_opacity(self, event, done):
        left, right = self._slider_span()
        frac = min(1.0, max(0.0, (event.x - left) / (right - left)))
        value = OPACITY_MIN + frac * (1.0 - OPACITY_MIN)
        # 끄는 동안에는 화면만, 손을 뗄 때 한 번만 저장한다.
        self._set_opacity(value, remember=done)
        if not done:
            self.config["opacity"] = clamp_opacity(value)   # 슬라이더가 따라오도록
        self._draw_opacity_slider()

    # ------------------------------------------------------- 커스텀 클립보드

    def _render_drawers(self):
        """머리말 아래 세 서랍(커스텀 클립보드·도구·결재 비교)을 정해진
        순서로 다시 깐다.

        매번 전부 떼었다가 열린 것만 다시 붙인다. 그래야 위 서랍을 닫으면
        아래 서랍이 곧바로 그 자리로 올라오고, 닫힌 서랍의 빈 자리도 남지
        않는다.
        """
        for drawer in (self.quick, self.tools, self.compare):
            drawer.pack_forget()
        if not self.collapsed:
            if self._quick_open:
                self._build_quick()
                self.quick.pack(fill="x")
            if self._tools_open:
                self._build_tools()
                self.tools.pack(fill="x")
            if self._compare_open:
                self._build_compare()
                self.compare.pack(fill="x")
        self._set_icon_active(self.btn_quick, self._quick_open)
        self._set_icon_active(self.btn_tools, self._tools_open)
        self._set_icon_active(self.btn_compare, self._compare_open)
        self._fit_height()

    def _toggle_quick(self):
        self._quick_open = not self._quick_open
        self.config["quickbar_open"] = self._quick_open
        save_config(self.config)
        self._render_drawers()

    def _build_quick(self):
        q = self.quick
        for child in q.winfo_children():
            child.destroy()
        tk.Frame(q, bg=RULE, height=1).pack(fill="x", padx=8, pady=(2, 7))

        head = tk.Frame(q, bg=PAPER)
        head.pack(fill="x", padx=12)
        tk.Label(head, text="자주 쓰는 문자", font=self.f_small, bg=PAPER,
                 fg=SOFT).pack(side="left")
        self._foot_button(head, "편집", lambda e=None: self._edit_glyphs()).pack(side="right")

        glyphs = list(self.config.get("glyphs") or [])
        grid = tk.Frame(q, bg=PAPER)
        grid.pack(fill="x", padx=12, pady=(5, 0))
        if glyphs:
            for i, text in enumerate(glyphs):
                cell = tk.Label(grid, text=_one_line(text, 6), font=self.f_row, bg=CARD,
                                fg=INK, cursor="hand2", padx=7, pady=3,
                                highlightbackground=RULE, highlightthickness=1)
                cell.grid(row=i // 6, column=i % 6, padx=(0, 4), pady=2, sticky="w")
                cell.bind("<Button-1>",
                          lambda e, t=text, w=cell: self._copy_text(t, w, _one_line(t, 6)))
                cell.bind("<Enter>", lambda e, w=cell: w.config(highlightbackground=INK))
                cell.bind("<Leave>", lambda e, w=cell: w.config(highlightbackground=RULE))
        else:
            tk.Label(grid, text="편집을 눌러 ○ ※ ℃ 처럼 자주 쓰는 문자를 넣어 두세요",
                     font=self.f_small, bg=PAPER, fg=SOFT, anchor="w",
                     wraplength=270, justify="left").pack(fill="x")

        tk.Label(q, text="담아 둔 글", font=self.f_small, bg=PAPER, fg=SOFT,
                 anchor="w").pack(fill="x", padx=12, pady=(9, 2))
        clips = list(self.config.get("clips") or [])
        if clips:
            box = tk.Frame(q, bg=PAPER)
            box.pack(fill="x", padx=12)
            for i, text in enumerate(clips):
                line = tk.Frame(box, bg=CARD, highlightbackground=RULE, highlightthickness=1)
                line.pack(fill="x", pady=2)
                label = tk.Label(line, text=_one_line(text, 30), font=self.f_small, bg=CARD,
                                 fg=INK, anchor="w", cursor="hand2")
                label.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=4)
                label.bind("<Button-1>",
                           lambda e, t=text, w=label: self._copy_text(t, w, _one_line(t, 30)))
                drop = tk.Label(line, text="✕", font=self.f_small, bg=CARD, fg=SOFT,
                                cursor="hand2", padx=7)
                drop.pack(side="right")
                drop.bind("<Button-1>", lambda e, t=text: self._forget_clip(t))
                # 순서를 손으로 바꾼다. 위아래 화살표로 한 칸씩 옮긴다.
                down = tk.Label(line, text="▾", font=self.f_small, bg=CARD, fg=SOFT,
                                cursor="hand2", padx=2)
                down.pack(side="right")
                down.bind("<Button-1>", lambda e, t=text: self._move_clip(t, 1))
                up = tk.Label(line, text="▴", font=self.f_small, bg=CARD, fg=SOFT,
                              cursor="hand2", padx=2)
                up.pack(side="right")
                up.bind("<Button-1>", lambda e, t=text: self._move_clip(t, -1))
        else:
            tk.Label(q, text="다른 곳에서 복사한 뒤 아래 단추를 누르면 여기 담깁니다",
                     font=self.f_small, bg=PAPER, fg=SOFT, anchor="w",
                     wraplength=290, justify="left").pack(fill="x", padx=12)

        bar = tk.Frame(q, bg=PAPER)
        bar.pack(fill="x", padx=12, pady=(7, 10))
        self.btn_stash = self._foot_button(bar, "지금 복사한 것 담기",
                                           lambda e=None: self._stash_clipboard())
        self.btn_stash.pack(side="left")
        if clips:
            self._foot_button(bar, "비우기", lambda e=None: self._clear_clips()).pack(side="right")

    def _copy_text(self, text: str, widget=None, restore: str | None = None):
        """문자나 담아 둔 글을 클립보드에 넣는다. 붙여넣기는 사용자가 한다.

        위젯이 다른 앱에 직접 글자를 밀어 넣는 것은 창마다 동작이 달라
        미덥지 않다. 클립보드에 얹어 두는 것이 어디서든 확실하다.
        """
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
        except tk.TclError:
            return
        if widget is not None:
            widget.config(text="복사됨", fg=SEAL)
            widget.after(900, lambda: self._restore_label(widget, restore))

    @staticmethod
    def _restore_label(widget, text):
        try:
            widget.config(text=text, fg=INK)
        except tk.TclError:
            pass

    def _stash_clipboard(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        text = (text or "").strip()
        if not text:
            self.btn_stash.config(text="복사한 글이 없습니다")
            self.btn_stash.after(1300,
                                 lambda: self.btn_stash.config(text="지금 복사한 것 담기"))
            return
        clips = [c for c in (self.config.get("clips") or []) if c != text]
        clips.insert(0, text)
        del clips[CLIP_MAX:]
        self.config["clips"] = clips
        save_config(self.config)
        self._render_drawers()

    def _forget_clip(self, text: str):
        clips = [c for c in (self.config.get("clips") or []) if c != text]
        self.config["clips"] = clips
        save_config(self.config)
        self._render_drawers()

    def _move_clip(self, text: str, delta: int):
        """담아 둔 글을 한 칸 위나 아래로 옮긴다."""
        clips = list(self.config.get("clips") or [])
        if text not in clips:
            return
        here = clips.index(text)
        there = max(0, min(len(clips) - 1, here + delta))
        if here == there:
            return
        clips.insert(there, clips.pop(here))
        self.config["clips"] = clips
        save_config(self.config)
        self._render_drawers()

    def _clear_clips(self):
        self.config["clips"] = []
        save_config(self.config)
        self._render_drawers()

    def _edit_glyphs(self):
        """자주 쓰는 문자를 한 줄에 하나씩 적어 두는 작은 창."""
        window = tk.Toplevel(self.root)
        window.title("자주 쓰는 문자")
        window.configure(bg=PAPER)
        window.resizable(False, False)
        window.transient(self.root)

        frame = tk.Frame(window, bg=PAPER)
        frame.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(frame, text="한 줄에 하나씩 적어 주세요. 한 글자든 짧은 문구든 됩니다.\n"
                             "줄 순서가 곧 배치 순서입니다. 줄을 잘라 옮기면 자리가 바뀝니다.",
                 font=self.f_small, bg=PAPER, fg=SOFT, anchor="w",
                 wraplength=300, justify="left").pack(fill="x", pady=(0, 8))
        box = tk.Text(frame, height=10, width=30, font=self.f_row, wrap="none",
                      bg=CARD, fg=INK, relief="flat", highlightthickness=1,
                      highlightbackground=RULE, padx=8, pady=6)
        box.insert("1.0", "\n".join(self.config.get("glyphs") or []))
        box.pack(fill="both")

        def save():
            lines = [ln.strip() for ln in box.get("1.0", "end").splitlines()]
            self.config["glyphs"] = [ln for ln in lines if ln][:GLYPH_MAX]
            save_config(self.config)
            window.destroy()
            self._render_drawers()

        buttons = tk.Frame(frame, bg=PAPER)
        buttons.pack(fill="x", pady=(12, 0))
        self._foot_button(buttons, "저장", lambda e=None: save()).pack(side="right")
        self._foot_button(buttons, "취소",
                          lambda e=None: window.destroy()).pack(side="right", padx=(0, 6))

        window.update_idletasks()
        window.geometry(f"+{self.root.winfo_x() - 40}+{self.root.winfo_y() + 60}")
        window.grab_set()
        box.focus_set()

    # ----------------------------------------------------------- 도구 서랍

    def _toggle_tools(self):
        self._tools_open = not self._tools_open
        self.config["tools_open"] = self._tools_open
        save_config(self.config)
        self._render_drawers()

    def _build_tools(self):
        t = self.tools
        for child in t.winfo_children():
            child.destroy()
        tk.Frame(t, bg=RULE, height=1).pack(fill="x", padx=8, pady=(2, 7))

        head = tk.Frame(t, bg=PAPER)
        head.pack(fill="x", padx=12)
        tk.Label(head, text="도구 서랍", font=self.f_small, bg=PAPER,
                 fg=SOFT).pack(side="left")
        self._foot_button(head, "편집",
                          lambda e=None: self._edit_tools()).pack(side="right")

        tools = list(self.config.get("tools") or [])
        if tools:
            grid = tk.Frame(t, bg=PAPER)
            grid.pack(fill="x", padx=12, pady=(6, 10))
            for i, tool in enumerate(tools):
                self._tool_tile(grid, tool, i)
            for col in range(3):
                grid.columnconfigure(col, weight=1, uniform="tool")
        else:
            tk.Label(t, text="편집을 눌러 자주 여는 프로그램·폴더·파일·웹 주소를 "
                             "등록해 두세요. 누르면 바로 열립니다.",
                     font=self.f_small, bg=PAPER, fg=SOFT, anchor="w",
                     wraplength=290, justify="left").pack(fill="x", padx=12, pady=(0, 10))

    def _tool_tile(self, grid, tool, i):
        name = tool.get("name") or tool.get("path", "")
        path = tool.get("path", "")
        custom = (tool.get("icon") or "").strip()
        cell = tk.Frame(grid, bg=CARD, cursor="hand2",
                        highlightbackground=RULE, highlightthickness=1)
        cell.grid(row=i // 3, column=i % 3, padx=(0, 4), pady=2, sticky="nsew")

        # 사용자가 아이콘(이모지)을 넣지 않았으면 그 프로그램·폴더의 실제
        # 아이콘을 뽑아 쓴다. 그것도 못 얻으면 별명 첫 글자로 떨어진다.
        image = None if custom else self._tool_icon_image(path, 20)
        if image is not None:
            top = tk.Label(cell, image=image, bg=CARD)
            top.image = image                      # 참조가 사라지면 그림도 사라진다
        else:
            top = tk.Label(cell, text=(custom or name[:1] or "▸"),
                           font=self.f_dday, bg=CARD, fg=INK)
        top.pack(pady=(6, 0))
        tk.Label(cell, text=_one_line(name, 8), font=self.f_small, bg=CARD,
                 fg=SOFT).pack(pady=(0, 6))
        for w in (cell, *cell.winfo_children()):
            w.bind("<Button-1>", lambda e, p=path, c=cell: self._open_tool(p, c))
            w.bind("<Enter>", lambda e, c=cell: self._tool_hi(c, True))
            w.bind("<Leave>", lambda e, c=cell: self._tool_hi(c, False))

    @staticmethod
    def _tool_hi(cell, on):
        try:
            cell.config(highlightbackground=INK if on else RULE)
        except tk.TclError:
            pass

    def _tool_icon_image(self, path: str, px: int):
        """등록한 대상(프로그램·폴더·파일)의 실제 아이콘을 tk 그림으로.
        윈도우가 아니거나 아이콘을 못 뽑으면 None — 부르는 쪽이 글자로 뗀다."""
        target = (path or "").strip().strip('"').strip()
        if sys.platform != "win32" or not target \
                or target.startswith(("http://", "https://")):
            return None
        target = str(Path(target))         # 슬래시를 윈도우식으로 — 셸 API 는 / 를 싫어한다
        key = (target, px)
        if key in self._icon_cache:
            return self._icon_cache[key]
        try:
            image = _win_file_icon(self.root, target, px, CARD)
        except Exception:  # noqa: BLE001 — 아이콘을 못 뽑아도 서랍은 떠야 한다
            image = None
        self._icon_cache[key] = image      # None 도 담아 두면 다시 시도하지 않는다
        return image

    def _open_tool(self, path: str, cell=None):
        """등록해 둔 대상을 연다. 프로그램·폴더·파일은 운영체제에 맡기고,
        웹 주소는 브라우저로 연다. 위젯이 직접 하는 일은 '열기'뿐이다."""
        target = (path or "").strip().strip('"').strip()
        ok = True
        if target.startswith(("http://", "https://")):
            webbrowser.open(target)
        else:
            spot = Path(target)
            if target and spot.exists():
                try:
                    open_in_os(spot)
                except OSError:
                    ok = False
            else:
                ok = False
        if cell is not None and not ok:
            cell.config(highlightbackground=SEAL)
            cell.after(1100, lambda: self._tool_hi(cell, False))

    def _edit_tools(self):
        """도구를 한 줄에 하나씩 — 아이콘·별명·경로. 위아래로 순서를 바꾼다.
        줄 순서가 곧 서랍의 배치 순서다."""
        win = tk.Toplevel(self.root)
        win.title("도구 서랍")
        win.configure(bg=PAPER)
        win.resizable(False, False)
        win.transient(self.root)

        frame = tk.Frame(win, bg=PAPER)
        frame.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(frame,
                 text="자주 여는 프로그램·폴더·파일·웹 주소를 등록하세요. 누르면 바로 열립니다.\n"
                      "아이콘은 이모지 한 글자를 권합니다. 줄 순서가 곧 서랍의 배치 순서입니다.",
                 font=self.f_small, bg=PAPER, fg=SOFT, justify="left",
                 wraplength=390).pack(fill="x", pady=(0, 10))

        rows = tk.Frame(frame, bg=PAPER)
        rows.pack(fill="both")
        self._tool_rows = []

        def relayout():
            for rec in self._tool_rows:
                rec["frame"].pack_forget()
            for rec in self._tool_rows:
                rec["frame"].pack(fill="x", pady=2)

        def move(rec, delta):
            i = self._tool_rows.index(rec)
            j = max(0, min(len(self._tool_rows) - 1, i + delta))
            if i != j:
                self._tool_rows.insert(j, self._tool_rows.pop(i))
                relayout()

        def drop(rec):
            rec["frame"].destroy()
            self._tool_rows.remove(rec)

        def field(parent, width):
            return tk.Entry(parent, width=width, font=self.f_small, bg=CARD, fg=INK,
                            relief="flat", highlightthickness=1, highlightbackground=RULE)

        def add_row(icon="", name="", path=""):
            if len(self._tool_rows) >= TOOL_MAX:
                return
            r = tk.Frame(rows, bg=PAPER)
            e_icon, e_name, e_path = field(r, 3), field(r, 10), field(r, 26)
            e_icon.insert(0, icon)
            e_name.insert(0, name)
            e_path.insert(0, path)
            e_icon.pack(side="left")
            e_name.pack(side="left", padx=(4, 0))
            e_path.pack(side="left", padx=(4, 0))
            rec = {"frame": r, "icon": e_icon, "name": e_name, "path": e_path}
            self._foot_button(r, "찾기",
                              lambda e=None, ep=e_path: self._pick_tool_path(ep)).pack(side="left", padx=(4, 0))
            self._foot_button(r, "▴", lambda e=None, x=rec: move(x, -1), padx=5).pack(side="left", padx=(4, 0))
            self._foot_button(r, "▾", lambda e=None, x=rec: move(x, 1), padx=5).pack(side="left", padx=(2, 0))
            self._foot_button(r, "✕", lambda e=None, x=rec: drop(x), padx=5).pack(side="left", padx=(2, 0))
            self._tool_rows.append(rec)
            relayout()

        for tool in (self.config.get("tools") or []):
            add_row(tool.get("icon", ""), tool.get("name", ""), tool.get("path", ""))
        if not self._tool_rows:
            add_row()

        def save():
            picked = []
            for rec in self._tool_rows:
                spot = rec["path"].get().strip().strip('"').strip()
                if not spot:
                    continue
                name = rec["name"].get().strip() or Path(spot).stem or spot
                picked.append({"name": name[:24], "path": spot,
                               "icon": rec["icon"].get().strip()[:2]})
            self.config["tools"] = picked[:TOOL_MAX]
            save_config(self.config)
            win.destroy()
            self._render_drawers()

        buttons = tk.Frame(frame, bg=PAPER)
        buttons.pack(fill="x", pady=(12, 0))
        self._foot_button(buttons, "저장", lambda e=None: save()).pack(side="right")
        self._foot_button(buttons, "취소",
                          lambda e=None: win.destroy()).pack(side="right", padx=(0, 6))
        self._foot_button(buttons, "＋ 도구 추가",
                          lambda e=None: add_row()).pack(side="left")

        win.update_idletasks()
        win.geometry(f"+{self.root.winfo_x() - 60}+{self.root.winfo_y() + 60}")
        win.grab_set()

    def _pick_tool_path(self, entry):
        from tkinter import filedialog
        chosen = filedialog.askopenfilename(title="열 프로그램·파일 고르기")
        if chosen:
            entry.delete(0, "end")
            entry.insert(0, chosen)

    # ------------------------------------------------------- 결재 전후 비교

    def _toggle_compare(self):
        self._compare_open = not self._compare_open
        self.config["compare_open"] = self._compare_open
        save_config(self.config)
        self._render_drawers()

    def _build_compare(self):
        c = self.compare
        for child in c.winfo_children():
            child.destroy()
        tk.Frame(c, bg=RULE, height=1).pack(fill="x", padx=8, pady=(2, 7))
        tk.Label(c, text="결재 전후 비교", font=self.f_small, bg=PAPER, fg=SOFT,
                 anchor="w").pack(fill="x", padx=12)
        tk.Label(c, text=COMPARE_NOTE, font=self.f_small, bg=PAPER, fg=SOFT,
                 anchor="w", justify="left",
                 wraplength=290).pack(fill="x", padx=12, pady=(3, 8))

        # 사진 편집의 '자르기' 모양 단추 — 누르면 원래 비교 기능이 실행된다
        button = tk.Frame(c, bg=CARD, cursor="hand2",
                          highlightbackground=RULE, highlightthickness=1)
        button.pack(anchor="w", padx=12, pady=(0, 10))
        crop = tk.Canvas(button, width=18, height=18, bg=CARD, highlightthickness=0)
        self._draw_crop(crop, False)
        crop.pack(side="left", padx=(8, 5), pady=5)
        text = tk.Label(button, text="비교 시작", font=self.f_small, bg=CARD, fg=INK)
        text.pack(side="left", padx=(0, 10))
        for w in (button, crop, text):
            w.bind("<Button-1>", lambda e: self.compare_screens())
            w.bind("<Enter>", lambda e: (button.config(highlightbackground=INK),
                                         self._draw_crop(crop, True)))
            w.bind("<Leave>", lambda e: (button.config(highlightbackground=RULE),
                                         self._draw_crop(crop, False)))

    def _paint_folder(self, hover: bool | None = None):
        """폴더 위치를 라운드 박스에 그린다. 눌러서 열 수 있다는 뜻으로,
        마우스를 올리면 바탕이 살짝 밝아진다."""
        if hover is not None:
            self._folder_hover = hover
        parts = self.folder.parts
        short = " › ".join(parts[-2:]) if len(parts) >= 2 else str(self.folder)

        c = self.folderchip
        c.delete("all")
        w = c.winfo_width()
        if w <= 10:                       # 배치 전
            w = WIDTH - 24 - 34 - 6 - 40 - 8
        fill = GLOW if self._folder_hover else CARD
        outline = SOFT if self._folder_hover else RULE
        _round_rect(c, 1, 1, w - 2, 21, 8, fill=fill, outline=outline, width=1)
        # 칸 폭에 맞춰 실제 픽셀로 재서 넘치면 말줄임표로 자른다
        self._folder_text = _fit_text("폴더  " + short, self.f_small, w - 22)
        c.create_text(11, 11, text=self._folder_text, anchor="w",
                      font=self.f_small, fill=INK)

    def show_folder(self):
        """지금 읽고 있는 폴더를 보여 주고, 원하면 바꾸게 한다."""
        window = tk.Toplevel(self.root)
        window.title("공문 폴더")
        window.configure(bg=PAPER)
        window.resizable(False, False)
        window.transient(self.root)

        frame = tk.Frame(window, bg=PAPER)
        frame.pack(fill="both", expand=True, padx=18, pady=16)

        for label, value in (("공문을 읽는 곳", self.folder), ("업무 폴더", self.base)):
            tk.Label(frame, text=label, font=self.f_small, bg=PAPER, fg=SOFT,
                     anchor="w").pack(fill="x", pady=(6, 2))
            box = tk.Text(frame, height=2, width=46, font=self.f_small, wrap="char",
                          bg=CARD, fg=INK, relief="flat", highlightthickness=1,
                          highlightbackground=RULE, padx=8, pady=6)
            box.insert("1.0", str(value))
            box.config(state="disabled")
            box.pack(fill="x")

        tk.Label(frame, text="월별 폴더는 파일을 옮겨 넣기만 하고 내용은 읽지 않습니다.",
                 font=self.f_small, bg=PAPER, fg=SOFT, anchor="w",
                 wraplength=330, justify="left").pack(fill="x", pady=(10, 0))

        buttons = tk.Frame(frame, bg=PAPER)
        buttons.pack(fill="x", pady=(14, 0))
        for text, command in (("폴더 열기", lambda: open_in_os(self.folder)),
                              ("폴더 바꾸기", lambda: (window.destroy(), self._change_folder())),
                              ("닫기", window.destroy)):
            self._foot_button(buttons, text, lambda e=None, c=command: c()).pack(side="left", padx=(0, 6))

        window.update_idletasks()
        x = self.root.winfo_x() + 20
        y = self.root.winfo_y() + 60
        window.geometry(f"+{x}+{y}")
        window.grab_set()

    def _foot_button(self, parent, text, command, padx=9):
        label = tk.Label(parent, text=text, font=self.f_small, bg=CARD, fg=INK,
                         padx=padx, pady=4, cursor="hand2",
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

    def _set_window_icon(self):
        """작업 표시줄과 Alt+Tab 에 뜰 아이콘을 건다."""
        icon = BASE_DIR / "icon.ico"
        if not icon.exists():
            return
        try:
            self.root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass

    def _claim_taskbar_button(self):
        """테두리 없는 창이라도 작업 표시줄에 아이콘이 뜨게 한다.

        윈도우는 팝업 창을 작업 표시줄에서 빼는데, 확장 스타일에
        WS_EX_APPWINDOW 를 걸어 두면 도로 넣어 준다. 작업 표시줄은 창이
        새로 보일 때만 다시 살피므로, 스타일을 바꾼 뒤 잠깐 숨겼다 띄운다.

        이 아이콘이 있으면 바탕화면 보기로 가려지거나 다른 창에 묻혀도
        작업 표시줄이나 Alt+Tab 으로 곧바로 되부를 수 있다. 밖에서 창을
        직접 세우는 기존 방법(`raise_running_widget`)은 그대로 둔다 —
        아주 오래된 판을 되살릴 때 쓰인다.
        """
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            for fn in (get_long, user32.GetParent):
                fn.restype = ctypes.c_void_p
            get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
            set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            user32.GetParent.argtypes = [ctypes.c_void_p]

            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            style = get_long(hwnd, GWL_EXSTYLE) or 0
            set_long(hwnd, GWL_EXSTYLE,
                     (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
        except Exception:  # noqa: BLE001 — 아이콘이 안 떠도 위젯은 돌아야 한다
            return
        # 작업 표시줄이 바뀐 스타일을 알아채도록 한 번 숨겼다 띄운다
        self.root.withdraw()
        self.root.after(12, self._finish_taskbar_button)

    def _finish_taskbar_button(self):
        try:
            self.root.deiconify()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", bool(self.config.get("on_top", True)))
            self.root.attributes("-alpha", clamp_opacity(self.config.get("opacity", 0.96)))
        except tk.TclError:
            pass

    def _fit_height(self):
        """내용을 다 그린 뒤 실제 필요한 높이로 창을 맞춘다."""
        if self.collapsed:
            return
        self.root.update_idletasks()
        height = min(self.root.winfo_reqheight(), self.root.winfo_screenheight() - 120)
        self.root.geometry(f"{WIDTH}x{height}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def _bind(self):
        # 머리말의 빈 자리와 요약줄을 끌면 창이 움직인다. 아이콘 단추는
        # 저마다 동작이 있으므로(_no_drag) 끌기에서 뺀다.
        for target in (self.head, self.summary):
            target.bind("<Button-1>", self._drag_start)
            target.bind("<B1-Motion>", self._drag_move)
            target.bind("<ButtonRelease-1>", self._drag_end)
        for child in self.head.winfo_children():
            if child not in self._no_drag:
                child.bind("<Button-1>", self._drag_start)
                child.bind("<B1-Motion>", self._drag_move)
                child.bind("<ButtonRelease-1>", self._drag_end)
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

    def redraw(self):
        """내용이 그대로여도 다시 그린다.

        요약줄을 "새 버전을 받는 중" 같은 다른 글로 덮어썼다가 되돌릴 때는
        내용이 안 바뀌었어도 그려야 한다.
        """
        self._drawn = None
        self.draw()

    def draw(self):
        today = date.today()
        # 대시보드와 같은 방식으로 센다. 본문과 첨부는 공문 하나로 묶인다.
        everything = fold_groups(self.store.all_docs())
        docs = [d for d in everything if not d["done"]]
        for doc in docs:
            doc["left"] = days_left(doc.get("deadline"), today)
        docs.sort(key=_widget_sort)

        urgent = sum(1 for d in docs if d["left"] is not None and d["left"] <= 3)
        text = f"처리할 것 {len(docs)}건"
        if urgent:
            text += f" · 사흘 안 마감 {urgent}건"

        # 보이는 것이 그대로면 아예 손대지 않는다. 몇 초마다 도는 감시 타이머가
        # 매번 행을 지웠다 다시 만들면 창 높이가 튀고 눈에 거슬리기 때문이다.
        signature = (today, text, len(docs), bool(everything),
                     tuple((d["id"], d["left"], d["category"], d.get("event_date"),
                            bool(d.get("pinned")), d["title"] or d["filename"])
                           for d in docs[:ROWS]))
        if signature == self._drawn:
            return
        self._drawn = signature

        self.summary.config(text=text, fg=SEAL if urgent else SOFT)
        self.stamp.config(text=f"{today.month}월 {today.day}일 기준")

        for child in self.rows.winfo_children():
            child.destroy()

        if not docs:
            message = "처리할 공문이 없습니다" if everything else "폴더에 공문을 넣고\n다시 훑기를 눌러 주세요"
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
        if doc.get("pinned"):
            tk.Label(top, text="고정", font=self.f_small, bg=CARD, fg=SEAL).pack(side="left")
        tk.Label(top, text=CATEGORIES[doc["category"]], font=self.f_small,
                 bg=CARD, fg=SOFT).pack(side="right")

        title = doc["title"] or doc["filename"]
        tk.Label(inner, text=_shorten(title, 24), font=self.f_row, bg=CARD, fg=INK,
                 anchor="w", justify="left").pack(fill="x")

        for target in (frame, inner, top) + tuple(inner.winfo_children()) + tuple(top.winfo_children()):
            target.bind("<Button-1>", self.open_browser)
            target.bind("<Button-3>", lambda e, d=doc: self._row_menu(e, d))
            target.configure(cursor="hand2")

    def _row_menu(self, event, doc):
        """행에서 오른쪽 버튼 — 중요한 공문을 맨 위에 고정하거나 푼다."""
        pinned = bool(doc.get("pinned"))
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="고정 해제" if pinned else "맨 위에 고정",
                         command=lambda: self._set_pinned(doc, not pinned))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"          # 창 전체에 걸린 설정 메뉴가 뒤이어 뜨지 않게 한다

    def _set_pinned(self, doc, pinned: bool):
        for member in doc.get("members") or [{"id": doc["id"]}]:
            self.store.set_pinned(member["id"], pinned)
        self.redraw()

    # ------------------------------------------------------------- 동작

    def open_browser(self, _event=None):
        webbrowser.open(f"http://127.0.0.1:{self.port}/")

    def toggle_fold(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.shell.pack_forget()
            self.root.geometry(f"{WIDTH}x54")
            self.btn_fold.config(text="□")
        else:
            self.shell.pack(fill="both", expand=True)
            self.btn_fold.config(text="—")
            self._render_drawers()
            self._draw_opacity_slider()
            self._fit_height()

    def compare_screens(self):
        """결재 전후 비교. 한글 창 두 개를 띄워 둔 채 자리만 끌면 된다.

        메뉴가 닫힌 뒤에 시작해야 한다. 바로 시작하면 화면을 덮는 막이
        아직 떠 있는 메뉴를 같이 덮어 버린다.
        """
        def start():
            from tkinter import messagebox
            import compare_window
            compare_window.run(self.root, messagebox.showinfo,
                               hide=self._hide_self, show=self._show_self)

        self.root.after(120, start)

    def _hide_self(self):
        """고르는 동안 위젯을 감춘다.

        위젯은 항상 위에 떠 있어서, 그대로 두면 화면을 찍을 때 **자기가
        같이 찍힌다.** 실사용에서 바로 그렇게 나왔다.
        """
        self._was_at = (self.root.winfo_x(), self.root.winfo_y())
        self.root.withdraw()
        self.root.update()

    def _show_self(self):
        """다시 띄운다. `deiconify()` 는 창 꾸밈을 되돌려 놓으므로
        테두리 없애기·항상 위·투명도·자리를 모두 다시 걸어 준다.
        """
        self.root.deiconify()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.config.get("on_top", True)))
        self.root.attributes("-alpha",
                             clamp_opacity(self.config.get("opacity", 0.96)))
        if getattr(self, "_was_at", None):
            self.root.geometry(f"+{self._was_at[0]}+{self._was_at[1]}")
        self.root.update()

    def _menu(self, event):
        # 나머지 기능은 모두 머리말 아이콘·슬라이더·폴더 박스로 옮겼다.
        # 여기에는 손 갈 일 없는 두 가지만 남긴다.
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="업데이트 확인", command=lambda: self.check_update(quiet=False))
        menu.add_command(label=f"버전 {VERSION}", state="disabled")
        menu.tk_popup(event.x_root, event.y_root)

    def _change_folder(self):
        from tkinter import filedialog
        chosen = filedialog.askdirectory(title="공문을 모아 둘 폴더 고르기",
                                         initialdir=str(self.folder))
        if not chosen:
            return
        base, inbox = resolve_inbox(Path(chosen))
        self.base, self.folder = base, inbox
        self.config["folder"] = str(inbox)
        save_config(self.config)
        from app import Handler
        Handler.folder, Handler.base = inbox, base
        self._paint_folder()
        self.refresh(scan=True)

    def _toggle_top(self):
        value = not bool(self.config.get("on_top", True))
        self.config["on_top"] = value
        save_config(self.config)
        self.root.attributes("-topmost", value)
        self._set_icon_active(self.btn_top, value)

    def _set_opacity(self, value: float, remember: bool = True):
        """창을 얼마나 비쳐 보이게 할지 정한다. 0.5 아래로는 내리지 않는다.

        너무 흐려지면 위젯이 어디 있는지 못 찾고 오른쪽 버튼도 누르지 못해
        되돌릴 길이 없어진다.
        """
        value = clamp_opacity(value)
        self.root.attributes("-alpha", value)
        if remember:
            self.config["opacity"] = value
            save_config(self.config)

    def check_update(self, quiet: bool = True) -> None:
        """새 버전이 있는지 알아본다. quiet면 없을 때 아무 말도 하지 않는다."""
        threading.Thread(target=self._check_update_worker, args=(quiet,), daemon=True).start()

    def _check_update_worker(self, quiet: bool) -> None:
        try:
            found = updater.check()
        except updater.UpdateError as exc:
            if not quiet:
                self.root.after(0, lambda: self._update_message(str(exc)))
            return
        self.config["update_checked_at"] = datetime.now().isoformat(timespec="seconds")
        save_config(self.config)
        if found:
            self.root.after(0, lambda: self._offer_update(found))
        elif not quiet:
            self.root.after(0, lambda: self._update_message("최신 버전을 쓰고 계십니다."))

    def _update_message(self, text: str) -> None:
        from tkinter import messagebox
        messagebox.showinfo("공문 정리함", text)

    def _offer_update(self, found: dict) -> None:
        from tkinter import messagebox
        notes = f"\n\n{found['notes']}" if found.get("notes") else ""
        agreed = messagebox.askyesno(
            "공문 정리함",
            f"새 버전 {found['version']} 이 나왔습니다.\n"
            f"지금 쓰시는 것은 {VERSION} 입니다.{notes}\n\n지금 받아서 바꿀까요?",
        )
        if not agreed:
            return
        self.summary.config(text="새 버전을 받는 중", fg=SLATE)
        threading.Thread(target=self._apply_update, args=(found,), daemon=True).start()

    def _apply_update(self, found: dict) -> None:
        try:
            updater.apply(found["url"])
        except updater.UpdateError as exc:
            self.root.after(0, lambda: self._update_message(f"업데이트하지 못했습니다.\n\n{exc}"))
            self.root.after(0, self.redraw)
            return
        self.root.after(0, lambda: self._finish_update(found["version"]))

    def _finish_update(self, version: str) -> None:
        from tkinter import messagebox
        self.config["widget_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        # 다시 뜬 뒤에 무엇이 바뀌었는지 알려 주려고 적어 둔다. 지금 프로세스는
        # 곧 죽으므로 새로 뜨는 쪽이 이 값을 보고 안내창을 띄운다.
        self.config["updated_to"] = version
        save_config(self.config)
        messagebox.showinfo("공문 정리함", f"{version} 로 바꿨습니다.\n확인을 누르면 새로 시작합니다.")
        updater.restart()

    def show_update_notice(self, version: str) -> None:
        """갱신을 마치고 다시 뜬 뒤 "이렇게 바뀌었습니다" 를 보여 준다.

        표시는 한 번만 하고 지운다. 변경내역.md 에 그 번호가 없으면
        (적어 두는 것을 잊었으면) 조용히 넘어간다.
        """
        self.config.pop("updated_to", None)
        save_config(self.config)

        items = changelog.as_lines(version)
        if not items:
            return

        window = tk.Toplevel(self.root)
        window.title("공문 정리함")
        window.configure(bg=PAPER)
        window.resizable(False, False)
        window.transient(self.root)

        frame = tk.Frame(window, bg=PAPER)
        frame.pack(fill="both", expand=True, padx=20, pady=18)

        tk.Label(frame, text=f"{version} 으로 새로워졌습니다", font=self.f_title,
                 bg=PAPER, fg=INK, anchor="w").pack(fill="x")
        tk.Label(frame, text="이렇게 바뀌었습니다.", font=self.f_small, bg=PAPER,
                 fg=SOFT, anchor="w").pack(fill="x", pady=(2, 12))

        box = tk.Frame(frame, bg=CARD, highlightbackground=RULE, highlightthickness=1)
        box.pack(fill="both", expand=True)
        for item in items[:8]:
            line = tk.Frame(box, bg=CARD)
            line.pack(fill="x", padx=12, pady=(8, 0))
            tk.Label(line, text="·", font=self.f_row, bg=CARD, fg=SEAL,
                     anchor="n").pack(side="left", padx=(0, 6))
            tk.Label(line, text=item, font=self.f_row, bg=CARD, fg=INK, anchor="w",
                     justify="left", wraplength=360).pack(side="left", fill="x")
        tk.Frame(box, bg=CARD, height=10).pack(fill="x")

        buttons = tk.Frame(frame, bg=PAPER)
        buttons.pack(fill="x", pady=(14, 0))
        self._foot_button(buttons, "확인", lambda e=None: window.destroy()).pack(side="right")

        window.update_idletasks()
        window.geometry(f"+{self.root.winfo_x() - 90}+{self.root.winfo_y() + 40}")
        window.attributes("-topmost", True)
        window.grab_set()

    def _maybe_check_update(self) -> None:
        """너무 자주는 아니되, 껐다 켜면 다시 확인한다.

        예전에는 "오늘 확인함"으로 적어 두는 바람에 같은 날 재시작해도
        건너뛰었다. 새 버전이 나온 걸 알고 껐다 켜도 소용이 없었다.
        지금은 마지막으로 확인한 시각을 보고 몇 시간이 지났으면 다시 본다.
        """
        self.config = load_config()
        last = self.config.get("update_checked_at")
        if last:
            try:
                elapsed = datetime.now() - datetime.fromisoformat(last)
                if elapsed < timedelta(hours=UPDATE_GAP_HOURS):
                    return
            except ValueError:
                pass
        self.check_update(quiet=True)

    def _live_tick(self):
        """브라우저에서 고친 것을 곧바로 따라 그린다.

        디스크는 건드리지 않는다. 저장소가 매기는 번호(rev)만 보고 달라졌을
        때만 다시 그리므로 몇 초마다 돌아도 부담이 없다. 새 파일이 들어왔는지
        훑는 일은 `_on_tick` 이 십 분에 한 번 따로 한다.

        메인 스레드에서만 돈다 — tkinter 를 다른 스레드에서 만지지 않기 위해서다.
        """
        try:
            self._sync_folder()
            if self.store.rev != self._seen_rev:
                self._seen_rev = self.store.rev
                self.draw()
        finally:
            self.root.after(int(LIVE_SECONDS * 1000), self._live_tick)

    def _watch_for_calls(self):
        """"앞으로 나와 달라" 는 부탁이 왔는지 본다.

        `_live_tick`(2.5초) 에 얹지 않고 따로 둔다. 되살리기는 사람이
        아이콘을 누르고 기다리는 일이라 2.5초는 길다. 여기서 하는 일은
        정수 하나 비교가 전부라 자주 돌아도 부담이 없다 — 디스크도
        저장소도 건드리지 않는다.
        """
        try:
            if Handler.show_calls != self._seen_calls:
                self._seen_calls = Handler.show_calls
                self.surface()
        finally:
            self.root.after(250, self._watch_for_calls)

    def surface(self):
        """가려졌거나 화면 밖으로 나간 위젯을 다시 눈앞으로 데려온다.

        테두리 없는 창이라 작업 표시줄에 뜨지 않는다. 바탕화면 보기로
        가려지면 되살릴 길이 없었다.
        """
        self.root.deiconify()
        self.root.overrideredirect(True)
        self._pull_onto_screen()
        self.root.attributes("-alpha",
                             clamp_opacity(self.config.get("opacity", 0.96)))
        self.root.lift()
        # 잠깐 맨 위로 올려야 확실히 보인다. '항상 위' 를 꺼 두신 분에게는
        # 그 설정을 다시 존중해 돌려놓는다.
        self.root.attributes("-topmost", True)
        if not bool(self.config.get("on_top", True)):
            self.root.after(1500,
                            lambda: self.root.attributes("-topmost", False))

    def _pull_onto_screen(self):
        """창이 화면 밖에 있으면 안으로 끌어온다.

        모니터를 빼거나 해상도를 바꾸면 저장해 둔 자리가 화면 밖이 된다.
        그러면 떠 있어도 영영 안 보인다.
        """
        metric = ctypes.windll.user32.GetSystemMetrics
        # 76~79 = 모든 모니터를 합친 범위 (왼쪽, 위, 너비, 높이)
        bounds = (metric(76), metric(77), metric(78), metric(79))
        here = (self.root.winfo_x(), self.root.winfo_y())
        there = onto_screen(here, bounds)
        if there != here:
            self.root.geometry(f"+{there[0]}+{there[1]}")

    def _sync_folder(self):
        """브라우저에서 폴더를 바꿨으면 위젯도 그쪽을 보게 한다."""
        folder = getattr(Handler, "folder", None)
        if folder is None or folder == self.folder:
            return
        self.folder = folder
        self.base = getattr(Handler, "base", None) or folder.parent
        self._paint_folder()
        self._drawn = None          # 폴더가 바뀌었으니 목록도 새로 그린다

    def _tick(self):
        self.root.after(REFRESH_MINUTES * 60_000, self._on_tick)

    def _on_tick(self):
        self.refresh(scan=True)
        # 켜 둔 채로 며칠이 지나도 날이 바뀌면 새 버전을 확인한다.
        # 하루에 한 번만 실제로 물어보도록 안에서 걸러진다.
        self._maybe_check_update()
        self._tick()
        # 같은 학교 여러 대가 한꺼번에 몰리지 않도록 조금 흩어 놓는다
        self.root.after(random.randint(5, 90) * 1000, self._maybe_check_update)

    def quit(self):
        self.config["widget_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_config(self.config)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def onto_screen(where: tuple[int, int], bounds: tuple[int, int, int, int],
                margin: int = 80) -> tuple[int, int]:
    """창 자리를 화면 안으로 끌어온다. (왼쪽, 위) 를 돌려준다.

    모니터를 빼거나 해상도를 바꾸면 저장해 둔 자리가 화면 밖이 된다.
    위젯은 테두리 없는 창이라 작업 표시줄에도 안 뜨므로, 그렇게 되면
    떠 있어도 영영 못 찾는다.

    `bounds` 는 모든 모니터를 합친 (왼쪽, 위, 너비, 높이). `margin` 은
    아래쪽에 남길 여유 — 창 전체가 아니라 머리말만이라도 잡을 수 있으면
    끌어다 옮길 수 있다.
    """
    x, y = where
    left, top, width, height = bounds
    x = min(max(x, left), left + width - WIDTH)
    y = min(max(y, top), top + height - margin)
    return int(x), int(y)


def _say_it_is_already_running() -> None:
    """되살리지 못했을 때만 띄우는 마지막 안내.

    **반드시 맨 위에 띄운다.** 그냥 띄우면 이 창마저 다른 창 뒤에 숨어서,
    쓰는 분에게는 여전히 "아무 반응이 없다" 로 보인다. 되살리기가 안 되던
    때 실제로 그랬다.
    """
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        messagebox.showinfo(
            "공문 정리함",
            "이미 실행 중이라 앞으로 불러내려 했지만 창을 찾지 못했습니다.\n\n"
            "작업 관리자(Ctrl+Shift+Esc)에서 '공문 정리함' 을 끝낸 뒤\n"
            "다시 실행해 주세요.\n\n"
            "지우고 다시 설치하실 필요는 없습니다. 설정과 그동안의 기록도\n"
            "그대로 남습니다.",
            parent=root)
    finally:
        root.destroy()


def clamp_opacity(value) -> float:
    """투명도를 쓸 수 있는 범위로 가둔다.

    OPACITY_MIN 아래로 내려가면 위젯이 어디 있는지 보이지 않아 오른쪽
    버튼도 누르지 못하고, 되돌릴 방법이 없어진다.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(OPACITY_MIN, min(1.0, number))


def _widget_sort(doc: dict):
    """고정한 것이 맨 위, 그 안에서 기한 있는 것 먼저, 날짜만 있는 것, 날짜 없는 것."""
    pin = 0 if doc.get("pinned") else 1
    if doc["left"] is not None:
        return (pin, 0, doc["left"], "")
    if doc.get("event_date"):
        return (pin, 1, 0, doc["event_date"])
    return (pin, 2, 0, "")


def _shorten(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _one_line(text: str, limit: int) -> str:
    """여러 줄 글을 한 줄로 눌러 목록에 보이기 좋게 자른다."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def _fit_text(text: str, font, max_px: int) -> str:
    """실제 픽셀 폭으로 재서 max_px 를 넘으면 뒤를 잘라 … 를 붙인다.

    글자 수로 자르면 한글·영문이 섞였을 때 어떤 폴더는 남고 어떤 폴더는
    잘려 들쭉날쭉하다. 폭으로 재야 칸에 맞게 일정하게 정리된다.
    """
    if max_px <= 0 or font.measure(text) <= max_px:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + "…") <= max_px:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo].rstrip() + "…") if lo else "…"


def _round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """모서리가 둥근 사각형. Canvas 에는 없어서 곡선을 이어 만든다."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kw)


def _hex_rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _win_file_icon(master, path: str, px: int, bg: str):
    """윈도우 셸에서 파일·폴더의 아이콘을 얻어 tk.PhotoImage 로 돌려준다.

    셸이 주는 것은 HICON 이라 바로 못 쓴다. 32비트 DIB 에 배경색을 깔고
    그 위에 아이콘을 그린 뒤 픽셀을 읽어, px 칸에 맞게 최근접 축소하며
    tk 이미지를 만든다. Pillow 없이 표준 라이브러리만으로 한다.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32 = ctypes.windll.shell32

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int),
                    ("dwAttributes", wintypes.DWORD),
                    ("szDisplayName", wintypes.WCHAR * 260),
                    ("szTypeName", wintypes.WCHAR * 80)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    for fn in (user32.GetDC, gdi32.CreateCompatibleDC, gdi32.CreateDIBSection,
               gdi32.CreateSolidBrush, gdi32.SelectObject, shell32.SHGetFileInfoW):
        fn.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.GdiFlush.argtypes = []
    user32.DestroyIcon.argtypes = [ctypes.c_void_p]
    user32.DrawIconEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    user32.FillRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    gdi32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.c_void_p, ctypes.c_uint]
    shell32.SHGetFileInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                       ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint]

    SHGFI_ICON = 0x00000100
    SHGFI_LARGEICON = 0x00000000
    info = SHFILEINFOW()
    if not shell32.SHGetFileInfoW(path, 0, ctypes.byref(info),
                                  ctypes.sizeof(info), SHGFI_ICON | SHGFI_LARGEICON):
        return None
    hicon = info.hIcon
    if not hicon:
        return None

    n = 32                                       # 큰 아이콘 기본 크기
    screen = user32.GetDC(None)
    memdc = gdi32.CreateCompatibleDC(screen)
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(header)
    header.biWidth, header.biHeight = n, -n       # 음수 = 위에서 아래로
    header.biPlanes, header.biBitCount = 1, 32
    bits = ctypes.c_void_p()
    dib = gdi32.CreateDIBSection(memdc, ctypes.byref(header), 0,
                                 ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(memdc, dib)
    try:
        r, g, b = _hex_rgb(bg)
        brush = gdi32.CreateSolidBrush(r | (g << 8) | (b << 16))
        user32.FillRect(memdc, ctypes.byref(wintypes.RECT(0, 0, n, n)), brush)
        gdi32.DeleteObject(brush)
        user32.DrawIconEx(memdc, 0, 0, hicon, n, n, 0, None, 0x0003)   # DI_NORMAL
        gdi32.GdiFlush()
        raw = ctypes.string_at(bits, n * n * 4)   # BGRA, 위에서 아래로
    finally:
        user32.DestroyIcon(hicon)
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(dib)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(None, screen)

    rows = []
    for y in range(px):
        sy = y * n // px
        row = []
        for x in range(px):
            i = (sy * n + x * n // px) * 4
            row.append("#%02x%02x%02x" % (raw[i + 2], raw[i + 1], raw[i]))
        rows.append("{" + " ".join(row) + "}")
    image = tk.PhotoImage(master=master, width=px, height=px)
    image.put(" ".join(rows))
    return image


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
    updater.clean_leftovers()
    parser = argparse.ArgumentParser(description="공문 정리함 위젯")
    parser.add_argument("--folder", help="공문을 모아 두는 폴더")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    config = load_config()
    is_first_run = not config.get("folder")
    # 방금 갱신하고 다시 뜬 것인지. 실제로 그 버전으로 바뀌었을 때만 알린다.
    updated_to = config.get("updated_to")
    just_updated = bool(updated_to) and updated_to == VERSION

    running = running_port(args.port) if not args.folder else None
    if running is not None:
        # 이미 떠 있으면 그쪽을 앞으로 불러내고 조용히 물러난다. 위젯은
        # 테두리 없는 창이라 작업 표시줄에 안 뜨는데, 가려지면 되살릴 길이
        # 없었다 — 다시 실행해도 "이미 실행 중" 이라는 말만 들었다.
        #
        # **두 길을 모두 쓴다.** 부탁하는 길(`/api/show`)은 상대가 그 길을
        # 아는 판일 때만 듣는다. 옛 버전이 돌고 있으면 404 가 나고, 다시
        # 설치해도 파일만 바뀔 뿐 **이미 돌던 옛 프로세스는 그대로**라
        # 영영 낫지 않는다. 창을 직접 세우는 길은 상대가 어느 판이든 듣는다.
        asked = ask_to_surface(running)
        raised = raise_running_widget()
        if asked or raised:
            return
        _say_it_is_already_running()
        return

    chosen = resolve_folder(args.folder, ask=is_first_run)
    base, folder = resolve_inbox(chosen)
    store = Store(DB_PATH)
    _server, port = start_server(store, folder, args.port, base=base)

    widget = Widget(store, folder, port, base=base)
    if is_first_run:
        widget.root.after(700, lambda: first_run_guide(folder))
    elif just_updated:
        widget.root.after(700, lambda: widget.show_update_notice(VERSION))
    elif updated_to:
        # 갱신했다고 적혀 있는데 버전이 그대로다 — 교체가 안 된 것이다.
        # 표시만 지운다. 갱신은 다음 확인 때 다시 권한다.
        widget.config.pop("updated_to", None)
        save_config(widget.config)
    widget.run()


if __name__ == "__main__":
    main()

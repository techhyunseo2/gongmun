"""화면 비교.

결재자가 말없이 고친 곳을 찾아 준다. 판단이 틀리면 "안 바뀌었다" 를
믿고 넘어가게 만드는 도구라, 놓치는 것이 잘못 알리는 것보다 위험하다.

글자를 창 없이 메모리에 그려서 시험한다(GDI). 윈도우의 실제 글자
렌더링을 그대로 쓰므로 진짜에 가깝고, 창이 안 뜨니 CI 에서도 돈다.
"""

from __future__ import annotations

import ctypes
import sys
import unittest
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import screen_compare as sc  # noqa: E402

WINDOWS = sys.platform == "win32"

BEFORE = [
    "예시중학교",
    "수신    내부결재",
    "(경유)",
    "제목   (중)2026학년도 방과후학교(요리반) 물품 구매",
    "1. 관련: 예시중학교-2949(2026. 5. 14., 2026 학교교육계획)",
    "2. 2026학년도 방과후학교(요리반) 운영에 필요한 물품을 구매하고자 합니다.",
    "   가. 일    시: 2026. 8. 24.(월) 7, 8교시",
    "   나. 장    소: 기술실",
    "   다. 대    상: 수강생 7명",
    "   라. 품목내역: 지출품의서 참조",
    "   마. 소요예산: 금75,000원(금칠만오천원).  끝.",
]


# ------------------------------------------------------- 창 없이 글자 그리기

class _Rect(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def render(lines, width=900, height=380, left=12, step=30):
    """메모리에 글자를 그려 Shot 을 만든다. 창을 띄우지 않는다."""
    gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
    dc = gdi32.CreateCompatibleDC(0)
    head = sc._BitmapInfoHeader()
    head.biSize = ctypes.sizeof(sc._BitmapInfoHeader)
    head.biWidth, head.biHeight = width, -height
    head.biPlanes, head.biBitCount = 1, 32
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(head), 0,
                                    ctypes.byref(bits), None, 0)
    white = gdi32.CreateSolidBrush(0x00FFFFFF)
    font = gdi32.CreateFontW(-15, 0, 0, 0, 400, 0, 0, 0, 129, 0, 0, 4, 0,
                             "맑은 고딕")
    try:
        gdi32.SelectObject(dc, bitmap)
        whole = _Rect(0, 0, width, height)
        user32.FillRect(dc, ctypes.byref(whole), white)
        gdi32.SelectObject(dc, font)
        gdi32.SetBkMode(dc, 1)              # TRANSPARENT
        gdi32.SetTextColor(dc, 0x00000000)
        for row, line in enumerate(lines):
            box = _Rect(left, 10 + row * step, width, 10 + (row + 1) * step)
            user32.DrawTextW(dc, line, -1, ctypes.byref(box), 0x00000004)
        gdi32.GdiFlush()
        raw = ctypes.string_at(bits, width * height * 4)
    finally:
        gdi32.DeleteObject(font)
        gdi32.DeleteObject(white)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dc)
    return sc.Shot(width, height, sc.to_grey(raw))


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Rendering(unittest.TestCase):
    """시험 도구 자체가 멀쩡한지부터. 이게 깨지면 아래가 다 무의미하다."""

    def test_text_actually_gets_drawn(self):
        shot = render(BEFORE)
        ink = sum(1 for v in shot.grey if v < sc.INK)
        self.assertGreater(ink, 2000, "글자가 그려지지 않았습니다")

    def test_every_line_becomes_a_band(self):
        self.assertEqual(len(sc.bands(render(BEFORE))), len(BEFORE))


def changed(rows):
    return [row for row in rows if row.state != sc.SAME]


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Finding(unittest.TestCase):

    def test_same_content_at_a_different_place_is_quiet(self):
        """두 창의 가로 위치가 달라도 오탐이 없어야 한다.

        나란히 띄운 두 창은 결코 같은 자리에 있지 않다. 여기서 오탐이
        나면 온 문서가 빨개져서 도구가 쓸모없어진다.
        """
        rows = sc.compare(render(BEFORE, left=12), render(BEFORE, left=45))
        self.assertEqual(changed(rows), [])

    def test_the_real_case(self):
        """실제로 겪은 사례. 따옴표가 씌워지고 '호' 가 붙었다."""
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        rows = changed(sc.compare(render(BEFORE), render(after)))
        self.assertEqual(len(rows), 1, f"고친 한 줄만 잡혀야 합니다: {rows}")
        self.assertEqual(rows[0].state, sc.EDITED)
        self.assertTrue(rows[0].spans, "어디가 달라졌는지 짚어야 합니다")
        # 줄 전체가 아니라 일부만 표시해야 한다.
        marked = sum(end - start for start, end in rows[0].spans)
        self.assertLess(marked, 200, "너무 넓게 표시했습니다")

    def test_inserted_line_does_not_flag_the_rest(self):
        """줄이 끼어들면 아래가 전부 밀린다. 그걸 다 바뀐 것으로 보면 안 된다."""
        after = BEFORE[:8] + ["   다. 준비물: 앞치마"] + BEFORE[8:]
        rows = changed(sc.compare(render(BEFORE), render(after)))
        self.assertTrue(any(row.state == sc.ADDED for row in rows))
        self.assertLessEqual(len(rows), 4, f"너무 많이 잡혔습니다: {rows}")

    def test_item_letter_change_is_caught(self):
        """마 → 바 처럼 획 수가 같은 글자도 잡아야 한다.

        칸별 잉크의 양만 세던 판에서 실제로 놓쳤다. 높이별 유무를 비트로
        쌓도록 고쳐서 잡는다.
        """
        after = list(BEFORE)
        after[10] = BEFORE[10].replace("마. 소요예산", "바. 소요예산")
        rows = changed(sc.compare(render(BEFORE), render(after)))
        self.assertEqual(len(rows), 1)
        first = min(start for start, _ in rows[0].spans)
        self.assertLess(first, 80, "줄 앞머리의 항목 번호를 짚어야 합니다")

    def test_amount_change_is_caught(self):
        after = list(BEFORE)
        after[10] = "   마. 소요예산: 금80,000원(금팔만원).  끝."
        rows = changed(sc.compare(render(BEFORE), render(after)))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].spans)


def with_rules(lines, width=900, height=380, thickness=6, **kwargs):
    """한글 창처럼 양옆에 세로 테두리가 있는 그림."""
    shot = render(lines, width=width, height=height, **kwargs)
    grey = bytearray(shot.grey)
    for y in range(height):
        for x in list(range(thickness)) + list(range(width - thickness, width)):
            grey[y * width + x] = 90
    return sc.Shot(width, height, bytes(grey))


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class VerticalRules(unittest.TestCase):
    """세로로 이어지는 선이 있으면 글줄 찾기가 통째로 무너진다.

    한글 창에는 쪽 테두리와 창 테두리가 세로로 끝까지 이어진다. 그 칸
    때문에 모든 가로줄에 잉크가 있게 되어 문서 전체가 글줄 하나로 뭉치고,
    달라진 곳을 문서만 한 상자 하나로 표시해 아무것도 못 알아보게 된다.

    실사용에서 처음 써 보셨을 때 바로 이것 때문에 "아무것도 표시되지
    않는다" 가 됐다. 표는 세로선이 더 많으니 그대로 두면 늘 이렇다.
    """

    def test_rules_are_found(self):
        found = with_rules(BEFORE).rules
        self.assertTrue(found)
        self.assertLessEqual(max(found), 899)
        self.assertIn(0, found)

    def test_lines_are_still_counted_right(self):
        self.assertEqual(len(sc.bands(with_rules(BEFORE))), len(BEFORE))

    def test_the_answer_matches_the_borderless_case(self):
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        plain = changed(sc.compare(render(BEFORE), render(after)))
        ruled = changed(sc.compare(with_rules(BEFORE), with_rules(after)))
        self.assertEqual([(c.state, c.top, c.bottom, c.spans) for c in plain],
                         [(c.state, c.top, c.bottom, c.spans) for c in ruled])

    def test_marks_never_swallow_the_whole_picture(self):
        """상자가 그림 높이만큼 커지면 표시가 아니라 테두리다."""
        after = list(BEFORE)
        after[4] = ("1. 관련: 예시중학교-2949(2026. 5. 14., "
                    "“2026 학교교육계획”)호")
        shot = with_rules(after)
        for mark in changed(sc.compare(with_rules(BEFORE), shot)):
            with self.subTest(mark=mark):
                self.assertLess(mark.bottom - mark.top, shot.height // 3,
                                "글줄 하나보다 훨씬 큽니다. 글줄이 뭉쳤습니다.")

    def test_same_content_with_rules_is_quiet(self):
        rows = sc.compare(with_rules(BEFORE, left=12), with_rules(BEFORE, left=45))
        self.assertEqual(changed(rows), [])

    def test_a_short_pick_keeps_its_letters(self):
        """한 줄만 바짝 잘라 골라도 글자가 살아 있어야 한다."""
        shot = render(BEFORE[:1], width=300, height=24, step=24)
        self.assertEqual(shot.rules, frozenset(), "글자를 선으로 봤습니다")
        self.assertTrue(sc.bands(shot), "글줄이 사라졌습니다")

    def test_it_backs_off_when_everything_looks_like_a_rule(self):
        """다 지워질 판이면 잘못 짚은 것이다. 그대로 두고 넘어간다.

        선만 있는 그림(표 눈금만 걸린 자리 따위)을 만나면 잉크가 하나도
        안 남아 글줄을 못 찾는다. 그럴 바엔 거르지 않는 편이 낫다.
        """
        width, height = 80, 100
        grey = bytearray([255] * (width * height))
        for y in range(height):                 # 세로선 세 개뿐인 그림
            for x in (10, 11, 40, 41, 70, 71):
                grey[y * width + x] = 60
        shot = sc.Shot(width, height, bytes(grey))
        self.assertEqual(shot.rules, frozenset(),
                         "다 지워 놓고 글줄이 없다고 하면 안 됩니다")


class Privacy(unittest.TestCase):
    """찍은 화면이 어디에도 남지 않아야 한다.

    화면에 무엇이 있을지 프로그램은 알 수 없다. 공문 폴더의 파일과 달리
    이용자가 읽어도 된다고 정해 준 것이 아니다. 셋 다 빠져도 프로그램은
    멀쩡히 돌아서 알아채기 어렵다.
    """

    SOURCE = (ROOT / "screen_compare.py").read_text(encoding="utf-8")

    def test_it_never_touches_the_disk(self):
        for forbidden in ("open(", "write_text", "write_bytes", "tempfile",
                          "NamedTemporary", "mkstemp", "shutil"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.SOURCE,
                                 f"찍은 화면이 디스크로 나갈 길이 생겼습니다: {forbidden}")

    def test_it_never_touches_the_store(self):
        for forbidden in ("import store", "sqlite3", "import app"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.SOURCE)

    def test_it_never_sends_anything_out(self):
        for forbidden in ("urllib", "http", "socket", "requests"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.SOURCE)

    def test_errors_do_not_carry_what_was_captured(self):
        """예외 메시지는 오류기록.txt 와 안내창에 그대로 나간다."""
        change = sc.Change(sc.EDITED, 10, 20, [(3, 9)])
        self.assertNotIn("grey", repr(change))
        shot = sc.Shot(2, 2, bytes([0, 1, 2, 3]))
        self.assertNotIn("grey", repr(shot))

    def test_a_too_small_pick_is_refused_before_capturing(self):
        with self.assertRaises(sc.ScreenError):
            sc.capture(0, 0, 2, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""위젯 설정 회귀 테스트 (창을 띄우지 않는 부분만).

tkinter 창이 필요한 부분은 CI 에서 띄우기 어려우므로, 창 없이 확인할 수
있는 규칙과 소스의 모양만 지킨다.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import widget  # noqa: E402


class Opacity(unittest.TestCase):

    def test_floor_keeps_the_widget_findable(self):
        """더 흐려지면 위젯을 찾지 못해 오른쪽 버튼도 못 누른다."""
        self.assertEqual(widget.clamp_opacity(0.1), widget.OPACITY_MIN)
        self.assertEqual(widget.clamp_opacity(0), widget.OPACITY_MIN)
        self.assertEqual(widget.clamp_opacity(-5), widget.OPACITY_MIN)

    def test_ceiling(self):
        self.assertEqual(widget.clamp_opacity(1.4), 1.0)

    def test_passes_through_normal_values(self):
        for value in (0.5, 0.7, 0.96, 1.0):
            with self.subTest(value=value):
                self.assertEqual(widget.clamp_opacity(value), value)

    def test_broken_config_does_not_crash(self):
        """설정 파일이 손상돼도 뜨기는 해야 한다."""
        for junk in (None, "", "밝게", [], {}):
            with self.subTest(junk=junk):
                self.assertEqual(widget.clamp_opacity(junk), 1.0)

    def test_floor_is_actually_usable(self):
        self.assertGreaterEqual(widget.OPACITY_MIN, 0.4,
                                "이보다 흐리면 위젯이 사실상 안 보인다")


class Wording(unittest.TestCase):
    """사용자가 직접 정한 문구. 업데이트 때 되돌리지 말 것.

    슬라이더 창 머리말은 사용자가 커밋 6499304 에서 손수 고친 것이다.
    "더 나은 표현" 으로 바꾸지 말고 그대로 둔다. 바꿔야 할 사정이 생기면
    사용자에게 먼저 물어본다.
    """

    HEADING = "최대 50%까지 투명도를 조절할 수 있습니다"

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def test_slider_heading_is_untouched(self):
        self.assertIn(
            f'text="{self.HEADING}"', self.source,
            "슬라이더 머리말은 사용자가 정한 문구입니다. "
            f'"{self.HEADING}" 그대로 두세요.')

    def test_heading_matches_the_actual_floor(self):
        """문구의 50% 와 OPACITY_MIN 이 어긋나면 거짓말이 된다."""
        floor = round(widget.OPACITY_MIN * 100)
        self.assertIn(f"{floor}%", self.HEADING,
                      f"OPACITY_MIN 을 {floor}% 로 바꿨으면 머리말도 함께 "
                      "고치고, 이 검사의 HEADING 도 같이 고쳐 주세요.")


class Menu(unittest.TestCase):

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def test_fixed_opacity_presets_are_gone(self):
        """세 단계 고정값 대신 손잡이로 조절한다."""
        for gone in ("선명하게", "조금 투명하게", "많이 투명하게"):
            with self.subTest(label=gone):
                self.assertNotIn(gone, self.source,
                                 f'메뉴에서 "{gone}" 를 뺐어야 합니다')

    def test_slider_entry_exists(self):
        self.assertIn("투명도 조절", self.source)
        self.assertIn("def show_opacity", self.source)


class BringingItBack(unittest.TestCase):
    """가려지거나 화면 밖으로 나간 위젯을 되찾는 길.

    위젯은 테두리 없는 창이라 **작업 표시줄에 뜨지 않는다.** 바탕화면
    보기로 가려지면 되살릴 방법이 없었다 — 다시 실행해도 "이미 실행 중"
    이라는 말만 들었다. 실사용에서 갇히셨다.
    """

    BOUNDS = (0, 0, 1920, 1080)          # 모니터 한 대

    def test_a_place_on_screen_is_left_alone(self):
        self.assertEqual(widget.onto_screen((300, 300), self.BOUNDS), (300, 300))

    def test_off_to_the_right_comes_back(self):
        x, _ = widget.onto_screen((9000, 300), self.BOUNDS)
        self.assertEqual(x, 1920 - widget.WIDTH)

    def test_below_the_screen_comes_back(self):
        _, y = widget.onto_screen((300, 9000), self.BOUNDS)
        self.assertEqual(y, 1080 - 80)
        self.assertLess(y, 1080, "화면 안이어야 합니다")

    def test_above_and_left_comes_back(self):
        self.assertEqual(widget.onto_screen((-500, -500), self.BOUNDS), (0, 0))

    def test_a_second_monitor_on_the_left_is_still_screen(self):
        """모니터를 왼쪽에 붙이면 좌표가 음수다. 그걸 화면 밖으로 보면 안 된다."""
        wide = (-1920, 0, 3840, 1080)
        self.assertEqual(widget.onto_screen((-1500, 100), wide), (-1500, 100))

    def test_it_leaves_room_to_grab_the_widget(self):
        """맨 아래에 붙어도 머리말은 남아야 끌어서 옮길 수 있다."""
        _, y = widget.onto_screen((300, 9000), self.BOUNDS)
        self.assertLessEqual(y + 40, 1080, "잡을 자리가 없습니다")

    def test_running_again_asks_the_first_one_to_show_itself(self):
        """다시 실행하는 것이 곧 되살리기여야 한다."""
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        start = source.index("running = running_port(")
        block = source[start:start + 700]
        self.assertIn("ask_to_surface(running)", block)
        # 부탁이 닿지 않았을 때만 예전 안내창으로 물러난다
        self.assertLess(block.index("ask_to_surface(running)"),
                        block.index("이미 실행 중입니다"),
                        "불러내 보지도 않고 안내창부터 띄웁니다")

    def test_the_signal_is_watched_on_the_main_thread(self):
        """tkinter 는 요청 스레드에서 만지면 안 된다.

        그래서 서버는 숫자만 올리고, 위젯이 메인 스레드에서 그 숫자를 본다.
        """
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        watch = source[source.index("def _watch_for_calls"):]
        watch = watch[:watch.index("\n    def ", 10)]
        self.assertIn("Handler.show_calls", watch)
        self.assertIn("self.root.after(", watch)

    def test_it_respects_the_always_on_top_setting(self):
        """잠깐 맨 위로 올리되, 꺼 두신 분에게는 되돌려 놓아야 한다."""
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        rise = source[source.index("    def surface(self):"):]
        rise = rise[:rise.index("\n    def ", 10)]
        self.assertIn("deiconify", rise)
        self.assertIn("_pull_onto_screen", rise)
        self.assertIn('on_top', rise)
        self.assertIn('"-topmost", False', rise)


if __name__ == "__main__":
    unittest.main(verbosity=2)

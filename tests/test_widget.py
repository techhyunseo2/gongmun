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

    def test_running_again_tries_both_ways_to_bring_it_back(self):
        """다시 실행하는 것이 곧 되살리기여야 한다. **길이 둘이어야 한다.**

        `/api/show` 로 부탁하는 길은 상대가 그 길을 아는 판일 때만 듣는다.
        옛 버전이 돌고 있으면 404 가 나고, 다시 설치해도 파일만 바뀔 뿐
        이미 돌던 옛 프로세스는 그대로라 영영 낫지 않는다. 실제로 몇 분이
        지웠다 설치하기를 되풀이하셨다.

        창을 밖에서 직접 세우는 길은 상대가 어느 판이든 듣는다.
        """
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        start = source.index("running = running_port(")
        block = source[start:start + 900]
        self.assertIn("ask_to_surface(running)", block, "부탁하는 길이 없습니다")
        self.assertIn("raise_running_widget()", block, "직접 세우는 길이 없습니다")
        # 둘 다 실패했을 때만 안내창으로 물러난다
        self.assertLess(block.index("raise_running_widget()"),
                        block.index("_say_it_is_already_running"),
                        "되살려 보지도 않고 안내창부터 띄웁니다")

    def test_the_last_resort_notice_cannot_hide_behind_things(self):
        """되살리지 못했을 때의 안내창마저 숨으면 '아무 반응 없음' 이 된다."""
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        block = source[source.index("def _say_it_is_already_running"):]
        block = block[:block.index("\ndef ", 10)]
        self.assertIn('"-topmost", True', block, "안내창이 뒤로 숨을 수 있습니다")
        # 지웠다 다시 설치하기를 되풀이하시던 분들께 그럴 필요가 없다고
        # 알려 주는 것이 이 문구의 핵심이다.
        self.assertIn("지우고 다시 설치하실 필요는 없습니다", block)
        self.assertIn("작업 관리자", block)

    def test_raising_from_outside_needs_no_help_from_the_running_copy(self):
        """밖에서 세우는 길은 떠 있는 판의 협조에 기대면 안 된다."""
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        block = source[source.index("def raise_running_widget"):]
        block = block[:block.index("\n# SetWindowPos")]
        for needed in ("EnumWindows", "GetWindowTextW", "SetWindowPos",
                       "AttachThreadInput", "GetCurrentProcessId"):
            with self.subTest(needed=needed):
                self.assertIn(needed, block)
        # 우리 자신을 세우려 들면 안 된다
        self.assertIn("owner.value == ours", block)

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

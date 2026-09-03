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


if __name__ == "__main__":
    unittest.main(verbosity=2)

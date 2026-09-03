"""ui.html 의 눈에 안 보이는 규칙들.

CSS 한 줄이 사라져도 화면은 그럭저럭 나오기 때문에 알아채기 어렵다.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HTML = (ROOT / "ui.html").read_text(encoding="utf-8")


def z_of(selector: str) -> int:
    """그 선택자 규칙 안의 z-index 값."""
    pattern = re.escape(selector) + r"\s*\{[^}]*?z-index\s*:\s*(\d+)"
    found = re.search(pattern, HTML, re.S)
    assert found, f"{selector} 에 z-index 가 없습니다"
    return int(found.group(1))


class Checkbox(unittest.TestCase):
    """네모는 작게 두되 누르는 자리는 넓혀야 한다.

    좁으면 옆을 눌러 미리보기가 열려서, 여러 건을 골라 한꺼번에 처리할 때
    번번이 방해가 된다. 브라우저에서 15px 네모 / 23px 판정(1.53배)을 확인했다.
    """

    def test_hit_area_is_widened(self):
        self.assertRegex(
            HTML, r"\.pick::before\s*\{[^}]*inset\s*:\s*-\d+px",
            ".pick::before 로 누르는 자리를 넓혀 두어야 합니다")

    def test_visible_size_unchanged(self):
        """사용자가 요청한 것은 판정 범위만 넓히는 것이었다."""
        found = re.search(r"\.pick\s*\{[^}]*?width\s*:\s*(\d+)px", HTML, re.S)
        self.assertIsNotNone(found)
        self.assertEqual(int(found.group(1)), 15, "보이는 네모 크기는 그대로 둡니다")

    def test_hit_area_is_about_one_and_a_half(self):
        inset = int(re.search(r"\.pick::before\s*\{[^}]*inset\s*:\s*-(\d+)px",
                              HTML, re.S).group(1))
        ratio = (15 + inset * 2) / 15
        self.assertGreater(ratio, 1.3, f"{ratio:.2f}배 — 너무 좁습니다")
        self.assertLess(ratio, 1.8, f"{ratio:.2f}배 — 옆 칸을 가로챕니다")

    def test_checkmark_still_uses_after(self):
        """::after 는 체크 표시가 쓴다. 판정 범위는 ::before 로 넓힌다."""
        self.assertIn('.pick[aria-checked="true"]::after', HTML)


class Layering(unittest.TestCase):
    """고른 건수를 알리는 검은 막대가 미리보기를 가리면 안 된다.

    공문 내용을 확인하면서 고르는 흐름이라, 막대가 위로 오면 정작 읽어야
    할 내용이 가려진다.
    """

    def test_panel_sits_above_the_selection_bar(self):
        self.assertGreater(z_of("aside"), z_of(".picked"),
                           "미리보기 패널이 검은 막대보다 위여야 합니다")

    def test_scrim_sits_above_the_selection_bar(self):
        self.assertGreater(z_of(".scrim"), z_of(".picked"),
                           "가림막이 검은 막대보다 위여야 합니다")

    def test_panel_sits_above_its_own_scrim(self):
        self.assertGreater(z_of("aside"), z_of(".scrim"))

    def test_toast_stays_on_top(self):
        """패널을 열어 둔 채 기한을 바꿔도 알림이 보여야 한다."""
        self.assertGreater(z_of("#toast"), z_of("aside"),
                           "알림이 패널 뒤로 숨습니다")


if __name__ == "__main__":
    unittest.main(verbosity=2)

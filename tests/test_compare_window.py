"""화면 비교의 창 부분.

그림을 tkinter 가 읽을 수 있는 형태로 만드는 일과, 결과 머리말 문구를
지킨다. 드래그로 고르는 부분은 사람이 마우스를 움직여야 해서 여기서
시험하지 못한다 — 그 대신 창을 실제로 띄워 확인했다.
"""

from __future__ import annotations

import base64
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WINDOWS = sys.platform == "win32"

if WINDOWS:
    import compare_window as cw
    import screen_compare as sc


def grey_shot(width=40, height=12, value=200):
    return sc.Shot(width, height, bytes([value]) * (width * height))


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Picture(unittest.TestCase):
    """Tk 는 base64 로 넘긴 PPM 을 못 읽는다. PNG 여야 한다.

    처음에 PPM 으로 만들었다가 `couldn't recognize image data` 로 막혔다.
    """

    def test_it_is_a_real_png(self):
        raw = base64.b64decode(cw._as_png(grey_shot()))
        self.assertEqual(raw[:8], bytes([137, 80, 78, 71, 13, 10, 26, 10]))
        self.assertEqual(raw[12:16], b"IHDR")
        self.assertTrue(raw.rstrip().endswith(b"IEND\xae\x42\x60\x82"))

    def test_the_size_survives(self):
        raw = base64.b64decode(cw._as_png(grey_shot(37, 19)))
        width, height = struct.unpack(">II", raw[16:24])
        self.assertEqual((width, height), (37, 19))

    def test_it_stays_one_grey_layer(self):
        """회색 한 겹이라야 자료가 3분의 1 이고, 빨강이 눈에 띈다."""
        raw = base64.b64decode(cw._as_png(grey_shot()))
        depth, colour = raw[24], raw[25]
        self.assertEqual((depth, colour), (8, 0), "8비트 회색 한 겹이어야 합니다")


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Headline(unittest.TestCase):
    """받는 분이 읽을 말이라 문구를 못박아 둔다."""

    def one(self, state):
        return sc.Change(state, 10, 24, [(5, 20)])

    def test_nothing_changed(self):
        said = cw._Result._headline([])
        self.assertIn("찾지 못했습니다", said)

    def test_counts_each_kind(self):
        said = cw._Result._headline([
            self.one(sc.EDITED), self.one(sc.EDITED),
            self.one(sc.ADDED), self.one(sc.REMOVED)])
        self.assertIn("고쳐진 곳 2", said)
        self.assertIn("새로 들어온 줄 1", said)
        self.assertIn("빠진 줄 1", said)

    def test_it_does_not_mention_kinds_that_did_not_happen(self):
        said = cw._Result._headline([self.one(sc.EDITED)])
        self.assertIn("고쳐진 곳 1", said)
        self.assertNotIn("빠진 줄", said)
        self.assertNotIn("새로 들어온 줄", said)


@unittest.skipUnless(WINDOWS, "화면 비교는 윈도우에서만 됩니다")
class Privacy(unittest.TestCase):
    """찍은 화면이 파일로 새지 않아야 한다. `screen_compare` 와 같은 규칙."""

    SOURCE = (ROOT / "compare_window.py").read_text(encoding="utf-8")

    def test_it_never_writes_the_capture_anywhere(self):
        for forbidden in ("open(", "write_text", "write_bytes", "tempfile",
                          "mkstemp", "urllib", "socket"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.SOURCE,
                                 f"찍은 화면이 나갈 길이 생겼습니다: {forbidden}")

    def test_the_veil_is_lifted_before_capturing(self):
        """막이 덮인 채로 찍으면 까만 그림만 남는다.

        `_Picker.run()` 은 창이 닫히기를 기다린 뒤에 찍어야 한다.
        """
        source = self.SOURCE
        wait = source.index("self.window.wait_window()")
        shoot = source.index("screen_compare.capture(")
        self.assertLess(wait, shoot, "막을 걷기 전에 찍고 있습니다")


if __name__ == "__main__":
    unittest.main(verbosity=2)

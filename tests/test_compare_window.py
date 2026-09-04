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
class HidingTheWidget(unittest.TestCase):
    """고르는 동안 위젯이 감춰져야 한다.

    위젯은 항상 위에 떠 있다. 그대로 두면 화면을 찍을 때 자기가 같이
    찍혀서, 결과 그림 한구석에 위젯이 박혀 나온다. 실사용에서 그랬다.
    """

    def setUp(self):
        self.log = []
        self.picks = [object(), object()]

        class FakePicker:
            def __init__(inner, root, message):
                self.log.append("고르기")

            def run(inner):
                return self.picks.pop(0) if self.picks else None

        self.real = (cw._Picker, cw._Result, cw.screen_compare.compare)
        cw._Picker = FakePicker
        cw._Result = lambda root, shot, changes: self.log.append("결과")
        cw.screen_compare.compare = lambda before, after: []
        self.addCleanup(self.restore)

    def restore(self):
        cw._Picker, cw._Result, cw.screen_compare.compare = self.real

    def test_hidden_before_picking_and_back_before_the_result(self):
        cw.run(None, lambda *_: None,
               hide=lambda: self.log.append("감춤"),
               show=lambda: self.log.append("되돌림"))
        self.assertEqual(self.log,
                         ["감춤", "고르기", "고르기", "되돌림", "결과"])

    def test_it_comes_back_even_if_the_user_gives_up(self):
        """Esc 로 그만둬도 위젯이 사라진 채 남으면 안 된다."""
        self.picks = [None]
        cw.run(None, lambda *_: None,
               hide=lambda: self.log.append("감춤"),
               show=lambda: self.log.append("되돌림"))
        self.assertEqual(self.log, ["감춤", "고르기", "되돌림"])

    def test_it_comes_back_even_if_capturing_blows_up(self):
        def boom(root, message):
            raise cw.screen_compare.ScreenError("찍지 못했습니다")
        cw._Picker = boom
        said = []
        cw.run(None, lambda title, text: said.append(text),
               hide=lambda: self.log.append("감춤"),
               show=lambda: self.log.append("되돌림"))
        self.assertEqual(self.log, ["감춤", "되돌림"])
        self.assertTrue(said, "무엇이 잘못됐는지 알려 줘야 합니다")

    def test_the_widget_knows_how_to_hide_and_come_back(self):
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        self.assertIn("hide=self._hide_self", source)
        self.assertIn("show=self._show_self", source)
        # deiconify 는 창 꾸밈을 되돌려 놓는다. 다시 걸어 주지 않으면
        # 위젯에 제목 표시줄이 생기고 투명도가 풀린다.
        back = source[source.index("def _show_self"):]
        back = back[:back.index("\n    def ", 10)]
        for needed in ("deiconify", "overrideredirect", "-topmost",
                       "-alpha", "geometry"):
            with self.subTest(needed=needed):
                self.assertIn(needed, back)


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
        """막이 덮인 채로 찍으면 그 아래가 아니라 막이 찍힌다.

        `destroy()` 는 요청일 뿐이라, 창이 닫히기를 기다리는 것만으로는
        모자라다. 윈도우가 가려졌던 자리를 다시 그릴 틈까지 줘야 한다.
        """
        source = self.SOURCE
        wait = source.index("self.window.wait_window()")
        settle = source.index("time.sleep(SETTLE)")
        shoot = source.index("screen_compare.capture(")
        self.assertLess(wait, settle, "막을 걷기 전에 기다리고 있습니다")
        self.assertLess(settle, shoot, "화면이 다시 그려지기 전에 찍습니다")
        self.assertGreaterEqual(cw.SETTLE, 0.05, "기다리는 시간이 너무 짧습니다")

    def test_the_result_can_be_scrolled_both_ways(self):
        """실제로 찍은 화면은 창보다 넓다. 가로로도 움직일 수 있어야 한다.

        세로만 있으면 오른쪽에 그려진 빨간 상자를 영영 못 본다.
        """
        self.assertIn('orient="horizontal"', self.SOURCE)
        self.assertIn("xscrollcommand", self.SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)

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


class QuickBar(unittest.TestCase):
    """복사한 글 담아 두기 + 자주 쓰는 특수문자 고정."""

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def test_one_line_flattens_and_trims(self):
        self.assertEqual(widget._one_line("가\n나  다", 10), "가 나 다")
        self.assertEqual(widget._one_line("x" * 50, 5), "xxxx…")

    def test_stash_and_glyphs_are_persisted(self):
        """담아 둔 글과 특수문자 배치는 껐다 켜도 남아야 한다(config.json)."""
        for key in ('"clips"', '"glyphs"', '"quickbar_open"'):
            with self.subTest(key=key):
                self.assertIn(key, self.source)
        stash = self.source[self.source.index("def _stash_clipboard"):]
        stash = stash[:stash.index("\n    def ", 10)]
        self.assertIn("save_config(self.config)", stash)
        self.assertIn("del clips[CLIP_MAX:]", stash, "오래된 것부터 밀어내야 한다")

    def test_order_can_be_edited(self):
        """저장한 텍스트와 특수문자의 자리를 바꿀 수 있어야 한다."""
        move = self.source[self.source.index("def _move_clip"):]
        move = move[:move.index("\n    def ", 10)]
        self.assertIn("clips.insert(there, clips.pop(here))", move)
        # 특수문자는 줄 편집기의 줄 순서가 곧 배치 순서다
        editor = self.source[self.source.index("def _edit_glyphs"):]
        editor = editor[:editor.index("\n    def ", 10)]
        self.assertIn("splitlines()", editor)
        self.assertIn("줄 순서가 곧 배치 순서", self.source)

    def test_click_copies_to_clipboard(self):
        copy = self.source[self.source.index("def _copy_text"):]
        copy = copy[:copy.index("\n    @staticmethod")]
        self.assertIn("clipboard_clear", copy)
        self.assertIn("clipboard_append", copy)


class Wording(unittest.TestCase):
    """사용자가 직접 정한 문구. 업데이트 때 되돌리지 말 것.

    이 문구는 사용자가 커밋 6499304 에서 손수 고친 것이다. "더 나은 표현"
    으로 바꾸지 말고 그대로 둔다. 1.7.2 부터는 투명도 슬라이더가 머리말
    바로 아래로 옮겨졌고, 이 문구는 그 슬라이더의 설명풍선으로 산다.
    """

    HEADING = "최대 50%까지 투명도를 조절할 수 있습니다"

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def test_slider_heading_is_untouched(self):
        self.assertIn(
            self.HEADING, self.source,
            "슬라이더 설명풍선 문구는 사용자가 정한 것입니다. "
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

    def test_opacity_slider_is_inline_not_in_the_menu(self):
        """투명도는 머리말 아래 슬라이더로 바로 조절한다. 메뉴 항목은 없앴다."""
        self.assertNotIn("투명도 조절", self.source, "메뉴 항목이 남아 있습니다")
        self.assertIn("def _draw_opacity_slider", self.source)
        self.assertIn("def _drag_opacity", self.source)

    def test_right_click_menu_is_only_update_and_version(self):
        """나머지는 모두 머리말 아이콘·슬라이더·폴더 박스로 옮겼다."""
        block = self.source[self.source.index("def _menu"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("업데이트 확인", block)
        self.assertIn("버전 {VERSION}", block)
        for gone in ("항상 위에 두기", "공문 폴더", "결재 전후 비교",
                     "자동 실행", "전체 화면 열기", "커스텀 클립보드"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, block, f'메뉴에 "{gone}" 가 남아 있습니다')


class HeaderControls(unittest.TestCase):
    """우클릭 메뉴에 있던 것들을 머리말 아이콘·슬라이더로 옮겼다."""

    def setUp(self):
        self.source = (ROOT / "widget.py").read_text(encoding="utf-8")

    def test_three_icon_buttons_with_tips(self):
        for maker in ('self._draw_ontop, "항상 위에 두기"',
                      'self._draw_compare, "결재 전후 비교"',
                      'self._draw_clip, "커스텀 클립보드"'):
            with self.subTest(maker=maker):
                self.assertIn(maker, self.source)

    def test_ontop_icon_is_stacked_pages_with_a_fillable_front(self):
        """압정이 아니라, 페이지가 겹친 모양. 맨 앞 장이 차 있으면 켜짐."""
        block = self.source[self.source.index("def _draw_ontop"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("create_rectangle", block)
        self.assertIn("SLATE if on else PAPER", block, "맨 앞 장의 채움으로 상태를 표시해야 합니다")
        self.assertNotIn("바늘", block, "압정 그림이 남아 있습니다")

    def test_every_header_button_shows_a_tip(self):
        """아이콘에 마우스를 올리면 무슨 기능인지 떠야 한다."""
        for fn in ("def _icon_button", "def _text_button"):
            block = self.source[self.source.index(fn):]
            block = block[:block.index("\n    def ", 10)]
            self.assertIn("_tip_schedule", block, f"{fn} 에 설명풍선이 없습니다")
        # ✕ 와 — 도 _text_button 으로 만들어 풍선이 붙는다
        self.assertIn('self._text_button("✕", "닫기"', self.source)
        self.assertIn('self._text_button("—", "접기"', self.source)

    def test_compare_icon_is_split_green_and_red(self):
        block = self.source[self.source.index("def _draw_compare"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("MOSS", block)
        self.assertIn("SEAL", block)

    def test_folder_is_a_rounded_box_that_brightens_on_hover(self):
        block = self.source[self.source.index("def _paint_folder"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("_round_rect", block)
        self.assertIn("GLOW if self._folder_hover", block)

    def test_opacity_row_shares_a_line_with_the_folder_box(self):
        """슬라이더는 절반만 쓰고, 남은 자리를 폴더 경로 박스가 채운다.

        따로 폴더 단추는 두지 않는다 — 폴더 박스를 눌러서 확인·열기·바꾸기.
        """
        build = self.source[self.source.index("def _build"):]
        build = build[:build.index("\n    def ", 10)]
        self.assertIn('self.opacity_slider = tk.Canvas(self.opacity_row', build)
        self.assertIn('width=40', build, "슬라이더 폭을 작게 고정해야 폴더 박스가 넓어집니다")
        self.assertIn('self.folderchip = tk.Canvas(self.opacity_row', build,
                      "폴더 박스가 투명도 줄과 같은 줄에 있어야 합니다")
        self.assertNotIn('"폴더 확인"', build)
        self.assertNotIn('"폴더 변경"', build)
        # "처리할 것 N건" 요약은 폴더 박스 다음, 목록 바로 위에 온다
        self.assertLess(build.index("self.folderchip"), build.index("self.summary ="))
        self.assertLess(build.index("self.summary ="), build.index("self.body ="))

    def test_folder_path_is_trimmed_to_fit_by_pixels(self):
        self.assertIn('_fit_text("폴더  " + short', self.source)

        class FakeFont:
            def measure(self, s):
                return len(s) * 7

        short = widget._fit_text("D:/아주/긴/폴더/경로/공문 정리함/공문", FakeFont(), 70)
        self.assertTrue(short.endswith("…"))
        self.assertLessEqual(FakeFont().measure(short), 70)
        # 짧으면 그대로 둔다
        self.assertEqual(widget._fit_text("공문", FakeFont(), 300), "공문")


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

    def test_the_taskbar_button_is_claimed_but_the_old_ways_stay(self):
        """작업 표시줄 아이콘은 되살리는 길을 하나 더 늘리는 것이지,

        밖에서 창을 직접 세우는 기존 길(아주 오래된 판에도 듣는다)을
        치우는 게 아니다. 둘 다 있어야 한다.
        """
        source = (ROOT / "widget.py").read_text(encoding="utf-8")
        claim = source[source.index("def _claim_taskbar_button"):]
        claim = claim[:claim.index("\n    def _finish_taskbar_button")]
        self.assertIn("WS_EX_APPWINDOW", claim, "팝업 창은 이 스타일 없이는 안 뜬다")
        self.assertIn("withdraw", claim, "작업 표시줄은 다시 보일 때만 살핀다")
        self.assertIn("sys.platform != \"win32\"", claim, "다른 OS 에서 터지면 안 된다")
        # 되살리기 다른 길은 그대로 있어야 한다
        self.assertIn("raise_running_widget", source)
        self.assertIn("_say_it_is_already_running", source)
        # 숨겼다 띄운 뒤 테두리 없애기를 다시 걸어야 한다
        finish = source[source.index("def _finish_taskbar_button"):]
        finish = finish[:finish.index("\n    def ", 10)]
        self.assertIn("overrideredirect(True)", finish)

    def test_uninstaller_still_cleans_the_legacy_startup_shortcut(self):
        """1.7.1 이하에서 프로그램 메뉴로 자동 실행을 켜 두신 분들이 있다.

        그 메뉴는 1.7.2 에서 없앴지만, 그때 만들어 둔 띄어쓰기 없는 바로가기
        (공문정리함.lnk / .bat)는 시작 폴더에 그대로 남아 있다. 지울 때
        같이 치워야 죽은 바로가기가 안 남는다.
        """
        iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
        for name in ("공문정리함.lnk", "공문정리함.bat"):
            with self.subTest(name=name):
                self.assertIn(name, iss,
                              f"installer.iss 의 [UninstallDelete] 에 {name} 을 남겨 두세요")

    def test_uninstaller_asks_before_deleting_records(self):
        """설정·기록(.gongmun)은 물어보고, 기본은 남기는 쪽이어야 한다."""
        iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn(".gongmun", iss)
        self.assertIn("MB_DEFBUTTON2", iss, "기본 단추가 '아니오' 여야 실수로 안 지운다")
        self.assertIn("UninstallSilent", iss, "조용히 지울 때는 묻지 말고 남겨야 한다")

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

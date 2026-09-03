"""배포물의 라이선스 고지가 빠지지 않았는지.

교육청 공모·배포를 염두에 둔 검사다. 여기 걸리는 것들은 하나같이
"빠져도 프로그램은 멀쩡히 돌아가서" 알아채기 어렵다.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


class Files(unittest.TestCase):

    def test_license_exists_and_is_mit(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", text)
        self.assertRegex(text, r"Copyright \(c\) \d{4}")

    def test_third_party_notices_cover_every_dependency(self):
        notices = (ROOT / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
        required = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for line in required.splitlines():
            name = re.split(r"[><=!\[]", line.strip())[0].strip()
            if name:
                with self.subTest(package=name):
                    self.assertIn(name, notices,
                                  f"THIRD-PARTY-NOTICES.txt 에 {name} 이 없습니다")

    def test_notices_cover_font_and_pyinstaller(self):
        notices = (ROOT / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
        self.assertIn("Pretendard", notices)
        self.assertIn("SIL Open Font License", notices)
        # GPL 을 본 심사자가 멈추지 않도록 예외 조항 근거가 있어야 한다
        self.assertIn("PyInstaller", notices)
        self.assertIn("예외", notices)

    def test_font_licence_text_is_present(self):
        """OFL 1.1 은 글꼴을 함께 배포할 때 전문을 같이 두도록 요구한다."""
        ofl = ROOT / "assets" / "Pretendard-OFL.txt"
        self.assertTrue(ofl.is_file(), "assets/Pretendard-OFL.txt 가 없습니다")
        text = ofl.read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", text)
        self.assertIn("Kil Hyung-jin", text)          # 저작권 표시

    def test_font_file_is_really_a_font(self):
        data = (ROOT / "assets" / "PretendardVariable.woff2").read_bytes()
        self.assertEqual(data[:4], b"wOF2")


class Bundling(unittest.TestCase):
    """빠뜨리면 글꼴이 조용히 안 나오거나 고지가 사라진다."""

    def setUp(self):
        self.spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.iss = (ROOT / "installer.iss").read_text(encoding="utf-8")

    def test_exe_bundles_font_and_notices(self):
        for name in ("PretendardVariable.woff2", "Pretendard-OFL.txt",
                     "LICENSE", "THIRD-PARTY-NOTICES.txt"):
            with self.subTest(name=name):
                self.assertIn(name, self.spec,
                              f"build.spec 의 datas 에 {name} 을 넣어 주세요")

    def test_installer_puts_notices_where_users_can_read_them(self):
        """exe 안에만 있으면 이용자가 열어 볼 수 없다."""
        for name in ("LICENSE", "THIRD-PARTY-NOTICES.txt", "Pretendard-OFL.txt"):
            with self.subTest(name=name):
                self.assertIn(name, self.iss,
                              f"installer.iss 의 [Files] 에 {name} 을 넣어 주세요")


class NoOutboundRequests(unittest.TestCase):
    """화면이 바깥으로 요청을 보내지 않아야 한다.

    공공기관 배포 검토에서 걸리는 지점이고, 학교망이 CDN 을 막으면
    글꼴이 조용히 바뀌는 문제이기도 하다.
    """

    def test_ui_has_no_external_urls(self):
        html = (ROOT / "ui.html").read_text(encoding="utf-8")
        found = re.findall(r"https?://[^\s\"')]+", html)
        self.assertEqual(found, [], f"ui.html 에 외부 주소가 있습니다: {found}")

    def test_font_is_served_from_ourselves(self):
        html = (ROOT / "ui.html").read_text(encoding="utf-8")
        self.assertIn("/assets/PretendardVariable.woff2", html)
        self.assertIn("@font-face", html)

    def test_asset_routes_are_a_closed_list(self):
        """경로를 받아 파일을 여는 대신 목록으로 못박아야 한다."""
        self.assertIn("/assets/PretendardVariable.woff2", app.ASSETS)
        self.assertIn("/assets/Pretendard-OFL.txt", app.ASSETS)
        for route in app.ASSETS:
            with self.subTest(route=route):
                self.assertNotIn("..", route)


if __name__ == "__main__":
    unittest.main(verbosity=2)

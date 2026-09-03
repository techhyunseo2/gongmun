"""배포물의 라이선스 고지가 빠지지 않았는지.

교육청 공모·배포를 염두에 둔 검사다. 여기 걸리는 것들은 하나같이
"빠져도 프로그램은 멀쩡히 돌아가서" 알아채기 어렵다.
"""

from __future__ import annotations

import re
import subprocess
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


class NoRealDocuments(unittest.TestCase):
    """실제 공문이 저장소에 딸려 들어가면 안 된다.

    저장소는 공개이고, 공모 요강은 "지정 서식을 제외한 제출자료에
    개인정보가 포함된 경우 실격" 이라고 못박는다. 필수 제출자료에
    '전체 소스' 가 들어 있으므로 여기 섞인 문서는 그대로 따라간다.

    실제로 `공문/` 아래에 남의 학교 선생님 실명·연락처와 외부 강사
    명단이 든 공문 2건이 커밋돼 있었다. 손으로 시험하다 남긴 것이라
    프로그램은 멀쩡히 돌아서 아무도 못 알아챘다. 이 파일의 다른
    검사들과 같은 종류다 — 빠져도 티가 안 난다.

    테스트용 문서는 코드가 그때그때 임시 폴더에 만들어 쓴다
    (`tests/test_organize.py` 등). 저장소에 둘 이유가 없다.
    """

    DOCUMENTS = {
        ".hwp", ".hwpx", ".pdf", ".doc", ".docx",
        ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx",
    }

    def _tracked_files(self):
        try:
            done = subprocess.run(
                ["git", "-C", str(ROOT), "ls-files", "-z"],
                capture_output=True, check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:  # git 이 없는 환경
            self.skipTest(f"git 을 쓸 수 없어 건너뜁니다: {exc}")
        return [n for n in done.stdout.decode("utf-8").split("\0") if n]

    def test_no_documents_are_tracked(self):
        found = sorted(
            name for name in self._tracked_files()
            if Path(name).suffix.lower() in self.DOCUMENTS
        )
        self.assertEqual(found, [], (
            "실제 문서가 저장소에 들어 있습니다. 개인정보가 섞여 있을 수 "
            "있으니 지우고 `.gitignore` 로 막으세요: " + ", ".join(found)
        ))

    def test_inbox_folder_is_ignored(self):
        """`공문/` 을 만들어 놓고 시험하다 다시 커밋하는 일을 막는다."""
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("공문/", text, ".gitignore 에 `공문/` 이 없습니다.")


if __name__ == "__main__":
    unittest.main(verbosity=2)

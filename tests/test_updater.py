"""updater.py 회귀 테스트 (네트워크 없이 도는 것만).

핵심은 "새 버전이 나왔는데도 내려받지 못하는" 사고를 막는 것이다.
1.3.6~1.3.7 은 자동 업데이트가 찾는 첨부 이름(공문정리함.exe)과 GitHub 이
실제로 올린 이름(default.exe)이 어긋나 "내려받다가 끊겼습니다" 로
실패했다. 그 상황을 표본으로 고정한다.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater  # noqa: E402


class VersionCompare(unittest.TestCase):

    def test_newer(self):
        self.assertTrue(updater.is_newer("v1.3.8", "1.3.7"))
        self.assertTrue(updater.is_newer("1.4.0", "1.3.9"))

    def test_not_newer(self):
        self.assertFalse(updater.is_newer("v1.3.7", "1.3.7"))
        self.assertFalse(updater.is_newer("v1.3.6", "1.3.7"))

    def test_asset_name_is_ascii(self):
        """한글이 섞이면 GitHub 이 파일명을 바꿔 버려 다운로드가 깨진다."""
        self.assertTrue(updater.ASSET_NAME.isascii())


class ReleaseParsing(unittest.TestCase):

    def test_picks_smaller_exe_as_app(self):
        """첨부가 설치파일 + 실행파일이면 더 작은 쪽이 PyInstaller exe."""
        release = {
            "body": "설명",
            "assets": [
                {"name": "gongmun-setup.exe", "size": 17_000_000, "state": "uploaded",
                 "browser_download_url": "https://x/gongmun-setup.exe"},
                {"name": "gongmun.exe", "size": 15_000_000, "state": "uploaded",
                 "browser_download_url": "https://x/gongmun.exe"},
            ],
        }
        info = updater._parse_release(release)
        self.assertEqual(info["asset_url"], "https://x/gongmun.exe")
        self.assertEqual(info["notes"], "설명")

    def test_survives_mangled_korean_names(self):
        """GitHub 이 한글 이름을 default.exe / -.exe 로 바꿔 놓은 옛 릴리스."""
        release = {
            "assets": [
                {"name": "-.exe", "size": 16_511_735, "state": "uploaded",
                 "browser_download_url": "https://x/-.exe"},
                {"name": "default.exe", "size": 14_822_686, "state": "uploaded",
                 "browser_download_url": "https://x/default.exe"},
            ],
        }
        info = updater._parse_release(release)
        self.assertEqual(info["asset_url"], "https://x/default.exe")

    def test_no_exe_asset(self):
        info = updater._parse_release({"body": "x", "assets": [
            {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"}]})
        self.assertNotIn("asset_url", info)

    def test_empty_release(self):
        self.assertEqual(updater._parse_release({}), {"notes": ""})


if __name__ == "__main__":
    unittest.main(verbosity=2)

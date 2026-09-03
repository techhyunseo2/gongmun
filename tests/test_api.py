"""HTTP 라우트 회귀 테스트.

실제 서버를 띄워 브라우저가 부르는 것과 같은 방식으로 두드린다.
파일을 여는 것은 운영체제 일이므로 그 부분만 가로채 기록한다.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from store import Store  # noqa: E402

BODY = ("제목\n      파견교사 선발 계획 알림\n\n"
        "신청서를 2026. 9. 25.까지 제출바랍니다.\n")


class RevealCommand(unittest.TestCase):
    """탐색기에 넘기는 명령줄이 옳은지.

    리스트로 넘기면 파이썬이 공백이 든 "/select,경로" 를 통째로 따옴표로
    감싸고, 그러면 explorer 가 /select 를 스위치로 못 알아보고 엉뚱하게
    문서 폴더를 연다. 실제 업무 폴더는 "OneDrive - 덕문중학교" 처럼
    공백이 섞여 있어서 늘 실패했다.
    """

    SPACED = Path(r"C:\Users\나\OneDrive - 덕문중학교\1. 교무기획\공문"
                  r"\[덕문중학교-4971] (본문) 계획.txt")

    def _sent(self, path: Path, platform: str = "win32"):
        sent = []
        saved_popen, saved_platform = app.subprocess.Popen, app.sys.platform
        app.subprocess.Popen = lambda args, **kw: sent.append(args)
        app.sys.platform = platform
        try:
            app.reveal_in_os(path)
        finally:
            app.subprocess.Popen = saved_popen
            app.sys.platform = saved_platform
        return sent[0]

    def test_switch_is_outside_the_quotes(self):
        line = self._sent(self.SPACED)
        self.assertIsInstance(line, str,
                              "리스트로 넘기면 파이썬이 따옴표를 다시 씌운다")
        self.assertTrue(line.startswith('explorer /select,"'),
                        f"/select 가 따옴표 안에 들어갔습니다: {line}")
        self.assertTrue(line.endswith('"'))
        self.assertIn(str(self.SPACED), line)

    def test_matches_the_documented_form(self):
        simple = Path(r"C:\gongmun\a.txt")
        self.assertEqual(self._sent(simple), f'explorer /select,"{simple}"')

    def test_reveal_does_not_block_the_request(self):
        """창을 앞으로 끌어올리는 일은 딴 스레드에서 해야 한다.

        여기서 기다리면 브라우저의 요청이 몇 초씩 붙잡힌다.
        """
        import time as _time
        start = _time.monotonic()
        app._raise_explorer_window("이런이름의폴더는없다ZZZ")
        self.assertLess(_time.monotonic() - start, 0.5,
                        "요청 스레드에서 창을 기다리고 있습니다")

    def test_foreground_helpers_never_raise(self):
        """창을 못 세워도 파일 열기 자체는 성공해야 한다."""
        app._allow_foreground_steal()
        for junk in ("", "없는폴더ZZZ"):
            with self.subTest(name=junk):
                app._raise_explorer_window(junk)

    def test_macos_reveals_rather_than_opens(self):
        sent = self._sent(self.SPACED, platform="darwin")
        self.assertEqual(sent[:2], ["open", "-R"])


class Routes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.base = cls.tmp / "1. 교무기획"
        cls.inbox = cls.base / "공문"
        cls.inbox.mkdir(parents=True)
        r = "[덕문중학교-4971]"
        (cls.inbox / f"{r} (본문) 계획 알림.txt").write_text(BODY, encoding="utf-8")
        (cls.inbox / f"{r} (첨부) 서식.zip").write_bytes(b"PK\x03\x04" + b"\0" * 3000)
        cls.store = Store(cls.tmp / "t.db")
        cls.store.scan(cls.inbox)
        cls.server, cls.port = app.start_server(cls.store, cls.inbox,
                                                port=9931, base=cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.store.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # 운영체제 호출을 가로채 무엇을 열려 했는지만 적어 둔다
        self.opened: list[Path] = []
        self.revealed: list[Path] = []
        self._saved = (app.open_in_os, app.reveal_in_os)
        app.open_in_os = self.opened.append
        app.reveal_in_os = self.revealed.append

    def tearDown(self):
        app.open_in_os, app.reveal_in_os = self._saved

    def get(self, path: str):
        # 한글이 든 주소도 그대로 넘길 수 있게 감싼다
        url = f"http://127.0.0.1:{self.port}{urllib.parse.quote(path, safe='/?=&')}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def a_doc(self, suffix: str) -> dict:
        for doc in self.store.all_docs():
            if doc["filename"].endswith(suffix):
                return doc
        self.fail(f"{suffix} 문서를 찾지 못했습니다")

    # ------------------------------------------------------------ reveal

    def test_reveal_targets_the_file_itself(self):
        """폴더만 여는 게 아니라 그 파일을 고른 채로 열어야 한다."""
        doc = self.a_doc(".zip")
        status, payload = self.get("/api/reveal?id=" + doc["id"])
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual([str(p) for p in self.revealed], [doc["path"]])
        self.assertEqual(self.opened, [], "파일을 고르지 않고 폴더만 열었습니다")

    def test_reveal_works_for_attachments_too(self):
        """미리보기가 안 되는 첨부야말로 위치를 열어 볼 일이 많다."""
        for suffix in (".txt", ".zip"):
            with self.subTest(suffix=suffix):
                self.revealed.clear()
                doc = self.a_doc(suffix)
                self.get("/api/reveal?id=" + doc["id"])
                self.assertEqual([str(p) for p in self.revealed], [doc["path"]])

    def test_reveal_falls_back_to_the_folder_when_file_is_gone(self):
        doc = self.a_doc(".txt")
        moved = Path(doc["path"])
        stashed = moved.with_suffix(".hidden")
        moved.rename(stashed)
        try:
            status, payload = self.get("/api/reveal?id=" + doc["id"])
            self.assertEqual(status, 200)
            self.assertEqual([str(p) for p in self.opened], [str(moved.parent)])
        finally:
            stashed.rename(moved)

    def test_reveal_unknown_id(self):
        status, payload = self.get("/api/reveal?id=없는아이디")
        self.assertEqual(status, 404)
        self.assertIn("error", payload)

    # -------------------------------------------------------------- 기타

    def test_open_still_opens_the_file(self):
        doc = self.a_doc(".zip")
        self.get("/api/open?id=" + doc["id"])
        self.assertEqual([str(p) for p in self.opened], [doc["path"]])

    def test_open_folder_opens_the_inbox(self):
        self.get("/api/open-folder")
        self.assertEqual([str(p) for p in self.opened], [str(self.inbox)])

    def test_state_and_rev_agree(self):
        _, rev = self.get("/api/rev")
        _, state = self.get("/api/state")
        self.assertEqual(state["rev"], rev["rev"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

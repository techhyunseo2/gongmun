"""store.py 회귀 테스트 — 동시 접근과 변경 번호(rev).

위젯과 브라우저가 같은 Store 하나를 나눠 쓴다. tkinter 메인 스레드,
위젯의 스캔 스레드, HTTP 요청 스레드들이 커넥션 하나에 동시에 손을 댄다.
락을 빼면 여기 6번 테스트가 `cannot start a transaction within a transaction`,
`bad parameter or other API misuse` 같은 오류를 수십 건 낸다. 콘솔 없는
exe 에서는 그게 곧 오류 팝업이므로 절대 되돌리지 말 것.

`rev` 는 "다시 그릴 일이 있는지"를 위젯과 브라우저에 알리는 번호다.
읽기만 했는데 오르면 위젯이 몇 초마다 헛되이 다시 그린다.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store import Store  # noqa: E402

SAMPLE = ("제목\n      자율동아리 계획 제출 안내\n\n"
          "계획서를 2026. 9. 30.까지 제출바랍니다.\n")


class StoreCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inbox = self.tmp / "공문"
        self.inbox.mkdir()
        self.store = Store(self.tmp / "t.db")

    def tearDown(self):
        self.store.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _put(self, name: str, text: str = SAMPLE) -> None:
        (self.inbox / name).write_text(text, encoding="utf-8")


class Revision(StoreCase):

    def test_starts_at_zero_and_touch_rises(self):
        self.assertEqual(self.store.rev, 0)
        self.store.touch()
        self.assertEqual(self.store.rev, 1)

    def test_reading_does_not_raise_rev(self):
        """읽기만 하는데 rev 가 오르면 위젯이 몇 초마다 헛되이 다시 그린다."""
        self._put("가.txt")
        self.store.scan(self.inbox)
        before = self.store.rev
        for _ in range(5):
            self.store.all_docs()
        self.assertEqual(self.store.rev, before)

    def test_each_edit_raises_rev(self):
        self._put("가.txt")
        self.store.scan(self.inbox)
        doc_id = self.store.all_docs()[0]["id"]
        before = self.store.rev
        self.store.set_done(doc_id, True)
        self.store.set_memo(doc_id, "담당 김선생")
        self.store.set_deadline(doc_id, "2026-10-01")
        self.store.set_category(doc_id, "event")
        self.assertEqual(self.store.rev, before + 4)

    def test_unchanged_rescan_keeps_rev(self):
        """달라진 게 없는 재훑기는 조용해야 한다."""
        self._put("가.txt")
        self.store.scan(self.inbox)
        before = self.store.rev
        self.store.scan(self.inbox)
        self.assertEqual(self.store.rev, before)

    def test_new_file_raises_rev(self):
        self._put("가.txt")
        self.store.scan(self.inbox)
        before = self.store.rev
        self._put("나.txt", "제목\n      추가 안내\n\n2026. 9. 20.까지 회신바랍니다.\n")
        self.store.scan(self.inbox)
        self.assertGreater(self.store.rev, before)

    def test_renamed_file_raises_rev(self):
        """내용이 같아 id 는 그대로여도 이름이 바뀌면 화면 글자가 달라진다."""
        self._put("가.txt")
        self.store.scan(self.inbox)
        before = self.store.rev
        (self.inbox / "가.txt").rename(self.inbox / "가-수정.txt")
        report = self.store.scan(self.inbox)
        self.assertEqual(report["moved"], 1)
        self.assertGreater(self.store.rev, before)


class Concurrency(StoreCase):

    def test_scan_read_write_together(self):
        """스캔·읽기·쓰기를 뒤섞어도 터지지 않는다 (Store 의 락).

        락을 빼면 `cannot start a transaction within a transaction`,
        `cannot commit - no transaction is active`, `bad parameter or other
        API misuse` 가 수십 건 난다.
        """
        for i in range(30):
            self._put(f"문서{i}.txt", f"제목\n      안내 {i}\n\n"
                                      f"2026. 9. {i % 28 + 1}.까지 제출바랍니다.\n")
        self.store.scan(self.inbox)
        ids = [d["id"] for d in self.store.all_docs()]
        self.assertTrue(ids)
        errors: list[str] = []

        def scanner():
            for _ in range(6):
                try:
                    self.store.scan(self.inbox, force=True)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"scan {type(exc).__name__}: {exc}")

        def reader():
            for _ in range(200):
                try:
                    self.store.all_docs()
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"read {type(exc).__name__}: {exc}")

        def writer():
            for i in range(100):
                try:
                    self.store.set_memo(ids[i % len(ids)], f"메모 {i}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"write {type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=fn)
                   for fn in (scanner, reader, writer, reader, writer, scanner)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors[:3], [], f"{len(errors)}건 터졌습니다")
        # 뒤엉킨 뒤에도 기록이 온전한지
        self.assertEqual(len(self.store.all_docs()), 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)

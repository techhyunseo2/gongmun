"""읽지 못하는 첨부(zip, png…)도 같은 공문으로 묶어 정리하는지.

에듀파인에서 내려받으면 압축·이미지 첨부에도 같은 접수번호가 이름 앞에
붙어 온다. 내용을 못 읽는다고 빠뜨리면 폴더 정리에서 홀로 남고, 완료된
업무를 월별 폴더로 옮길 때도 뒤에 남겨진다.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import organize  # noqa: E402
from store import Store  # noqa: E402

BODY = ("제목\n      파견교사 선발 계획 알림\n\n"
        "신청서를 2026. 9. 25.까지 제출바랍니다.\n")


class MixedFolder(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base = self.tmp / "1. 교무기획"
        self.inbox = self.base / "공문"
        self.inbox.mkdir(parents=True)
        self.store = Store(self.tmp / "t.db")

    def tearDown(self):
        self.store.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fill(self):
        r = "[예시중학교-4971]"
        (self.inbox / f"{r} (본문) 파견교사 선발 계획 알림.txt").write_text(BODY, encoding="utf-8")
        (self.inbox / f"{r} (첨부) 제출서식.zip").write_bytes(b"PK\x03\x04" + b"\0" * 4000)
        (self.inbox / f"{r} 안내 포스터.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 900)
        # 접수번호가 없는 남의 파일. 건드리면 안 된다.
        (self.inbox / "내가 찍은 화면.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 80)


class Planning(MixedFolder):

    def test_plan_gathers_every_format(self):
        self._fill()
        groups, loose = organize.plan(self.inbox)
        self.assertEqual(len(groups), 1)
        names = sorted(i.path.suffix for i in groups[0].items)
        self.assertEqual(names, [".png", ".txt", ".zip"])

    def test_plan_leaves_unnumbered_files_alone(self):
        self._fill()
        _groups, loose = organize.plan(self.inbox)
        self.assertEqual([p.name for p in loose], ["내가 찍은 화면.png"])

    def test_organize_moves_every_format(self):
        self._fill()
        report = organize.organize(self.inbox)
        self.assertEqual(report["moved"], 3)
        folder = next(d for d in self.inbox.iterdir() if d.is_dir())
        self.assertEqual(sorted(p.suffix for p in folder.iterdir()),
                         [".png", ".txt", ".zip"])
        self.assertTrue((self.inbox / "내가 찍은 화면.png").exists(),
                        "접수번호 없는 파일까지 옮기면 안 됩니다")


class Recording(MixedFolder):

    def test_companions_are_recorded_but_not_read(self):
        self._fill()
        self.store.scan(self.inbox)
        by_name = {d["filename"]: d for d in self.store.all_docs()}
        self.assertIn("[예시중학교-4971] (첨부) 제출서식.zip", by_name)
        zipped = by_name["[예시중학교-4971] (첨부) 제출서식.zip"]
        self.assertFalse(zipped["readable"])
        self.assertEqual(zipped["error"], "",
                         "읽을 필요가 없는 것이지 못 읽은 것이 아닙니다")

    def test_unnumbered_loose_file_is_ignored(self):
        """공문 폴더 바로 아래의 접수번호 없는 그림은 남의 파일일 수 있다."""
        self._fill()
        self.store.scan(self.inbox)
        self.assertNotIn("내가 찍은 화면.png",
                         {d["filename"] for d in self.store.all_docs()})

    def test_everything_folds_into_one_group(self):
        self._fill()
        self.store.scan(self.inbox)
        groups = app.fold_groups(self.store.all_docs())
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["members"]), 3)
        self.assertEqual(groups[0]["attachments"], 2)

    def test_lead_is_never_an_unreadable_file(self):
        """대표가 zip 이면 목록에 제목도 기한도 없이 이름만 남는다."""
        self._fill()
        self.store.scan(self.inbox)
        lead = app.fold_groups(self.store.all_docs())[0]
        self.assertTrue(lead["filename"].endswith(".txt"))
        self.assertEqual(lead["deadline"], "2026-09-25")

    def test_sibling_in_organized_folder_joins_the_group(self):
        """정리된 폴더 안에 접수번호 없는 파일을 넣어도 갈라지면 안 된다."""
        self._fill()
        self.store.scan(self.inbox)
        organize.organize(self.inbox)
        folder = next(d for d in self.inbox.iterdir() if d.is_dir())
        (folder / "회의사진.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 300)
        self.store.scan(self.inbox)
        groups = app.fold_groups(self.store.all_docs())
        self.assertEqual(len(groups), 1, "같은 폴더인데 묶음이 갈라졌습니다")
        self.assertEqual(len(groups[0]["members"]), 4)

    def test_large_companion_is_not_read_whole(self):
        """큰 첨부까지 통째로 해시하면 훑을 때마다 디스크를 긁는다."""
        import store as store_module
        big = self.inbox / "[예시중학교-4971] (첨부) 큰파일.zip"
        big.write_bytes(b"A" * (store_module.COMPANION_HASH_BYTES + 2048))
        first = store_module._file_id(big, store_module.COMPANION_HASH_BYTES)
        # 뒷부분만 다른 파일은 크기가 같으면 같은 id 가 될 수 있지만,
        # 앞부분만 읽어도 크기를 섞으므로 크기가 다르면 갈린다.
        big.write_bytes(b"A" * (store_module.COMPANION_HASH_BYTES + 4096))
        self.assertNotEqual(first, store_module._file_id(
            big, store_module.COMPANION_HASH_BYTES))

    def test_readable_file_id_rule_unchanged(self):
        """읽는 형식의 id 규칙이 바뀌면 이미 쌓인 처리 상태와 메모가 날아간다."""
        import hashlib

        import store as store_module
        path = self.inbox / "[예시중학교-4971] (본문) 계획.txt"
        path.write_text(BODY, encoding="utf-8")
        expected = hashlib.sha1(path.read_bytes()).hexdigest()[:16]
        self.assertEqual(store_module._file_id(path), expected)


class Archiving(MixedFolder):

    def test_archive_carries_companions(self):
        self._fill()
        self.store.scan(self.inbox)
        organize.organize(self.inbox)
        self.store.scan(self.inbox)
        for doc in self.store.all_docs():
            self.store.set_done(doc["id"], True)

        entries = [{"title": g["title"], "month": 9,
                    "receipt": g.get("receipt_number", ""), "paths": g["paths"]}
                   for g in app.fold_groups(self.store.all_docs())]
        organize.archive(self.base, self.inbox, entries)

        landed = sorted(p.suffix for p in (self.base / "9월").rglob("*") if p.is_file())
        self.assertEqual(landed, [".png", ".txt", ".zip"],
                         "압축·이미지가 공문 폴더에 남겨졌습니다")


if __name__ == "__main__":
    unittest.main(verbosity=2)

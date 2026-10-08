"""ODT(개방형 문서) 읽기.

에듀파인은 공문 본문을 .odt 로도 내려 준다. 머리(수신·제목)와 꼬리(시행·
접수)는 글상자 속 표로 문단 안에 끼워 두는데, 이것을 글자처럼 이어 붙이면
제목을 못 찾고, 칸 사이에 "|" 를 끼우면 시행일을 제출 기한으로 집었다.

실제 공문은 저장소에 두지 않는다(test_licensing 의 NoRealDocuments).
같은 구조의 파일을 그때그때 만들어 쓴다.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import classify  # noqa: E402
import extract  # noqa: E402

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"')


def _cell(text: str) -> str:
    return f"<table:table-cell><text:p>{text}</text:p></table:table-cell>"


def _row(*cells: str) -> str:
    return "<table:table-row>" + "".join(_cell(c) for c in cells) + "</table:table-row>"


def _boxed(*rows: str) -> str:
    """에듀파인처럼 글꼴 꾸밈 > 글상자 > 표 로 문단 안에 끼운 틀."""
    return ("<text:p><text:span><draw:frame><draw:text-box><table:table>"
            + "".join(rows) + "</table:table></draw:text-box></draw:frame></text:span></text:p>")


# 에듀파인이 내보내는 본문 .odt 와 같은 뼈대
GONGMUN = (
    _boxed(_row("아름다운 청렴, 행복한 부산교육"),
           _row("", "부산광역시교육청", ""),
           _row("수신", "수신자 참조"),
           _row("제목", "(의무제출) 인증서 사용실태 점검 실시"))
    + "<text:p>1. 관련: 교육부 디지털인프라담당관-7394(2024. 11. 8.)</text:p>"
    + "<text:p>다. 제출기한: 2024. 12. 3.(화)까지</text:p>"
    + "<table:table>" + _row("구분", "제출처", "")
    + _row("중학교", "교육지원청 학교지원과") + "</table:table>"
    + "<text:p>붙임 점검 서식 1부. 끝.</text:p>"
    + _boxed(_row("부산광역시교육감"),
             _row("시행", "학교지원과-1234", "(", "2024. 11. 19.", ")",
                  "접수", "예시중학교-7009", "(", "2024. 11. 19.", ")"))
)


def _make_odt(folder: Path, body: str, name: str = "공문.odt") -> Path:
    path = folder / name
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {NS}>'
           f"<office:body><office:text>{body}</office:text></office:body>"
           "</office:document-content>")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", xml)
    return path


class ReadingOdt(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def text(self, body: str) -> str:
        return extract.extract_text(_make_odt(self.folder, body))

    def test_odt_is_a_supported_format(self):
        self.assertIn(".odt", extract.SUPPORTED)

    def test_paragraphs_become_lines(self):
        text = self.text("<text:h>안내</text:h><text:p>첫째 줄</text:p><text:p>둘째 줄</text:p>")
        self.assertEqual(text.split("\n"), ["안내", "첫째 줄", "둘째 줄"])

    def test_spacing_marks_are_restored(self):
        """여러 칸 띄어쓰기(text:s)를 지우면 낱말이 붙어 버린다."""
        text = self.text('<text:p>기한<text:s text:c="3"/>9. 25.<text:tab/>까지'
                         '<text:line-break/>다음 줄</text:p>')
        self.assertIn("기한 9. 25. 까지", text)
        self.assertIn("\n다음 줄", text)

    def test_a_real_table_keeps_one_row_per_line(self):
        text = self.text("<table:table>" + _row("제출", "2026.10.1.(목)", "", "")
                         + "</table:table>")
        self.assertEqual(text, "제출 | 2026.10.1.(목)", "뒤쪽 빈 칸은 버린다")

    def test_a_nested_table_is_not_read_twice(self):
        inner = "<table:table>" + _row("안쪽") + "</table:table>"
        text = self.text("<table:table><table:table-row><table:table-cell>"
                         f"{inner}</table:table-cell></table:table-row></table:table>")
        self.assertEqual(text.count("안쪽"), 1)

    def test_review_comments_are_left_out(self):
        text = self.text("<text:p>본문<office:annotation><text:p>검토 메모</text:p>"
                         "</office:annotation></text:p>")
        self.assertEqual(text, "본문")

    def test_boxed_header_and_footer_read_like_a_pdf(self):
        text = self.text(GONGMUN)
        self.assertIn("\n제목 (의무제출) 인증서 사용실태 점검 실시\n", text)
        self.assertIn("시행 학교지원과-1234 ( 2024. 11. 19. ) "
                      "접수 예시중학교-7009 ( 2024. 11. 19. )", text)
        self.assertNotIn("부산교육부산광역시교육청", text, "머리가 한 덩어리로 붙었다")
        self.assertIn("구분 | 제출처", text, "본문 표는 그대로 칸을 나눈다")

    def test_missing_body_is_a_clear_error(self):
        path = self.folder / "깨진.odt"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        with self.assertRaises(extract.ExtractError):
            extract.extract_text(path)


STYLED = (
    '<office:automatic-styles>'
    '<style:style style:name="P1" style:family="paragraph">'
    '<style:paragraph-properties fo:text-align="center"/>'
    '<style:text-properties fo:font-size="20pt" fo:font-weight="bold"/></style:style>'
    '<style:style style:name="C1" style:family="table-cell">'
    '<style:table-cell-properties fo:border-bottom="0.5pt solid #000000" '
    'fo:background-color="red;background:url(x)" fo:border-top="none"/></style:style>'
    '<style:style style:name="T1" style:family="text">'
    '<style:text-properties fo:color="#FF0000" fo:font-size="12pt"/></style:style>'
    '</office:automatic-styles>'
)


def _make_styled(folder: Path, body: str, pictures: dict | None = None) -> Path:
    path = folder / "서식.odt"
    ns = NS + (' xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"'
               ' xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"'
               ' xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"'
               ' xmlns:xlink="http://www.w3.org/1999/xlink"')
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ns}>'
           f"{STYLED}<office:body><office:text>{body}</office:text></office:body>"
           "</office:document-content>")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", xml)
        for name, data in (pictures or {}).items():
            archive.writestr(name, data)
    return path


class OdtPreview(unittest.TestCase):
    """PDF 처럼 문서 모양 그대로 보이는 미리보기(odt_view)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def html(self, body: str, pictures: dict | None = None) -> str:
        import odt_view
        return odt_view.render(_make_styled(self.folder, body, pictures))

    def test_extract_hands_the_preview_to_the_screen(self):
        text, html = extract.extract_rich(_make_odt(self.folder, GONGMUN))
        self.assertIn("제목 (의무제출)", text)
        self.assertIn('class="od-page"', html)
        self.assertIn("data-width=", html, "화면이 칸 폭에 맞춰 줄이려면 쪽 폭이 필요하다")

    def test_paragraph_keeps_alignment_size_and_weight(self):
        html = self.html('<text:p text:style-name="P1">부산광역시교육청</text:p>')
        self.assertIn("text-align:center", html)
        self.assertIn("font-size:26.7px", html)          # 20pt
        self.assertIn("font-weight:700", html)

    def test_no_p_tags_so_boxed_tables_do_not_break_the_page(self):
        """<p> 안에 표가 오면 브라우저가 문단을 끊는다. 에듀파인 머리가 그렇다."""
        html = self.html(GONGMUN)
        self.assertNotIn("<p", html)
        self.assertIn('<div class="od-box"', html)

    def test_merged_cells_and_borders(self):
        html = self.html(
            '<table:table><table:table-row>'
            '<table:table-cell table:style-name="C1" table:number-columns-spanned="2">'
            '<text:p>합친 칸</text:p></table:table-cell><table:covered-table-cell/>'
            '</table:table-row></table:table>')
        self.assertIn('colspan="2"', html)
        self.assertIn("border-bottom:1px solid #000000", html)
        self.assertNotIn("border-top", html, "none 은 테두리가 없다")
        self.assertEqual(html.count("<td"), 1, "가려진 칸은 그리지 않는다")

    def test_document_text_and_style_values_cannot_inject(self):
        html = self.html('<text:p><text:span text:style-name="T1">'
                         '&lt;script&gt;alert(1)&lt;/script&gt;</text:span></text:p>'
                         '<table:table><table:table-row><table:table-cell table:style-name="C1">'
                         '<text:p>x</text:p></table:table-cell></table:table-row></table:table>')
        self.assertNotIn("<script", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("url(", html, "색으로 확인되지 않은 값은 버린다")
        self.assertIn("color:#FF0000", html)

    def test_pictures_are_referenced_not_embedded(self):
        """로고를 base64 로 넣으면 html 이 저장 상한을 넘어 잘렸다(1.9.3)."""
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 300_000
        frame = ('<text:p><draw:frame svg:width="2cm"><draw:image xlink:href="{}"/>'
                 '</draw:frame></text:p>')
        html = self.html(frame.format("Pictures/logo.png"), {"Pictures/logo.png": png})
        self.assertIn('data-odt-image="Pictures/logo.png"', html)
        self.assertNotIn("base64", html)
        self.assertLess(len(html), 2000, "그림 크기가 html 에 실리면 안 된다")
        self.assertIn("width:75.6px", html)               # 2cm
        for bad in ("../secret.png", "/etc/x.png", "Pictures/없음.png", "Pictures/x.wmf"):
            with self.subTest(href=bad):
                self.assertIn("[그림]", self.html(frame.format(bad)))

    def test_blank_lines_keep_their_height(self):
        html = self.html('<text:p><text:span text:style-name="T1"></text:span></text:p>')
        self.assertIn("&nbsp;", html)


class OdtImageAndStorage(unittest.TestCase):
    """그림은 따로 받아 가고, 저장할 때 미리보기가 잘리지 않는다."""

    PNG = b"\x89PNG\r\n\x1a\n" + b"1" * 200

    def setUp(self):
        import app
        from store import Store
        self.tmp = Path(tempfile.mkdtemp())
        self.inbox = self.tmp / "공문"
        self.inbox.mkdir()
        self.store = Store(self.tmp / "t.db")
        self.server, self.port = app.start_server(self.store, self.inbox,
                                                  port=9963, base=self.tmp)

    def tearDown(self):
        import shutil
        self.server.shutdown()
        # 소켓까지 닫는다. 윈도우는 닫지 않은 자리에 다음 서버가 같은 번호로
        # 또 붙을 수 있어, 요청이 죽은 쪽으로 가서 멈춘다.
        self.server.server_close()
        self.store.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self, path: str):
        import urllib.error
        import urllib.parse
        import urllib.request
        url = f"http://127.0.0.1:{self.port}{urllib.parse.quote(path, safe='/?=&')}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, response.headers.get("Content-Type"), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Content-Type"), exc.read()

    def _scan_one(self, name: str, body: str, pictures: dict | None = None) -> str:
        _make_styled(self.tmp, body, pictures).rename(self.inbox / name)
        self.store.scan(self.inbox)
        return next(d["id"] for d in self.store.all_docs() if d["filename"] == name)

    def _saved_html(self, doc_id: str) -> str:
        return self.store.conn.execute("SELECT body_html FROM docs WHERE id=?",
                                       (doc_id,)).fetchone()[0]

    def test_the_picture_comes_from_inside_that_odt(self):
        body = ('<text:p><draw:frame svg:width="2cm"><draw:image xlink:href="Pictures/a.png"/>'
                '</draw:frame></text:p>')
        doc_id = self._scan_one("로고.odt", body, {"Pictures/a.png": self.PNG})
        status, kind, data = self.raw(f"/api/odt-image?id={doc_id}&name=Pictures/a.png")
        self.assertEqual((status, kind, data), (200, "image/png", self.PNG))
        for name in ("content.xml", "../a.png", "Pictures/없음.png"):
            with self.subTest(name=name):
                self.assertEqual(self.raw(f"/api/odt-image?id={doc_id}&name={name}")[0], 404)

    def test_only_odt_records_hand_out_pictures(self):
        (self.inbox / "그냥.txt").write_text("본문", encoding="utf-8")
        self.store.scan(self.inbox)
        doc_id = self.store.all_docs()[0]["id"]
        self.assertEqual(self.raw(f"/api/odt-image?id={doc_id}&name=Pictures/a.png")[0], 404)
        self.assertEqual(self.raw("/api/odt-image?id=없는아이디&name=Pictures/a.png")[0], 404)

    def test_an_oversized_preview_is_dropped_not_cut(self):
        """반쯤 잘린 html 은 닫히지 않은 표가 화면 단추까지 집어삼킨다."""
        import store
        para = "<text:p>" + "가" * 400 + "</text:p>"
        doc_id = self._scan_one("긴글.odt", para * (store.HTML_LIMIT // 300))
        self.assertEqual(self._saved_html(doc_id), "",
                         "상한을 넘으면 비우고 글자 미리보기로 물러나야 한다")
        self.assertTrue(self.store.get(doc_id)["readable"])

    def test_a_preview_cut_by_the_old_version_is_read_again(self):
        """1.9.3 이 잘라 담아 둔 미리보기는 파일이 그대로여도 다시 읽는다."""
        import store
        doc_id = self._scan_one("공문.odt", GONGMUN)
        cut = ("<div><table>" + "x" * store.HTML_LIMIT)[:store.HTML_LIMIT]
        self.store.conn.execute("UPDATE docs SET body_html=?, done=1 WHERE id=?",
                                (cut, doc_id))
        self.store.conn.commit()

        self.store.scan(self.inbox)

        saved = self._saved_html(doc_id)
        self.assertTrue(saved.startswith('<div class="od-page"'))
        self.assertTrue(saved.endswith("</div>"))
        self.assertTrue(self.store.get(doc_id)["done"], "다시 읽어도 처리 표시는 그대로")

        before = self.store.rev
        self.store.scan(self.inbox)
        self.assertEqual(self.store.rev, before, "고친 뒤에는 다시 읽지 않는다")


class JudgingAnOdtGongmun(unittest.TestCase):
    """읽은 뒤 판단까지 — 다른 형식의 공문과 같은 답이 나와야 한다."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            text = extract.extract_text(_make_odt(Path(folder), GONGMUN))
        cls.result = classify.analyze("공문", text, base=date(2024, 11, 19))

    def test_title(self):
        self.assertEqual(self.result["title"], "(의무제출) 인증서 사용실태 점검 실시")

    def test_numbers_for_grouping(self):
        self.assertEqual(self.result["doc_number"], "학교지원과-1234")
        self.assertEqual(self.result["receipt_number"], "예시중학교-7009")

    def test_the_deadline_is_the_real_one_not_the_send_date(self):
        self.assertEqual(self.result["deadline"], "2024-12-03")
        self.assertEqual(self.result["category"], "submit")


if __name__ == "__main__":
    unittest.main(verbosity=2)

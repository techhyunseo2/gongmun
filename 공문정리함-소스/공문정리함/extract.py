"""공문 파일에서 본문 텍스트를 뽑아낸다.

지원 형식
  .hwpx  표준 압축 XML  — 외부 라이브러리 없이 처리
  .hwp   한글 바이너리 — olefile 필요
  .pdf                 — pypdf 필요
  .docx                — 외부 라이브러리 없이 처리
  .txt / .md           — 그대로 읽음

라이브러리가 없으면 그 형식만 건너뛰고 나머지는 정상 동작한다.
"""

from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import hwpx_view

SUPPORTED = {".hwpx", ".hwp", ".pdf", ".docx", ".txt", ".md"}

# HWP 문단 안에서 8개 WCHAR(16바이트)를 차지하는 제어 문자들
_WIDE_CONTROLS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
_HWPTAG_PARA_TEXT = 67


class ExtractError(Exception):
    pass


def extract_text(path: str | Path) -> str:
    return extract_rich(path)[0]


def extract_rich(path: str | Path) -> tuple[str, str]:
    """(평문, 미리보기 html)을 돌려준다. html은 hwpx에서만 나온다."""
    path = Path(path)
    suffix = path.suffix.lower()
    html = ""
    if suffix == ".hwpx":
        try:
            html, text = hwpx_view.render(path)
        except Exception:          # 구조가 예상과 다르면 평평하게라도 읽는다
            html, text = "", _from_hwpx(path)
    elif suffix == ".hwp":
        text = _from_hwp(path)
    elif suffix == ".pdf":
        text = _from_pdf(path)
    elif suffix == ".docx":
        text = _from_docx(path)
    elif suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
    else:
        raise ExtractError(f"지원하지 않는 형식입니다: {suffix}")
    return _tidy(text), html


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- hwpx

def _from_hwpx(path: Path) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)]
        names.sort(key=lambda n: int(re.search(r"(\d+)", n.split("/")[-1]).group(1)))
        if not names:
            names = [n for n in archive.namelist() if n.endswith(".xml") and "section" in n.lower()]
        for name in names:
            try:
                root = ET.fromstring(archive.read(name).decode("utf-8", "ignore"))
            except ET.ParseError:
                continue
            chunks.append(_walk_hwpx(root))
    if not chunks:
        raise ExtractError("hwpx 안에서 본문 XML을 찾지 못했습니다.")
    return "\n".join(chunks)


def _walk_hwpx(root) -> str:
    out: list[str] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append("\n")
        elif tag == "t" and element.text:
            out.append(element.text)
        elif tag in ("lineBreak", "tab"):
            out.append(" ")
    return "".join(out)


# ----------------------------------------------------------------- hwp

def _from_hwp(path: Path) -> str:
    try:
        import olefile
    except ImportError as exc:  # pragma: no cover
        raise ExtractError("hwp를 읽으려면 olefile이 필요합니다. pip install olefile") from exc
    import zlib

    ole = olefile.OleFileIO(str(path))
    try:
        header = ole.openstream("FileHeader").read()
        compressed = bool(header[36] & 0x01)
        encrypted = bool(header[36] & 0x02)
        if encrypted:
            raise ExtractError("암호가 걸린 hwp 파일입니다.")

        sections = [e for e in ole.listdir() if len(e) > 1 and e[0] == "BodyText"]
        sections.sort(key=lambda e: int(re.sub(r"\D", "", e[1]) or 0))
        if not sections:
            raise ExtractError("hwp 본문 스트림이 없습니다.")

        out: list[str] = []
        for entry in sections:
            data = ole.openstream(entry).read()
            if compressed:
                try:
                    data = zlib.decompress(data, -15)
                except zlib.error:
                    continue
            out.append(_parse_hwp_records(data))
        return "\n".join(out)
    finally:
        ole.close()


def _parse_hwp_records(data: bytes) -> str:
    out: list[str] = []
    cursor, total = 0, len(data)
    while cursor + 4 <= total:
        (raw_header,) = struct.unpack_from("<I", data, cursor)
        cursor += 4
        tag = raw_header & 0x3FF
        size = (raw_header >> 20) & 0xFFF
        if size == 0xFFF:
            if cursor + 4 > total:
                break
            (size,) = struct.unpack_from("<I", data, cursor)
            cursor += 4
        if cursor + size > total:
            break
        if tag == _HWPTAG_PARA_TEXT:
            out.append(_decode_hwp_paragraph(data[cursor:cursor + size]))
        cursor += size
    return "\n".join(out)


def _decode_hwp_paragraph(raw: bytes) -> str:
    chars: list[str] = []
    i, size = 0, len(raw) - 1
    while i < size:
        (code,) = struct.unpack_from("<H", raw, i)
        if code in (0, 10, 13):
            chars.append("\n")
            i += 2
        elif code in _WIDE_CONTROLS:
            chars.append(" ")
            i += 16
        elif code < 32:
            i += 2
        else:
            chars.append(chr(code))
            i += 2
    return "".join(chars)


# ----------------------------------------------------------------- pdf

def _from_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ExtractError("pdf를 읽으려면 pypdf가 필요합니다. pip install pypdf") from exc
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages[:20]]
    text = "\n".join(pages)
    if not text.strip():
        raise ExtractError("스캔본으로 보입니다. 글자가 들어 있지 않습니다.")
    return text


# ---------------------------------------------------------------- docx

def _from_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", "ignore")
    root = ET.fromstring(xml)
    out: list[str] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append("\n")
        elif tag == "t" and element.text:
            out.append(element.text)
    return "".join(out)

"""ODT(개방형 문서) 서식 미리보기.

PDF 는 쪽 모양이 정해진 파일이라 브라우저가 그대로 그리지만, ODT 에는
글자와 서식 정보만 있다. 이 모듈은 그 서식(문단 정렬·들여쓰기, 글자
크기·굵기, 표 칸 너비·테두리, 그림)을 읽어 실제 쪽 크기 그대로 HTML 로
다시 그린다. 화면은 그 쪽을 미리보기 칸 폭에 맞춰 줄여 보여 준다.

  render(path) -> html

평문(분류·날짜 추출용)은 extract._from_odt 가 따로 뽑는다. 여기서는
보여 주기만 한다. 문서에서 온 글자는 전부 이스케이프하고, 스타일 값은
숫자·색으로 확인된 것만 쓴다. 태그와 속성은 이 모듈이 만든 것만 나간다.
"""

from __future__ import annotations

import base64
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
}


def q(name: str) -> str:
    """'text:p' → '{urn:…text…}p'"""
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


BASE_PT = 10.0              # 문서가 기본 글자 크기를 안 정해 두었을 때
PAGE_PAD = 28               # 종이 여백(px). 실제 쪽 여백은 너무 넓어 줄인다
MAX_REPEAT = 64             # 서식이 남긴 빈 칸·열 반복은 이만큼만 펼친다
IMAGE_MAX = 600_000         # 그림 한 장을 미리보기에 넣는 상한(바이트)
IMAGES_TOTAL = 2_000_000    # 한 문서에서 넣는 그림 합계 상한
_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "gif": "image/gif", "bmp": "image/bmp"}
_LENGTH = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(cm|mm|in|pt|pc|px)\s*$")
_PX = {"cm": 96 / 2.54, "mm": 96 / 25.4, "in": 96.0, "pt": 96 / 72, "pc": 16.0, "px": 1.0}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_BORDER_STYLES = {"solid", "double", "dashed", "dotted"}


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def px(value: str | None) -> float | None:
    """'1.387cm' → 화면 px. 알아볼 수 없으면 None."""
    match = _LENGTH.match(value or "")
    if not match:
        return None
    return float(match.group(1)) * _PX[match.group(2)]


def _num(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _border(value: str | None) -> str | None:
    """'0.5pt solid #000000' → '1px solid #000000'. 없음이면 None."""
    if not value or value.strip() == "none":
        return None
    parts = value.split()
    width = next((px(p) for p in parts if px(p) is not None), 1.0) or 0
    if width <= 0:
        return None
    kind = next((p for p in parts if p in _BORDER_STYLES), "solid")
    color = next((p for p in parts if _COLOR.match(p)), "#000000")
    if kind == "double":
        width = max(width, 3)
    return f"{_num(max(1.0, width))}px {kind} {color}"


# ------------------------------------------------------------------ 서식

class Styles:
    """이름 → 속성. 부모 스타일을 따라 올라가 합친 값을 돌려준다."""

    def __init__(self):
        self.raw: dict[tuple[str, str], tuple[str | None, dict]] = {}
        self.defaults: dict[str, dict] = {}
        self.page_width: float | None = None

    def load(self, root) -> None:
        if root is None:
            return
        for element in root.iter():
            if element.tag == q("style:default-style"):
                self.defaults[element.get(q("style:family"), "")] = _props(element)
            elif element.tag == q("style:style"):
                key = (element.get(q("style:family"), ""), element.get(q("style:name"), ""))
                self.raw[key] = (element.get(q("style:parent-style-name")), _props(element))
            elif element.tag == q("style:page-layout-properties") and self.page_width is None:
                width = px(element.get(q("fo:page-width")))
                if width:
                    left = px(element.get(q("fo:margin-left"))) or 0
                    right = px(element.get(q("fo:margin-right"))) or 0
                    self.page_width = width - left - right

    def get(self, family: str, name: str | None) -> dict:
        merged: dict = dict(self.defaults.get(family, {}))
        chain, seen = [], set()
        while name and (family, name) in self.raw and name not in seen:
            seen.add(name)
            parent, props = self.raw[(family, name)]
            chain.append(props)
            name = parent
        for props in reversed(chain):
            merged.update(props)
        return merged


def _props(style) -> dict:
    """스타일 하나에서 쓰는 속성만 모은다. 값은 아직 문서가 적은 그대로다."""
    out = {}
    for child in style:
        for attr, value in child.attrib.items():
            name = attr.rsplit("}", 1)[-1]
            ns = attr[1:].split("}", 1)[0] if attr.startswith("{") else ""
            # 아시아 글꼴 쪽 크기·굵기를 우선한다. 한글은 이쪽 값을 쓴다
            if name in ("font-size-asian", "font-weight-asian"):
                out[name.replace("-asian", "")] = value
            elif name in ("font-size", "font-weight") and name not in out:
                out[name] = value
            elif ns in (NS["fo"], NS["style"]) and name in (
                    "text-align", "margin-left", "margin-right", "margin-top",
                    "margin-bottom", "text-indent", "line-height", "font-style",
                    "color", "background-color", "border", "border-top",
                    "border-bottom", "border-left", "border-right", "padding",
                    "padding-top", "padding-bottom", "padding-left", "padding-right",
                    "vertical-align", "column-width", "width", "text-underline-style"):
                out[name] = value
    return out


# ------------------------------------------------------------------ 그리기

class Renderer:
    def __init__(self, archive: zipfile.ZipFile, styles: Styles):
        self.archive = archive
        self.styles = styles
        self.base_pt = _pt(styles.defaults.get("paragraph", {}).get("font-size")) or BASE_PT
        self.image_bytes = 0

    # ---- 글자 크기·꾸밈
    def _text_css(self, props: dict, inherited_pt: float | None = None) -> list[str]:
        css = []
        size = props.get("font-size", "")
        if size.endswith("%") and inherited_pt:
            try:
                css.append(f"font-size:{_num(inherited_pt * float(size[:-1]) / 100 * 4 / 3)}px")
            except ValueError:
                pass
        elif _pt(size):
            css.append(f"font-size:{_num(_pt(size) * 4 / 3)}px")
        weight = props.get("font-weight", "")
        if weight == "bold" or (weight.isdigit() and int(weight) >= 600):
            css.append("font-weight:700")
        if props.get("font-style") == "italic":
            css.append("font-style:italic")
        if props.get("text-underline-style", "none") not in ("none", ""):
            css.append("text-decoration:underline")
        color = props.get("color", "")
        if _COLOR.match(color) and color.lower() != "#000000":
            css.append(f"color:{color}")
        return css

    # ---- 덩어리(문단·표·목록)
    def blocks(self, node) -> str:
        out = []
        for child in node:
            tag = child.tag
            if tag in (q("text:p"), q("text:h")):
                out.append(self.paragraph(child))
            elif tag == q("table:table"):
                out.append(self.table(child))
            elif tag in (q("text:list"), q("text:list-item"), q("text:list-header"),
                         q("text:section"), q("draw:text-box")):
                out.append(self.blocks(child))
            elif tag == q("draw:frame"):
                out.append(self.frame(child))
        return "".join(out)

    def paragraph(self, node) -> str:
        props = self.styles.get("paragraph", node.get(q("text:style-name")))
        css = []
        align = {"center": "center", "end": "right", "right": "right",
                 "justify": "justify"}.get(props.get("text-align", ""))
        if align:
            css.append(f"text-align:{align}")
        for name in ("margin-left", "margin-right", "margin-top", "margin-bottom", "text-indent"):
            value = px(props.get(name))
            if value:
                css.append(f"{name}:{_num(value)}px")
        height = props.get("line-height", "")
        if height.endswith("%"):
            try:
                css.append(f"line-height:{_num(max(100.0, float(height[:-1])) / 100)}")
            except ValueError:
                pass
        css += self._text_css(props)
        inner = self.inline(node, _pt(props.get("font-size")) or self.base_pt)
        if not re.sub(r"<span[^>]*>|</span>", "", inner).strip():
            inner += "&nbsp;"                # 빈 줄도 자리를 지킨다 — 공문은 빈 줄로 간격을 둔다
        style = f' style="{";".join(css)}"' if css else ""
        # <p> 를 쓰지 않는다. 에듀파인 공문은 머리 표를 문단 속 글상자에
        # 넣어 두는데, <p> 안에 표가 오면 브라우저가 문단을 거기서 끊어
        # 버려 모양이 무너진다.
        return f'<div class="od-p"{style}>{inner}</div>'

    def inline(self, node, size_pt: float) -> str:
        out = [esc(node.text or "")]
        for child in node:
            tag = child.tag
            if tag == q("text:s"):
                try:
                    count = min(int(child.get(q("text:c"), "1") or 1), 200)
                except ValueError:
                    count = 1
                out.append("&nbsp;" * count)
            elif tag == q("text:tab"):
                out.append('<span class="od-tab"></span>')
            elif tag == q("text:line-break"):
                out.append("<br>")
            elif tag == q("text:span"):
                props = self.styles.get("text", child.get(q("text:style-name")))
                css = self._text_css(props, size_pt)
                inner = self.inline(child, _pt(props.get("font-size")) or size_pt)
                out.append(f'<span style="{";".join(css)}">{inner}</span>' if css else inner)
            elif tag == q("draw:frame"):
                out.append(self.frame(child))
            elif tag in (q("office:annotation"), q("text:note-citation"),
                         q("text:bookmark"), q("text:bookmark-start"),
                         q("text:bookmark-end"), q("text:soft-page-break")):
                pass
            else:                             # 링크·번호 매기기 등은 글자만
                out.append(self.inline(child, size_pt))
            out.append(esc(child.tail or ""))
        return "".join(out)

    def frame(self, node) -> str:
        width = px(node.get(q("svg:width")))
        image = node.find(q("draw:image"))
        if image is not None and image.find(q("office:binary-data")) is None:
            return self.image(image.get(q("xlink:href"), ""), width)
        box = node.find(q("draw:text-box"))
        if box is not None:
            style = f' style="width:{_num(width)}px"' if width else ""
            return f'<div class="od-box"{style}>{self.blocks(box)}</div>'
        return '<span class="hx-obj">[개체]</span>'

    def image(self, href: str, width: float | None) -> str:
        suffix = href.rsplit(".", 1)[-1].lower()
        mime = _MIME.get(suffix)
        try:
            data = self.archive.read(href) if mime and not href.startswith(("/", "..")) else b""
        except KeyError:
            data = b""
        if not data or len(data) > IMAGE_MAX or self.image_bytes + len(data) > IMAGES_TOTAL:
            return '<span class="hx-obj">[그림]</span>'
        self.image_bytes += len(data)
        size = f' style="width:{_num(width)}px"' if width else ""
        return (f'<img class="od-img"{size} alt="" '
                f'src="data:{mime};base64,{base64.b64encode(data).decode("ascii")}">')

    def table(self, node) -> str:
        table_props = self.styles.get("table", node.get(q("table:style-name")))
        cols: list[float | None] = []
        for column in _columns(node):
            width = px(self.styles.get("table-column",
                                       column.get(q("table:style-name"))).get("column-width"))
            repeat = _repeat(column.get(q("table:number-columns-repeated")))
            cols.extend([width] * repeat)
            if len(cols) >= MAX_REPEAT:
                break
        total = px(table_props.get("width")) or (sum(c for c in cols if c) or None)

        out = ['<table class="od-table"']
        if total:
            out.append(f' style="width:{_num(total)}px"')
        out.append(">")
        if cols and all(cols):
            out.append("<colgroup>" + "".join(f'<col style="width:{_num(c)}px">'
                                               for c in cols[:MAX_REPEAT]) + "</colgroup>")
        for row in _rows(node):
            out.append("<tr>")
            for cell in row:
                if cell.tag == q("table:covered-table-cell"):
                    continue                  # 합쳐진 칸에 가려진 자리
                for _ in range(min(_repeat(cell.get(q("table:number-columns-repeated"))), 8)):
                    out.append(self.cell(cell))
            out.append("</tr>")
        out.append("</table>")
        return "".join(out)

    def cell(self, node) -> str:
        props = self.styles.get("table-cell", node.get(q("table:style-name")))
        css = []
        everywhere = _border(props.get("border"))
        for side in ("top", "right", "bottom", "left"):
            value = _border(props.get(f"border-{side}")) if f"border-{side}" in props else everywhere
            if value:
                css.append(f"border-{side}:{value}")
        background = props.get("background-color", "")
        if _COLOR.match(background) and background.lower() != "#ffffff":
            css.append(f"background:{background}")
        valign = {"middle": "middle", "bottom": "bottom", "top": "top"}.get(
            props.get("vertical-align", ""))
        if valign:
            css.append(f"vertical-align:{valign}")
        pad = [px(props.get(f"padding-{s}")) if f"padding-{s}" in props else px(props.get("padding"))
               for s in ("top", "right", "bottom", "left")]
        if any(p is not None for p in pad):
            css.append("padding:" + " ".join(f"{_num(max(0.0, p or 0))}px" for p in pad))
        attrs = ""
        for name, html in (("number-columns-spanned", "colspan"), ("number-rows-spanned", "rowspan")):
            span = _repeat(node.get(q(f"table:{name}")))
            if span > 1:
                attrs += f' {html}="{span}"'
        style = f' style="{";".join(css)}"' if css else ""
        return f"<td{attrs}{style}>{self.blocks(node)}</td>"


def _columns(table):
    """표의 열 정의. 칸 안에 든 표의 열까지 훑지 않도록 이 표의 것만."""
    for child in table:
        if child.tag == q("table:table-column"):
            yield child
        elif child.tag in (q("table:table-columns"), q("table:table-header-columns"),
                           q("table:table-column-group")):
            yield from _columns(child)


def _rows(table):
    """표의 행. 머리 행 묶음·행 묶음 안의 행도 차례대로 꺼낸다."""
    for child in table:
        if child.tag == q("table:table-row"):
            yield child
        elif child.tag in (q("table:table-header-rows"), q("table:table-rows"),
                           q("table:table-row-group")):
            yield from _rows(child)


def _repeat(value: str | None) -> int:
    try:
        return max(1, min(int(value or 1), MAX_REPEAT))
    except ValueError:
        return 1


def _pt(value: str | None) -> float | None:
    length = px(value)
    return length * 72 / 96 if length else None


# ------------------------------------------------------------------ 입구

def render(path: str | Path) -> str:
    """ODT 한 편을 미리보기 HTML 로. 쪽 폭은 data-width 로 알려 화면이 맞춰 줄인다."""
    with zipfile.ZipFile(path) as archive:
        content = ET.fromstring(archive.read("content.xml"))
        styles = Styles()
        try:
            styles.load(ET.fromstring(archive.read("styles.xml")))
        except (KeyError, ET.ParseError):
            pass
        styles.load(content.find(q("office:automatic-styles")))
        body = content.find(f"{q('office:body')}/{q('office:text')}")
        if body is None:
            return ""
        renderer = Renderer(archive, styles)
        inner = renderer.blocks(body)
    width = styles.page_width or 643          # A4 에 여백 2cm 씩일 때의 글 폭
    font = renderer.base_pt * 4 / 3
    full = width + PAGE_PAD * 2              # 화면은 border-box 라 여백까지 넣은 폭
    return (f'<div class="od-page" data-width="{_num(full)}" '
            f'style="width:{_num(full)}px;padding:{PAGE_PAD}px;font-size:{_num(font)}px">'
            f"{inner}</div>")

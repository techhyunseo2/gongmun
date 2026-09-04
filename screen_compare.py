"""화면 두 곳을 찍어 달라진 자리를 짚어 준다.

결재자가 말없이 고쳐서 결재한 공문을, 한글 창 두 개를 나란히 띄운 채
드래그로 영역만 지정하면 무엇이 달라졌는지 표시해 준다.

글자를 읽지 않는다(OCR 이 아니다). 모양만 본다:

1. 찍은 그림에서 글자가 있는 가로 띠(글줄)를 찾는다
2. 글줄마다 좌우 여백을 떼어 낸다 — 두 창의 위치가 달라도 맞물리게
3. 글줄끼리 맞춘다 — 줄이 끼어들어 아래가 밀려도 따라간다
4. 짝지어진 줄 안에서 칸 단위로 다시 비교해 달라진 구간을 돌려준다

표준 라이브러리만 쓴다. 화면은 `ctypes` 로 윈도우 GDI 를 직접 부르고,
맞추는 일은 `difflib` 가 한다. 새 꾸러미를 들이면 배포 라이선스 고지가
늘어난다.

**개인정보 — 지켜야 할 규칙**

화면에 무엇이 있을지 프로그램은 알 수 없다. 공문 폴더에 넣은 파일과
달리 이용자가 "이건 읽어도 된다" 고 정해 준 것이 아니다. 그래서:

- 지정한 사각형만 찍는다. 화면 전체를 미리 찍어 두지 않는다.
- 찍은 그림은 **메모리에만** 둔다. 저장소·임시파일·설정파일 어디에도
  쓰지 않는다. 이 파일에는 파일을 여는 코드가 없어야 한다.
- 예외 메시지에 찍은 내용을 담지 않는다. `widget.py` 의 전역 처리기가
  예외 메시지를 `.gongmun/오류기록.txt` 에 적고 안내창에도 띄운다.

`tests/test_screen_compare.py` 가 이 셋을 지킨다.
"""

from __future__ import annotations

import ctypes
import difflib
import sys
from ctypes import wintypes

# 이보다 어두우면 글자로 본다. 흐린 회색 글씨도 잡되 종이 바탕은 거른다.
INK = 140

# 칸을 이만큼씩 묶어 글줄끼리 맞춘다. 잘게 보면 느리고, 크게 묶으면 둔해진다.
BUCKET = 3

# 두 글줄이 이만큼도 안 닮았으면 같은 줄이 고쳐진 것으로 보지 않는다.
PAIRABLE = 0.55

# 이만큼 붙어 있는 표시 구간은 하나로 묶는다. 상자가 잘게 흩어지면 읽기 어렵다.
JOIN = 8

SAME, EDITED, ADDED, REMOVED = "same", "edited", "added", "removed"


class ScreenError(Exception):
    """찍거나 비교할 수 없는 경우.

    메시지에 찍은 내용을 담지 않는다 — 오류 기록에 그대로 남기 때문이다.
    """


class Shot:
    """찍은 그림 한 장. 밝기만 남긴다(색은 비교에 필요 없다)."""

    def __init__(self, width: int, height: int, grey: bytes):
        self.width, self.height, self.grey = width, height, grey

    def row_has_ink(self, y: int) -> bool:
        row = self.grey[y * self.width:(y + 1) * self.width]
        return any(v < INK for v in row)

    def columns(self, top: int, bottom: int) -> list[int]:
        """글줄 하나를 칸별로 훑어 어느 높이에 획이 있는지를 비트로 모은다.

        잉크의 양만 세면 획 수가 같은 글자(마/바)를 구별하지 못한다.
        실제로 항목 번호가 바뀐 것을 놓쳤다. 높이별 유무를 비트로 쌓으면
        같은 양이라도 모양이 다르면 값이 달라지고, 정수 하나라 비교 비용은
        그대로다.
        """
        out = [0] * self.width
        for step, y in enumerate(range(top, bottom)):
            row = self.grey[y * self.width:(y + 1) * self.width]
            bit = 1 << step
            for x in range(self.width):
                if row[x] < INK:
                    out[x] |= bit
        return out


class Change:
    """수정본에서 표시할 자리 하나."""

    def __init__(self, state: str, top: int, bottom: int,
                 spans: list[tuple[int, int]]):
        self.state, self.top, self.bottom, self.spans = state, top, bottom, spans

    def __repr__(self) -> str:   # 내용은 담지 않는다. 좌표뿐.
        return (f"Change({self.state}, y={self.top}~{self.bottom}, "
                f"{len(self.spans)}곳)")


# ------------------------------------------------------------------ 화면 찍기

class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def to_grey(raw: bytes) -> bytes:
    """32비트 화면 자료에서 초록 채널만 남긴다. 밝기 대신 쓰기 충분하다."""
    return bytes(raw[i + 1] for i in range(0, len(raw), 4))


def capture(left: int, top: int, width: int, height: int) -> Shot:
    """화면의 그 사각형만 찍는다. 바깥은 애초에 복사되지 않는다."""
    if sys.platform != "win32":
        raise ScreenError("화면 비교는 윈도우에서만 됩니다.")
    if width < 8 or height < 8:
        raise ScreenError("고른 자리가 너무 좁습니다. 조금 더 넓게 끌어 주세요.")

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    screen = user32.GetDC(0)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    try:
        gdi32.SelectObject(memory, bitmap)
        # SRCCOPY. 요청한 사각형만 옮긴다.
        if not gdi32.BitBlt(memory, 0, 0, width, height,
                            screen, left, top, 0x00CC0020):
            raise ScreenError("화면을 찍지 못했습니다. "
                              "보안 프로그램이 막고 있을 수 있습니다.")
        head = _BitmapInfoHeader()
        head.biSize = ctypes.sizeof(_BitmapInfoHeader)
        head.biWidth, head.biHeight = width, -height    # 음수 = 위에서 아래로
        head.biPlanes, head.biBitCount = 1, 32
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(head), 0)
        raw = buffer.raw
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(0, screen)
    return Shot(width, height, to_grey(raw))


# ------------------------------------------------------------------ 비교

def bands(shot: Shot, gap: int = 4) -> list[tuple[int, int]]:
    """글자가 있는 가로 띠. 사이가 gap 줄 이하로 벌어지면 같은 글줄로 본다."""
    ink = [shot.row_has_ink(y) for y in range(shot.height)]
    found, y = [], 0
    while y < shot.height:
        if not ink[y]:
            y += 1
            continue
        start, blank = y, 0
        while y < shot.height and blank <= gap:
            y += 1
            blank = 0 if (y < shot.height and ink[y]) else blank + 1
        found.append((start, y - blank))
    return [(a, b) for a, b in found if b - a >= 5]


def _trim(columns: list[int]) -> tuple[list[int], int]:
    """좌우 여백을 떼어 낸다. 두 창의 가로 위치가 달라도 맞물리게."""
    marked = [i for i, v in enumerate(columns) if v]
    if not marked:
        return [], 0
    return columns[marked[0]:marked[-1] + 1], marked[0]


def _sign(columns: list[int]) -> tuple:
    """글줄의 지문. 똑같이 그려진 줄은 똑같은 값이 나온다."""
    return tuple(sum(columns[i:i + BUCKET])
                 for i in range(0, len(columns), BUCKET))


def _ratio(one, other) -> float:
    # autojunk 는 꺼 둔다. difflib 은 열이 200개를 넘으면 자주 나오는 값을
    # 잡음으로 보고 버리는데, 여기 값은 글자 모양이지 잡음이 아니다.
    #
    # 다만 정직하게 적어 둔다 — 실제로 그려 본 글줄로 전수 확인했더니
    # 켜고 끄고가 결과를 바꾸지 않았다(200칸 넘는 줄 다섯 개 모두 동일).
    # 칸마다 획 위치를 비트로 쌓아 값이 제각각이라 버릴 만큼 흔한 값이
    # 없기 때문이다. 그래도 끄는 쪽이 뜻에 맞고 비용이 없어 그대로 둔다.
    return difflib.SequenceMatcher(None, one, other, autojunk=False).ratio()


def _spans(before: list[int], after: list[int]) -> list[tuple[int, int]]:
    """같은 글줄 안에서 달라진 칸 구간. 수정본 기준."""
    rough = []
    for tag, _, _, start, end in difflib.SequenceMatcher(
            None, before, after, autojunk=False).get_opcodes():
        if tag != "equal":
            rough.append((start, max(end, start + 2)))
    joined: list[list[int]] = []
    for start, end in rough:
        if joined and start - joined[-1][1] <= JOIN:
            joined[-1][1] = end
        else:
            joined.append([start, end])
    return [(a, b) for a, b in joined]


def compare(before: Shot, after: Shot) -> list[Change]:
    """두 그림을 견주어, 수정본에서 표시할 자리를 돌려준다."""
    rows_before, rows_after = bands(before), bands(after)
    if not rows_after:
        raise ScreenError("고른 자리에서 글자를 찾지 못했습니다. "
                          "글이 있는 곳을 끌어 주세요.")

    cut_before = [_trim(before.columns(*box)) for box in rows_before]
    cut_after = [_trim(after.columns(*box)) for box in rows_after]
    sign_before = [_sign(columns) for columns, _ in cut_before]
    sign_after = [_sign(columns) for columns, _ in cut_after]

    changes: list[Change] = []
    for tag, b1, b2, a1, a2 in difflib.SequenceMatcher(
            None, sign_before, sign_after, autojunk=False).get_opcodes():
        if tag == "equal":
            changes += [Change(SAME, rows_after[i][0], rows_after[i][1], [])
                        for i in range(a1, a2)]
        elif tag == "insert":
            changes += [_whole(rows_after[i], cut_after[i])
                        for i in range(a1, a2)]
        elif tag == "delete":
            changes += [Change(REMOVED, rows_before[i][0], rows_before[i][1], [])
                        for i in range(b1, b2)]
        else:
            changes += _paired(rows_before, cut_before, sign_before, b1, b2,
                               rows_after, cut_after, sign_after, a1, a2)
    return changes


def _whole(box, cut) -> Change:
    """줄이 통째로 새로 생긴 경우. 그 줄 전체를 표시한다."""
    columns, offset = cut
    return Change(ADDED, box[0], box[1], [(offset, offset + len(columns))])


def _paired(rows_before, cut_before, sign_before, b1, b2,
            rows_after, cut_after, sign_after, a1, a2) -> list[Change]:
    """바뀐 덩어리. 닮은 줄끼리 짝지어 고쳐진 것으로 본다."""
    taken: set[int] = set()
    out = []
    for after in range(a1, a2):
        best, score = None, PAIRABLE
        for before in range(b1, b2):
            if before in taken:
                continue
            found = _ratio(sign_before[before], sign_after[after])
            if found > score:
                best, score = before, found
        if best is None:
            out.append(_whole(rows_after[after], cut_after[after]))
            continue
        taken.add(best)
        offset = cut_after[after][1]
        spans = [(offset + start, offset + end)
                 for start, end in _spans(cut_before[best][0],
                                          cut_after[after][0])]
        out.append(Change(EDITED, rows_after[after][0], rows_after[after][1],
                          spans))
    return out

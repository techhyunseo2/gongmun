"""스스로 업데이트하기.

GitHub 릴리스에 새 버전이 올라와 있으면 내려받아 자기 자신을 갈아 끼운다.
받아 쓰는 분들이 새 파일을 다시 내려받아 설치할 일이 없어진다.

윈도우는 실행 중인 exe를 지우지는 못해도 이름을 바꾸는 것은 허용한다.
그 성질을 이용해 지금 파일을 .old 로 밀어 두고 새 파일을 그 자리에 놓는다.
.old 는 다음에 켤 때 지운다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote

from app import UPDATE_REPO, VERSION

LATEST = "https://github.com/{repo}/releases/latest"
DOWNLOAD = "https://github.com/{repo}/releases/download/{tag}/{asset}"
API = "https://api.github.com/repos/{repo}/releases/latest"
# 내려받을 실행 파일 이름. 반드시 영문이어야 한다 — GitHub 릴리스가 한글
# 첨부 파일명을 제멋대로 바꿔서(공문정리함.exe → default.exe) 이 주소가
# 404 가 나고 "내려받다가 끊겼습니다" 로 실패하기 때문. 평소에는 API 로
# 실제 첨부 주소를 확인하고, API 가 막히면 이 이름으로 주소를 만든다.
ASSET_NAME = "gongmun.exe"
MIN_EXE_BYTES = 5_000_000
TIMEOUT = 20


class UpdateError(Exception):
    pass


# ------------------------------------------------------------------ 버전

def _as_numbers(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV")
    parts = []
    for chunk in cleaned.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(candidate: str, current: str = VERSION) -> bool:
    return _as_numbers(candidate) > _as_numbers(current)


# ------------------------------------------------------------------ 확인

def check() -> dict | None:
    """새 버전이 있으면 {'version', 'url', 'notes'}, 없으면 None.

    api.github.com 은 로그인 없이 쓰면 IP 하나당 한 시간에 60번까지만
    받아 준다. 학교처럼 여러 대가 같은 공인 IP를 쓰는 곳에서는 걸릴 수
    있으므로, 평소에는 API 대신 releases/latest 주소가 어디로 넘어가는지만
    본다. 이 요청은 그 제한에 걸리지 않는다.
    """
    if not UPDATE_REPO or "/" not in UPDATE_REPO:
        raise UpdateError("업데이트 주소가 설정되어 있지 않습니다.")

    tag = _latest_tag()
    if not is_newer(tag):
        return None

    info = _release_info()
    fallback = DOWNLOAD.format(repo=UPDATE_REPO, tag=quote(tag),
                               asset=quote(ASSET_NAME))
    return {
        "version": tag.lstrip("vV"),
        "url": info.get("asset_url") or fallback,
        "notes": info.get("notes", ""),
    }


def _latest_tag() -> str:
    """releases/latest 가 어느 태그로 넘어가는지 본다."""
    request = urllib.request.Request(
        LATEST.format(repo=UPDATE_REPO),
        method="HEAD",
        headers={"User-Agent": "gongmun"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            final = response.url
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("아직 올라온 버전이 없습니다.") from exc
        raise UpdateError(f"확인하지 못했습니다. (오류 {exc.code})") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise UpdateError("인터넷에 연결되어 있는지 확인해 주세요.") from exc

    if "/tag/" not in final:
        raise UpdateError("버전을 알아내지 못했습니다.")
    return unquote(final.rsplit("/tag/", 1)[1].strip("/"))


def _release_info() -> dict:
    """API 한 번으로 설명글과 '실제로 올라와 있는' exe 주소를 함께 가져온다.

    api.github.com 은 IP 하나당 시간당 60번 제한이 있어 실패할 수 있다.
    실패하면 빈 dict 를 돌려주고, 부르는 쪽이 ASSET_NAME 으로 주소를
    직접 만든다. 첨부가 여럿이면(설치 파일 + 실행 파일) 더 작은 쪽이
    PyInstaller 실행 파일이다.
    """
    request = urllib.request.Request(
        API.format(repo=UPDATE_REPO),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "gongmun"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            release = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return _parse_release(release)


def _parse_release(release: dict) -> dict:
    """API 응답에서 설명글과 내려받을 exe 주소를 뽑는다."""
    info = {"notes": (release.get("body") or "").strip()[:400]}
    exes = [a for a in release.get("assets", [])
            if str(a.get("name", "")).lower().endswith(".exe")
            and a.get("state", "uploaded") == "uploaded"
            and a.get("browser_download_url")]
    if exes:
        chosen = min(exes, key=lambda a: a.get("size") or 0)
        info["asset_url"] = chosen["browser_download_url"]
    return info


# ------------------------------------------------------------------ 설치

def _download(url: str, dest: Path) -> None:
    """새 exe 를 내려받아 dest 에 저장한다. 온전하지 않으면 예외를 던진다.

    학교 인터넷은 중간에 잘 끊긴다. 한 번은 다시 시도하고, 다 받은 파일이
    Content-Length 와 맞는지, 실행 파일이라 할 만한 크기인지 확인한다.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "gongmun"})
    last: Exception | None = None

    for _ in range(2):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                expected = int(response.headers.get("Content-Length") or 0)
                with dest.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
        except urllib.error.HTTPError as exc:
            dest.unlink(missing_ok=True)
            raise UpdateError(
                "받을 파일을 찾지 못했습니다. 설치 파일을 새로 내려받아 "
                f"다시 설치해 주세요. (오류 {exc.code})") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
            continue

        size = dest.stat().st_size
        if size >= MIN_EXE_BYTES and (not expected or size == expected):
            return
        last = UpdateError(f"파일이 덜 받아졌습니다. ({size:,}바이트)")

    dest.unlink(missing_ok=True)
    raise UpdateError("내려받다가 끊겼습니다. 잠시 뒤 다시 해 보세요.") from last


def apply(url: str) -> Path:
    """새 파일을 내려받아 지금 실행 파일 자리에 놓는다. 새 파일 경로를 돌려준다."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("소스로 실행 중일 때는 자동 업데이트를 쓸 수 없습니다.")

    current = Path(sys.executable).resolve()
    downloaded = Path(tempfile.gettempdir()) / "gongmun_new.exe"

    _download(url, downloaded)

    backup = current.with_suffix(current.suffix + ".old")
    backup.unlink(missing_ok=True)
    try:
        current.rename(backup)                 # 실행 중이어도 이름은 바꿀 수 있다
        shutil.move(str(downloaded), str(current))
    except OSError as exc:
        if backup.exists() and not current.exists():
            backup.rename(current)             # 실패했으면 되돌린다
        raise UpdateError("파일을 바꾸지 못했습니다. 설치 폴더 권한을 확인해 주세요.") from exc
    return current


def restart() -> None:
    """새 파일로 다시 띄우고 지금 것은 끝낸다."""
    exe = Path(sys.executable)
    try:
        subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)
    except OSError:
        pass
    os._exit(0)


def clean_leftovers() -> None:
    """지난번 업데이트가 남긴 .old 파일을 지운다."""
    if not getattr(sys, "frozen", False):
        return
    folder = Path(sys.executable).resolve().parent
    for stale in folder.glob("*.old"):
        try:
            stale.unlink()
        except OSError:
            pass                                # 아직 물려 있으면 다음에 지운다

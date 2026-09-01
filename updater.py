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
ASSET_NAME = "공문정리함.exe"
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

    return {
        "version": tag.lstrip("vV"),
        "url": DOWNLOAD.format(repo=UPDATE_REPO, tag=quote(tag),
                               asset=quote(ASSET_NAME)),
        "notes": _release_notes(),
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


def _release_notes() -> str:
    """설명글은 있으면 좋고 없어도 그만이라 실패해도 조용히 넘어간다."""
    request = urllib.request.Request(
        API.format(repo=UPDATE_REPO),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "gongmun"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            release = json.loads(response.read().decode("utf-8"))
        return (release.get("body") or "").strip()[:400]
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------ 설치

def apply(url: str) -> Path:
    """새 파일을 내려받아 지금 실행 파일 자리에 놓는다. 새 파일 경로를 돌려준다."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("소스로 실행 중일 때는 자동 업데이트를 쓸 수 없습니다.")

    current = Path(sys.executable).resolve()
    downloaded = Path(tempfile.gettempdir()) / "공문정리함_새버전.exe"

    request = urllib.request.Request(url, headers={"User-Agent": "gongmun"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, \
             downloaded.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        downloaded.unlink(missing_ok=True)
        raise UpdateError("내려받다가 끊겼습니다. 잠시 뒤 다시 해 보세요.") from exc

    if downloaded.stat().st_size < 1_000_000:
        downloaded.unlink(missing_ok=True)
        raise UpdateError("내려받은 파일이 온전하지 않습니다.")

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

# PyInstaller 설정 — 파이썬이 없는 컴퓨터에서도 도는 실행 파일 하나를 만든다.
#   pyinstaller build.spec
# 결과: dist/gongmun.exe
#
# exe 이름은 반드시 영문이어야 한다. GitHub 릴리스는 한글이 든 첨부
# 파일명을 제멋대로 바꿔 버려서(공문정리함.exe → default.exe), 자동
# 업데이트가 그 파일을 찾지 못하고 "내려받다가 끊겼습니다" 로 실패한다.
# 사용자에게 보이는 이름은 설치 후 바로가기(installer.iss의 AppName,
# "공문 정리함")가 담당하므로 exe 파일명이 영문이어도 상관없다.

a = Analysis(
    ["widget.py"],
    pathex=["."],
    binaries=[],
    datas=[("ui.html", ".")],
    hiddenimports=["olefile", "pypdf", "openpyxl", "xlrd", "app", "store",
                   "classify", "extract", "hwpx_view", "updater", "organize"],
    hookspath=[],
    runtime_hooks=[],
    # 쓰지 않는 큰 덩어리를 빼서 파일 크기를 줄인다
    excludes=["numpy", "pandas", "matplotlib", "scipy", "PIL", "pytest", "playwright"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="gongmun",
    icon="icon.ico",
    console=False,          # 검은 명령 창을 띄우지 않는다
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

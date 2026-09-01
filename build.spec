# PyInstaller 설정 — 파이썬이 없는 컴퓨터에서도 도는 실행 파일 하나를 만든다.
#   pyinstaller build.spec
# 결과: dist/공문정리함.exe
#
# 파일 이름을 영문으로 둔 이유: 윈도우 명령창이 한글 파일명을 잘못 읽는 일이
# 있어서다. 만들어지는 exe 이름은 아래 name 값을 따르므로 한글 그대로 나온다.

a = Analysis(
    ["widget.py"],
    pathex=["."],
    binaries=[],
    datas=[("ui.html", ".")],
    hiddenimports=["olefile", "pypdf", "app", "store", "classify", "extract",
                   "hwpx_view", "updater"],
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
    name="공문정리함",
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

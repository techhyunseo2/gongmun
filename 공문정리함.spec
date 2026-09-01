# PyInstaller 설정 — 파이썬이 없는 컴퓨터에서도 도는 실행 파일 하나를 만든다.
#   pyinstaller 공문정리함.spec
# 결과: dist/공문정리함.exe

block_cipher = None

analysis = Analysis(
    ["widget.py"],
    pathex=["."],
    binaries=[],
    datas=[("ui.html", "."), ("icon.ico", ".")],
    hiddenimports=["olefile", "pypdf", "app", "store", "classify", "extract", "hwpx_view"],
    hookspath=[],
    runtime_hooks=[],
    # 쓰지 않는 큰 덩어리를 빼서 파일 크기를 줄인다
    excludes=["numpy", "pandas", "matplotlib", "scipy", "PIL", "pytest",
              "unittest", "test", "tkinter.test", "playwright"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
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
    version="version.txt",
)

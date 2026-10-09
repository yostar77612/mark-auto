# Windows x64 onedir: LGPL Qt shared libraries remain replaceable.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'desktop.py')], pathex=[str(root)],
    datas=[(str(root / 'examples'), 'examples'),
           (str(root / 'LICENSE'), '.'),
           (str(root / 'packaging' / 'THIRD_PARTY_NOTICES.md'), '.'),
           (str(root / 'build' / 'licenses'), 'licenses')] + collect_data_files('tzdata'),
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'streamlit', 'shioaji', 'trader', 'PyQt5', 'PyQt6'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='MarkAuto',
          debug=False, strip=False, upx=False, console=False, target_arch='x86_64')
coll = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='MarkAuto')

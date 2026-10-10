# Windows x64 onedir: LGPL Qt shared libraries remain replaceable.
from pathlib import Path
import sys
import runpy
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
root = Path(SPECPATH).parent
from quantlab.sqlite_runtime import verify, verify_binaries
# Fail before freezing if dependency analysis would collect an unpinned DLL.
verify(root / 'packaging/sqlite-runtime.json', Path(sys.base_prefix))
# Strict actual build verification is separate from structural spec inspection.
from quantlab.local_ai import collect_support_binaries
local_ai_binaries = collect_support_binaries()
analysis = Analysis(
    [str(root / 'desktop.py')], pathex=[str(root)],
    binaries=local_ai_binaries,
    runtime_hooks=[str(root / 'packaging/sqlite_runtime_hook.py')],
    datas=[(str(root / 'packaging/sqlite-runtime.json'), '.'),
           (str(root / 'packaging' / 'local_ai'), 'packaging/local_ai'),
           (str(root / 'examples'), 'examples'),
           (str(root / 'desktop_chatgpt_auth.py'), '.'),
           (str(root / 'desktop_chatgpt_provider.py'), '.'),
           (str(root / 'desktop_chatgpt_dependency_manifest.json'), '.'),
           (str(root / 'packaging' / 'third_party' / 'README.md'), 'licenses/chatgpt-auth-provenance'),
           (str(root / 'LICENSE'), '.'),
           (str(root / 'packaging' / 'THIRD_PARTY_NOTICES.md'), '.'),
           (str(root / 'build' / 'licenses'), 'licenses'),
           # Engine provenance hashes read these exact source bytes via __file__.
           (str(root / 'quantlab' / 'core.py'), 'quantlab'),
           (str(root / 'quantlab' / 'data.py'), 'quantlab'),
           (str(root / 'quantlab' / 'strategies.py'), 'quantlab'),
           (str(root / 'quantlab' / 'backtest.py'), 'quantlab'),
           (str(root / 'quantlab' / 'research.py'), 'quantlab'),
           (str(root / 'quantlab' / 'walk_forward.py'), 'quantlab'),
           (str(root / 'quantlab' / 'saved_candidate_pool.py'), 'quantlab'),
           (str(root / 'quantlab' / 'provider.py'), 'quantlab'),
           (str(root / 'quantlab' / 'manual_exchange.py'), 'quantlab')] + collect_data_files('tzdata')
          + [entry for name in ('PyJWT', 'cryptography', 'cffi', 'pycparser')
             for entry in copy_metadata(name)],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
                   # Lazy JWT import must be visible to native upstream hooks.
                   'jwt', 'cryptography', 'cryptography.hazmat.bindings._rust',
                   'cffi', '_cffi_backend', 'pycparser'],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtVirtualKeyboard', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
              'streamlit', 'shioaji', 'trader', 'PyQt5', 'PyQt6'],
    noarchive=False,
)
# QtGui's upstream hook collects optional plugins regardless of direct imports.
# Remove reviewed VirtualKeyboard/PDF and optional OpenSSL-backend components
# from all TOCs; preserve Windows Schannel and Python HTTPS. Independently audit
# actual output after freezing, including retained native dependency hashes.
qt_licenses = runpy.run_path(str(root / 'packaging/qt_licenses.py'))
analysis.binaries = qt_licenses['filter_payload_toc'](analysis.binaries)
analysis.datas = qt_licenses['filter_payload_toc'](analysis.datas)
# Native SQLite is not a pip distribution. Check the actual collected library.
verify_binaries(analysis.binaries, root / 'packaging/sqlite-runtime.json')
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='MarkAuto',
          version=str(root / 'build/markauto-version.txt'),
          debug=False, strip=False, upx=False, console=False, target_arch='x86_64')
coll = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='MarkAuto')

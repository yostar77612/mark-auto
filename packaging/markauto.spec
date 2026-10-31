# Windows x64 onedir: LGPL Qt shared libraries remain replaceable.
from pathlib import Path
import sys
import runpy
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
root = Path(SPECPATH).parent
from quantlab.sqlite_runtime import verify, verify_binaries
# Fail before freezing if dependency analysis would collect an unpinned DLL.
verify(root / 'packaging/sqlite-runtime.json', Path(sys.base_prefix))
# Offline remains the original Analysis unchanged. SDK collection is a separate
# explicit build flavor, never a runtime environment or account-permission flag.
broker_package = runpy.run_path(str(root / 'packaging/broker_package.py'))
Analysis = broker_package['configure_analysis'](Analysis, root, copy_metadata)
analysis = Analysis(
    [str(root / 'desktop.py')], pathex=[str(root)],
    binaries=[],
    runtime_hooks=[str(root / 'packaging/sqlite_runtime_hook.py')] + [str(root / 'packaging/early_multiprocessing_runtime_hook.py')],
    datas=[(str(root / 'packaging/sqlite-runtime.json'), '.'),
           (str(root / 'packaging/markauto.ico'), 'packaging'),
           (str(root / 'examples'), 'examples'),
           (str(root / 'quantlab/data_files/taifex_expiries.json'), 'quantlab/data_files'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/auth.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/provider.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/vault.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/identity.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/loopback.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/account_summary.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/account_paths.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/response_stream.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/transport.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/provenance.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/account_store.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/resolution_audit.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/unknown_reconciliation.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/finished_reconciliation.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/campaign_receipts.py'), 'quantlab/assistant/adapters/chatgpt'),
           (str(root / 'quantlab/assistant/domain/auth_protocol.py'), 'quantlab/assistant/domain'),
           (str(root / 'quantlab/assistant/domain/auth_tokens.py'), 'quantlab/assistant/domain'),
           (str(root / 'quantlab/assistant/domain/plan_protocol.py'), 'quantlab/assistant/domain'),
           (str(root / 'quantlab/assistant/domain/source_components.py'), 'quantlab/assistant/domain'),
           (str(root / 'quantlab/assistant/ports/auth.py'), 'quantlab/assistant/ports'),
           (str(root / 'quantlab/research_core/domain/receipts.py'), 'quantlab/research_core/domain'),
           (str(root / 'quantlab/assistant/domain/__init__.py'), 'quantlab/assistant/domain'),
           (str(root / 'quantlab/assistant/ports/__init__.py'), 'quantlab/assistant/ports'),
           (str(root / 'quantlab/research_core/domain/__init__.py'), 'quantlab/research_core/domain'),
           (str(root / 'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json'), 'quantlab/assistant/adapters/chatgpt'),
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
           (str(root / 'quantlab' / 'research_analysis.py'), 'quantlab'),
           (str(root / 'quantlab' / 'indicators.py'), 'quantlab'),
           (str(root / 'quantlab' / 'provider.py'), 'quantlab'),
           (str(root / 'quantlab' / 'manual_exchange.py'), 'quantlab')]
          # v2 profiles verify these exact source bytes in the frozen runtime.
          + [(str(p), p.parent.relative_to(root).as_posix())
             for p in sorted((root / 'quantlab' / 'trading').rglob('*.py'))]
          + collect_data_files('tzdata')
          + [entry for name in ('PyJWT', 'cryptography', 'cffi', 'pycparser')
             for entry in copy_metadata(name)],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
                   'quantlab.research_core.adapters.workspace_store',
                   'quantlab.research_core.adapters.settings_store',
                   'quantlab.research_core.adapters.state_json',
                   'quantlab.research_core.adapters.runtime_safety',
                   'quantlab.research_core.adapters.event_log',
                   'quantlab.research_core.adapters.walk_forward_owner',
                   'quantlab.research_core.application.job_manager',
                   'desktop_app.research_bootstrap',
                   'desktop_app.research_session',

                   # Lazy JWT import must be visible to native upstream hooks.
                   'jwt', 'cryptography', 'cryptography.hazmat.bindings._rust',
                   'cffi', '_cffi_backend', 'pycparser'],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtVirtualKeyboard', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
              'streamlit', 'shioaji', 'trader', 'archives', 'archives.legacy_autotrading', 'legacy_autotrading', 'gui', 'run', 'PyQt5', 'PyQt6'],
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
          icon=str(root / 'packaging/markauto.ico'),
          version=str(root / 'build/markauto-version.txt'),
          debug=False, strip=False, upx=False, console=False, target_arch='x86_64')
coll = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='MarkAuto')

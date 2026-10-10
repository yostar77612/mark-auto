# Windows native desktop distribution

Target: Windows 10 22H2 x64 and Windows 11 x64. End users install the EXE; Python,
pip and Git are bundled/not required. Qt Widgets creates a native desktop window.
Install defaults to `%LOCALAPPDATA%\Programs\MarkAuto`, without admin rights;
Start-menu and desktop shortcuts are created. Uninstall via Windows Settings. Close the app yourself first: installer and
uninstaller refuse while it is running, never force-close jobs or auto-relaunch it.
User data lives separately at `%LOCALAPPDATA%\MarkAuto` and is retained by upgrade
and uninstall. Remove that directory yourself only if you intend to erase data.

## Repeatable developer build

Build on Windows x64 with Python 3.13.16 and PowerShell, from the repository root:

    ./packaging/build.ps1 -Version 0.2.1
    ./packaging/test_installer.ps1 -Version 0.2.1
    python packaging/build_manifest.py

Only developers need Python. The hash-locked Windows dependency closure and
pinned official Inno Setup 6.4.3 installer produce `dist/installers/*-setup.exe`.
The `0.0.0` fixture tests installer version upgrade and is not shipped. It uses
the same app payload; this is not proof of historical schema migration.
PyInstaller onedir keeps Qt DLLs replaceable. See THIRD_PARTY_NOTICES.md.

The pinned GitHub Actions workflow builds on **Windows Server 2022**, records exact
OS/image/build/dependencies/inputs/artifact SHA256, then exercises installation,
bundled runtime launch with developer tools removed from PATH, shortcut existence,
real Start-menu window launch, upgrade, normal close and data-preserving uninstall.
Removing tools from PATH is useful isolation, but not a clean client-OS test.
PE timestamps can vary; repeatable inputs do not imply byte-identical binaries.

PR runs upload CI artifacts only. Trusted main pushes/manual main runs and
`desktop-v*` tags publish a GitHub **prerelease** after installer tests and same-workflow security gates succeed. Publication also
requires a successful exact-SHA Quantlab workflow with every job passing; absent
or failed evidence blocks publication.
The release job alone receives ephemeral built-in `GITHUB_TOKEN` contents:write.
No persistent secret, paid build service or signing certificate is required.
Each release includes the installer, verification logs/manifests/checksums, and
corresponding Qt/PySide source archives verified against official SHA256 files.

## Explicit release blockers

- Clean Windows 10 22H2 x64 install/launch/upgrade/uninstall: **BLOCKED, not run**.
- Clean Windows 11 x64 install/launch/upgrade/uninstall: **BLOCKED, not run**.
- Windows Server CI is not evidence that either client target passed.
- Installer is **unsigned**. Windows may show unknown publisher / SmartScreen
  warnings. No certificate is bought and no security bypass is recommended.
- Current automation is a preview gate, not production acceptance or financial
  correctness certification. Test broker/AI workflows separately; real orders
  remain disabled unless the application explicitly supports and authorizes them.

For clean client acceptance, use disposable standard-user Win10 22H2 and Win11
x64 VMs without Python/pip/Git, record OS edition/version/build + installer SHA256,
install normally, launch both shortcuts, complete offline example and paper
workflows, close/reopen, upgrade while preserving saved data, uninstall and verify
only app files/shortcuts are removed. Test Chinese paths/display scaling and ensure
credentials never appear in logs. Record exact failures, not just screenshots.

## Primary upstream references (checked 2026-10-09)

- Qt 6.12 Windows 10 1809+/Windows 11 support; last Qt version for Win10:
  https://doc.qt.io/qt-6.12/supported-platforms.html
- PySide6 6.12.0 wheels: https://pypi.org/project/PySide6/6.12.0/
- PyInstaller distribution exception: https://pyinstaller.org/en/stable/license.html
- Inno 6.4.3 permissive license:
  https://github.com/jrsoftware/issrc/blob/is-6_4_3/license.txt
- Inno official binary digest:
  https://api.github.com/repos/jrsoftware/issrc/releases/tags/is-6_4_3
- Inno current commercial terms differ; do not silently upgrade builder:
  https://jrsoftware.org/isorder-terms.php

## Python runtime security decision

CPython 3.13.16 (2026-09-30) replaces the initial diagnostic 3.12.10 build.
3.12.10 predates later security fixes, and newer 3.12 releases have no Windows
installers. The official 3.13.16 x64 installer was downloaded and its SHA256
matched Python.org; metadata is recorded in `python-runtime.json`. CI obtains
that exact version through the pinned setup-python action, and the build
asserts the actual interpreter version/bitness before dependency installation.
The hash-locked complete Windows dependency closure resolves for Python 3.13;
actual frozen runtime behavior still must pass Windows CI.

Python 3.13 supports Windows 8.1+, Qt 6.12 supports Windows 10 1809+ and Windows11,
and PyInstaller 6.22.3 supports Python 3.8–3.15 / Windows8+. Product minimum stays
**Windows 10 22H2 x64**, not broadened by upstream support. 3.13.16 is itself the
last full maintenance release; future security updates require reevaluation of
a maintained Windows binary line, not indefinitely retaining this pin.

- https://www.python.org/downloads/release/python-31316/
- https://www.python.org/downloads/release/python-31215/
- https://docs.python.org/3.13/using/windows.html
- https://pypi.org/project/pyinstaller/6.22.3/

## 0.2.0 actual-version upgrade and client kit

New installs use a fresh `payloads/<version>/<attempt>` directory; the compiled
inventory digest, every file digest and exact file count must match before
shortcuts target that payload. Prior payloads are retained for recovery, not mixed
with new DLLs. Default per-user root and separate AppData remain unchanged.
See [update recovery](update_recovery.md) for interruption, retry, split shortcuts
and retained/orphan payload disk usage. No wildcard cleanup is performed.

CI downloads the exact released0.1.2 installer via `fetch_baseline.py` with pinned
SHA/size/source metadata. The Windows recovery harness performs a real extraction
process interruption and rerun, separately identifying a constructed shortcut
interruption state. This is not exhaustive hardware-power-loss verification.

The release includes `MarkAuto-0.2.0-clean-windows-acceptance.zip`: old/new EXEs,
independent manifests, shared lifecycle tests, built-in PowerShell-only clean-client
preflight and manual acceptance runbook. See [clean-client guide](clean_windows_README.md).
Generating the kit or passing Server CI never passes clean Windows10/11 gates.

Local model validation tooling is developer-only and opt-in; no Qwen model/runtime
is bundled or downloaded automatically by this installer. Desktop users configure
their own compatible endpoint. Structured JSON Schema mode means constrained
built-in-family parameter generation, not arbitrary program generation.


## 0.2.1 official subscription packaging

The Windows build explicitly requires all pinned authentication dependencies and
source/metadata provenance before the complete test suite. The normal frozen
smoke additionally verifies native CFFI, parser, OpenSSL, RS256/JWK identity and
nonce/audience rejection with fresh synthetic keys while network calls are blocked.
It does not register a host, grant an account, contact a model or prove eligibility.
Source hashes and dependency metadata are bundled for runtime admission; missing
or mismatched items block subscription research. Original seven smoke operations
and the market/manual checks remain required.

The fixed reviewed native notice archive is retained unextracted under licenses,
with provenance explained in third_party/README.md. Default networking, paid API
fallback and real-money trading remain disabled. The current clean-client kit
contains the actual released0.2.0 baseline and0.2.1 candidate; build-manifest and
installer hashes must match before either is run. Clean Windows10/11 and real
user-grant acceptance remain separate from Windows Server engineering CI.

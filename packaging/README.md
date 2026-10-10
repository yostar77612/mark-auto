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

    ./packaging/build.ps1 -Version 0.2.2
    ./packaging/test_installer.ps1 -Version 0.2.2
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


## 0.2.2 normal-workflow and history acceptance

Build defaults target0.2.2. Upgrade and standalone client kit use the actually downloaded, source/size/SHA-pinned0.2.1 release as baseline. Existing0.2.1 documentation above remains historical. The original seven research/Paper smoke operations, two manual exchange operations and offline native auth checks remain required; independent history_smoke additionally executes the real bounded history worker, reloads its cache and renders three products across eight timeframes. Its invented30tick CSV is labelledsynthetic and never implies actualexchange/client/model acceptance. Missing module, forgedresult, corruptedsource/cache or timeout fails the complete smoke.

Normal typedexpiry/date input and effective-dated Paper margins are included. Existing scalar PaperReplay callers retain their binding. Desktop schedule mode refuses an incompatible old replay at the same path without modifying its journal or generating replacement orders; retain and reconcile prior state, never erase it to bypass validation. No broker/live order capability is enabled.


### Pinned native SQLite and replay safety

The tested Windows Python 3.11/3.12 profiles and packaged CPython 3.13.16 stay
unchanged. `tools/install_sqlite_runtime.py` copies the full Windows base Python
into a new private build directory, then replaces only that copy's SQLite DLL
with official SQLite 3.54.0. It rejects existing/overlapping destinations and
verifies that the original DLL remains unchanged. Always start from an ordinary
base interpreter, not a venv. Remove an old build/sqlite-python directory manually
before repeating a package build; the setup script never overwrites a runtime.
Use that copy's `python.exe` for source execution and all build/test commands.
It is not a relocatable Python redistributable; PyInstaller creates the final app.

Linux CI compiles the same pinned official amalgamation using the runner's C
compiler and scopes the resulting `libsqlite3.so.0` through job-local
LD_LIBRARY_PATH. It never installs to /usr or changes the system SQLite package.
Setup downloads are online; application and original offline test workloads have
no new network requirement. No durability setting or test timeout is changed.

The pin was verified against the official download page on 2026-10-10, including
published SHA3-256 archive digests and the release's sqlite3.c digest/source ID.
3.51.3 is the minimum upstream WAL-reset fix; 3.54.0 was chosen as the current
published binary/source pair with cumulative upstream fixes. It includes newer
query/planner and floating conversion changes, so full original tests, native
Windows timing gates, and frozen lifecycle tests remain required; a setup probe
is not acceptance. See https://www.sqlite.org/changes.html and
https://www.sqlite.org/wal.html#walresetbug.

Every provisioned runtime is probed in a fresh child using real
SELECT sqlite_version(), sqlite_source_id(), actual loaded native-library path,
its SHA256 and compile options. Frozen startup runs the same exact-version,
source-ID, in-bundle-path and DLL-digest checks, including frozen child processes.
PyInstaller also fails if analysis selects any different SQLite DLL. Setup and
build manifests retain the native provenance because pip-audit alone cannot
certify a non-wheel SQLite DLL. Source pin, compiler and output digest are saved
for Linux; locally compiled Linux binaries are not claimed bit-identical.

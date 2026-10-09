# Windows native desktop distribution

Target: Windows 10 22H2 x64 and Windows 11 x64. End users install the EXE; Python,
pip and Git are bundled/not required. Qt Widgets creates a native desktop window.
Install defaults to `%LOCALAPPDATA%\Programs\MarkAuto`, without admin rights;
Start-menu and desktop shortcuts are created. Uninstall via Windows Settings.
User data lives separately at `%LOCALAPPDATA%\MarkAuto` and is retained by upgrade
and uninstall. Remove that directory yourself only if you intend to erase data.

## Repeatable developer build

Build on Windows x64 with Python 3.12.10 and PowerShell, from the repository root:

    ./packaging/build.ps1 -Version 0.1.1
    ./packaging/test_installer.ps1 -Version 0.1.1
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

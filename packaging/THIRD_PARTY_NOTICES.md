# Third-party software and replaceable Qt libraries

Mark Auto is Apache-2.0; its LICENSE accompanies this application. This distribution
includes Python (PSF license), PySide6/Shiboken6 and Qt 6.12.0 (open-source licenses,
including LGPL-3.0), tzdata (Apache-2.0/public-domain data), and the PyInstaller
bootloader (GPL with its distribution exception). Copies of installed dependency
license/notice files are under `_internal/licenses`. Python's license is included
there too. Available upstream wheel notices are retained. Explicit full GNU GPLv3
and LGPLv3 texts, Qt component attribution, reviewed module scope and exact
source-archive links/hashes are in `_internal/licenses/qt/`. See `QT-NOTICE.txt`
and `manifest.json` there. `QT-NATIVE-NOTICES.zip` preserves native codec,
Core/Gui/Network/Qml, Mesa/LLVM and identified OpenSSL license texts with exact
source-version URLs and copyright notices; identical texts share one hash.
The Microsoft runtime files have separate terms.
This notice does not relicense Qt or Microsoft code under Apache-2.0.

The shipped Qt module/plugin scope is audited from the actual frozen payload.
Unused Qt Virtual Keyboard and Qt PDF components are excluded; Windows' qwindows
platform plugin remains for native windowing and input-method integration.
The optional Qt OpenSSL backend and its affected OpenSSL 3.5.5 -x64 DLL pair
are excluded. Qt Schannel/certificate-only backends and Python's separately
named OpenSSL 3.5.9 libraries remain.
Qt Core/Gui/Widgets and other included LGPL modules are used dynamically, not statically. The onedir distribution
keeps their DLLs replaceable under `_internal/PySide6` and associated plugins.
You may replace LGPL-covered libraries with compatible modified versions and
reverse-engineer this application to debug those modifications as LGPL permits.
Keep the matching ABI, architecture, dependency DLLs and plugin versions. No
signature check prevents library replacement. This permission supersedes any
contrary restriction for these LGPL purposes.

Corresponding upstream source for the exact unmodified libraries:
- PySide6/Shiboken6 6.12.0: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/
- Qt 6.12.0: https://download.qt.io/official_releases/qt/6.12/6.12.0/single/
- Qt licensing: https://doc.qt.io/qtforpython-6.12/licenses.html
- Python source/license: https://www.python.org/downloads/source/
- PyInstaller exception: https://pyinstaller.org/en/stable/license.html

The release workflow also archives the exact Qt and PySide source tarballs as
release assets; consult their SHA256 in source-manifest.json. This avoids relying
only on source links for LGPL source availability. No commercial Qt license,
paid installer service or code-signing certificate is used. Inno Setup 6.4.3 is
used under its permissive license, available at:
https://github.com/jrsoftware/issrc/blob/is-6_4_3/license.txt

## Desktop ChatGPT authentication dependencies

The desktop also includes PyJWT 2.15.1 (MIT), cryptography 50.0.2
(Apache-2.0 OR BSD-3-Clause), cffi 2.1.1 (MIT-0), and pycparser 3.11
(BSD-3-Clause). Their installed license texts remain in `_internal/licenses`.
Native OpenSSL 4.0.3, Rust dependency and vendored libffi notices, exact-wheel
SBOMs, source URLs and verification records are in the standard ZIP archive
`_internal/licenses/chatgpt-auth-native-notices.zip`. Open this archive with
Windows Explorer or another ZIP reader; the application never extracts it.
See `_internal/licenses/chatgpt-auth-provenance/README.md` for its pinned hash,
component scope and the distinction between verified source archives and
independently verified exact-version upstream notice texts. Build-only
components are labeled separately. A dependency change requires renewed review.


## SQLite native runtime

SQLite 3.54.0 is public domain: https://www.sqlite.org/copyright.html.
The Windows package uses the official x64 DLL in a private CPython copy.
`sqlite-runtime.json` records exact archive/source/library hashes and provenance.
The official source archive is https://www.sqlite.org/2026/sqlite-amalgamation-3540000.zip.
No commercial license or service is required. The upstream public-domain
statement also covers distribution of compiled SQLite binaries.

## Removed local AI route and remaining Microsoft runtime obligations

The 2026-10-10 subscription-only candidate removes the dedicated llama.cpp/Qwen/
GGUF setup route, its local-AI notice assets and the duplicate
`_internal/local-ai-dependencies` collection. Earlier notices and profiles remain
in Git history. The current installer does not ship or download a local model.
This change does not delete user caches or historical research evidence.

Qt and CPython still require their applicable native dependencies and notices.
Removing the dedicated local-AI copy does not remove Microsoft redistribution
obligations for binaries that remain in the actual frozen payload. Microsoft's
binaries are not licensed by this project's Apache-2.0 grant or Qt's LGPL grant.
The collected `_internal/licenses/PYTHON-LICENSE.txt` retains the Windows Python
notice; its presence alone is not a legal determination for every bundled DLL.
Final payload provenance and applicable downstream conditions must be assessed
against the actual build, without inventing a new paid-license or EULA requirement.
See https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files.

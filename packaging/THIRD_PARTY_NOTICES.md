# Third-party software and replaceable Qt libraries

Mark Auto is Apache-2.0; its LICENSE accompanies this application. This distribution
includes Python (PSF license), PySide6/Shiboken6 and Qt 6.12.0 (open-source licenses,
including LGPL-3.0), tzdata (Apache-2.0/public-domain data), and the PyInstaller
bootloader (GPL with its distribution exception). Copies of installed dependency
license/notice files are under `_internal/licenses`. Python's license is included
there too. Qt's third-party notices are collected from the distributed wheels.

Qt Core/Gui/Widgets are used dynamically, not statically. The onedir distribution
keeps their DLLs replaceable under `_internal/PySide6` and associated plugins.
You may replace LGPL-covered libraries with compatible modified versions and
reverse-engineer this application to debug those modifications as LGPL permits.
Keep the matching ABI, architecture, dependency DLLs and plugin versions. No
signature check prevents library replacement. This permission supersedes any
contrary restriction for these LGPL purposes.

Corresponding upstream source for the exact unmodified libraries:
- PySide6/Shiboken6 6.12.0: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/
- Qt 6.12.0: https://download.qt.io/official_releases/qt/6.12/6.12.0/single/
- Qt licensing: https://doc.qt.io/qtforpython-6/licenses.html
- Python source/license: https://www.python.org/downloads/source/
- PyInstaller exception: https://pyinstaller.org/en/stable/license.html

The release workflow also archives the exact Qt and PySide source tarballs as
release assets; consult their SHA256 in source-manifest.json. This avoids relying
only on source links for LGPL source availability. No commercial Qt license,
paid installer service or code-signing certificate is used. Inno Setup 6.4.3 is
used under its permissive license, available at:
https://github.com/jrsoftware/issrc/blob/is-6_4_3/license.txt

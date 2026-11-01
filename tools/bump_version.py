"""Set the product version everywhere it is written; quantlab/__init__.py is the source.

Usage: python tools/bump_version.py 0.3.1
tests/test_version_consistency.py fails when any place drifts from quantlab.__version__.
"""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

# (file, pattern with one version group). The upgrade baseline (0.2.1 release) is not a product version.
# Not listed: the defaults in packaging/markauto.iss and packaging/test_installer.ps1. build.ps1 always passes
# /DAppVersion, CI never relies on the harness default, and both files are hash-pinned security baselines.
LOCATIONS = (
    ('quantlab/__init__.py', r'__version__ = "(\d+\.\d+\.\d+)"'),
    ('pyproject.toml', r'(?m)^version = "(\d+\.\d+\.\d+)"'),
    ('packaging/build_broker_portable.py', r"'--version', default='(\d+\.\d+\.\d+)'"),
    ('packaging/test_unified_installer.ps1', r"\[string\]\$Version = '(\d+\.\d+\.\d+)'"),
    ('packaging/test_update_recovery.ps1', r"\[string\]\$Version = '(\d+\.\d+\.\d+)'"),
    # Skips the pinned 0.2.1 baseline installer and the 0.0.0 upgrade fixture.
    ('.github/workflows/windows-desktop.yml', r'(?:-Version |--version |(?<!baseline/)MarkAuto-)(?!0\.0\.0-)(\d+\.\d+\.\d+)'),
)


def versions():
    """Every written version as (file, version)."""
    for name, pattern in LOCATIONS:
        text = (ROOT / name).read_text(encoding='utf-8-sig')
        for match in re.finditer(pattern, text):
            yield name, match[1]


def main(argv):
    if len(argv) != 1 or not re.fullmatch(r'\d+\.\d+\.\d+', argv[0]):
        print(__doc__)
        return 2
    new = argv[0]
    for name, pattern in LOCATIONS:
        path = ROOT / name
        raw = path.read_bytes()
        bom = raw.startswith(b'\xef\xbb\xbf')
        text = raw.decode('utf-8-sig')
        text = re.sub(pattern, lambda m: m[0].replace(m[1], new), text)
        path.write_bytes((b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8'))
    print(f'Version set to {new}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

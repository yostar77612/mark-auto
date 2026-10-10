"""Generate project-owned Windows EXE version metadata, not a signature."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


PRODUCT_NAME = 'MarkAuto'
COMPANY_NAME = 'Mark Auto contributors'


def version_tuple(version):
    if not isinstance(version, str) or not re.fullmatch(
            r'(?:0|[1-9][0-9]{0,4})\.(?:0|[1-9][0-9]{0,4})\.(?:0|[1-9][0-9]{0,4})', version):
        raise ValueError('Version must be canonical numeric x.y.z')
    parts = tuple(int(value) for value in version.split('.'))
    if any(value > 65535 for value in parts):
        raise ValueError('Windows version components must be at most 65535')
    return (*parts, 0)


def render_version_resource(version):
    fixed = version_tuple(version)
    strings = {
        'CompanyName': COMPANY_NAME,
        'FileDescription': PRODUCT_NAME,
        'FileVersion': version,
        'InternalName': PRODUCT_NAME,
        'OriginalFilename': 'MarkAuto.exe',
        'ProductName': PRODUCT_NAME,
        'ProductVersion': version,
    }
    entries = ',\n'.join(f'            StringStruct({key!r}, {value!r})'
                         for key, value in strings.items())
    return f'''# UTF-8; generated from the validated build version. Not a code signature.
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers={fixed!r}, prodvers={fixed!r},
        mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
        subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable('040904B0', [
{entries}
        ])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])
    ]
)
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    text = render_version_resource(args.version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Enroll only a CA password reference; the UI selects the file separately.

Run manually on Windows. This tool does not load the SDK or activate a CA.
Account person_id is discovered after login and is never entered or stored here.
"""

from getpass import getpass
import json
from pathlib import Path
import sys

TARGET = 'MarkAuto/v2/certificate/sinopac'


def main() -> int:
    password = getpass('CA password: ')
    if not password or len(password.encode('utf-8')) > 2000:
        print('Password missing or too long; nothing saved.')
        return 1
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.store_sinopac_key import _write

    _write(TARGET, json.dumps({'ca_password': password}, ensure_ascii=False).encode('utf-8'))
    del password
    print('Saved certificate password reference: ' + TARGET)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

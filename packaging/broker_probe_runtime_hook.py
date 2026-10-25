"""Optional broker build only: explicit no-login proof before Qt initialization."""

import sys

if getattr(sys, 'frozen', False) and '--broker-sdk-probe' in sys.argv[1:]:
    if len(sys.argv) != 3 or sys.argv[1] != '--broker-sdk-probe':
        raise SystemExit(2)
    from pathlib import Path
    import runpy

    probe = runpy.run_path(str(Path(sys._MEIPASS) / 'packaging/broker_probe.py'))
    raise SystemExit(probe['run_probe'](Path(sys.argv[2]), Path(sys._MEIPASS) / 'broker-build.json', require_frozen=True))

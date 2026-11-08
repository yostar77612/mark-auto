"""Read-only, verified archive of the MarkAuto workspace (a full copy you can keep before any big upgrade).

    python tools/archive_workspace.py --destination D:/MarkAutoArchive/2026-11-08            # archive
    python tools/archive_workspace.py --destination D:/MarkAutoArchive/2026-11-08 --dry-run  # only count
    python tools/archive_workspace.py --destination D:/MarkAutoArchive/2026-11-08 --verify   # re-check later

Close MarkAuto first: a file that changes while it is copied makes the run fail instead of storing a torn copy.
Nothing in the workspace is changed or deleted. The archive holds credentials and control files as opaque
bytes; keep it in a private folder of your own Windows account.
"""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantlab.research_core.adapters.workspace_archive import ArchiveError, create_archive, inventory, verify_archive  # noqa: E402


def default_sources() -> dict[str, Path]:
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise ArchiveError('local_app_data_unknown')
    found = {label: Path(base) / folder for label, folder in (('bootstrap', 'MarkAuto'), ('trading', 'MarkAuto-v2')) if (Path(base) / folder).is_dir()}
    if not found:
        raise ArchiveError('source_missing')
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--destination', required=True, type=lambda value: Path(value).absolute())
    parser.add_argument('--source', action='append', metavar='LABEL=PATH', help='default: the bootstrap and trading folders under LOCALAPPDATA')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verify', action='store_true', help='re-check an existing archive instead of creating one')
    args = parser.parse_args(argv)
    try:
        if args.verify:
            manifest = verify_archive(args.destination)
            result = {'status': 'VERIFIED', 'files': manifest['file_count'], 'bytes': manifest['total_bytes']}
        else:
            sources = {item.partition('=')[0]: Path(item.partition('=')[2]) for item in args.source} if args.source else default_sources()
            if args.dry_run:
                entries = inventory(sources)
                result = {'status': 'DRY_RUN', 'files': len(entries), 'bytes': sum(entry.size for entry in entries)}
            else:
                manifest = create_archive(sources, args.destination)
                verify_archive(args.destination)
                result = {'status': 'ARCHIVED', 'files': manifest['file_count'], 'bytes': manifest['total_bytes']}
    except ArchiveError as error:
        print(json.dumps({'status': 'REFUSED', 'code': error.code}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

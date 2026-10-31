"""E4 reproducible history extraction and direct consumer/patch-target migration."""

import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OLD = 'quantlab.market_history'
PREFIX = 'quantlab.research_core.'
GROUPS = {
    'domain.market_sessions': [
        'MAX_BARS',
        'MAX_SESSIONS',
        'PRODUCT_SOURCES',
        'UTC',
        'TAIPEI',
        '_fail',
        '_stamp',
        'MarketSession',
        '_session_dict',
        'session_from_dict',
        '_sessions',
        'HistoryLoad',
        '_canonical',
        '_hash',
    ],
    'adapters.history_decoder': [
        'MAX_FILE_BYTES',
        'MAX_ROWS',
        'COLUMNS',
        'WARNINGS',
        'VERSION',
        'SOURCE_URL',
        '_check',
        '_lines',
        '_positive',
        '_tick_time',
        '_decode',
        '_bar_dict',
        '_result',
    ],
    'adapters.market_history': [
        'MAX_CACHE_BYTES',
        'MAX_IMPORTS',
        '_local_path_text',
        '_windows_local_drive',
        '_safe',
        '_pairs',
        'load_history',
        '_entries',
        '_cache_lock',
        'list_history',
        '_existing_result',
    ],
    'application.history_import': ['MAX_SECONDS', 'import_history'],
}
OWNERS = {name: PREFIX + module for module, names in GROUPS.items() for name in names}
HEADERS = {
    'domain.market_sessions': '''from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from quantlab.errors import fail
from quantlab.market import InstrumentRef, MarketSeries, MarketValidationError, day, utc
from quantlab.shared.time import aware_iso_utc
''',
    'adapters.history_decoder': '''import csv
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import os
import re
import time
from quantlab.market import MarketBar, MarketSeries, MarketValidationError, SourceProvenance, bar_key
from quantlab.research_core.domain.market_sessions import PRODUCT_SOURCES, UTC, TAIPEI, HistoryLoad, _fail, _hash, _session_dict
''',
    'adapters.market_history': '''from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile
from quantlab.market import MarketBar, MarketValidationError, utc
from quantlab.windows_paths import canonical_path, native_path
from quantlab.research_core.domain.market_sessions import MAX_BARS, _fail, _hash, _session_dict, _sessions, _stamp, session_from_dict
from .history_decoder import MAX_FILE_BYTES, MAX_ROWS, VERSION, _check, _result
''',
    'application.history_import': '''from datetime import datetime
import time
from quantlab.market import utc
from quantlab.research_core.domain.market_sessions import UTC, _canonical, _hash, _session_dict, _sessions
from quantlab.research_core.ports.history import HistoryStorage
''',
}


def write(path, source):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding='utf-8', newline='\n')


def extract():
    source = subprocess.check_output(['git', 'show', '1f13408:quantlab/market_history.py'], cwd=ROOT).decode('utf-8')
    lines = source.splitlines(keepends=True)
    defs = {}
    for node in ast.parse(source).body:
        name = getattr(node, 'name', None)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name:
            start = min([node.lineno] + [d.lineno for d in getattr(node, 'decorator_list', [])])
            defs[name] = ''.join(lines[start - 1 : node.end_lineno])
    original = defs['import_history']
    before, publication = original.split('    _safe(canonical_path(root), directory=True)\n', 1)
    before = before.replace(
        'def import_history(path, root, *, sessions, received_at=None, cancelled=None):',
        'def import_history(path, root, *, sessions, storage: HistoryStorage, received_at=None, cancelled=None):\n    _check, _safe, _decode, _result = storage.check, storage.safe, storage.decode, storage.result\n    VERSION, MAX_CACHE_BYTES = storage.version, storage.max_cache_bytes\n    _bar_dict, _fail = storage.bar_dict, storage.fail\n    canonical_path = storage.canonical_path',
    )
    # Preserve target admission before cancellation and cache encoding.
    defs['import_history'] = before + '    return storage.publish(root, target, result, content, deadline, cancelled)\n'
    publication = "def publish(root, target, result, content, deadline, cancelled):\n    _safe(canonical_path(root), directory=True)\n" + publication
    for module, names in GROUPS.items():
        body = '\n\n'.join(defs[name] for name in names)
        if module == 'adapters.market_history':
            body += '\n\n' + publication
        write(
            'quantlab/research_core/' + module.replace('.', '/') + '.py',
            '"""Bounded history responsibility; validation, digest and publication ordering preserved."""\n\n' + HEADERS[module] + '\n\n' + body,
        )
    # The old location retains metadata only, with zero exported implementation names.
    write('quantlab/market_history.py', '"""Historical module metadata. History owners live in research_core; no exports."""\n')


def reference_edits():
    import json

    recipe = json.loads((ROOT / 'tools/refactor/e_market_history_references.json').read_text(encoding='utf-8'))
    for path, hunks in recipe['edits'].items():
        source = (ROOT / path).read_text(encoding='utf-8-sig')
        for old, new in reversed(hunks):
            if new in source:
                continue
            if old in source:
                source = source.replace(old, new, 1)
            else:
                raise ValueError('Reference recipe no longer matches: ' + path)
        write(path, source)
    for path, source in recipe['new_ports'].items():
        write(path, source)


if __name__ == '__main__':
    extract()
    reference_edits()

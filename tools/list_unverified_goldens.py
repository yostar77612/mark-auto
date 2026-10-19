"""Offline inventory of golden entries lacking independent verification.

Scope and historical evidence are recorded in IMPLEMENTATION_CONTRACTS.md.
Malformed or missing metadata fails validation instead of reducing the count.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {'engine_golden.json': 'cases', 'ui_operations_golden.json': 'observations'}
SOURCES = frozenset({'hand-computed', 'existing-behaviour', 'cross-checked', 'derived'})
REVIEWS = frozenset({'unreviewed', 'reviewed', 'independently-verified'})
PRECISIONS = frozenset({'Decimal-exact', 'exact after documented normalisations; Decimal-exact money'})
METADATA_KEYS = frozenset({'source', 'review', 'precision'})


def golden_entries(document, collection):
    """One engine case or one complete operation observation is one golden."""
    entries = document[collection]
    return list(entries.values()) if isinstance(entries, dict) else list(entries)


def count_unverified(fixtures=ROOT / 'tests' / 'fixtures'):
    counts = {}
    for filename, collection in FIXTURES.items():
        with (Path(fixtures) / filename).open(encoding='utf-8') as stream:
            entries = golden_entries(json.load(stream), collection)
        for entry in entries:
            for field, allowed in (('source', SOURCES), ('review', REVIEWS), ('precision', PRECISIONS)):
                if not isinstance(entry.get(field), str) or entry[field] not in allowed:
                    raise ValueError(f'{filename}: invalid or missing {field}')
        counts[filename] = sum(entry['source'] not in {'hand-computed', 'cross-checked'} or entry['review'] != 'independently-verified' for entry in entries)
    return {'fixtures': counts, 'total': sum(counts.values())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Emit machine-readable counts')
    args = parser.parse_args(argv)
    report = count_unverified()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for name, count in report['fixtures'].items():
            print(f'{name}: {count} unverified')
        print(f'Total: {report["total"]} unverified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

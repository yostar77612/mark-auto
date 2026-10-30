"""Dump and compare every locale/key and alias with the fixed PR-C main base."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = '6b78239'
FIXTURE = ROOT / 'tests/fixtures/desktop_catalog_main_6b78239.json'


def dump(namespace):
    keys = tuple(dict.fromkeys((*namespace['ZH_TW'], *namespace['TEXT_ALIASES'])))
    return {
        'locales': namespace['LOCALES'],
        'aliases': namespace['TEXT_ALIASES'],
        'lookups': {locale: {key: namespace['ui_text'](key, locale) for key in keys} for locale in namespace['LOCALES']},
        'key_order': list(namespace['ZH_TW']),
        'alias_order': list(namespace['TEXT_ALIASES']),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-baseline', action='store_true', help='Explicitly capture the fixed main commit, never the current tree')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from desktop_app.strings import catalog

    expected = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if expected.pop('source_commit') != BASE:
        raise SystemExit('Unexpected catalog baseline commit')
    actual = dump(vars(catalog))
    if args.write_baseline:
        print('catalog baseline: already applied; committed fixture retained')
    summary = {}
    for locale in expected['locales'].keys() | actual['locales'].keys():
        before, after = expected['lookups'].get(locale, {}), actual['lookups'].get(locale, {})
        summary[locale] = {
            'added': len(after.keys() - before.keys()),
            'removed': len(before.keys() - after.keys()),
            'changed': sum(before[key] != after[key] for key in before.keys() & after.keys()),
        }
    print(json.dumps(summary))
    if expected != actual:
        raise SystemExit('Catalog mappings, aliases, locale lookups or insertion order changed')


if __name__ == '__main__':
    main()

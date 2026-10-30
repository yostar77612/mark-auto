"""Dump and compare every locale/key and alias with the fixed PR-C main base."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import subprocess
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

    directory = ROOT / '.tmp-layered/catalog-equality'
    directory.mkdir(parents=True, exist_ok=True)
    original = directory / 'main_catalog.py'
    original.write_bytes(subprocess.check_output(['git', 'show', f'{BASE}:desktop_app/strings/catalog.py'], cwd=ROOT))
    expected, actual = dump(runpy.run_path(str(original))), dump(vars(catalog))
    for name, payload in (('main', expected), ('tree', actual)):
        (directory / f'{name}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.write_baseline:
        FIXTURE.write_text(json.dumps({'source_commit': BASE, **expected}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
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

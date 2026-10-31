"""Replay exact T5-E6 test import/patch and refactor-inventory relocations."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    table = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    for row in table:
        path = ROOT / row['path']
        current = path.read_text(encoding='utf-8-sig') if path.exists() else ''
        digest = hashlib.sha256(current.encode()).hexdigest()
        if digest == row['after_sha256']:
            continue
        assert digest == row['before_sha256'], row['path']
        lines = current.splitlines(keepends=True)
        for change in reversed(row['changes']):
            assert lines[change['start'] : change['end']] == change['before']
            lines[change['start'] : change['end']] = change['after']
        result = ''.join(lines)
        assert hashlib.sha256(result.encode()).hexdigest() == row['after_sha256']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result, encoding='utf-8')
    print(f'{len(table)} exact T5-E6 reference files verified')


if __name__ == '__main__':
    main()

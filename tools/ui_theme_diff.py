"""Compare ui_snapshot.py outputs: identical metrics and <=0.1% changed pixels.

Usage: python tools/ui_theme_diff.py BEFORE AFTER [--report REPORT.json]
Uses Qt QImage so the desktop environment does not need Pillow or NumPy.
"""
import argparse
import json
from pathlib import Path

from PySide6.QtGui import QImage


def compare(before, after):
    before, after = Path(before), Path(after)
    old = json.loads((before / 'metrics.json').read_text(encoding='utf-8'))
    new = json.loads((after / 'metrics.json').read_text(encoding='utf-8'))
    if old != new:
        raise ValueError('Snapshot metrics differ (including heights, counts or visible_text)')
    files = sorted(before.glob('*.png'))
    if not files or {path.name for path in files} != {path.name for path in after.glob('*.png')}:
        raise ValueError('Snapshot PNG sets differ or are empty')
    measurements = {}
    for path in files:
        left, right = QImage(str(path)), QImage(str(after / path.name))
        if left.isNull() or right.isNull() or left.size() != right.size():
            raise ValueError('Invalid image or dimensions differ: ' + path.name)
        left = left.convertToFormat(QImage.Format.Format_RGB888)
        right = right.convertToFormat(QImage.Format.Format_RGB888)
        changed = 0
        for y in range(left.height()):
            a = bytes(left.constScanLine(y))[:left.width() * 3]
            b = bytes(right.constScanLine(y))[:right.width() * 3]
            changed += sum(max(abs(a[x] - b[x]), abs(a[x+1] - b[x+1]),
                               abs(a[x+2] - b[x+2])) > 8 for x in range(0, len(a), 3))
        measurements[path.name] = {
            'size': [left.width(), left.height()],
            'changed_pixel_fraction': changed / (left.width() * left.height()),
        }
    return {'metrics_identical': True, 'channel_delta_threshold': 8,
            'maximum_changed_fraction': 0.001, 'images': measurements,
            'passed': all(item['changed_pixel_fraction'] <= 0.001
                          for item in measurements.values())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    result = compare(args.before, args.after)
    output = json.dumps(result, indent=2) + '\n'
    if args.report:
        args.report.write_text(output, encoding='utf-8')
    print(output, end='')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

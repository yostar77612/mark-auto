import json, sys
from pathlib import Path
from PySide6.QtGui import QImage

def compare(before, after):
    before, after = Path(before), Path(after)
    a = json.loads((before/'metrics.json').read_text(encoding='utf-8'))
    b = json.loads((after/'metrics.json').read_text(encoding='utf-8'))
    if a != b:
        for page, metrics in a['pages'].items():
            print(page, {key: (value,b['pages'][page].get(key)) for key,value in metrics.items() if value != b['pages'][page].get(key)})
    assert a == b, 'Page metrics differ'
    result = {}
    for file in sorted(before.glob('*.png')):
        left, right = QImage(str(file)).convertToFormat(QImage.Format.Format_RGB888), QImage(str(after/file.name)).convertToFormat(QImage.Format.Format_RGB888)
        assert left.size() == right.size(), file.name
        changed = 0
        for y in range(left.height()):
            l, r = bytes(left.constScanLine(y))[:left.width()*3], bytes(right.constScanLine(y))[:right.width()*3]
            changed += sum(max(abs(l[x]-r[x]), abs(l[x+1]-r[x+1]), abs(l[x+2]-r[x+2])) > 8 for x in range(0,len(l),3))
        result[file.name] = changed / (left.width() * left.height())
    print(json.dumps(result, indent=2))
    assert max(result.values()) <= .001, 'Pixel parity regression'
    return result
if __name__ == '__main__':
    compare(*sys.argv[1:])

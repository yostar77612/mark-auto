"""Offline development-only SciPy oracle; never a product/test dependency."""

from decimal import Decimal
import json
from pathlib import Path

from scipy import __version__, stats


def generate():
    assert __version__ == '1.16.3', 'Goldens require the pinned offline oracle'
    cases = []
    for n, multiplier, modulus, offset in ((60, 7, 11, 4), (30, 5, 13, 5), (2, 7, 11, 4), (5, 7, 11, 4), (500, 7, 11, 4)):
        strings = [str(Decimal(i * multiplier % modulus - offset) / Decimal(1000)) for i in range(n)]
        values = [float(value) for value in strings]
        test = stats.ttest_1samp(values, 0, alternative='greater')
        cases.append({'n': n, 'returns': strings, 't': float(test.statistic), 'p_value_t': float(test.pvalue)})
    payload = {'scipy_version': __version__, 'generating_script': Path(__file__).read_text(encoding='utf-8'), 'cases': cases}
    path = Path(__file__).resolve().parents[1] / 'tests/fixtures/significance_goldens.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    generate()

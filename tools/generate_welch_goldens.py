"""Development-only offline SciPy Welch oracle; no product/test dependency."""

import json
from pathlib import Path

from scipy import __version__, stats


def generate():
    assert __version__ == '1.16.3', 'Goldens require the pinned offline oracle'
    early = [(i * 5 % 11 - 4) / 1000 for i in range(40)]
    recent = [(i * 7 % 11 - 6) / 1000 for i in range(40)]
    result = stats.ttest_ind(early, recent, equal_var=False, alternative='greater')
    payload = {
        'scipy_version': __version__,
        'early': early,
        'recent': recent,
        't': float(result.statistic),
        'df': float(result.df),
        'p_value': float(result.pvalue),
        'generating_script': Path(__file__).read_text(encoding='utf-8'),
    }
    path = Path(__file__).resolve().parents[1] / 'tests/fixtures/welch_goldens.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    generate()

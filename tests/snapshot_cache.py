"""One shared default-state UI metrics capture per test process.

Rasterising all seven pages is slow on software-rendering CI hosts, and several test modules only
need the logical metrics (text, counts, heights). They share this single metrics-only capture; the
PNG-exact comparison stays in tests.test_desktop_pages (Windows) and tests.test_ui_snapshot.
"""

import copy
import tempfile
from pathlib import Path

_METRICS = {}


def default_metrics():
    if 'default' not in _METRICS:
        from tools.ui_snapshot import capture

        with tempfile.TemporaryDirectory(prefix='markauto-shared-metrics-') as folder:
            _METRICS['default'] = capture(Path(folder) / 'snapshot', images=False)
    return copy.deepcopy(_METRICS['default'])

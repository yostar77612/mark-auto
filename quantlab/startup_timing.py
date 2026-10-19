"""In-memory GUI startup measurements; importing this module does no I/O."""

from math import isfinite
from time import monotonic

MAX_STAGES = 8
STAGES = frozenset({'application', 'bootstrap', 'workspace', 'window', 'ready'})
TRUNCATION_MARKER = '[truncated]'


class StartupTiming:
    """Each mark measures the completed interval since construction/previous mark.

    Names must be fixed codes. No arbitrary detail, absolute clock values or
    persistent history is retained. Overflow preserves the first MAX_STAGES.
    """

    def __init__(self, clock=monotonic):
        self._clock = clock
        self._previous = clock()
        self._stages = []
        self._truncated = False

    def mark(self, stage):
        if type(stage) is not str or stage not in STAGES:
            raise ValueError('Unknown startup stage')
        if len(self._stages) == MAX_STAGES:
            self._truncated = True
            return
        current = self._clock()
        elapsed = current - self._previous
        duration = max(0.0, elapsed) if isfinite(elapsed) else 0.0
        self._previous = current
        self._stages.append({'stage': stage, 'duration_seconds': duration})

    def snapshot(self):
        result = {'stages': [dict(row) for row in self._stages]}
        if self._truncated:
            result['truncation'] = TRUNCATION_MARKER
        return result


def timing_snapshot(value):
    """Project only the recorder's bounded, fixed-code numeric entries."""
    if type(value) is not StartupTiming:
        return 'unavailable'
    return value.snapshot()

"""Presentation-only duration arithmetic; never changes a research budget."""

import math

# Conservative per-evaluation cost. docs/analysis/t14_p3_latency.md measured a
# 0.49 s median on a quiet machine, while the plan (P3-10) recorded about 8 s per
# evaluation under load; the larger figure keeps the preview an upper-bound estimate.
MEASURED_EVALUATION_SECONDS: float | None = 8.0


def estimated_seconds(evaluations, per_evaluation_seconds):
    """Return an estimate, or None when count/measurement is unavailable."""
    if type(evaluations) is not int or evaluations <= 0:
        return None
    if type(per_evaluation_seconds) not in (int, float) or per_evaluation_seconds <= 0:
        return None
    try:
        result = evaluations * per_evaluation_seconds
        return result if math.isfinite(result) else None
    except OverflowError:
        return None

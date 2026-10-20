"""Bounded, read-only projection of existing import quality coordinates."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import heapq
import re

from .desktop_errors import error_message
from .errors import ERROR_TABLE

MAX_GAPS = 500


@dataclass(frozen=True, order=True)
class Gap:
    trade_date: str
    start: str
    end: str
    contract_id: str
    session: str


@dataclass(frozen=True)
class GapReport:
    gaps: tuple = ()
    more: int = 0
    code: str = 'operation_failed'

    @property
    def message(self):
        return error_message(self.code)


def _restricted_scope(value):
    return any(value.get(key) in ('oos', 'out_of_sample', 'holdout', 'final_holdout') for key in ('scope', 'split', 'partition', 'role'))


def _gap(row):
    if not isinstance(row, dict) or _restricted_scope(row):
        return None
    try:
        day, contract, session = row['trade_date'], row['contract_id'], row['session']
        if type(day) is not str or date.fromisoformat(day).isoformat() != day:
            return None
        if type(contract) is not str or not re.fullmatch(r'TAIFEX:TMF:[0-9]{6}', contract) or session not in ('day', 'night'):
            return None
        start, end = row['start'], row['end']
        start = start if type(start) is datetime else datetime.fromisoformat(start)
        end = end if type(end) is datetime else datetime.fromisoformat(end)
        if start.utcoffset() is None or end.utcoffset() is None or start >= end:
            return None
        return Gap(day, start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat(), contract, session)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def build_gap_report(quality, code='validation_failed'):
    """Never inspect error strings, paths, manifests, bars or research payloads.

    Only the validator's session_coverage_gaps schema is projected. Unknown B1
    codes fail closed. A heap bounds retained rows even for large inputs.
    """
    if type(code) is not str or code not in ERROR_TABLE:
        return GapReport()
    if not isinstance(quality, dict) or _restricted_scope(quality):
        return GapReport(code=code)
    rows = quality.get('session_coverage_gaps', ())
    if not isinstance(rows, (list, tuple)):
        return GapReport(code=code)
    total = 0

    def valid_rows():
        nonlocal total
        for row in rows:
            gap = _gap(row)
            if gap is not None:
                total += 1
                yield gap

    gaps = tuple(heapq.nsmallest(MAX_GAPS, valid_rows()))
    return GapReport(gaps, max(0, total - len(gaps)), code)


def reject_invalid_import(data, emit=None):
    """Use the existing validation failure before any store write."""
    if data.quality.get('valid') is not True or data.quality.get('errors'):
        if emit is not None:
            report = build_gap_report(data.quality)
            emit(
                'progress',
                gap_report={
                    'code': report.code,
                    'more': report.more,
                    'quality': {'session_coverage_gaps': [gap.__dict__ for gap in report.gaps]},
                },
            )
        # Preserve the existing validator and its exact failure text.
        from .data import validate_dataset

        validate_dataset(data)

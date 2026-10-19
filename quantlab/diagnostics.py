"""Bounded, allowlisted diagnostics. The builder has no I/O or clock access."""

from datetime import date, datetime, timezone
import json
from pathlib import Path

from . import __version__
from .desktop_feedback import OPERATION_LABELS
from .errors import ERROR_TABLE
from .job_stages import normalize_stage
from .startup_timing import timing_snapshot

MAX_BYTES = 4096
MAX_ERRORS = 32
LOG_BYTES = 32768
UNAVAILABLE = 'unavailable'
TRUNCATION_MARKER = '[truncated]'
OPERATIONS = frozenset('ui_' + name for name in OPERATION_LABELS)


def fixed(value, choices, fallback=UNAVAILABLE):
    return value if type(value) is str and value in choices else fallback


def error_entry(packet):
    """Worker packets and JSONL records share only this fixed public projection."""
    packet = packet if type(packet) is dict else {}
    code = fixed(packet.get('error_code'), ERROR_TABLE, 'operation_failed')
    return {'error_code': code, 'explanation': ERROR_TABLE[code].explanation}


def _instant(value):
    # Parse a timestamp value, never pass arbitrary input text through to output.
    if type(value) is str and len(value) <= 40:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if type(value) is datetime and value.tzinfo is not None:
        try:
            return value.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass
    return None


def _day(value):
    if type(value) is str and len(value) == 10:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    return UNAVAILABLE


def build_diagnostics(*, workspace=None, data=None, job=None, errors=(), now=None, startup_timing=None):
    """Return deterministic UTF-8 JSON text with a fixed byte ceiling.

    workspace is a presence boolean, never a path. All mapping values are
    untrusted; only enums, canonical dates and computed integer ages survive.
    Error input order is oldest to newest; output order is newest first.
    """
    data = data if type(data) is dict else {}
    job = job if type(job) is dict else {}
    latest, current = _instant(data.get('latest_bar_timestamp')), _instant(now)
    age = max(0, int((current - latest).total_seconds())) if latest and current else UNAVAILABLE
    records = errors if type(errors) in (list, tuple) else ()
    recent = [error_entry(row) for row in reversed(records[-MAX_ERRORS:]) if type(row) is dict and 'error_code' in row]
    snapshot = {
        'app_version': __version__,
        'workspace': 'available' if workspace is True else UNAVAILABLE,
        'data': {
            'source': fixed(data.get('source'), {'TAIFEX', 'TWSE', 'research', 'synthetic'}),
            'mode': fixed(data.get('mode'), {'history', 'eod', 'realtime', 'delayed', 'offline'}),
            'latest_bar_timestamp': latest.isoformat() if latest else UNAVAILABLE,
            'latest_bar_trade_date': _day(data.get('latest_bar_trade_date')),
            'age_seconds': age,
        },
        'job': {
            'operation': fixed(job.get('operation'), OPERATIONS),
            'stage': normalize_stage(job.get('stage')),
            'state': 'active' if job.get('active') is True else 'idle',
        },
        'last_errors': recent,
        'errors_status': 'available' if type(errors) in (list, tuple) else UNAVAILABLE,
        'startup_timing': timing_snapshot(startup_timing),
    }
    if len(records) > MAX_ERRORS:
        snapshot['truncation'] = TRUNCATION_MARKER
    while True:
        text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
        if len(text.encode('utf-8')) <= MAX_BYTES:
            return text
        snapshot['truncation'] = TRUNCATION_MARKER
        if recent:
            recent.pop()  # Drop oldest whole entries; retain valid JSON and every section.
        else:
            snapshot['startup_timing']['stages'].pop()
            snapshot['startup_timing']['truncation'] = TRUNCATION_MARKER


def read_error_records(path):
    """Read only a bounded tail; absent, unreadable or malformed logs are optional."""
    try:
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            return None
        with path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - LOG_BYTES))
            raw = stream.read(LOG_BYTES)
    except (OSError, ValueError, TypeError):
        return None
    records = []
    for line in raw.splitlines()[-200:]:
        try:
            row = json.loads(line)
        except (ValueError, UnicodeError, RecursionError):
            continue
        if type(row) is dict and row.get('event') == 'error' and 'error_code' in row:
            records.append(error_entry(row))
    return records[-MAX_ERRORS:]


def copy_diagnostics(text, clipboard):
    """The UI copies exactly the displayed builder output, without reserialization."""
    clipboard.setText(text)

"""Bounded history responsibility; validation, digest and publication ordering preserved."""

from datetime import datetime
import time
from quantlab.market import utc
from quantlab.research_core.domain.market_sessions import UTC, _canonical, _hash, _session_dict, _sessions
from quantlab.research_core.ports.history import HistoryStorage


MAX_SECONDS = 120


def import_history(path, root, *, sessions, storage: HistoryStorage, received_at=None, cancelled=None):
    _check, _safe, _decode, _result = storage.check, storage.safe, storage.decode, storage.result
    VERSION, MAX_CACHE_BYTES = storage.version, storage.max_cache_bytes
    _bar_dict, _fail = storage.bar_dict, storage.fail
    canonical_path = storage.canonical_path
    deadline = time.monotonic() + MAX_SECONDS
    _check(deadline, cancelled)
    sessions = _sessions(sessions)
    path = _safe(path)
    if path.suffix.lower() not in ('.csv', '.rpt'):
        _fail('local native CSV or comma-delimited RPT required')
    root = _safe(canonical_path(root), directory=True, create=True)
    received_at = received_at or datetime.now(UTC)
    utc(received_at)
    bars, source_hash, counters = _decode(path, sessions, deadline, cancelled)
    result = _result(bars, sessions, source_hash, counters, received_at)
    target = _safe(canonical_path(root / (result.cache_id + '.json')))
    _check(deadline, cancelled)
    payload = dict(
        version=VERSION,
        source_hash=source_hash,
        policy_hash=result.policy_hash,
        received_at=received_at.isoformat(),
        sessions=[_session_dict(s) for s in sessions],
        bars=[_bar_dict(b) for b in bars],
        counters=counters,
    )
    content = _canonical(dict(payload=payload, sha256=_hash(payload))).encode('utf-8')
    if len(content) > MAX_CACHE_BYTES:
        _fail('normalized history cache byte limit')
    return storage.publish(root, target, result, content, deadline, cancelled)

"""Bounded host-only stock signal TRAINING, without E1, PnL or execution authority.

The official source verifies local payload bytes and complete calendar/event
coverage. Every decision uses its own full, point-in-time adjusted history.
"""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import timedelta, timezone
from hashlib import sha256
from pathlib import Path
from time import monotonic

from quantlab.core import Bar, Dataset, canonical_json, content_hash, freeze, validate_signal_contract, ValidationError
from quantlab.trading.domain.stock_history import adjust_bars, price_series
from quantlab.trading.domain.validation import DomainError, trading_date
from quantlab.trading.runtime.official_daily_source import OfficialDailyStockSource
from quantlab.trading.runtime.provenance import compute_profile
from quantlab.trading.runtime.v1_signal_source import canonical_spec_json, spec_fingerprint, validated_spec, generate_signals

PRODUCER = 'm3-stock-signal-training-v1'
MAX_BARS = 6000
MAX_SECONDS = 15 * 60


@dataclass(frozen=True)
class StockSignalStudy:
    """Descriptive signal targets, never a CandidateEvidence or execution artifact."""

    manifest: dict
    targets: tuple[dict, ...]
    result_hash: str

    def __post_init__(self):
        object.__setattr__(self, 'manifest', freeze(self.manifest))
        object.__setattr__(self, 'targets', freeze(self.targets))


def stock_signal_dataset(history, calendar, through) -> Dataset:
    """Project a trusted official history at one completed DAY, with no lookahead."""
    trading_date(through)
    series = price_series(history.bars, history.events, as_of=through)
    if series.bars[-1].trade_date != through:
        raise DomainError('daily_signal_not_available', 'requested completed stock DAY is absent')
    rows = []
    for bar in series.bars:
        session = calendar.day_session(bar.trade_date)
        rows.append(
            Bar(
                session.opens_at.astimezone(timezone.utc),
                session.closes_at.astimezone(timezone.utc),
                bar.trade_date.isoformat(),
                'day',
                history.instrument_id,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                history.source_digest,
            )
        )
    bars = tuple(rows)
    manifest = {
        'source_type': 'official_stock_signal',
        'validation_status': 'valid',
        'data_hash': content_hash(bars),
        'partition': 'TRAINING',
        'interval': '1d',
        'instrument_id': history.instrument_id,
        'through': through.isoformat(),
        'calendar_version': calendar.version,
        'calendar_hash': content_hash(
            (
                calendar.calendar_id,
                calendar.version,
                calendar.source,
                tuple((s.trade_date.isoformat(), s.opens_at.astimezone(timezone.utc), s.closes_at.astimezone(timezone.utc), s.kind) for s in calendar.sessions),
            )
        ),
        'source_digest': history.source_digest,
        **dict(series.evidence()),
    }
    return Dataset(bars, manifest, {'valid': True, 'errors': [], 'missing_intervals': 0})


def _decision_targets(history, calendar, spec, checkpoint):
    """Targets for every raw DAY, equal to `stock_signal_dataset` + `generate_signals` per day.

    The per-day definition rebuilds the whole point-in-time history for each day.
    Between two days on which an official event first enters the observation
    horizon the adjusted history only grows by one unadjusted bar, so every day's
    dataset is a prefix of one series. This reads each such segment once:
    adjusted bars, Bars and the running data hash are built once per segment and
    shared by its days, and the shared signal callable is run once over the
    segment (it is causal: the prefix result is its signals up to that bar).
    Nothing after a decision day ever enters that day's adjustment or hash.
    """
    raws = history.bars
    dates = [bar.trade_date for bar in raws]
    # The checks price_series makes on its whole input at the first decision.
    if tuple(sorted(raws, key=lambda bar: bar.trade_date)) != raws or len(set(dates)) != len(dates):
        raise DomainError('validation_failed', 'ordered unique daily history required')
    instrument = raws[0].instrument_id
    if any(event.instrument_id != instrument for event in history.events):
        raise DomainError('validation_failed', 'single instrument required')
    if len({event.ex_date for event in history.events}) != len(history.events):
        raise DomainError('validation_failed', 'one combined official event per date')
    events = sorted((event for event in history.events if dates[0] < event.ex_date), key=lambda event: event.ex_date)
    # An event takes part from the first decision day on or after its ex-date.
    entry = [bisect_left(dates, event.ex_date) for event in events]
    starts = sorted({0, *(index for index in entry if index < len(raws))})
    ends = [*starts[1:], len(raws)]
    sessions = {}
    for session in calendar.sessions:
        if session.kind == 'DAY':
            sessions.setdefault(session.trade_date, session)
    known_days = {session.trade_date for session in calendar.sessions}
    targets = []
    for lo, stop in zip(starts, ends):
        checkpoint()
        active = tuple(event for event, index in zip(events, entry) if index <= lo)
        adjusted = adjust_bars(raws[:stop], active)
        bars = []
        for bar in adjusted:
            if bar.instrument_id != instrument:
                raise DomainError('validation_failed', 'single instrument required')
            if bar.trade_date not in known_days:
                raise DomainError('calendar_missing', bar.trade_date.isoformat())
            if bar.trade_date not in sessions:
                raise DomainError('calendar_missing', 'day session missing')
            session = sessions[bar.trade_date]
            bars.append(
                Bar(
                    session.opens_at.astimezone(timezone.utc),
                    session.closes_at.astimezone(timezone.utc),
                    bar.trade_date.isoformat(),
                    'day',
                    history.instrument_id,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    history.source_digest,
                )
            )
        bars = tuple(bars)
        # canonical_json(tuple(bars)) == '[' + ','.join(canonical_json(bar)) + ']'
        running = sha256(b'[')
        for index, bar in enumerate(bars[:lo]):
            running.update((b',' if index else b'') + canonical_json(bar).encode('utf-8'))
        shared = all(a.end < b.end for a, b in zip(bars, bars[1:]))
        signals = generate_signals(bars, spec) if shared else None
        position, target = 0, 0
        for index in range(lo, stop):
            checkpoint()
            running.update((b',' if index else b'') + canonical_json(bars[index]).encode('utf-8'))
            digest = running.copy()
            digest.update(b']')
            if signals is None:  # equal bar ends cannot be told apart by timestamp
                current = generate_signals(bars[: index + 1], spec)
                target = max(0, current[-1].target_position) if current else 0
            else:
                while position < len(signals) and signals[position].timestamp <= bars[index].end:
                    target = max(0, signals[position].target_position)
                    position += 1
            targets.append({'at': bars[index].end, 'target': target, 'signal_data_hash': digest.hexdigest()})
    return targets


def _source_identity():
    root = Path(__file__).resolve().parents[2]
    # The v2 profile alone does not cover the shared v1 callable and its admission.
    return {
        'trading_source_digest': compute_profile().source_digest,
        'signal_sources': {name: sha256((root / name).read_bytes()).hexdigest() for name in ('core.py', 'strategies.py', 'research.py', 'backtest.py')},
    }


def research_stock_signals(
    store,
    instrument_id,
    calendar,
    start,
    through,
    signal_spec_json,
    *,
    clock,
    partition='TRAINING',
    cancelled=lambda: False,
    max_seconds=MAX_SECONDS,
    timer=monotonic,
) -> StockSignalStudy:
    """Read the existing official cache; never refresh it or write a result journal.

    This composition entry owns validation and cannot accept a UI-asserted E1
    verdict. TPEx/unknown negative event evidence fails in the official reader.
    """
    _validate_request(instrument_id, calendar, start, through, partition, max_seconds)
    spec = validated_spec(signal_spec_json)
    if 'stop_ticks' in spec.parameters or 'target_ticks' in spec.parameters or spec.parameters.get('quantity', 1) != 1:
        raise DomainError('candidate_spec_unsupported')
    began = timer()

    def checkpoint():
        if cancelled():
            raise DomainError('research_cancelled')
        if timer() - began >= max_seconds:
            raise DomainError('research_timeout')

    checkpoint()
    identity = _source_identity()
    revision = store.verification_revision
    history = OfficialDailyStockSource(store, clock).history(instrument_id, calendar, through=through, start=start)
    if not 1 <= len(history.bars) <= MAX_BARS or len(history.events) > MAX_BARS:
        raise DomainError('official_stock_coverage_missing', 'bounded stock history required')
    targets = _decision_targets(history, calendar, spec, checkpoint)
    # The last decision's dataset (and its evidence) comes from the per-day definition.
    dataset = stock_signal_dataset(history, calendar, history.bars[-1].trade_date)
    if targets[-1]['signal_data_hash'] != dataset.manifest['data_hash'] or targets[-1]['at'] != dataset.bars[-1].end:
        raise DomainError('source_invalid_evidence', 'stock signal projection disagrees with its dataset')
    checkpoint()
    if store.verification_revision != revision or _source_identity() != identity:
        raise DomainError('source_invalid_evidence', 'stock input or signal source changed during research')
    manifest = {
        'producer': PRODUCER,
        'partition': 'TRAINING',
        'scope': 'signals-only; no E1, E2, PnL or execution qualification',
        'direction_policy': 'LONG_ONLY',
        'window': 'FULL_HISTORY_POINT_IN_TIME',
        'signal_spec_json': canonical_spec_json(signal_spec_json),
        'candidate_fingerprint': spec_fingerprint(signal_spec_json),
        'final_dataset': dict(dataset.manifest),
        **identity,
    }
    values = tuple(targets)
    result = StockSignalStudy(manifest, values, content_hash({'manifest': manifest, 'targets': values}))
    checkpoint()
    return result


def _validate_request(instrument_id, calendar, start, through, partition, max_seconds):
    if partition != 'TRAINING':
        raise DomainError('validation_failed', 'stock signal study accepts TRAINING only')
    try:
        validate_signal_contract(instrument_id)
    except ValidationError:
        raise DomainError('auto_instrument_not_allowed') from None
    if not instrument_id.startswith(('TWSE:', 'TPEX:')):
        raise DomainError('auto_instrument_not_allowed')
    if instrument_id.startswith('TPEX:'):
        raise DomainError('daily_signal_source_unverified', 'verified TPEx negative event evidence is not available')
    trading_date(start)
    trading_date(through)
    end = through + timedelta(days=1)
    try:
        five_years_ago = end.replace(year=end.year - 5)
    except ValueError:
        five_years_ago = end.replace(year=end.year - 5, day=28)
    if start > five_years_ago or not calendar.days or calendar.days[0] > start or calendar.days[-1] < through:
        raise DomainError('official_stock_coverage_missing', 'five years and the complete explicit calendar required')
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= MAX_SECONDS:
        raise DomainError('validation_failed', 'bounded stock research deadline required')

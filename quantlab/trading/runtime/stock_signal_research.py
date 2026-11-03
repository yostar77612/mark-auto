"""Bounded host-only stock signal TRAINING, without E1, PnL or execution authority.

The official source verifies local payload bytes and complete calendar/event
coverage. Every decision uses its own full, point-in-time adjusted history.
"""

from dataclasses import dataclass
from datetime import timedelta, timezone
from hashlib import sha256
from pathlib import Path
from time import monotonic

from quantlab.core import Bar, Dataset, content_hash, freeze, validate_signal_contract, ValidationError
from quantlab.trading.domain.stock_history import price_series
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
    targets = []
    for raw in history.bars:
        checkpoint()
        dataset = stock_signal_dataset(history, calendar, raw.trade_date)
        signals = generate_signals(dataset.bars, spec)
        target = max(0, signals[-1].target_position) if signals else 0
        targets.append({'at': dataset.bars[-1].end, 'target': target, 'signal_data_hash': dataset.manifest['data_hash']})
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

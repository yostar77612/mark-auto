"""Explicit synthetic trusted-port fixtures, never evidence of an exchange fetch.

Callers must opt in, supply observations and publish each later close themselves.
This fake deliberately allows a same-day recorded snapshot; the production
provider's conservative publication policy is not changed or inherited here.
"""

from dataclasses import replace
from hashlib import sha256

from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.research import research
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.daily_signal_data import OfficialDailyHistory
from quantlab.trading.domain.stock_history import DailyStockBar
from quantlab.trading.domain.strategy import CompletedBar
from quantlab.trading.domain.validation import DomainError

FAKE_SOURCE_LABEL = 'EXPLICIT_SYNTHETIC_OFFICIAL_DAILY_TEST_PORT'


def fake_official_history(instrument_id, bars, observed_at, *, events=()):
    """Re-express supplied daily test observations, without inventing market facts."""
    initialize()
    digest = sha256((FAKE_SOURCE_LABEL + dumps((instrument_id, bars, events))).encode()).hexdigest()
    rows = tuple(
        DailyStockBar(instrument_id, bar.ended_at.date(), bar.open, max(bar.open, bar.close), min(bar.open, bar.close), bar.close, bar.volume, digest)
        for bar in bars
    )
    return OfficialDailyHistory(instrument_id, rows, tuple(events), observed_at, digest)


class FakeOfficialDailySource:
    """Only explicitly published immutable fixture batches can be read."""

    def __init__(self, histories=()):
        self.histories = {row.instrument_id: row for row in histories}
        self.requests = []

    def publish(self, history):
        self.histories[history.instrument_id] = history

    def history(self, instrument_id, calendar, *, through, start=None, cached_only=False):
        self.requests.append((instrument_id, through, start))
        history = self.histories.get(instrument_id)
        if history is None:
            raise DomainError('daily_signal_source_unverified', 'explicit fake daily input was not published')
        current = history.trim(start or history.bars[0].trade_date, through)
        if current.bars[-1].trade_date != through:
            raise DomainError('daily_signal_not_available', 'fake source does not synthesize missing closes')
        current.raw_completed(calendar)
        return current


def install_fake_official_source(engine, history):
    """Opt-in fixture wiring; a real engine's calendar authority stays unchanged."""
    source = getattr(engine, 'daily_signal_source', None)
    if not isinstance(source, FakeOfficialDailySource):
        source = FakeOfficialDailySource()
        engine.daily_signal_source = source
    source.publish(history)
    if not callable(getattr(engine, '_strategy_calendar', None)):
        engine._strategy_calendar = lambda record, instrument_id=None: calendar_for_instrument(
            engine.calendar, engine.catalog.resolve(instrument_id or record.form.instrument_id)
        )
    return source


def publish_fake_daily_close(engine, instrument_id, day, price, *, volume=270000):
    """Publish an explicit scenario's daily observation, independent of its minute tape."""
    source = engine.daily_signal_source
    if not isinstance(source, FakeOfficialDailySource):
        raise AssertionError('daily close publication requires the explicit fake source')
    calendar = calendar_for_instrument(engine.calendar, engine.catalog.resolve(instrument_id))
    session = calendar.day_session(day)
    previous = source.histories[instrument_id].raw_completed(calendar)
    rows = tuple(row for row in previous if row.ended_at < session.opens_at)
    close = CompletedBar(session.opens_at, session.closes_at, session.closes_at, price, price, volume)
    source.publish(fake_official_history(instrument_id, (*rows, close), engine.clock.now()))


def official_research_fixture(engine, record, history):
    """Produce real pure research over labelled synthetic official-input data."""
    install_fake_official_source(engine, history)
    calendar = engine._strategy_calendar(record, record.form.instrument_id)
    raw = history.raw_completed(calendar)
    result = research(
        record,
        engine.catalog.resolve(record.form.instrument_id),
        calendar,
        raw,
        engine.fees,
        source_profile=getattr(engine, 'profile', None),
        daily_history=history,
    )
    return replace(record, research_blob=dumps(result), evidence_hash=result.fingerprint, evidence='EXPLICIT_SYNTHETIC_OFFICIAL_DAILY_FIXTURE'), result


def official_intent_fixture(engine, record, intent):
    """Use the application's real hash authority; do not substitute a PASS flag."""
    from quantlab.trading.application.daily_signal_data import _signal_window_hash

    result = loads(record.research_blob)
    calendar = engine._strategy_calendar(record, intent.instrument_id)
    session = next(row for row in calendar.sessions if row.kind == 'DAY' and row.closes_at == intent.cursor.bar_end)
    history = engine.daily_signal_source.history(intent.instrument_id, calendar, through=session.trade_date, start=result.daily_basis.start)
    signals = history.signal_history(calendar, session.trade_date)
    return replace(
        intent,
        evidence_fingerprint=record.evidence_hash,
        data_policy_fingerprint=history.policy.fingerprint,
        data_fingerprint=_signal_window_hash(history, calendar, session.trade_date, signals),
    )

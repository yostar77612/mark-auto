"""Read-only, payload-verified official daily cache for stock signals."""

from collections import OrderedDict
from dataclasses import replace
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import re
from threading import Lock
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from quantlab.trading.adapters.official.stock_data import daily_url, events_url, parse_daily, parse_events, stock_identity
from quantlab.trading.adapters.official.daily_signal_events import daily_event_scope, parse_daily_signal_events
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.daily_signal_data import OfficialDailyHistory
from quantlab.trading.domain.validation import DomainError, aware, trading_date
from quantlab.trading.ports.stock_history import DailyStockStore


MAX_VERIFIED_HISTORIES = 128


def _query(url):
    parsed = urlsplit(url)
    values = parse_qs(parsed.query, strict_parsing=True)
    if parsed.scheme != 'https' or parsed.fragment or any(len(value) != 1 for value in values.values()):
        raise ValueError('official source URL')
    return parsed, {name: value[0] for name, value in values.items()}


def _roc_day(value):
    year, month, day = map(int, value.split('/'))
    return date(year + 1911, month, day)


def _source_scope(url, instrument_id):
    """Admit only endpoints and exact request identities understood by the parser."""
    venue, _ = stock_identity(instrument_id)
    parsed, query = _query(url)
    host = 'www.twse.com.tw' if venue == 'TWSE' else 'www.tpex.org.tw'
    if parsed.netloc != host:
        raise ValueError('source exchange mismatch')
    daily_paths = (
        ('/exchangeReport/STOCK_DAY', '/rwd/zh/afterTrading/STOCK_DAY') if venue == 'TWSE' else ('/web/stock/aftertrading/daily_trading_info/st43_result.php',)
    )
    if parsed.path in daily_paths:
        month = datetime.strptime(query['date'], '%Y%m%d').date() if venue == 'TWSE' else _roc_day(query['d'] + '/01')
        if month.day != 1 or query != _query(daily_url(instrument_id, month))[1]:
            raise ValueError('daily request identity mismatch')
        return 'daily', month, None
    if venue == 'TWSE' and parsed.path in ('/rwd/zh/exRight/TWT49U', '/exchangeReport/TWT49U'):
        first, last = daily_event_scope(url)
        return 'global_events', first, last
    event_path = '/exchangeReport/TWT48U' if venue == 'TWSE' else '/web/stock/exright/dailyquo/exDailyQ_result.php'
    if parsed.path != event_path:
        raise ValueError('unsupported official endpoint')
    if venue == 'TWSE':
        first, last = (datetime.strptime(query[key], '%Y%m%d').date() for key in ('startDate', 'endDate'))
    else:
        first, last = (_roc_day(query[key]) for key in ('d', 'ed'))
    if first >= last or query != _query(events_url(instrument_id, first, last))[1]:
        raise ValueError('event request identity mismatch')
    return 'events', first, last


def _covered(ranges, first, end):
    cursor = first
    for start, stop in sorted(ranges):
        if start > cursor:
            break
        cursor = max(cursor, stop)
        if cursor >= end:
            return True
    return False


def _verified_sources(store, batch, first, end, sessions, now):
    daily, events, event_ranges, sources = {}, {}, [], []
    arrivals, daily_sources, required = {}, {}, set()
    for payload in batch.payloads:
        original = store.official_payload(payload.source_url, payload.digest)
        if original != payload or sha256(payload.raw).hexdigest() != payload.digest:
            raise DomainError('daily_signal_source_unverified', 'official payload bytes differ')
        source_key = payload.source_url, payload.digest
        arrivals[source_key] = store.official_payload_arrival(*source_key)
        try:
            kind, start, stop = _source_scope(payload.source_url, batch.instrument_id)
            if kind == 'daily':
                rows = parse_daily(payload.raw, batch.instrument_id, start)
                # Native TWSE titles identify the stock independently of the URL.
                title = json.loads(payload.raw.decode('utf-8-sig')).get('title')
                if title is not None and not re.search(r'(?<!\d)' + stock_identity(batch.instrument_id)[1] + r'(?!\d)', title):
                    raise ValueError('daily response stock mismatch')
                for row in rows:
                    if first <= row.trade_date < end:
                        daily[(row.trade_date, row.source_digest)] = row
                        daily_sources[(row.trade_date, row.source_digest)] = source_key
            else:
                rows = (
                    parse_daily_signal_events(payload.raw, batch.instrument_id, payload.source_url)
                    if kind == 'global_events'
                    else parse_events(payload.raw, batch.instrument_id, start, stop, payload.source_url)
                )
                event_ranges.append((start, stop))
                if start < end and stop > first:
                    required.add(source_key)
                for row in rows:
                    if first <= row.ex_date < end:
                        events[(row.ex_date, row.source_digest, row.source_url)] = row
        except (DomainError, ValueError, KeyError, TypeError, UnicodeError):
            raise DomainError('daily_signal_source_unverified', 'unsupported official payload identity or schema') from None
        sources.append((payload.source_url, payload.digest))
    if not _covered(event_ranges, first, end):
        raise DomainError('daily_signal_source_unverified', 'complete event-response coverage required, including empty responses')
    if any(daily.get((bar.trade_date, bar.source_digest)) != bar for bar in batch.bars):
        raise DomainError('daily_signal_source_unverified', 'cached daily values differ from official payload')
    actual = {(row.ex_date, row.source_digest, row.source_url): row for row in batch.events}
    if any(events.get(key) != row for key, row in actual.items()):
        raise DomainError('daily_signal_source_unverified', 'cached event values differ from official payload')
    # Overlapping refresh manifests can attest identical facts at different URLs.
    # Keep exact current-row provenance above and every historical positive below;
    # conflicting facts or a removed positive cannot become negative evidence.
    expected_facts = {(row.ex_date, row.previous_close, row.reference_price) for row in events.values()}
    actual_facts = {(row.ex_date, row.previous_close, row.reference_price) for row in actual.values()}
    if actual_facts != expected_facts:
        raise DomainError('daily_signal_source_unverified', 'cached event values differ from complete official responses')
    required.update(daily_sources[(bar.trade_date, bar.source_digest)] for bar in batch.bars)
    for source_key in required:
        arrival = arrivals[source_key]
        if arrival is None:
            raise DomainError('daily_signal_source_unverified', 'actual official payload arrival is unknown')
        aware(arrival)
        if arrival > now:
            raise DomainError('daily_signal_not_available', 'official payload arrival is in the future')
    for bar in batch.bars:
        source_key = daily_sources[(bar.trade_date, bar.source_digest)]
        if arrivals[source_key] < sessions[bar.trade_date].closes_at:
            raise DomainError('daily_signal_not_available', 'daily payload was observed before its completed DAY')
    material = json.dumps(sorted(set(sources)), separators=(',', ':'), ensure_ascii=True)
    return sha256(material.encode()).hexdigest(), max(arrivals[source_key] for source_key in required)


class OfficialDailyStockSource:
    def __init__(self, store: DailyStockStore, clock):
        self.store, self.clock = store, clock
        self._cache_store = store
        self._cache = OrderedDict()
        self._cache_lock = Lock()

    def history(
        self, instrument_id: str, calendar: TradingCalendar, *, through: date, start: date | None = None, cached_only: bool = False
    ) -> OfficialDailyHistory:
        """Only warmed same-revision values are usable by the locked hot path."""
        try:
            history = self._cached_history(instrument_id, calendar, through=through, start=start, cached_only=cached_only)
            if history is None:
                raise DomainError('daily_signal_not_available', 'verified official history must be prepared outside the writer locks')
            return history
        except DomainError:
            raise
        except Exception:
            raise DomainError('daily_signal_source_unverified', 'official history boundary failed') from None

    def cached_history(self, instrument_id: str, calendar: TradingCalendar, *, through: date, start: date | None = None) -> OfficialDailyHistory | None:
        """Probe current verified values only; None means an actual absent cache key."""
        try:
            return self._cached_history(instrument_id, calendar, through=through, start=start, cached_only=True)
        except DomainError:
            raise
        except Exception:
            raise DomainError('daily_signal_source_unverified', 'official history boundary failed') from None

    def _cached_history(self, instrument_id, calendar, *, through, start, cached_only):
        stock_identity(instrument_id)
        trading_date(through)
        now = aware(self.clock.now())
        if through >= now.astimezone(ZoneInfo('Asia/Taipei')).date():
            raise DomainError('daily_signal_not_available', 'only prior civil-day official data is available')
        if calendar.day_session(through).closes_at >= now:
            raise DomainError('daily_signal_not_available', 'verified DAY session has not completed')
        store = self.store
        revision = store.verification_revision
        key = instrument_id, through, start, revision, calendar
        with self._cache_lock:
            if self._cache_store is not store:
                self._cache.clear()
                self._cache_store = store
            history = self._cache.get(key)
            if history is not None:
                self._cache.move_to_end(key)
        if history is None and not cached_only:
            history = self._load_history(store, instrument_id, calendar, through=through, start=start, now=now)
        if self.store is not store or store.verification_revision != revision:
            raise DomainError('daily_signal_source_unverified', 'official cache changed while verifying history')
        if history is None:
            return None
        if history.observed_at > now:
            raise DomainError('daily_signal_not_available', 'official history has not arrived at this clock time')
        with self._cache_lock:
            self._cache[key] = history
            self._cache.move_to_end(key)
            while len(self._cache) > MAX_VERIFIED_HISTORIES:
                self._cache.popitem(last=False)
        return history

    def _load_history(self, store, instrument_id, calendar, *, through, start, now):
        first, end = calendar.days[0] if start is None else trading_date(start), through + timedelta(days=1)
        if first > through:
            raise DomainError('daily_signal_not_available', 'empty official daily history')
        batch = store.daily_history(instrument_id, first, end)
        if not batch.bars or len(batch.bars) > 6000 or batch.bars[-1].trade_date != through:
            raise DomainError('daily_signal_not_available', 'bounded history must include the requested completed day')
        if start is None:
            first = batch.bars[0].trade_date
            batch = replace(batch, start=first, events=tuple(event for event in batch.events if first <= event.ex_date < end))
        expected = tuple(day for day in calendar.days if first <= day <= through)
        sessions = {row.trade_date: row for row in calendar.sessions if row.kind == 'DAY'}
        if tuple(bar.trade_date for bar in batch.bars) != expected or not store.daily_coverage(instrument_id, first, end):
            raise DomainError('daily_signal_not_available', 'complete verified DAY coverage required; missing bars are never padded')
        for day in expected:
            if day not in sessions:
                raise DomainError('calendar_missing', 'day session missing')
            if sessions[day].closes_at >= now:
                raise DomainError('daily_signal_not_available', 'official DAY history is not complete')
        digest, observed_at = _verified_sources(store, batch, first, end, sessions, now)
        history = OfficialDailyHistory(instrument_id, batch.bars, batch.events, observed_at, digest)
        history.validate_previous_closes(calendar)
        return history

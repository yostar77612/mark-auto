"""Read-only, payload-verified official daily cache for stock signals."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from quantlab.trading.adapters.official.stock_data import daily_url, events_url, parse_daily, parse_events, stock_identity
from quantlab.trading.adapters.official.daily_signal_events import daily_event_scope, parse_daily_signal_events
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.daily_signal_data import OfficialDailyHistory
from quantlab.trading.domain.validation import DomainError, aware, trading_date
from quantlab.trading.ports.stock_history import DailyStockStore


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


def _verified_sources(store, batch, first, end):
    daily, events, event_ranges, sources = {}, {}, [], []
    for payload in batch.payloads:
        original = store.official_payload(payload.source_url, payload.digest)
        if original != payload or sha256(payload.raw).hexdigest() != payload.digest:
            raise DomainError('daily_signal_source_unverified', 'official payload bytes differ')
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
            else:
                rows = (
                    parse_daily_signal_events(payload.raw, batch.instrument_id, payload.source_url)
                    if kind == 'global_events'
                    else parse_events(payload.raw, batch.instrument_id, start, stop, payload.source_url)
                )
                event_ranges.append((start, stop))
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
    material = json.dumps(sorted(set(sources)), separators=(',', ':'), ensure_ascii=True)
    return sha256(material.encode()).hexdigest()


class OfficialDailyStockSource:
    def __init__(self, store: DailyStockStore, clock):
        self.store, self.clock = store, clock

    def history(self, instrument_id: str, calendar: TradingCalendar, *, through: date, start: date | None = None) -> OfficialDailyHistory:
        stock_identity(instrument_id)
        trading_date(through)
        observed_at = aware(self.clock.now())
        if through >= observed_at.astimezone(ZoneInfo('Asia/Taipei')).date():
            raise DomainError('daily_signal_not_available', 'only prior civil-day official data is available')
        if calendar.day_session(through).closes_at >= observed_at:
            raise DomainError('daily_signal_not_available', 'verified DAY session has not completed')
        first, end = calendar.days[0] if start is None else trading_date(start), through + timedelta(days=1)
        if first > through:
            raise DomainError('daily_signal_not_available', 'empty official daily history')
        batch = self.store.daily_history(instrument_id, first, end)
        if not batch.bars or len(batch.bars) > 6000 or batch.bars[-1].trade_date != through:
            raise DomainError('daily_signal_not_available', 'bounded history must include the requested completed day')
        if start is None:
            first = batch.bars[0].trade_date
            batch = replace(batch, start=first, events=tuple(event for event in batch.events if first <= event.ex_date < end))
        expected = tuple(day for day in calendar.days if first <= day <= through)
        if tuple(bar.trade_date for bar in batch.bars) != expected or not self.store.daily_coverage(instrument_id, first, end):
            raise DomainError('daily_signal_not_available', 'complete verified DAY coverage required; missing bars are never padded')
        for day in expected:
            if calendar.day_session(day).closes_at >= observed_at:
                raise DomainError('daily_signal_not_available', 'official DAY history is not complete')
        digest = _verified_sources(self.store, batch, first, end)
        return OfficialDailyHistory(instrument_id, batch.bars, batch.events, observed_at, digest)

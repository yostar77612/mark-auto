"""Sector ranking from market-wide snapshot rounds; read-only, fail-closed on stale or missing data."""

from collections import deque
import logging
from datetime import date, datetime, time
from decimal import Decimal
from threading import RLock
from typing import Callable
from zoneinfo import ZoneInfo

from quantlab.trading.domain.concept_groups import BUILTIN_GROUPS, ConceptGroup
from quantlab.trading.domain.industry_names import industry_name
from quantlab.trading.domain.sector_alerts import SectorAlert
from quantlab.trading.domain.sector import QuoteRow, SectorGroup, SectorStat, compute_stats, eligible_stock, sort_stats
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import WatchInstrument, WatchKind
from quantlab.trading.ports.sector import SnapshotSourcePort
from .sector_contracts import MemberView, MonitorCount, SectorBoardView, ShareBaseline

_TAIPEI = ZoneInfo('Asia/Taipei')
logger = logging.getLogger(__name__)
SESSION_START, SESSION_END = time(8, 55), time(13, 35)
STALE_SECONDS = 30


def _quotes_are_from_today(rows: dict[str, QuoteRow], fetched: datetime) -> bool:
    """In session, at least one quote must carry today's (Taipei) date; outside it nothing is judged."""
    if not in_session(fetched):
        return True
    today = fetched.astimezone(_TAIPEI).date()
    # any(), not max(): one stray future-dated row must not switch a whole trading day off.
    return any(row.at.astimezone(_TAIPEI).date() == today for row in rows.values())


def in_session(now: datetime) -> bool:
    local = now.astimezone(_TAIPEI)
    return local.weekday() < 5 and SESSION_START <= local.time() <= SESSION_END


def industry_groups(stocks: tuple[WatchInstrument, ...]) -> tuple[SectorGroup, ...]:
    by_category: dict[str, list[str]] = {}
    for item in stocks:
        if item.category:
            by_category.setdefault(item.category, []).append(item.code)
    return tuple(SectorGroup('industry.' + code, industry_name(code), 'INDUSTRY', tuple(codes)) for code, codes in sorted(by_category.items()))


class SectorService:
    def __init__(
        self,
        directory: Callable[[], tuple[WatchInstrument, ...]],
        source: SnapshotSourcePort,
        now: Callable[[], datetime],
        *,
        concepts: Callable[[], tuple[ConceptGroup, ...]] = lambda: BUILTIN_GROUPS,
        interval_seconds: int = 10,
    ):
        self.directory, self.source, self.now, self.concepts = directory, source, now, concepts
        self.interval_seconds = interval_seconds
        self.lock = RLock()
        self._rows: dict[str, QuoteRow] = {}
        self._stats: tuple[SectorStat, ...] = ()
        self._groups: dict[str, SectorGroup] = {}
        self._fetched_at: datetime | None = None
        self._failed = False
        self._first_limit_up: dict[str, datetime] = {}
        self._limit_day: date | None = None
        self._data_is_today = True
        self._generation = 0
        self._closing_day: date | None = None
        # True while on_round runs for the one extra after-close round (see due): the sector hooks skip it.
        self.after_close_round = False
        self._alerts: deque[SectorAlert] = deque(maxlen=200)
        self.on_round: Callable[[datetime, tuple[SectorStat, ...]], tuple[SectorAlert, ...]] = lambda now, stats: ()
        self.on_alert: Callable[[SectorAlert], None] = lambda alert: None
        self.monitor_info: Callable[[], tuple[tuple[str, ...], tuple[tuple[str, int, int], ...]]] = lambda: ((), ())
        self.side_ratio: Callable[[str], Decimal | None] = lambda code: None
        self.share_baselines: Callable[[], tuple[ShareBaseline, ...]] = lambda: ()

    def stocks(self) -> tuple[WatchInstrument, ...]:
        return tuple(item for item in self.directory() if item.kind is WatchKind.STOCK and eligible_stock(item.code))

    def groups(self) -> tuple[SectorGroup, ...]:
        concept = tuple(SectorGroup(group.id, group.name, 'CONCEPT', group.codes) for group in self.concepts())
        return (*industry_groups(self.stocks()), *concept)

    def _closing_due(self, now: datetime) -> bool:
        """One weekday round after the session ends, so the stock screener judges the final day totals."""
        local = now.astimezone(_TAIPEI)
        return local.weekday() < 5 and local.time() > SESSION_END and self._closing_day != local.date()

    def due(self) -> bool:
        """One round when nothing is loaded yet or after a failure; rounds continue in session and once after close."""
        if not self.source.connected:
            return False
        with self.lock:
            now = self.now()
            return not self._rows or self._failed or in_session(now) or self._closing_due(now)

    def status(self) -> str:
        """OFFLINE, EMPTY, CLOSED, STALE or LIVE, the same state the board shows."""
        with self.lock:
            return self._state(self.now())

    def quotes(self) -> dict[str, QuoteRow]:
        """The last accepted round, copied so callers can work outside the lock."""
        with self.lock:
            return dict(self._rows)

    def refresh(self) -> None:
        stocks = self.stocks()
        if not stocks:
            return
        with self.lock:
            generation = self._generation
            now = self.now()
            extra_closing = bool(self._rows) and not self._failed and not in_session(now) and self._closing_due(now)
        try:
            rows = {row.code: row for row in self.source.snapshots(stocks)}
        except DomainError:
            with self.lock:
                if generation == self._generation:
                    self._failed = True
            return
        groups = self.groups()
        with self.lock:
            if generation != self._generation:
                return
            self._failed = False
            self._rows, self._fetched_at = rows, self.now()
            if self._closing_due(self._fetched_at):
                self._closing_day = self._fetched_at.astimezone(_TAIPEI).date()
            self.after_close_round = extra_closing
            self._groups = {group.id: group for group in groups}
            self._stats = compute_stats(groups, rows)
            self._track_limit_up(rows)
            fetched, stats = self._fetched_at, self._stats
            self._data_is_today = _quotes_are_from_today(rows, fetched)
            from_today = self._data_is_today
        if not from_today:
            # A weekday holiday (no calendar here): the exchange is closed and every snapshot still carries the last
            # trading day's closing totals. Storing them under today's date would pollute the 5-day baseline and
            # replay, and judging them could raise alerts and subscribe ticks for a market that is not trading.
            return
        # Hooks run outside the lock: they write to disk, may subscribe to ticks and may call back into the service.
        alerts = self.on_round(fetched, stats)
        with self.lock:
            self._alerts.extend(alerts)
        for alert in alerts:
            try:
                self.on_alert(alert)
            except Exception:
                logger.error('sector alert delivery failed')

    def _track_limit_up(self, rows: dict[str, QuoteRow]) -> None:
        latest = max((row.at for row in rows.values()), default=None)
        today = self.now().astimezone(_TAIPEI).date()
        # A stray future timestamp must not move the day; in session only today's rows can set a leader time.
        day = min(latest.astimezone(_TAIPEI).date(), today) if latest is not None else None
        if in_session(self.now()) and day != today:
            day = None
        if day != self._limit_day:
            self._first_limit_up, self._limit_day = {}, day
        for code, row in rows.items():
            if row.limit == 'UP' and row.at.astimezone(_TAIPEI).date() == day:
                self._first_limit_up.setdefault(code, row.at)
            else:
                self._first_limit_up.pop(code, None)

    def recompute(self) -> None:
        """Re-rank the last snapshot with the current group list, e.g. right after the user edits a group."""
        groups = self.groups()
        with self.lock:
            if self._rows:
                self._groups = {group.id: group for group in groups}
                self._stats = compute_stats(groups, self._rows)

    def candidates(self, group_id: str) -> tuple[tuple[WatchInstrument, int], ...]:
        """Members of a group that have a quote, with their turnover, for choosing what to subscribe."""
        with self.lock:
            group = self._groups.get(group_id)
            if group is None:
                return ()
            rows = self._rows
            codes = [code for code in dict.fromkeys(group.codes) if code in rows]
        stocks = {item.code: item for item in self.stocks()}
        return tuple((stocks[code], rows[code].total_amount) for code in codes if code in stocks)

    def group_name(self, group_id: str) -> str:
        group = self._groups.get(group_id)
        return group.name if group is not None else group_id

    def disconnected(self) -> None:
        with self.lock:
            self._generation += 1
            self._rows, self._stats, self._groups, self._fetched_at = {}, (), {}, None
            self._first_limit_up, self._limit_day, self._failed = {}, None, False
            self._data_is_today = True

    def _state(self, now: datetime) -> str:
        if not self.source.connected:
            return 'OFFLINE'
        if self._fetched_at is None:
            return 'EMPTY'
        if not in_session(now) or not self._data_is_today:
            return 'CLOSED'
        return 'STALE' if (now - self._fetched_at).total_seconds() > STALE_SECONDS else 'LIVE'

    def board(self, group_id: str = '', sort_key: str = 'equal_pct') -> SectorBoardView:
        with self.lock:
            now = self.now()
            state = self._state(now)
            if state in ('OFFLINE', 'EMPTY'):
                return SectorBoardView(state, interval_seconds=self.interval_seconds, failed=self._failed)
            selected = group_id if group_id in self._groups else ''
            monitored, counts = self.monitor_info()
            return SectorBoardView(
                state,
                max((row.at for row in self._rows.values()), default=None),
                int((now - self._fetched_at).total_seconds()),
                self.interval_seconds,
                sum(1 for code in self._rows if eligible_stock(code)),
                sort_stats(self._stats, sort_key),
                selected,
                self._members(selected) if selected else (),
                self._failed,
                tuple(reversed(self._alerts)),
                monitored,
                tuple(MonitorCount(*item) for item in counts),
                self.share_baselines(),
            )

    def _members(self, group_id: str) -> tuple[MemberView, ...]:
        stocks = {item.code: item for item in self.stocks()}
        codes = [code for code in dict.fromkeys(self._groups[group_id].codes) if code in self._rows]
        limit_up = {code: self._first_limit_up[code] for code in codes if code in self._first_limit_up}
        leader = min(limit_up, key=limit_up.get) if limit_up else ''
        members = [
            MemberView(
                stocks[code].instrument_id if code in stocks else code,
                code,
                stocks[code].name if code in stocks else code,
                self._rows[code].price,
                self._rows[code].change_pct,
                self._rows[code].volume_ratio,
                self._rows[code].total_amount,
                self._rows[code].limit,
                limit_up.get(code),
                code == leader,
                self.side_ratio(code),
            )
            for code in codes
        ]
        return tuple(sorted(members, key=lambda member: member.change_pct, reverse=True))

"""Sector money-flow monitoring: which groups to watch, which members to subscribe, when a flow is persistent.

Pure functions and small state classes; amounts are integer NT$ and ratios Decimal.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .sector import SectorStat
from .sector_alerts import SectorAlertParams

MIN_MEMBERS = 4
WARMUP_MINUTES = 5
BASELINE_MINUTES = 30
LOT_SHARES = 1000


def tick_amount(price: Decimal, lots: int) -> int:
    """NT$ traded by one tick; stock volume is in lots of 1,000 shares."""
    return int((price * lots * LOT_SHARES).to_integral_value())


class MonitorSelector:
    """Top groups by equal-weight gain; a group pushed out of the top stays for the retention period."""

    def __init__(self) -> None:
        self._last_top: dict[str, datetime] = {}

    def update(self, stats: tuple[SectorStat, ...], now: datetime, params: SectorAlertParams) -> tuple[str, ...]:
        eligible = [item for item in stats if item.valid_count >= MIN_MEMBERS and item.equal_pct is not None]
        ranked = sorted(eligible, key=lambda item: item.equal_pct, reverse=True)
        for item in ranked[: params.monitor_groups]:
            self._last_top[item.group_id] = now
        keep = timedelta(minutes=params.monitor_keep_minutes)
        valid = {item.group_id for item in eligible}
        self._last_top = {gid: seen for gid, seen in self._last_top.items() if gid in valid and now - seen <= keep}
        order = {item.group_id: index for index, item in enumerate(ranked)}
        return tuple(sorted(self._last_top, key=lambda gid: order[gid]))

    def reset(self) -> None:
        self._last_top = {}


@dataclass(frozen=True)
class Allocation:
    codes: tuple[str, ...]
    counts: tuple[tuple[str, int, int], ...]  # group id, monitored members, total members


def allocate(groups: tuple[tuple[str, tuple[tuple[str, int], ...]], ...], budget: int, held: tuple[str, ...] = ()) -> Allocation:
    """Fill the budget group by group (in rank order), biggest turnover first within a group.

    ``groups`` holds (group id, ((code, turnover), ...)); a stock shared by several groups costs one slot.
    ``held`` are codes already subscribed: they keep their slots first, so a rank or turnover flip under a tight
    budget does not churn subscriptions.
    """
    chosen: dict[str, None] = {}
    known = {code for _, members in groups for code, _ in members}
    for code in held:
        if code in known and len(chosen) < budget:
            chosen[code] = None
    counts = []
    for group_id, members in groups:
        ordered = sorted(members, key=lambda item: item[1], reverse=True)
        for code, _ in ordered:
            if code not in chosen and len(chosen) < budget:
                chosen[code] = None
        counts.append((group_id, sum(1 for code, _ in members if code in chosen), len(members)))
    return Allocation(tuple(chosen), tuple(counts))


@dataclass(frozen=True)
class FlowMinute:
    minute: datetime
    net: int
    big_net: int


def judge_flow(history: tuple[FlowMinute, ...], params: SectorAlertParams) -> tuple[str, int, int, int] | None:
    """Persistent same-sign flow over the latest minutes -> (direction, net, big_net, minutes), else None.

    Each streak minute must reach max(floor, multiple x the mean |net| of the preceding baseline minutes).
    """
    streak = history[-params.flow_minutes :]
    if len(streak) < params.flow_minutes:
        return None
    if any(item.minute - previous.minute != timedelta(minutes=1) for previous, item in zip(streak, streak[1:])):
        return None
    signs = {(item.net > 0) - (item.net < 0) for item in streak}
    if len(signs) != 1 or 0 in signs:
        return None
    before = history[: -params.flow_minutes][-BASELINE_MINUTES:]
    baseline = sum(abs(item.net) for item in before) // len(before) if before else 0
    need = max(params.flow_floor, int(baseline * params.flow_multiple))
    if any(abs(item.net) < need for item in streak):
        return None
    net, big = sum(item.net for item in streak), sum(item.big_net for item in streak)
    # big-order net keeps its sign relative to the flow: negative means large orders went the other way
    return ('UP' if net > 0 else 'DOWN', abs(net), big if net > 0 else -big, params.flow_minutes)

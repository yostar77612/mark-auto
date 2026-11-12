"""M5-5: monitored group selection, subscription budget/priority, flow alert (B) replay, side ratio display."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from quantlab.trading.application.sector_monitor import SectorMonitor
from quantlab.trading.domain.sector import SectorStat
from quantlab.trading.domain.sector_alerts import SectorAlertParams
from quantlab.trading.domain.sector_flow import FlowMinute, MonitorSelector, allocate, judge_flow, tick_amount
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import WatchInstrument, WatchKind
from tests.test_m5_sector import release

TAIPEI = timezone(timedelta(hours=8))
DAY = datetime(2026, 11, 9, tzinfo=TAIPEI)
GOLDEN = Path(__file__).parent / 'fixtures' / 'm5_monitor_replay_golden.json'
MILLION = 1_000_000


def at(hour, minute, second=0):
    return DAY.replace(hour=hour, minute=minute, second=second)


START = at(9, 10)


def stock(code):
    return WatchInstrument(f'TWSE:{code}', WatchKind.STOCK, 'TSE', code, 'N' + code)


def stat(group, pct, valid=5, amount=10**9):
    return SectorStat(group, group.upper(), 'CONCEPT', Decimal(str(pct)), valid, valid, valid, 0, 0, amount, Decimal('0.1'))


def tick(code, amount, side, when):
    lots = amount // 100_000  # price 100: one lot is NT$100,000
    return Tick(f'TWSE:{code}', Decimal(100), lots, when, when, when.date(), side=side)


class SelectorTests(unittest.TestCase):
    def test_top_groups_by_equal_gain_skip_small_groups(self):
        selector = MonitorSelector()
        stats = (stat('a', 3), stat('b', 2.5), stat('tiny', 9, valid=3), stat('c', 2), stat('d', 1), stat('e', 0.5))
        self.assertEqual(selector.update(stats, at(9, 30), SectorAlertParams()), ('a', 'b', 'c'))

    def test_a_group_pushed_out_stays_five_minutes_then_leaves(self):
        selector, params = MonitorSelector(), SectorAlertParams()
        selector.update((stat('a', 3), stat('b', 2.5), stat('c', 2), stat('d', 1)), at(9, 30), params)
        pushed = (stat('a', 3), stat('b', 2.5), stat('d', 2.2), stat('c', 1))
        self.assertEqual(selector.update(pushed, at(9, 31), params), ('a', 'b', 'd', 'c'))
        self.assertEqual(selector.update(pushed, at(9, 35), params), ('a', 'b', 'd', 'c'))
        self.assertEqual(selector.update(pushed, at(9, 36, 1), params), ('a', 'b', 'd'))

    def test_group_that_loses_enough_members_is_dropped_at_once(self):
        selector, params = MonitorSelector(), SectorAlertParams()
        selector.update((stat('a', 3), stat('b', 2)), at(9, 30), params)
        self.assertEqual(selector.update((stat('a', 3, valid=3), stat('b', 2)), at(9, 31), params), ('b',))

    def test_rank_flips_between_rounds_keep_the_same_set(self):
        selector, params = MonitorSelector(), SectorAlertParams()
        results = []
        for minute, order in enumerate((('a', 'b', 'c', 'd'), ('a', 'b', 'd', 'c'), ('a', 'b', 'c', 'd'), ('d', 'a', 'b', 'c'))):
            stats = tuple(stat(group, 4 - index) for index, group in enumerate(order))
            results.append(frozenset(selector.update(stats, at(9, 30 + minute), params)))
        self.assertEqual(results[1:], [frozenset('abcd')] * 3)


class AllocationTests(unittest.TestCase):
    def test_rank_order_then_turnover_and_a_shared_stock_costs_one_slot(self):
        groups = (('g1', (('1', 5), ('2', 9), ('3', 1))), ('g2', (('2', 9), ('4', 7), ('5', 3))))
        plan = allocate(groups, 4)
        self.assertEqual(plan.codes, ('2', '1', '3', '4'))
        self.assertEqual(plan.counts, (('g1', 3, 3), ('g2', 2, 3)))
        self.assertEqual(allocate(groups, 0).codes, ())
        self.assertEqual(allocate(groups, 99).codes, ('2', '1', '3', '4', '5'))

    def test_tick_amount_is_in_lots_of_1000_shares(self):
        self.assertEqual(tick_amount(Decimal('100.5'), 3), 301_500)


class FlowJudgementTests(unittest.TestCase):
    def history(self, *nets, start=at(9, 0)):
        return tuple(FlowMinute(start + timedelta(minutes=index), net, net // 2) for index, net in enumerate(nets))

    def test_same_sign_streak_over_the_floor(self):
        result = judge_flow(self.history(*(2 * MILLION,) * 5, 15 * MILLION, 12 * MILLION, 11 * MILLION), SectorAlertParams())
        self.assertEqual(result, ('UP', 38 * MILLION, 19 * MILLION, 3))

    def test_opposite_sign_or_zero_or_short_history_breaks_it(self):
        params = SectorAlertParams()
        self.assertIsNone(judge_flow(self.history(15 * MILLION, -15 * MILLION, 15 * MILLION), params))
        self.assertIsNone(judge_flow(self.history(15 * MILLION, 0, 15 * MILLION), params))
        self.assertIsNone(judge_flow(self.history(15 * MILLION, 15 * MILLION), params))

    def test_each_minute_must_reach_floor_and_twice_the_recent_average(self):
        params = SectorAlertParams()
        self.assertIsNone(judge_flow(self.history(15 * MILLION, 15 * MILLION, 9 * MILLION), params))
        loud = (40 * MILLION,) * 10
        self.assertIsNone(judge_flow(self.history(*loud, 15 * MILLION, 15 * MILLION, 15 * MILLION), params))
        self.assertEqual(judge_flow(self.history(*loud, 81 * MILLION, 81 * MILLION, 81 * MILLION), params)[0], 'UP')

    def test_a_missing_minute_breaks_the_streak(self):
        history = self.history(15 * MILLION, 15 * MILLION, 15 * MILLION)
        gapped = (history[0], history[1], FlowMinute(history[2].minute + timedelta(minutes=1), 15 * MILLION, 0))
        self.assertIsNone(judge_flow(gapped, SectorAlertParams()))

    def test_sell_streak_is_down(self):
        self.assertEqual(judge_flow(self.history(-15 * MILLION, -15 * MILLION, -15 * MILLION), SectorAlertParams())[0], 'DOWN')


class Subscriptions:
    def __init__(self, capacity=10, taken=0):
        self.capacity, self.subscribed, self.calls = capacity, {f'T{index}' for index in range(taken)}, []

    def free_slots(self):
        return self.capacity - len(self.subscribed)

    def is_subscribed(self, instrument_id):
        return instrument_id in self.subscribed

    def subscribe(self, instrument):
        self.calls.append(('subscribe', instrument.instrument_id))
        if len(self.subscribed) >= self.capacity:
            raise DomainError('subscription_limit_reached')
        self.subscribed.add(instrument.instrument_id)

    def unsubscribe(self, instrument_id):
        self.calls.append(('unsubscribe', instrument_id))
        self.subscribed.discard(instrument_id)


MEMBERS = {
    'gA': tuple((stock(code), (10 - index) * 10**8) for index, code in enumerate(('1101', '1102', '1103', '1104'))),
    'gB': tuple((stock(code), (10 - index) * 10**8) for index, code in enumerate(('2101', '2102', '2103', '2104'))),
    'gC': tuple((stock(code), (10 - index) * 10**8) for index, code in enumerate(('3101', '3102', '3103', '3104'))),
    'gD': tuple((stock(code), (10 - index) * 10**8) for index, code in enumerate(('4101', '4102', '4103', '4104'))),
}
STATS = (stat('gA', 3), stat('gB', 2), stat('gC', 1), stat('gD', 0.5))


class Marks:
    def __init__(self):
        self.rows = {}

    def alert_marks(self, trade_date, kind):
        return {key[2:]: minute for key, minute in self.rows.items() if key[:2] == (trade_date, kind)}

    def mark_alert(self, trade_date, kind, group_id, direction, minute):
        self.rows[(trade_date, kind, group_id, direction)] = minute


def monitor(capacity=40, taken=0, params=None, marks=None):
    subscriptions = Subscriptions(capacity, taken)
    names = lambda group_id: group_id.upper()  # noqa: E731
    members = lambda group_id: MEMBERS.get(group_id, ())  # noqa: E731
    extra = () if marks is None else (marks,)
    value = SectorMonitor(members, subscriptions, lambda: params or SectorAlertParams(), names, *extra)
    return value, subscriptions


NETS = {0: 2, 1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 15, 7: 12, 8: 11, 9: 20, 10: -20, 11: -20, 12: -20, 13: 15}


def minute_ticks(index, net_million, start=None):
    net = net_million * MILLION
    big = (abs(net) // 2) // MILLION * MILLION
    side = 'BUY' if net > 0 else 'SELL'
    base = (start or START) + timedelta(minutes=index, seconds=30)
    codes = ('1101', '1102', '1103', '1104')
    amounts = [MILLION] * (big // MILLION) + [MILLION // 2] * ((abs(net) - big) // (MILLION // 2))
    return tuple(tick(codes[position % 4], amount, side, base) for position, amount in enumerate(amounts))


def replay(params=None, stats=STATS, minutes=15, capacity=40, start=None, marks=None):
    start = start or START
    value, subscriptions = monitor(capacity, params=params, marks=marks)
    alerts = []
    for step in range(minutes * 6 + 1):
        now = start + timedelta(seconds=10 * step)
        minute = step // 6
        if step % 6 == 3 and minute in NETS:
            value.on_ticks(minute_ticks(minute, NETS[minute], start))
        alerts.extend(value.on_round(now, stats))
    return value, subscriptions, alerts


class MonitorTests(unittest.TestCase):
    def test_replay_trigger_times_match_the_golden_file(self):
        _, _, alerts = replay()
        observed = [[alert.at.astimezone(TAIPEI).strftime('%H:%M'), alert.group_id, alert.direction] for alert in alerts]
        self.assertEqual(observed, json.loads(GOLDEN.read_text(encoding='utf-8'))['alerts'])

    def test_alert_numbers_and_cooldown_warmup(self):
        _, _, alerts = replay()
        up, down = alerts
        self.assertEqual((up.kind, up.amount, up.detail, up.baseline, up.members, up.monitored), ('FLOW', 38 * MILLION, 18 * MILLION, 3, 4, 4))
        self.assertEqual((down.amount, down.detail), (60 * MILLION, 30 * MILLION))
        # 09:19 would repeat the UP streak but sits inside the 10 minute cooldown.
        self.assertNotIn('09:19', [alert.at.astimezone(TAIPEI).strftime('%H:%M') for alert in alerts])

    def test_flow_cooldown_survives_a_restart_through_the_stored_marks(self):
        marks = Marks()
        _, _, first = replay(marks=marks)
        self.assertEqual(len(first), 2)
        self.assertEqual({key[1:] for key in marks.rows}, {('FLOW', 'gA', 'UP'), ('FLOW', 'gA', 'DOWN')})
        _, _, restarted = replay(marks=marks)  # a fresh monitor on the same day and the same ticks
        self.assertEqual(restarted, [])
        _, _, next_day = replay(marks=marks, start=START + timedelta(days=1))
        self.assertEqual(len(next_day), 2)

    def test_opening_warmup_also_applies_to_flow(self):
        _, _, alerts = replay(start=at(9, 0))
        # the 09:08 UP streak is inside the opening warm-up; the 09:12 DOWN streak is not
        self.assertEqual([(alert.at.astimezone(TAIPEI).strftime('%H:%M'), alert.direction) for alert in alerts], [('09:12', 'DOWN')])

    def test_warmup_blocks_alerts_in_the_first_five_monitored_minutes(self):
        value, _ = monitor()
        early = []
        for step in range(5 * 6):
            now = at(9, 10) + timedelta(seconds=10 * step)
            if step % 6 == 3:
                value.on_ticks((tick('1101', 15 * MILLION, 'BUY', now),))
            early.extend(value.on_round(now, STATS))
        self.assertEqual(early, [])

    def test_disabled_and_parameters(self):
        _, _, none = replay(SectorAlertParams(flow_enabled=False))
        self.assertEqual(none, [])
        _, _, strict = replay(SectorAlertParams(flow_floor=30 * MILLION))
        self.assertEqual(strict, [])
        _, _, quick = replay(SectorAlertParams(flow_minutes=2, cooldown_minutes=1))
        self.assertTrue(quick)

    def test_none_side_and_unmonitored_stocks_are_ignored(self):
        value, _ = monitor()
        value.on_round(at(9, 0), STATS)
        value.on_ticks((tick('1101', 5 * MILLION, 'NONE', at(9, 0, 5)), tick('9999', 5 * MILLION, 'BUY', at(9, 0, 5))))
        self.assertIsNone(value.side_ratio('1101'))
        self.assertIsNone(value.side_ratio('9999'))

    def test_side_ratio_is_buy_share_of_decided_amount(self):
        value, _ = monitor()
        value.on_round(at(9, 0), STATS)
        value.on_ticks((tick('1101', 3 * MILLION, 'BUY', at(9, 0, 5)), tick('1101', MILLION, 'SELL', at(9, 0, 6))))
        self.assertEqual(value.side_ratio('1101'), Decimal('0.75'))

    def test_only_the_top_three_groups_are_subscribed_and_counts_reported(self):
        value, subscriptions = monitor()
        value.on_round(at(9, 0), STATS)
        groups, counts = value.info()
        self.assertEqual(groups, ('gA', 'gB', 'gC'))
        self.assertEqual(counts, (('gA', 4, 4), ('gB', 4, 4), ('gC', 4, 4)))
        self.assertEqual(len(subscriptions.subscribed), 12)
        self.assertFalse(any(code.startswith('TWSE:4') for code in subscriptions.subscribed))

    def test_reselecting_the_same_groups_causes_no_subscription_churn(self):
        value, subscriptions = monitor()
        value.on_round(at(9, 0), STATS)
        before = len(subscriptions.calls)
        for minute in range(1, 8):
            flipped = (stat('gB', 3), stat('gA', 2.9), stat('gC', 1), stat('gD', 0.5)) if minute % 2 else STATS
            value.on_round(at(9, minute), flipped)
        self.assertEqual(len(subscriptions.calls), before)

    def test_budget_degrades_to_part_of_each_group_biggest_turnover_first(self):
        value, subscriptions = monitor(capacity=6)
        value.on_round(at(9, 0), STATS)
        groups, counts = value.info()
        self.assertEqual(counts, (('gA', 4, 4), ('gB', 2, 4), ('gC', 0, 4)))
        self.assertIn('TWSE:2101', subscriptions.subscribed)
        self.assertNotIn('TWSE:2104', subscriptions.subscribed)
        self.assertEqual(len(subscriptions.subscribed), 6)

    def test_monitor_budget_parameter_caps_subscriptions(self):
        value, subscriptions = monitor(params=SectorAlertParams(monitor_budget=5))
        value.on_round(at(9, 0), STATS)
        self.assertEqual(len(subscriptions.subscribed), 5)

    def test_slots_already_used_by_others_shrink_the_monitor_budget(self):
        value, subscriptions = monitor(capacity=14, taken=10)
        value.on_round(at(9, 0), STATS)
        self.assertEqual(len(subscriptions.subscribed), 14)
        self.assertEqual(sum(count for _, count, _ in value.info()[1]), 4)

    def test_release_one_only_gives_back_monitor_owned_subscriptions(self):
        value, subscriptions = monitor(capacity=6, taken=2)
        value.on_round(at(9, 0), STATS)
        owned = {code for code in subscriptions.subscribed if code.startswith('TWSE:')}
        self.assertEqual(len(owned), 4)
        for _ in range(4):
            self.assertTrue(value.release_one())
        self.assertFalse(value.release_one())
        self.assertEqual(subscriptions.subscribed, {'T0', 'T1'})

    def test_claim_transfers_ownership_so_it_is_never_dropped_by_the_monitor(self):
        value, subscriptions = monitor(capacity=40)
        value.on_round(at(9, 0), STATS)
        value.claim('TWSE:1101')
        value.on_round(at(9, 7), (stat('gD', 9), stat('gE', 8, valid=5), stat('gF', 7, valid=5)))
        self.assertIn('TWSE:1101', subscriptions.subscribed)
        self.assertNotIn('TWSE:1102', subscriptions.subscribed)

    def test_group_pushed_out_is_kept_five_minutes_then_unsubscribed(self):
        value, subscriptions = monitor(capacity=40)
        value.on_round(at(9, 0), STATS)
        pushed = (stat('gA', 3), stat('gB', 2), stat('gD', 1.5), stat('gC', 1))
        value.on_round(at(9, 1), pushed)
        self.assertEqual(value.info()[0], ('gA', 'gB', 'gD', 'gC'))
        value.on_round(at(9, 7), pushed)
        self.assertEqual(value.info()[0], ('gA', 'gB', 'gD'))
        self.assertFalse(any(code.startswith('TWSE:3') for code in subscriptions.subscribed))

    def test_disconnect_forgets_everything(self):
        value, _ = monitor()
        value.on_round(at(9, 0), STATS)
        value.on_ticks((tick('1101', MILLION, 'BUY', at(9, 0, 5)),))
        value.disconnected()
        self.assertEqual(value.info(), ((), ()))
        self.assertIsNone(value.side_ratio('1101'))


class QaRegressionTests(unittest.TestCase):
    def test_rank_flips_under_a_tight_budget_cause_no_resubscription(self):
        value, subscriptions = monitor(capacity=6)
        value.on_round(at(9, 10), STATS)
        base = len(subscriptions.calls)
        for minute in range(11, 19):
            flipped = (stat('gB', 3), stat('gA', 2.9), stat('gC', 1), stat('gD', 0.5)) if minute % 2 else STATS
            value.on_round(at(9, minute), flipped)
        self.assertEqual(len(subscriptions.calls), base)

    def test_a_turnover_reorder_at_the_cutoff_does_not_swap_held_stocks(self):
        groups = (('g', (('1', 9), ('2', 8), ('3', 7))),)
        first = allocate(groups, 2)
        flipped = (('g', (('1', 9), ('2', 5), ('3', 7))),)
        self.assertEqual(allocate(flipped, 2).codes, ('1', '3'))
        self.assertEqual(allocate(flipped, 2, held=first.codes).codes, first.codes)

    def test_held_codes_outside_the_groups_are_not_kept(self):
        self.assertEqual(allocate((('g', (('1', 1),)),), 5, held=('zzz', '1')).codes, ('1',))

    def test_large_order_net_keeps_its_sign_relative_to_the_flow(self):
        minutes = tuple(FlowMinute(at(9, 20) + timedelta(minutes=index), 22 * MILLION, -5 * MILLION) for index in range(3))
        direction, net, big, count = judge_flow(minutes, SectorAlertParams())
        self.assertEqual((direction, net, big, count), ('UP', 66 * MILLION, -15 * MILLION, 3))
        down = tuple(FlowMinute(at(9, 20) + timedelta(minutes=index), -22 * MILLION, 5 * MILLION) for index in range(3))
        self.assertEqual(judge_flow(down, SectorAlertParams())[2], -15 * MILLION)

    def test_release_updates_the_reported_counts_at_once(self):
        value, subscriptions = monitor(capacity=40)
        value.on_round(at(9, 10), STATS)
        self.assertEqual(value.info()[1][0], ('gA', 4, 4))
        value.release_one()
        counts = dict((gid, monitored) for gid, monitored, _ in value.info()[1])
        self.assertEqual(sum(counts.values()), 11)

    def test_off_session_round_subscribes_nothing(self):
        value, subscriptions = monitor()
        value.on_round(DAY.replace(hour=15, minute=0), STATS)
        self.assertEqual((subscriptions.calls, value.info()[0]), ([], ()))

    def test_budget_exhaustion_still_counts_stocks_the_terminal_already_holds(self):
        value, subscriptions = monitor(capacity=3)
        subscriptions.subscribed.add('TWSE:1104')  # the terminal holds the smallest turnover stock of gA
        value.on_round(at(9, 10), STATS)
        self.assertIn('TWSE:1104', subscriptions.subscribed)
        counts = dict((gid, monitored) for gid, monitored, _ in value.info()[1])
        self.assertEqual(counts['gA'], 3)

    def test_a_new_trading_day_starts_clean(self):
        value, _ = monitor()
        for step in range(8 * 6):
            now = at(9, 10) + timedelta(seconds=10 * step)
            value.on_round(now, STATS)
        self.assertTrue(value._since)
        value.on_round(at(9, 10) + timedelta(days=1), STATS)
        self.assertEqual(value._since, {'gA': at(9, 10) + timedelta(days=1), 'gB': at(9, 10) + timedelta(days=1), 'gC': at(9, 10) + timedelta(days=1)})
        self.assertTrue(all(len(history) == 0 for history in value._history.values()))

    def test_flow_alert_wording_matches_the_log_and_renders_on_the_board(self):
        from PySide6.QtWidgets import QApplication

        from desktop_app.components.charts import CandlestickChart
        from desktop_app.features.trading.sector_board import SectorBoardWidget, alert_text
        from quantlab.trading.application.sector_contracts import SectorBoardView
        from quantlab.trading.domain.sector_alerts import SectorAlert

        QApplication.instance() or QApplication([])
        alert = SectorAlert(at(10, 15), 'gA', '散熱', 'FLOW', 'UP', 120_000_000, 3, None, 70_000_000, 7, 7)
        self.assertEqual(alert_text(alert), '10:15 散熱 主動買連續 3 分鐘 淨買 1.2 億（大單淨買 0.7 億，監控 7/7 檔）')
        sell = SectorAlert(at(10, 15), 'gA', '散熱', 'FLOW', 'DOWN', 120_000_000, 3, None, -20_000_000, 7, 5)
        self.assertIn('主動賣連續 3 分鐘 淨賣 1.2 億（大單淨賣 -0.2 億，監控 5/7 檔）', alert_text(sell))
        widget = release(self, SectorBoardWidget(SimpleNamespace(), CandlestickChart()))
        widget.render_board(SectorBoardView('LIVE', at(10, 15), 1, 10, 50, (stat('gA', 3),), alerts=(alert,)))
        self.assertIn('主動買連續', widget.alert_bar.text())


class BridgeTests(unittest.TestCase):
    def make(self, capacity):
        from quantlab.trading.runtime.market_terminal import SessionBridge

        subscriptions = Subscriptions(capacity)
        session = SimpleNamespace(
            connected=True,
            subscribe=subscriptions.subscribe,
            subscribe_bidask=subscriptions.subscribe,
            unsubscribe=subscriptions.unsubscribe,
            drain_ticks=lambda limit: self.pending,
        )
        bridge = SessionBridge(SimpleNamespace(session=session))
        value = SectorMonitor(lambda group_id: MEMBERS.get(group_id, ()), subscriptions, SectorAlertParams, lambda group_id: group_id)
        bridge.monitor = value
        self.pending = ()
        return bridge, value, subscriptions

    def test_terminal_subscription_takes_a_slot_from_the_monitor_when_full(self):
        bridge, value, subscriptions = self.make(capacity=4)
        value.on_round(at(9, 0), STATS)
        self.assertEqual(len(subscriptions.subscribed), 4)
        bridge.subscribe(stock('9001'))
        self.assertIn('TWSE:9001', subscriptions.subscribed)
        self.assertEqual(len(subscriptions.subscribed), 4)

    def test_without_a_monitor_slot_to_give_the_limit_error_surfaces(self):
        bridge, value, subscriptions = self.make(capacity=1)
        subscriptions.subscribed.add('TWSE:8000')
        with self.assertRaises(DomainError):
            bridge.subscribe(stock('9001'))

    def test_every_drained_tick_is_offered_to_the_monitor_and_still_returned(self):
        bridge, value, subscriptions = self.make(capacity=40)
        value.on_round(at(9, 0), STATS)
        ticks = (tick('1101', 3 * MILLION, 'BUY', at(9, 0, 5)),)
        self.pending = ticks
        self.assertEqual(bridge.drain_ticks(10), ticks)
        self.assertEqual(value.side_ratio('1101'), Decimal(1))

    def test_terminal_taking_over_a_monitored_stock_is_not_resubscribed_or_released(self):
        bridge, value, subscriptions = self.make(capacity=40)
        value.on_round(at(9, 0), STATS)
        calls = len(subscriptions.calls)
        bridge.subscribe(stock('1101'))
        self.assertEqual(len(subscriptions.calls), calls + 1)  # session dedupes; the monitor no longer owns it
        while value.release_one():
            pass
        self.assertIn('TWSE:1101', subscriptions.subscribed)


class BoardDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_rank_shows_the_monitor_mark_and_members_show_count_and_side_ratio(self):
        from desktop_app.components.charts import CandlestickChart
        from desktop_app.features.trading.sector_board import SectorBoardWidget
        from quantlab.trading.application.sector_contracts import MemberView, MonitorCount, SectorBoardView

        widget = release(self, SectorBoardWidget(SimpleNamespace(), CandlestickChart()))
        groups = (stat('gA', 3), stat('gB', 2))
        members = (
            MemberView('TWSE:1101', '1101', 'N1101', Decimal(100), Decimal('1.5'), Decimal('1.2'), 10**8, '', side_ratio=Decimal('0.57')),
            MemberView('TWSE:1102', '1102', 'N1102', Decimal(90), Decimal('0.5'), None, 10**7, ''),
        )
        view = SectorBoardView('LIVE', at(9, 30), 1, 10, 50, groups, 'gA', members, monitored=('gA',), monitor_counts=(MonitorCount('gA', 2, 4),))
        widget.render_board(view)
        names = {widget.rank.item(row, 0).data(0x100): widget.rank.item(row, 0).text() for row in range(widget.rank.rowCount())}
        self.assertTrue(names['gA'].startswith('● '))
        self.assertFalse(names['gB'].startswith('●'))
        self.assertIn('監控 2/4 檔', widget.members_title.text())
        self.assertIn('額度不足', widget.members_title.text())
        sides = [widget.members.item(row, 6).text() for row in range(widget.members.rowCount())]
        self.assertEqual(sorted(sides), ['57%', '—'])


if __name__ == '__main__':
    unittest.main()

"""M5-4: sector alert parameters, minute roll-up, burst alert (A), cooldown, warm-up, replay golden file."""

from datetime import date, datetime, timedelta, timezone

from PySide6.QtCore import Qt
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from quantlab.trading.adapters.storage.sector_minute_store import RETAIN_DAYS, SectorMinuteStore
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.sector_minutes import MinuteAggregator
from quantlab.trading.domain.sector import SectorStat
from quantlab.trading.domain.sector_alerts import (
    MinuteStat,
    SectorAlert,
    SectorAlertParams,
    in_alert_window,
    judge_burst,
    minute_direction,
)
from quantlab.trading.domain.validation import DomainError

from tests.test_m5_sector import release

import quantlab.trading.runtime.protocol  # noqa: F401  (registers wire types)

TAIPEI = timezone(timedelta(hours=8))
DAY = datetime(2026, 11, 9, tzinfo=TAIPEI)
GOLDEN = Path(__file__).parent / 'fixtures' / 'm5_sector_replay_golden.json'
NAMES = {'g1': 'G1', 'g2': 'G2', 'g3': 'G3'}


class ParamTests(unittest.TestCase):
    def test_defaults_match_the_spec_table(self):
        params = SectorAlertParams()
        self.assertEqual(
            (params.snapshot_seconds, params.burst_multiple, params.burst_floor, params.baseline_minutes, params.direction_pct, params.warmup_minutes),
            (10, Decimal(3), 20_000_000, 30, Decimal('0.3'), 10),
        )
        self.assertEqual((params.flow_minutes, params.flow_floor, params.flow_multiple, params.big_order), (3, 10_000_000, Decimal(2), 1_000_000))
        self.assertEqual((params.monitor_groups, params.monitor_keep_minutes, params.monitor_budget, params.cooldown_minutes), (3, 5, 45, 10))

    def test_ranges_are_enforced_at_the_boundary(self):
        for name, value in (
            ('snapshot_seconds', 4),
            ('snapshot_seconds', 31),
            ('burst_multiple', Decimal('1.4')),
            ('baseline_minutes', 9),
            ('cooldown_minutes', 0),
            ('flow_minutes', 11),
            ('big_order', 99_999),
            ('direction_pct', Decimal(3)),
            ('burst_enabled', 1),
        ):
            with self.assertRaises(DomainError, msg=name):
                SectorAlertParams(**{name: value})
        SectorAlertParams(snapshot_seconds=5, burst_multiple=Decimal('1.5'), cooldown_minutes=60)

    def test_dict_roundtrip_ignores_unknown_keys_and_rejects_bad_values(self):
        params = SectorAlertParams(burst_multiple=Decimal('4.5'), flow_enabled=False)
        self.assertEqual(SectorAlertParams.from_dict(json.loads(json.dumps(params.as_dict()))), params)
        self.assertEqual(SectorAlertParams.from_dict({'future_field': 1}), SectorAlertParams())
        with self.assertRaises(DomainError):
            SectorAlertParams.from_dict({'cooldown_minutes': 999})

    def test_wire_roundtrip(self):
        params = SectorAlertParams(burst_multiple=Decimal('4.5'))
        self.assertEqual(loads(dumps(params)), params)
        alert = SectorAlert(DAY.replace(hour=9, minute=40), 'g1', 'G1', 'BURST', 'UP', 450, 100, Decimal('4.5'))
        self.assertEqual(loads(dumps(alert)), alert)

    def test_burst_judgement_needs_multiple_floor_and_a_positive_baseline(self):
        params = SectorAlertParams()
        history = (100_000_000,) * 30
        self.assertEqual(judge_burst(300_000_000, history, params), (True, 100_000_000))
        self.assertEqual(judge_burst(299_999_999, history, params), (False, 100_000_000))
        self.assertEqual(judge_burst(15_000_000, (5_000_000,) * 30, params)[0], False)  # 3x but below the floor
        self.assertEqual(judge_burst(60_000_000, (20_000_000,) * 30, params)[0], True)
        self.assertEqual(judge_burst(100_000_000, (0,) * 30, params), (False, 0))
        self.assertEqual(judge_burst(100_000_000, (), params), (False, 0))
        short = SectorAlertParams(baseline_minutes=10)
        self.assertEqual(judge_burst(500, (10_000_000,) * 25 + (50,) * 10, short), (False, 50))

    def test_direction_threshold_is_exclusive_and_in_percent(self):
        self.assertEqual(minute_direction(31, Decimal('0.3')), 'UP')
        self.assertEqual(minute_direction(30, Decimal('0.3')), 'NEUTRAL')
        self.assertEqual(minute_direction(-31, Decimal('0.3')), 'DOWN')
        self.assertEqual(minute_direction(-30, Decimal('0.3')), 'NEUTRAL')

    def test_alert_window_is_0900_to_1325_after_warmup(self):
        params = SectorAlertParams()
        for hour, minute, expected in ((8, 59, False), (9, 0, False), (9, 9, False), (9, 10, True), (13, 25, True), (13, 26, False)):
            self.assertEqual(in_alert_window(DAY.replace(hour=hour, minute=minute), TAIPEI, params), expected, (hour, minute))
        self.assertTrue(in_alert_window(DAY.replace(hour=9, minute=0), TAIPEI, SectorAlertParams(warmup_minutes=0)))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.store = SectorMinuteStore((Path(self.temp.name) / 'market' / 'sector_minutes.sqlite3').resolve())
        self.addCleanup(self.store.close)

    def stat(self, minute, group='g1', amount=5, complete=True):
        return MinuteStat(minute.astimezone(timezone.utc), group, amount, amount * 10, 250, 123, 6000, 1, 0, 7, complete)

    def test_roundtrip_replace_and_incomplete_flag(self):
        moment = DAY.replace(hour=10, minute=12)
        self.store.append((self.stat(moment), self.stat(moment, 'g2', complete=False)), date(2026, 11, 9))
        self.store.append((self.stat(moment, amount=9),), date(2026, 11, 9))
        rows = {item.group_id: item for item in self.store.load_day(date(2026, 11, 9))}
        self.assertEqual((rows['g1'].amount, rows['g1'].minute, rows['g1'].complete), (9, moment.astimezone(timezone.utc), True))
        self.assertFalse(rows['g2'].complete)
        self.assertEqual(self.store.load_day(date(2026, 11, 10)), ())

    def test_share_baseline_averages_the_same_time_of_the_last_five_stored_days(self):
        def share(day, hhmm, group, bps):
            minute = datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[3:]), tzinfo=TAIPEI)
            return MinuteStat(minute.astimezone(timezone.utc), group, 1, 10, bps, 0, 0, 0, 0, 5, True)

        today = date(2026, 11, 16)
        days = [today - timedelta(days=offset) for offset in (1, 2, 3, 4, 5, 6, 7)]
        for index, day in enumerate(days):
            # the last minute at or before 10:00 counts; later minutes of the same day must not
            self.store.append((share(day, '09:58', 'g1', 100 * (index + 1)), share(day, '10:30', 'g1', 9999)), day)
        self.store.append((share(days[0], '09:00', 'g2', 400), share(days[0], '09:01', 'g2', 0)), days[0])
        self.store.append((share(today, '09:30', 'g1', 7777),), today)
        found = self.store.share_baseline(today, '10:00')
        self.assertEqual(found['g1'], (300, 5))  # 100..500 from the five latest earlier days; today and 10:30 ignored
        self.assertEqual(found['g2'], (400, 1))  # a zero share (no value) is not a data point
        self.assertEqual(self.store.share_baseline(today, '08:30'), {})
        self.assertEqual(self.store.share_baseline(days[-1], '10:00'), {})

    def test_history_lists_days_minutes_and_one_minute_and_reports_store_failure(self):
        from quantlab.trading.application.sector_contracts import HistoryRow, SectorHistoryQuery
        from quantlab.trading.application.sector_minutes import sector_history

        early, late = DAY.replace(hour=9, minute=1), DAY.replace(hour=9, minute=2)
        self.store.append((self.stat(early), self.stat(early, 'g2', complete=False), self.stat(late, amount=8)), DAY.date())
        self.store.append((self.stat(early + timedelta(days=1)),), DAY.date() + timedelta(days=1))
        names = {'g1': 'G1', 'g2': 'G2'}.get
        self.assertEqual(sector_history(self.store, SectorHistoryQuery(), names).days, ('2026-11-10', '2026-11-09'))
        last = sector_history(self.store, SectorHistoryQuery('2026-11-09'), names)
        self.assertEqual((last.minutes, last.minute, [row.group_id for row in last.rows]), (('09:01', '09:02'), '09:02', ['g1']))
        first = sector_history(self.store, SectorHistoryQuery('2026-11-09', '09:01'), names)
        self.assertEqual(first.rows, (HistoryRow('g1', 'G1', 123, 250, 6000, 1, 5, 7, True), HistoryRow('g2', 'G2', 123, 250, 6000, 1, 5, 7, False)))
        unknown = sector_history(self.store, SectorHistoryQuery('2026-11-09', '13:30'), names)
        self.assertEqual(unknown.minute, '09:02')  # a minute that was never stored falls back to the last one
        empty = sector_history(self.store, SectorHistoryQuery('2026-10-01'), names)
        self.assertEqual((empty.minutes, empty.minute, empty.rows, empty.failed), ((), '', (), False))
        self.store.close()
        self.assertTrue(sector_history(self.store, SectorHistoryQuery(), names).failed)

    def test_history_queries_reject_malformed_dates_and_minutes(self):
        from quantlab.trading.application.sector_contracts import SectorHistoryQuery

        for bad in (('2026-13-01', ''), ('2026-11-09', '9:01'), ('', '09:01'), ('2026-11-09', '24:00')):
            with self.subTest(bad=bad), self.assertRaises(DomainError):
                SectorHistoryQuery(*bad)

    def test_purge_keeps_30_days(self):
        old, keep = date(2026, 11, 9) - timedelta(days=RETAIN_DAYS + 1), date(2026, 11, 9) - timedelta(days=RETAIN_DAYS)
        for day in (old, keep):
            self.store.append((self.stat(datetime(day.year, day.month, day.day, 10, 0, tzinfo=TAIPEI)),), day)
        self.assertEqual(self.store.purge(date(2026, 11, 9)), 1)
        self.assertEqual((len(self.store.load_day(old)), len(self.store.load_day(keep))), (0, 1))

    def test_relative_path_and_foreign_schema_are_refused(self):
        with self.assertRaises(DomainError):
            SectorMinuteStore(Path('relative.sqlite3'))
        import sqlite3

        path = (Path(self.temp.name) / 'foreign.sqlite3').resolve()
        db = sqlite3.connect(path)
        db.execute('CREATE TABLE sector_minutes (a INTEGER)')
        db.commit()
        db.close()
        recovered = SectorMinuteStore(path)
        self.addCleanup(recovered.close)
        self.assertEqual(recovered.warning, 'sector_minutes_corrupt')
        self.assertEqual(len(list(path.parent.glob('foreign.sqlite3.bad-*'))), 1)
        self.assertEqual(recovered.load_day(date(2026, 11, 9)), ())

    def test_a_file_that_is_not_a_database_is_set_aside_and_never_blocks_startup(self):
        path = (Path(self.temp.name) / 'garbage.sqlite3').resolve()
        path.write_bytes(b'this is not sqlite' * 100)
        store = SectorMinuteStore(path)
        self.addCleanup(store.close)
        self.assertEqual(store.warning, 'sector_minutes_corrupt')
        self.assertEqual(len(list(path.parent.glob('garbage.sqlite3.bad-*'))), 1)
        store.append((self.stat(DAY.replace(hour=10)),), date(2026, 11, 9))
        self.assertEqual(len(store.load_day(date(2026, 11, 9))), 1)

    def test_minutes_are_stored_in_taipei_time(self):
        moment = DAY.replace(hour=9, minute=5)
        self.store.append((self.stat(moment),), date(2026, 11, 9))
        row = self.store._db.execute('SELECT trade_date, minute FROM sector_minutes').fetchone()
        self.assertEqual(row, ('2026-11-09', '09:05'))
        self.assertEqual(self.store.load_day(date(2026, 11, 9))[0].minute, moment.astimezone(timezone.utc))


def stat(group, cumulative, pct_bps, valid=7):
    return SectorStat(group, NAMES[group], 'CONCEPT', Decimal(pct_bps) / 100, 5, valid, 7, 0, 0, int(cumulative), Decimal('0.1'))


def scenario():
    """Deterministic day: per-minute NT$ and pct jumps (bps) by group, minute index 0 = 09:00."""
    amounts = {'g1': {i: 100_000_000 for i in range(-5, 70)}, 'g2': {i: 20_000_000 for i in range(-5, 70)}, 'g3': {i: 5_000_000 for i in range(-5, 70)}}
    jumps = {'g1': {}, 'g2': {}, 'g3': {}}
    for index in range(-5, 0):
        for group in amounts:
            amounts[group][index] = 0
    amounts['g1'].update({5: 500_000_000, 21: 500_000_000, 40: 450_000_000, 45: 500_000_000, 48: 500_000_000, 55: 600_000_000})
    jumps['g1'].update({40: 60, 48: 40, 55: 50})
    amounts['g2'].update({12: 40_000_000, 30: 80_000_000})
    jumps['g2'].update({30: 10})
    amounts['g3'].update({5: 300_000_000, 35: 15_000_000})
    return amounts, jumps


def rounds(skip_minute=None):
    """Yield (time, stats) every 10 s from 08:55 to 10:00; the last round of each minute is at +50 s."""
    amounts, jumps = scenario()
    start = DAY.replace(hour=8, minute=55)
    for step in range(65 * 6 + 1):
        moment = start + timedelta(seconds=10 * step)
        index = (moment.hour * 60 + moment.minute) - 9 * 60
        second = moment.second
        fraction = Decimal(second + 10) / 60
        if index == skip_minute:
            continue
        stats = []
        for group in amounts:
            base = sum(amounts[group][i] for i in range(-5, index))
            moved = sum(jumps[group].get(i, 0) for i in range(-5, index))
            cum = base + int(amounts[group][index] * fraction)
            bps = moved + int(jumps[group].get(index, 0) * fraction)
            stats.append(stat(group, cum, bps))
        yield moment, tuple(stats)


def replay(params=None, skip_minute=20):
    temp = TemporaryDirectory(dir=Path.cwd())
    store = SectorMinuteStore((Path(temp.name) / 'sector_minutes.sqlite3').resolve())
    aggregator = MinuteAggregator(store, lambda: params or SectorAlertParams(), NAMES.get)
    alerts = []
    for moment, stats in rounds(skip_minute):
        alerts.extend(aggregator.on_round(moment, stats))
    return aggregator, store, temp, alerts


class ReplayTests(unittest.TestCase):
    def test_replay_trigger_times_match_the_golden_file(self):
        aggregator, store, temp, alerts = replay()
        self.addCleanup(temp.cleanup)
        self.addCleanup(store.close)
        observed = [[alert.at.astimezone(TAIPEI).strftime('%H:%M'), alert.group_id, alert.direction] for alert in alerts]
        golden = json.loads(GOLDEN.read_text(encoding='utf-8'))
        self.assertEqual(observed, golden['alerts'])

    def test_warmup_cooldown_floor_and_gap_each_suppress_exactly_what_they_should(self):
        aggregator, store, temp, alerts = replay()
        self.addCleanup(temp.cleanup)
        self.addCleanup(store.close)
        seen = {(alert.at.astimezone(TAIPEI).strftime('%H:%M'), alert.group_id, alert.direction) for alert in alerts}
        self.assertNotIn(('09:05', 'g1', 'NEUTRAL'), seen)  # opening warm-up
        self.assertNotIn(('09:05', 'g3', 'NEUTRAL'), seen)
        self.assertNotIn(('09:48', 'g1', 'UP'), seen)  # same direction inside the 10 minute cooldown
        self.assertIn(('09:55', 'g1', 'UP'), seen)  # cooldown over
        self.assertIn(('09:45', 'g1', 'NEUTRAL'), seen)  # another direction is a separate cooldown
        self.assertFalse(any(group == 'g3' for _, group, _ in seen))  # 3x but below the NT$20M floor
        self.assertNotIn(('09:21', 'g1', 'NEUTRAL'), seen)  # minute after a missed round is incomplete

    def test_missed_minute_is_stored_incomplete_with_zero_amount_and_skipped_for_baseline(self):
        aggregator, store, temp, alerts = replay()
        self.addCleanup(temp.cleanup)
        self.addCleanup(store.close)
        rows = {(item.minute.astimezone(TAIPEI).strftime('%H:%M'), item.group_id): item for item in store.load_day(date(2026, 11, 9))}
        self.assertFalse(rows[('09:21', 'g1')].complete)
        self.assertEqual(rows[('09:21', 'g1')].amount, 0)
        self.assertTrue(rows[('09:19', 'g1')].complete)
        self.assertEqual(rows[('09:19', 'g1')].amount, 100_000_000)
        self.assertEqual(rows[('09:40', 'g1')].amount, 450_000_000)
        self.assertEqual(rows[('09:40', 'g1')].equal_pct_bps, 60)
        self.assertNotIn(0, [value for value in aggregator._history['g1']][-30:])

    def test_disabled_burst_and_stricter_parameters_change_the_outcome(self):
        _, store, temp, alerts = replay(SectorAlertParams(burst_enabled=False))
        self.addCleanup(temp.cleanup)
        self.addCleanup(store.close)
        self.assertEqual(alerts, [])
        _, store2, temp2, strict = replay(SectorAlertParams(burst_multiple=Decimal('4.5')))
        self.addCleanup(temp2.cleanup)
        self.addCleanup(store2.close)
        self.assertEqual([(alert.at.astimezone(TAIPEI).strftime('%H:%M'), alert.group_id) for alert in strict], [('09:40', 'g1')])

    def test_restart_keeps_the_cooldown_of_alerts_already_sent_today(self):
        aggregator, store, temp, alerts = replay()
        self.addCleanup(temp.cleanup)
        self.addCleanup(store.close)
        self.assertTrue(aggregator._last_alert)
        fresh = MinuteAggregator(store, SectorAlertParams, NAMES.get)
        fresh.on_round(DAY.replace(hour=10, minute=1), (stat('g1', 10**10, 0), stat('g2', 10**9, 0), stat('g3', 10**8, 0)))
        self.assertEqual(fresh._last_alert, aggregator._last_alert)
        tomorrow = MinuteAggregator(store, SectorAlertParams, NAMES.get)
        tomorrow.on_round(DAY.replace(hour=10, minute=1) + timedelta(days=1), (stat('g1', 10**10, 0),))
        self.assertEqual(tomorrow._last_alert, {})

    def test_each_finished_minute_refreshes_the_share_baseline_and_a_new_day_clears_it(self):
        aggregator, store, temp, alerts = replay()
        self.addCleanup(temp.cleanup)
        self.addCleanup(store.close)
        self.assertEqual(aggregator.baselines, ())  # the replay day is the only stored day
        tomorrow = MinuteAggregator(store, SectorAlertParams, NAMES.get)
        start = DAY.replace(hour=9, minute=40) + timedelta(days=1)
        for seconds in (0, 50, 60):
            tomorrow.on_round(start + timedelta(seconds=seconds), (stat('g1', 10**10, 0), stat('g2', 10**9, 0)))
        by_group = {item.group_id: item for item in tomorrow.baselines}
        self.assertEqual(set(by_group), {'g1', 'g2', 'g3'})  # every group stored at 09:40 of the replay day
        stored = {item.group_id: item.share_bps for item in store.load_day(DAY.date()) if item.minute.astimezone(TAIPEI).strftime('%H:%M') == '09:40'}
        self.assertEqual({group: by_group[group].share_bps for group in by_group}, {group: stored[group] for group in by_group})
        self.assertTrue(all(item.days == 1 for item in tomorrow.baselines))
        later = tomorrow.on_round(start + timedelta(days=1), (stat('g1', 10**10, 0),))
        self.assertEqual((later, tomorrow.baselines), ((), ()))

    def test_restart_inside_a_cooldown_does_not_repeat_the_alert(self):
        temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temp.cleanup)
        path = (Path(temp.name) / 'sector_minutes.sqlite3').resolve()
        store = SectorMinuteStore(path)
        aggregator = MinuteAggregator(store, SectorAlertParams, NAMES.get)
        alerts, restarted = [], False
        for moment, stats in rounds(20):
            if not restarted and moment.astimezone(TAIPEI).strftime('%H:%M') == '09:44':
                store.close()  # 09:40 g1 UP is inside its 10 minute cooldown here
                store = SectorMinuteStore(path)
                aggregator = MinuteAggregator(store, SectorAlertParams, NAMES.get)
                restarted = True
            alerts.extend(aggregator.on_round(moment, stats))
        store.close()
        observed = [[alert.at.astimezone(TAIPEI).strftime('%H:%M'), alert.group_id, alert.direction] for alert in alerts]
        self.assertEqual(observed, json.loads(GOLDEN.read_text(encoding='utf-8'))['alerts'])

    def test_restart_midday_reloads_history_so_baseline_survives(self):
        aggregator, store, temp, alerts = replay()
        self.addCleanup(temp.cleanup)
        self.addCleanup(store.close)
        fresh = MinuteAggregator(store, SectorAlertParams, NAMES.get)
        stats = (stat('g1', 10**10, 0), stat('g2', 10**9, 0), stat('g3', 10**8, 0))
        fresh.on_round(DAY.replace(hour=10, minute=1, second=0), stats)
        self.assertGreater(len(fresh._history['g1']), 30)
        self.assertEqual(fresh._previous, {})  # cumulative base is unknown after a restart: next minute is incomplete

    def test_alert_carries_numbers_for_the_log_text(self):
        _, store, temp, alerts = replay()
        self.addCleanup(temp.cleanup)
        self.addCleanup(store.close)
        first = alerts[1]
        self.assertEqual((first.group_id, first.amount, first.baseline, first.kind), ('g1', 450_000_000, 100_000_000, 'BURST'))
        self.assertEqual(first.ratio, Decimal('4.5'))
        self.assertEqual(first.group_name, 'G1')
        self.assertEqual(first.members, 7)


class MinuteRobustnessTests(unittest.TestCase):
    def feed(self, aggregator, minute_count, per_minute, valid_at=lambda minute: 7):
        alerts = []
        base = DAY.replace(hour=9, minute=10)
        for index in range(minute_count):
            cumulative = per_minute(index)
            for second in (0, 30):
                moment = base + timedelta(minutes=index, seconds=second)
                alerts.extend(aggregator.on_round(moment, (stat('g1', cumulative, 0, valid_at(index)), stat('g2', 0, 0), stat('g3', 0, 0))))
        return alerts

    def make(self):
        temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temp.cleanup)
        store = SectorMinuteStore((Path(temp.name) / 'm.sqlite3').resolve())
        self.addCleanup(store.close)
        return MinuteAggregator(store, SectorAlertParams, NAMES.get), store

    def test_a_changed_member_count_makes_that_minute_incomplete_instead_of_a_false_burst(self):
        aggregator, store = self.make()
        # steady 100M per minute, then a member with 2B cumulative turnover rejoins the group at minute 20
        alerts = self.feed(aggregator, 40, lambda index: 100_000_000 * index + (2_000_000_000 if index >= 20 else 0), lambda index: 8 if index >= 20 else 7)
        self.assertEqual(alerts, [])
        rows = {item.minute.astimezone(TAIPEI).strftime('%H:%M'): item for item in store.load_day(date(2026, 11, 9)) if item.group_id == 'g1'}
        self.assertFalse(rows['09:30'].complete)
        self.assertTrue(rows['09:31'].complete)
        self.assertEqual(rows['09:31'].amount, 100_000_000)

    def test_pre_open_minutes_do_not_dilute_the_baseline(self):
        aggregator, store = self.make()
        early = DAY.replace(hour=8, minute=56)
        for index in range(4):
            for second in (0, 30):
                aggregator.on_round(early + timedelta(minutes=index, seconds=second), (stat('g1', 0, 0), stat('g2', 0, 0), stat('g3', 0, 0)))
        self.assertEqual(list(aggregator._history.get('g1', ())), [])

    def test_cooldown_marks_are_kept_per_day_and_kind_and_dropped_the_next_day(self):
        aggregator, store = self.make()
        minute = DAY.replace(hour=9, minute=40)
        store.mark_alert(minute.date(), 'BURST', 'g1', 'UP', minute)
        store.mark_alert(minute.date(), 'BURST', 'g1', 'UP', minute + timedelta(minutes=15))
        self.assertEqual(store.alert_marks(minute.date(), 'BURST'), {('g1', 'UP'): minute + timedelta(minutes=15)})
        self.assertEqual(store.alert_marks(minute.date(), 'FLOW'), {})
        store.purge(minute.date() + timedelta(days=1))
        self.assertEqual(store.alert_marks(minute.date(), 'BURST'), {})

    def test_a_file_written_before_marks_existed_gains_the_table_and_keeps_its_minutes(self):
        aggregator, store = self.make()
        store.append((MinuteStat(DAY.replace(hour=9, minute=1), 'g1', 5, 5, 0, 0, 0, 0, 0, 3, True),), DAY.date())
        store._db.execute('DROP TABLE sector_alert_marks')
        store._db.commit()
        path = store.path
        store.close()
        reopened = SectorMinuteStore(path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.warning, '')
        self.assertEqual(len(reopened.load_day(DAY.date())), 1)
        self.assertEqual(reopened.alert_marks(DAY.date(), 'BURST'), {})


class LogIntegrationTests(unittest.TestCase):
    def make(self, folder):
        from threading import RLock

        from quantlab.trading.adapters.storage.alert_store import JsonAlertStore
        from quantlab.trading.application.alert_service import AlertService
        from quantlab.trading.runtime.market_alerts import RuntimeAlerts

        runtime = RuntimeAlerts.__new__(RuntimeAlerts)
        runtime.lock = RLock()
        runtime.service = AlertService(JsonAlertStore(Path(folder)), now=DAY.replace(hour=10))
        return runtime

    def burst(self, direction='UP'):
        return SectorAlert(DAY.replace(hour=9, minute=40), 'builtin.cooling', '散熱', 'BURST', direction, 450_000_000, 100_000_000, Decimal('4.5'), members=7)

    def test_sector_alert_enters_the_same_log_and_survives_a_reload(self):
        from quantlab.trading.adapters.storage.alert_store import JsonAlertStore
        from quantlab.trading.domain.alerts import AlertKind

        with TemporaryDirectory(dir=Path.cwd()) as folder:
            runtime = self.make(folder)
            runtime.record_sector(self.burst())
            (event,) = runtime.service.events
            self.assertEqual((event.kind, event.instrument_id, event.rule_id), (AlertKind.SECTOR_BURST, 'SECTOR:builtin.cooling', 'sector.burst'))
            self.assertEqual(event.message_args, ('09:40', '散熱', 'UP', '4.5', '1.0', '4.5'))
            self.assertEqual(event.occurred_at, DAY.replace(hour=9, minute=41).astimezone(timezone.utc))
            (loaded,) = JsonAlertStore(Path(folder)).load_events(DAY.replace(hour=10))
            self.assertEqual(loaded, event)

    def test_log_wording_matches_the_spec_example_and_colours_by_direction(self):
        from desktop_app.features.trading.alert_panel import event_direction, event_text

        with TemporaryDirectory(dir=Path.cwd()) as folder:
            runtime = self.make(folder)
            runtime.record_sector(self.burst())
            runtime.record_sector(self.burst('NEUTRAL'))
            up, neutral = runtime.service.events
            self.assertEqual(event_text(up), '09:40 散熱 爆量上攻 本分鐘 4.5 億（基準 1.0 億，4.5 倍）')
            self.assertEqual(event_text(neutral), '09:40 散熱 爆量 本分鐘 4.5 億（基準 1.0 億，4.5 倍）')
            self.assertEqual((event_direction(up), event_direction(neutral)), ('UP', 'NEUTRAL'))

    def test_panel_shows_group_name_and_click_selects_the_group_not_an_instrument(self):
        from PySide6.QtWidgets import QApplication

        from desktop_app.features.trading.alert_panel import AlertPanel
        from quantlab.trading.application.alert_contracts import AlertActions  # noqa: F401

        QApplication.instance() or QApplication([])
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            runtime = self.make(folder)
            runtime.record_sector(self.burst())
            chosen, groups = [], []
            panel = release(self, AlertPanel(runtime.service, lambda: 'TWSE:2330', lambda key, at: chosen.append(key)))
            panel.select_sector = groups.append
            self.assertEqual([panel.table.item(0, column).text() for column in (1, 2, 3)], ['散熱', '族群', '族群爆量'])
            panel.select_event(panel.table.item(0, 0))
            self.assertEqual((chosen, groups), ([], ['builtin.cooling']))

    def test_a_rule_for_a_sector_kind_is_a_validation_error(self):
        from quantlab.trading.domain.alerts import AlertKind, AlertRule

        for kind in (AlertKind.SECTOR_BURST, AlertKind.SECTOR_FLOW):
            with self.assertRaises(DomainError):
                AlertRule('r', kind, 'MARKET')

    def test_sector_kinds_cannot_be_added_as_rules(self):
        from PySide6.QtWidgets import QApplication

        from desktop_app.features.trading.alert_panel import AlertRuleDialog

        QApplication.instance() or QApplication([])
        dialog = release(self, AlertRuleDialog('TWSE:2330'))
        kinds = {getattr(dialog.kind.itemData(index), 'value', dialog.kind.itemData(index)) for index in range(dialog.kind.count())}
        self.assertNotIn('SECTOR_BURST', kinds)
        self.assertNotIn('SECTOR_FLOW', kinds)
        self.assertIn('PRICE_CROSS', kinds)


class SettingsTests(unittest.TestCase):
    def test_save_load_keeps_other_sections_and_bad_values_fall_back(self):
        from quantlab.research_core.adapters.settings_store import SettingsStore
        from quantlab.trading.runtime.sector_settings import SectorAlertSettings

        with TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / 'settings.json'
            SettingsStore(path).save({'other': {'keep': 1}})
            settings = SectorAlertSettings(path)
            self.assertEqual(settings.get(), SectorAlertParams())
            saved = settings.save(SectorAlertParams(burst_multiple=Decimal('4.5'), cooldown_minutes=20))
            body = SettingsStore(path).load()
            self.assertEqual(body['other'], {'keep': 1})
            self.assertEqual(SectorAlertSettings(path).get(), saved)
            body['sector_alerts_v1']['cooldown_minutes'] = 999
            SettingsStore(path).save(body)
            self.assertEqual(SectorAlertSettings(path).get(), SectorAlertParams())

    def test_dialog_collects_scaled_values_and_reports_engine_refusal(self):
        from types import SimpleNamespace

        from PySide6.QtWidgets import QApplication

        from desktop_app.features.trading.sector_settings_dialog import SectorAlertSettingsDialog

        QApplication.instance() or QApplication([])
        sent = []

        def submit(operation, completed):
            try:
                completed(operation(), None)
            except DomainError as error:
                completed(None, error)

        def settings(params=None):
            sent.append(params)
            if params is None or params.cooldown_minutes > 60:
                raise DomainError('validation_failed', 'range')
            return params

        dialog = release(self, SectorAlertSettingsDialog(SimpleNamespace(sector_settings=settings), SectorAlertParams(), submit))
        widget = dialog.inputs['burst_floor'][0]
        self.assertEqual(widget.value(), 2000)  # NT$20M shown in 10,000s
        widget.setValue(3000)
        dialog.inputs['burst_multiple'][0].setValue(4.5)
        dialog.burst.setChecked(False)
        params = dialog.collect()
        self.assertEqual((params.burst_floor, params.burst_multiple, params.burst_enabled), (30_000_000, Decimal('4.5'), False))
        dialog.save()
        self.assertEqual(sent[-1], params)
        self.assertEqual(dialog.params, params)


class BoardAlertBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def view(self, alerts):
        from quantlab.trading.application.sector_contracts import SectorBoardView

        groups = (
            SectorStat('g1', 'G1', 'CONCEPT', Decimal('2.0'), 3, 4, 4, 0, 0, 5 * 10**8, Decimal('0.1')),
            SectorStat('g2', 'G2', 'CONCEPT', Decimal('1.0'), 2, 4, 4, 0, 0, 5 * 10**8, Decimal('0.1')),
        )
        return SectorBoardView('LIVE', DAY.replace(hour=9, minute=41), 1, 10, 100, groups, alerts=alerts)

    def widget(self):
        from types import SimpleNamespace

        from desktop_app.components.charts import CandlestickChart
        from desktop_app.features.trading.sector_board import SectorBoardWidget

        widget = release(self, SectorBoardWidget(SimpleNamespace(sector_board=lambda query: self.view(())), CandlestickChart()))
        widget._submit = lambda operation, completed: None
        return widget

    def alert(self, group='g1'):
        return SectorAlert(DAY.replace(hour=9, minute=40), group, group.upper(), 'BURST', 'UP', 450_000_000, 100_000_000, Decimal('4.5'), members=4)

    def test_bar_shows_latest_expands_and_click_selects_the_group(self):
        widget = self.widget()
        widget.render_board(self.view(()))
        self.assertIn('尚無族群警訊', widget.alert_bar.text())
        widget.render_board(self.view((self.alert('g2'), self.alert('g1'))))
        self.assertEqual(widget.alert_bar.text(), '09:40 G2 爆量上攻 本分鐘 4.5 億（基準 1.0 億，4.5 倍）')
        self.assertEqual(widget.alert_list.count(), 2)
        self.assertFalse(widget.alert_list.isVisibleTo(widget))
        widget.toggle_alerts()
        self.assertTrue(widget.alert_list.isVisibleTo(widget))
        widget.select_group = lambda group_id: widget.__dict__.setdefault('picked', []).append(group_id)
        widget.alert_list.itemClicked.emit(widget.alert_list.item(1))
        self.assertEqual(widget.picked, ['g1'])

    def test_alerted_row_flashes_then_keeps_a_light_tint_until_the_next_round(self):
        widget = self.widget()
        widget.render_board(self.view(()))
        later = self.view((self.alert('g1'),))
        widget.render_board(later)
        row = next(index for index in range(widget.rank.rowCount()) if widget.rank.item(index, 0).data(Qt.ItemDataRole.UserRole) == 'g1')
        other = 1 - row
        strong = widget.rank.item(row, 0).background().color().name()
        self.assertNotEqual(strong, widget.rank.item(other, 0).background().color().name())
        flashed = widget._flash['g1']
        widget._flash['g1'] = (flashed[0], flashed[1] - 5, flashed[2])
        widget.render_board(later)
        light = widget.rank.item(row, 0).background().color().name()
        self.assertNotEqual(light, strong)
        newer = self.view((self.alert('g1'),))
        newer = SectorBoardView_with_data_at(newer, DAY.replace(hour=9, minute=42))
        widget.render_board(newer)
        self.assertNotIn('g1', widget._flash)

    def test_alerts_that_predate_the_window_do_not_flash_and_the_newest_tint_wins(self):
        widget = self.widget()
        first = self.view((self.alert('g1'),))
        widget.render_board(first)
        self.assertEqual(widget._flash, {})
        older = SectorAlert(DAY.replace(hour=9, minute=38), 'g2', 'G2', 'BURST', 'DOWN', 450_000_000, 100_000_000, Decimal('4.5'), members=4)
        newer = SectorAlert(DAY.replace(hour=9, minute=39), 'g2', 'G2', 'BURST', 'UP', 450_000_000, 100_000_000, Decimal('4.5'), members=4)
        widget.render_board(self.view((newer, older, self.alert('g1'))))
        self.assertEqual(widget._flash['g2'][0], 'UP')
        self.assertNotIn('g1', widget._flash)

    def test_clicking_an_alert_for_a_group_hidden_by_the_filter_shows_it(self):
        widget = self.widget()
        widget.render_board(self.view(()))
        widget.set_filter('INDUSTRY')
        self.assertEqual(widget.rank.rowCount(), 0)
        widget._submit = lambda operation, completed: None
        widget.select_group('g2')
        self.assertEqual(widget.filter, 'all')
        self.assertEqual(widget.rank.rowCount(), 2)

    def test_settings_button_opens_the_dialog_with_engine_values(self):
        widget = self.widget()
        calls = []
        widget._submit = lambda operation, completed: calls.append(operation)
        widget.open_settings()
        self.assertEqual(len(calls), 1)


def SectorBoardView_with_data_at(view, data_at):
    from dataclasses import replace

    return replace(view, data_at=data_at)


if __name__ == '__main__':
    unittest.main()

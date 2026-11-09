"""M5-2: sector statistics, snapshot normalisation, directory v2, the sector service and the board tab."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest

from PySide6.QtCore import Qt

from quantlab.trading.adapters.shioaji.snapshot_poller import BATCH, ShioajiSnapshotSource, normalise_snapshot
from quantlab.trading.adapters.shioaji.symbol_directory import SymbolDirectory
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.sector_contracts import MemberView, SectorBoardView, SectorQuery
from quantlab.trading.application.sector_service import STALE_SECONDS, SectorService, in_session, industry_groups
from quantlab.trading.domain.concept_groups import BUILTIN_GROUPS
from quantlab.trading.domain.industry_names import industry_name
from quantlab.trading.domain.sector import QuoteRow, SectorGroup, compute_stats, eligible_stock, sort_stats
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import WatchInstrument, WatchKind

import quantlab.trading.runtime.protocol  # noqa: F401  (registers wire types)

TAIPEI = timezone(timedelta(hours=8))
OPEN = datetime(2026, 11, 9, 10, 0, tzinfo=TAIPEI)  # a Monday, in session
CLOSED = datetime(2026, 11, 9, 15, 0, tzinfo=TAIPEI)
WEEKEND = datetime(2026, 11, 14, 10, 0, tzinfo=TAIPEI)


def row(code, pct, amount=100_000_000, limit='', price='100', ratio='1.5', at=OPEN):
    return QuoteRow(code, Decimal(price), Decimal(pct), limit, 1000, amount, Decimal(ratio) if ratio is not None else None, at)


def stock(code, category='24', exchange='TSE'):
    prefix = 'TWSE' if exchange == 'TSE' else 'TPEX'
    return WatchInstrument(f'{prefix}:{code}', WatchKind.STOCK, exchange, code, 'N' + code, category)


class DomainTests(unittest.TestCase):
    def test_equal_weight_breadth_limits_amount_share_and_valid_counts_match_hand_calculation(self):
        rows = {
            '2330': row('2330', '2.00', 300, 'UP'),
            '2454': row('2454', '-1.00', 100),
            '3034': row('3034', '0.00', 100),
            '2317': row('2317', '5.00', 500),  # outside the group, still market turnover
        }
        group = SectorGroup('g', 'G', 'CONCEPT', ('2330', '2454', '3034', '9999'))
        (stat,) = compute_stats((group,), rows)
        self.assertEqual(stat.equal_pct, Decimal('1.00') / 3)
        self.assertEqual((stat.up_count, stat.valid_count, stat.listed_count), (1, 3, 4))
        self.assertEqual((stat.limit_up, stat.limit_down), (1, 0))
        self.assertEqual(stat.amount, 500)
        self.assertEqual(stat.share, Decimal(500) / Decimal(1000))
        self.assertEqual(stat.breadth, Decimal(1) / 3)
        self.assertTrue(stat.few_members)

    def test_empty_group_has_no_percent_and_sorts_last_either_direction(self):
        rows = {'1101': row('1101', '1.0'), '1102': row('1102', '3.0')}
        groups = (SectorGroup('a', 'A', 'CONCEPT', ('1101',)), SectorGroup('b', 'B', 'CONCEPT', ('9998',)), SectorGroup('c', 'C', 'INDUSTRY', ('1102',)))
        stats = compute_stats(groups, rows)
        self.assertIsNone(stats[1].equal_pct)
        self.assertEqual([item.group_id for item in sort_stats(stats)], ['c', 'a', 'b'])
        self.assertEqual([item.group_id for item in sort_stats(stats, descending=False)], ['a', 'c', 'b'])
        with self.assertRaises(DomainError):
            sort_stats(stats, 'nope')

    def test_duplicate_codes_in_a_group_count_once_and_stock_filter_excludes_etf_and_preferred(self):
        rows = {'2330': row('2330', '1.0')}
        (stat,) = compute_stats((SectorGroup('g', 'G', 'CONCEPT', ('2330', '2330')),), rows)
        self.assertEqual((stat.valid_count, stat.listed_count), (1, 1))
        self.assertTrue(eligible_stock('2330'))
        for code in ('0050', '006208', '2882A', '030001', ''):
            self.assertFalse(eligible_stock(code))

    def test_builtin_groups_match_the_spec_appendix(self):
        self.assertEqual(len(BUILTIN_GROUPS), 17)
        self.assertEqual(len({group.id for group in BUILTIN_GROUPS}), 17)
        self.assertEqual(len(next(group for group in BUILTIN_GROUPS if group.id == 'builtin.cooling').codes), 7)
        for group in BUILTIN_GROUPS:
            self.assertTrue(group.codes and all(eligible_stock(code) for code in group.codes), group.id)
            self.assertEqual(len(set(group.codes)), len(group.codes), group.id)
        self.assertIn('2330', next(group for group in BUILTIN_GROUPS if group.id == 'builtin.adv_packaging').codes)

    def test_industry_names_and_unknown_codes(self):
        self.assertEqual(industry_name('24'), '半導體')
        self.assertEqual(industry_name('99'), '產業 99')

    def test_quote_row_rejects_non_positive_price_and_bad_limit(self):
        with self.assertRaises(DomainError):
            row('2330', '1', price='0')
        with self.assertRaises(DomainError):
            row('2330', '1', limit='SIDEWAYS')


def raw_snapshot(code='2330', close=100, rate=1.5, change_type='Up', volume_ratio=1.2, ts=None, amount=123456789, volume=2000):
    stamp = ts or int(datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    return SimpleNamespace(
        code=code,
        close=close,
        change_rate=rate,
        change_type=change_type,
        volume_ratio=volume_ratio,
        ts=stamp,
        total_amount=amount,
        total_volume=volume,
    )


class SnapshotTests(unittest.TestCase):
    def test_normalises_limit_states_ratio_and_time(self):
        up = normalise_snapshot(raw_snapshot(change_type=SimpleNamespace(value='LimitUp')))
        self.assertEqual((up.limit, up.price, up.change_pct, up.volume_ratio), ('UP', Decimal('100'), Decimal('1.5'), Decimal('1.2')))
        self.assertEqual(up.at, datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc))
        self.assertEqual(normalise_snapshot(raw_snapshot(change_type='LimitDown')).limit, 'DOWN')
        self.assertEqual(normalise_snapshot(raw_snapshot(change_type='Unchanged')).limit, '')

    def test_rows_without_a_price_are_dropped_and_negative_ratio_is_unknown(self):
        self.assertIsNone(normalise_snapshot(raw_snapshot(close=0)))
        self.assertIsNone(normalise_snapshot(raw_snapshot(volume_ratio=-1)).volume_ratio)
        self.assertIsNone(normalise_snapshot(raw_snapshot(volume_ratio=None)).volume_ratio)

    def test_one_malformed_row_does_not_discard_the_round(self):
        class Facade:
            def market_contract(self, code):
                return SimpleNamespace(code=code)

            def snapshots(self, contracts):
                rows = [raw_snapshot(contract.code) for contract in contracts]
                rows[0].total_amount = None
                return rows

        source = ShioajiSnapshotSource(SimpleNamespace(connected=True, facade=Facade()))
        self.assertEqual(len(source.snapshots((stock('2330'), stock('2454'), stock('3034')))), 2)
        with self.assertRaises(DomainError):
            source.snapshots((stock('2330'),))

    def test_source_batches_at_500_resolves_contracts_once_and_cleans_vendor_errors(self):
        calls, lookups = [], []

        class Facade:
            def market_contract(self, code):
                lookups.append(code)
                return SimpleNamespace(code=code)

            def snapshots(self, contracts):
                calls.append(len(contracts))
                return [raw_snapshot(contract.code) for contract in contracts]

        session = SimpleNamespace(connected=True, facade=Facade())
        source = ShioajiSnapshotSource(session)
        items = tuple(stock(f'{1000 + index}') for index in range(BATCH + 50))
        self.assertEqual(len(source.snapshots(items)), BATCH + 50)
        self.assertEqual(calls, [BATCH, 50])
        source.snapshots(items)
        self.assertEqual(len(lookups), BATCH + 50)

        def boom(contracts):
            raise RuntimeError('SECRET vendor text')

        session.facade.snapshots = boom
        with self.assertRaises(DomainError) as caught:
            source.snapshots(items[:1])
        self.assertNotIn('SECRET', str(caught.exception))
        session.connected = False
        with self.assertRaises(DomainError):
            source.snapshots(items[:1])


class DirectoryTests(unittest.TestCase):
    def facade(self):
        stocks = [SimpleNamespace(code='2330', exchange='TSE', category='24'), SimpleNamespace(code='6104', exchange='OTC', category='')]
        return SimpleNamespace(
            market_contracts=lambda kind: stocks if kind == 'STK' else [],
            market_contract_info=lambda base: SimpleNamespace(name='Name ' + base.code),
        )

    def test_refresh_stores_category_and_a_version_1_cache_is_refetched(self):
        now = datetime(2026, 11, 9, 0, tzinfo=timezone.utc)
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / 'symbol_directory.json'
            directory = SymbolDirectory(path)
            items = {item.code: item for item in directory.refresh(self.facade(), now)}
            self.assertEqual(items['2330'].category, '24')
            self.assertEqual(items['6104'].category, '')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['version'], 2)
            self.assertEqual({item.code: item.category for item in SymbolDirectory(path).items}['2330'], '24')
            old = json.loads(path.read_text(encoding='utf-8'))
            old['version'] = 1
            old['items'] = [item[:5] for item in old['items']]
            path.write_text(json.dumps(old), encoding='utf-8')
            reloaded = SymbolDirectory(path)
            self.assertIsNone(reloaded.fetched_at)
            self.assertEqual({item.code: item.category for item in reloaded.refresh(self.facade(), now)}['2330'], '24')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['version'], 2)


class Source:
    def __init__(self, rows):
        self.rows, self.connected, self.fail, self.calls = rows, True, False, 0

    def snapshots(self, instruments):
        self.calls += 1
        if self.fail:
            raise DomainError('market_data_snapshot_failed')
        return tuple(self.rows)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = OPEN
        self.stocks = (stock('2330'), stock('2454', '24'), stock('3034', '24'), stock('1101', '01'), stock('2317', '13'))
        self.rows = [
            row('2330', '3.00', 400, 'UP', at=OPEN),
            row('2454', '1.00', 300),
            row('3034', '-2.00', 200),
            row('1101', '0.50', 100),
            row('2317', '2.00', 100),
        ]
        self.source = Source(self.rows)
        self.service = SectorService(lambda: self.stocks, self.source, lambda: self.now)

    def test_industry_groups_come_from_directory_categories(self):
        groups = {group.id: group for group in industry_groups(self.stocks)}
        self.assertEqual(groups['industry.24'].name, '半導體')
        self.assertEqual(groups['industry.24'].codes, ('2330', '2454', '3034'))
        self.assertEqual(groups['industry.01'].name, '水泥工業')

    def test_live_board_ranks_by_equal_weight_and_lists_members_with_leader(self):
        self.service.refresh()
        view = self.service.board('industry.24')
        self.assertEqual(view.state, 'LIVE')
        stat = next(item for item in view.groups if item.group_id == 'industry.24')
        self.assertEqual(stat.equal_pct, Decimal('2.00') / 3)
        self.assertEqual(
            [item.equal_pct for item in view.groups if item.equal_pct is not None],
            sorted((item.equal_pct for item in view.groups if item.equal_pct is not None), reverse=True),
        )
        self.assertEqual([member.code for member in view.members], ['2330', '2454', '3034'])
        self.assertTrue(view.members[0].is_leader)
        self.assertEqual(view.members[0].leader_at, OPEN)
        self.assertEqual(view.members[0].instrument_id, 'TWSE:2330')
        self.assertEqual(view.stock_count, 5)
        self.assertEqual(view.data_at, OPEN)

    def test_leader_is_the_earliest_limit_up_and_resets_when_it_opens(self):
        self.service.refresh()
        later = OPEN + timedelta(minutes=5)
        self.rows[1] = row('2454', '9.90', 300, 'UP', at=later)
        self.now = later
        self.service.refresh()
        members = {member.code: member for member in self.service.board('industry.24').members}
        self.assertTrue(members['2330'].is_leader)
        self.assertFalse(members['2454'].is_leader)
        self.assertEqual(members['2454'].leader_at, later)
        self.rows[0] = row('2330', '8.00', 400, '', at=later)
        self.service.refresh()
        members = {member.code: member for member in self.service.board('industry.24').members}
        self.assertTrue(members['2454'].is_leader)
        self.assertIsNone(members['2330'].leader_at)

    def test_state_machine_offline_empty_live_stale_closed(self):
        self.source.connected = False
        self.assertEqual(self.service.board().state, 'OFFLINE')
        self.source.connected = True
        self.assertEqual(self.service.board().state, 'EMPTY')
        self.service.refresh()
        self.assertEqual(self.service.board().state, 'LIVE')
        self.now = OPEN + timedelta(seconds=STALE_SECONDS + 15)
        stale = self.service.board()
        self.assertEqual((stale.state, stale.age_seconds), ('STALE', STALE_SECONDS + 15))
        self.now = CLOSED
        self.assertEqual(self.service.board().state, 'CLOSED')
        self.assertTrue(self.service.board().groups)
        self.source.connected = False
        offline = self.service.board()
        self.assertEqual((offline.state, offline.groups, offline.members), ('OFFLINE', (), ()))

    def test_disconnect_drops_data_so_old_numbers_are_never_shown_as_live(self):
        self.service.refresh()
        self.service.disconnected()
        self.assertEqual(self.service.board().state, 'EMPTY')
        self.assertEqual(self.service.board().groups, ())

    def test_failed_round_keeps_data_marks_failure_and_is_due_again(self):
        self.service.refresh()
        self.source.fail = True
        self.now = OPEN + timedelta(seconds=40)
        self.service.refresh()
        self.assertEqual(self.service.board().state, 'STALE')
        self.assertTrue(self.service.due())

    def test_polling_is_due_only_connected_and_in_session_after_the_first_round(self):
        self.assertTrue(self.service.due())
        self.service.refresh()
        self.assertTrue(self.service.due())
        self.now = CLOSED
        self.assertFalse(self.service.due())
        self.now = WEEKEND
        self.assertFalse(self.service.due())
        self.source.connected = False
        self.now = OPEN
        self.assertFalse(self.service.due())

    def test_after_hours_with_nothing_loaded_still_takes_one_round(self):
        self.now = CLOSED
        self.assertTrue(self.service.due())
        self.service.refresh()
        self.assertEqual(self.service.board().state, 'CLOSED')
        self.assertFalse(self.service.due())

    def test_session_window_is_0855_to_1335_on_weekdays(self):
        for hour, minute, expected in ((8, 54, False), (8, 55, True), (13, 35, True), (13, 36, False)):
            self.assertEqual(in_session(datetime(2026, 11, 9, hour, minute, tzinfo=TAIPEI)), expected)
        self.assertFalse(in_session(WEEKEND))

    def test_leader_ignores_a_round_of_old_rows_and_a_future_outlier(self):
        old = OPEN - timedelta(days=3)
        self.rows[0] = row('2330', '9.90', 400, 'UP', at=old)
        self.service.refresh()
        self.assertTrue(all(member.leader_at is None for member in self.service.board('industry.24').members))
        self.rows[0] = row('2330', '9.90', 400, 'UP', at=OPEN)
        self.rows[1] = row('2454', '1.00', 300, '', at=OPEN + timedelta(days=1))
        self.service.refresh()
        members = {member.code: member for member in self.service.board('industry.24').members}
        self.assertEqual(members['2330'].leader_at, OPEN)

    def test_unknown_group_selection_is_ignored(self):
        self.service.refresh()
        view = self.service.board('does-not-exist')
        self.assertEqual((view.selected_group_id, view.members), ('', ()))

    def test_concept_group_with_missing_codes_counts_valid_over_listed(self):
        self.service.refresh()
        view = self.service.board()
        stat = next(item for item in view.groups if item.group_id == 'builtin.container_shipping')
        self.assertEqual((stat.valid_count, stat.listed_count, stat.equal_pct), (0, 3, None))
        ai = next(item for item in view.groups if item.group_id == 'builtin.ai_server')
        self.assertEqual((ai.valid_count, ai.listed_count), (1, 9))

    def test_round_finishing_after_a_disconnect_cannot_repopulate_the_board(self):
        class Slow(Source):
            def snapshots(inner, instruments):
                self.service.disconnected()
                return super().snapshots(instruments)

        self.service.source = Slow(self.rows)
        self.service.refresh()
        self.assertEqual(self.service.board().state, 'EMPTY')

    def test_a_row_from_another_day_never_sets_the_leader_time(self):
        yesterday = OPEN - timedelta(days=1)
        self.rows[0] = row('2330', '9.90', 400, 'UP', at=yesterday)
        self.rows[1] = row('2454', '9.90', 300, 'UP', at=OPEN)
        self.service.refresh()
        members = {member.code: member for member in self.service.board('industry.24').members}
        self.assertIsNone(members['2330'].leader_at)
        self.assertTrue(members['2454'].is_leader)

    def test_failed_latest_round_is_visible_on_the_board(self):
        self.service.refresh()
        self.assertFalse(self.service.board().failed)
        self.source.fail = True
        self.service.refresh()
        self.assertTrue(self.service.board().failed)

    def test_wire_roundtrip_for_board_query_and_members(self):
        self.service.refresh()
        view = self.service.board('industry.24')
        self.assertEqual(loads(dumps(view)), view)
        self.assertEqual(loads(dumps(SectorQuery('industry.24'))), SectorQuery('industry.24'))
        self.assertEqual(loads(dumps(SectorBoardView())), SectorBoardView())
        member = view.members[0]
        self.assertIsInstance(member, MemberView)


class BoardWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def make(self):
        from desktop_app.components.charts import CandlestickChart
        from desktop_app.features.trading.sector_board import SectorBoardWidget

        service = SectorService(
            lambda: (stock('2330'), stock('2454'), stock('3034'), stock('1101', '01')),
            Source([row('2330', '3.00', 400, 'UP'), row('2454', '1.00', 300), row('3034', '-2.00', 200), row('1101', '0.50', 100)]),
            lambda: OPEN,
        )
        service.refresh()
        facade = SimpleNamespace(sector_board=lambda query: service.board(query.group_id))
        return SectorBoardWidget(facade, CandlestickChart()), service

    def test_ranking_renders_filters_sorts_and_selects_group_members(self):
        widget, service = self.make()
        widget.render_board(service.board())
        names = [widget.rank.item(row, 0).text() for row in range(widget.rank.rowCount())]
        self.assertTrue(any('半導體' in name for name in names))
        self.assertEqual(widget.rank.rowCount(), len(service.board().groups))
        widget.set_filter('CONCEPT')
        self.assertTrue(all(widget.rank.item(row, 1).text() == '概念' for row in range(widget.rank.rowCount())))
        widget.set_filter('INDUSTRY')
        self.assertTrue(all(widget.rank.item(row, 1).text() == '產業' for row in range(widget.rank.rowCount())))
        pcts = [widget.rank.item(row, 2).text() for row in range(widget.rank.rowCount())]
        self.assertEqual(pcts[0], '+0.67%')
        widget.group_id = 'industry.24'
        widget.render_board(service.board('industry.24'))
        self.assertEqual([widget.members.item(row, 0).text().lstrip('★') for row in range(widget.members.rowCount())], ['2330', '2454', '3034'])
        self.assertTrue(widget.members.item(0, 0).text().startswith('★'))
        self.assertIn('領頭羊', widget.members.item(0, 0).toolTip())
        self.assertFalse(widget.members_hint.isVisibleTo(widget))

    def test_status_text_for_offline_stale_and_closed_and_empty_tables(self):
        widget, service = self.make()
        widget.render_board(SectorBoardView('OFFLINE'))
        self.assertIn('行情未連線', widget.status.text())
        self.assertEqual(widget.rank.rowCount(), 0)
        widget.render_board(SectorBoardView('EMPTY'))
        self.assertIn('載入', widget.status.text())
        widget.render_board(SectorBoardView('CLOSED', OPEN, 5, 10, 1, service.board().groups))
        self.assertIn('非交易時段', widget.status.text())
        widget.render_board(SectorBoardView('STALE', OPEN, 45, 10, 1, service.board().groups))
        self.assertIn('資料延遲 45 秒', widget.status.text())

    def test_groups_without_a_value_sort_last_in_both_directions(self):
        widget, service = self.make()
        widget.render_board(service.board())
        column = 2
        for order in (Qt.SortOrder.DescendingOrder, Qt.SortOrder.AscendingOrder):
            widget.rank_sort = (column, order)
            widget.render_board(service.board())
            texts = [widget.rank.item(row, column).text() for row in range(widget.rank.rowCount())]
            known = [text for text in texts if text != '—']
            self.assertEqual(texts[: len(known)], known)
            self.assertTrue(all(text == '—' for text in texts[len(known) :]))
            values = [Decimal(text.rstrip('%')) for text in known]
            self.assertEqual(values, sorted(values, reverse=order == Qt.SortOrder.DescendingOrder))
        self.assertIn('—', texts)

    def test_failed_read_clears_the_tables_instead_of_keeping_old_numbers(self):
        widget, service = self.make()
        widget.render_board(service.board('industry.24'))
        self.assertGreater(widget.rank.rowCount(), 0)
        widget.render_failure()
        self.assertEqual((widget.rank.rowCount(), widget.members.rowCount()), (0, 0))
        self.assertIn('讀取失敗', widget.status.text())

    def test_the_latest_stock_click_during_a_selection_is_not_lost(self):
        widget, service = self.make()
        widget.render_board(service.board('industry.24'))
        chosen = []
        widget._submit = lambda operation, completed: chosen.append(completed)
        widget.select_stock('TWSE:2330')
        widget.select_stock('TWSE:2454')
        self.assertEqual(widget.stock_id, 'TWSE:2330')
        chosen.pop(0)(True, None)
        self.assertEqual(widget.stock_id, 'TWSE:2454')

    def test_failed_selection_can_be_retried_and_does_not_drop_the_queued_click(self):
        widget, service = self.make()
        widget.render_board(service.board('industry.24'))
        calls = []
        widget._submit = lambda operation, completed: calls.append(completed)
        widget.select_stock('TWSE:2330')
        widget.select_stock('TWSE:2454')
        calls.pop(0)(None, RuntimeError('x'))
        self.assertEqual(widget.stock_id, 'TWSE:2454')
        calls.pop(0)(None, RuntimeError('x'))
        self.assertEqual(widget.stock_id, '')
        widget.select_stock('TWSE:2454')
        self.assertEqual((widget.stock_id, len(calls)), ('TWSE:2454', 1))

    def test_stale_detail_fetch_does_not_block_the_next_stock(self):
        widget, service = self.make()
        widget.render_board(service.board('industry.24'))
        calls = []
        widget._submit = lambda operation, completed: calls.append((operation, completed))
        widget.stock_id = 'TWSE:2330'
        widget._refresh_detail()
        widget.stock_id = 'TWSE:2454'
        widget._refresh_detail()
        self.assertEqual(len(calls), 2)
        calls[0][1](None, RuntimeError('late'))
        self.assertEqual(widget._detail_loading, ('TWSE:2454', '1m'))

    def test_first_round_failure_is_visible_instead_of_loading_forever(self):
        widget, service = self.make()
        service.disconnected()
        service.source.fail = True
        service.refresh()
        view = service.board()
        self.assertEqual((view.state, view.failed), ('EMPTY', True))
        widget.render_board(view)
        self.assertIn('失敗', widget.status.text())

    def test_a_failed_selection_is_reported_not_left_blank(self):
        widget, service = self.make()
        widget.render_board(service.board('industry.24'))
        chosen = []
        widget._submit = lambda operation, completed: chosen.append(completed)
        widget.select_stock('TWSE:2330')
        chosen.pop(0)(None, RuntimeError('x'))
        self.assertIn('失敗', widget.detail_title.text())

    def test_amount_and_percent_formatting(self):
        from desktop_app.features.trading.sector_board import amount_text, percent_text

        self.assertEqual(amount_text(320_000_000), '3.2 億')
        self.assertEqual(percent_text(Decimal('1.234')), '+1.23%')
        self.assertEqual(percent_text(None), '—')


if __name__ == '__main__':
    unittest.main()

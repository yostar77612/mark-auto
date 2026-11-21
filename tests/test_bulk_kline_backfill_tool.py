"""The bulk K-line tool: its --existing mode (which stocks, how far back, no login when only listing) and that it never leaves the store open."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from quantlab.trading.domain.watch import WatchKind
from tools import bulk_kline_backfill as tool


def item(market, code, kind=WatchKind.STOCK):
    return SimpleNamespace(instrument_id=f'{market}:{code}', code=code, name=f'name{code}', kind=kind)


DIRECTORY = SimpleNamespace(
    items=(
        item('TPEX', '6111'),
        item('TWSE', '1101'),
        item('TWSE', '2002'),
        item('INDEX', 'IX0001', WatchKind.INDEX),
        item('TWSE', '2330'),
    )
)
EXTENT = (datetime(2025, 11, 21, 1, 0, tzinfo=timezone.utc), datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc), None)
HELD = {'TPEX:6111': EXTENT, 'TWSE:1101': EXTENT, 'INDEX:IX0001': EXTENT, 'TWSE:9999': EXTENT, 'TWSE:2330': EXTENT}


class FakeStore:
    opened = []

    def __init__(self, path):
        self.path = path
        self.closed = 0
        FakeStore.opened.append(self)

    def instrument_ids(self):
        return tuple(HELD) + ('TWSE:2002',)  # 2002 is listed but holds no minute bars

    def minute_extent(self, instrument_id):
        return HELD.get(instrument_id)

    def close(self):
        self.closed += 1


class ExistingSelectionTests(unittest.TestCase):
    def test_only_stocks_with_minute_bars_are_selected_in_code_order(self):
        stocks, unknown = tool.downloaded_stocks(FakeStore(None), DIRECTORY)
        self.assertEqual([stock.code for stock in stocks], ['1101', '2330', '6111'])  # no index, no stock without bars
        self.assertEqual(unknown, ['TWSE:9999'])  # held by the store but unknown to the symbol directory: never requested

    def test_a_store_without_any_minute_bars_selects_nothing(self):
        empty = SimpleNamespace(instrument_ids=lambda: ('TWSE:1101',), minute_extent=lambda instrument_id: None)
        self.assertEqual(tool.downloaded_stocks(empty, DIRECTORY), ([], []))


class ToolRunTests(unittest.TestCase):
    def setUp(self):
        FakeStore.opened = []
        self.session = mock.Mock()
        self.requests = []
        self.history_settings = []
        self.history_stores = []
        self.steps = 0  # how many run_next calls report finished work before the queue is empty

    def recorder(self):
        requests, history_settings, test = self.requests, self.history_settings, self

        class Recorder:
            def __init__(self, store, session, settings, autostart):
                history_settings.append((settings, autostart))
                test.history_stores.append(store)
                self.calls = 0

            def request(self, instrument, start, end, priority=0):
                requests.append((instrument.code, start, end, priority))

            def run_next(self):
                self.calls += 1
                return self.calls <= test.steps

            def next_retry_in(self):
                return None

            def state(self):
                return SimpleNamespace(paused=False, history_error=(), usage=None)

            def is_backfilling(self, instrument_id):
                return False

        return Recorder

    def patches(self, **override):
        replace = dict(
            markauto_running=mock.Mock(return_value=False),
            market_settings=mock.Mock(return_value=SimpleNamespace(environment=SimpleNamespace(value='BROKER_SIMULATION'))),
            SymbolDirectory=mock.Mock(return_value=DIRECTORY),
            KlineStore=FakeStore,
            create_market_session=mock.Mock(return_value=self.session),
            HistorySync=self.recorder(),
            stored_bars=mock.Mock(return_value=123),
        )
        replace.update(override)
        return [mock.patch.object(tool, name, value) for name, value in replace.items()]

    def run_main(self, *argv, **override):
        output = StringIO()
        patches = self.patches(**override)
        with redirect_stdout(output):
            for patch in patches:
                patch.start()
            try:
                code = tool.main(['--context', str(Path('context')), *argv])
            finally:
                for patch in patches:
                    patch.stop()
        return code, output.getvalue()

    def assert_every_store_closed_once(self):
        self.assertTrue(all(store.closed == 1 for store in FakeStore.opened), [store.closed for store in FakeStore.opened])

    def assert_one_store_opened_and_used_by_the_download(self):
        self.assertEqual(len(FakeStore.opened), 1)  # a download without a store would otherwise pass unnoticed: "no store opened" is also "every store closed"
        self.assertEqual(len(self.history_stores), 1)
        self.assertIs(self.history_stores[0], FakeStore.opened[0])

    def test_existing_mode_requests_every_selected_stock_back_to_the_given_days(self):
        code, output = self.run_main('--existing', '--days', '1095', '--max-bars-today', '100000000')
        self.assertEqual(code, 0)
        self.assertEqual([request[0] for request in self.requests], ['1101', '2330', '6111'])
        self.assertEqual([request[3] for request in self.requests], [1, 2, 3])  # code order is the queue order
        for _, start, end, _ in self.requests:
            self.assertEqual(end - start, timedelta(days=1095))
        self.assertEqual(len({request[2] for request in self.requests}), 1)  # one common end for every stock
        settings, autostart = self.history_settings[0]
        self.assertEqual((settings.daily_bar_limit, autostart), (100_000_000, False))
        self.session.connect.assert_called_once_with()
        self.session.disconnect.assert_called_once_with()
        self.assertIn('已有 1 分 K 的股票 3 檔，各補到近 1095 天：1101 2330 6111', output)
        self.assertIn('符號目錄查不到而略過的代號 1 個：TWSE:9999', output)
        self.assert_one_store_opened_and_used_by_the_download()
        self.assert_every_store_closed_once()

    def test_listing_with_rank_only_never_logs_in_and_requests_nothing(self):
        code, output = self.run_main('--existing', '--rank-only')
        self.assertEqual(code, 0)
        self.assertEqual(self.requests, [])
        self.session.connect.assert_not_called()
        self.assertIn('1101 2330 6111', output)
        self.assertEqual(len(FakeStore.opened), 1)
        self.assert_every_store_closed_once()  # even the listing opens the store, and an unclosed one forces a full check at the next app start

    def test_an_empty_selection_neither_logs_in_nor_downloads(self):
        with mock.patch.object(FakeStore, 'minute_extent', return_value=None):
            code, output = self.run_main('--existing')
        self.assertEqual(code, 0)
        self.assertEqual(self.requests, [])
        self.session.connect.assert_not_called()
        self.assertIn('沒有可以延伸的股票', output)
        self.assert_every_store_closed_once()

    def test_progress_lines_name_the_earliest_stored_day_when_extending(self):
        self.steps = 1
        _, output = self.run_main('--existing', '--days', '1095')
        self.assertIn('[  1/3] 1101 name1101: 最早 2025-11-21', output)
        self.assertIn('[  3/3] 6111 name6111: 最早 2025-11-21', output)

    def test_without_existing_the_ranking_path_is_unchanged(self):
        rows = [(DIRECTORY.items[0], 5e8), (DIRECTORY.items[1], 2e8)]
        self.steps = 1
        with mock.patch.object(tool, 'ranked', return_value=rows) as ranked:
            code, output = self.run_main('--top', '2', '--days', '365')
        self.assertEqual(code, 0)
        ranked.assert_called_once_with(self.session, DIRECTORY, 2)
        self.assertEqual([request[0] for request in self.requests], ['6111', '1101'])  # amount order, not code order
        self.assertIn('成交金額前 2 名', output)
        self.assertIn('[  1/2] 6111 name6111: 123 根', output)  # the ranking path still reports bar counts
        self.assert_one_store_opened_and_used_by_the_download()
        self.assert_every_store_closed_once()

    def test_ranking_with_rank_only_prints_and_stops_without_downloading_or_opening_the_store(self):
        rows = [(DIRECTORY.items[0], 5e8), (DIRECTORY.items[1], 2e8)]
        with mock.patch.object(tool, 'ranked', return_value=rows) as ranked:
            code, output = self.run_main('--top', '2', '--rank-only')
        self.assertEqual(code, 0)
        ranked.assert_called_once_with(self.session, DIRECTORY, 2)
        self.assertEqual(self.requests, [])
        self.assertEqual(FakeStore.opened, [])
        self.session.disconnect.assert_called_once_with()
        self.assertIn('成交金額前 2 名', output)

    def test_the_store_is_closed_when_the_login_or_the_download_fails(self):
        self.session.connect.side_effect = RuntimeError('login failed')
        with self.assertRaises(RuntimeError):
            self.run_main('--existing')
        self.assert_every_store_closed_once()
        self.session.connect.side_effect = None
        FakeStore.opened = []
        broken = self.recorder()
        broken.run_next = mock.Mock(side_effect=OSError('disk'))
        with self.assertRaises(OSError):
            self.run_main('--existing', HistorySync=broken)
        self.assertEqual(len(FakeStore.opened), 1)
        self.assert_every_store_closed_once()
        self.session.disconnect.assert_called()

    def test_it_refuses_to_run_while_the_app_is_open_and_touches_nothing(self):
        def untouched(name):
            return mock.Mock(side_effect=AssertionError(f'{name} must not be reached while the app is open'))

        guard = dict(
            markauto_running=mock.Mock(return_value=True),
            market_settings=untouched('market_settings'),
            SymbolDirectory=untouched('SymbolDirectory'),
            KlineStore=untouched('KlineStore'),
            create_market_session=untouched('create_market_session'),
        )  # the owner's real context is the tool's default: a refusal that stops refusing must fail here, not open it
        code, output = self.run_main('--existing', **guard)
        self.assertEqual(code, 2)
        self.assertIn('MarkAuto 正在執行', output)


if __name__ == '__main__':
    unittest.main()

"""The bulk K-line tool's --existing mode: which stocks it extends, how far back, and that listing never logs in."""

from contextlib import redirect_stdout
from datetime import timedelta
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
HELD = {'TPEX:6111': object(), 'TWSE:1101': object(), 'INDEX:IX0001': object(), 'TWSE:9999': object(), 'TWSE:2330': object()}


class FakeStore:
    def __init__(self, path):
        self.path = path

    def instrument_ids(self):
        return tuple(HELD) + ('TWSE:2002',)  # 2002 is listed but holds no minute bars

    def minute_extent(self, instrument_id):
        return HELD.get(instrument_id)


class ExistingSelectionTests(unittest.TestCase):
    def test_only_stocks_with_minute_bars_are_selected_in_code_order(self):
        stocks, unknown = tool.downloaded_stocks(FakeStore(None), DIRECTORY)
        self.assertEqual([stock.code for stock in stocks], ['1101', '2330', '6111'])  # no index, no stock without bars
        self.assertEqual(unknown, ['TWSE:9999'])  # held by the store but unknown to the symbol directory: reported, never requested

    def test_a_store_without_any_minute_bars_selects_nothing(self):
        empty = SimpleNamespace(instrument_ids=lambda: ('TWSE:1101',), minute_extent=lambda instrument_id: None)
        self.assertEqual(tool.downloaded_stocks(empty, DIRECTORY), ([], []))


class ExistingRunTests(unittest.TestCase):
    def run_main(self, *argv):
        self.session = mock.Mock()
        self.requests = []
        self.history_settings = []
        requests, history_settings = self.requests, self.history_settings

        class Recorder:
            def __init__(self, store, session, settings, autostart):
                history_settings.append((settings, autostart))

            def request(self, instrument, start, end, priority=0):
                requests.append((instrument.code, start, end, priority))

            def run_next(self):
                return False

            def next_retry_in(self):
                return None

            def state(self):
                return SimpleNamespace(paused=False, history_error=(), usage=None)

            def is_backfilling(self, instrument_id):
                return False

        patches = (
            mock.patch.object(tool, 'markauto_running', return_value=False),
            mock.patch.object(tool, 'market_settings', return_value=SimpleNamespace(environment=SimpleNamespace(value='BROKER_SIMULATION'))),
            mock.patch.object(tool, 'SymbolDirectory', return_value=DIRECTORY),
            mock.patch.object(tool, 'KlineStore', FakeStore),
            mock.patch.object(tool, 'create_market_session', return_value=self.session),
            mock.patch.object(tool, 'HistorySync', Recorder),
            mock.patch.object(tool, 'stored_bars', return_value=123),
        )
        output = StringIO()
        with redirect_stdout(output):
            for patch in patches:
                patch.start()
            try:
                code = tool.main(['--context', str(Path('context')), *argv])
            finally:
                mock.patch.stopall()
        return code, output.getvalue()

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

    def test_listing_with_rank_only_never_logs_in_and_requests_nothing(self):
        code, output = self.run_main('--existing', '--rank-only')
        self.assertEqual(code, 0)
        self.assertEqual(self.requests, [])
        self.session.connect.assert_not_called()
        self.assertIn('1101 2330 6111', output)

    def test_without_existing_the_ranking_path_is_unchanged(self):
        rows = [(DIRECTORY.items[0], 5e8), (DIRECTORY.items[1], 2e8)]
        with mock.patch.object(tool, 'ranked', return_value=rows) as ranked:
            code, output = self.run_main('--top', '2', '--days', '365')
        self.assertEqual(code, 0)
        ranked.assert_called_once()
        self.assertEqual([request[0] for request in self.requests], ['6111', '1101'])  # amount order, not code order
        self.assertIn('成交金額前 2 名', output)

    def test_it_refuses_to_run_while_the_app_is_open(self):
        with mock.patch.object(tool, 'markauto_running', return_value=True), redirect_stdout(StringIO()):
            self.assertEqual(tool.main(['--existing']), 2)


if __name__ == '__main__':
    unittest.main()

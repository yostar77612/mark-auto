"""Offline synthetic TRAINING coverage, not market or candidate qualification."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext, ROUND_UP
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quantlab.backtest import run_backtest
from quantlab.core import Dataset, Fill, Instrument, Signal, ValidationError, canonical_json, content_hash
from quantlab.research import candidate_fingerprint
from quantlab.strategies import generate_signals
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.daily_signal_data import OfficialDailyHistory
from quantlab.trading.domain.signal_strategy import SignalBar
from quantlab.trading.domain.stock_history import CorporateAction, DailyStockBar
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.adapters.official.stock_data import events_url
from quantlab.trading.ports.stock_history import OfficialPayload, OfficialStockBatch
from quantlab.trading.runtime import stock_signal_research as research
from quantlab.trading.runtime.v1_signal_source import V1SignalSource
from m3_stock_fixtures import daily_bars, daily_config, daily_dataset, specs, behavior_hash
from test_official_daily_source import CachedStore, calendar, sample

D = Decimal
ROOT = Path(__file__).parents[1]


def official_history():
    raw = daily_bars('TWSE:2330', fractional=True)
    history = OfficialDailyHistory(
        'TWSE:2330',
        tuple(DailyStockBar(b.contract_id, date.fromisoformat(b.trade_date), b.open, b.high, b.low, b.close, b.volume, 'a' * 64) for b in raw),
        (),
        raw[-1].end + timedelta(days=1),
        'b' * 64,
    )
    cal = TradingCalendar('synthetic', 'v1', 'synthetic', tuple(TradingSession(date.fromisoformat(b.trade_date), b.timestamp, b.end) for b in raw))
    return history, cal


class StockCoreTests(unittest.TestCase):
    def test_explicit_stock_decimal_signal_identity_not_execution_identity(self):
        for contract in ('TWSE:2330', 'TWSE:0050', 'TPEX:6488'):
            bar = daily_bars(contract, fractional=True)[0]
            self.assertEqual(Signal(bar.end, contract, 1, 'test').contract_id, contract)
            for value in (D('0.005'), D('0.00001')):
                replace(bar, open=value, high=value, low=value, close=value)
            with self.assertRaises(ValidationError):
                replace(bar, session='night')
            with self.assertRaises(ValidationError):
                Instrument(contract)
            with self.assertRaises(ValidationError):
                Fill('fill', 'order', bar.end, contract, 'buy', 1, bar.close, D(0), D(0))
            data = Dataset((bar,), {'source_type': 'synthetic', 'validation_status': 'valid', 'data_hash': content_hash((bar,))}, {'valid': True})
            with patch('quantlab.backtest.generate_signals') as called, self.assertRaises(ValidationError):
                run_backtest(data, specs()[0], daily_config())
            called.assert_not_called()
        for contract in ('2330', 'TWSE:ABC', 'TWSE:１２３４', 'TWSE:123', 'TPEX:1234567', 'TAIFEX:TX:202611'):
            with self.subTest(contract=contract), self.assertRaises(ValidationError):
                daily_bars(contract, fractional=True)
        for value in (D(0), D('-1'), D('NaN'), D('Infinity'), 100.5):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                replace(daily_bars('TWSE:2330', fractional=True)[0], close=value)

    def test_all_families_ast_fractional_prefix_and_exact_shared_callable(self):
        self.assertIs(research.generate_signals, generate_signals)
        for contract in ('TWSE:2330', 'TPEX:6488'):
            prices = [D('1000.25')] * 30 + [D('1010.25')] * 20 + [D('990.25')] * 20 + [D('1005.25')] * 30
            bars = tuple(
                replace(bar, open=price, high=price + D('.1'), low=price - D('.1'), close=price)
                for bar, price in zip(daily_bars(contract, fractional=True), prices, strict=True)
            )
            mapped = tuple(SignalBar(b.timestamp, b.end, date.fromisoformat(b.trade_date), b.session, b.open, b.high, b.low, b.close, b.volume) for b in bars)
            for spec in specs():
                with self.subTest(contract=contract, strategy=spec.strategy_id):
                    full = generate_signals(bars, spec)
                    self.assertTrue(full, f"decimal fixture must trigger {spec.strategy_id}")
                    actual = V1SignalSource().signals(contract, mapped, canonical_json(spec))
                    self.assertEqual(tuple((p.at, p.target, p.reason) for p in actual), tuple((p.timestamp, p.target_position, p.reason) for p in full))
                    for length in range(1, len(bars) + 1):
                        self.assertEqual(generate_signals(bars[:length], spec), tuple(p for p in full if p.timestamp <= bars[length - 1].end))

    def test_prechange_daily_behavior_spec_and_candidate_fingerprints_unchanged(self):
        baseline = json.loads((ROOT / 'tests/fixtures/m3_stock_daily_behavior.json').read_text())
        self.assertEqual(baseline['baseline_commit'], 'c447ba4da6f7dcd356a73f4b1f3cdd5b1b397e45')
        for spec, row in zip(specs(), baseline['rows'], strict=True):
            with self.subTest(strategy=spec.strategy_id):
                self.assertEqual(spec.strategy_id, row['strategy'])
                self.assertEqual(candidate_fingerprint(spec), row['candidate_fingerprint'])
                self.assertEqual(content_hash(spec), row['spec_hash'])
                self.assertEqual(behavior_hash(run_backtest(daily_dataset(), spec, daily_config())), row['behavior_hash'])


class StockSignalStudyTests(unittest.TestCase):
    def test_full_history_point_in_time_adjustment_does_not_rewrite_prior_decisions(self):
        history, cal = official_history()
        before = history.bars[30].trade_date
        event = CorporateAction(
            'TWSE:2330', history.bars[50].trade_date, history.bars[49].close, history.bars[49].close / 2, 'c' * 64, 'https://www.twse.com.tw/test'
        )
        changed = replace(history, events=(event,))
        original = research.stock_signal_dataset(history, cal, before)
        self.assertEqual(research.stock_signal_dataset(changed, cal, before), original)
        after = research.stock_signal_dataset(changed, cal, history.bars[-1].trade_date)
        self.assertEqual(after.bars[0].close, history.bars[0].close / 2)
        self.assertEqual(after.bars[-1].close, history.bars[-1].close)
        self.assertEqual(after.manifest['partition'], 'TRAINING')
        self.assertEqual(len(after.bars), len(history.bars))
        with self.assertRaises(ValidationError):
            run_backtest(after, specs()[0], daily_config())

    def inputs(self):
        # Two observed dates over five explicit calendar years: intentionally
        # sparse SYNTHETIC coverage, never claimed to be a real exchange calendar.
        first, through = date(2020, 1, 2), date(2025, 1, 2)
        # Different monthly documents are required for real source validation;
        # use a trusted fake history here, with separate real-reader coverage below.
        history, _ = official_history()
        raw = (replace(history.bars[0], trade_date=first), replace(history.bars[1], trade_date=through))
        cal = calendar((first, through))
        value = replace(history, bars=raw, observed_at=datetime(2025, 1, 3, tzinfo=timezone.utc))
        return first, through, cal, value

    def run_fake(self, **kwargs):
        first, through, cal, value = self.inputs()
        store = SimpleNamespace(verification_revision=1)
        clock = SimpleNamespace(now=lambda: datetime(2025, 1, 4, tzinfo=timezone.utc))
        with patch.object(research.OfficialDailyStockSource, 'history', return_value=value):
            return research.research_stock_signals(store, 'TWSE:2330', cal, first, through, canonical_json(specs()[-1]), clock=clock, **kwargs)

    def test_study_is_repeatable_long_only_immutable_and_source_bound(self):
        first = self.run_fake()
        self.assertEqual(first, self.run_fake())
        self.assertEqual(first.manifest['partition'], 'TRAINING')
        self.assertEqual(first.manifest['direction_policy'], 'LONG_ONLY')
        self.assertTrue(all(p['target'] in (0, 1) for p in first.targets))
        self.assertIn('no E1, E2, PnL', first.manifest['scope'])
        self.assertEqual(first.result_hash, content_hash({'manifest': first.manifest, 'targets': first.targets}))
        self.assertEqual(set(first.manifest['signal_sources']), {'core.py', 'strategies.py', 'research.py', 'backtest.py'})
        with self.assertRaises(TypeError):
            first.targets[0]['target'] = -1
        with localcontext() as context:
            context.prec = 6
            context.rounding = ROUND_UP
            self.assertEqual(first, self.run_fake())

    def test_long_only_projects_real_negative_states_without_changing_shared_signals(self):
        history, _ = official_history()
        first = date(2020, 1, 2)
        history = replace(history, bars=(replace(history.bars[0], trade_date=first), *history.bars[1:]))
        through = history.bars[-1].trade_date
        cal = calendar(tuple(bar.trade_date for bar in history.bars))
        store = SimpleNamespace(verification_revision=1)
        clock = SimpleNamespace(now=lambda: history.observed_at + timedelta(days=1))
        calls = []

        def shared(bars, spec):
            actual = generate_signals(bars, spec)
            calls.append((bars, actual))
            return actual

        with patch.object(research.OfficialDailyStockSource, 'history', return_value=history), patch.object(research, 'generate_signals', side_effect=shared):
            result = research.research_stock_signals(store, 'TWSE:2330', cal, first, through, canonical_json(specs()[-1]), clock=clock)
        # The shared callable runs once per adjustment horizon (here: no events, so once
        # over the complete history); each decision day sees the signals up to its own bar.
        self.assertEqual(len(calls), 1)
        bars, actual = calls[0]
        seen = []
        for index in range(len(bars)):
            known = [p for p in actual if p.timestamp <= bars[index].end]
            seen.append(known[-1].target_position if known else 0)
            # Causality: the prefix run is exactly the full run restricted to that bar.
            self.assertEqual(generate_signals(bars[: index + 1], specs()[-1]), tuple(known))
        self.assertEqual(set(seen), {-1, 0, 1})
        self.assertEqual(tuple(row['target'] for row in result.targets), tuple(max(0, value) for value in seen))

    def test_execution_parameters_cannot_be_misrepresented_as_signal_only_research(self):
        first, through, cal, _ = self.inputs()
        for change in ({'stop_ticks': 3}, {'target_ticks': 4}, {'quantity': 2}):
            spec = replace(specs()[0], parameters={**specs()[0].parameters, **change})
            with patch.object(research.OfficialDailyStockSource, 'history') as read, self.assertRaises(DomainError) as raised:
                research.research_stock_signals(None, 'TWSE:2330', cal, first, through, canonical_json(spec), clock=None)
            self.assertEqual(raised.exception.code, 'candidate_spec_unsupported')
            read.assert_not_called()

    def test_invalid_partition_deadline_cancellation_before_any_read(self):
        for options in (
            {'partition': 'OUT_OF_SAMPLE'},
            {'partition': 'FINAL_HOLDOUT'},
            {'max_seconds': 901},
            {'max_seconds': True},
            {'cancelled': lambda: True},
        ):
            with self.subTest(options=options), self.assertRaises(DomainError):
                self.run_fake(**options)
        with self.assertRaises(DomainError) as raised:
            self.run_fake(timer=iter((0, 901)).__next__)
        self.assertEqual(raised.exception.code, 'research_timeout')

    def test_insufficient_range_tpex_and_wrong_instrument_fail_before_source_read(self):
        first, through, cal, _ = self.inputs()
        for instrument, start in (('TPEX:6488', first), ('TWSE:2330', date(2024, 1, 1)), ('2330', first), ('TAIFEX:TMF:202611', first)):
            with self.subTest(instrument=instrument, start=start), patch.object(research.OfficialDailyStockSource, 'history') as read:
                with self.assertRaises(DomainError):
                    research.research_stock_signals(None, instrument, cal, start, through, canonical_json(specs()[0]), clock=None)
                read.assert_not_called()

    def test_actual_reader_refuses_unknown_missing_or_tampered_official_evidence(self):
        first, through, cal, _ = self.inputs()
        store = CachedStore(sample())
        clock = SimpleNamespace(now=lambda: datetime(2025, 1, 4, tzinfo=timezone.utc))
        with self.assertRaises(DomainError):
            research.research_stock_signals(store, 'TWSE:2330', cal, first, through, canonical_json(specs()[0]), clock=clock)

    def test_actual_verified_reader_runs_without_download_or_any_write(self):
        first, through, cal, _ = self.inputs()
        early = sample(first=first, through=first)
        late = sample(first=through, through=through)
        event = early.payloads[-1]
        event = OfficialPayload(events_url('TWSE:2330', first, through + timedelta(days=1)), event.digest, event.raw)
        batch = OfficialStockBatch('TWSE:2330', first, through + timedelta(days=1), early.bars + late.bars, (), (early.payloads[0], late.payloads[0], event))
        store = CachedStore(batch)
        clock = SimpleNamespace(now=lambda: datetime(2025, 1, 4, tzinfo=timezone.utc))
        result = research.research_stock_signals(store, 'TWSE:2330', cal, first, through, canonical_json(specs()[0]), clock=clock)
        self.assertEqual(len(result.targets), 2)
        self.assertEqual(store.batch, batch)
        self.assertTrue(any(call[0] == 'payload' for call in store.calls))
        self.assertTrue(all(call[0] in ('history', 'coverage', 'payload') for call in store.calls))
        store.coverage = False
        with self.assertRaises(DomainError):
            research.research_stock_signals(store, 'TWSE:2330', cal, first, through, canonical_json(specs()[0]), clock=clock)

    def test_revision_or_shared_source_change_cannot_return_artifact(self):
        first, through, cal, value = self.inputs()
        store = SimpleNamespace(verification_revision=1)
        clock = SimpleNamespace(now=lambda: datetime(2025, 1, 4, tzinfo=timezone.utc))

        def changed(*args, **kwargs):
            store.verification_revision = 2
            return value

        with patch.object(research.OfficialDailyStockSource, 'history', side_effect=changed), self.assertRaises(DomainError) as raised:
            research.research_stock_signals(store, 'TWSE:2330', cal, first, through, canonical_json(specs()[0]), clock=clock)
        self.assertEqual(raised.exception.code, 'source_invalid_evidence')
        with patch.object(research, '_source_identity', side_effect=({'version': 1}, {'version': 2})), self.assertRaises(DomainError) as raised:
            self.run_fake()
        self.assertEqual(raised.exception.code, 'source_invalid_evidence')


if __name__ == '__main__':
    unittest.main()

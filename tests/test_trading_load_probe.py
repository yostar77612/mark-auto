"""Load samples require an actual successful rendered response, not idle state."""

import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.trading_load_probe import Probe


class LoadSampleTests(unittest.TestCase):
    def probe(self):
        probe = Probe.__new__(Probe)
        probe.pending = None
        probe.pending_operation = None
        probe.pending_rendered = False
        probe.sample_error = ''
        probe.refresh_requests = probe.refresh_completions = probe.refresh_failures = 0
        probe.latencies = []
        probe.window = SimpleNamespace(state=SimpleNamespace(markets=[]), market_refresh_button=object())
        return probe

    def test_success_is_measured_through_render_and_finished(self):
        probe, operation = self.probe(), object()
        probe.pending = 1.0
        probe.sample_started(operation)
        probe.sample_rendered(operation, True)
        self.assertEqual(probe.latencies, [])
        with patch('tools.trading_load_probe.time.perf_counter', return_value=1.125):
            probe.sample_finished(operation)
        self.assertEqual(probe.latencies, [125.0])
        self.assertEqual(probe.refresh_requests, probe.refresh_completions)
        self.assertEqual(probe.sample_error, '')

    def test_failed_query_is_not_a_successful_latency_sample(self):
        probe, operation = self.probe(), object()
        probe.pending = time.perf_counter()
        probe.sample_started(operation)
        probe.sample_rendered(operation, False)
        probe.sample_finished(operation)
        self.assertEqual(probe.refresh_failures, 1)
        self.assertEqual(probe.refresh_completions, 0)
        self.assertEqual(probe.latencies, [])
        self.assertEqual(probe.sample_error, 'UI refresh query failed')

    def test_wrong_operation_or_missing_render_cannot_count_as_completion(self):
        for wrong in (False, True):
            with self.subTest(wrong_operation=wrong):
                probe, operation = self.probe(), object()
                probe.pending = time.perf_counter()
                probe.sample_started(operation)
                if wrong:
                    probe.sample_rendered(object(), True)
                probe.sample_finished(operation)
                self.assertTrue(probe.sample_error)
                self.assertEqual(probe.latencies, [])
                self.assertEqual(probe.refresh_completions, 0)

    def test_duplicate_response_cannot_double_count(self):
        probe, operation = self.probe(), object()
        probe.pending = time.perf_counter()
        probe.sample_started(operation)
        probe.sample_rendered(operation, True)
        probe.sample_rendered(operation, True)
        probe.sample_finished(operation)
        self.assertIn('duplicate', probe.sample_error)
        self.assertEqual(probe.latencies, [])

    def test_completion_before_mouse_click_returns_remains_a_valid_sample(self):
        probe, operation = self.probe(), object()
        probe.started = time.monotonic()
        probe.seconds = 60
        probe.next_refresh = 0
        probe.next_memory = float('inf')
        probe.producer = SimpleNamespace(error='')

        def native_click(*_):
            probe.sample_started(operation)
            probe.sample_rendered(operation, True)
            probe.sample_finished(operation)

        with patch('tools.trading_load_probe.QTest.mouseClick', side_effect=native_click):
            probe.observe()
        self.assertEqual(probe.refresh_requests, 1)
        self.assertEqual(probe.refresh_completions, 1)
        self.assertEqual(len(probe.latencies), 1)
        self.assertIsNone(probe.pending_operation)
        self.assertEqual(probe.sample_error, '')

    def test_pending_refresh_retains_existing_ten_second_ipc_deadline(self):
        probe = self.probe()
        probe.started = time.monotonic()
        probe.pending = time.perf_counter() - 11
        with self.assertRaisesRegex(RuntimeError, 'IPC response deadline'):
            probe.observe()

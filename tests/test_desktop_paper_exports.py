"""Replay JSON exports from the real UI worker; disposable synthetic accounts."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_app.shell.main_window import execute_ui_operation, paper_risk_limits
from quantlab.core import Instrument, content_hash, to_dict
from quantlab.desktop_runtime import AppPaths
from quantlab.paper import PaperBroker
from quantlab.reporting import demo_config, read_json, save_dataset, synthetic_dataset, write_json
from quantlab.strategies import builtin_strategies


class PaperReplayExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='paper-export-')
        self.addCleanup(self.tmp.cleanup)
        self.paths = AppPaths(Path(self.tmp.name) / 'workspace').ensure()
        self.root = self.paths.state
        for target in ('socket.socket', 'subprocess.Popen'):
            guard = patch(target, side_effect=AssertionError('offline worker test only'))
            guard.start()
            self.addCleanup(guard.stop)
        self.policy = {
            'contract_id': 'TAIFEX:TMF:202601',
            'risk_sessions': [
                {
                    'open': '2026-01-05T00:45:00Z',
                    'end': '2026-01-05T04:45:00Z',
                    'trade_date': '2026-01-05',
                    'session': 'day',
                    'source': 'synthetic export fixture',
                }
            ],
            'margin_schedule': [{'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'synthetic-export-v1'}],
        }
        self.data = synthetic_dataset(120)
        self.spec = builtin_strategies()[0]
        save_dataset(self.data, self.root / 'dataset.json')
        write_json(
            self.root / 'selection.json',
            {
                'strategy': to_dict(self.spec),
                'strategy_hash': content_hash(self.spec),
                'result_hash': 'f' * 64,
                'scope': 'research_and_paper_only',
            },
        )
        execute_ui_operation('ui_paper_snapshot', {'policy': self.policy}, self.paths)
        self.old_snapshot = read_json(self.root / 'paper_snapshot.json')
        self.old_journal = read_json(self.root / 'paper_journal_export.json')
        self.payload = {
            'reconcile_confirmed': True,
            'max_bars': 100,
            'snapshot': {'account_id': 'synthetic-export', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}},
        }

    def broker(self):
        return PaperBroker(
            self.root / 'paper.sqlite3',
            instrument=Instrument(self.policy['contract_id']),
            costs=demo_config().costs,
            limits=paper_risk_limits(),
            risk_sessions=tuple(self.policy['risk_sessions']),
            margin_schedule=tuple(self.policy['margin_schedule']),
        )

    def test_successful_replay_refreshes_snapshot_and_complete_journal_exports(self):
        result = execute_ui_operation('ui_paper_replay', self.payload, self.paths)
        self.assertEqual(set(result), {'replay', 'account'})
        self.assertEqual(result['replay']['cursor'], 100)
        self.assertFalse(result['replay']['active'])
        self.assertTrue(result['account']['kill_switch'])
        self.assertTrue(result['account']['fills'])
        self.assertNotEqual(result['account'], self.old_snapshot)
        snapshot = read_json(self.root / 'paper_snapshot.json')
        self.assertEqual(snapshot, result['account'], 'JSON snapshot must contain the completed replay account')
        exported = read_json(self.root / 'paper_journal_export.json')
        self.assertEqual(exported[: len(self.old_journal)], self.old_journal)
        self.assertGreater(len(exported), len(self.old_journal))
        self.assertEqual(exported[-1]['operation'], 'kill')
        self.assertEqual(exported[-1]['payload'], {'active': True})
        self.assertEqual(exported[-1]['state_hash'], content_hash(snapshot))
        broker = self.broker()  # A later UI refresh may append restart/kill bookkeeping.
        broker.set_kill_switch(True)
        current = broker.journal_events()
        self.assertEqual(current[: len(exported)], exported)
        self.assertEqual([(row['operation'], row['payload']) for row in current[len(exported) :]], [('restart', {}), ('kill', {'active': True})])
        self.assertEqual(broker.snapshot()['fills'], snapshot['fills'])

    def _export_failure(self, filename):
        from quantlab.paper_replay import PaperReplay

        original_start, original_step, original_stop = PaperReplay.start, PaperReplay.step, PaperReplay.stop
        observed, writes = {}, []

        def step(replay, **kwargs):
            observed['replay'] = replay
            return original_step(replay, **kwargs)

        def export(path, value):
            writes.append(Path(path).name)
            if Path(path).name == filename:
                replay = observed['replay']
                observed['cursor'] = replay.snapshot()
                observed['account'] = replay.broker.snapshot()
                observed['journal'] = replay.broker.journal_events()
                raise OSError('synthetic post-commit export failure')
            return write_json(path, value)

        with (
            patch.object(PaperReplay, 'start', autospec=True, side_effect=original_start) as start,
            patch.object(PaperReplay, 'step', autospec=True, side_effect=step) as advance,
            patch.object(PaperReplay, 'stop', autospec=True, side_effect=original_stop) as stop,
            patch('desktop_app.shell.main_window.write_json', side_effect=export),
        ):
            with self.assertRaisesRegex(OSError, 'synthetic post-commit export failure'):
                execute_ui_operation('ui_paper_replay', self.payload, self.paths)
        self.assertEqual((start.call_count, advance.call_count, stop.call_count), (1, 1, 1))
        replay = observed['replay']
        self.assertEqual(observed['cursor']['cursor'], 100)
        self.assertFalse(observed['cursor']['active'])
        self.assertTrue(observed['account']['fills'])
        self.assertTrue(observed['account']['kill_switch'])
        self.assertEqual(replay.snapshot(), observed['cursor'])
        self.assertEqual(replay.broker.snapshot(), observed['account'])
        self.assertEqual(replay.broker.journal_events(), observed['journal'])
        self.assertEqual(read_json(self.root / 'paper_journal_export.json'), self.old_journal)
        if filename == 'paper_snapshot.json':
            self.assertEqual(writes, ['paper_snapshot.json'])
            self.assertEqual(read_json(self.root / 'paper_snapshot.json'), self.old_snapshot)
        else:
            self.assertEqual(writes, ['paper_snapshot.json', 'paper_journal_export.json'])
            self.assertEqual(read_json(self.root / 'paper_snapshot.json'), observed['account'])

    def test_snapshot_export_failure_does_not_repeat_committed_replay(self):
        self._export_failure('paper_snapshot.json')

    def test_journal_export_failure_does_not_repeat_committed_replay(self):
        self._export_failure('paper_journal_export.json')

    def _replay_failure(self, failing_method):
        from quantlab.paper_replay import PaperReplay

        original_start, original_step, original_stop = PaperReplay.start, PaperReplay.step, PaperReplay.stop
        observed = {}

        def step(replay, **kwargs):
            observed['replay'] = replay
            value = original_step(replay, **kwargs)
            if failing_method == 'step':
                raise RuntimeError('synthetic step failure')
            return value

        def stop(replay):
            value = original_stop(replay)
            if failing_method == 'stop':
                raise RuntimeError('synthetic stop failure')
            return value

        with (
            patch.object(PaperReplay, 'start', autospec=True, side_effect=original_start) as start,
            patch.object(PaperReplay, 'step', autospec=True, side_effect=step) as advance,
            patch.object(PaperReplay, 'stop', autospec=True, side_effect=stop) as halt,
            patch('desktop_app.shell.main_window.write_json', wraps=write_json) as export,
        ):
            with self.assertRaisesRegex(RuntimeError, 'synthetic ' + failing_method + ' failure'):
                execute_ui_operation('ui_paper_replay', self.payload, self.paths)
        self.assertEqual((start.call_count, advance.call_count, halt.call_count), (1, 1, 1))
        export.assert_not_called()
        self.assertEqual(read_json(self.root / 'paper_snapshot.json'), self.old_snapshot)
        self.assertEqual(read_json(self.root / 'paper_journal_export.json'), self.old_journal)
        replay = observed['replay']
        self.assertEqual(replay.snapshot()['cursor'], 100)
        self.assertFalse(replay.snapshot()['active'])
        self.assertTrue(replay.broker.snapshot()['kill_switch'])

    def test_step_failure_is_stopped_once_without_success_exports(self):
        self._replay_failure('step')

    def test_stop_failure_is_not_retried_or_published_as_success(self):
        self._replay_failure('stop')

    def test_non_replay_paper_return_shape_and_exports_are_preserved(self):
        for operation, payload in [('ui_paper_reconcile', {'snapshot': self.payload['snapshot']}), ('ui_paper_kill', {})]:
            with self.subTest(operation=operation):
                result = execute_ui_operation(operation, payload, self.paths)
                self.assertEqual(set(result), {'account', 'journal_tail', 'journal_file'})
                self.assertEqual(result['account'], read_json(self.root / 'paper_snapshot.json'))
                self.assertEqual(result['journal_tail'], read_json(self.root / 'paper_journal_export.json')[-20:])
                self.assertEqual(result['journal_file'], str(self.root / 'paper_journal_export.json'))


if __name__ == '__main__':
    unittest.main()

"""In-memory characterization captured before the Part C extractions."""

from quantlab.research_core.application import job_manager
from quantlab.research_core.adapters.workspace_backup import WorkspaceJobStorage


from quantlab.research_core.application.job_manager import JobManager

from quantlab.research_core.adapters import job_process

from quantlab.research_core.domain import saved_pool


from dataclasses import replace
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import unittest
from unittest.mock import Mock, patch

from quantlab import chart_data, paper, saved_candidate_pool, walk_forward
from quantlab import desktop_runtime
from quantlab.core import content_hash, to_dict
from quantlab.desktop_runtime import RuntimeSafetyError
from tests.test_chart_data import START, bar
from tests import saved_pool_fixtures
from tests.test_walk_forward import inputs, fake_worker


def runtime_oracle():
    results = []
    cases = [
        ('demo', {'bars': 20}),
        ('ui_walk_forward_read', {'reference': 'a' * 64}),
        ('ui_analysis_read', {'analysis_id': 'b' * 64}),
        ('ui_chatgpt_auth', {'request': dict(request_id=1, action='fixture', registration='fixture', max_runtime_seconds=30, user_confirmed=True)}),
        ('ui_campaign', {'provider': {'mode': 'chatgpt_plan'}, 'config': {'max_runtime_seconds': 40}}),
    ]
    for registrar in (None, 'fixture:registrar'):
        for operation, payload in cases:
            paths = SimpleNamespace(root=Path('fixture'), bootstrap=None, state=Path('fixture-state'))
            manager = JobManager.__new__(JobManager)
            manager.paths, manager.process, manager.tree = paths, None, None
            manager._log = Mock()
            manager.process_port = job_process.DesktopJobProcess()
            manager.storage_port = WorkspaceJobStorage()
            context = Mock()
            context.Pipe.return_value = (Mock(), Mock())
            with (
                patch('quantlab.analysis_recovery.require_operation'),
                patch.object(job_process.mp, 'get_context', return_value=context),
                patch.object(job_manager.uuid, 'uuid4', return_value=SimpleNamespace(hex='job')),
                patch.object(job_manager.time, 'monotonic', return_value=100.0),
                patch.object(desktop_runtime.sys, 'platform', 'linux'),
                patch('quantlab.research_core.adapters.job_worker._executor_registrar', registrar),
            ):
                job = manager.start(operation, payload)
            args = context.Process.call_args.kwargs['args']
            results.append(
                [
                    operation,
                    registrar,
                    job,
                    manager._deadline,
                    manager._auth_request_id,
                    manager._subscription_job,
                    manager._requires_tree_quiescence,
                    manager._analysis_result_reference,
                    manager._walk_forward_result_reference,
                    args[2:],
                    context.Event.return_value.set.call_count,
                    context.Process.return_value.start.call_count,
                    context.Pipe.return_value[1].close.call_count,
                ]
            )
    return content_hash(results)


def admission_oracle():
    def reserve(dataset, **kwargs):
        return {'status': 'reserved_consumed', 'holdout_hash': content_hash(dataset.bars)}

    with patch.object(saved_pool_fixtures, '_reserve_holdout', side_effect=reserve), patch.object(saved_pool_fixtures, 'write_source'):
        folder, reference, data, state = saved_pool_fixtures.make_saved_source(Path('fixture'), candidates=3)
    with (
        patch.object(saved_candidate_pool, '_read_campaign', return_value=state),
        patch.object(saved_candidate_pool, '_validate_source_registry', return_value={'fixture': True}),
    ):
        return content_hash(
            saved_candidate_pool.admit_saved_campaign_pool(
                source_campaign_dir=folder,
                source_campaign_ref=reference,
                original_dataset=data,
                original_dataset_ref='fixture-dataset',
                first_training_timestamp=START,
            )
        )


def walk_forward_oracle(status='reserved_consumed', cancelled=False):
    dataset, plan = inputs(process_start_method='spawn')
    plan = walk_forward.walk_forward_plan_from_dict(to_dict(plan))
    snapshots = []
    connect = sqlite3.connect
    with ExitStack() as stack:
        for name in ('_require_wal_runtime', '_require_local_wal_path', '_configure_state_storage'):
            stack.enter_context(patch.object(walk_forward, name))
        stack.enter_context(patch.object(walk_forward, '_read_state', return_value=None))
        stack.enter_context(patch.object(walk_forward, '_save_state', side_effect=lambda db, folder, state: snapshots.append(content_hash(state))))
        stack.enter_context(patch.object(walk_forward, 'walk_forward_binding', return_value={'fixture': True}))
        stack.enter_context(patch.object(walk_forward, '_run_bounded', side_effect=fake_worker))
        stack.enter_context(patch.object(walk_forward, '_reserve_holdout', return_value={'status': status}))
        stack.enter_context(patch.object(walk_forward.time, 'monotonic', return_value=100.0))
        stack.enter_context(patch.object(walk_forward.sqlite3, 'connect', side_effect=lambda *a, **k: connect(':memory:')))
        stack.enter_context(patch.object(Path, 'mkdir'))
        stack.enter_context(patch.object(Path, 'exists', return_value=False))
        state = walk_forward.run_walk_forward(
            dataset, plan=plan, output_dir=Path('fixture-output'), holdout_registry_path=Path('fixture-registry'), cancelled=lambda: cancelled
        )
    return content_hash([snapshots, state])


def chart_oracle():
    bars = [replace(bar(i, str(10 + i)), source_id='a' if i % 2 else 'b', volume=None if i == 4 else i + 1) for i in (0, 1, 3, 4, 5)]
    bars = [bars[-1], *bars, bars[0]]
    return {
        period: content_hash(chart_data.aggregate_bars(bars, timeframe=period, as_of=START + timedelta(minutes=6))) for period in ('1m', '3m', '5m', '1d', '1w')
    }


def paper_oracle():
    state = paper._initial()
    hashes = []
    events = [('initialize', {'account_id': 'fixture', 'cash': '10000'})]
    for index, (side, quantity, price) in enumerate([('buy', 3, '100'), ('sell', 1, '90'), ('sell', 3, '110'), ('buy', 1, '120')]):
        oid = str(index)
        stamp = (START + timedelta(seconds=index)).isoformat()
        intent = dict(client_order_id=oid, contract_id='fixture', side=side, quantity=quantity, created_at=stamp)
        events.extend(
            [
                ('intent', dict(intent=intent, trade_date='2026-10-09', now=stamp, window_seconds=60, quote={'price': price})),
                ('ack', {'order_id': oid}),
                (
                    'event',
                    dict(
                        order_id=oid,
                        sequence=1,
                        timestamp=stamp,
                        type='fill',
                        fill_id=oid,
                        quantity=quantity,
                        price=price,
                        multiplier='10',
                        commission='1.25',
                        tax='0.15',
                    ),
                ),
            ]
        )
    events.extend([('restart', {}), ('quarantine', {'event_id': 'bad'}), ('consecutive_loss_halt', {}), ('kill', {'active': True})])
    for op, payload in events:
        before = content_hash(state)
        result = paper._reduce(state, op, payload)
        if content_hash(state) != before:
            raise AssertionError('reducer mutated input state')
        state = result
        hashes.append(content_hash(state))
    return content_hash(hashes)


class PartCBehaviorTests(unittest.TestCase):
    def test_existing_engine_golden(self):
        from tests.test_backtest import EngineTests

        EngineTests('test_independent_golden_pnl').test_independent_golden_pnl()

    def test_runtime_original_launch_arguments_and_deadlines(self):
        self.assertEqual(runtime_oracle(), RUNTIME_EXPECTED)

    def test_saved_admission_original_hash(self):
        self.assertEqual(admission_oracle(), ADMISSION_EXPECTED)

    def test_walk_forward_original_save_order_and_hashes(self):
        self.assertEqual([walk_forward_oracle(), walk_forward_oracle('blocked'), walk_forward_oracle(cancelled=True)], WALK_FORWARD_EXPECTED)

    def test_chart_original_output_hashes(self):
        self.assertEqual(chart_oracle(), CHART_EXPECTED)

    def test_paper_original_replay_hash(self):
        self.assertEqual(paper_oracle(), PAPER_EXPECTED)

    def test_admission_validation_order(self):
        with self.assertRaisesRegex(saved_pool.SavedCandidatePoolError, 'Source campaign reference must be a normal 64-hex workspace reference'):
            saved_candidate_pool.admit_saved_campaign_pool(
                source_campaign_dir=None, source_campaign_ref='invalid', original_dataset=None, original_dataset_ref=None, first_training_timestamp=None
            )

    def test_start_active_rejects_before_payload_access(self):
        manager = Mock()
        manager.active = True
        with self.assertRaisesRegex(RuntimeSafetyError, 'A job is already running'):
            JobManager.start(manager, None, None)
        manager.assert_not_called()

    def test_wal_runtime_precedes_path_and_source_validation(self):
        with (
            patch.object(walk_forward, '_require_wal_runtime', side_effect=RuntimeError('guard')),
            patch.object(walk_forward, '_require_local_wal_path') as local,
            patch.object(walk_forward, '_validate_source') as source,
        ):
            with self.assertRaisesRegex(RuntimeError, 'guard'):
                walk_forward.run_walk_forward(None, plan=None, output_dir=None, holdout_registry_path=None)
            local.assert_not_called()
            source.assert_not_called()


CHART_EXPECTED = {
    '1m': '8f3cd738b868f265c0bd66644cfb4fc8cdc593ff57b67639325a0facb09abd36',
    '3m': '56c5b923635db5a93ac061ce9b8cb0140e0d23053b0f8cd9ecb5187347fe8a96',
    '5m': '9b878d082fc9e65718a3d694dad0e2465fdf6a6cb65cdc812e8ad365a3499198',
    '1d': '9d1b67310471788ed286f4268f82c0b1f2b97dbbecabd63b80d51a015496c8db',
    '1w': 'c2c04bb676c63ee7a84ab8f2ee48416074872ebdea9d59e4c0af8682a7613f0e',
}
PAPER_EXPECTED = '221f0d3fe2b00b0c86b685d2ead44c9296c7d9b2061d0f1db1c1bd1f3cd07492'

ADMISSION_EXPECTED = '2c16cabfe2815284218524ead4e55f90d35f1f95537c064b15296cf65061ad19'
WALK_FORWARD_EXPECTED = [
    'c7a5f1074b3ca45a553c94b587c1f66610e7d07c6e6999242392cbfe208b8967',
    'cc1a142933220628243ee47bd50422c33710b891ed860d6eb38d0d73fa241e3f',
    '39be8bae5d17cea06d15e7a53881c19bd41492265b296ba78391f28c611c66f1',
]
RUNTIME_EXPECTED = '248b87e056be8cfff763bea2558e3d295f79f2a298096429d548eb6cd125036d'

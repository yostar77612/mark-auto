"""Source/mocked checks only; actual frozen proof belongs to installed EXE CI."""

import ast
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import desktop_app.smoke.recovery as smoke
from quantlab.analysis_recovery import plan_bindings, admission, register_launch, read_launch
from quantlab.desktop_runtime import AppPaths
from quantlab.reporting import synthetic_dataset, save_dataset
from quantlab.research_analysis import validate_analysis_plan
from tests.test_research_analysis import source, write_source


class RecoveryFrozenSmokeTests(unittest.TestCase):
    def test_nonwindows_is_not_applicable_without_fixture_or_processes(self):
        with patch.object(smoke.sys, 'platform', 'linux'), patch.object(smoke.mp, 'get_context') as spawn:
            result = smoke.run_recovery_smoke(None, None, deadline=0)
        self.assertEqual(result['status'], 'not_applicable')
        self.assertTrue(result['cleanup_verified'])
        spawn.assert_not_called()

    def test_unfrozen_windows_is_not_frozen_proof(self):
        with (
            patch.object(smoke.sys, 'platform', 'win32'),
            patch.object(smoke.sys, 'frozen', False, create=True),
            patch.object(smoke.mp, 'get_context') as spawn,
        ):
            result = smoke.run_recovery_smoke(None, None, deadline=time.monotonic() + 40)
        self.assertEqual(result['status'], 'not_applicable')
        self.assertFalse(result['frozen'])
        spawn.assert_not_called()

    def test_insufficient_or_invalid_budget_never_starts(self):
        with (
            patch.object(smoke.sys, 'platform', 'win32'),
            patch.object(smoke.sys, 'frozen', True, create=True),
            patch.object(smoke.mp, 'get_context') as spawn,
            patch.object(smoke.threading, 'Timer') as timer,
        ):
            for deadline in (True, float('inf'), time.monotonic() + 1, 0):
                result = smoke.run_recovery_smoke(None, None, deadline=deadline)
                self.assertEqual(result['status'], 'failed')
        spawn.assert_not_called()
        timer.assert_not_called()

    def test_strict_real_plan_and_ledger_without_provider_or_auth(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = AppPaths(Path(folder)).ensure()
            data, state, campaign = source(paths.state / 'campaigns', synthetic_dataset(120))
            state['real_model_status'] = 'not_verified'
            write_source(campaign, state)
            save_dataset(data, paths.state / 'dataset.json')
            with (
                patch('socket.create_connection', side_effect=AssertionError('No network')),
                patch('quantlab.assistant.adapters.chatgpt.provider.analysis_provider', side_effect=AssertionError('No provider')),
                patch('quantlab.assistant.adapters.chatgpt.auth.OAuthCredentialReference', side_effect=AssertionError('No credentials')),
            ):
                plan, request = smoke._prepare_plan(paths, state, time.monotonic() + 10)
                self.assertEqual(validate_analysis_plan(plan), plan)
                binding = plan_bindings(plan)
                with admission(paths) as owner:
                    launch = register_launch(paths, job_id='b' * 32, helper_nonce='c' * 32, approved_plan=plan, request=request, admission=owner)
                self.assertEqual(read_launch(paths, 'b' * 32), launch)
                self.assertEqual(launch['plan_hash'], binding['plan_hash'])
                self.assertFalse((paths.state / 'analyses').exists())

    def test_reuses_actual_production_fixture_campaign_without_rewriting_it(self):
        from quantlab.core import content_hash
        from quantlab.reporting import demo_config
        from quantlab.research import demo_campaign_config, FixtureGenerator, run_campaign

        with tempfile.TemporaryDirectory() as folder:
            paths = AppPaths(Path(folder)).ensure()
            data = synthetic_dataset(120)
            save_dataset(data, paths.state / 'dataset.json')
            config = demo_campaign_config(data, demo_config())
            config.update(families=['trend'], max_trials=1, max_improvements=0, max_runtime_seconds=10)
            config['ranking']['minimum'] = '1000000000000'
            campaign = paths.state / 'campaigns' / content_hash('frozen-smoke-fixture')
            state = run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=campaign)
            before = {p.name: p.read_bytes() for p in campaign.iterdir() if p.is_file()}
            plan, request = smoke._prepare_plan(paths, state, time.monotonic() + 10)
            self.assertEqual(plan['binding']['packet']['provenance']['campaign_ref'], campaign.name)
            self.assertEqual(request['campaign_reference'], campaign.name)
            self.assertEqual(before, {p.name: p.read_bytes() for p in campaign.iterdir() if p.is_file()})

    def test_nonfixture_campaign_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = AppPaths(Path(folder)).ensure()
            save_dataset(synthetic_dataset(120), paths.state / 'dataset.json')
            with self.assertRaises(ValueError):
                smoke._prepare_plan(paths, {'status': 'completed', 'real_model_status': 'verified'}, time.monotonic() + 10)

    def test_long_fixture_uses_canonical_reference_without_relaxing_admission(self):
        from quantlab.desktop_runtime import RuntimeSafetyError, validate_analysis_request
        from quantlab.windows_paths import canonical_path, native_path

        with tempfile.TemporaryDirectory(dir=native_path(tempfile.gettempdir(), force=True)) as folder:
            root = Path(folder)
            while len(str(root).encode('utf-16-le')) // 2 < 400:
                root /= 'SYNTHETIC-long-recovery-0123456789'
            paths = AppPaths(native_path(root)).ensure()
            data, state, campaign = source(paths.state / 'campaigns', synthetic_dataset(120))
            state['real_model_status'] = 'not_verified'
            write_source(campaign, state)
            dataset_path = paths.state / 'dataset.json'
            save_dataset(data, dataset_path)
            with (
                patch('socket.create_connection', side_effect=AssertionError('No network')),
                patch('quantlab.assistant.adapters.chatgpt.provider.analysis_provider', side_effect=AssertionError('No provider')),
                patch('quantlab.assistant.adapters.chatgpt.auth.OAuthCredentialReference', side_effect=AssertionError('No credentials')),
            ):
                plan, request = smoke._prepare_plan(paths, state, time.monotonic() + 10)
                self.assertEqual(validate_analysis_plan(plan), plan)
                self.assertEqual(validate_analysis_request(request), request)
                self.assertEqual(request['original_dataset']['path'], str(canonical_path(dataset_path)))
                self.assertEqual(request['campaign_reference'], campaign.name)
                with admission(paths) as owner:
                    launch = register_launch(paths, job_id='d' * 32, helper_nonce='e' * 32, approved_plan=plan, request=request, admission=owner)
                self.assertEqual(read_launch(paths, 'd' * 32), launch)
                if dataset_path != canonical_path(dataset_path):
                    with self.assertRaises(RuntimeSafetyError):
                        validate_analysis_request({**request, 'original_dataset': {'kind': 'local_dataset_file', 'path': str(dataset_path)}})
                for refused in ('//server/share/dataset.json', '\\\\?\\UNC\\server\\share\\dataset.json', '\\\\.\\C:\\dataset.json'):
                    with self.subTest(refused=refused), self.assertRaises(RuntimeSafetyError):
                        validate_analysis_request({**request, 'original_dataset': {'kind': 'local_dataset_file', 'path': refused}})

    def test_spawn_targets_static_and_no_test_imports_or_pid_reopen(self):
        text = Path(smoke.__file__).read_text()
        tree = ast.parse(text)
        targets = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertTrue({'_gated_worker', '_grandchild'} <= targets)
        imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(any(n.startswith('tests') for n in imports))
        self.assertNotIn('OpenProcess', text)
        self.assertNotIn('patch(', text)
        self.assertEqual(smoke.CAP_SECONDS, 40)
        self.assertEqual(smoke.PREP_SECONDS, 6)
        self.assertIn('validate_stop_receipt(paths, job_id) != launch', text)
        self.assertIn('os._exit(124)', text)


if __name__ == '__main__':
    unittest.main()

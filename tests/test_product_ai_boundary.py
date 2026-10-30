"""Offline removal regressions. No models, credentials or external requests."""

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ProductAIBoundaryTests(unittest.TestCase):
    def test_retired_product_sources_and_assets_are_absent(self):
        for name in (
            'quantlab/local_ai.py',
            'desktop_local_ai.py',
            'desktop_local_ai_runtime.py',
            'desktop_local_ai_smoke.py',
            'packaging/local_ai',
            'packaging/validate_local_ai.py',
        ):
            self.assertFalse((ROOT / name).exists(), name)
        for name in (
            'desktop.py',
            'desktop_app/shell/main_window.py',
            'desktop_app/features/settings/automatic_backup.py',
            'quantlab/desktop_runtime.py',
            'desktop_app/smoke/tls.py',
            'packaging/markauto.spec',
            'packaging/build_manifest.py',
        ):
            source = (ROOT / name).read_text(encoding='utf-8')
            for token in ('quantlab.local_ai', 'desktop_local_ai', 'local_ai_panel', 'ui_local_ai', 'packaging/local_ai', '--local-ai'):
                self.assertNotIn(token, source, name)

    def test_removed_job_and_provider_requests_fail_before_spawn(self):
        from quantlab.desktop_runtime import AppPaths, JobManager, RuntimeSafetyError

        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths(Path(temp) / 'workspace').ensure()
            jobs = JobManager(paths)
            before = sorted(str(p.relative_to(paths.root)) for p in paths.root.rglob('*'))
            with patch('quantlab.desktop_runtime.mp.get_context') as spawn:
                for action in ('download', 'install', 'serve', 'probe'):
                    with self.assertRaises(RuntimeSafetyError):
                        jobs.start('ui_local_ai', {'action': action, 'consent': True})
                for provider in ({}, None, [], {'mode': 'local'}, {'mode': 'compatible'}, {'mode': 'ollama'}, {'mode': 'paid_api'}):
                    with self.assertRaises(RuntimeSafetyError):
                        jobs.start('ui_campaign', {'provider': provider})
                spawn.assert_not_called()
            self.assertFalse(jobs.active)
            self.assertEqual(before, sorted(str(p.relative_to(paths.root)) for p in paths.root.rglob('*')))

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt required for host adapter')
    def test_removed_worker_dispatch_does_not_create_workspace(self):
        from desktop_app.shell.main_window import execute_ui_operation, campaign_generator
        from quantlab.desktop_runtime import AppPaths
        from quantlab.core import ValidationError

        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths(Path(temp) / 'unused-workspace')
            for provider in ({}, None, [], {'mode': 'local'}, {'mode': 'compatible'}):
                with self.assertRaises(ValidationError):
                    execute_ui_operation('ui_campaign', {'provider': provider}, paths)
                with self.assertRaises(ValidationError):
                    campaign_generator(paths, provider)
            self.assertFalse(paths.root.exists())

    def test_removed_cli_flags_refuse_before_user_workspace_access(self):
        import desktop

        with patch('quantlab.desktop_runtime.AppPaths.discover') as discover, contextlib.redirect_stderr(io.StringIO()):
            for flag in ('--local-ai-smoke', '--local-ai-model', '--local-ai-runtime-archive', '--local-ai-root'):
                with self.assertRaises(SystemExit) as caught:
                    desktop.main([flag, '/unused'])
                self.assertEqual(caught.exception.code, 2)
            discover.assert_not_called()

    def test_historical_validator_command_is_inert_even_with_arguments(self):
        from tools import validate_real_ai

        with (
            patch.object(validate_real_ai, 'verify_artifacts') as artifacts,
            patch.object(validate_real_ai, 'run_campaign') as campaign,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(validate_real_ai.main(['--model', '/unused/model.gguf']), 2)
            artifacts.assert_not_called()
            campaign.assert_not_called()
        self.assertNotIn('subprocess', validate_real_ai.__dict__)

    def test_cli_research_stays_fixture_only(self):
        # Existing CLI has no selectable network provider or implicit fallback.
        source = (ROOT / 'quantlab/__main__.py').read_text(encoding='utf-8')
        self.assertIn('generator=FixtureGenerator()', source)
        self.assertNotIn('CompatibleProvider', source)
        self.assertNotIn('HTTPTransport', source)

    def test_static_gate_has_no_local_runtime_subprocess_exception(self):
        from tools.quality_gate import python_findings

        for label in ('desktop_local_ai_runtime.py', 'desktop_app/shell/main_window.py'):
            self.assertTrue(python_findings('import subprocess\nsubprocess.Popen([],shell=False)\n', label, desktop=True))

    def test_ci_retains_tls_and_unrelated_acceptance_gates(self):
        source = (ROOT / '.github/workflows/windows-desktop.yml').read_text(encoding='utf-8')
        self.assertNotIn('validate_local_ai.py', source)
        for required in (
            'packaging/validate_tls.py',
            'tools/quality_gate.py --history',
            'pip_audit',
            'packaging/test_installer.ps1',
            'packaging/test_update_recovery.ps1',
            'packaging/clean_windows_kit.py',
            'packaging/wait_for_gates.py',
        ):
            self.assertIn(required, source)


class StandaloneTLSGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        spec = importlib.util.spec_from_file_location('standalone_tls_gate', ROOT / 'packaging/validate_tls.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.executable = self.root / 'MarkAuto.exe'
        self.executable.write_bytes(b'INERT')
        self.report = self.root / 'report.json'

    def test_cli_dispatches_tls_only_before_user_state_or_qt(self):
        import desktop

        with patch('desktop_app.smoke.tls.write_report', return_value=0) as write, patch('quantlab.desktop_runtime.AppPaths.discover') as discover:
            self.assertEqual(desktop.main(['--tls-smoke', str(self.report)]), 0)
        write.assert_called_once_with(self.report)
        discover.assert_not_called()
        with contextlib.redirect_stderr(io.StringIO()), patch('desktop_app.smoke.tls.write_report') as write:
            for args in (['--tls-smoke', 'relative.json'], ['--tls-smoke', str(self.report), '--smoke-test', str(self.root / 'smoke.json')]):
                with self.assertRaises(SystemExit):
                    desktop.main(args)
            write.assert_not_called()

    def test_gate_requires_fresh_bounded_valid_report(self):
        import json
        from tests.test_desktop_tls_smoke import report

        def launch(*args, **kwargs):
            self.report.write_text(json.dumps(report()))

        with patch.object(self.module.subprocess, 'run', side_effect=launch) as run:
            result = self.module.validate(self.executable, self.report)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(run.call_args.args[0], [str(self.executable), '--tls-smoke', str(self.report)])
        self.assertTrue(run.call_args.kwargs['check'])
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
        with patch.object(self.module.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                self.module.validate(self.executable, self.report)
            run.assert_not_called()

    def test_failed_or_oversized_proof_cannot_pass(self):
        for text in ('{"status":"failed"}', ' ' * 65537):
            with patch.object(self.module.subprocess, 'run', side_effect=lambda *a, **k: self.report.write_text(text)):
                with self.assertRaises(ValueError):
                    self.module.validate(self.executable, self.report)
            self.report.unlink()

    def test_tls_evidence_writer_preserves_existing_files_and_failure(self):
        import json
        import desktop_app.smoke.tls as tls

        failure = {'status': 'failed', 'scope': tls.SCOPE, 'error_category': 'validation'}
        with patch.object(tls, 'run', return_value=failure):
            self.assertEqual(tls.write_report(self.report), 1)
        self.assertEqual(json.loads(self.report.read_text()), failure)
        before = self.report.read_bytes()
        with patch.object(tls, 'run') as run:
            with self.assertRaises(ValueError):
                tls.write_report(self.report)
            run.assert_not_called()
        self.assertEqual(self.report.read_bytes(), before)

    def test_tls_paths_reject_relative_unc_symlink_and_hardlink(self):
        import os
        import desktop_app.smoke.tls as tls

        for path in ('relative', '//server/share/report'):
            with self.assertRaises(ValueError):
                tls.safe_path(path)
        for kind in ('symlink', 'hardlink'):
            linked = self.root / kind
            try:
                if kind == 'symlink':
                    linked.symlink_to(self.executable)
                else:
                    os.link(self.executable, linked)
            except (OSError, NotImplementedError):
                continue
            with self.assertRaises(ValueError):
                tls.safe_path(linked, file=True)
            linked.unlink()


if __name__ == '__main__':
    unittest.main()

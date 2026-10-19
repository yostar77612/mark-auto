"""Offline contracts for the isolated, bounded WFO storage observation job."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    '.github/workflows/quantlab.yml', 'tools/diagnose_wfo_storage.py',
    'tests/test_wfo_storage_diagnostic.py', 'tests/test_wfo_storage_ci.py',
    'tests/fixtures/wfo-storage-manifest.json', 'tests/fixtures/wfo-storage-smoke.json.gz',
    'tests/fixtures/wfo-storage-large.json.gz', 'docs/engineering/WFO_STORAGE_DIAGNOSTIC.md',
}


def job_text(workflow, name):
    match = re.search(r'(?ms)^  ' + re.escape(name) + r':\n.*?(?=^  [a-z][a-z0-9_-]*:\n|\Z)', workflow)
    if match is None:
        raise AssertionError('Missing job: ' + name)
    return match.group(0)


class WfoStorageWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / '.github/workflows/quantlab.yml').read_text(encoding='utf-8')
        cls.job = job_text(cls.workflow, 'wfo-storage-diagnostic')

    def test_separate_windows312_fixed_budget_and_pinned_actions(self):
        self.assertIn('runs-on: windows-latest', self.job)
        self.assertIn('timeout-minutes: 6', self.job)
        self.assertIn("python-version: '3.12'", self.job)
        self.assertIn('persist-credentials: false', self.job)
        actions = re.findall(r'uses: (\S+)', self.job)
        self.assertEqual(actions, [
            'actions/checkout@11d5960a326750d5838078e36cf38b85af677262',
            'actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065',
            'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'])
        self.assertNotIn('continue-on-error', self.job)
        self.assertNotIn('strategy:', self.job)
        self.assertNotIn('needs:', self.job)

    def test_existing_runtime_provisioning_precedes_measurement(self):
        provision = ('python tools/install_sqlite_runtime.py --destination build/sqlite-runtime '
                     '--report dist/validation/sqlite-runtime.json --github')
        self.assertEqual(self.job.count(provision), 1)
        command = ('python tools/diagnose_wfo_storage.py --runtime-root build/sqlite-runtime '
                   '--storage-root "$env:RUNNER_TEMP" --seconds 180 --fixture smoke '
                   '--report dist/validation/wfo-storage.json')
        self.assertEqual(self.job.count(command), 1)
        self.assertLess(self.job.index(provision), self.job.index(command))
        self.assertIn('shell: pwsh', self.job)
        self.assertIn('exit $LASTEXITCODE', self.job)
        self.assertIn("python -m unittest discover -s tests -p 'test_wfo_storage*.py' -v", self.job)
        for forbidden in ('--fixture large', 'pip install', 'Start-Job', 'Retry', '|| true'):
            self.assertNotIn(forbidden, self.job)

    def test_reports_always_retained_even_on_incomplete(self):
        upload = self.job.split('      - name: Preserve complete or incomplete', 1)[1]
        self.assertIn('if: always()', upload)
        self.assertIn('name: wfo-storage-windows312-diagnostic', upload)
        self.assertIn('dist/validation/wfo-storage.json', upload)
        self.assertIn('dist/validation/sqlite-runtime.json', upload)
        self.assertIn('if-no-files-found: error', upload)
        self.assertIn('retention-days: 7', upload)

    def test_product_jobs_and_workloads_remain_separate(self):
        offline = job_text(self.workflow, 'offline')
        self.assertIn('timeout-minutes: 15', offline)
        for version in ('3.11', '3.12'):
            self.assertIn("{os: windows-latest, python: '" + version + "', group: research}", offline)
            for shard in ('desktop', 'remaining'):
                self.assertIn("{os: windows-latest, python: '" + version +
                              "', group: core, shard: " + shard + '}', offline)
        aggregate = job_text(self.workflow, 'core-coverage')
        self.assertIn('name: offline (windows-latest, ${{ matrix.python }})', aggregate)
        self.assertIn('needs: [offline, ruff]', aggregate)
        self.assertIn('if: always()', aggregate)
        self.assertIn('timeout-minutes: 15', aggregate)
        self.assertIn('python tools/validate_core_shards.py', aggregate)
        self.assertIn("os.environ.get('OFFLINE_RESULT') == 'success'", aggregate)
        self.assertIn('python tools/run_test_group.py --group ${{ matrix.group }}', offline)
        for name in ('offline', 'ui', 'quality', 'security', 'guest-execution-diagnostic'):
            job = job_text(self.workflow, name)
            self.assertNotIn('diagnose_wfo_storage.py', job)
            self.assertNotIn('wfo-storage-diagnostic', job)

    def test_tool_supervisor_preserves_180_plus_10_second_bound(self):
        source = (ROOT / 'tools/diagnose_wfo_storage.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        supervisor = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'supervise')
        code = ast.get_source_segment(source, supervisor)
        self.assertIn('process.wait(timeout=args.seconds)', code)
        self.assertIn('process.wait(timeout=10)', code)
        self.assertIn('except subprocess.TimeoutExpired:', code)
        self.assertIn("status='INCOMPLETE'", code)
        self.assertIn('process.kill()', code)
        self.assertIn('1 <= args.seconds <= 180', source)
        self.assertIn("return 0 if report.get('status') == 'COMPLETE' else 2", code)

    def test_diagnostic_inputs_are_present_tracked_and_compilable(self):
        for name in REQUIRED:
            self.assertTrue((ROOT / name).is_file(), name)
            if name.endswith('.py'):
                compile((ROOT / name).read_text(encoding='utf-8'), name, 'exec')
        if (ROOT / '.git').exists():
            tracked = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines())
            self.assertFalse(REQUIRED - tracked, f'Diagnostic inputs absent from Git: {sorted(REQUIRED - tracked)}')

    @unittest.skipUnless(shutil.which('git'), 'Git checkout conversion test needs Git')
    def test_windows_crlf_checkout_preserves_archive_pins_and_reconstruction(self):
        spec = importlib.util.spec_from_file_location('wfo_storage_ci_probe', ROOT / 'tools/diagnose_wfo_storage.py')
        probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)
            git('init'); git('config', 'core.autocrlf', 'true')
            source = ROOT / 'tests/fixtures'
            names = ('wfo-storage-manifest.json', 'wfo-storage-smoke.json.gz', 'wfo-storage-large.json.gz')
            for name in names:
                (repo / name).write_bytes((source / name).read_bytes())
            git('add', '--', *names)
            for name in names:
                (repo / name).unlink()
            git('checkout-index', '-a', '-f')
            raw = (repo / names[0]).read_bytes()
            self.assertIn(b'\r\n', raw)  # Prove actual conversion, not a simulated read.
            manifest = json.loads(raw)
            for name in ('smoke', 'large'):
                self.assertEqual(hashlib.sha256((repo / manifest[name]['file']).read_bytes()).hexdigest(),
                                 manifest[name]['archive_sha256'])
            with patch.object(probe, 'FIXTURES', repo):
                for name, count in (('smoke', 63), ('large', 574)):
                    payloads, metadata = probe.load_stream(name)
                    self.assertEqual(len(payloads), count)
                    self.assertEqual(hashlib.sha256(''.join(payloads).encode('utf-8')).hexdigest(),
                                     metadata['stream_sha256'])


if __name__ == '__main__':
    unittest.main()

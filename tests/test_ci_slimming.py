"""Offline regressions for the PR-stage CI slimming (docs-only skip, filters, concurrency)."""

import tempfile
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from tools import ci_changes

ROOT = Path(__file__).resolve().parents[1]


def text(name):
    return (ROOT / '.github/workflows' / name).read_text(encoding='utf-8')


def header(name):
    return text(name).split('\njobs:\n', 1)[0]


def job_blocks(workflow):
    blocks = {}
    current = None
    for line in workflow.split('\njobs:\n', 1)[1].splitlines():
        if line.startswith('  ') and not line.startswith('   ') and line.rstrip().endswith(':'):
            current = line.strip()[:-1]
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return {name: '\n'.join(lines) for name, lines in blocks.items()}


class DocsOnlyClassifierTests(unittest.TestCase):
    def test_unreferenced_prose_is_docs_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'tests').mkdir()
            (root / 'tests/test_x.py').write_text("open('docs/read.md')", encoding='utf-8')
            self.assertTrue(ci_changes.docs_only(['docs/free.md', '.github/pull_request_template.md'], root))
            self.assertFalse(ci_changes.docs_only(['docs/read.md'], root))

    def test_anything_else_is_not_docs_only(self):
        for changed in (
            [],
            ['quantlab/core.py'],
            ['docs/free.md', 'tools/x.py'],
            ['docs/agent/PROJECT_STATE.md'],
            ['docs/adr/0001.md'],
            ['packaging/README.md'],
            ['docs/data.json'],
            ['packaging/build.ps1'],
            ['packaging/markauto.iss'],
            ['.github/workflows/quantlab.yml'],
            ['.github/workflows/windows-desktop.yml'],
            ['tools/layer_map.json'],
            ['requirements-desktop.txt'],
            ['requirements-qt-ci.lock'],
            ['desktop_app/shell/main_window.py'],
            ['trading_runtime.py'],
        ):
            self.assertFalse(ci_changes.docs_only(changed, ROOT), changed)

    def test_real_repo_files_read_by_tests_are_never_skipped(self):
        for path in ('README.md', 'docs/GLOSSARY.md', 'docs/agent/ACCEPTANCE.json'):
            self.assertFalse(ci_changes.docs_only([path], ROOT), path)


class WorkflowShapeTests(unittest.TestCase):
    def test_actual_quantlab_aggregate_accepts_only_applicable_success(self):
        gate = job_blocks(text('quantlab.yml'))['gate']
        names = gate.split('needs: [', 1)[1].split(']', 1)[0].split(', ')
        script = textwrap.dedent(gate.split('        run: |\n', 1)[1])
        self.assertTrue(script.startswith("python3 - <<'PY'\n"))
        program = script.split('\n', 1)[1].rsplit('\nPY', 1)[0]
        for docs_only, changed_result, expected in (
            (True, None, 0),
            (False, None, 0),
            (True, ('ruff', 'failure'), 1),
            (True, ('changes', 'failure'), 1),
            (True, ('offline', 'failure'), 1),
            (True, ('offline', 'cancelled'), 1),
            (False, ('offline', 'skipped'), 1),
            (False, ('ui', 'failure'), 1),
        ):
            needs = {name: {'result': 'skipped' if docs_only and name not in ('changes', 'ruff', 'quality') else 'success'} for name in names}
            needs['changes']['outputs'] = {'code': 'false' if docs_only else 'true'}
            if changed_result is not None:
                needs[changed_result[0]]['result'] = changed_result[1]
            with self.subTest(docs_only=docs_only, changed_result=changed_result):
                result = subprocess.run(
                    [sys.executable, '-c', program], env={**os.environ, 'NEEDS': json.dumps(needs)}, capture_output=True, text=True, timeout=10
                )
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_concurrency_cancels_only_pull_requests(self):
        for name in ('quantlab.yml', 'windows-desktop.yml'):
            head = header(name)
            self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", head)
            self.assertIn('github.event.pull_request.number || github.ref', head)
            self.assertNotIn('cancel-in-progress: true', head)

    def test_installer_pr_filter_and_unfiltered_main_push(self):
        pull_request, rest = header('windows-desktop.yml').split('  push:\n', 1)
        for required in (
            'packaging/**',
            'tests/test_windows_recovery_feasibility.py',
            'requirements*.lock',
            'requirements*.txt',
            'desktop_chatgpt_dependency_manifest.json',
            "'*.spec'",
            "'*.iss'",
            'tools/make_icon.py',
            '.github/workflows/windows-desktop.yml',
        ):
            self.assertIn(required, pull_request)
        self.assertNotIn('paths:', rest)
        self.assertIn('branches: [main]', rest)
        self.assertIn("tags: ['desktop-v*']", rest)
        self.assertIn('workflow_dispatch:', rest)
        installer = job_blocks(text('windows-desktop.yml'))
        self.assertNotIn('changes', installer)
        self.assertNotIn('needs:', installer['quality'])
        self.assertFalse(any(line.startswith('    if:') for line in installer['quality'].splitlines()))
        self.assertIn('needs: quality', installer['regression'])
        self.assertIn('needs: [quality, regression]', installer['build'])
        self.assertIn('needs: [build, quality]', installer['release'])
        self.assertNotIn('continue-on-error', text('windows-desktop.yml'))

    def test_hosted_windows_requires_real_symlinks_instead_of_skipping_security_cases(self):
        command = 'run: python -c "from tests.native_capabilities import symlinks_available; assert symlinks_available(), '
        for workflow, job in (('quantlab.yml', 'offline'), ('windows-desktop.yml', 'quality')):
            block = job_blocks(text(workflow))[job]
            self.assertIn(command, block)
            self.assertNotIn('continue-on-error', block)

    def test_every_heavy_job_is_gated_and_aggregate_covers_all(self):
        jobs = job_blocks(text('quantlab.yml'))
        always = {'changes', 'ruff', 'quality', 'gate', 'guest-execution-diagnostic'}
        for name, block in jobs.items():
            if name not in always:
                self.assertIn("needs.changes.outputs.code == 'true'", block, name)
        gate = jobs['gate']
        needs = gate.split('needs: [', 1)[1].split(']', 1)[0].split(', ')
        self.assertEqual(set(needs), set(jobs) - {'gate', 'guest-execution-diagnostic'})
        self.assertIn('    if: always()\n', gate)
        self.assertIn('name: Quantlab gates complete', gate)
        self.assertIn('name not in always', gate)


if __name__ == '__main__':
    unittest.main()

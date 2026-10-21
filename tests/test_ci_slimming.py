"""Offline regressions for the PR-stage CI slimming (docs-only skip, filters, concurrency)."""

import tempfile
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
        ):
            self.assertFalse(ci_changes.docs_only(changed, ROOT), changed)

    def test_real_repo_files_read_by_tests_are_never_skipped(self):
        for path in ('README.md', 'docs/GLOSSARY.md', 'docs/agent/ACCEPTANCE.json'):
            self.assertFalse(ci_changes.docs_only([path], ROOT), path)


class WorkflowShapeTests(unittest.TestCase):
    def test_concurrency_cancels_only_pull_requests(self):
        for name in ('quantlab.yml', 'windows-desktop.yml'):
            head = header(name)
            self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", head)
            self.assertIn('github.event.pull_request.number || github.ref', head)
            self.assertNotIn('cancel-in-progress: true', head)

    def test_installer_pr_filter_and_unfiltered_main_push(self):
        pull_request, rest = header('windows-desktop.yml').split('  push:\n', 1)
        for required in ('packaging/**', 'requirements*.lock', 'desktop_chatgpt_dependency_manifest.json', "'*.spec'", "'*.iss'", 'tools/make_icon.py'):
            self.assertIn(required, pull_request)
        self.assertNotIn('paths:', rest)
        self.assertIn('branches: [main]', rest)
        self.assertIn("tags: ['desktop-v*']", rest)
        self.assertIn('workflow_dispatch:', rest)

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

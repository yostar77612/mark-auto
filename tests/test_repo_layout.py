"""Cheap, offline layout and archived-code boundary regressions."""

import ast
import subprocess
from fnmatch import fnmatchcase  # noqa: F401 -- preserve pre-format import
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.quality_gate import python_findings, scan

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'archives/legacy_autotrading'
# Derived from the post-move git ls-files top level; additions need review.
ALLOWED_FILES = {
    '.gitattributes',
    '.gitignore',
    'LICENSE',
    'README.md',
    'pyproject.toml',
    'requirements-desktop.lock',
    'requirements-desktop.txt',
    'requirements-qt-ci.lock',
    'requirements-ui.lock',
    'requirements-ui.txt',
    'requirements-ruff.lock',
    'research_app.py',
    'desktop.py',
    'desktop_accessibility.py',
    'desktop_automatic_backup.py',
    'desktop_charts.py',
    'desktop_chatgpt_auth.py',
    'desktop_chatgpt_dependency_manifest.json',
    'desktop_chatgpt_provider.py',
    'desktop_chatgpt_ui.py',
    'desktop_expiry_inputs.py',
    'desktop_forms.py',
    'desktop_help.py',
    'desktop_icon.py',
    'desktop_market.py',
    'desktop_presentation.py',
    'desktop_recovery_smoke.py',
    'desktop_strings.py',
    'desktop_theme.py',
    'desktop_timeinput.py',
    'desktop_tls_smoke.py',
    'desktop_ui.py',
    'desktop_ui_polish.py',
    'desktop_walk_forward.py',
}
ALLOWED_DIRECTORIES = {
    '.github',
    '.streamlit',
    'archives',
    'desktop_pages',
    'docs',
    'examples',
    'packaging',
    'quantlab',
    'tests',
    'tools',
}
# User-local files and normal ignored development/build output are not project
# layout. Never inspect their contents or require their presence in CI.
IGNORED_LOCAL_NAMES = {
    '.claude',
    'AGENTS.md',
    'CLAUDE.md',
    '.git',
    '.gitnexus',
    '.venv',
    '.runtime-sqlite',
    '__pycache__',
    'build',
    'dist',
    '.pytest_cache',
    '.ruff_cache',
}
IGNORED_LOCAL_PATTERNS = ('.tmp*', '.t*-work', '*.log', '*.egg-info')


class RepoLayoutTests(unittest.TestCase):
    def test_exact_root_layout(self):
        # Judge the TRACKED layout: other tests and tools legitimately leave untracked artifacts
        # (e.g. qt-install-report.json) in the working directory of a CI job.
        listing = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        tracked = [name for name in listing.split(chr(0)) if name]
        files = {name for name in tracked if '/' not in name}
        directories = {name.split('/', 1)[0] for name in tracked if '/' in name}
        self.assertEqual(files, ALLOWED_FILES)
        self.assertEqual(directories, ALLOWED_DIRECTORIES)

    def test_legacy_archive_and_license(self):
        for name in ('trader', 'gui.py', 'run.py', 'TelegramBot.md'):
            self.assertFalse((ROOT / name).exists(), name)
            self.assertTrue((ARCHIVE / name).exists(), name)
        self.assertTrue((ARCHIVE / 'requirements.txt').is_file())
        self.assertTrue((ROOT / 'LICENSE').is_file())
        self.assertIn('](archives/legacy_autotrading/)', (ROOT / 'README.md').read_text(encoding='utf-8'))
        spec = ast.parse((ROOT / 'packaging/markauto.spec').read_text(encoding='utf-8'))
        analysis = next(n for n in ast.walk(spec) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'Analysis')
        excluded = ast.literal_eval(next(k.value for k in analysis.keywords if k.arg == 'excludes'))
        self.assertTrue({'trader', 'archives', 'archives.legacy_autotrading'} <= set(excluded))

    def test_product_never_imports_archived_modules(self):
        paths = list(ROOT.glob('*.py'))
        for directory in ('quantlab', 'desktop_pages'):
            paths.extend((ROOT / directory).rglob('*.py'))
        for path in paths:
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    modules = [node.module or '']
                else:
                    continue
                self.assertFalse({'trader', 'gui', 'run', 'archives'}.intersection(name.split('.')[0] for name in modules), str(path))

    def test_gate_scans_archive_and_rejects_reenabled_startup_or_orders(self):
        name = 'archives/legacy_autotrading/trader/__init__.py'
        root = Path('/synthetic-repository')
        with patch('tools.quality_gate.git', return_value=(name + '\0').encode()), patch.object(Path, 'is_file', return_value=True):
            for source in ('import shioaji', 'raise RuntimeError()\nAPI.place_order()'):
                with patch.object(Path, 'read_bytes', return_value=source.encode()):
                    self.assertTrue(scan(root))
            with patch.object(Path, 'read_bytes', return_value=b'raise RuntimeError()'):
                self.assertEqual(scan(root), [])

    def test_archive_import_cannot_bypass_product_boundary(self):
        for source in ('import archives.legacy_autotrading.trader', 'from archives.legacy_autotrading import gui'):
            self.assertTrue(python_findings(source, 'desktop_ui.py', desktop=True))
            self.assertTrue(python_findings(source, 'quantlab/new.py', research=True))


if __name__ == '__main__':
    unittest.main()

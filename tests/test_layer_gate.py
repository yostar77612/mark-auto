"""Spec 3.1 boundaries, inventory parity, shrink-only debt and CI discovery."""

from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from tools import check_layers as gate
from tools import run_test_group as groups

ROOT = Path(__file__).resolve().parents[1]
# Frozen R1 baseline, independent of the live allowlist; never regenerate this
# when removing debt. Moving a source must remove its old exemption and fix it.
BASELINE_COUNT = 92
BASELINE = frozenset(
    tuple(line.split("|"))
    for line in """
desktop_automatic_backup.py|quantlab.analysis_recovery|presentation-to-infrastructure
desktop_automatic_backup.py|quantlab.automatic_backup|presentation-to-infrastructure
desktop_capital_scenario.py|desktop_pages.job_progress|application-to-presentation
desktop_capital_scenario.py|desktop_walk_forward|application-to-presentation
desktop_capital_scenario.py|quantlab.desktop_feedback|application-to-presentation
desktop_charts.py|quantlab.chart_drawings|presentation-to-infrastructure
desktop_chatgpt_auth.py|quantlab.desktop_runtime|infrastructure-to-application
desktop_chatgpt_provider.py|quantlab.research|infrastructure-to-application
desktop_chatgpt_provider.py|quantlab.research_analysis|infrastructure-to-application
desktop_chatgpt_ui.py|desktop_chatgpt_auth|presentation-to-infrastructure
desktop_chatgpt_ui.py|desktop_chatgpt_provider|presentation-to-infrastructure
desktop_expiry_inputs.py|quantlab.taifex_expiries|presentation-to-infrastructure
desktop_forms.py|quantlab.__main__|presentation-to-composition
desktop_forms.py|quantlab.reporting|presentation-to-infrastructure
desktop_market.py|quantlab.market_history|presentation-to-infrastructure
desktop_market.py|quantlab.reporting|presentation-to-infrastructure
desktop_market_workspace.py|desktop_market_layout|presentation-to-infrastructure
desktop_pages/assistant_completion.py|quantlab.agent_skills|presentation-to-infrastructure
desktop_pages/assistant_runtime.py|desktop_chatgpt_auth|application-to-infrastructure
desktop_pages/assistant_runtime.py|desktop_chatgpt_provider|application-to-infrastructure
desktop_pages/assistant_runtime.py|desktop_pages.assistant_models|application-to-presentation
desktop_pages/backtest.py|quantlab.__main__|presentation-to-composition
desktop_pages/backtest.py|quantlab.reporting|presentation-to-infrastructure
desktop_pages/backtest.py|quantlab.strict_json|presentation-to-infrastructure
desktop_pages/backup_inspection.py|quantlab.backup_inspection|presentation-to-infrastructure
desktop_pages/compare.py|quantlab.analysis_recovery|presentation-to-infrastructure
desktop_pages/compare.py|quantlab.reporting|presentation-to-infrastructure
desktop_pages/connection_test.py|desktop_chatgpt_auth|presentation-to-infrastructure
desktop_pages/connection_test.py|desktop_chatgpt_provider|presentation-to-infrastructure
desktop_pages/maintenance.py|quantlab.payload_cleanup|presentation-to-infrastructure
desktop_pages/maintenance.py|quantlab.update_check|presentation-to-infrastructure
desktop_pages/market.py|quantlab.chart_drawings|presentation-to-infrastructure
desktop_pages/market.py|quantlab.market_history|presentation-to-infrastructure
desktop_pages/market.py|quantlab.market_providers|presentation-to-infrastructure
desktop_pages/market.py|quantlab.reporting|presentation-to-infrastructure
desktop_pages/paper.py|quantlab.reporting|presentation-to-infrastructure
desktop_pages/paper_layout.py|quantlab.strict_json|presentation-to-infrastructure
desktop_pages/paper_readiness.py|quantlab.reporting|presentation-to-infrastructure
desktop_pages/paper_tabs.py|quantlab.strict_json|presentation-to-infrastructure
desktop_pages/paper_tabs.py|shiboken6|presentation-to-external-sdk
desktop_pages/preferences.py|quantlab.runtime_support|presentation-to-infrastructure
desktop_pages/quick_start.py|quantlab.reporting|presentation-to-infrastructure
desktop_pages/result_widgets.py|shiboken6|presentation-to-external-sdk
desktop_pages/settings.py|quantlab.__main__|presentation-to-composition
desktop_pages/strategy.py|quantlab.__main__|presentation-to-composition
desktop_pages/strategy.py|quantlab.reporting|presentation-to-infrastructure
desktop_pages/views.py|quantlab.reporting|presentation-to-infrastructure
desktop_pages/widgets.py|quantlab.strict_json|presentation-to-infrastructure
desktop_presentation.py|quantlab.reporting|presentation-to-infrastructure
desktop_ui.py|desktop_chatgpt_auth|presentation-to-infrastructure
desktop_ui.py|desktop_chatgpt_provider|presentation-to-infrastructure
desktop_ui.py|quantlab.__main__|presentation-to-composition
desktop_ui.py|quantlab.analysis_recovery|presentation-to-infrastructure
desktop_ui.py|quantlab.data|presentation-to-infrastructure
desktop_ui.py|quantlab.downloads|presentation-to-infrastructure
desktop_ui.py|quantlab.idea_search|presentation-to-infrastructure
desktop_ui.py|quantlab.manual_exchange|presentation-to-infrastructure
desktop_ui.py|quantlab.market_history|presentation-to-infrastructure
desktop_ui.py|quantlab.market_providers|presentation-to-infrastructure
desktop_ui.py|quantlab.reporting|presentation-to-infrastructure
desktop_ui.py|quantlab.runtime_support|presentation-to-infrastructure
quantlab/agent_read_tools.py|quantlab.reporting|application-to-infrastructure
quantlab/agent_skills.py|quantlab.agent_tools|infrastructure-to-application
quantlab/analysis_contracts.py|quantlab.research|domain-to-application
quantlab/automatic_backup.py|quantlab.desktop_runtime|infrastructure-to-application
quantlab/backup_inspection.py|quantlab.desktop_runtime|infrastructure-to-application
quantlab/data_gap_report.py|quantlab.data|application-to-infrastructure
quantlab/data_gap_report.py|quantlab.desktop_errors|application-to-presentation
quantlab/desktop_errors.py|quantlab.runtime_support|presentation-to-infrastructure
quantlab/desktop_runtime.py|quantlab.__main__|application-to-composition
quantlab/desktop_runtime.py|quantlab.analysis_recovery|application-to-infrastructure
quantlab/desktop_runtime.py|quantlab.analysis_recovery_windows|application-to-infrastructure
quantlab/desktop_runtime.py|quantlab.desktop_errors|application-to-presentation
quantlab/desktop_runtime.py|quantlab.runtime_support|application-to-infrastructure
quantlab/diagnostics.py|quantlab.desktop_feedback|application-to-presentation
quantlab/download_import.py|quantlab.data|application-to-infrastructure
quantlab/download_import.py|quantlab.downloads|application-to-infrastructure
quantlab/download_import.py|quantlab.reporting|application-to-infrastructure
quantlab/download_import.py|quantlab.runtime_support|application-to-infrastructure
quantlab/idea_research.py|quantlab.idea_search|application-to-infrastructure
quantlab/idea_research.py|quantlab.reporting|application-to-infrastructure
quantlab/idea_research.py|quantlab.response_output|application-to-infrastructure
quantlab/idea_research.py|quantlab.web_fetch|application-to-infrastructure
quantlab/manual_exchange.py|quantlab.research|infrastructure-to-application
quantlab/paper_replay.py|quantlab.data|application-to-infrastructure
quantlab/provider.py|quantlab.research|infrastructure-to-application
quantlab/reporting.py|quantlab.research_analysis|infrastructure-to-application
quantlab/research.py|quantlab.runtime_support|application-to-infrastructure
quantlab/research_analysis.py|quantlab.analysis_recovery|application-to-infrastructure
quantlab/saved_candidate_pool.py|quantlab.data|application-to-infrastructure
quantlab/walk_forward.py|quantlab.data|application-to-infrastructure
quantlab/walk_forward.py|quantlab.runtime_support|application-to-infrastructure
""".strip().splitlines()
)


def assert_shrink_only(case, entries):
    keys = {gate.allowlist_key(entry) for entry in entries}
    case.assertEqual(len(entries), len(keys), 'Duplicate allowlist entries')
    case.assertLessEqual(len(entries), BASELINE_COUNT)
    case.assertLessEqual(keys, BASELINE, 'Allowlist additions are forbidden')


@contextmanager
def fixture_repository():
    # Inherit the test runner's directory ACL (also works in Windows sandboxes).
    parent = Path(tempfile.gettempdir()).resolve()
    root = parent / ('layer-gate-' + uuid4().hex)
    root.mkdir()
    try:
        yield root
    finally:
        assert root.resolve().parent == parent and root.name.startswith('layer-gate-')
        shutil.rmtree(root, onerror=remove_readonly)


def remove_readonly(function, path, error):
    # Git object files are read-only on Windows.
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    function(path)


class LayerGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = gate.load_map(ROOT / 'tools/layer_map.json')
        cls.modules = gate.module_index(gate.tracked_sources(ROOT))

    def check(self, source, path):
        return gate.check_source(source, path, self.mapping, self.modules)

    def test_every_forbidden_layer_edge(self):
        for path, source, rule in (
            ('quantlab/core.py', 'import PySide6.QtCore', 'domain-to-pyside6'),
            ('quantlab/core.py', 'import shioaji', 'domain-to-external-sdk'),
            ('quantlab/core.py', 'import quantlab.data', 'domain-to-infrastructure'),
            ('quantlab/core.py', 'from . import research', 'domain-to-application'),
            ('quantlab/core.py', 'import desktop_forms', 'domain-to-presentation'),
            ('quantlab/research.py', 'from .data import load_csv', 'application-to-infrastructure'),
            ('quantlab/research.py', 'import PySide6', 'application-to-pyside6'),
            ('quantlab/research.py', 'import desktop_forms', 'application-to-presentation'),
            ('quantlab/research.py', 'import shioaji', 'application-to-external-sdk'),
            ('quantlab/data.py', 'import desktop_forms', 'infrastructure-to-presentation'),
            ('quantlab/data.py', 'from . import research', 'infrastructure-to-application'),
            ('desktop_forms.py', 'import shioaji', 'presentation-to-external-sdk'),
            ('desktop_forms.py', 'from quantlab import data', 'presentation-to-infrastructure'),
            ('desktop_forms.py', 'import desktop', 'presentation-to-composition'),
            ('desktop_forms.py', 'from tools import quality_gate', 'presentation-to-tooling'),
            ('quantlab/data.py', 'import tools', 'infrastructure-to-tooling'),
            ('desktop_strings.py', 'import PySide6', 'shared-to-pyside6'),
            ('desktop_strings.py', 'import shioaji', 'shared-to-external-sdk'),
        ):
            with self.subTest(path=path, source=source):
                findings = self.check(source, path)
                self.assertEqual([item.rule for item in findings], [rule])
                self.assertEqual(findings[0].line, 1)
        for target, layer in (
            ('quantlab.core', 'domain'),
            ('quantlab.research', 'application'),
            ('quantlab.data', 'infrastructure'),
            ('desktop_forms', 'presentation'),
            ('desktop', 'composition'),
            ('tools.quality_gate', 'tooling'),
        ):
            with self.subTest(shared_target=target):
                self.assertEqual(self.check(f'import {target}', 'desktop_strings.py')[0].rule, f'shared-to-{layer}')

    def test_allowed_dependencies_ports_and_composition(self):
        for path, source in (
            ('quantlab/core.py', 'import decimal\nfrom .errors import AppError'),
            ('quantlab/research.py', 'from .core import Bar'),
            ('quantlab/data.py', 'import shioaji\nfrom quantlab.trading.ports import broker'),
            ('desktop_forms.py', 'from PySide6.QtCore import QObject\nfrom quantlab import research'),
            ('desktop_strings.py', 'import json\nfrom quantlab import errors'),
            ('desktop.py', 'import desktop_forms\nimport quantlab.data\nfrom tools import quality_gate'),
            ('tools/new_tool.py', 'import desktop_forms\nimport shioaji'),
        ):
            with self.subTest(path=path, source=source):
                self.assertEqual(self.check(source, path), ())

    def test_relative_alias_star_conditional_and_function_local_imports(self):
        for source, target in (
            ('from ..adapters import simulated as adapter', 'quantlab.trading.adapters.simulated'),
            ('from ..adapters.simulated import *', 'quantlab.trading.adapters.simulated'),
            ('import quantlab.data as storage', 'quantlab.data'),
            ('def work():\n    from quantlab import data', 'quantlab.data'),
            ('from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import quantlab.data', 'quantlab.data'),
        ):
            with self.subTest(source=source):
                findings = self.check(source, 'quantlab/trading/domain/new.py')
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0].target, target)
                self.assertEqual(findings[0].rule, 'domain-to-infrastructure')

    def test_unassigned_sources_and_targets_fail(self):
        for path in ('new_module.py', 'quantlab/new_module.py'):
            with self.subTest(path=path):
                self.assertEqual(self.check('import json', path)[0].rule, 'unassigned-file')
        modules = {**self.modules, 'quantlab.new_module': 'quantlab/new_module.py'}
        self.assertEqual(gate.check_source('from . import new_module', 'quantlab/core.py', self.mapping, modules)[0].rule, 'unassigned-target')

    def test_inventory_assignments_match_exactly(self):
        text = (ROOT / 'docs/analysis/08_REFACTOR_INVENTORY.md').read_text(encoding='utf-8')
        section = text.split('## 2 ')[1].split('## 3 ')[0]
        rows = dict(re.findall(r'^\| `([^`]+\.py)` \| \d+ \| (\w+) \|', section, re.M))
        self.assertTrue(rows)
        self.assertLessEqual(set(gate.tracked_sources(ROOT)), rows.keys())
        for path, layer in rows.items():
            with self.subTest(path=path):
                self.assertEqual(gate.layer_for(path, self.mapping), layer)

    def test_allowlist_is_shrink_only(self):
        entries = json.loads((ROOT / 'tools/layer_allowlist.json').read_text(encoding='utf-8'))
        self.assertEqual(len(BASELINE), BASELINE_COUNT)
        assert_shrink_only(self, entries)

    def test_fake_addition_and_same_count_replacement_fail_baseline(self):
        entries = json.loads((ROOT / 'tools/layer_allowlist.json').read_text(encoding='utf-8'))
        fake = dict(path='fake.py', target='shioaji', rule='domain-to-external-sdk', justification='fake')
        for altered in (entries + [fake], [*entries[1:], fake]):
            with self.subTest(count=len(altered)), self.assertRaises(AssertionError):
                assert_shrink_only(self, altered)
        assert_shrink_only(self, entries[:-1])

    def test_line_independent_allowance_and_stale_debt(self):
        entry = dict(path='quantlab/core.py', target='quantlab.data', rule='domain-to-infrastructure', justification='existing debt')
        for source in ('import quantlab.data', '\n\nfrom .data import load_csv', 'import quantlab.data\nimport quantlab.data'):
            with self.subTest(source=source):
                self.assertEqual(gate.apply_allowlist(self.check(source, entry['path']), [entry]), ())
        stale = gate.apply_allowlist((), [entry])
        self.assertEqual(stale[0].rule, 'stale-allowlist-entry')
        self.assertEqual(stale[0].line, 1)
        self.assertTrue(gate.apply_allowlist((), [entry, entry]))
        self.assertTrue(gate.apply_allowlist((), [{**entry, 'justification': ''}]))

    def test_repo_scan_is_clean(self):
        self.assertEqual(gate.scan(ROOT), ())

    def test_cli_injected_import_unassigned_and_stale_entries_exit_nonzero(self):
        with fixture_repository() as root:
            (root / 'tools').mkdir()
            (root / 'quantlab').mkdir()
            (root / 'tools/layer_map.json').write_text(json.dumps(self.mapping), encoding='utf-8')
            (root / 'tools/layer_allowlist.json').write_text('[]', encoding='utf-8')
            source = root / 'quantlab/core.py'
            source.write_text('import json\n', encoding='utf-8')
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, capture_output=True)
            command = [sys.executable, str(ROOT / 'tools/check_layers.py'), '--root', str(root)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            source.write_text('import json\nimport shioaji\n', encoding='utf-8')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('quantlab/core.py:2: domain-to-external-sdk: shioaji', result.stdout)
            source.write_text('import json\n', encoding='utf-8')
            entry = dict(path='quantlab/core.py', target='shioaji', rule='domain-to-external-sdk', justification='old debt')
            (root / 'tools/layer_allowlist.json').write_text(json.dumps([entry]), encoding='utf-8')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('quantlab/core.py:1: stale-allowlist-entry', result.stdout)
            (root / 'new.py').write_text('import json', encoding='utf-8')
            subprocess.run(['git', '-C', str(root), 'add', 'new.py'], check=True, capture_output=True)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('new.py:1: unassigned-file', result.stdout)

    def test_scan_scope_and_syntax_failures(self):
        with patch.object(gate, 'git', return_value=b'quantlab/core.py\0tests/test_x.py\0archives/old.py\0tools/new.py\0'):
            self.assertEqual(gate.tracked_sources(ROOT), ('quantlab/core.py', 'tools/new.py'))
        self.assertEqual(self.check('def broken(', 'quantlab/core.py')[0].rule, 'invalid-syntax')
        with patch.object(gate, 'tracked_sources', return_value=()):
            self.assertEqual(gate.scan(ROOT)[0].rule, 'empty-source-scope')
        with patch.object(gate, 'tracked_sources', return_value=('missing.py',)):
            self.assertEqual(gate.scan(ROOT, self.mapping, [])[0].rule, 'tracked-file-missing')
        with patch.object(gate, 'scan', side_effect=ValueError), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(gate.main([]), 1)
            self.assertIn('layer-scan-failed', output.getvalue())

    def test_discovered_tests_enter_existing_core_groups(self):
        loader = unittest.TestLoader()
        suite = loader.discover(str(ROOT / 'tests'), pattern='test_layer_gate.py')
        self.assertEqual(loader.errors, [])
        expected = {case.id() for case in groups.cases(suite)}
        self.assertTrue(expected)
        research = type('ResearchSentinel', (unittest.TestCase,), {'__module__': 'test_research', 'runTest': lambda self: None})()
        partitions = groups.partition(unittest.TestSuite([suite, research]))
        self.assertEqual({case.id() for case in groups.cases(partitions['core'])}, expected)
        self.assertEqual(groups.core_shard_for_module('test_layer_gate'), 'remaining')
        self.assertEqual(groups.linux_core_slice_for_module('test_layer_gate'), 'paper-remaining')


if __name__ == '__main__':
    unittest.main()

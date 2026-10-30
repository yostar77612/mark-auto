"""Spec 3.1 boundaries, inventory parity, shrink-only debt and CI discovery."""

from contextlib import contextmanager, redirect_stdout
import io
import hashlib
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
# when removing debt. Approved relocations preserve these original identities.
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
            ('quantlab/core.py', 'import desktop_app.components.forms', 'domain-to-presentation'),
            ('quantlab/research.py', 'from .data import load_csv', 'application-to-infrastructure'),
            ('quantlab/research.py', 'import PySide6', 'application-to-pyside6'),
            ('quantlab/research.py', 'import desktop_app.components.forms', 'application-to-presentation'),
            ('quantlab/research.py', 'import shioaji', 'application-to-external-sdk'),
            ('quantlab/data.py', 'import desktop_app.components.forms', 'infrastructure-to-presentation'),
            ('quantlab/data.py', 'from . import research', 'infrastructure-to-application'),
            ('desktop_app/components/forms.py', 'import shioaji', 'presentation-to-external-sdk'),
            ('desktop_app/components/forms.py', 'from quantlab import data', 'presentation-to-infrastructure'),
            ('desktop_app/components/forms.py', 'import desktop', 'presentation-to-composition'),
            ('desktop_app/components/forms.py', 'from tools import quality_gate', 'presentation-to-tooling'),
            ('quantlab/data.py', 'import tools', 'infrastructure-to-tooling'),
            ('desktop_app/strings/catalog.py', 'import PySide6', 'shared-to-pyside6'),
            ('desktop_app/strings/catalog.py', 'import shioaji', 'shared-to-external-sdk'),
        ):
            with self.subTest(path=path, source=source):
                findings = self.check(source, path)
                self.assertEqual([item.rule for item in findings], [rule])
                self.assertEqual(findings[0].line, 1)
        for target, layer in (
            ('quantlab.core', 'domain'),
            ('quantlab.research', 'application'),
            ('quantlab.data', 'infrastructure'),
            ('desktop_app.components.forms', 'presentation'),
            ('desktop', 'composition'),
            ('tools.quality_gate', 'tooling'),
        ):
            with self.subTest(shared_target=target):
                self.assertEqual(self.check(f'import {target}', 'desktop_app/strings/catalog.py')[0].rule, f'shared-to-{layer}')

    def test_allowed_dependencies_ports_and_composition(self):
        for path, source in (
            ('quantlab/core.py', 'import decimal\nfrom .errors import AppError'),
            ('quantlab/research.py', 'from .core import Bar'),
            ('quantlab/data.py', 'import shioaji\nfrom quantlab.trading.ports import broker'),
            ('desktop_app/components/forms.py', 'from PySide6.QtCore import QObject\nfrom quantlab import research'),
            ('desktop_app/strings/catalog.py', 'import json\nfrom quantlab import errors'),
            ('desktop.py', 'import desktop_app.components.forms\nimport quantlab.data\nfrom tools import quality_gate'),
            ('tools/new_tool.py', 'import desktop_app.components.forms\nimport shioaji'),
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
        relocations = json.loads((ROOT / 'tools/layer_relocations.json').read_text(encoding='utf-8'))
        inverse = {new: old for old, new in relocations.items()}
        metadata = {
            'quantlab/shared/__init__.py': 'shared',
            'quantlab/shared/runtime_errors.py': 'shared',
            'tools/refactor/extract_runtime_error.py': 'tooling',
            "quantlab/assistant/adapters/chatgpt/vault.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/identity.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/loopback.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/account_summary.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/account_paths.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/response_stream.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/transport.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/provenance.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/account_store.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/resolution_audit.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/unknown_reconciliation.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/finished_reconciliation.py": "infrastructure",
            "quantlab/assistant/adapters/chatgpt/campaign_receipts.py": "infrastructure",
            "quantlab/assistant/domain/auth_protocol.py": "domain",
            "quantlab/assistant/domain/auth_tokens.py": "domain",
            "quantlab/assistant/domain/plan_protocol.py": "domain",
            "quantlab/assistant/domain/source_components.py": "domain",
            "quantlab/assistant/ports/auth.py": "application",
            "quantlab/research_core/domain/receipts.py": "domain",
            "quantlab/assistant/domain/__init__.py": "domain",
            "quantlab/assistant/ports/__init__.py": "application",
            "quantlab/research_core/domain/__init__.py": "domain",
            "tools/refactor/split_core_assistant.py": "tooling",
            "tools/refactor/split_core_profile.py": "tooling",
            "tools/refactor/split_core_slice1_references.py": "tooling",
            "tools/refactor/split_core_test_paths.py": "tooling",
            "tools/refactor/split_core_lock_paths.py": "tooling",
            'desktop_app/smoke/__init__.py': 'tooling',
            'desktop_app/features/trading/__init__.py': 'presentation',
            'desktop_app/shell/__init__.py': 'presentation',
            'desktop_app/__init__.py': 'presentation',
            'desktop_app/features/settings/__init__.py': 'presentation',
            'desktop_app/features/__init__.py': 'presentation',
            'desktop_app/features/capital_scenario/__init__.py': 'presentation',
            'desktop_app/features/market/__init__.py': 'presentation',
            'desktop_app/components/__init__.py': 'presentation',
            'quantlab/assistant/adapters/chatgpt/__init__.py': 'infrastructure',
            'quantlab/assistant/adapters/__init__.py': 'infrastructure',
            'quantlab/assistant/__init__.py': 'shared',
            'desktop_app/features/assistant/__init__.py': 'presentation',
            'quantlab/research_core/adapters/__init__.py': 'infrastructure',
            'quantlab/research_core/__init__.py': 'shared',
            'desktop_app/features/paper/__init__.py': 'presentation',
            'desktop_app/features/backtest/__init__.py': 'presentation',
            'desktop_app/features/compare/__init__.py': 'presentation',
            'desktop_app/features/data/__init__.py': 'presentation',
            'desktop_app/features/strategy/__init__.py': 'presentation',
            'desktop_app/features/onboarding/__init__.py': 'presentation',
            'desktop_app/features/walk_forward/__init__.py': 'presentation',
            'desktop_app/strings/__init__.py': 'shared',
            'tools/refactor/move_desktop_app.py': 'tooling',
            'tools/refactor/adapt_test_paths.py': 'tooling',
            'tools/refactor/verify_moves.py': 'tooling',
            'tools/refactor/repair_paths.py': 'tooling',
        }
        current = gate.tracked_sources(ROOT)
        self.assertLessEqual({inverse.get(path, path) for path in current}, rows.keys() | metadata.keys())
        for path in current:
            canonical = inverse.get(path, path)
            with self.subTest(path=path, original=canonical):
                if canonical in rows:
                    expected = rows[canonical]
                elif path in metadata:
                    expected = metadata[path]
                    if path.endswith('/__init__.py'):
                        expected_initializer = '"""Pure shared contracts for Quantlab layers."""' if path == 'quantlab/shared/__init__.py' else ''
                        self.assertEqual((ROOT / path).read_text(encoding='utf-8').strip(), expected_initializer)
                else:
                    self.fail('Uninventoried product source: ' + path)
                self.assertEqual(gate.layer_for(path, self.mapping), expected)

    def test_only_package_initializer_destination_is_corrected(self):
        raw = (ROOT / 'tests/fixtures/layered_paths/r0_relocations_a.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest(), 'b1f30593fa4736ea17ef5eca319a91de9e2f05411171e353100b8303d32942e2')
        original = json.loads(raw)
        self.assertEqual(len(original), 102)
        self.assertEqual(original['desktop_pages/__init__.py'], 'desktop_app/shell/__init__.py')
        original['desktop_pages/__init__.py'] = 'desktop_app/shell/pages.py'
        actual = json.loads((ROOT / 'tools/layer_relocations.json').read_text(encoding='utf-8'))
        self.assertEqual(actual, original, 'The other 101 relocation pairs must remain exact')

    def test_allowlist_is_shrink_only(self):
        entries = json.loads((ROOT / 'tools/layer_allowlist.json').read_text(encoding='utf-8'))
        self.assertEqual(len(BASELINE), BASELINE_COUNT)
        assert_shrink_only(self, entries)

    def test_relocation_map_is_frozen_and_matches_inventory(self):
        raw = (ROOT / 'tools/layer_relocations.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest(), 'fa66be37970e64bbe132d90645c505d7120de6d7680784ec02e9fc6a3f2d3e17')
        relocations = json.loads(raw)
        self.assertEqual(len(relocations), len(set(relocations.values())))
        self.assertFalse(set(relocations) & set(relocations.values()))
        for old, new in relocations.items():
            with self.subTest(path=old):
                self.assertTrue(old.endswith('.py') and new.endswith('.py'))
                self.assertNotIn('..', Path(new).parts)
                self.assertFalse(Path(new).is_absolute())

    def test_relocated_debt_cannot_expand_or_replace_original_debt(self):
        relocations = json.loads((ROOT / 'tools/layer_relocations.json').read_text(encoding='utf-8'))
        entry = dict(path='desktop_chatgpt_ui.py', target='desktop_chatgpt_auth', rule='presentation-to-infrastructure', justification='R0 debt')
        moved = gate.Finding(relocations[entry['path']], 50, entry['rule'], 'quantlab.assistant.adapters.chatgpt.auth')
        self.assertEqual(gate.apply_allowlist((moved,), [entry], relocations), ())
        for altered in (
            gate.Finding(moved.path, 50, moved.rule, 'quantlab.new_adapter'),
            gate.Finding('desktop_app/new.py', 50, moved.rule, moved.target),
            gate.Finding(moved.path, 50, 'domain-to-infrastructure', moved.target),
        ):
            with self.subTest(finding=altered):
                self.assertTrue(gate.apply_allowlist((altered,), [entry], relocations))

    def test_removed_debt_cannot_be_restored(self):
        entries = json.loads((ROOT / 'tools/layer_allowlist.json').read_text(encoding='utf-8'))
        self.assertEqual(gate.restored_debts(entries[:-1], entries), ())
        self.assertEqual([item.rule for item in gate.restored_debts(entries, entries[:-1])], ['restored-allowlist-entry'])

    def test_split_origins_preserve_only_existing_debt_and_never_new_edges(self):
        origins = self.mapping['split_origins']
        self.assertEqual(
            origins,
            {
                'quantlab/assistant/adapters/chatgpt/vault.py': 'desktop_chatgpt_auth.py',
                'quantlab/assistant/adapters/chatgpt/transport.py': 'desktop_chatgpt_provider.py',
                'quantlab/assistant/adapters/chatgpt/response_stream.py': 'desktop_chatgpt_provider.py',
                'quantlab/research_core/adapters/job_process.py': 'quantlab/desktop_runtime.py',
                'quantlab/research_core/adapters/job_worker.py': 'quantlab/desktop_runtime.py',
                'quantlab/research_core/adapters/saved_pool_source.py': 'quantlab/saved_candidate_pool.py',
                'quantlab/research_core/adapters/workspace_backup.py': 'quantlab/desktop_runtime.py',
                'quantlab/research_core/application/job_requests.py': 'quantlab/desktop_runtime.py',
                'quantlab/research_core/application/saved_pool_attempts.py': 'quantlab/saved_candidate_pool.py',
                'quantlab/research_core/application/saved_pool_validation.py': 'quantlab/saved_candidate_pool.py',
                'desktop_app/features/capital_scenario/presenter.py': 'desktop_capital_scenario.py',
            },
        )
        entry = dict(
            path='desktop_chatgpt_auth.py',
            target='quantlab.desktop_runtime',
            rule='infrastructure-to-application',
            justification='Unchanged pre-existing vault dependency',
        )
        finding = gate.Finding('quantlab/assistant/adapters/chatgpt/vault.py', 10, entry['rule'], entry['target'])
        self.assertEqual(gate.apply_allowlist((finding,), [entry], split_origins=origins), ())
        for altered in (
            gate.Finding(finding.path, 10, finding.rule, 'quantlab.research'),
            gate.Finding('quantlab/assistant/adapters/chatgpt/provenance.py', 10, finding.rule, finding.target),
            gate.Finding(finding.path, 10, 'domain-to-application', finding.target),
        ):
            with self.subTest(finding=altered):
                self.assertTrue(gate.apply_allowlist((altered,), [entry], split_origins=origins))

    def test_scan_includes_new_untracked_sources_before_controller_commit(self):
        with patch.object(gate, 'git', return_value=b'quantlab/core.py\0quantlab/new.py\0') as command:
            self.assertEqual(gate.tracked_sources(ROOT), ('quantlab/core.py', 'quantlab/new.py'))
            command.assert_called_once_with(ROOT, 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '*.py')

    def test_cli_rejects_restored_debt_and_unresolvable_baseline(self):
        with fixture_repository() as root:
            (root / 'tools').mkdir()
            (root / 'quantlab').mkdir()
            (root / 'tools/layer_map.json').write_text(json.dumps(self.mapping), encoding='utf-8')
            allowances = root / 'tools/layer_allowlist.json'
            allowances.write_text('[]', encoding='utf-8')
            source = root / 'quantlab/core.py'
            source.write_text('import json\n', encoding='utf-8')
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, capture_output=True)
            subprocess.run(
                [
                    'git',
                    '-C',
                    str(root),
                    '-c',
                    'user.name=Layer Gate Test',
                    '-c',
                    'user.email=test@example.invalid',
                    '-c',
                    'commit.gpgsign=false',
                    'commit',
                    '-qm',
                    'No debt',
                ],
                check=True,
                capture_output=True,
            )
            entry = dict(path='quantlab/core.py', target='shioaji', rule='domain-to-external-sdk', justification='removed debt')
            source.write_text('import shioaji\n', encoding='utf-8')
            allowances.write_text(json.dumps([entry]), encoding='utf-8')
            command = [sys.executable, str(ROOT / 'tools/check_layers.py'), '--root', str(root), '--baseline-ref']
            result = subprocess.run([*command, 'HEAD'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('restored-allowlist-entry', result.stdout)
            result = subprocess.run([*command, 'not-a-commit'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('layer-scan-failed', result.stdout)

    def test_original_and_relocated_file_cannot_share_one_exemption(self):
        with fixture_repository() as root:
            old, new = 'old.py', 'moved.py'
            for path in (old, new):
                (root / path).write_text('import shioaji\n', encoding='utf-8')
            (root / 'tools').mkdir()
            (root / 'tools/layer_relocations.json').write_text(json.dumps({old: new}), encoding='utf-8')
            mapping = dict(prefixes={}, overrides={old: 'domain', new: 'domain'}, ports=[])
            entry = dict(path=old, target='shioaji', rule='domain-to-external-sdk', justification='R0 debt')
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, capture_output=True)
            self.assertIn('duplicate-relocated-source', [item.rule for item in gate.scan(root, mapping, [entry])])

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

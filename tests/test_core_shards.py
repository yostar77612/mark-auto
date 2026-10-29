"""Synthetic controls for whole-module core shards and their strict CI gate.

These controls do not run, shorten, mock out, or replace product test workloads.
"""

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from tools import run_test_group as group
from tools import validate_core_shards as gate


# Exact baseline Windows applicability skips, independent of the validator.
EXPECTED_WINDOWS_CORE_SKIPS = {
    "test_desktop_chatgpt_integration.DescendantQuiescenceTests.test_term_ignoring_descendant_cannot_survive_cancel": "Linux process evidence",
    "test_desktop_history_smoke.HistorySmokeResultTests.test_missing_module_bad_result_and_worker_failure_fail_overall": "Frozen installer harness owns isolated Windows profile smoke",
    "test_desktop_market_smoke.MarketSmokeWidgetTests.test_missing_bundled_root_module_fails_overall_without_dialog_hang": "Use an isolated home for failure-report test; Windows profile must remain untouched",
    "test_desktop_market_smoke.MarketSmokeWidgetTests.test_source_smoke_runs_worker_manual_exchange_and_preserves_seven_steps": "Windows frozen smoke is run by installer harness; do not touch test-runner real profile here",
    "test_kvm_x86_execution.KvmExecutionMockedTests.test_cleanup_failures_invalidate_success_and_remaining_cleanup_is_attempted": "Linux x86_64 C harness requires the host C compiler",
    "test_kvm_x86_execution.KvmExecutionMockedTests.test_every_setup_and_run_failure_closes_all_acquired_resources": "Linux x86_64 C harness requires the host C compiler",
    "test_kvm_x86_execution.KvmExecutionMockedTests.test_io_alone_is_insufficient_if_second_exit_is_not_halt": "Linux x86_64 C harness requires the host C compiler",
    "test_kvm_x86_execution.KvmExecutionMockedTests.test_malformed_io_metadata_and_marker_never_resume_guest": "Linux x86_64 C harness requires the host C compiler",
    "test_kvm_x86_execution.KvmExecutionMockedTests.test_missing_denied_or_symlink_device_are_sanitized": "Linux x86_64 C harness requires the host C compiler",
    "test_kvm_x86_execution.KvmExecutionMockedTests.test_no_or_arbitrary_arguments_never_touch_host": "Linux x86_64 C harness requires the host C compiler",
    "test_kvm_x86_execution.KvmExecutionMockedTests.test_preflight_rejections_never_create_vm": "Linux x86_64 C harness requires the host C compiler",
    "test_kvm_x86_execution.KvmExecutionMockedTests.test_success_requires_expected_out_then_halt_and_complete_cleanup": "Linux x86_64 C harness requires the host C compiler",
    "test_kvm_x86_execution.KvmExecutionMockedTests.test_timeout_fails_without_retry_and_cleans_up": "Linux x86_64 C harness requires the host C compiler",
    "test_kvm_x86_execution.KvmExecutionWorkflowContractTests.test_mocked_wrapper_preserves_complete_partial_and_empty_stdout": "Hosted Linux shell contract requires bash",
    "test_notice_collector.ZipCollectorTests.test_special_source_fails_without_opening": "FIFO requires POSIX",
    "test_smoke_timeout_diagnostics.ProcDisappearanceTests.test_group_join_and_liveness_do_not_hide_permission_or_unknown_errors": "Linux /proc disappearance semantics",
    "test_smoke_timeout_diagnostics.ProcDisappearanceTests.test_group_join_survives_real_unrelated_proc_exit_during_scan": "Linux /proc disappearance semantics",
    "test_smoke_timeout_diagnostics.ProcDisappearanceTests.test_liveness_classifies_kernel_dead_states_and_retains_unknowns": "Linux /proc disappearance semantics",
    "test_smoke_timeout_diagnostics.ProcDisappearanceTests.test_liveness_survives_real_process_exit_during_stat_read": "Linux /proc disappearance semantics",
    "test_smoke_timeout_diagnostics.ProcDisappearanceTests.test_owned_stopped_process_is_live_until_killed_zombie_and_reaped": "Linux /proc disappearance semantics",
    "test_smoke_timeout_diagnostics.ProcDisappearanceTests.test_timeout_cleanup_survives_real_unrelated_proc_exit_during_scan": "Linux /proc disappearance semantics",
    "test_smoke_timeout_diagnostics.ProcDisappearanceTests.test_timeout_scan_permission_and_unknown_errors_keep_cleanup_unverified": "Linux /proc disappearance semantics",
    "test_ui.UITests.test_campaign_repeat_and_path_error": "Optional Streamlit is not installed; UI verification not run",
    "test_ui.UITests.test_empty_error_and_import": "Optional Streamlit is not installed; UI verification not run",
    "test_ui.UITests.test_paper_repeated_intent_stop_and_reconciliation_error": "Optional Streamlit is not installed; UI verification not run",
    "test_ui.UITests.test_repeated_run_selection_and_restart": "Optional Streamlit is not installed; UI verification not run",
    "test_ui.UITests.test_selected_strategy_paper_replay": "Optional Streamlit is not installed; UI verification not run",
}


def _fixture_cases(module, names=('test_b', 'test_a'), class_name='Fixture'):
    case_type = type(
        class_name,
        (unittest.TestCase,),
        {
            '__module__': module,
            **{name: lambda self: None for name in names},
        },
    )
    return [case_type(name) for name in names]


EXPECTED_PAPER_MODULES = frozenset(
    {
        'test_paper',
        'test_paper_diagnostics',
        'test_paper_replay',
        'test_paper_replay_policy',
        'test_paper_replay_storage',
        'test_paper_replay_timeout_diagnostics',
        'test_paper_replay_wal',
    }
)
EXPECTED_DESKTOP_MODULES = frozenset(
    {
        'test_analysis_recovery_ui',
        'test_market_history_ui',
        'test_ui_operations_registry',
        'test_ui_redesign_data_results',
    }
)


def _expected_shard(module):
    # Independent assertion of the versioned rule, not the production classifier.
    if module.startswith(('test_trading_', 'test_broker_', 'test_runtime_context_')) or module == 'test_quality_gate_v2_boundaries':
        return 'trading'
    if module.startswith('test_desktop_') or module in EXPECTED_DESKTOP_MODULES:
        return 'desktop'
    return 'paper' if module in EXPECTED_PAPER_MODULES else 'remaining'


class CoreShardAssignmentTests(unittest.TestCase):
    def suite(self):
        modules = (
            'test_analysis_recovery_ui',
            'test_core_future',
            'test_desktop_future',
            'test_market_history_ui',
            'test_other_future',
            'test_paper',
            'test_paper_replay_wal',
            'test_trading_future',
        )
        return unittest.TestSuite(unittest.TestSuite(_fixture_cases(module)) for module in modules)

    def test_versioned_rule_and_future_modules(self):
        self.assertEqual(group.CORE_SHARDS, ('desktop', 'paper', 'remaining', 'trading'))
        self.assertEqual(group.CORE_SHARD_PLAN, 'core-modules-v4')
        self.assertEqual(group.PAPER_MODULES, EXPECTED_PAPER_MODULES)
        self.assertEqual(group.LEGACY_DESKTOP_MODULES, EXPECTED_DESKTOP_MODULES)
        for module in (
            'test_desktop_future',
            'test_analysis_recovery_ui',
            'test_market_history_ui',
            'test_core_future',
            'test_future',
            'test_desktopish',
            'test_analysis_recovery',
            'test_paper_future',
            'test_paperish',
            'test_trading_future',
            'test_broker_future',
            'test_runtime_context_future',
            'test_quality_gate_v2_boundaries',
            'test_tradingish',
            'test_brokerish',
            'test_runtime_contextish',
            'test_ui_operations_registry',
            'test_ui_redesign_data_results',
            'test_ui_unknown_future',
            *sorted(EXPECTED_PAPER_MODULES),
        ):
            with self.subTest(module=module):
                self.assertEqual(group.core_shard_for_module(module), _expected_shard(module))

    def test_deterministic_complete_disjoint_whole_module_assignment(self):
        suite = self.suite()
        original_cases = list(group.cases(suite))
        original_ids = [case.id() for case in original_cases]
        assigned = group.core_shard_assignments(suite)
        self.assertEqual(assigned, group.core_shard_assignments(suite))
        self.assertEqual(tuple(assigned), group.CORE_SHARDS)
        for label in group.CORE_SHARDS:
            expected = [case.id() for case in original_cases if _expected_shard(type(case).__module__) == label]
            self.assertEqual(assigned[label], expected)
            self.assertTrue(assigned[label])
        union = sum(assigned.values(), [])
        self.assertEqual(len(union), len(set(union)))
        self.assertEqual(set(union), set(original_ids))
        self.assertEqual(list(group.cases(suite)), original_cases)
        self.assertEqual([case.id() for case in group.cases(suite)], original_ids)
        for module in {type(case).__module__ for case in original_cases}:
            owners = {label for label, ids in assigned.items() if any(test_id.startswith(module + '.') for test_id in ids)}
            self.assertEqual(owners, {_expected_shard(module)})

    def test_trading_modules_have_one_owner_and_preserve_legacy_module_rules(self):
        trading = {
            path.stem
            for path in (group.ROOT / 'tests').glob('test_*.py')
            if path.stem.startswith(('test_trading_', 'test_broker_', 'test_runtime_context_')) or path.stem == 'test_quality_gate_v2_boundaries'
        }
        self.assertIn('test_trading_application', trading)
        self.assertIn('test_trading_runtime', trading)
        self.assertIn('test_broker_optional_packaging', trading)
        for module in sorted(trading):
            with self.subTest(module=module):
                self.assertEqual(group.core_shard_for_module(module), 'trading')
        for path in (group.ROOT / 'tests').glob('test_*.py'):
            module = path.stem
            if module in trading or module in group.RESEARCH_MODULES:
                continue
            legacy = (
                'desktop'
                if module.startswith('test_desktop_') or module in EXPECTED_DESKTOP_MODULES
                else 'paper'
                if module in EXPECTED_PAPER_MODULES
                else 'remaining'
            )
            with self.subTest(legacy_module=module):
                self.assertEqual(group.core_shard_for_module(module), legacy)

    def test_original_research_modules_are_rejected_including_desktop_names(self):
        for module in sorted(group.RESEARCH_MODULES):
            with self.subTest(module=module), self.assertRaises(ValueError):
                group.core_shard_for_module(module)
            suite = self.suite()
            suite.addTests(_fixture_cases(module))
            with self.subTest(suite_module=module), self.assertRaises(ValueError):
                group.core_shard_assignments(suite)

    def test_empty_duplicate_and_one_sided_assignments_fail_closed(self):
        one = _fixture_cases('test_desktop_future')[0]
        bad_suites = [
            unittest.TestSuite(),
            unittest.TestSuite([one, one]),
            unittest.TestSuite(_fixture_cases('test_desktop_future')),
            unittest.TestSuite(_fixture_cases('test_core_future')),
            unittest.TestSuite(_fixture_cases('test_paper')),
        ]
        for suite in bad_suites:
            with self.subTest(ids=[case.id() for case in group.cases(suite)]):
                with self.assertRaises(ValueError):
                    group.core_shard_assignments(suite)
        for missing in ('desktop', 'paper', 'remaining', 'trading'):
            suite = unittest.TestSuite(case for case in group.cases(self.suite()) if _expected_shard(type(case).__module__) != missing)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                group.core_shard_assignments(suite)
        suite = self.suite()
        suite.addTest(next(group.cases(suite)))
        with self.assertRaises(ValueError):
            group.core_shard_assignments(suite)

    def test_whole_module_assignment_preserves_fixture_and_original_case_order(self):
        events = []
        modules = {}
        original_cases = []
        expected_by_shard = {name: [] for name in ('desktop', 'paper', 'remaining', 'trading')}
        for module_name in (
            'test_desktop_fixture_alpha',
            'test_future_fixture',
            'test_desktop_fixture_beta',
            'test_paper',
            'test_paper_replay_wal',
            'test_trading_fixture',
        ):
            module = types.ModuleType(module_name)
            module.setUpModule = lambda name=module_name: events.append(name + ':module-setup')
            module.tearDownModule = lambda name=module_name: events.append(name + ':module-teardown')
            modules[module_name] = module
            expected = expected_by_shard[_expected_shard(module_name)]
            expected.append(module_name + ':module-setup')
            for class_name in ('Second', 'First'):
                prefix = module_name + ':' + class_name
                case_type = type(
                    class_name,
                    (unittest.TestCase,),
                    {
                        '__module__': module_name,
                        'setUpClass': classmethod(lambda cls, p=prefix: events.append(p + ':class-setup')),
                        'tearDownClass': classmethod(lambda cls, p=prefix: events.append(p + ':class-teardown')),
                        'test_b': lambda self, p=prefix: events.append(p + ':b'),
                        'test_a': lambda self, p=prefix: events.append(p + ':a'),
                    },
                )
                original_cases.extend((case_type('test_b'), case_type('test_a')))
                expected.extend((prefix + ':class-setup', prefix + ':b', prefix + ':a', prefix + ':class-teardown'))
            expected.append(module_name + ':module-teardown')
        suite = unittest.TestSuite(original_cases)
        assigned = group.core_shard_assignments(suite)
        with patch.dict(sys.modules, modules):
            for label in group.CORE_SHARDS:
                chosen = [case for case in original_cases if case.id() in set(assigned[label])]
                self.assertEqual([case.id() for case in chosen], assigned[label])
                result = unittest.TestResult()
                unittest.TestSuite(chosen).run(result)
                self.assertTrue(result.wasSuccessful(), result.errors)
                self.assertEqual(result.testsRun, len(chosen))
        self.assertEqual(events, sum(expected_by_shard.values(), []))


class PortableCoreSourceIdentityTests(unittest.TestCase):
    def write_sources(self, root):
        sources = {
            'application.py': b'VALUE = 1\n',
            'quantlab/model.py': b'VALUE = 2\n',
            'tests/test_synthetic.py': b'VALUE = 3\n',
            'tools/run_test_group.py': b'VALUE = 4\n',
            'tools/validate_core_shards.py': b'VALUE = 5\n',
        }
        for name, content in sources.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def identity(self, root):
        with patch.object(group, 'ROOT', root), patch.object(group, '__file__', str(root / 'tools/run_test_group.py')):
            return group.portable_source_identity(str(root / 'tests'))

    def test_portable_identity_matches_across_independent_checkout_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / 'runner-one' / 'checkout'
            second = Path(temporary) / 'runner-two' / 'different-checkout'
            self.write_sources(first)
            self.write_sources(second)
            before = self.identity(first)
            self.assertRegex(before, r'^[0-9a-f]{64}$')
            self.assertEqual(before, self.identity(first))
            self.assertEqual(before, self.identity(second))

    def test_source_bytes_relative_paths_and_validator_changes_affect_identity(self):
        for relative in ('application.py', 'quantlab/model.py', 'tests/test_synthetic.py', 'tools/run_test_group.py', 'tools/validate_core_shards.py'):
            with self.subTest(source=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_sources(root)
                before = self.identity(root)
                path = root / relative
                path.write_bytes(path.read_bytes() + b'# changed\n')
                self.assertNotEqual(before, self.identity(root))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_sources(root)
            before = self.identity(root)
            (root / 'tests/test_synthetic.py').rename(root / 'tests/test_renamed.py')
            self.assertNotEqual(before, self.identity(root))

    def test_real_parent_directory_alias_matches_canonical_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'checkout'
            self.write_sources(root)
            alias = root / '..' / 'checkout'
            self.assertNotEqual(alias, alias.resolve())
            self.assertEqual(alias.resolve(), root.resolve())
            self.assertEqual(self.identity(alias), self.identity(root.resolve()))

    def test_duplicate_aliases_coalesce_but_distinct_external_files_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            root = parent / 'checkout'
            self.write_sources(root)
            first = parent / 'external-one' / 'same.py'
            second = parent / 'external-two' / 'same.py'
            for path in (first, second):
                path.parent.mkdir()
                path.write_bytes(b'VALUE = 99\n')
            alias = first.parent / '..' / first.parent.name / first.name
            self.assertNotEqual(first, alias)
            self.assertEqual(first.resolve(), alias.resolve())
            original_glob = Path.glob

            def identity_with_sources(extra):
                # Control source enumeration only; all paths and bytes are real.
                def glob(path, pattern, **kwargs):
                    found = list(original_glob(path, pattern, **kwargs))
                    if path == root and pattern == '*.py':
                        found.extend(extra)
                    return iter(found)

                with patch.object(Path, 'glob', glob):
                    return self.identity(root)

            expected = identity_with_sources([first])
            self.assertEqual(expected, identity_with_sources([first, alias]))
            with self.assertRaisesRegex(ValueError, 'Ambiguous portable source path'):
                identity_with_sources([first, second])

    def test_parallel_source_digests_match_independent_ordered_byte_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'checkout'
            self.write_sources(root)
            included = {
                'application.py',
                'quantlab/model.py',
                'tests/test_synthetic.py',
                'tools/run_test_group.py',
                'tools/validate_core_shards.py',
            }
            additions = {
                '.gitattributes': b'*.py text eol=lf\n',
                'pyproject.toml': b'[project]\nname="fixture"\n',
                'requirements-fixture.lock': b'fixture==1\n',
                'desktop_pages/view.py': b'VIEW=1\n',
                'desktop_app/features/trading/view.json': b'{"v":1}\n',
                'desktop_smoke/source.txt': b'fixture\x00\xff',
                'packaging/input.ps1': b'exit 0\r\n',
                'packaging/input.cs': b'// fixture\n',
                'tests/fixtures/data.gz': b'\x1f\x8b\x00\xff',
                'tests/fixtures/data.csv': b'one,two\n1,2\n',
                '.github/workflows/one.yml': b'name: one\n',
                '.github/workflows/two.yaml': b'name: two\n',
            }
            for name, raw in additions.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            included.update(additions)
            for name in ('ignored.json', 'quantlab/ignored.bin', 'quantlab/ignored.PY', 'quantlab/__pycache__/ignored.py'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'not a source input\n')
            external = Path(temporary).resolve() / 'external'
            external.mkdir()
            extra = external / 'test_extra.py'
            extra.write_bytes(b'EXTERNAL=1\n')
            portable = hashlib.sha256()
            expected = {name: root / name for name in included}
            expected['__test_suite__/test_extra.py'] = extra
            # An independent fixed-fixture selection and sequential byte stream;
            # neither production selector nor parallel reader builds this oracle.
            for name, path in sorted(expected.items()):
                with path.open('rb') as stream:
                    raw = stream.read()
                portable.update(name.encode('utf-8') + b'\0' + str(len(raw)).encode('ascii') + b'\0' + raw)
            execution = hashlib.sha256()
            local_paths = [root / name for name in ('application.py', 'quantlab/model.py', 'tests/test_synthetic.py', 'tools/run_test_group.py')]
            if os.name == 'nt':
                # Existing local glob is case-insensitive on Windows, unlike
                # the portable recursive suffix allowlist. Preserve both rules.
                local_paths.append(root / 'quantlab/ignored.PY')
            for path in sorted(local_paths + [extra]):
                with path.open('rb') as stream:
                    raw = stream.read()
                execution.update(str(path).encode('utf-8') + b'\0' + raw + b'\0')
            with patch.object(group, 'ROOT', root), patch.object(group, '__file__', str(root / 'tools/run_test_group.py')):
                self.assertEqual(group.portable_source_identity(str(external)), portable.hexdigest())
                self.assertEqual(group.execution_identity(str(external))['source_sha256'], execution.hexdigest())

    def test_parallel_reads_are_bounded_and_return_input_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = [Path(temporary) / (str(index) + '.py') for index in range(8)]
            expected = [bytes([index, 255, 0]) for index in range(8)]
            for path, raw in zip(paths, expected):
                path.write_bytes(raw)
            original = Path.read_bytes
            lock = threading.Lock()
            barrier = threading.Barrier(4, timeout=3)
            fourth_done = threading.Event()
            active = peak = calls = 0

            def read(path):
                nonlocal active, peak, calls
                with lock:
                    calls += 1
                    number = calls
                    active += 1
                    peak = max(peak, active)
                try:
                    if number <= 4:
                        barrier.wait()
                    if path == paths[0]:
                        self.assertTrue(fourth_done.wait(3), 'Later raw read must run without waiting for the first result')
                    raw = original(path)
                    if path == paths[3]:
                        fourth_done.set()
                    time.sleep(0.005)
                    return raw
                finally:
                    with lock:
                        active -= 1

            with patch.object(Path, 'read_bytes', read):
                self.assertEqual(list(group._ordered_source_bytes(paths)), expected)
            self.assertEqual(calls, len(paths))
            self.assertEqual(peak, 4)
            self.assertEqual(active, 0)

    def test_source_read_window_does_not_prefetch_entire_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = [Path(temporary) / (str(index) + '.py') for index in range(12)]
            for path in paths:
                path.write_bytes(b'fixture')
            consumed = []

            def inventory():
                for path in paths:
                    consumed.append(path)
                    yield path

            raw = group._ordered_source_bytes(inventory())
            try:
                self.assertEqual(next(raw), b'fixture')
                self.assertEqual(consumed, paths[:4])
            finally:
                raw.close()

    def test_read_failures_cannot_return_either_identity_or_leave_source_workers(self):
        for name in ('portable_source_identity', 'execution_identity'):
            for error_type in (PermissionError, FileNotFoundError):
                with self.subTest(identity=name, error=error_type), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary).resolve()
                    self.write_sources(root)
                    original = Path.read_bytes
                    lock = threading.Lock()
                    active = 0

                    def read(path):
                        nonlocal active
                        with lock:
                            active += 1
                        try:
                            if path == root / 'quantlab/model.py':
                                raise error_type('Controlled source read failure')
                            time.sleep(0.005)
                            return original(path)
                        finally:
                            with lock:
                                active -= 1

                    with (
                        patch.object(group, 'ROOT', root),
                        patch.object(group, '__file__', str(root / 'tools/run_test_group.py')),
                        patch.object(Path, 'read_bytes', read),
                        self.assertRaises(error_type),
                    ):
                        getattr(group, name)(str(root / 'tests'))
                    self.assertEqual(active, 0)

    def test_both_identity_passes_reread_changed_source_bytes(self):
        for name in ('portable_source_identity', 'execution_identity'):
            with self.subTest(identity=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                self.write_sources(root)
                original = Path.read_bytes
                lock = threading.Lock()
                counts = {}

                def read(path):
                    with lock:
                        counts[path] = counts.get(path, 0) + 1
                    return original(path)

                with (
                    patch.object(group, 'ROOT', root),
                    patch.object(group, '__file__', str(root / 'tools/run_test_group.py')),
                    patch.object(Path, 'read_bytes', read),
                ):
                    first = getattr(group, name)(str(root / 'tests'))
                    (root / 'quantlab/model.py').write_bytes(b'VALUE = 200\n')
                    second = getattr(group, name)(str(root / 'tests'))
                self.assertNotEqual(first, second)
                self.assertTrue(counts)
                self.assertTrue(all(count == 2 for count in counts.values()), counts)


class IndependentCoreInventoryTests(unittest.TestCase):
    def write_suite(self, root, broken=False):
        for name in ('test_desktop_expected_inventory', 'test_expected_inventory', 'test_paper', 'test_trading_expected_inventory', 'test_research'):
            marker = repr(str(root / 'execution-was-forbidden'))
            (root / (name + '.py')).write_text(
                "import unittest\nfrom pathlib import Path\n"
                "def forbidden():\n Path(" + marker + ").write_text('executed')\n"
                " raise AssertionError('Independent inventory must never execute fixtures or test methods')\n"
                "def setUpModule(): forbidden()\n"
                "def tearDownModule(): forbidden()\n"
                "class Fixture(unittest.TestCase):\n"
                " def test_a(self): forbidden()\n def test_b(self): forbidden()\n"
                "def load_tests(loader, tests, pattern):\n"
                " return unittest.TestSuite([Fixture('test_b'), Fixture('test_a')])\n",
                encoding='utf-8',
            )
        if broken:
            (root / 'test_unrelated_broken.py').write_text("raise RuntimeError('synthetic unrelated discovery failure')\n", encoding='utf-8')

    def collect(self, root):
        # Isolate synthetic module names from the enclosing test runner imports.
        script = """import json, sys
from tools.validate_core_shards import collect_expected_inventory
try:
 inventory = collect_expected_inventory(sys.argv[1])
except ValueError as error:
 print(json.dumps({'error': str(error)}))
else:
 print(json.dumps({'inventory': inventory}))
"""
        result = subprocess.run([sys.executable, '-c', script, str(root)], cwd=group.ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((root / 'execution-was-forbidden').exists())
        return json.loads(result.stdout)

    def test_actual_discovery_preserves_original_custom_order_without_executing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_suite(root)
            result = self.collect(root)
            self.assertNotIn('error', result)
            expected = [
                module + '.Fixture.' + method
                for module in ('test_desktop_expected_inventory', 'test_expected_inventory', 'test_paper', 'test_research', 'test_trading_expected_inventory')
                for method in ('test_b', 'test_a')
            ]
            self.assertEqual(
                result['inventory'],
                {
                    'discovered_ids': expected,
                    'partitions': {
                        'core': [item for item in expected if not item.startswith('test_research.')],
                        'research': [item for item in expected if item.startswith('test_research.')],
                    },
                },
            )

    def test_unrelated_import_error_is_fatal_to_independent_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_suite(root, broken=True)
            result = self.collect(root)
            self.assertNotIn('inventory', result)
            self.assertIn('error', result)
            self.assertTrue(result['error'])


class CoreShardReportTests(unittest.TestCase):
    CONTEXT = {'head_sha': 'a' * 40, 'run_id': '123456789', 'run_attempt': '2', 'python_profile': '3.11', 'source_sha256': 'b' * 64}

    def expected_inventory(self):
        core = [
            'test_desktop_synthetic.Fixture.test_a',
            'test_desktop_synthetic.Fixture.test_b',
            'test_paper.Fixture.test_a',
            'test_paper.Fixture.test_b',
            'test_future_synthetic.Fixture.test_a',
            'test_future_synthetic.Fixture.test_b',
            'test_trading_synthetic.Fixture.test_a',
            'test_trading_synthetic.Fixture.test_b',
        ] + sorted(EXPECTED_WINDOWS_CORE_SKIPS)
        research = ['test_research.Fixture.test_a', 'test_walk_forward.Fixture.test_b']
        discovered = core[:2] + research[:1] + core[2:] + research[1:]
        return {'discovered_ids': discovered, 'partitions': {'core': core, 'research': research}}

    def reports(self):
        inventory = self.expected_inventory()
        discovered = inventory['discovered_ids']
        core, research = inventory['partitions']['core'], inventory['partitions']['research']
        assignments = {
            label: [test_id for test_id in core if _expected_shard(test_id.rsplit('.', 2)[0]) == label]
            for label in ('desktop', 'paper', 'remaining', 'trading')
        }
        reports = []
        for index, label in enumerate(('desktop', 'paper', 'remaining', 'trading')):
            selected = assignments[label]
            identity = {
                'source_sha256': str(index + 1) * 64,
                'head_sha': self.CONTEXT['head_sha'],
                'executable': 'C:\\runner-' + str(index) + '\\python.exe',
                'python': '3.11.14 (synthetic Windows fixture)',
                'sqlite_version': json.loads((group.ROOT / 'packaging/sqlite-runtime.json').read_text())['version'],
                'environment': {
                    'TEMP': 'C:\\temp-' + str(index),
                    'TMP': 'C:\\temp-' + str(index),
                    'RUNNER_TEMP': 'C:\\runner-temp-' + str(index),
                    'QT_QPA_PLATFORM': 'offscreen',
                },
                'tempfile_gettempdir': 'C:\\temp-' + str(index),
            }
            reports.append(
                {
                    'head_sha': self.CONTEXT['head_sha'],
                    'python': '3.11.14',
                    'platform': 'win32',
                    'group': 'core',
                    'core_shard': label,
                    'core_shard_plan': 'core-modules-v4',
                    'core_shard_assignments': copy.deepcopy(assignments),
                    'shard_context': dict(self.CONTEXT),
                    'source_sha256_after': self.CONTEXT['source_sha256'],
                    'local_identity_before': copy.deepcopy(identity),
                    'local_identity_after': copy.deepcopy(identity),
                    'discovered_ids': discovered[:],
                    'partitions': {'core': core[:], 'research': research[:]},
                    'selected_ids': selected[:],
                    'discovery_errors': [],
                    'run_completed': True,
                    'successful': True,
                    'tests_run': len(selected),
                    'started_ids': selected[:],
                    'stopped_ids': selected[:],
                    'failures': [],
                    'errors': [],
                    'expected_failures': [],
                    'unexpected_successes': [],
                    'skipped': [{'id': test_id, 'reason': gate.WINDOWS_CORE_SKIPS[test_id]} for test_id in selected if test_id in gate.WINDOWS_CORE_SKIPS],
                }
            )
        return reports

    def validate(self, reports):
        return gate.validate_core_reports(reports, expected_inventory=self.expected_inventory(), **self.CONTEXT)

    def test_complete_reports_allow_distinct_stable_runner_paths_without_mutation(self):
        reports = self.reports()
        before = copy.deepcopy(reports)
        self.assertNotEqual(reports[0]['local_identity_before'], reports[1]['local_identity_before'])
        result = self.validate(reports)
        self.assertIsInstance(result, dict)
        self.assertEqual(result['coverage_scope'], 'original core only; research remains a separate mandatory gate')
        self.assertEqual(result['head_sha'], self.CONTEXT['head_sha'])
        self.assertEqual(result['python_profile'], self.CONTEXT['python_profile'])
        self.assertEqual(result['core_shard_plan'], 'core-modules-v4')
        self.assertEqual(result['shards'], 4)
        self.assertEqual(result['tests_run'], len(reports[0]['partitions']['core']))
        self.assertIs(result['successful'], True)
        self.assertEqual(result['core_ids'], reports[0]['partitions']['core'])
        self.assertEqual(reports, before)
        self.assertEqual(self.validate(list(reversed(reports))), result)

    def test_exactly_three_distinct_named_shards_required(self):
        # Retain this historical test ID while extending the versioned plan.
        self.assert_each_of_three_shards_is_required_with_original_order_and_identity()
        for bad in ([], self.reports()[:1], self.reports()[:2], self.reports() + self.reports()[:1], [None, {}], [{}, {}], [[], []]):
            with self.subTest(reports=bad), self.assertRaises(ValueError):
                self.validate(bad)
        for label in ('desktop', 'remaining', 'trading', 'unknown', None, True):
            reports = self.reports()
            reports[1]['core_shard'] = label
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.validate(reports)

    def test_fourth_trading_report_cannot_be_missing_forged_reclassified_or_skipped(self):
        original = self.reports()
        trading = next(row for row in original if row['core_shard'] == 'trading')
        self.assertEqual(trading['selected_ids'], ['test_trading_synthetic.Fixture.test_a', 'test_trading_synthetic.Fixture.test_b'])
        self.assertEqual(trading['skipped'], [])
        self.assertEqual(self.validate(original)['shards'], 4)
        with self.assertRaises(ValueError):
            self.validate([row for row in original if row['core_shard'] != 'trading'])
        for mode in ('duplicate', 'move', 'omit', 'skip', 'old-plan', 'wrong-attempt', 'wrong-source'):
            reports = self.reports()
            row = next(item for item in reports if item['core_shard'] == 'trading')
            if mode == 'duplicate':
                reports.append(copy.deepcopy(row))
            elif mode == 'move':
                for report in reports:
                    moved = report['core_shard_assignments']['trading'].pop()
                    report['core_shard_assignments']['remaining'].append(moved)
            elif mode == 'omit':
                row['selected_ids'].pop()
            elif mode == 'skip':
                row['skipped'] = [{'id': row['selected_ids'][0], 'reason': 'temporarily disabled'}]
            elif mode == 'old-plan':
                row['core_shard_plan'] = 'core-modules-v2'
            elif mode == 'wrong-attempt':
                row['shard_context']['run_attempt'] = '1'
            else:
                row['source_sha256_after'] = 'c' * 64
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.validate(reports)

    def assert_each_of_three_shards_is_required_with_original_order_and_identity(self):
        for label in ('desktop', 'paper', 'remaining', 'trading'):
            reports = self.reports()
            with self.subTest(missing=label), self.assertRaises(ValueError):
                self.validate([row for row in reports if row['core_shard'] != label])
            for field, value in (('successful', False), ('run_completed', False), ('tests_run', 0), ('core_shard_plan', 'core-modules-v1')):
                changed = self.reports()
                next(row for row in changed if row['core_shard'] == label)[field] = value
                with self.subTest(shard=label, field=field), self.assertRaises(ValueError):
                    self.validate(changed)
            for field in ('selected_ids', 'started_ids', 'stopped_ids'):
                changed = self.reports()
                row = next(row for row in changed if row['core_shard'] == label)
                row[field] = list(reversed(row[field]))
                with self.subTest(shard=label, reordered=field), self.assertRaises(ValueError):
                    self.validate(changed)
            changed = self.reports()
            next(row for row in changed if row['core_shard'] == label)['shard_context']['run_attempt'] = '1'
            with self.subTest(stale_attempt=label), self.assertRaises(ValueError):
                self.validate(changed)

    def assert_correlated_paper_omission_or_reassignment_cannot_redefine_core(self):
        target = 'test_paper.Fixture.test_a'
        for mode in ('omit', 'move-to-remaining'):
            reports = self.reports()
            for row in reports:
                if mode == 'omit':
                    row['discovered_ids'].remove(target)
                    row['partitions']['core'].remove(target)
                assignments = row['core_shard_assignments']
                assignments['paper'].remove(target)
                if mode == 'move-to-remaining':
                    assignments['remaining'].insert(0, target)
                selected = assignments[row['core_shard']]
                for field in ('selected_ids', 'started_ids', 'stopped_ids'):
                    row[field] = selected[:]
                row['tests_run'] = len(selected)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.validate(reports)

    def test_wrong_or_missing_run_context_fails_closed(self):
        for field in self.CONTEXT:
            for value in ('wrong', None, '', True):
                reports = self.reports()
                for report in reports:
                    report['shard_context'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.validate(reports)
            reports = self.reports()
            del reports[0]['shard_context'][field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.validate(reports)
        for field, value in (
            ('head_sha', 'f' * 40),
            ('group', 'research'),
            ('python', '3.12.1'),
            ('platform', 'linux'),
            ('core_shard_plan', 'core-modules-v1'),
        ):
            reports = self.reports()
            for report in reports:
                report[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(reports)

    def test_inconsistent_full_discovery_partitions_and_rule_assignments_rejected(self):
        changes = {
            'discovery omitted': lambda r: r['discovered_ids'].pop(),
            'discovery duplicate': lambda r: r['discovered_ids'].append(r['discovered_ids'][0]),
            'discovery reordered': lambda r: r['discovered_ids'].reverse(),
            'partition omitted': lambda r: r['partitions']['core'].pop(),
            'partition reordered': lambda r: r['partitions']['core'].reverse(),
            'partition overlap': lambda r: r['partitions']['research'].append(r['partitions']['core'][0]),
            'research omitted': lambda r: r['partitions'].pop('research'),
            'assignment omitted': lambda r: r['core_shard_assignments']['desktop'].pop(),
            'assignment duplicate': lambda r: r['core_shard_assignments']['desktop'].append(r['core_shard_assignments']['desktop'][0]),
            'assignment overlap': lambda r: r['core_shard_assignments']['remaining'].append(r['core_shard_assignments']['desktop'][0]),
            'assignment reordered': lambda r: r['core_shard_assignments']['desktop'].reverse(),
            'unexpected shard': lambda r: r['core_shard_assignments'].update(extra=[]),
        }
        for name, change in changes.items():
            reports = self.reports()
            change(reports[0])
            with self.subTest(change=name), self.assertRaises(ValueError):
                self.validate(reports)

    def test_correlated_omission_addition_and_reclassification_cannot_redefine_inventory(self):
        self.assert_correlated_paper_omission_or_reassignment_cannot_redefine_core()
        ordinary = 'test_desktop_synthetic.Fixture.test_a'
        skipped = next(iter(EXPECTED_WINDOWS_CORE_SKIPS))
        for mode, target in (
            ('omission', ordinary),
            ('omission', skipped),
            ('addition', ordinary),
            ('reclassification', ordinary),
            ('research-omission', ordinary),
        ):
            reports = self.reports()
            expected = self.expected_inventory()
            original_expected = copy.deepcopy(expected)
            for report in reports:
                if mode == 'omission':
                    report['discovered_ids'].remove(target)
                    report['partitions']['core'].remove(target)
                elif mode == 'addition':
                    added = 'test_future_unreported.Fixture.test_added'
                    report['discovered_ids'].append(added)
                    report['partitions']['core'].append(added)
                elif mode == 'reclassification':
                    replacement = 'test_future_reclassified.Fixture.test_a'
                    for values in (report['discovered_ids'], report['partitions']['core']):
                        values[values.index(target)] = replacement
                else:
                    omitted = report['partitions']['research'].pop()
                    report['discovered_ids'].remove(omitted)
                core = report['partitions']['core']
                report['core_shard_assignments'] = {
                    label: [test_id for test_id in core if _expected_shard(test_id.rsplit('.', 2)[0]) == label]
                    for label in ('desktop', 'paper', 'remaining', 'trading')
                }
                selected = report['core_shard_assignments'][report['core_shard']]
                for field in ('selected_ids', 'started_ids', 'stopped_ids'):
                    report[field] = selected[:]
                report['tests_run'] = len(selected)
                report['skipped'] = [
                    {'id': test_id, 'reason': EXPECTED_WINDOWS_CORE_SKIPS[test_id]} for test_id in selected if test_id in EXPECTED_WINDOWS_CORE_SKIPS
                ]
            with self.subTest(mode=mode, target=target), self.assertRaises(ValueError):
                gate.validate_core_reports(reports, expected_inventory=expected, **self.CONTEXT)
            self.assertEqual(expected, original_expected)

    def test_missing_or_malformed_independent_inventory_cannot_fall_back_to_reports(self):
        with self.assertRaises(TypeError):
            gate.validate_core_reports(self.reports(), **self.CONTEXT)
        for inventory in (None, {}, [], {'discovered_ids': [], 'partitions': {}}, {'discovered_ids': self.expected_inventory()['discovered_ids']}):
            with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                gate.validate_core_reports(self.reports(), expected_inventory=inventory, **self.CONTEXT)

    def test_contradictory_selection_or_identity_error_never_coexists_with_success(self):
        for field in ('selection_error', 'shard_identity_error'):
            for value in ('reported error', '', None, False):
                reports = self.reports()
                reports[0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.validate(reports)

    def test_consistently_forged_partition_and_assignment_rules_rejected(self):
        reports = self.reports()
        for report in reports:
            core_id = report['partitions']['core'].pop(0)
            report['partitions']['research'].insert(0, core_id)
        with self.assertRaises(ValueError):
            self.validate(reports)
        reports = self.reports()
        moving = reports[0]['core_shard_assignments']['desktop'][:2]
        for report in reports:
            assignments = report['core_shard_assignments']
            assignments['desktop'] = assignments['desktop'][2:]
            assignments['remaining'] = moving + assignments['remaining']
            selected = assignments[report['core_shard']]
            for field in ('selected_ids', 'started_ids', 'stopped_ids'):
                report[field] = selected[:]
            report['tests_run'] = len(selected)
        with self.assertRaises(ValueError):
            self.validate(reports)

    def test_omitted_duplicate_reordered_overlapping_or_research_execution_rejected(self):
        for field in ('selected_ids', 'started_ids', 'stopped_ids'):
            mutations = {
                'omitted': lambda values, reports: values[1:],
                'duplicate': lambda values, reports: values + values[:1],
                'reordered': lambda values, reports: list(reversed(values)),
                'overlap': lambda values, reports: values + reports[1]['selected_ids'][:1],
                'research': lambda values, reports: values + reports[0]['partitions']['research'][:1],
            }
            for name, change in mutations.items():
                reports = self.reports()
                reports[0][field] = change(reports[0][field], reports)
                with self.subTest(field=field, mutation=name), self.assertRaises(ValueError):
                    self.validate(reports)

    def test_incomplete_false_pass_wrong_counts_outcomes_and_fixture_errors_rejected(self):
        changes = (
            ('discovery_errors', ['broken import']),
            ('run_completed', False),
            ('run_completed', 1),
            ('successful', False),
            ('successful', 1),
            ('tests_run', True),
            ('tests_run', 0),
            ('tests_run', 999999),
            ('failures', ['test_desktop_synthetic.Fixture.test_a (subtest=1)']),
            ('errors', ['setUpClass (test_desktop_synthetic.Fixture)']),
            ('errors', ['tearDownModule (test_desktop_synthetic)']),
            ('expected_failures', ['test_desktop_synthetic.Fixture.test_a']),
            ('unexpected_successes', ['test_desktop_synthetic.Fixture.test_a']),
        )
        for field, value in changes:
            reports = self.reports()
            reports[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.validate(reports)
        for field in (
            'discovery_errors',
            'run_completed',
            'successful',
            'tests_run',
            'failures',
            'errors',
            'expected_failures',
            'unexpected_successes',
            'selected_ids',
            'started_ids',
            'stopped_ids',
            'skipped',
        ):
            reports = self.reports()
            del reports[0][field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.validate(reports)

    def test_exact_original_windows_skip_ids_and_reasons_are_required(self):
        self.assertEqual(gate.WINDOWS_CORE_SKIPS, EXPECTED_WINDOWS_CORE_SKIPS)
        self.assertEqual(len(gate.WINDOWS_CORE_SKIPS), 27)
        reports = self.reports()
        self.assertEqual(sum(len(report['skipped']) for report in reports), 27)
        self.validate(reports)
        mutations = {
            'missing': lambda skipped: skipped[1:],
            'duplicate': lambda skipped: skipped + skipped[:1],
            'reordered': lambda skipped: list(reversed(skipped)),
            'changed reason': lambda skipped: [dict(skipped[0], reason='Qt missing')] + skipped[1:],
            'new skip': lambda skipped: skipped + [{'id': 'test_desktop_synthetic.Fixture.test_a', 'reason': 'temporarily disabled'}],
        }
        paper = next(row for row in reports if row['core_shard'] == 'paper')
        self.assertEqual(paper['skipped'], [])
        changed = copy.deepcopy(reports)
        next(row for row in changed if row['core_shard'] == 'paper')['skipped'] = [{'id': paper['selected_ids'][0], 'reason': 'temporarily disabled'}]
        with self.assertRaises(ValueError):
            self.validate(changed)
        for label in ('desktop', 'remaining'):
            for name, change in mutations.items():
                reports = self.reports()
                report = next(row for row in reports if row['core_shard'] == label)
                self.assertGreater(len(report['skipped']), 1)
                report['skipped'] = change(report['skipped'])
                with self.subTest(shard=label, mutation=name), self.assertRaises(ValueError):
                    self.validate(reports)

    def test_both_python_profiles_validate_but_mixed_patch_versions_fail(self):
        for profile in ('3.11', '3.12'):
            reports = self.reports()
            version = profile + '.14'
            context = dict(self.CONTEXT, python_profile=profile)
            for report in reports:
                report['python'] = version
                report['shard_context']['python_profile'] = profile
                for key in ('local_identity_before', 'local_identity_after'):
                    report[key]['python'] = version + ' (synthetic Windows fixture)'
            with self.subTest(profile=profile):
                self.assertTrue(gate.validate_core_reports(reports, expected_inventory=self.expected_inventory(), **context)['successful'])
                reports[1]['python'] = profile + '.15'
                for key in ('local_identity_before', 'local_identity_after'):
                    reports[1][key]['python'] = profile + '.15 (synthetic Windows fixture)'
                with self.assertRaises(ValueError):
                    gate.validate_core_reports(reports, expected_inventory=self.expected_inventory(), **context)

    def test_invalid_expected_run_identity_is_rejected(self):
        invalid = {
            'head_sha': ('A' * 40, 'a' * 39, None, True),
            'run_id': ('0', '-1', '', 123456789, True),
            'run_attempt': ('0', '-1', '', 2, True),
            'python_profile': ('3.10', '3.13', '', None, True),
            'source_sha256': ('B' * 64, 'b' * 63, None, True),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    gate.validate_core_reports(self.reports(), expected_inventory=self.expected_inventory(), **dict(self.CONTEXT, **{field: value}))

    def test_malformed_or_wrong_stable_local_identity_is_rejected(self):
        changes = (
            ('source_sha256', ''),
            ('head_sha', 'f' * 40),
            ('executable', ''),
            ('python', ''),
            ('python', '   '),
            ('python', '3.12.14 synthetic'),
            ('sqlite_version', '0.0.0'),
            ('tempfile_gettempdir', None),
            ('environment', {}),
            ('environment', {'QT_QPA_PLATFORM': 'offscreen'}),
        )
        for field, value in changes:
            reports = self.reports()
            for key in ('local_identity_before', 'local_identity_after'):
                reports[0][key][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.validate(reports)
        for field in self.reports()[0]['local_identity_before']:
            reports = self.reports()
            for key in ('local_identity_before', 'local_identity_after'):
                del reports[0][key][field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.validate(reports)

    def test_local_source_runtime_environment_or_path_drift_rejected(self):
        changes = (
            ('source_sha256', 'f' * 64),
            ('head_sha', 'e' * 40),
            ('executable', 'C:\\different\\python.exe'),
            ('python', '3.12.1'),
            ('sqlite_version', '3.0.0'),
            ('tempfile_gettempdir', 'C:\\different-temp'),
            ('environment', {'QT_QPA_PLATFORM': 'different'}),
        )
        for field, value in changes:
            reports = self.reports()
            reports[0]['local_identity_after'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(reports)
        for value in ('f' * 64, None, ''):
            reports = self.reports()
            reports[0]['source_sha256_after'] = value
            with self.subTest(source_sha256_after=value), self.assertRaises(ValueError):
                self.validate(reports)
        for field in ('local_identity_before', 'local_identity_after', 'source_sha256_after'):
            reports = self.reports()
            del reports[0][field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.validate(reports)
        reports = self.reports()
        reports[0]['local_identity_before'] = None
        reports[0]['local_identity_after'] = None
        with self.assertRaises(ValueError):
            self.validate(reports)


class CoreShardRunnerTests(unittest.TestCase):
    def write_suite(self, root, outcome='pass', setup='pass', teardown='pass'):
        for module_name in ('test_desktop_synthetic', 'test_future_synthetic', 'test_paper', 'test_trading_synthetic', 'test_research'):
            (root / (module_name + '.py')).write_text(
                "import unittest, weakref\nreference = None\n"
                "def setUpModule(): print('MODULE_SETUP:' + __name__); " + setup + "\n"
                "def tearDownModule(): print('MODULE_TEARDOWN:' + __name__); " + teardown + "\n"
                "class Fixture(unittest.TestCase):\n"
                " @classmethod\n def setUpClass(cls): print('CLASS_SETUP:' + __name__)\n"
                " @classmethod\n def tearDownClass(cls): print('CLASS_TEARDOWN:' + __name__)\n"
                " def test_a(self):\n  global reference\n  reference = weakref.ref(self)\n  " + outcome + "\n"
                " def test_b(self):\n  self.assertEqual(reference() is None, " + repr(outcome == 'pass') + ")\n",
                encoding='utf-8',
            )

    def run_shard(self, root, label, mode='normal'):
        # The only discovered cases are the tiny temporary fixtures above.
        # The platform stub exercises argument/report contracts, not Windows APIs.
        script = """import sys
from tools import run_test_group as g
g.sys.platform = 'win32'
"""
        if mode == 'local-drift':
            script += """original = g.execution_identity
calls = 0
def changing(start):
 global calls
 calls += 1
 result = original(start)
 if calls > 1: result['tempfile_gettempdir'] += '-changed'
 return result
g.execution_identity = changing
"""
        elif mode == 'source-drift':
            script += """calls = 0
def changing(start):
 global calls
 calls += 1
 return ('a' if calls == 1 else 'b') * 64
g.portable_source_identity = changing
"""
        script += "raise SystemExit(g.main(['--group', 'core', '--core-shard', sys.argv[2], '--start-directory', sys.argv[1], '--manifest', sys.argv[3]]))\n"
        environment = dict(os.environ, GITHUB_SHA='a' * 40, GITHUB_RUN_ID='123456789', GITHUB_RUN_ATTEMPT='2', QT_QPA_PLATFORM='offscreen')
        output = root / (label + '-manifest.json')
        result = subprocess.run(
            [sys.executable, '-c', script, str(root), label, str(output)], cwd=group.ROOT, env=environment, capture_output=True, text=True, timeout=15
        )
        return result, json.loads(output.read_text(encoding='utf-8'))

    def test_independent_shards_keep_fixtures_ids_order_and_release_successful_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_suite(root)
            reports = []
            for label, module in (
                ('desktop', 'test_desktop_synthetic'),
                ('paper', 'test_paper'),
                ('remaining', 'test_future_synthetic'),
                ('trading', 'test_trading_synthetic'),
            ):
                result, report = self.run_shard(root, label)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = [module + '.Fixture.test_a', module + '.Fixture.test_b']
                self.assertEqual(report['selected_ids'], expected)
                self.assertEqual(report['started_ids'], expected)
                self.assertEqual(report['stopped_ids'], expected)
                self.assertEqual(report['tests_run'], 2)
                self.assertEqual(report['core_shard_assignments'][label], expected)
                self.assertEqual(report['local_identity_before'], report['local_identity_after'])
                self.assertEqual(report['source_sha256_after'], report['shard_context']['source_sha256'])
                self.assertEqual(report['shard_context']['head_sha'], 'a' * 40)
                self.assertEqual(report['shard_context']['run_id'], '123456789')
                self.assertEqual(report['shard_context']['run_attempt'], '2')
                for marker in ('MODULE_SETUP:', 'MODULE_TEARDOWN:', 'CLASS_SETUP:', 'CLASS_TEARDOWN:'):
                    self.assertEqual(result.stdout.count(marker), 1, result.stdout)
                    self.assertIn(marker + module, result.stdout)
                self.assertEqual(report['discovery_errors'], [])
                self.assertTrue(report['run_completed'])
                self.assertTrue(report['successful'])
                self.assertEqual(len(report['discovered_ids']), 10)
                reports.append(report)
            for report in reports[1:]:
                for key in ('discovered_ids', 'partitions', 'core_shard_assignments'):
                    self.assertEqual(reports[0][key], report[key])
            selected = sum((report['selected_ids'] for report in reports), [])
            self.assertEqual(len(selected), len(set(selected)))
            self.assertEqual(set(selected), set(reports[0]['partitions']['core']))

    def test_failure_and_skip_remain_owned_by_result_without_release_rewrite(self):
        for outcome, code, field in (("self.fail('synthetic failure')", 1, 'failures'), ("self.skipTest('synthetic skip')", 0, 'skipped')):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_suite(root, outcome=outcome)
                result, report = self.run_shard(root, 'desktop')
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(report['tests_run'], 2)
                self.assertEqual(report['started_ids'], report['selected_ids'])
                self.assertEqual(report['stopped_ids'], report['selected_ids'])
                self.assertEqual(len(report[field]), 1)
                self.assertEqual(report['errors'], [])

    def test_module_fixture_failure_keeps_failure_and_actual_start_counts(self):
        for phase in ('setup', 'teardown'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_suite(root, **{phase: "raise RuntimeError('synthetic fixture failure')"})
                result, report = self.run_shard(root, 'desktop')
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(report['successful'])
                self.assertTrue(report['run_completed'])
                self.assertEqual(len(report['selected_ids']), 2)
                self.assertEqual(report['tests_run'], 0 if phase == 'setup' else 2)
                self.assertEqual(report['started_ids'], [] if phase == 'setup' else report['selected_ids'])
                self.assertEqual(report['stopped_ids'], report['started_ids'])
                self.assertEqual(len(report['errors']), 1)
                self.assertIn('setUpModule' if phase == 'setup' else 'tearDownModule', report['errors'][0])

    def test_source_or_local_identity_change_cannot_leave_success_exit(self):
        for mode in ('local-drift', 'source-drift'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_suite(root)
                result, report = self.run_shard(root, 'desktop', mode=mode)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue(report['run_completed'])
                self.assertFalse(report['successful'])
                self.assertIn('shard_identity_error', report)
                self.assertEqual(report['tests_run'], 2)

    def test_invalid_shard_modes_rejected_before_discovery(self):
        scenarios = (
            ('linux', ['--group', 'core', '--core-shard', 'desktop']),
            ('win32', ['--group', 'all', '--core-shard', 'desktop']),
            ('win32', ['--group', 'research', '--core-shard', 'desktop']),
            ('win32', ['--group', 'core', '--core-shard', 'desktop', '--workers', '2']),
            ('win32', ['--group', 'core', '--core-shard', 'desktop', '--worker-index', '0']),
            ('win32', ['--group', 'core', '--core-shard', 'desktop', '--worker-token', 'a' * 32]),
            ('win32', ['--group', 'core', '--core-shard', 'typo']),
        )
        for platform, arguments in scenarios:
            with self.subTest(platform=platform, arguments=arguments):
                with patch.object(group.sys, 'platform', platform), patch.object(group.unittest.TestLoader, 'discover') as discover:
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                        group.main(arguments + ['--manifest', 'unused.json'])
                    self.assertEqual(error.exception.code, 2)
                    discover.assert_not_called()


class CoreShardReportFileTests(unittest.TestCase):
    CONTEXT = CoreShardReportTests.CONTEXT

    def write_artifacts(self, root):
        downloads = root / 'downloads'
        downloads.mkdir()
        paths = []
        for report in CoreShardReportTests().reports():
            directory = downloads / ('test-inventory-windows-latest-3.11-core-' + report['core_shard'] + '-attempt-2')
            directory.mkdir()
            path = directory / 'test-inventory.json'
            path.write_text(json.dumps(report), encoding='utf-8')
            paths.append(path)
        return downloads, paths

    def run_gate(self, root, downloads, environment=None, *, runtime_effect=None, inventory_effect=None, source_effect=None, local_effect=None):
        env = {'GITHUB_SHA': self.CONTEXT['head_sha'], 'GITHUB_RUN_ID': self.CONTEXT['run_id'], 'GITHUB_RUN_ATTEMPT': self.CONTEXT['run_attempt']}
        if environment is not None:
            env = environment
        manifest = root / 'summary.json'
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(gate, 'portable_source_identity', return_value=self.CONTEXT['source_sha256'], side_effect=source_effect),
            patch.object(gate, 'collect_expected_inventory', side_effect=inventory_effect or CoreShardReportTests().expected_inventory),
            patch.object(gate, 'verify_discovery_runtime', return_value='3.11.14', side_effect=runtime_effect),
            patch.object(gate, 'execution_identity', return_value={'synthetic': 'stable'}, side_effect=local_effect),
        ):
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                code = gate.main(['--reports', str(downloads), '--python-profile', '3.11', '--manifest', str(manifest)])
        return code, json.loads(manifest.read_text(encoding='utf-8'))

    def test_cli_accepts_exact_three_artifacts_and_emits_core_only_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            downloads, _ = self.write_artifacts(root)
            code, summary = self.run_gate(root, downloads)
            self.assertEqual(code, 0)
            self.assertIs(summary['successful'], True)
            self.assertEqual(summary['shards'], 4)
            self.assertEqual(summary['coverage_scope'], 'original core only; research remains a separate mandatory gate')
            self.assertEqual(summary['run_id'], self.CONTEXT['run_id'])
            self.assertEqual(summary['run_attempt'], self.CONTEXT['run_attempt'])

    def assert_missing_or_wrong_attempt_for_any_of_three_artifacts_is_fatal(self):
        for label in ('desktop', 'paper', 'remaining', 'trading'):
            for mode in ('missing', 'wrong-attempt'):
                with self.subTest(shard=label, mode=mode), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    downloads, paths = self.write_artifacts(root)
                    path = next(path for path in paths if '-core-' + label + '-' in path.parent.name)
                    if mode == 'missing':
                        path.unlink()
                        path.parent.rmdir()
                    else:
                        path.parent.rename(Path(str(path.parent).replace('attempt-2', 'attempt-1')))
                    code, summary = self.run_gate(root, downloads)
                    self.assertEqual(code, 1)
                    self.assertIs(summary['successful'], False)

    def test_json_loading_rejects_malformed_duplicate_nonfinite_and_nonobject_reports(self):
        payloads = (
            '{',
            '{"value": 1, "value": 2}',
            '{"nested": {"value": 1, "value": 2}}',
            '{"value": NaN}',
            '{"value": Infinity}',
            '{"value": -Infinity}',
            '[]',
            'null',
            'true',
            '"report"',
        )
        for raw in payloads:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                downloads, paths = self.write_artifacts(root)
                paths[0].write_text(raw, encoding='utf-8')
                with self.assertRaises(ValueError):
                    gate.read_core_report(paths[0])
                code, summary = self.run_gate(root, downloads)
                self.assertEqual(code, 1)
                self.assertIs(summary['successful'], False)
                self.assertNotIn('core_ids', summary)

    def test_missing_oversized_and_invalid_encoding_reports_fail_closed(self):
        for mode in ('missing', 'oversized', 'invalid-encoding'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                downloads, paths = self.write_artifacts(root)
                if mode == 'missing':
                    paths[0].unlink()
                elif mode == 'oversized':
                    paths[0].write_bytes(b' ' * (8 * 1024 * 1024 + 1))
                else:
                    paths[0].write_bytes(b'\xff')
                with self.assertRaises((OSError, ValueError)):
                    gate.read_core_report(paths[0])
                code, summary = self.run_gate(root, downloads)
                self.assertEqual(code, 1)
                self.assertIs(summary['successful'], False)

    def test_missing_extra_wrong_attempt_and_nondirectory_artifacts_fail_closed(self):
        self.assert_missing_or_wrong_attempt_for_any_of_three_artifacts_is_fatal()
        for mode in ('missing', 'extra', 'wrong-attempt', 'nondirectory'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                downloads, paths = self.write_artifacts(root)
                if mode == 'missing':
                    paths[0].unlink()
                    paths[0].parent.rmdir()
                elif mode == 'extra':
                    (downloads / 'unexpected-artifact').mkdir()
                elif mode == 'wrong-attempt':
                    paths[0].parent.rename(Path(str(paths[0].parent).replace('attempt-2', 'attempt-1')))
                else:
                    (downloads / 'unexpected-file').write_text('{}', encoding='utf-8')
                code, summary = self.run_gate(root, downloads)
                self.assertEqual(code, 1)
                self.assertIs(summary['successful'], False)

    def test_independent_discovery_runtime_or_aggregate_drift_cannot_leave_success(self):
        cases = (
            ('runtime rejection', {'runtime_effect': ValueError('wrong runtime')}),
            ('oracle failure', {'inventory_effect': ValueError('discovery failed')}),
            ('oracle import failure', {'inventory_effect': ImportError('unavailable dependency')}),
            ('oracle interrupted', {'inventory_effect': KeyboardInterrupt()}),
            ('source drift', {'source_effect': [self.CONTEXT['source_sha256'], 'f' * 64]}),
            ('local drift', {'local_effect': [{'synthetic': 'before'}, {'synthetic': 'after'}]}),
            ('different full Python', {'runtime_effect': lambda profile: '3.11.15'}),
        )
        for label, changes in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                downloads, _ = self.write_artifacts(root)
                code, summary = self.run_gate(root, downloads)
                self.assertEqual(code, 0)
                self.assertIs(summary['successful'], True)
                code, summary = self.run_gate(root, downloads, **changes)
                self.assertEqual(code, 1)
                self.assertIs(summary['successful'], False)
                self.assertIn('error_type', summary)
                self.assertNotIn('core_ids', summary)

    def test_missing_run_context_cannot_reuse_a_stale_success_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            downloads, _ = self.write_artifacts(root)
            code, summary = self.run_gate(root, downloads)
            self.assertEqual(code, 0)
            self.assertTrue(summary['successful'])
            for missing in ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
                env = {'GITHUB_SHA': self.CONTEXT['head_sha'], 'GITHUB_RUN_ID': self.CONTEXT['run_id'], 'GITHUB_RUN_ATTEMPT': self.CONTEXT['run_attempt']}
                del env[missing]
                with self.subTest(missing=missing):
                    code, summary = self.run_gate(root, downloads, environment=env)
                    self.assertEqual(code, 1)
                    self.assertIs(summary['successful'], False)
                    self.assertNotIn('core_ids', summary)


class CoreShardWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (group.ROOT / '.github/workflows/quantlab.yml').read_text(encoding='utf-8')

    def job(self, name):
        match = re.search(r'(?ms)^  ' + re.escape(name) + r':\n.*?(?=^  [a-z][a-z0-9_-]*:\n|\Z)', self.workflow)
        self.assertIsNotNone(match, 'Missing job: ' + name)
        return match.group(0)

    def step(self, job, name):
        match = re.search(r'(?ms)^      - name: ' + re.escape(name) + r'\n.*?(?=^      - |\Z)', job)
        self.assertIsNotNone(match, 'Missing step: ' + name)
        return match.group(0)

    def test_exact_matrix_keeps_original_linux_and_research_with_six_core_shards(self):
        offline = self.job('offline')
        rows = re.findall(r"^          - \{os: ([^,]+), python: '([^']+)', group: ([^,}]+)(?:, shard: ([^}]+))?\}$", offline, re.MULTILINE)
        expected = [('windows-latest', version, 'core', shard) for version in ('3.11', '3.12') for shard in ('desktop', 'paper', 'remaining', 'trading')]
        expected += [('windows-latest', version, 'research', '') for version in ('3.11', '3.12')]
        self.assertCountEqual(rows, expected)
        self.assertEqual(len(rows), 10)
        self.assertEqual(len(rows), len(set(rows)))
        self.assertIn('timeout-minutes: 15', offline)
        self.assertIn('fail-fast: false', offline)
        self.assertNotIn('continue-on-error', offline)
        self.assertIn("--workers ${{ runner.os == 'Windows' && matrix.group == 'research' && 2 || 1 }}", offline)
        self.assertIn("${{ matrix.shard && format('--core-shard {0}', matrix.shard) || '' }}", offline)
        linux, coverage = self.job('linux-tests'), self.job('linux-coverage')
        linux_rows = re.findall(r"^          - \{python: '([^']+)', group: ([^,}]+)(?:, core_slice: ([^}]+))?\}$", linux, re.MULTILINE)
        linux_expected = [(version, 'core', name) for version in ('3.11', '3.12') for name in ('desktop-trading', 'paper-remaining')]
        linux_expected += [(version, 'research', '') for version in ('3.11', '3.12')]
        self.assertCountEqual(linux_rows, linux_expected)
        self.assertEqual(len(linux_rows), 6)
        self.assertIn("format('--core-slice {0}', matrix.core_slice)", linux)
        self.assertIn('timeout-minutes: 15', linux)
        self.assertIn('fail-fast: false', linux)
        self.assertIn('run: python tools/ui_test_gate.py --profile offline --python-profile ${{ matrix.python }} --group ${{ matrix.group }}', linux)
        self.assertIn('name: offline (ubuntu-latest, ${{ matrix.python }})', coverage)
        self.assertIn('needs: [changes, linux-tests, ruff]', coverage)
        self.assertIn("python: ['3.11', '3.12']", coverage)
        self.assertIn('pattern: linux-test-inventory-${{ matrix.python }}-*-attempt-${{ github.run_attempt }}', coverage)
        self.assertIn('run: python tools/ui_test_gate.py --profile offline --python-profile ${{ matrix.python }} --reports', coverage)
        self.assertNotIn('continue-on-error', linux + coverage)

    def test_subset_check_names_and_artifacts_are_distinct_and_attempt_bound(self):
        offline = self.job('offline')
        name = re.search(r'^    name: (.*)$', offline, re.MULTILINE).group(1)
        self.assertEqual(
            name,
            "${{ matrix.shard && format('offline core {0}', matrix.shard) || "
            "(matrix.group == 'research' && 'offline research' || 'offline') }} "
            "(${{ matrix.os }}, ${{ matrix.python }})",
        )
        self.assertNotIn('name: offline (windows-latest,', offline)
        inventory = self.step(offline, 'Preserve exact-head discovery and selection evidence')
        self.assertIn('if: always()', inventory)
        self.assertIn(
            "name: test-inventory-${{ matrix.os }}-${{ matrix.python }}-${{ matrix.group }}"
            "${{ matrix.shard && format('-{0}-attempt-{1}', matrix.shard, github.run_attempt) || '' }}",
            inventory,
        )
        self.assertIn('if-no-files-found: error', inventory)
        for prefix in ('desktop-auth', 'paper-timing'):
            self.assertIn(
                'name: ' + prefix + '-${{ matrix.os }}-${{ matrix.python }}-${{ matrix.group }}${{ matrix.shard && format(\'-{0}\', matrix.shard) || \'\' }}',
                offline,
            )

    def test_aggregate_owns_exact_mandatory_names_and_reads_each_current_attempt_artifact(self):
        aggregate = self.job('core-coverage')
        self.assertIn('name: offline (windows-latest, ${{ matrix.python }})', aggregate)
        self.assertEqual(self.workflow.count('name: offline (windows-latest, ${{ matrix.python }})'), 1)
        self.assertIn("python: ['3.11', '3.12']", aggregate)
        self.assertIn('needs: [changes, offline, ruff]', aggregate)
        self.assertRegex(aggregate, r"(?m)^    if: always\(\) && needs\.changes\.outputs\.code == 'true'$")
        self.assertIn('timeout-minutes: 15', aggregate)
        self.assertIn('fail-fast: false', aggregate)
        self.assertNotIn('continue-on-error', aggregate)
        download = self.step(aggregate, "Download only this run attempt's original core shard evidence")
        self.assertIn('if: always()', download)
        self.assertIn('pattern: test-inventory-windows-latest-${{ matrix.python }}-core-*-attempt-${{ github.run_attempt }}', download)
        self.assertIn('merge-multiple: false', download)
        self.assertIn('path: dist/validation/core-shards', download)
        validator = self.step(aggregate, 'Require exact complete original core coverage')
        self.assertIn('if: always()', validator)
        self.assertIn(
            'run: python tools/validate_core_shards.py --reports dist/validation/core-shards '
            '--python-profile ${{ matrix.python }} --manifest dist/validation/core-coverage.json',
            validator,
        )

    def test_aggregate_provisions_original_windows_runtime_before_independent_discovery(self):
        offline, aggregate = self.job('offline'), self.job('core-coverage')
        self.assertIn('QT_QPA_PLATFORM: offscreen', aggregate)
        self.assertIn('timeout-minutes: 15', aggregate)
        validator = 'python tools/validate_core_shards.py'
        setup_commands = (
            'python tools/install_sqlite_runtime.py --destination build/sqlite-runtime --report dist/validation/sqlite-runtime.json --github',
            'python -m pip install tzdata==2026.5',
            'python -m pip --isolated install --index-url https://pypi.org/simple --require-hashes '
            '--only-binary=:all: --force-reinstall --no-cache-dir --report qt-install-report.json '
            '-r requirements-qt-ci.lock',
            'python tools/install_desktop_auth.py --report dist/validation/desktop-auth-install.json',
            'python -c "from desktop import _auth_smoke_dependencies; print(_auth_smoke_dependencies())"',
        )
        previous = -1
        for command in setup_commands:
            with self.subTest(command=command):
                self.assertIn(command, offline)
                self.assertEqual(aggregate.count(command), 1)
                position = aggregate.index(command)
                self.assertLess(previous, position)
                self.assertLess(position, aggregate.index(validator))
                previous = position
        self.assertNotIn('continue-on-error', aggregate)

    def test_every_producer_and_independent_discovery_has_full_baseline_history_and_hashlocked_packaging(self):
        install = (
            'python -m pip --isolated install --index-url https://pypi.org/simple --require-hashes '
            '--only-binary=:all: --force-reinstall --no-cache-dir -r requirements-packaging-ci.lock'
        )
        for name in ('offline', 'linux-tests', 'linux-coverage', 'core-coverage', 'ui-tests', 'ui'):
            job = self.job(name)
            with self.subTest(job=name):
                self.assertRegex(job, r'persist-credentials: false\n          fetch-depth: 0\n')
                self.assertEqual(job.count(install), 1)
                self.assertIn('timeout-minutes: 15', job)
                self.assertNotIn('continue-on-error', job)
                runner = (
                    'tools/run_test_group.py'
                    if name == 'offline'
                    else ('tools/validate_core_shards.py' if name == 'core-coverage' else 'tools/ui_test_gate.py')
                )
                self.assertLess(job.index(install), job.index(runner))
        lock = (group.ROOT / 'requirements-packaging-ci.lock').read_text(encoding='utf-8')
        desktop = (group.ROOT / 'requirements-desktop.lock').read_text(encoding='utf-8')
        requirement = r'packaging==26\.3\s*\\\n\s*--hash=sha256:([a-f0-9]{64})'
        self.assertRegex(lock, requirement)
        self.assertEqual(re.search(requirement, lock).group(1), re.search(requirement, desktop).group(1))
        self.assertEqual(re.findall(r'(?m)^[A-Za-z][A-Za-z0-9_-]*==', lock), ['packaging=='])

    def test_aggregate_independently_requires_all_offline_runners_including_research(self):
        aggregate = self.job('core-coverage')
        dependency = self.step(aggregate, 'Require every offline runner including research to have succeeded')
        self.assertIn('if: always()', dependency)
        self.assertIn('OFFLINE_RESULT: ${{ needs.offline.result }}', dependency)
        self.assertIn("sys.exit(0 if os.environ.get('OFFLINE_RESULT') == 'success' else 1)", dependency)
        self.assertNotIn('continue-on-error', dependency)
        upload = self.step(aggregate, 'Preserve complete or failed aggregate coverage evidence')
        self.assertIn('if: always()', upload)
        self.assertIn('name: test-inventory-windows-latest-${{ matrix.python }}-core-aggregate-attempt-${{ github.run_attempt }}', upload)
        self.assertIn('path: dist/validation/core-coverage.json', upload)
        self.assertIn('if-no-files-found: error', upload)


if __name__ == '__main__':
    unittest.main()

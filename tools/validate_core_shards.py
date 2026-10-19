"""Fail closed on incomplete independent-runner core coverage.

This validates original core execution only. Research retains its own mandatory
job and worker gate; the workflow also requires every offline matrix job to pass.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.run_test_group import (
    CORE_SHARDS,
    CORE_SHARD_PLAN,
    RESEARCH_MODULES,
    cases,
    core_shard_for_module,
    execution_identity,
    partition,
    portable_source_identity,
    read_worker_report,
    write_manifest,
)

# Exact original Windows applicability skips, verified against the 70d inventory.
# Missing Qt or any new skip must fail this gate, not silently reduce coverage.
WINDOWS_CORE_SKIPS = {
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
REPORT_LIMIT = 8 * 1024 * 1024


def read_core_report(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > REPORT_LIMIT:
        raise ValueError('Missing, linked or oversized core report')
    result = read_worker_report(path, limit=REPORT_LIMIT)
    if type(result) is not dict:
        raise ValueError('Core report must be an object')
    return result


def _ids(value, label, *, nonempty=True):
    if (
        type(value) is not list
        or (nonempty and not value)
        or any(type(item) is not str or not 1 <= len(item) <= 1024 for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError('Invalid ordered IDs: ' + label)
    return value


def _module(test_id):
    parts = test_id.rsplit('.', 2)
    if len(parts) != 3 or not all(parts):
        raise ValueError('Malformed test ID')
    return parts[0]


def _selection(report):
    discovered = _ids(report.get('discovered_ids'), 'discovered')
    partitions = report.get('partitions')
    if type(partitions) is not dict or set(partitions) != {'core', 'research'}:
        raise ValueError('Missing original partitions')
    core = _ids(partitions['core'], 'core')
    research = _ids(partitions['research'], 'research')
    core_set, research_set = set(core), set(research)
    if (
        core_set & research_set
        or core_set | research_set != set(discovered)
        or [item for item in discovered if item in core_set] != core
        or [item for item in discovered if item in research_set] != research
        or any(_module(item) in RESEARCH_MODULES for item in core)
        or any(_module(item) not in RESEARCH_MODULES for item in research)
    ):
        raise ValueError('Original discovery/partitions are inconsistent')
    assignments = {name: [item for item in core if core_shard_for_module(_module(item)) == name] for name in CORE_SHARDS}
    if not all(assignments.values()):
        raise ValueError('Empty core shard')
    return discovered, partitions, assignments


def collect_expected_inventory(start_directory='tests'):
    """Independent genuine discovery with the same installed runtime; no tests run."""
    loader = unittest.TestLoader()
    suite = loader.discover(start_directory)
    if loader.errors:
        raise ValueError('Independent aggregate discovery failed')
    groups = partition(suite)
    return {
        'discovered_ids': [case.id() for case in cases(suite)],
        'partitions': {name: [case.id() for case in cases(groups[name])] for name in ('core', 'research')},
    }


def validate_core_reports(reports, *, expected_inventory, head_sha, run_id, run_attempt, python_profile, source_sha256):
    if (
        type(head_sha) is not str
        or re.fullmatch('[0-9a-f]{40}', head_sha) is None
        or type(source_sha256) is not str
        or re.fullmatch('[0-9a-f]{64}', source_sha256) is None
        or type(run_id) is not str
        or re.fullmatch('[1-9][0-9]*', run_id) is None
        or type(run_attempt) is not str
        or re.fullmatch('[1-9][0-9]*', run_attempt) is None
        or python_profile not in ('3.11', '3.12')
    ):
        raise ValueError('Invalid expected run/source/profile identity')
    if type(reports) is not list or len(reports) != len(CORE_SHARDS):
        raise ValueError('Exactly ' + str(len(CORE_SHARDS)) + ' core reports required')
    by_shard = {}
    for report in reports:
        if type(report) is not dict or report.get('core_shard') not in CORE_SHARDS:
            raise ValueError('Unknown core shard report')
        name = report['core_shard']
        if name in by_shard:
            raise ValueError('Duplicate core shard report')
        by_shard[name] = report
    first = by_shard[CORE_SHARDS[0]]
    if type(expected_inventory) is not dict or set(expected_inventory) != {'discovered_ids', 'partitions'}:
        raise ValueError('Independent expected inventory required')
    discovered, partitions, assignments = _selection(expected_inventory)
    context = dict(head_sha=head_sha, run_id=run_id, run_attempt=run_attempt, python_profile=python_profile, source_sha256=source_sha256)
    sqlite_version = json.loads((ROOT / 'packaging/sqlite-runtime.json').read_text(encoding='utf-8'))['version']
    python_version = first.get('python')
    if type(python_version) is not str or re.fullmatch(re.escape(python_profile) + r'\.[0-9]+', python_version) is None:
        raise ValueError('Wrong Python runtime profile')
    for name in CORE_SHARDS:
        report = by_shard[name]
        expected = assignments[name]
        if (
            report.get('head_sha') != head_sha
            or report.get('platform') != 'win32'
            or report.get('python') != python_version
            or report.get('group') != 'core'
            or report.get('core_shard_plan') != CORE_SHARD_PLAN
            or report.get('shard_context') != context
            or report.get('source_sha256_after') != source_sha256
            or report.get('discovered_ids') != discovered
            or report.get('partitions') != partitions
            or report.get('core_shard_assignments') != assignments
            or report.get('selected_ids') != expected
            or report.get('discovery_errors') != []
            or report.get('run_completed') is not True
            or report.get('successful') is not True
            or type(report.get('tests_run')) is not int
            or report['tests_run'] != len(expected)
            or report.get('started_ids') != expected
            or report.get('stopped_ids') != expected
            or 'selection_error' in report
            or 'shard_identity_error' in report
            or any(report.get(key) != [] for key in ('failures', 'errors', 'expected_failures', 'unexpected_successes'))
        ):
            raise ValueError('Incomplete, stale or inconsistent core shard: ' + name)
        before, after = report.get('local_identity_before'), report.get('local_identity_after')
        if (
            type(before) is not dict
            or before != after
            or set(before) != {'source_sha256', 'head_sha', 'executable', 'python', 'sqlite_version', 'environment', 'tempfile_gettempdir'}
            or before.get('head_sha') != head_sha
            or before.get('sqlite_version') != sqlite_version
            or type(before.get('python')) is not str
            or not before['python'].split()
            or before['python'].split()[0] != python_version
            or type(before.get('source_sha256')) is not str
            or re.fullmatch('[0-9a-f]{64}', before['source_sha256']) is None
            or any(type(before.get(key)) is not str or not before[key] for key in ('executable', 'tempfile_gettempdir'))
            or type(before.get('environment')) is not dict
            or set(before['environment']) != {'TEMP', 'TMP', 'RUNNER_TEMP', 'QT_QPA_PLATFORM'}
            or before['environment'].get('QT_QPA_PLATFORM') != 'offscreen'
        ):
            raise ValueError('Missing, changed or wrong local runtime identity: ' + name)
        expected_skips = [{'id': test_id, 'reason': WINDOWS_CORE_SKIPS[test_id]} for test_id in expected if test_id in WINDOWS_CORE_SKIPS]
        if report.get('skipped') != expected_skips:
            raise ValueError('Unexpected or missing original applicability skips: ' + name)
    return {
        'coverage_scope': 'original core only; research remains a separate mandatory gate',
        'head_sha': head_sha,
        'run_id': run_id,
        'run_attempt': run_attempt,
        'python_profile': python_profile,
        'source_sha256': source_sha256,
        'core_shard_plan': CORE_SHARD_PLAN,
        'shards': len(CORE_SHARDS),
        'tests_run': len(partitions['core']),
        'core_ids': partitions['core'],
        'successful': True,
    }


def verify_discovery_runtime(python_profile):
    pinned_sqlite = json.loads((ROOT / 'packaging/sqlite-runtime.json').read_text(encoding='utf-8'))['version']
    version = platform.python_version()
    if sys.platform != 'win32' or not version.startswith(python_profile + '.') or sqlite3.sqlite_version != pinned_sqlite:
        raise ValueError('Independent discovery requires the matching pinned Windows runtime')
    return version


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--python-profile', choices=('3.11', '3.12'), required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    summary = {'successful': False, 'coverage_scope': 'original core only'}
    expected_inventory = None
    discovery_identity = None
    try:
        context = {name: os.environ[key] for name, key in (('head_sha', 'GITHUB_SHA'), ('run_id', 'GITHUB_RUN_ID'), ('run_attempt', 'GITHUB_RUN_ATTEMPT'))}
        expected = {'test-inventory-windows-latest-' + args.python_profile + '-core-' + name + '-attempt-' + context['run_attempt'] for name in CORE_SHARDS}
        directories = list(args.reports.iterdir())
        if any(path.is_symlink() or not path.is_dir() for path in directories) or {path.name for path in directories} != expected:
            raise ValueError('Missing or unexpected downloaded core artifacts')
        reports = [read_core_report(path / 'test-inventory.json') for path in sorted(directories)]
        python_version = verify_discovery_runtime(args.python_profile)
        source_before = portable_source_identity()
        discovery_identity = dict(
            context, python_profile=args.python_profile, python=python_version, sqlite_version=sqlite3.sqlite_version, source_sha256=source_before
        )
        local_before = execution_identity('tests')
        expected_inventory = collect_expected_inventory()
        if portable_source_identity() != source_before or execution_identity('tests') != local_before:
            raise ValueError('Aggregate source or local runtime changed during discovery')
        if any(report.get('python') != python_version for report in reports):
            raise ValueError('Shard Python version differs from independent discovery runtime')
        summary = validate_core_reports(
            reports, expected_inventory=expected_inventory, **context, python_profile=args.python_profile, source_sha256=source_before
        )
    except (Exception, KeyboardInterrupt) as error:
        summary['error_type'] = type(error).__name__
        print('Core coverage verification failed: ' + type(error).__name__, file=sys.stderr)
    if discovery_identity is not None:
        summary['independent_discovery_identity'] = discovery_identity
    if expected_inventory is not None:
        summary['independent_expected_inventory'] = expected_inventory
    write_manifest(args.manifest, summary)
    if summary['successful']:
        print('Verified exact original core coverage: ' + str(summary['tests_run']) + ' tests across ' + str(len(CORE_SHARDS)) + ' runners')
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

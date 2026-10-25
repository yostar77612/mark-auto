"""Verify complete same-attempt Linux partitions with strict offline or UI profiles."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLAN = 'ui-original-partitions-v2'
OFFLINE_PLAN = 'linux-offline-original-partitions-v2'
GROUPS = ('core', 'research')
CORE_SLICES = ('desktop-trading', 'paper-remaining')
PRODUCERS = (*CORE_SLICES, 'research')


def producer_assignments(parts):
    from tools.run_test_group import linux_core_slice_for_module

    assigned = {key: [] for key in CORE_SLICES}
    for test_id in parts['core']:
        module, _, _ = test_id.rsplit('.', 2)
        assigned[linux_core_slice_for_module(module)].append(test_id)
    assigned['research'] = parts['research'][:]
    if not all(assigned.values()):
        raise ValueError('Every original Linux producer must contain whole modules')
    return assigned


def context(profile='ui'):
    # Resolve repository helpers after the direct-script import path is established.
    from tools.run_test_group import portable_source_identity

    try:
        streamlit = importlib.metadata.version('streamlit')
    except importlib.metadata.PackageNotFoundError:
        streamlit = None
    pinned = next(
        line.split('==', 1)[1].strip() for line in (ROOT / 'requirements-ui.lock').read_text(encoding='utf-8').splitlines() if line.startswith('streamlit==')
    )
    if profile not in ('ui', 'offline') or (streamlit != pinned if profile == 'ui' else streamlit is not None):
        raise ValueError('UI runtime does not match its committed Streamlit lock')
    core_source = portable_source_identity()
    digest = hashlib.sha256(core_source.encode('ascii'))
    # Include the UI packages as well as the existing portable core/test/workflow identity.
    for package in ('desktop_pages', 'desktop_smoke'):
        for path in sorted((ROOT / package).rglob('*.py')):
            digest.update(path.relative_to(ROOT).as_posix().encode('utf-8') + b'\0' + path.read_bytes() + b'\0')
    return {
        'plan': PLAN if profile == 'ui' else OFFLINE_PLAN,
        'head_sha': os.environ.get('GITHUB_SHA'),
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'source_sha256': digest.hexdigest(),
        'core_source_sha256': core_source,
        'streamlit': streamlit,
    }


def run(selected, destination, profile='ui', core_slice=None):
    # Reuse the original runner after direct-script path setup, without importing Qt here.
    from tools.run_test_group import execution_identity, main as run_group, write_manifest
    from tools.validate_core_shards import read_core_report

    before = execution_identity('tests')
    original = context(profile)
    cases_path = destination.with_suffix('.cases.json')
    # The existing runner preserves whole-module fixtures and all original case limits.
    command = ['--group', selected, '--manifest', str(cases_path)]
    if core_slice is not None:
        command.extend(['--core-slice', core_slice])
    status = run_group(command)
    report = read_core_report(cases_path)
    after = execution_identity('tests')
    report.update(ui_context=original, ui_identity_before=before, ui_identity_after=after)
    if status != 0 or report.get('successful') is not True:
        status = 1
        report['successful'] = False
    if before != after or context(profile) != original:
        status = 1
        report.update(successful=False, identity_error=True)
    write_manifest(destination, report)
    return status


def validate(reports, expected, expected_context, expected_identity, skips, python_profile='3.12'):
    ui = expected_context.get('plan') == PLAN if type(expected_context) is dict else False
    if (
        type(expected_context) is not dict
        or expected_context.get('plan') not in (PLAN, OFFLINE_PLAN)
        or python_profile not in ('3.11', '3.12')
        or (ui and python_profile != '3.12')
        or re.fullmatch('[a-f0-9]{40}', str(expected_context.get('head_sha'))) is None
        or re.fullmatch('[a-f0-9]{64}', str(expected_context.get('source_sha256'))) is None
        or re.fullmatch('[a-f0-9]{64}', str(expected_context.get('core_source_sha256'))) is None
        or any(re.fullmatch('[1-9][0-9]*', str(expected_context.get(key))) is None for key in ('run_id', 'run_attempt'))
        or (not expected_context.get('streamlit') if ui else expected_context.get('streamlit') is not None)
    ):
        raise ValueError('Invalid UI source/run/dependency context')
    if type(reports) is not list or len(reports) != len(PRODUCERS):
        raise ValueError('Exactly three Linux producer reports required')
    discovered, parts = expected['discovered_ids'], expected['partitions']
    if (
        not discovered
        or len(discovered) != len(set(discovered))
        or set(parts) != set(GROUPS)
        or any(not parts[key] or len(parts[key]) != len(set(parts[key])) for key in GROUPS)
        or set(parts['core']) & set(parts['research'])
        or set(parts['core']) | set(parts['research']) != set(discovered)
    ):
        raise ValueError('Invalid independent original discovery')
    streamlit_cases = [test_id for test_id in discovered if test_id.startswith('test_ui.UITests.')]
    if len(streamlit_cases) != 5 or not set(streamlit_cases) <= set(parts['core']):
        raise ValueError('Original five Streamlit cases must be present')
    assigned = producer_assignments(parts)
    by_group = {}
    for row in reports:
        if type(row) is not dict:
            raise ValueError('Invalid Linux producer report')
        key = 'research' if row.get('group') == 'research' else row.get('core_slice')
        if key not in PRODUCERS or key in by_group:
            raise ValueError('Missing, unknown or duplicate Linux producer')
        by_group[key] = row
    if set(by_group) != set(PRODUCERS):
        raise ValueError('Missing Linux producer')
    if type(skips) is not list or len({row['id'] for row in skips}) != len(skips) or (ui and set(streamlit_cases) & {row['id'] for row in skips}):
        raise ValueError('Invalid original Linux applicability skips')
    version = json.loads((ROOT / 'packaging/sqlite-runtime.json').read_text(encoding='utf-8'))['version']
    if expected_identity.get('sqlite_version') != version:
        raise ValueError('Independent UI discovery must use the pinned SQLite runtime')
    for key in PRODUCERS:
        report, selected = by_group[key], assigned[key]
        before, after = report.get('ui_identity_before'), report.get('ui_identity_after')
        if (
            report.get('group') != ('research' if key == 'research' else 'core')
            or report.get('ui_context') != expected_context
            or report.get('head_sha') != expected_context['head_sha']
            or report.get('platform') != 'linux'
            or report.get('python') != platform.python_version()
            or not report['python'].startswith(python_profile + '.')
            or report.get('discovered_ids') != discovered
            or report.get('partitions') != parts
            or report.get('selected_ids') != selected
            or report.get('started_ids') != selected
            or report.get('stopped_ids') != selected
            or report.get('run_completed') is not True
            or report.get('successful') is not True
            or type(report.get('tests_run')) is not int
            or report['tests_run'] != len(selected)
            or any(report.get(field) != [] for field in ('discovery_errors', 'failures', 'errors', 'expected_failures', 'unexpected_successes'))
            or any(field in report for field in ('selection_error', 'identity_error', 'cleanup_error'))
            or type(before) is not dict
            or set(before) != set(expected_identity)
            or before != after
            or before.get('source_sha256') != expected_identity.get('source_sha256')
            or before.get('head_sha') != expected_context['head_sha']
            or before.get('sqlite_version') != version
            or before.get('python') != expected_identity.get('python')
            or type(before.get('environment')) is not dict
            or before['environment'].get('QT_QPA_PLATFORM') != 'offscreen'
            or not before.get('executable')
            or not before.get('tempfile_gettempdir')
        ):
            raise ValueError('Incomplete, failed or inconsistent UI partition: ' + key)
        if key in CORE_SLICES:
            from tools.run_test_group import LINUX_CORE_PLAN

            expected_slice_context = {
                'head_sha': expected_context['head_sha'],
                'run_id': expected_context['run_id'],
                'run_attempt': expected_context['run_attempt'],
                'python_profile': python_profile,
                'source_sha256': expected_context['core_source_sha256'],
            }
            if (
                report.get('core_slice') != key
                or report.get('core_slice_plan') != LINUX_CORE_PLAN
                or report.get('core_slice_assignments') != {name: assigned[name] for name in CORE_SLICES}
                or report.get('core_slice_context') != expected_slice_context
                or report.get('source_sha256_after') != expected_context['core_source_sha256']
                or report.get('local_identity_before') != before
                or report.get('local_identity_after') != before
                or 'shard_identity_error' in report
            ):
                raise ValueError('Invalid whole-module Linux core slice proof: ' + key)
        elif any(name in report for name in ('core_slice', 'core_slice_plan', 'core_slice_context', 'core_slice_assignments')):
            raise ValueError('Research cannot substitute for a core slice')
        if report.get('skipped') != [row for row in skips if row['id'] in set(selected)]:
            raise ValueError('Unexpected UI skip; original Streamlit cases may not be skipped')
    return {
        'successful': True,
        'ui_context': expected_context,
        'tests_run': len(discovered),
        'groups': list(GROUPS),
        'producers': list(PRODUCERS),
        'streamlit_cases': streamlit_cases,
    }


def main(argv=None):
    # Discovery uses the same existing helpers once direct-script path setup has completed.
    from tools.run_test_group import execution_identity, write_manifest
    from tools.validate_core_shards import collect_expected_inventory, read_core_report

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=GROUPS)
    parser.add_argument('--core-slice', choices=CORE_SLICES)
    parser.add_argument('--reports', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--profile', choices=('ui', 'offline'), default='ui')
    parser.add_argument('--python-profile', choices=('3.11', '3.12'), default='3.12')
    args = parser.parse_args(argv)
    if (args.group is None) == (args.reports is None):
        parser.error('Choose one UI group or independent verification')
    if args.core_slice is not None and args.group != 'core':
        parser.error('A core slice requires the original core group')
    if args.profile == 'ui' and args.python_profile != '3.12':
        parser.error('The complete UI profile requires Python 3.12')
    os.chdir(ROOT)
    summary = {'successful': False}
    try:
        if args.group:
            return run(args.group, args.manifest, args.profile, args.core_slice)
        before, original = execution_identity('tests'), context(args.profile)
        expected = collect_expected_inventory()
        if execution_identity('tests') != before or context(args.profile) != original:
            raise ValueError('Independent discovery changed its runtime or sources')
        prefix = 'ui' if args.profile == 'ui' else 'linux'
        reports = [read_core_report(path) for path in sorted(args.reports.rglob(prefix + '-test-inventory.json'))]
        skip_name = 'ui_linux_applicability_skips.json' if args.profile == 'ui' else 'linux_offline_applicability_skips.json'
        skips = json.loads((ROOT / 'tests/fixtures' / skip_name).read_text(encoding='utf-8'))
        summary = validate(reports, expected, original, before, skips, args.python_profile)
        summary['independent_discovery_identity'] = before
        print('Verified exact complete ' + args.profile + ' coverage: ' + str(summary['tests_run']) + ' cases, same source/run/attempt')
    except (Exception, KeyboardInterrupt) as error:
        summary['error_type'] = type(error).__name__
        print('UI gate failed: ' + type(error).__name__, file=sys.stderr)
    write_manifest(args.manifest, summary)
    return 0 if summary['successful'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

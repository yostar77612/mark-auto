"""Run exact, module-granularity partitions of the ordinary unittest discovery.

Windows timings from the 12e088f full-suite run put saved-pool/research and
walk-forward integration in a separate job. New modules default to core; no
case is excluded. Module boundaries preserve unittest module/class fixtures.
"""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import tempfile
import time
import uuid
import sys
import unittest
from itertools import islice

# Running this file directly must have the same application import path as
# `python -m unittest discover -s tests`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESEARCH_MODULES = frozenset(
    {
        "test_saved_candidate_pool",
        "test_desktop_saved_candidate_pool",
        "test_research",
        "test_walk_forward",
        "test_desktop_walk_forward",
        "test_desktop_walk_forward_runtime",
        "test_desktop_walk_forward_smoke",
        "test_desktop_walk_forward_terminal",
        "test_result_reference_layers",
    }
)
GROUPS = ("all", "core", "research")

# Seven existing paper modules account for 344.37 s of the observed 773.35 s
# Windows 3.11 remaining run at a9bcdb2. Rebalance whole modules only.
PAPER_MODULES = frozenset(
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
CORE_SHARDS = ('desktop', 'paper', 'remaining', 'trading')
CORE_SHARD_PLAN = 'core-modules-v4'
# c054 Windows remaining log: these two additional UI modules account for
# approximately 118 seconds. Keep them whole and retain the fifteen-minute cap.
LEGACY_DESKTOP_MODULES = frozenset(
    {
        'test_analysis_recovery_ui',
        'test_market_history_ui',
        'test_ui_operations_registry',
        'test_ui_redesign_data_results',
    }
)
LINUX_CORE_SLICES = ('desktop-trading', 'paper-remaining')
LINUX_CORE_PLAN = 'linux-core-whole-modules-v1'


def core_shard_for_module(module):
    if module in RESEARCH_MODULES:
        raise ValueError('Research modules cannot enter a core shard')
    # Keep every module intact; the new platform has its own unchanged-budget
    # runner rather than consuming the legacy remaining runner's fifteen minutes.
    if module.startswith(('test_trading_', 'test_broker_', 'test_runtime_context_')) or module == 'test_quality_gate_v2_boundaries':
        return 'trading'
    if module in PAPER_MODULES:
        return 'paper'
    return 'desktop' if module.startswith('test_desktop_') or module in LEGACY_DESKTOP_MODULES else 'remaining'


def linux_core_slice_for_module(module):
    return 'desktop-trading' if core_shard_for_module(module) in ('desktop', 'trading') else 'paper-remaining'


def linux_core_assignments(suite):
    selected = list(cases(suite))
    expected = [case.id() for case in selected]
    assigned = {name: [] for name in LINUX_CORE_SLICES}
    for case in selected:
        assigned[linux_core_slice_for_module(type(case).__module__)].append(case.id())
    union = sum(assigned.values(), [])
    if not all(assigned.values()) or len(expected) != len(set(expected)) or len(union) != len(set(union)) or set(union) != set(expected):
        raise ValueError('Linux slices must cover each original core case exactly once')
    return assigned


def core_shard_assignments(suite):
    selected = list(cases(suite))
    expected = [case.id() for case in selected]
    assigned = {name: [] for name in CORE_SHARDS}
    for case in selected:
        assigned[core_shard_for_module(type(case).__module__)].append(case.id())
    flattened = sum(assigned.values(), [])
    if not all(assigned.values()) or len(expected) != len(set(expected)) or len(flattened) != len(set(flattened)) or set(flattened) != set(expected):
        raise ValueError('Core shards must cover each selected case exactly once')
    return assigned


def _ordered_source_bytes(paths):
    """Fresh raw reads in input order, with at most four reads/results in flight."""
    paths = iter(paths)
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='source-identity') as pool:
        pending = deque(pool.submit(path.read_bytes) for path in islice(paths, 4))
        try:
            while pending:
                yield pending.popleft().result()
                for path in islice(paths, 1):
                    pending.append(pool.submit(path.read_bytes))
        finally:
            # A read exception still propagates; never return a partial digest.
            # Join running reads before returning so no source worker outlives it.
            for future in pending:
                future.cancel()


def portable_source_identity(start_directory='tests'):
    """Source bytes plus relative names; host paths remain separate evidence."""
    # Resolve both sides: Windows temporary roots can contain 8.3 aliases.
    root = ROOT.resolve()
    paths = set(root.glob('*.py')) | set(root.glob('requirements*'))
    paths |= {root / 'pyproject.toml', root / '.gitattributes'}
    for directory in ('quantlab', 'desktop_pages', 'desktop_smoke', 'desktop_trading', 'tests', 'tools', 'packaging', '.github/workflows'):
        paths |= {
            path
            for path in (root / directory).rglob('*')
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in {'.py', '.ps1', '.cs', '.json', '.gz', '.csv', '.yml', '.yaml', '.txt'}
        }
    paths |= set(Path(start_directory).resolve().glob('*.py'))
    named = {}
    for path in paths:
        path = path.resolve()
        if not path.is_file():
            continue
        try:
            name = path.relative_to(root).as_posix()
        except ValueError:
            name = '__test_suite__/' + path.name
        if name in named and named[name] != path:
            raise ValueError('Ambiguous portable source path')
        named[name] = path
    digest = hashlib.sha256()
    ordered = sorted(named.items())
    for (name, _), raw in zip(ordered, _ordered_source_bytes(path for _, path in ordered)):
        digest.update(name.encode('utf-8') + b'\0' + str(len(raw)).encode('ascii') + b'\0' + raw)
    return digest.hexdigest()


# Two test parents, not two total processes: tests retain their bounded children.
# Whole modules preserve every module/class fixture and intra-module order.
RESEARCH_WORKERS = (
    frozenset(
        {
            'test_walk_forward',
            'test_desktop_saved_candidate_pool',
            'test_desktop_walk_forward',
            'test_desktop_walk_forward_runtime',
            'test_desktop_walk_forward_smoke',
            'test_result_reference_layers',
        }
    ),
    frozenset({'test_saved_candidate_pool', 'test_research', 'test_desktop_walk_forward_terminal'}),
)
WINDOWS_RESEARCH_SKIPS = {
    'test_desktop_walk_forward_smoke.WalkForwardSmokeProcessTests.test_full_smoke_preserves_all_gates_settings_and_120_second_budget': 'Frozen installer harness owns isolated Windows profile smoke',
    'test_desktop_walk_forward_smoke.WalkForwardSmokeProcessTests.test_omitted_module_malformed_result_reference_and_worker_failure_fail_overall': 'Frozen installer harness owns isolated Windows profile smoke',
    'test_research.BoundedWorkerCleanupTests.test_real_worker_success_waits_for_owned_kill_and_reap': 'SIGTERM/SIGKILL lifecycle requires POSIX',
    'test_research.BoundedWorkerCleanupTests.test_sequential_backtest_and_generator_hangs_leave_no_child_residue': 'Backtest patch requires fork',
    'test_research.ResearchTests.test_hanging_backtest_is_killed': 'Patch inheritance uses POSIX fork; production default is spawn',
    'test_research.ResearchTests.test_worker_memory_limit_rejects_large_allocation': 'RLIMIT_AS verification requires Linux',
}


def worker_assignments(suite):
    if len(RESEARCH_WORKERS) != 2 or RESEARCH_WORKERS[0] & RESEARCH_WORKERS[1] or set().union(*RESEARCH_WORKERS) != RESEARCH_MODULES:
        raise ValueError('Worker modules must cover the original research group exactly')
    selected = list(cases(suite))
    assigned = [[case.id() for case in selected if type(case).__module__ in modules] for modules in RESEARCH_WORKERS]
    expected = [case.id() for case in selected]
    union = assigned[0] + assigned[1]
    if not all(assigned) or len(union) != len(set(union)) or set(union) != set(expected):
        raise ValueError('Workers must cover each selected case exactly once')
    return assigned


def execution_identity(start_directory):
    # All application/test Python sources, including imported fixture helpers.
    paths = set(ROOT.glob('*.py')) | set((ROOT / 'quantlab').glob('*.py'))
    paths |= set((ROOT / 'tests').glob('*.py')) | {Path(__file__).resolve()}
    paths |= set(Path(start_directory).resolve().glob('*.py'))
    digest = hashlib.sha256()
    ordered = sorted(paths)
    for path, raw in zip(ordered, _ordered_source_bytes(ordered)):
        digest.update(str(path).encode('utf-8') + b'\0' + raw + b'\0')
    return {
        'source_sha256': digest.hexdigest(),
        'head_sha': os.environ.get('GITHUB_SHA'),
        'executable': sys.executable,
        'python': sys.version,
        'sqlite_version': sqlite3.sqlite_version,
        'environment': {name: os.environ.get(name) for name in ('TEMP', 'TMP', 'RUNNER_TEMP', 'QT_QPA_PLATFORM')},
        'tempfile_gettempdir': tempfile.gettempdir(),
    }


def write_manifest(path, value):
    # A sibling unique temporary avoids partial/stale success evidence.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_worker_report(path, *, limit=None):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate worker report key')
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError('Nonfinite worker report value')

    if limit is None:
        raw = path.read_text(encoding='utf-8')
    else:
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Worker report exceeds bound')
        raw = raw.decode('utf-8')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def validate_worker_reports(parent, assignments, reports, tokens):
    if len(reports) != 2 or len(tokens) != 2 or len(assignments) != 2:
        raise ValueError('Exactly two worker reports required')
    selected = assignments[0] + assignments[1]
    if (
        not all(assignments)
        or len(selected) != len(set(selected))
        or len(parent['selected_ids']) != len(selected)
        or set(selected) != set(parent['selected_ids'])
    ):
        raise ValueError('Worker assignments do not cover the original selection exactly once')
    for index, (expected, report, token) in enumerate(zip(assignments, reports, tokens)):
        if (
            type(report) is not dict
            or type(report.get('worker_index')) is not int
            or report.get('worker_index') != index
            or report.get('worker_token') != token
            or report.get('identity') != parent['identity']
            or report.get('group') != 'research'
            or report.get('discovered_ids') != parent['discovered_ids']
            or report.get('partitions') != parent['partitions']
            or report.get('selected_ids') != expected
            or report.get('discovery_errors') != []
            or report.get('run_completed') is not True
            or report.get('successful') is not True
            or type(report.get('tests_run')) is not int
            or report['tests_run'] != len(expected)
            or report.get('started_ids') != expected
            or report.get('stopped_ids') != expected
            or any(report.get(key) != [] for key in ('failures', 'errors', 'expected_failures', 'unexpected_successes'))
        ):
            raise ValueError('Incomplete, failed or inconsistent worker report: ' + str(index))
        expected_skips = [{'id': test_id, 'reason': WINDOWS_RESEARCH_SKIPS[test_id]} for test_id in expected if test_id in WINDOWS_RESEARCH_SKIPS]
        if report.get('skipped') != expected_skips:
            raise ValueError('Unexpected or missing original applicability skips: ' + str(index))


def new_owned_tree(pid):
    from quantlab.desktop_runtime import _WindowsProcessTree

    return _WindowsProcessTree(pid)


def tree_empty(tree):
    from ctypes import wintypes as w

    class Accounting(ctypes.Structure):
        _fields_ = [(name, ctypes.c_int64) for name in ('TotalUserTime', 'TotalKernelTime', 'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')]
        _fields_ += [(name, w.DWORD) for name in ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')]

    kernel = tree.kernel
    kernel.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
    info = Accounting()
    if not tree.handle or not kernel.QueryInformationJobObject(tree.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
        raise RuntimeError('Cannot verify original worker Job ownership')
    return info.ActiveProcesses == 0


def run_parallel(args, manifest, research):
    started = time.monotonic()
    assignments = worker_assignments(research)
    manifest.update(
        workers=2,
        identity=execution_identity(args.start_directory),
        worker_assignments=assignments,
        worker_results=[],
        owned_workers=[],
        successful=False,
        aggregate_id_order='worker index, then original intra-worker discovery order; not wall-clock chronology',
    )
    tokens = [uuid.uuid4().hex for _ in assignments]
    work = Path(tempfile.mkdtemp(prefix='research-workers-', dir=args.manifest.parent))
    manifest['worker_evidence_directory'] = str(work)
    write_manifest(args.manifest, manifest)
    owned = []
    problem = None
    try:
        for index in range(2):
            output = work / ('worker-' + str(index) + '.json')
            log = work / ('worker-' + str(index) + '.log')
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                '--group',
                'research',
                '--manifest',
                str(output),
                '--start-directory',
                args.start_directory,
                '--worker-index',
                str(index),
                '--worker-token',
                tokens[index],
            ]
            with log.open('wb') as stream:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stream, stderr=stream)
            item = {'process': process, 'tree': None, 'output': output, 'log': log}
            owned.append(item)  # Retain original process even if Job assignment fails.
            item['tree'] = new_owned_tree(process.pid)
            # No discovery/test executes until the original Job owns the child.
            process.stdin.write((tokens[index] + '\n').encode('ascii'))
            process.stdin.flush()
            process.stdin.close()
        # The existing workflow's original 15-minute JOB cap remains authoritative;
        # no independent/restarted 15-minute allowance or per-case limit is added.
        while any(item['process'].poll() is None for item in owned):
            time.sleep(0.05)
        reports = manifest['worker_results']
        natural_exits = True
        for item in owned:
            natural = item['process'].returncode == 0 and tree_empty(item['tree'])
            manifest['owned_workers'].append({'exit_code': item['process'].returncode, 'natural_exit_and_quiescent': natural})
            natural_exits = natural_exits and natural
            if not item['output'].exists():
                reports.append({'report_error': 'missing worker report'})
            elif item['output'].stat().st_size > 8 * 1024 * 1024:
                reports.append({'report_error': 'worker report exceeds bound'})
            else:
                try:
                    reports.append(read_worker_report(item['output']))
                except (ValueError, OSError) as error:
                    reports.append({'report_error': type(error).__name__})
        if not natural_exits:
            raise ValueError('Worker failed or left descendants; cleanup cannot convert this to PASS')
        validate_worker_reports(manifest, assignments, reports, tokens)
        if execution_identity(args.start_directory) != manifest['identity']:
            raise ValueError('Sources or runtime identity changed during execution')
        manifest.update(run_completed=True, successful=True, tests_run=sum(report['tests_run'] for report in reports))
        for key in ('started_ids', 'stopped_ids', 'failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes'):
            manifest[key] = [value for report in reports for value in report[key]]
    except BaseException as error:
        problem = type(error).__name__ + ': ' + str(error)
        manifest.update(successful=False, supervision_error=problem)
    finally:
        for item in owned:
            process, tree = item['process'], item['tree']
            try:
                if tree is not None:
                    if not tree_empty(tree):
                        manifest['successful'] = False
                        tree.stop_and_join()
                    if not tree_empty(tree):
                        raise RuntimeError('Worker descendants remain active')
                elif process.poll() is None:
                    process.kill()  # Startup gate was never released.
                process.wait(timeout=4)
            except BaseException as error:
                manifest.update(successful=False, cleanup_error=type(error).__name__ + ': ' + str(error))
            finally:
                try:
                    if process.stdin is not None and not process.stdin.closed:
                        process.stdin.close()
                except OSError as error:
                    manifest.update(successful=False, cleanup_error=type(error).__name__ + ': ' + str(error))
                try:
                    if tree is not None:
                        tree.close()
                except BaseException as error:
                    manifest.update(successful=False, cleanup_error=type(error).__name__ + ': ' + str(error))
            # Separate logs avoid blocked PIPEs and interleaved unittest lines.
            with item['log'].open('r', encoding='utf-8', errors='replace') as stream:
                for chunk in iter(lambda: stream.read(65536), ''):
                    sys.stderr.write(chunk)
        manifest['cleanup_confirmed'] = 'cleanup_error' not in manifest
        manifest['wall_seconds'] = time.monotonic() - started
        write_manifest(args.manifest, manifest)
    if manifest.get('successful') is True and manifest['cleanup_confirmed']:
        print('\n----------------------------------------------------------------------', file=sys.stderr)
        print('Ran ' + str(manifest['tests_run']) + ' tests in ' + format(manifest['wall_seconds'], '.3f') + 's', file=sys.stderr)
        print('Aggregate of 2 owned workers; original research selection unchanged', file=sys.stderr)
        print('OK (skipped=' + str(len(manifest['skipped'])) + ')', file=sys.stderr)
        return 0
    print('Research worker execution FAILED: ' + (problem or manifest.get('cleanup_error', 'forced cleanup')), file=sys.stderr)
    return 1


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def partition(suite):
    """Validate exact coverage before execution; retain discovery order."""
    discovered = list(cases(suite))
    ids = [case.id() for case in discovered]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Discovery must be nonempty with unique test IDs")
    selected = {"core": [], "research": []}
    for case in discovered:
        group = "research" if type(case).__module__ in RESEARCH_MODULES else "core"
        selected[group].append(case)
    core = {case.id() for case in selected["core"]}
    research = {case.id() for case in selected["research"]}
    if not core or not research or core & research or core | research != set(ids):
        raise ValueError("Core/research must be nonempty, disjoint, and cover discovery exactly")
    return {"all": suite, **{name: unittest.TestSuite(items) for name, items in selected.items()}}


class RecordingResult(unittest.TextTestResult):
    """Record actual starts separately: failed fixtures can prevent starts."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_ids = []
        self.stopped_ids = []

    def startTest(self, test):
        self.started_ids.append(test.id())
        super().startTest(test)

    def stopTest(self, test):
        self.stopped_ids.append(test.id())
        super().stopTest(test)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=GROUPS, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--start-directory", default="tests")
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--core-shard', choices=CORE_SHARDS)
    parser.add_argument('--core-slice', choices=LINUX_CORE_SLICES)
    parser.add_argument('--worker-index', type=int, choices=(0, 1), help=argparse.SUPPRESS)
    parser.add_argument('--worker-token', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.core_slice is not None and (
        sys.platform != 'linux'
        or args.group != 'core'
        or args.workers != 1
        or args.core_shard is not None
        or args.worker_index is not None
        or args.worker_token is not None
    ):
        parser.error('Core slices are supported only for independent Linux core runners')
    if args.core_shard is not None and (
        sys.platform != 'win32' or args.group != 'core' or args.workers != 1 or args.worker_index is not None or args.worker_token is not None
    ):
        parser.error('Core shards are supported only for independent Windows core runners')
    if args.workers == 2 and (sys.platform != 'win32' or args.group != 'research'):
        parser.error('Two workers are supported only for Windows research')
    if args.worker_index is not None or args.worker_token is not None:
        if args.worker_index is None or not args.worker_token or len(args.worker_token) != 32 or args.workers != 1 or args.group != 'research':
            parser.error('Invalid owned-worker arguments')
        if sys.stdin.buffer.readline(34) != (args.worker_token + '\n').encode('ascii'):
            parser.error('Owned-worker startup gate was not released')
    loader = unittest.TestLoader()
    suite = loader.discover(args.start_directory)
    manifest = {
        "head_sha": os.environ.get("GITHUB_SHA"),
        "python": platform.python_version(),
        "platform": sys.platform,
        "group": args.group,
        "discovered_ids": [case.id() for case in cases(suite)],
        "selected_ids": [],
        "partitions": {},
        "discovery_errors": list(loader.errors),
        "run_completed": False,
        "started_ids": [],
    }
    try:
        if loader.errors:
            raise ValueError("Discovery failed:\n" + "\n".join(loader.errors))
        groups = partition(suite)
        manifest["partitions"] = {name: [case.id() for case in cases(groups[name])] for name in ("core", "research")}
        manifest["selected_ids"] = [case.id() for case in cases(groups[args.group])]
        if args.core_shard is not None:
            assignments = core_shard_assignments(groups['core'])
            selected = assignments[args.core_shard]
            groups['core'] = unittest.TestSuite(case for case in cases(groups['core']) if case.id() in set(selected))
            manifest.update(
                selected_ids=selected,
                core_shard=args.core_shard,
                core_shard_plan=CORE_SHARD_PLAN,
                core_shard_assignments=assignments,
                shard_context={
                    'head_sha': os.environ.get('GITHUB_SHA'),
                    'run_id': os.environ.get('GITHUB_RUN_ID'),
                    'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
                    'python_profile': str(sys.version_info.major) + '.' + str(sys.version_info.minor),
                    'source_sha256': portable_source_identity(args.start_directory),
                },
                local_identity_before=execution_identity(args.start_directory),
            )
        if args.worker_index is not None:
            assignments = worker_assignments(groups['research'])
            selected = assignments[args.worker_index]
            groups['research'] = unittest.TestSuite(case for case in cases(groups['research']) if case.id() in set(selected))
            manifest.update(
                selected_ids=selected, worker_index=args.worker_index, worker_token=args.worker_token, identity=execution_identity(args.start_directory)
            )
        if args.core_slice is not None:
            assignments = linux_core_assignments(groups['core'])
            selected = assignments[args.core_slice]
            groups['core'] = unittest.TestSuite(case for case in cases(groups['core']) if case.id() in set(selected))
            manifest.update(
                selected_ids=selected,
                core_slice=args.core_slice,
                core_slice_plan=LINUX_CORE_PLAN,
                core_slice_assignments=assignments,
                core_slice_context={
                    'head_sha': os.environ.get('GITHUB_SHA'),
                    'run_id': os.environ.get('GITHUB_RUN_ID'),
                    'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
                    'python_profile': str(sys.version_info.major) + '.' + str(sys.version_info.minor),
                    'source_sha256': portable_source_identity(args.start_directory),
                },
                local_identity_before=execution_identity(args.start_directory),
            )
    except ValueError as error:
        manifest["selection_error"] = str(error)
        print(error, file=sys.stderr)
        status = 2
    else:
        status = None
    # Written before running tests so a failure/cancellation still has inventory.
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(args.manifest, manifest)
    if status is not None:
        return status
    # Keep only the selected owner after inventory validation. Otherwise the
    # discovery suite and alternate partitions retain completed TestCase objects
    # (including native windows) after unittest removes them from this suite.
    selected_suite = groups[args.group]
    del suite, groups
    if args.workers == 2:
        return run_parallel(args, manifest, selected_suite)
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(selected_suite)
    manifest.update(
        {
            "run_completed": True,
            "started_ids": result.started_ids,
            "stopped_ids": result.stopped_ids,
            "tests_run": result.testsRun,
            "successful": result.wasSuccessful(),
            "failures": [test.id() for test, _ in result.failures],
            "errors": [test.id() for test, _ in result.errors],
            "skipped": [{"id": test.id(), "reason": reason} for test, reason in result.skipped],
            "expected_failures": [test.id() for test, _ in result.expectedFailures],
            "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        }
    )
    if args.core_shard is not None or args.core_slice is not None:
        manifest['local_identity_after'] = execution_identity(args.start_directory)
        manifest['source_sha256_after'] = portable_source_identity(args.start_directory)
        if (
            manifest['local_identity_after'] != manifest['local_identity_before']
            or manifest['source_sha256_after'] != manifest['shard_context' if args.core_shard is not None else 'core_slice_context']['source_sha256']
        ):
            manifest['successful'] = False
            manifest['shard_identity_error'] = 'Source or local runtime identity changed during tests'
    write_manifest(args.manifest, manifest)
    return 0 if manifest['successful'] else 1


if __name__ == "__main__":
    raise SystemExit(main())

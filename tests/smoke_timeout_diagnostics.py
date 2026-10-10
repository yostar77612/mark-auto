"""Failure-only synthetic smoke evidence; never copy raw output or user state."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid
from types import SimpleNamespace

from quantlab.desktop_runtime import JobManager, _WindowsProcessTree

PREFIX = 'SMOKE_DIAGNOSTIC '
STATUSES = {'passed', 'failed', 'completed', 'running', 'cancelled'}


def read_json(path):
    try:
        if path.stat().st_size > 262144:
            return None
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def report_summary(value):
    if not isinstance(value, dict):
        return {'available': False}
    result = {'available': True}
    if type(value.get('status')) is str and value['status'] in STATUSES:
        result['status'] = value['status']
    for key in ('timed_out', 'worker_completed', 'backtest_completed', 'campaign_completed', 'paper_completed'):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    cleanup = value.get('worker_cleanup', {})
    if isinstance(cleanup, dict) and type(cleanup.get('verified')) is bool:
        result['worker_cleanup_verified'] = cleanup['verified']
    for key in ('steps', 'walk_forward_smoke', 'market_smoke', 'history_smoke'):
        item = value.get(key)
        if isinstance(item, list):
            result[key + '_count'] = len(item)
        elif isinstance(item, dict):
            result[key] = report_summary(item)
    return result


def output_summary(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', errors='replace')
    raw = raw or ''
    events, stacks = [], []
    for line in raw.splitlines():
        if line.startswith(PREFIX):
            try:
                value = json.loads(line[len(PREFIX):])
            except ValueError:
                continue
            if not isinstance(value, dict):
                continue
            event = {}
            if type(value.get('stage')) is str and value['stage'] in {'start_requested', 'started', 'terminal', 'cleanup_start', 'cleanup_end', 'main_return'}:
                event['stage'] = value['stage']
            for name in ('pid', 'elapsed_ms', 'status'):
                if type(value.get(name)) is int:
                    event[name] = value[name]
            if type(value.get('operation')) is str and value['operation'] in {'ui_demo', 'ui_backtest', 'ui_select', 'ui_campaign', 'ui_paper_reconcile', 'ui_paper_replay', 'ui_paper_kill', 'ui_market_refresh', 'ui_walk_forward_preview', 'ui_walk_forward_run', 'ui_walk_forward_read'}:
                event['operation'] = value['operation']
            if type(value.get('event')) is str and value['event'] in {'result', 'error', 'cancelled'}:
                event['event'] = value['event']
            if type(value.get('verified')) is bool:
                event['verified'] = value['verified']
            if 'stage' in event:
                events.append(event)
        match = re.match(r'\s*File "[^"\n]*[/\\]([A-Za-z_][A-Za-z_0-9]*\.py)", line (\d+) in ([A-Za-z_][A-Za-z_0-9]*)$', line)
        if match:
            stacks.append({'module': match[1], 'line': int(match[2]), 'function': match[3]})
    return {'characters': len(raw), 'events': events[-100:], 'stack_frames': stacks[-30:]}


def run_smoke_process(command, *, cwd, env, report, pidfile, writes, process_can_run,
                      artifact_dir, timeout=40):
    """Retain the original gate; kill/join owned processes before timeout evidence."""
    command = list(command)
    # No application code can spawn before Windows Job Object admission.
    command[2] = 'import sys; sys.stdin.read(1)\n' + command[2]
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=sys.platform != 'win32')
    tree = None
    try:
        if sys.platform == 'win32':
            tree = _WindowsProcessTree(process.pid)
        try:
            stdout, stderr = process.communicate('x', timeout=timeout)
            # Check before closing the outer kill-on-close handle: containment
            # must not turn leaked workers into a false successful smoke.
            completed_pids = read_json(pidfile)
            if isinstance(completed_pids, list):
                if any(process_can_run(pid) for pid in completed_pids
                       if type(pid) is int and pid > 0):
                    if tree is not None:
                        tree.stop_and_join()
                    else:
                        owner = SimpleNamespace(tree=None, _operation='ui_walk_forward_run')
                        for pid in completed_pids:
                            if type(pid) is int and pid > 0:
                                JobManager._join_descendants(owner, pid)
                    raise AssertionError('Smoke exited with a live recorded worker')
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired as expired:
            if sys.platform != 'win32':
                try: os.killpg(process.pid, signal.SIGSTOP)
                except ProcessLookupError: pass
            pids = read_json(pidfile)
            pids = [pid for pid in pids if type(pid) is int and pid > 0] if isinstance(pids, list) else []
            def liveness(pid):
                try: return process_can_run(pid)
                except (OSError, AssertionError): return None
            before = {str(pid): liveness(pid) for pid in pids}
            cleanup_error = None
            try:
                if tree is not None:
                    tree.stop_and_join()
                else:
                    # Each recorded JobManager worker owns its own process group.
                    # Freeze the launcher before snapshotting/killing those groups.
                    owned = set(pids)
                    if sys.platform.startswith('linux'):
                        for entry in Path('/proc').iterdir():
                            if not entry.name.isdigit(): continue
                            try: fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                            except (FileNotFoundError, ProcessLookupError): continue
                            if int(fields[1]) == process.pid: owned.add(int(entry.name))
                    owner = SimpleNamespace(tree=None, _operation='ui_walk_forward_run')
                    for pid in owned:
                        JobManager._join_descendants(owner, pid)
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                stdout, stderr = process.communicate(timeout=6)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                cleanup_error = type(error).__name__
                stdout, stderr = expired.stdout, expired.stderr
            after = {str(pid): liveness(pid) for pid in pids}
            audited = []
            try:
                if writes.stat().st_size <= 262144:
                    audited = [report_summary(json.loads(line)) for line in writes.read_text(encoding='utf-8').splitlines()]
            except (OSError, ValueError):
                pass
            evidence = {'scope': 'synthetic smoke timeout diagnostic; not acceptance',
                'timeout_seconds': timeout, 'report': report_summary(read_json(report)),
                'report_writes': audited, 'worker_alive_before': before, 'worker_alive_after': after,
                'cleanup_verified': cleanup_error is None and process.poll() is not None and all(value is False for value in after.values()),
                'cleanup_error_type': cleanup_error, 'stdout': output_summary(stdout), 'stderr': output_summary(stderr)}
            artifact_dir.mkdir(parents=True, exist_ok=True)
            target = artifact_dir / ('smoke-timeout-' + uuid.uuid4().hex + '.json')
            target.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
            raise AssertionError('Smoke exceeded unchanged deadline; sanitized evidence: ' + json.dumps(evidence)) from None
    finally:
        try:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=6)
        finally:
            if tree is not None:
                tree.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

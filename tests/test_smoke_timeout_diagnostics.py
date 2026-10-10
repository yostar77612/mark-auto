"""Controlled timeout evidence and owned child cleanup; not native acceptance."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from quantlab.desktop_runtime import RuntimeSafetyError

from tests.smoke_timeout_diagnostics import output_summary, run_smoke_process
from tests.test_desktop_smoke_terminal import process_can_run


class SmokeTimeoutDiagnosticTests(unittest.TestCase):
    def test_timeout_preserves_only_sanitized_evidence_and_stops_real_subtree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, pids, writes = (root / name for name in ('report.json', 'pids.json', 'writes.jsonl'))
            worker_code = '''import json, subprocess, sys, time
from pathlib import Path
from quantlab.desktop_runtime import _WindowsProcessTree
grandchild = subprocess.Popen([sys.executable, '-c', 'import sys,time; sys.stdin.read(1); time.sleep(60)'], stdin=subprocess.PIPE, text=True)
inner_tree = _WindowsProcessTree(grandchild.pid) if sys.platform == 'win32' else None
grandchild.stdin.write('x'); grandchild.stdin.flush(); grandchild.stdin.close()
target = Path(sys.argv[1]); staging = target.with_suffix('.tmp')
staging.write_text(json.dumps(grandchild.pid), encoding='utf-8'); staging.replace(target)
time.sleep(60)
'''
            code = '''import json, os, subprocess, sys, time
from pathlib import Path
nested_pid = Path(sys.argv[2]).with_name('grandchild.json')
child = subprocess.Popen([sys.executable, '-c', sys.argv[4], str(nested_pid)], start_new_session=sys.platform != 'win32')
Path(sys.argv[2]).write_text(json.dumps([child.pid]), encoding='utf-8')
while not nested_pid.exists(): time.sleep(.01)
Path(sys.argv[2]).write_text(json.dumps([child.pid, json.loads(nested_pid.read_text())]), encoding='utf-8')
value = {'status': 'failed', 'worker_cleanup': {'verified': False}, 'secret': 'DO_NOT_RETAIN', 'data_dir': 'private/user/root'}
Path(sys.argv[1]).write_text(json.dumps(value), encoding='utf-8')
Path(sys.argv[3]).write_text(json.dumps(value)+'\\n', encoding='utf-8')
print('DO_NOT_RETAIN', flush=True)
print('SMOKE_DIAGNOSTIC ' + json.dumps({'stage':'started', 'operation':'ui_campaign', 'pid':child.pid, 'secret':'DO_NOT_RETAIN'}), file=sys.stderr, flush=True)
time.sleep(60)
'''
            with self.assertRaisesRegex(AssertionError, 'unchanged deadline') as error:
                run_smoke_process([sys.executable, '-c', code, str(report), str(pids), str(writes), worker_code],
                    cwd=root, env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])), report=report, pidfile=pids, writes=writes,
                    process_can_run=process_can_run, artifact_dir=root / 'artifacts', timeout=5)
            artifacts = list((root / 'artifacts').glob('smoke-timeout-*.json'))
            self.assertEqual(len(artifacts), 1)
            raw = artifacts[0].read_text(encoding='utf-8')
            self.assertNotIn('DO_NOT_RETAIN', raw + str(error.exception))
            self.assertNotIn('private/user/root', raw)
            value = json.loads(raw)
            self.assertEqual(value['timeout_seconds'], 5)
            self.assertTrue(value['cleanup_verified'])
            self.assertEqual(value['report']['status'], 'failed')
            self.assertEqual(len(value['report_writes']), 1)
            self.assertEqual(len(value['worker_alive_before']), 2)
            self.assertTrue(all(value['worker_alive_before'].values()))
            self.assertFalse(any(value['worker_alive_after'].values()))
            self.assertEqual(value['stderr']['events'][0]['operation'], 'ui_campaign')
            self.assertTrue(all(not process_can_run(pid) for pid in json.loads(pids.read_text())))

    def test_normal_exit_cannot_hide_a_live_worker_and_still_cleans_it_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pids = root / 'pids.json'
            code = """import json, subprocess, sys
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=sys.platform != 'win32')
Path(sys.argv[1]).write_text(json.dumps([child.pid]), encoding='utf-8')
"""
            with self.assertRaisesRegex(AssertionError, 'live recorded worker'):
                run_smoke_process([sys.executable, '-c', code, str(pids)], cwd=root,
                    env=os.environ.copy(), report=root / 'report', pidfile=pids,
                    writes=root / 'writes', process_can_run=process_can_run,
                    artifact_dir=root / 'artifacts', timeout=2)
            self.assertTrue(all(not process_can_run(pid) for pid in json.loads(pids.read_text())))

    def test_non_object_and_malformed_diagnostic_lines_are_ignored(self):
        value = output_summary('\n'.join('SMOKE_DIAGNOSTIC ' + text for text in
            ('[]', 'null', '1', '"text"', '{', '{"stage": [], "operation": {}}')))
        self.assertEqual(value['events'], [])

    def test_windows_admission_failure_does_not_release_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / 'application-ran'
            code = "from pathlib import Path; Path(__import__('sys').argv[1]).touch()"
            with patch('tests.smoke_timeout_diagnostics.sys.platform', 'win32'), \
                    patch('tests.smoke_timeout_diagnostics._WindowsProcessTree', side_effect=RuntimeSafetyError('Isolation unavailable')):
                with self.assertRaises(RuntimeSafetyError):
                    run_smoke_process([sys.executable, '-c', code, str(marker)], cwd=root,
                        env=os.environ.copy(), report=root / 'report', pidfile=root / 'pids',
                        writes=root / 'writes', process_can_run=process_can_run,
                        artifact_dir=root / 'artifacts', timeout=2)
            self.assertFalse(marker.exists())

    def test_output_drops_raw_paths_messages_and_unrecognized_fields(self):
        result = output_summary('password=DO_NOT_RETAIN\n  File "/private/user/desktop.py", line 770 in main\n')
        self.assertEqual(result['stack_frames'], [{'module': 'desktop.py', 'line': 770, 'function': 'main'}])
        self.assertNotIn('DO_NOT_RETAIN', json.dumps(result))
        self.assertNotIn('/private', json.dumps(result))

"""Opt-in real spawn-worker benchmark; stdlib harness, no default-suite timing tests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def summary(values):
    return dict(median=statistics.median(values), min=min(values), max=max(values))


def measured_worker(sender, gate, operation, payload, root, bootstrap, job_id, *args):
    entered = time.perf_counter()
    import quantlab.desktop_runtime as runtime

    imported = time.perf_counter()
    totals = {'runtime_import': imported - entered, 'worker_entered': entered}
    starts = {}
    names = {'_worker_operation_executor': 'executor_import', 'run_backtest': 'compute', 'write_json': 'result_disk_write'}

    def profile(frame, event, arg):
        label = names.get(frame.f_code.co_name)
        if label and frame.f_globals.get('__name__', '').startswith(('quantlab.', 'desktop_ui')):
            key = id(frame)
            if event == 'call':
                starts[key] = time.perf_counter()
            elif event == 'return' and key in starts:
                totals[label] = totals.get(label, 0.0) + time.perf_counter() - starts.pop(key)

    class Sender:
        def send_bytes(self, raw):
            started = time.perf_counter()
            sender.send_bytes(raw)
            totals['ipc_write'] = totals.get('ipc_write', 0.0) + time.perf_counter() - started

        def close(self):
            sender.close()

    sys.setprofile(profile)
    try:
        runtime._job_worker(Sender(), gate, operation, payload, root, bootstrap, job_id, *args)
    finally:
        sys.setprofile(None)
        totals['qt_loaded'] = any(name.startswith('PySide6') for name in sys.modules)
        Path(root, job_id + '.timing.json').write_text(json.dumps(totals), encoding='utf-8')


def job_sample(paths):
    import quantlab.desktop_runtime as runtime
    from quantlab.core import to_dict
    from quantlab.reporting import demo_config

    manager = runtime.JobManager(paths)
    try:
        started = time.perf_counter()
        with patch.object(runtime, '_job_worker', measured_worker):
            job_id = manager.start('ui_backtest', {'family': 'trend', 'config': to_dict(demo_config())})
        launched = time.perf_counter()
        events = []
        while manager.active:
            events.extend(manager.poll())
            if time.perf_counter() - started > 60:
                raise RuntimeError('Benchmark exceeded its 60 second bound')
            time.sleep(0.001)
        elapsed = time.perf_counter() - started
        if not any(event['type'] == 'result' for event in events) or any(event['type'] == 'error' for event in events):
            raise RuntimeError('Real UI worker failed: ' + repr(events))
        sample = json.loads(Path(paths.root, job_id + '.timing.json').read_text(encoding='utf-8'))
        sample['subprocess_start'] = sample.pop('worker_entered') - started
        sample['launch_call'] = launched - started
        sample['total'] = elapsed
        return sample
    finally:
        manager.close()


def import_report(module, limit):
    result = subprocess.run([sys.executable, '-X', 'importtime', '-c', 'import ' + module], cwd=ROOT, capture_output=True, text=True, check=True)
    rows = []
    for line in result.stderr.splitlines():
        fields = line.removeprefix('import time:').split('|')
        if len(fields) == 3 and fields[0].strip().isdigit():
            rows.append({'self_us': int(fields[0]), 'cumulative_us': int(fields[1]), 'module': fields[2].strip()})
    return sorted(rows, key=lambda row: row['self_us'], reverse=True)[:limit]


def runtime_import_sample():
    code = (
        'import time,json,sys; t=time.perf_counter(); import quantlab.desktop_runtime; '
        'print(json.dumps(dict(seconds=time.perf_counter()-t, qt_loaded=any(n.startswith("PySide6") for n in sys.modules))))'
    )
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--json', type=Path, help='also save the complete JSON report')
    parser.add_argument('--importtime', action='store_true', help='include top 15 self-time import contributors')
    options = parser.parse_args()
    if options.repeats < 5:
        parser.error('--repeats must be at least 5')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from quantlab.desktop_runtime import AppPaths
    from quantlab.reporting import synthetic_dataset, save_dataset, demo_config
    from quantlab.strategies import builtin_strategies
    from quantlab.research import _run_bounded, _evaluate_split

    # Inherited permissions avoid Windows sandbox mode-0700 temp ACL artifacts.
    folder = Path(tempfile.gettempdir()) / ('markauto-latency-' + uuid.uuid4().hex)
    folder.mkdir(mode=0o755)
    try:
        paths = AppPaths(folder).ensure()
        data = synthetic_dataset(960)
        save_dataset(data, paths.state / 'dataset.json')
        samples, errors = [], []
        for _ in range(options.repeats):
            try:
                samples.append(job_sample(paths))
            except (OSError, RuntimeError) as exc:
                errors.append({'phase': 'job_worker', 'error': str(exc), 'type': type(exc).__name__})
        wf = []
        for _ in range(options.repeats):
            started = time.perf_counter()
            try:
                _run_bounded(
                    _evaluate_split, (data, builtin_strategies()[0], demo_config()), deadline=time.monotonic() + 30, config={'process_start_method': 'spawn'}
                )
                wf.append(time.perf_counter() - started)
            except (OSError, RuntimeError) as exc:
                errors.append({'phase': 'walk_forward_evaluation', 'error': str(exc), 'type': type(exc).__name__})
        imports = [runtime_import_sample() for _ in range(options.repeats)]
        report = {
            'python': sys.version,
            'platform': platform.platform(),
            'bars': 960,
            'repeats': options.repeats,
            'method': 'spawn; real JobManager and _job_worker, profiling enabled',
            'samples': samples,
            'seconds': {key: summary([row[key] for row in samples]) for key in samples[0] if key != 'qt_loaded'} if samples else {},
            'walk_forward_evaluation_seconds': summary(wf) if wf else None,
            'walk_forward_samples': wf,
            'runtime_import_seconds': summary([row['seconds'] for row in imports]),
            'import_samples': imports,
            'errors': errors,
        }
        if options.importtime:
            report['importtime'] = {module: import_report(module, 15) for module in ('quantlab.desktop_runtime', 'desktop_ui')}
        raw = json.dumps(report, indent=2)
        if options.json:
            options.json.write_text(raw + '\n', encoding='utf-8')
        print(raw)
        print('\nstage                            median(s)       min(s)       max(s)')
        for key, values in {
            **report['seconds'],
            'runtime_import': report['runtime_import_seconds'],
            'walk_forward_evaluation': report['walk_forward_evaluation_seconds'],
        }.items():
            if values is not None:
                print(f"{key:32} {values['median']:11.6f} {values['min']:12.6f} {values['max']:12.6f}")
            else:
                print(f'{key:32} unavailable')
    finally:
        shutil.rmtree(folder)
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())

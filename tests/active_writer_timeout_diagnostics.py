"""Bounded test-only writer timing; no data, SQL, paths or acceptance changes."""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sys
import threading
import time
import uuid

from tests.smoke_timeout_diagnostics import WORKER_PHASES, instrument_walk_forward

MAX_REPORT_BYTES = 32768
MAX_FUNCTION_LABEL = 128

PHASES = WORKER_PHASES | {'writer.body', 'wfo.normalize', 'json.encode', 'export.write', 'export.replace'}
STACK_MODULES = frozenset(
    {
        'active_writer_timeout_diagnostics.py',
        'smoke_timeout_diagnostics.py',
        'test_desktop_walk_forward.py',
        'test_walk_forward.py',
        'desktop_walk_forward.py',
        'desktop_ui.py',
        'walk_forward.py',
        'core.py',
        'research.py',
        'desktop_runtime.py',
        'pathlib.py',
        'threading.py',
        'contextlib.py',
        'thread.py',
        '_base.py',
        'mock.py',
        'encoder.py',
        '__init__.py',
    }
)


class WriterDiagnostics:
    """Inclusive timings filtered to the original writer, excluding the reader."""

    def __init__(self):
        self.started = time.perf_counter()
        self.writer_ident = None
        self.lock = threading.RLock()
        self.active = []
        self.timings = {}

    def run(self, function, *args, **kwargs):
        self.writer_ident = threading.get_ident()
        with self.measure('writer.body'):
            return function(*args, **kwargs)

    @contextmanager
    def measure(self, phase):
        if threading.get_ident() != self.writer_ident:
            yield
            return
        if phase not in PHASES:
            raise ValueError('Unknown writer diagnostic phase')
        started, cpu = time.perf_counter(), time.thread_time()
        with self.lock:
            self.active.append((phase, started))
        try:
            yield
        finally:
            ended, cpu_ended = time.perf_counter(), time.thread_time()
            with self.lock:
                self.active.pop()
                calls, seconds, cpu_seconds = self.timings.get(phase, (0, 0.0, 0.0))
                self.timings[phase] = (calls + 1, seconds + ended - started, cpu_seconds + cpu_ended - cpu)

    def snapshot(self):
        with self.lock:
            now = time.perf_counter()
            value = {
                'scope': 'synthetic active writer timeout diagnostic; not acceptance',
                'elapsed_ms': int((now - self.started) * 1000),
                'timing_semantics': 'inclusive overlapping phases; completed calls only; writer thread only',
                'active': [{'phase': name, 'elapsed_ms': int((now - started) * 1000)} for name, started in self.active[-32:]],
                'timings': [
                    {'phase': name, 'calls': calls, 'elapsed_ms': int(seconds * 1000), 'cpu_ms': int(cpu * 1000)}
                    for name, (calls, seconds, cpu) in sorted(self.timings.items())
                ],
            }
        frames = []
        frame = sys._current_frames().get(self.writer_ident)
        # Do not extract source lines, arguments or locals, or retain frames.
        try:
            for _ in range(60):
                if frame is None or len(frames) >= 30:
                    break
                module = Path(frame.f_code.co_filename).name
                function = frame.f_code.co_name
                if module in STACK_MODULES and len(function) <= MAX_FUNCTION_LABEL and re.fullmatch('[A-Za-z_][A-Za-z_0-9]*', function):
                    frames.append({'module': module, 'line': frame.f_lineno, 'function': function})
                frame = frame.f_back
        finally:
            del frame
        value['writer_stack'] = frames
        return value

    def report_timeout(self, *, artifact_dir, evaluations_started, future_done, timeout_seconds=10):
        """Report before executor shutdown; failures here never mask TimeoutError."""
        try:
            if type(timeout_seconds) is not int or timeout_seconds not in (10, 20):
                raise ValueError('Unknown original writer completion gate')
            evidence = self.snapshot()
            evidence.update(timeout_seconds=timeout_seconds, expected_evaluations=33, evaluations_started=evaluations_started, future_done=future_done)
            encoded = json.dumps(evidence, indent=2) + '\n'
            if len(encoded.encode('utf-8')) > MAX_REPORT_BYTES:
                raise ValueError('Writer diagnostic byte limit exceeded')
            # Emit first, so subsequent executor shutdown cannot erase the point
            # at which the original completion gate actually failed.
            print('ACTIVE_WRITER_TIMEOUT_DIAGNOSTIC ' + json.dumps(evidence), file=sys.stderr, flush=True)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            target = artifact_dir / ('smoke-timeout-active-writer-' + uuid.uuid4().hex + '.json')
            target.write_text(encoded, encoding='utf-8')
        except Exception as error:
            try:
                print('ACTIVE_WRITER_DIAGNOSTIC_ERROR ' + type(error).__name__, file=sys.stderr, flush=True)
            except Exception:
                pass


@contextmanager
def observe_writer():
    """Reuse unchanged-call instrumentation, with additional export/encode clocks."""
    from quantlab import walk_forward

    timings = WriterDiagnostics()
    restores = []

    def wrap(owner, name, phase):
        original = getattr(owner, name)

        def measured(*args, **kwargs):
            with timings.measure(phase):
                return original(*args, **kwargs)

        restores.append((owner, name, original))
        setattr(owner, name, measured)

    try:
        with instrument_walk_forward(timings):
            wrap(walk_forward, 'to_dict', 'wfo.normalize')
            wrap(json, 'dumps', 'json.encode')
            wrap(Path, 'write_text', 'export.write')
            wrap(walk_forward, 'replace_file', 'export.replace')
            yield timings
    finally:
        for owner, name, original in reversed(restores):
            setattr(owner, name, original)

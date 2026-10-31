"""Original synthetic smoke observation only; no gate, SQL or workload changes."""

from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

from quantlab.research_core.adapters.job_worker import _job_worker as _original_job_worker
from tests.smoke_timeout_diagnostics import PREFIX, WorkerTimings, instrument_walk_forward

OPERATIONS = frozenset({'ui_campaign', 'ui_paper_reconcile', 'ui_paper_replay', 'ui_paper_kill'})
MAX_REPORT_BYTES = 32768


class GenericTimings(WorkerTimings):
    """Inclusive phase clocks; CPU excludes spawned evaluation children."""

    def __init__(self, operation):
        if operation not in OPERATIONS:
            raise ValueError('Unknown original smoke operation')
        super().__init__()
        self.operation = operation
        self.cpu = {}
        self.instrumentation_ready = False
        self.instrumentation_failed = False

    @contextmanager
    def measure(self, phase):
        cpu = time.thread_time()
        try:
            with super().measure(phase):
                yield
        finally:
            with self.lock:
                self.cpu[phase] = self.cpu.get(phase, 0.0) + time.thread_time() - cpu

    def snapshot(self):
        with self.lock:
            value = super().snapshot()
            value['operation'] = self.operation
            value['instrumentation_ready'] = self.instrumentation_ready
            value['instrumentation_failed'] = self.instrumentation_failed
            for row in value['timings']:
                row['cpu_ms'] = int(self.cpu.get(row['phase'], 0.0) * 1000)
            return value


@contextmanager
def instrument_generic_operations(timings):
    """Observe the original durable operations; preserve every call and argument."""
    from quantlab import research
    from quantlab.paper import PaperBroker
    from quantlab.paper_replay import PaperReplay

    with ExitStack() as stack:
        stack.enter_context(instrument_walk_forward(timings))

        def wrap(owner, name, phase, *, context=False):
            original = getattr(owner, name)
            if context:

                @contextmanager
                def measured(*args, **kwargs):
                    with timings.measure(phase), original(*args, **kwargs) as value:
                        yield value
            else:

                def measured(*args, **kwargs):
                    with timings.measure(phase):
                        return original(*args, **kwargs)

            stack.enter_context(patch.object(owner, name, measured))

        for owner, name, phase in (
            (research, 'run_campaign', 'campaign.run'),
            (research, '_run_bounded', 'campaign.worker'),
            (research, '_reserve_holdout', 'campaign.reserve'),
            (PaperBroker, '__init__', 'broker.initialize'),
            (PaperBroker, '_restore', 'broker.restore'),
            (PaperBroker, 'reconcile', 'broker.reconcile'),
            (PaperBroker, 'set_kill_switch', 'broker.kill'),
            (PaperReplay, '__init__', 'replay.initialize'),
            (PaperReplay, 'step', 'replay.step'),
            (Path, 'write_text', 'export.write'),
            (Path, 'replace', 'export.replace'),
            (research, 'replace_file', 'export.replace'),
        ):
            wrap(owner, name, phase)
        wrap(PaperBroker, '_transaction', 'broker.transaction', context=True)
        wrap(PaperReplay, '_db', 'replay.transaction', context=True)
        yield


def diagnosed_generic_worker(sender, gate, operation, payload, root, bootstrap, job_id, reconciliation_admitted=False, *worker_options):
    """Keep the actual ownership gate and worker; retain its failure-time phases."""
    if operation not in OPERATIONS:
        return _original_job_worker(sender, gate, operation, payload, root, bootstrap, job_id, reconciliation_admitted, *worker_options)
    timings = GenericTimings(operation)
    stop = threading.Event()
    stack = ExitStack()
    reporter = None
    admitted = False

    def restore():
        try:
            stack.close()
        except Exception:
            timings.instrumentation_failed = True

    def report():
        try:
            encoded = json.dumps(timings.snapshot())
            if len(encoded.encode('utf-8')) <= MAX_REPORT_BYTES:
                print(PREFIX + encoded, file=sys.stderr, flush=True)
        except Exception:
            pass  # Observation cannot replace or retry the original operation.

    def periodic():
        while not stop.wait(1):
            report()

    class Gate:
        def wait(self, *args, **kwargs):
            nonlocal admitted, reporter
            # Delegate the original wait once, after the real worker's setsid.
            accepted = gate.wait(*args, **kwargs)
            if accepted:
                admitted = True
                try:
                    report()
                    reporter = threading.Thread(target=periodic, daemon=True)
                    reporter.start()
                    with timings.measure('worker.instrumentation'):
                        stack.enter_context(instrument_generic_operations(timings))
                    timings.instrumentation_ready = True
                except Exception:
                    timings.instrumentation_failed = True
                    restore()  # Partial setup must not modify the operation.
            return accepted

    try:
        with timings.measure('worker.body'):
            return _original_job_worker(sender, Gate(), operation, payload, root, bootstrap, job_id, reconciliation_admitted, *worker_options)
    finally:
        try:
            restore()
        finally:
            stop.set()
            if reporter is not None and reporter.ident is not None:
                # Do not leave an in-flight diagnostic writer at process exit.
                # The unchanged outer 40s/EOF gate contains blocked output too.
                reporter.join()
            if admitted:
                report()

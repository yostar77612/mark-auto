"""Test/developer lifetime for source engines; never controls a discovered host.

Windows venv launchers redirect to another PID. Select the actual interpreter
and the current installed import paths before Popen, preserving the product's
strict retained-PID/session check. Runtime/IPC/engine code is otherwise real.
"""

import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime import context_client
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.ipc import read_session


def source_python() -> str:
    return str(Path(getattr(sys, '_base_executable', sys.executable)).resolve())


def source_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment['PYTHONPATH'] = os.pathsep.join(str(Path(item or '.').resolve()) for item in sys.path)
    return environment


class OwnedEngineProcesses:
    """Register before setup can fail; close all retained engines independently.

    This scope changes only context_client's source Popen launcher, not global
    sys.executable, subprocess, process identity checks or any runtime facade.
    Reused hosts are never registered and are therefore never shut down here.
    """

    def __init__(self):
        self.owned: list[tuple[subprocess.Popen, RuntimeLaunch]] = []
        self.closed: list[dict] = []
        self._closed = False

    def __enter__(self):
        proxy = SimpleNamespace(Popen=self._start, DEVNULL=subprocess.DEVNULL, CREATE_NO_WINDOW=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self._launcher = patch.object(context_client, 'subprocess', proxy)
        self._launcher.start()
        return self

    def _start(self, arguments, **options):
        arguments = list(arguments)
        root = Path(arguments[arguments.index('--trading-engine') + 1]).resolve()
        environment = Environment(arguments[arguments.index('--trading-environment') + 1])
        account = arguments[arguments.index('--trading-account') + 1]
        profile = Path(arguments[arguments.index('--trading-profile') + 1]) if '--trading-profile' in arguments else None
        launch = RuntimeLaunch(root, environment, profile, account)
        arguments[0] = source_python()
        options['env'] = source_environment()
        process = subprocess.Popen(arguments, **options)
        self.owned.append((process, launch))
        return process

    def _shutdown(self, process, launch):
        # A startup timeout can happen before publication. Cleanup keeps the
        # existing bounded 15s startup allowance, then the normal 15s exit wait.
        deadline = time.monotonic() + 15
        while process.poll() is None:
            try:
                session = read_session(launch.root)
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    raise DomainError('startup_failed', 'owned test engine never published its control endpoint') from None
                time.sleep(0.02)
                continue
            if session.process_id != process.pid:
                raise DomainError('startup_workspace_busy', 'refuse to control a different session owner')
            facade = context_client.ContextIpcFacade(launch)
            outcome = 'NORMAL'
            try:
                for _ in range(3):
                    state = facade.snapshot()
                    if state.engine_state == 'CLOSED':
                        break
                    receipt = facade.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, state.version))
                    if receipt.accepted:
                        break
                    if receipt.code != 'state_conflict':
                        raise DomainError(receipt.code)
                else:
                    raise DomainError('state_conflict', 'owned test shutdown remained stale')
            except FileNotFoundError:
                # Another normal shutdown may remove the endpoint before the
                # retained process exits. Only its verified zero exit can pass.
                outcome = 'ALREADY_EXITED'
            if process.wait(timeout=15) != 0:
                raise DomainError('operation_failed', 'owned test engine exited abnormally')
            return outcome
        process.wait(timeout=15)
        return 'ALREADY_EXITED'

    def close(self):
        if self._closed:
            return
        self._closed = True
        errors = []
        for process, launch in reversed(self.owned):
            outcome = 'FAILED'
            try:
                outcome = self._shutdown(process, launch)
            except (DomainError, OSError, EOFError, ValueError, subprocess.TimeoutExpired) as exc:
                errors.append(f'{process.pid}: {type(exc).__name__}')
                # Failure containment is limited to the exact retained native
                # Popen. It is reported as failure, never passing acceptance.
                try:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired) as stop_error:
                    errors.append(f'{process.pid}: retained handle cleanup {type(stop_error).__name__}')
            finally:
                if context_client._STARTED.get(launch.root) is process and process.poll() is not None:
                    context_client._STARTED.pop(launch.root)
                self.closed.append({'pid': process.pid, 'root': str(launch.root), 'shutdown': outcome, 'exit_code': process.poll()})
        if errors:
            raise RuntimeError('owned engine cleanup failed: ' + '; '.join(errors))

    def __exit__(self, *_):
        try:
            self.close()
        finally:
            self._launcher.stop()

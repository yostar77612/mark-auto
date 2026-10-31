"""Desktop job implementation extracted without changing safety control flow."""

from __future__ import annotations
import importlib
import multiprocessing as mp
import os
from pathlib import Path
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from quantlab.job_stages import normalize_stage, stage_from_traceback
from quantlab.shared.runtime_errors import RuntimeSafetyError
from quantlab.research_core.domain.job_protocol import DEFAULT_OPERATION_REGISTRAR, DEFAULT_WORKER_STORAGE_FACTORY, UI_OPERATIONS


class _OperationExecutorRegistry:
    def __init__(self):
        self._executor = None

    def register(self, executor):
        if not callable(executor):
            raise RuntimeSafetyError('Operation executor must be callable')
        if self._executor is not None and self._executor is not executor:
            raise RuntimeSafetyError('A different operation executor is already registered')
        self._executor = executor

    def executor(self):
        if self._executor is None:
            raise RuntimeSafetyError('No operation executor is registered')
        return self._executor


_executor_registry = _OperationExecutorRegistry()
_executor_registrar = None
_worker_registrar_import = ContextVar("markauto_worker_registrar_import", default=False)


def register_operation_executor(executor):
    """Same callable is idempotent; replacement fails closed."""
    _executor_registry.register(executor)


def _operation_executor():
    return _executor_registry.executor()


def register_operation_executor_factory(registrar):
    """Register a module:callable entry point resolving the worker executor.

    The callable is the executor itself, rather than an eagerly built UI object.
    A fresh worker registry is required by multiprocessing spawn. The same entry
    point is idempotent; changing an established entry point fails closed.
    """
    global _executor_registrar
    if type(registrar) is not str or re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*', registrar) is None:
        raise RuntimeSafetyError('Invalid operation executor registrar')
    if _executor_registrar is not None and _executor_registrar != registrar:
        raise RuntimeSafetyError('A different operation executor registrar is already registered')
    _executor_registrar = registrar


def _worker_operation_executor(registrar):
    if not registrar:
        raise RuntimeSafetyError('No operation executor is registered')
    module, name = registrar.split(':')
    registry = _OperationExecutorRegistry()
    token = _worker_registrar_import.set(True)
    try:
        registry.register(getattr(importlib.import_module(module), name))
    finally:
        _worker_registrar_import.reset(token)
    return registry.executor()


def _is_worker_registrar_import():
    """True only while the worker resolves its explicit operation registrar.

    The role is process-local and never conveyed in an untrusted job payload.
    Ordinary GUI imports keep their full public surface and Qt implementations.
    """
    # A direct registrar lookup in the GUI process must not poison its cached
    # desktop_app.shell.main_window module with the child-only, nonconstructible GUI bases.
    return _worker_registrar_import.get() and mp.parent_process() is not None


@contextmanager
def _worker_recovery_guard(paths, operation, job_id, helper_nonce):
    # Keep operation-specific dependencies out of module startup.
    from quantlab.analysis_recovery import admission, operation_guard, read_launch, SOURCE_WRITERS, ANALYSIS_STARTS, WORKSPACE_MUTATIONS

    if operation == 'ui_analysis_run' and helper_nonce is not None:
        with admission(paths):
            launch = read_launch(paths, job_id, for_admission=True)
            if launch['helper_nonce'] != helper_nonce:
                raise RuntimeSafetyError('Original analysis helper generation differs')
            yield
    elif operation in SOURCE_WRITERS | ANALYSIS_STARTS | WORKSPACE_MUTATIONS or operation == 'ui_analysis_reconcile':
        with operation_guard(paths, operation):
            yield
    else:
        yield


def _job_worker(
    sender,
    gate,
    operation,
    payload,
    root,
    bootstrap,
    job_id,
    reconciliation_admitted=False,
    helper_nonce=None,
    operation_registrar=DEFAULT_OPERATION_REGISTRAR,
):
    if sys.platform != 'win32':
        os.setsid()
    if not gate.wait(15):
        return

    module, name = DEFAULT_WORKER_STORAGE_FACTORY.split(':')
    storage_port = getattr(importlib.import_module(module), name)()
    failure_stage = 'prepare_operation'

    def emit(kind, **values):
        nonlocal failure_stage
        if 'stage' in values:
            failure_stage = normalize_stage(values['stage'])
            values['stage'] = failure_stage
        sender.send_bytes(storage_port.validate_payload({'job_id': job_id, 'type': kind, **values}))

    try:
        emit('progress', message='Working', progress=0)
        paths = storage_port.worker_paths(Path(root), Path(bootstrap) if bootstrap else None)
        with _worker_recovery_guard(paths, operation, job_id, helper_nonce):
            if operation in UI_OPERATIONS:
                executor = _worker_operation_executor(operation_registrar)
                failure_stage = 'run_operation'
                result = executor(
                    operation,
                    payload,
                    paths,
                    emit=emit,
                    descendants_stopped=reconciliation_admitted is True
                    and operation in ('ui_chatgpt_reconcile', 'ui_walk_forward_reconcile', 'ui_analysis_reconcile'),
                )
            else:
                # Keep operation-specific dependencies out of module startup.
                from argparse import Namespace

                # Keep operation-specific dependencies out of module startup.
                from quantlab.__main__ import execute

                stage = paths.state / 'runs' / (job_id + '.partial')
                stage.mkdir(parents=True, exist_ok=False)
                args = {'command': operation, 'output': stage, **payload}
                if 'dataset' in args:
                    args['dataset'] = Path(args['dataset'])
                args.setdefault('config', None)
                args.setdefault('family', 'trend')
                args.setdefault('bars', 240)
                failure_stage = 'run_campaign' if operation == 'campaign' else 'run_operation'
                execute(Namespace(**args))
                failure_stage = 'write_result'
                final = stage.with_suffix('')
                os.replace(stage, final)
                result = {'output': str(final)}
        # Keep operation-specific dependencies out of module startup.
        from quantlab.core import to_dict

        failure_stage = 'write_result'
        result = to_dict(result)
        try:
            storage_port.validate_payload(result)
        except RuntimeSafetyError:
            result = {'output': str(paths.state), 'summary': 'Completed; detailed results exceed the IPC display limit and remain on disk'}
        emit('result', result=result, message='Completed', progress=100)
    except BaseException as exc:
        # Do not echo exception text: providers/files may include credentials.
        # Fixed presentation metadata only; never expose exception prose.
        from quantlab.desktop_errors import exception_code

        categories = {
            'ValidationError': '輸入驗證失敗，請檢查資料、設定與紙上帳戶對帳',
            'FileNotFoundError': '找不到所需檔案，請重新選取資料',
            'PermissionError': '檔案存取遭拒，請檢查路徑及檔案是否被占用',
            'RuntimeSafetyError': '安全檢查未通過，請檢查備份版本或作業狀態',
        }
        emit(
            'error',
            message=categories.get(type(exc).__name__, '作業失敗；既有資料已保留，請檢查輸入後重試'),
            error_type=type(exc).__name__,
            error_code=exception_code(exc),
            stage=stage_from_traceback(exc.__traceback__, failure_stage),
        )
    finally:
        sender.close()

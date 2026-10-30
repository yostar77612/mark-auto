"""Native shell composition and stable, Qt-free spawned-worker registrar."""

from quantlab.desktop_runtime import (
    _is_worker_registrar_import,
    register_operation_executor,
    register_operation_executor_factory,
)
from desktop_app.bootstrap import create_operation_ports, create_ui_services
from quantlab.research_core.application.ui_operations.registry import UI_OPERATIONS, _UI_OPERATION_HANDLERS, prepare_operation

_worker_import = _is_worker_registrar_import()


def execute_ui_operation(operation, payload, paths, *, emit=None, descendants_stopped=False):
    ports = create_operation_ports()
    payload, root = prepare_operation(ports, operation, payload, paths)
    return _UI_OPERATION_HANDLERS[operation](ports, payload, paths, root, emit=emit, descendants_stopped=descendants_stopped)


OPERATION_REGISTRAR = 'desktop_app.shell.main_window:execute_ui_operation'
register_operation_executor(execute_ui_operation)
register_operation_executor_factory(OPERATION_REGISTRAR)

if not _worker_import:
    from PySide6.QtWidgets import QMainWindow
    from desktop_app.shell.window import MainWindow


def create_window(paths, jobs, settings=None, backups=None, guard=None):
    if _worker_import:
        raise RuntimeError('GUI construction is unavailable in an operation worker')
    services = create_ui_services(create_operation_ports())
    return MainWindow(paths, jobs, settings, backups, guard, services=services)

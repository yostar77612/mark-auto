"""Connection worker wiring at the desktop process composition boundary."""

from quantlab.assistant.adapters.chatgpt import connection_worker
from quantlab.assistant.ports.connection import configure_connection_worker


def configure():
    configure_connection_worker(lambda request, **kwargs: connection_worker.run_connection_request(request, **kwargs))


def execute_ui_operation(*args, **kwargs):
    from quantlab.research_core.adapters.job_worker import _worker_operation_executor

    execute = _worker_operation_executor('desktop_app.shell.main_window:execute_ui_operation')

    configure()
    return execute(*args, **kwargs)

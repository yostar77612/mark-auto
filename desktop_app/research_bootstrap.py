"""Qt-free composition of default research runtime adapters."""


def create_event_log(path):
    from quantlab.desktop_errors import ERROR_TABLE
    from quantlab.research_core.adapters.event_log import RedactedEventLog

    return RedactedEventLog(path, error_codes=ERROR_TABLE)


def create_job_manager(paths, *, process_port=None, storage_port=None):
    from quantlab.research_core.adapters.job_process import DesktopJobProcess
    from quantlab.research_core.adapters.workspace_backup import WorkspaceJobStorage
    from quantlab.research_core.application.job_manager import JobManager

    return JobManager(
        paths,
        process_port=process_port or DesktopJobProcess(),
        storage_port=storage_port or WorkspaceJobStorage(),
        event_log=create_event_log(paths.logs / 'desktop-events.jsonl'),
    )

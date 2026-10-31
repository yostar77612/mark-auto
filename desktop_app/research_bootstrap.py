"""Qt-free composition of default research runtime adapters."""

from quantlab.research_core.ports.market_data import MarketDataProvider


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


def create_history_storage():
    from types import SimpleNamespace
    from quantlab.research_core.adapters import history_decoder as decoder, market_history as cache
    from quantlab.research_core.domain.market_sessions import _fail
    from quantlab.windows_paths import canonical_path

    return SimpleNamespace(
        check=decoder._check,
        safe=cache._safe,
        decode=decoder._decode,
        result=decoder._result,
        bar_dict=decoder._bar_dict,
        fail=_fail,
        canonical_path=canonical_path,
        publish=cache.publish,
        version=decoder.VERSION,
        max_cache_bytes=cache.MAX_CACHE_BYTES,
    )


def create_history_service():
    from functools import partial
    from types import SimpleNamespace
    from quantlab.research_core.application.history_import import import_history
    from quantlab.research_core.adapters.market_history import list_history
    from quantlab.research_core.domain.market_sessions import session_from_dict

    return SimpleNamespace(
        import_history=partial(import_history, storage=create_history_storage()), session_from_dict=session_from_dict, list_history=list_history
    )


def create_market_provider(config=None) -> MarketDataProvider:
    from quantlab import market_providers

    # Both official sources already share the parser/transport service contract.
    providers = {'official_daily': market_providers}
    return providers[(config or {}).get('provider', 'official_daily')]

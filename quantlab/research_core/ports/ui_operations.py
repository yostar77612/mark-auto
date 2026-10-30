"""Only the capabilities exercised by existing desktop worker use cases."""

from typing import Any, Callable, Protocol


class AuthPort(Protocol):
    OAuthCredentialReference: Any


class BackupsPort(Protocol):
    BackupManager: Any


class CapitalPort(Protocol):
    execute: Any


class ConnectionPort(Protocol):
    ConnectionEvent: Any
    ConnectionRequest: Any
    ReconciliationEvent: Any
    SubscriptionOptions: Any
    TestConnectionEvent: Any
    run_connection_request: Any


class DataImportPort(Protocol):
    SessionCalendar: Any
    import_taifex: Any
    validate_dataset: Any


class DownloadPort(Protocol):
    refresh: Any


class ErrorsPort(Protocol):
    exception_code: Any


class FilesPort(Protocol):
    TemporaryDirectory: Any
    _promote_report: Any
    _root: Any
    exists: Any
    is_dir: Any
    is_symlink: Any
    mkdir: Any
    official_source: Any
    unlink: Any


class HistoryPort(Protocol):
    import_history: Any
    session_from_dict: Any


class InputsPort(Protocol):
    _dataset: Any
    candidate_state: Any
    implementation_sources: Any
    research_controls: Any


class ManualPort(Protocol):
    export_request: Any
    export_request_file: Any
    import_response: Any
    import_response_file: Any


class MarketPort(Protocol):
    MAX_BYTES: Any
    import_daily: Any
    refresh_daily: Any


class RecoveryPort(Protocol):
    RecoveryError: Any
    admission: Any
    inspect_recovery: Any
    recover_control_journal: Any
    supports_durable_recovery: Any
    validate_stop_receipt: Any


class RepositoryPort(Protocol):
    comparison_rows: Any
    demo_config: Any
    export_report: Any
    load_dataset: Any
    load_result: Any
    load_selection: Any
    read_json: Any
    save_dataset: Any
    save_selection: Any
    synthetic_dataset: Any
    write_json: Any


class SubscriptionPort(Protocol):
    ChatGPTPlanProvider: Any
    PlanHTTPTransport: Any
    _persist_account_pause: Any
    analysis_provider: Any
    implementation_provenance: Any
    read_account_status: Any


class WalkForwardPort(Protocol):
    execute_walk_forward: Any


class UiOperationPorts(Protocol):
    text: Callable[[str], str]
    idea_stream: Callable[..., Any]
    auth: AuthPort
    backups: BackupsPort
    capital: CapitalPort
    connection: ConnectionPort
    data_import: DataImportPort
    download: DownloadPort
    errors: ErrorsPort
    files: FilesPort
    history: HistoryPort
    inputs: InputsPort
    manual: ManualPort
    market: MarketPort
    recovery: RecoveryPort
    repository: RepositoryPort
    subscription: SubscriptionPort
    walk_forward: WalkForwardPort

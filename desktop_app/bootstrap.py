"""Concrete bindings and dispatcher selection for desktop worker operations."""

from pathlib import Path
from desktop_app.strings.catalog import ui_text
from quantlab.research_core.adapters.ui_repository import WorkerRepository
from quantlab.research_core.adapters import ui_files
from quantlab.research_core.adapters.ui_idea_stream import _idea_event_caller


class DesktopOperationPorts:
    def __init__(self, text, source_root):
        self.text = text
        self.inputs = WorkerRepository(text, source_root)
        self.files = ui_files
        self.idea_stream = _idea_event_caller

    @property
    def auth(self):
        import quantlab.assistant.adapters.chatgpt.auth as implementation

        return implementation

    @property
    def backups(self):
        import quantlab.research_core.adapters.workspace_backup as implementation

        return implementation

    @property
    def capital(self):
        import desktop_app.features.capital_scenario.worker as implementation

        return implementation

    @property
    def connection(self):
        from types import SimpleNamespace
        from quantlab.assistant.application import connection_contracts
        from quantlab.assistant.adapters.chatgpt.connection_worker import run_connection_request

        return SimpleNamespace(
            ConnectionEvent=connection_contracts.ConnectionEvent,
            ConnectionRequest=connection_contracts.ConnectionRequest,
            ReconciliationEvent=connection_contracts.ReconciliationEvent,
            SubscriptionOptions=connection_contracts.SubscriptionOptions,
            TestConnectionEvent=connection_contracts.TestConnectionEvent,
            run_connection_request=run_connection_request,
        )

    @property
    def data_import(self):
        import quantlab.data as implementation

        return implementation

    @property
    def download(self):
        import quantlab.downloads as implementation

        return implementation

    @property
    def errors(self):
        import quantlab.desktop_errors as implementation

        return implementation

    @property
    def history(self):
        import quantlab.market_history as implementation

        return implementation

    @property
    def manual(self):
        import quantlab.manual_exchange as implementation

        return implementation

    @property
    def market(self):
        import quantlab.market_providers as implementation

        return implementation

    @property
    def recovery(self):
        import quantlab.analysis_recovery as implementation

        return implementation

    @property
    def repository(self):
        import quantlab.reporting as implementation

        return implementation

    @property
    def subscription(self):
        import quantlab.assistant.adapters.chatgpt.provider as implementation

        return implementation

    @property
    def walk_forward(self):
        import desktop_app.features.walk_forward.presenter as implementation

        return implementation


def create_operation_ports():
    return DesktopOperationPorts(ui_text, Path(__file__).resolve().parents[1])


def create_idea_records(root):
    from quantlab.idea_research import IdeaStore

    return IdeaStore(root)


def create_ui_services(ports):
    import desktop_app.components.formatting as formatting
    from desktop_app.shell.services import UiServices
    from quantlab.research_core.application.ui_operations.registry import UI_OPERATIONS
    from quantlab.research_core.application import paper_operations as paper
    from quantlab.research_core.application.ui_operations import assistant, data, market, lifecycle

    return UiServices(
        idea_records=create_idea_records,
        state_root=ports.files._root,
        operations=UI_OPERATIONS,
        paper_risk_limits=lambda *args, **kwargs: paper.paper_risk_limits(*args, **kwargs),
        paper=lambda *args, **kwargs: paper._paper(ports, *args, **kwargs),
        dataset=lambda *args, **kwargs: ports.inputs._dataset(*args, **kwargs),
        candidate_record=lambda *args, **kwargs: data.candidate_record(ports, *args, **kwargs),
        plan_provider=lambda *args, **kwargs: assistant.plan_provider(ports, *args, **kwargs),
        connection_event_from_payload=lambda *args, **kwargs: assistant.connection_event_from_payload(ports, *args, **kwargs),
        dataset_market_series=lambda *args, **kwargs: market.dataset_market_series(ports, *args, **kwargs),
        latest_market_observations=lambda *args, **kwargs: market.latest_market_observations(*args, **kwargs),
        saved_analysis_entries=lambda *args, **kwargs: ports.repository.saved_analysis_entries(*args, **kwargs),
        load_result=lambda *args, **kwargs: ports.repository.load_result(*args, **kwargs),
        result_name=lambda *args, **kwargs: formatting.result_name(*args, **kwargs),
        write_json=lambda *args, **kwargs: ports.repository.write_json(*args, **kwargs),
        read_json=lambda *args, **kwargs: ports.repository.read_json(*args, **kwargs),
        load_dataset=lambda *args, **kwargs: ports.repository.load_dataset(*args, **kwargs),
        require_operation=lambda *args, **kwargs: ports.recovery.require_operation(*args, **kwargs),
        recover_state=lambda *args, **kwargs: lifecycle.recover_state(ports, *args, **kwargs),
    )

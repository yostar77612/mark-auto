"""Late-call services supplied by composition to desktop presentation."""

from dataclasses import dataclass
from typing import Any, Callable
from quantlab.research_core.ports.market_data import MarketDataProvider
from quantlab.research_core.ports.ui_operations import HistoryPort


@dataclass(frozen=True)
class UiServices:
    history: HistoryPort
    market_data: MarketDataProvider
    candidate_record: Callable[..., Any]
    connection_event_from_payload: Callable[..., Any]
    dataset: Callable[..., Any]
    dataset_market_series: Callable[..., Any]
    idea_records: Callable[..., Any]
    latest_market_observations: Callable[..., Any]
    load_dataset: Callable[..., Any]
    load_result: Callable[..., Any]
    operations: frozenset[str]
    paper: Callable[..., Any]
    paper_risk_limits: Callable[..., Any]
    plan_provider: Callable[..., Any]
    read_json: Callable[..., Any]
    recover_state: Callable[..., Any]
    require_operation: Callable[..., Any]
    result_name: Callable[..., Any]
    saved_analysis_entries: Callable[..., Any]
    state_root: Callable[..., Any]
    write_json: Callable[..., Any]

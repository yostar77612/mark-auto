"""Late-call services supplied by composition to desktop presentation."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class UiServices:
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
    sample_market_series: Callable[..., Any]
    saved_analysis_entries: Callable[..., Any]
    state_root: Callable[..., Any]
    write_json: Callable[..., Any]

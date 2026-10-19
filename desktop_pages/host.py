"""Explicit shell services and shared cross-page state for desktop pages."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable


class PageState(SimpleNamespace):
    """Shared UI state; contains data and widget references, never a shell reference."""


@dataclass
class PageHost:
    callbacks: dict
    find_child: Callable
    window_screen: Callable
    resize_window: Callable
    move_window: Callable
    question: Callable
    open_file: Callable
    save_file: Callable
    market_history_dialog: Callable
    state: PageState
    mount_market: Callable
    mount_page: Callable
    advanced: Callable
    bind_result_layers: Callable
    browse: Callable
    button: Callable
    candidate_record: Callable
    dataset: Callable
    dataset_market_series: Callable
    form_feedback: Callable
    inspect_plan_usage: Callable
    latest_market_observations: Callable
    payload: Callable
    plan_provider: Callable
    record_event: Callable
    remember: Callable
    result_snapshot_lines: Callable
    safe: Callable
    save_sections: Callable
    show_account: Callable
    show_sign_in: Callable
    start_job: Callable
    text: Callable
    window_geometry: Callable
    # QWidget x()/y() are frame coordinates; geometry().x()/y() are client coordinates.
    window_position: Callable
    window_minimum_size: Callable

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
    window_position: Callable
    window_minimum_size: Callable
    sample_market_series: Callable
    idea_records: Callable


@dataclass(frozen=True)
class PageServices:
    """Stage-1 service contract, deliberately not injected into existing pages.

    Callable[..., object] preserves the existing arbitrary forwarding signatures.
    ui_operations is the existing registry object, not a callable or a copy.
    """

    _advanced: Callable[..., object]
    _analysis_event: Callable[..., object]
    _analysis_request: Callable[..., object]
    _analysis_saved_changed: Callable[..., object]
    _analysis_section: Callable[..., object]
    _browse: Callable[..., object]
    _busy: Callable[..., object]
    _button: Callable[..., object]
    _chatgpt_cancel: Callable[..., object]
    _chatgpt_dispatch: Callable[..., object]
    _chatgpt_event: Callable[..., object]
    _chatgpt_open_browser: Callable[..., object]
    _chatgpt_quiesce: Callable[..., object]
    _compare_page: Callable[..., object]
    _confirm_button: Callable[..., object]
    _current_plan_binding: Callable[..., object]
    _invalidate_analysis_preview: Callable[..., object]
    _mount_market: Callable[..., object]
    _mount_page: Callable[..., object]
    _navigate_selected_page: Callable[..., object]
    _notification_link: Callable[..., object]
    _page: Callable[..., object]
    _paper_page: Callable[..., object]
    _payload: Callable[..., object]
    _plan_usage_request: Callable[..., object]
    _quiesce_and_recover: Callable[..., object]
    _record_connection_error: Callable[..., object]
    _recovery_display_fingerprint: Callable[..., object]
    _refresh_analysis_saved: Callable[..., object]
    _refresh_recovery_controls: Callable[..., object]
    _remember: Callable[..., object]
    _remember_stop: Callable[..., object]
    _safe: Callable[..., object]
    _save_section_preferences: Callable[..., object]
    _selected_recovery_launch: Callable[..., object]
    _settings_page: Callable[..., object]
    _show_account: Callable[..., object]
    _text: Callable[..., object]
    auto_restore_chatgpt: Callable[..., object]
    backup: Callable[..., object]
    cancel_job: Callable[..., object]
    closeEvent: Callable[..., object]
    configure_workspace: Callable[..., object]
    demo_paper_policy: Callable[..., object]
    form_feedback: Callable[..., object]
    freeze_paper: Callable[..., object]
    inspect_plan_usage: Callable[..., object]
    kill_paper: Callable[..., object]
    load_form_file: Callable[..., object]
    load_settings: Callable[..., object]
    notify_local: Callable[..., object]
    open_releases: Callable[..., object]
    paper_job: Callable[..., object]
    pick_analysis_original: Callable[..., object]
    poll_jobs: Callable[..., object]
    preview_analysis: Callable[..., object]
    read_analysis: Callable[..., object]
    read_logs: Callable[..., object]
    reconcile_saved_analysis: Callable[..., object]
    record_event: Callable[..., object]
    refresh_views: Callable[..., object]
    run_analysis: Callable[..., object]
    save_settings: Callable[..., object]
    select_strategy: Callable[..., object]
    show_chatgpt_sign_in: Callable[..., object]
    start_job: Callable[..., object]
    ui_operations: frozenset[str]
    paper_risk_limits: Callable[..., object]
    _paper: Callable[..., object]
    _dataset: Callable[..., object]
    plan_provider: Callable[..., object]
    connection_event_from_payload: Callable[..., object]
    analysis_preview_text: Callable[..., object]
    analysis_record_text: Callable[..., object]
    saved_analysis_entries: Callable[..., object]
    load_result: Callable[..., object]
    result_name: Callable[..., object]
    write_json: Callable[..., object]
    read_json: Callable[..., object]
    load_dataset: Callable[..., object]


def _page_services(shell: object) -> PageServices:
    """Build the opt-in typed view without changing PageHost or page wiring.

    Shell operations resolve attributes at call time. Module-level operations
    reuse page_services' late module lookup, keeping desktop_app.shell.main_window out of imports.
    """
    return PageServices(
        _advanced=lambda *a, **kw: getattr(shell, '_advanced')(*a, **kw),
        _analysis_event=lambda *a, **kw: getattr(shell, '_analysis_event')(*a, **kw),
        _analysis_request=lambda *a, **kw: getattr(shell, '_analysis_request')(*a, **kw),
        _analysis_saved_changed=lambda *a, **kw: getattr(shell, '_analysis_saved_changed')(*a, **kw),
        _analysis_section=lambda *a, **kw: getattr(shell, '_analysis_section')(*a, **kw),
        _browse=lambda *a, **kw: getattr(shell, '_browse')(*a, **kw),
        _busy=lambda *a, **kw: getattr(shell, '_busy')(*a, **kw),
        _button=lambda *a, **kw: getattr(shell, '_button')(*a, **kw),
        _chatgpt_cancel=lambda *a, **kw: getattr(shell, '_chatgpt_cancel')(*a, **kw),
        _chatgpt_dispatch=lambda *a, **kw: getattr(shell, '_chatgpt_dispatch')(*a, **kw),
        _chatgpt_event=lambda *a, **kw: getattr(shell, '_chatgpt_event')(*a, **kw),
        _chatgpt_open_browser=lambda *a, **kw: getattr(shell, '_chatgpt_open_browser')(*a, **kw),
        _chatgpt_quiesce=lambda *a, **kw: getattr(shell, '_chatgpt_quiesce')(*a, **kw),
        _compare_page=lambda *a, **kw: getattr(shell, '_compare_page')(*a, **kw),
        _confirm_button=lambda *a, **kw: getattr(shell, '_confirm_button')(*a, **kw),
        _current_plan_binding=lambda *a, **kw: getattr(shell, '_current_plan_binding')(*a, **kw),
        _invalidate_analysis_preview=lambda *a, **kw: getattr(shell, '_invalidate_analysis_preview')(*a, **kw),
        _mount_market=lambda *a, **kw: getattr(shell, '_mount_market')(*a, **kw),
        _mount_page=lambda *a, **kw: getattr(shell, '_mount_page')(*a, **kw),
        _navigate_selected_page=lambda *a, **kw: getattr(shell, '_navigate_selected_page')(*a, **kw),
        _notification_link=lambda *a, **kw: getattr(shell, '_notification_link')(*a, **kw),
        _page=lambda *a, **kw: getattr(shell, '_page')(*a, **kw),
        _paper_page=lambda *a, **kw: getattr(shell, '_paper_page')(*a, **kw),
        _payload=lambda *a, **kw: getattr(shell, '_payload')(*a, **kw),
        _plan_usage_request=lambda *a, **kw: getattr(shell, '_plan_usage_request')(*a, **kw),
        _quiesce_and_recover=lambda *a, **kw: getattr(shell, '_quiesce_and_recover')(*a, **kw),
        _record_connection_error=lambda *a, **kw: getattr(shell, '_record_connection_error')(*a, **kw),
        _recovery_display_fingerprint=lambda *a, **kw: getattr(shell, '_recovery_display_fingerprint')(*a, **kw),
        _refresh_analysis_saved=lambda *a, **kw: getattr(shell, '_refresh_analysis_saved')(*a, **kw),
        _refresh_recovery_controls=lambda *a, **kw: getattr(shell, '_refresh_recovery_controls')(*a, **kw),
        _remember=lambda *a, **kw: getattr(shell, '_remember')(*a, **kw),
        _remember_stop=lambda *a, **kw: getattr(shell, '_remember_stop')(*a, **kw),
        _safe=lambda *a, **kw: getattr(shell, '_safe')(*a, **kw),
        _save_section_preferences=lambda *a, **kw: getattr(shell, '_save_section_preferences')(*a, **kw),
        _selected_recovery_launch=lambda *a, **kw: getattr(shell, '_selected_recovery_launch')(*a, **kw),
        _settings_page=lambda *a, **kw: getattr(shell, '_settings_page')(*a, **kw),
        _show_account=lambda *a, **kw: getattr(shell, '_show_account')(*a, **kw),
        _text=lambda *a, **kw: getattr(shell, '_text')(*a, **kw),
        auto_restore_chatgpt=lambda *a, **kw: getattr(shell, 'auto_restore_chatgpt')(*a, **kw),
        backup=lambda *a, **kw: getattr(shell, 'backup')(*a, **kw),
        cancel_job=lambda *a, **kw: getattr(shell, 'cancel_job')(*a, **kw),
        closeEvent=lambda *a, **kw: getattr(shell, 'closeEvent')(*a, **kw),
        configure_workspace=lambda *a, **kw: getattr(shell, 'configure_workspace')(*a, **kw),
        demo_paper_policy=lambda *a, **kw: getattr(shell, 'demo_paper_policy')(*a, **kw),
        form_feedback=lambda *a, **kw: getattr(shell, 'form_feedback')(*a, **kw),
        freeze_paper=lambda *a, **kw: getattr(shell, 'freeze_paper')(*a, **kw),
        inspect_plan_usage=lambda *a, **kw: getattr(shell, 'inspect_plan_usage')(*a, **kw),
        kill_paper=lambda *a, **kw: getattr(shell, 'kill_paper')(*a, **kw),
        load_form_file=lambda *a, **kw: getattr(shell, 'load_form_file')(*a, **kw),
        load_settings=lambda *a, **kw: getattr(shell, 'load_settings')(*a, **kw),
        notify_local=lambda *a, **kw: getattr(shell, 'notify_local')(*a, **kw),
        open_releases=lambda *a, **kw: getattr(shell, 'open_releases')(*a, **kw),
        paper_job=lambda *a, **kw: getattr(shell, 'paper_job')(*a, **kw),
        pick_analysis_original=lambda *a, **kw: getattr(shell, 'pick_analysis_original')(*a, **kw),
        poll_jobs=lambda *a, **kw: getattr(shell, 'poll_jobs')(*a, **kw),
        preview_analysis=lambda *a, **kw: getattr(shell, 'preview_analysis')(*a, **kw),
        read_analysis=lambda *a, **kw: getattr(shell, 'read_analysis')(*a, **kw),
        read_logs=lambda *a, **kw: getattr(shell, 'read_logs')(*a, **kw),
        reconcile_saved_analysis=lambda *a, **kw: getattr(shell, 'reconcile_saved_analysis')(*a, **kw),
        record_event=lambda *a, **kw: getattr(shell, 'record_event')(*a, **kw),
        refresh_views=lambda *a, **kw: getattr(shell, 'refresh_views')(*a, **kw),
        run_analysis=lambda *a, **kw: getattr(shell, 'run_analysis')(*a, **kw),
        save_settings=lambda *a, **kw: getattr(shell, 'save_settings')(*a, **kw),
        select_strategy=lambda *a, **kw: getattr(shell, 'select_strategy')(*a, **kw),
        show_chatgpt_sign_in=lambda *a, **kw: getattr(shell, 'show_chatgpt_sign_in')(*a, **kw),
        start_job=lambda *a, **kw: getattr(shell, 'start_job')(*a, **kw),
        ui_operations=getattr(shell, 'page_services')()['ui_operations'],
        paper_risk_limits=lambda *a, **kw: getattr(shell, 'page_services')()['paper_risk_limits'](*a, **kw),
        _paper=lambda *a, **kw: getattr(shell, 'page_services')()['_paper'](*a, **kw),
        _dataset=lambda *a, **kw: getattr(shell, 'page_services')()['_dataset'](*a, **kw),
        plan_provider=lambda *a, **kw: getattr(shell, 'page_services')()['plan_provider'](*a, **kw),
        connection_event_from_payload=lambda *a, **kw: getattr(shell, 'page_services')()['connection_event_from_payload'](*a, **kw),
        analysis_preview_text=lambda *a, **kw: getattr(shell, 'page_services')()['analysis_preview_text'](*a, **kw),
        analysis_record_text=lambda *a, **kw: getattr(shell, 'page_services')()['analysis_record_text'](*a, **kw),
        saved_analysis_entries=lambda *a, **kw: getattr(shell, 'page_services')()['saved_analysis_entries'](*a, **kw),
        load_result=lambda *a, **kw: getattr(shell, 'page_services')()['load_result'](*a, **kw),
        result_name=lambda *a, **kw: getattr(shell, 'page_services')()['result_name'](*a, **kw),
        write_json=lambda *a, **kw: getattr(shell, 'page_services')()['write_json'](*a, **kw),
        read_json=lambda *a, **kw: getattr(shell, 'page_services')()['read_json'](*a, **kw),
        load_dataset=lambda *a, **kw: getattr(shell, 'page_services')()['load_dataset'](*a, **kw),
    )

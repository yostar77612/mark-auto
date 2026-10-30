"""Historical single-hop alias literals; ordered records preserve the original catalog."""

ENTRIES = (
    (3, 'ui.connection_event_from_payload.text_1', 'ui.connection_event_from_payload.invalid_event_format'),
    (4, 'ui.plan_provider.text_1', 'ui.plan_provider.unsupported_settings'),
    (5, 'ui.plan_provider.text_2', 'ui.plan_provider.reconciliation_not_authorization'),
    (6, 'ui.plan_provider.text_3', 'ui.plan_provider.request_binding_changed'),
    (320, 'ui.show_chatgpt_sign_in.text_1', 'ui.show_chatgpt_sign_in.checking_connection'),
    (321, 'ui.show_chatgpt_sign_in.text_2', 'ui.show_chatgpt_sign_in.connection_panel_missing'),
    (322, 'ui._chatgpt_quiesce.text_1', 'ui.chatgpt_quiesce.stop_record_checking'),
    (323, 'ui._chatgpt_dispatch.text_1', 'ui.chatgpt_dispatch.stop_record_checking'),
    (324, 'ui._chatgpt_dispatch.text_2', 'ui.chatgpt_dispatch.connection_start_failed'),
    (325, 'ui._chatgpt_open_browser.text_1', 'ui.chatgpt_open_browser.authorization_page_failed'),
    (326, 'ui._plan_usage_request.text_1', 'ui.plan_usage_request.connection_models_required'),
    (327, 'ui.inspect_plan_usage.text_1', 'ui.inspect_plan_usage.connection_job_busy'),
    (328, 'ui._chatgpt_event.text_1', 'ui.chatgpt_event.recovery_checked'),
    (329, 'ui._chatgpt_event.text_2', 'ui.chatgpt_event.recovery_failed'),
    (330, 'ui._chatgpt_event.text_3', 'ui.chatgpt_event.settings_changed'),
    (331, 'ui._chatgpt_event.text_4', 'ui.chatgpt_event.request_record_checked'),
    (332, 'ui._chatgpt_event.text_5', 'ui.chatgpt_event.request_record_unknown'),
)

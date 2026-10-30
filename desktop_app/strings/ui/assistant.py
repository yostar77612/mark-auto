"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (0, 104, 'ui.connection_event_from_payload.invalid_event_format', '連線事件格式不符'),
    (0, 105, 'ui.plan_provider.unsupported_settings', '不支援的訂閱設定欄位'),
    (0, 106, 'ui.plan_provider.reconciliation_not_authorization', '紀錄核對不可授權網路或推論'),
    (0, 107, 'ui.plan_provider.request_binding_changed', '研究／模型／預算／來源已變更，請重新核對持久請求紀錄並明確同意'),
    (0, 420, 'ui.show_chatgpt_sign_in.checking_connection', '正在核對本機 ChatGPT 連線；官方登入會在系統瀏覽器開啟，授權由您決定。'),
    (0, 421, 'ui.show_chatgpt_sign_in.connection_panel_missing', '找不到官方 ChatGPT 連線區'),
    (0, 422, 'ui.chatgpt_quiesce.stop_record_checking', '分析停止紀錄正在本機核對；本次連線動作未執行，完成後請重新操作。'),
    (0, 423, 'ui.chatgpt_dispatch.stop_record_checking', '分析停止紀錄正在本機核對；本次登入未執行，完成後請重新按登入。'),
    (0, 424, 'ui.chatgpt_dispatch.connection_start_failed', '連線背景作業無法啟動；請核對本機狀態。'),
    (0, 425, 'ui.chatgpt_open_browser.authorization_page_failed', '無法開啟官方授權頁面；請取消後再核對環境。'),
    (0, 426, 'ui.plan_usage_request.connection_models_required', '請先明確核對連線與官方模型清單'),
    (0, 427, 'ui.inspect_plan_usage.connection_job_busy', '請先等待連線背景作業結束'),
    (0, 428, 'ui.chatgpt_event.recovery_checked', '中斷研究紀錄已核對；仍需明確檢查狀態。'),
    (0, 429, 'ui.chatgpt_event.recovery_failed', '中斷研究核對失敗；維持未知封鎖，請勿重送。'),
    (0, 430, 'ui.chatgpt_event.settings_changed', '研究設定已變更，請重新核對請求紀錄。'),
    (0, 431, 'ui.chatgpt_event.request_record_checked', '本次研究持久請求紀錄已核對；執行前仍需本次明確同意。'),
    (0, 432, 'ui.chatgpt_event.request_record_unknown', '請求紀錄核對未完成；狀態未知，禁止自動重送。'),
)

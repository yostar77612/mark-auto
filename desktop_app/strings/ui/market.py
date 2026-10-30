"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (0, 214, 'ui.dataset_market_series.minute_history_required', '只接受明確的一分鐘官方歷史；不把合成或日資料轉成分鐘'),
    (0, 215, 'ui.dataset_market_series.calendar_hash_mismatch', '交易日曆與研究資料雜湊不符'),
    (0, 216, 'ui.dataset_market_series.taifex_source_hash', 'TAIFEX 官方歷史；原始研究資料雜湊 {0}'),
    (0, 230, 'ui.refresh_market.job_busy', '已有背景作業，請等待或取消'),
    (0, 231, 'ui.refresh_market.confirmation_title', '更新官方唯讀資料'),
    (0, 232, 'ui.refresh_market.network_consent', '本次連線 TWSE 與 TAIFEX 免費公開端點，下載歷史／盤後資料？不含即時行情、不使用交易帳密。'),
    (0, 233, 'ui.import_market_file.file_dialog_title', '選擇官方格式原始資料（本機檔案來源仍需自行核對）'),
    (0, 234, 'ui.import_market_history.job_busy', '已有背景作業，請等待或取消'),
    (0, 235, 'ui.import_market_history.closing_blocked', '視窗正在關閉，不能啟動新匯入'),
    (0, 444, 'ui.load_market_cache.update_failed_cache_retained', '{0}：更新失敗，保留最後有效快取'),
    (0, 445, 'ui.load_market_cache.invalid_cache', '{0}：快取驗證失敗，未採用該資料'),
    (0, 446, 'ui.load_market_cache.update_failed_no_cache', '{0}：更新失敗，尚無有效快取'),
    (0, 447, 'ui.load_market_cache.warning_separator', '；'),
    (0, 448, 'ui.load_market_cache.inactive', '未啟用'),
    (0, 449, 'ui.load_market_cache.active_version', '已啟用研究／紙上版本 {0}'),
    (0, 450, 'ui.load_market_cache.invalid_version', '版本驗證失敗，不可使用'),
    (0, 451, 'ui.load_market_cache.account_read_failed', '帳戶讀取失敗，狀態未知'),
    (0, 452, 'ui.load_market_cache.stop_check_records', '請停止並核對紀錄'),
)

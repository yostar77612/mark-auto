"""M2-9 maintenance controls; append-only catalogue registration; orders follow U1 (2962-2976)."""

ENTRIES = (
    (65, 2962, 'm2.maintenance.expiry', 'API 金鑰到期日'),
    (65, 2963, 'm2.maintenance.expiry_hint', 'YYYY-MM-DD；留空表示未知'),
    (65, 2964, 'm2.maintenance.expiry_unknown', 'API 金鑰到期日：未知'),
    (65, 2965, 'm2.maintenance.expired', 'API 金鑰已到期，請更新金鑰與到期日後重新連線。'),
    (65, 2966, 'm2.maintenance.expiry_due', 'API 金鑰剩餘 {} 天，請提前更新。'),
    (65, 2967, 'm2.maintenance.expiry_days', 'API 金鑰剩餘 {} 天。'),
    (65, 2968, 'm2.maintenance.minimum_fee', '每筆最低手續費（元）'),
    (65, 2969, 'm2.maintenance.tmf_fee', '微台每口手續費（元）'),
    (65, 2970, 'm2.maintenance.checklist', '開盤前檢查清單'),
    (65, 2971, 'm2.maintenance.calendar_days', '已確認未來 {} 個交易日；日曆版本：{}'),
    (65, 2972, 'm2.maintenance.calendar_missing', '交易日曆不足未來 30 個交易日，自動新倉停止。'),
    (65, 2973, 'm2.maintenance.expiries_missing', '期貨到期月份未完整覆蓋，自動新倉停止。'),
    (65, 2974, 'm2.maintenance.annual_reminder', '十二月起請核對並更新下一年度交易日曆與期貨到期資料。'),
    (65, 2975, 'm2.maintenance.unknown', '開盤前維護狀態：未知；請確認設定並重新取得資料。'),
    (65, 2976, 'm2.maintenance.ready', '維護資料已涵蓋檢查範圍；這不代表已取得下單權限。'),
)

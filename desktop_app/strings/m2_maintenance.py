"""M2-9 maintenance controls; append-only catalogue registration."""

ENTRIES = (
    (64, 2952, 'm2.maintenance.expiry', 'API 金鑰到期日'),
    (64, 2953, 'm2.maintenance.expiry_hint', 'YYYY-MM-DD；留空表示未知'),
    (64, 2954, 'm2.maintenance.expiry_unknown', 'API 金鑰到期日：未知'),
    (64, 2955, 'm2.maintenance.expired', 'API 金鑰已到期，請更新金鑰與到期日後重新連線。'),
    (64, 2956, 'm2.maintenance.expiry_due', 'API 金鑰剩餘 {} 天，請提前更新。'),
    (64, 2957, 'm2.maintenance.expiry_days', 'API 金鑰剩餘 {} 天。'),
    (64, 2958, 'm2.maintenance.minimum_fee', '每筆最低手續費（元）'),
    (64, 2959, 'm2.maintenance.tmf_fee', '微台每口手續費（元）'),
    (64, 2960, 'm2.maintenance.checklist', '開盤前檢查清單'),
    (64, 2961, 'm2.maintenance.calendar_days', '已確認未來 {} 個交易日；日曆版本：{}'),
    (64, 2962, 'm2.maintenance.calendar_missing', '交易日曆不足未來 30 個交易日，自動新倉停止。'),
    (64, 2963, 'm2.maintenance.expiries_missing', '期貨到期月份未完整覆蓋，自動新倉停止。'),
    (64, 2964, 'm2.maintenance.annual_reminder', '十二月起請核對並更新下一年度交易日曆與期貨到期資料。'),
    (64, 2965, 'm2.maintenance.unknown', '開盤前維護狀態：未知；請確認設定並重新取得資料。'),
    (64, 2966, 'm2.maintenance.ready', '維護資料已涵蓋檢查範圍；這不代表已取得下單權限。'),
)

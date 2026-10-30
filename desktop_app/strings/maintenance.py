"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (10, 1556, 'maintenance.options', '版本維護（檢查更新／舊程式版本）'),
    (10, 1557, 'maintenance.check_updates', '檢查更新'),
    (10, 1558, 'maintenance.check_payloads', '檢查舊程式版本'),
    (10, 1559, 'maintenance.checking', '正在檢查版本資訊，請稍候…'),
    (10, 1560, 'maintenance.available', '有新版本 {0}。請自行按「開啟專案 Releases 頁面」下載並核對安裝檔 SHA256；本工具不會下載或安裝。'),
    (10, 1561, 'maintenance.current', '依本次已核對 SHA256 的版本資訊，目前無較新版本（發布版本：{0}）。'),
    (10, 1562, 'maintenance.update_error', '無法核對更新資訊。請稍後重試，或自行查看專案發布頁；不會下載或安裝。'),
    (10, 1563, 'maintenance.not_installed', '此功能僅適用於預設位置的已安裝桌面版。'),
    (10, 1564, 'maintenance.refused', '無法安全規劃清理：版本目錄不明確、目前版本不存在、含連結或無法存取。未刪除任何目錄。'),
    (10, 1565, 'maintenance.nothing', '沒有可清理的舊版本；保留目前版本與最近一個較舊版本以供回退。'),
    (
        10,
        1566,
        'maintenance.confirm',
        '僅清理下列程式版本及其所有安裝嘗試；保留目前版本與最近一個較舊版本，不處理使用者工作區。\n位置：{0}\n將刪除：\n{1}\n確定刪除？',
    ),
    (10, 1567, 'maintenance.cancelled', '已取消清理，未刪除任何目錄。'),
    (10, 1568, 'maintenance.cleaned', '已清理 {0} 個程式版本目錄。'),
    (10, 1569, 'maintenance.cleanup_error', '清理已停止；已完整刪除 {0} 個版本目錄，失敗目錄可能僅部分刪除。請核對安裝目錄後再重試。'),
)

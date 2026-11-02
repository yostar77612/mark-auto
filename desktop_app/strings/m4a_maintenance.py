"""M4a explicitly confirmed updates and optional current-user startup."""

ENTRIES = (
    (68, 3032, 'update.installed', '目前版本：{0}'),
    (68, 3033, 'update.latest', '最新版本：{0}'),
    (68, 3034, 'update.published', '發布時間：{0}'),
    (68, 3035, 'update.unknown', '尚未檢查'),
    (68, 3036, 'update.install', '下載並安裝'),
    (68, 3037, 'update.confirm_title', '下載並安裝更新'),
    (
        68,
        3038,
        'update.confirm',
        '下載來源：{0}\n版本：{1}\n驗證碼（SHA256）前 12 碼：{2}\n\n安裝時會關閉本程式，自動交易會停止。重啟後維持停止新倉，需您手動恢復。\n安裝檔尚未簽章；僅核對下載來源與驗證碼。\n\n是否下載並安裝？',
    ),
    (68, 3039, 'update.cancel', '取消下載'),
    (68, 3040, 'update.downloading', '正在下載並驗證更新，完成後將關閉本程式並安裝。'),
    (68, 3041, 'update.cancelled', '已取消更新；既有程式、設定與工作區保持完整。'),
    (68, 3042, 'update.ready', '下載已驗證，正在等候程式乾淨關閉。'),
    (68, 3043, 'update.manual', '也可前往發布頁下載安裝；安裝前請先關閉本程式。'),
    (68, 3044, 'autostart.enable', '開機時自動啟動 MarkAuto'),
    (68, 3045, 'autostart.hint', '只開啟程式，重啟後仍停止新倉，需手動恢復自動交易。電腦睡眠或關機時不會自動交易。'),
    (68, 3046, 'autostart.unavailable', '安裝 Windows 版後可設定開機自動啟動。'),
    (68, 3047, 'autostart.enabled', '已啟用開機自動啟動。'),
    (68, 3048, 'autostart.disabled', '已關閉開機自動啟動。'),
    (68, 3049, 'update.available', '有新版本 {0}，可按「下載並安裝」更新。'),
)

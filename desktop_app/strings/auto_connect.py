"""Connect-on-startup switch on the broker connection panel, and the self-updating pre-open checklist preview."""

ENTRIES = (
    (78, 3362, 'autoconnect.label', '啟動時自動連線（永豐模擬環境）'),
    (78, 3363, 'autoconnect.hint', '勾選後，下次開啟程式會自動用上方已儲存的設定連線；只在目標為「券商模擬」時動作，連線失敗不會重試。'),
    (78, 3364, 'autoconnect.failed', '自動連線失敗：{0}'),
    (78, 3365, 'autoconnect.skipped_live', '自動連線已略過：儲存的目標不是券商模擬環境，請手動連線。'),
    (78, 3366, 'autoconnect.save_failed', '無法儲存自動連線設定，請稍後再試。'),
    (
        78,
        3367,
        'preflight.preview_note',
        '以上為即時預覽，尚未記錄。按「檢查目前帳戶」會正式記入今日開盤檢查：只要有一項未通過，今日自動新倉就會停止，之後重新檢查也無法解除，請等全部就緒再按。',
    ),
    (78, 3368, 'performance.empty', '尚無績效紀錄；策略成交並完成對帳後會顯示在這裡。'),
)

"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (
        50,
        2059,
        'chatgpt_reconciliation_k2.summary',
        '第 {0}／{1} 次請求已經結束，但沒有正常完成。App 無法判斷它是否已送達或已計入官方用量。（App 內部結果代碼：{2}，可提供給維護者；你不需要看懂它）',
    ),
    (50, 2060, 'chatgpt_reconciliation_k2.not_sent_notice', '即使這次可能沒有送達伺服器，也會記錄為已消耗。'),
    (50, 2061, 'chatgpt_reconciliation_k2.other_usage', '我了解官方用量頁也包含 App 以外工具（例如命令列程式）送出的請求，App 無法替我分辨'),
    (50, 2062, 'chatgpt_reconciliation_k2.too_recent', '這筆請求剛結束不久，請至少等待 5 分鐘，讓官方用量頁有時間更新後再核對。'),
    (
        50,
        2063,
        'chatgpt_reconciliation_k2.other_registration',
        '這筆請求是用另一個本機連線送出的。請在上方連線選單切換到那個連線後再核對；如果選單裡找不到它，目前版本無法人工核對。',
    ),
    (
        50,
        2064,
        'chatgpt_reconciliation_k2.unmappable',
        '這筆請求已經結束但結果未知，而且本機紀錄無法唯一對應到一個帳號，目前版本無法人工核對。請保留本機紀錄，不要手動修改，等待後續版本處理。',
    ),
)

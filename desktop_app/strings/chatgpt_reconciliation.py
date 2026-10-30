"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (49, 2039, 'chatgpt_reconciliation.inspect', '核對未知請求…'),
    (49, 2040, 'chatgpt_reconciliation.title', '核對未知的 ChatGPT 請求'),
    (49, 2041, 'chatgpt_reconciliation.summary', '第 {0}／{1} 次請求已送出，但 App 沒有收到完成結果。這一次可能已經計入官方用量。'),
    (
        49,
        2042,
        'chatgpt_reconciliation.explanation',
        '請自行用瀏覽器開啟 OpenAI 官方用量頁，確認這段時間的用量。App 不會開啟或讀取這個頁面，也無法驗證你看到的內容。無論官方頁面顯示什麼，這一次都會記錄為已消耗，不退還次數，而這次研究批次會永久停止。',
    ),
    (49, 2043, 'chatgpt_reconciliation.usage_checked', '我已經在官方用量頁核對過'),
    (49, 2044, 'chatgpt_reconciliation.no_refund', '我了解不會退還次數，這次研究批次會停止'),
    (49, 2045, 'chatgpt_reconciliation.no_other_tool', '目前沒有其他工具或命令列程式正在送出 ChatGPT 請求'),
    (49, 2046, 'chatgpt_reconciliation.confirm', '記錄為已消耗'),
    (49, 2047, 'chatgpt_reconciliation.cancel', '取消'),
    (49, 2048, 'chatgpt_reconciliation.other_registration', '未知請求屬於另一個已登入的帳號，請切換到該帳號再核對。'),
    (49, 2049, 'chatgpt_reconciliation.too_recent', '請求剛送出不久，請至少等待 5 分鐘，並確認沒有其他工具正在執行。'),
    (49, 2050, 'chatgpt_reconciliation.none', '目前沒有可以人工核對的未知請求。'),
    (
        49,
        2051,
        'chatgpt_reconciliation.resolved',
        '已記錄為使用者確認消耗。帳號目前處於已知暫停。請核對額度後，再到「進階連線管理」按「核對額度後申請解除已知暫停」。',
    ),
    (49, 2052, 'chatgpt_reconciliation.pending', '已記錄為使用者確認消耗，但仍有未知請求。請重新核對本機紀錄。'),
    (49, 2053, 'chatgpt_reconciliation.disabled', '請先選取目前登入帳號，並等待所有背景工作停止。'),
    (49, 2054, 'chatgpt_reconciliation.inspecting', '正在核對本機未知請求紀錄；不會連網。'),
    (49, 2055, 'chatgpt_reconciliation.resolving', '正在記錄使用者確認消耗；不會連網。'),
    (49, 2056, 'chatgpt_reconciliation.changed', '帳號或本機狀態已變更，請重新核對未知請求。'),
    (49, 2057, 'chatgpt_reconciliation.resolved_unverified', '已記錄為使用者確認消耗，但目前無法確認本機暫停狀態。請重新核對本機紀錄。'),
    (49, 2058, 'chatgpt_reconciliation.resolved_ready', '已記錄為使用者確認消耗。帳號目前沒有本機暫停，原本的研究批次仍會永久停止。'),
)

"""Assistant source that runs through the Claude Code installed on this computer."""

ENTRIES = (
    (75, 3211, 'assistant.claude_code', 'Claude Code（未驗證）'),
    (75, 3212, 'assistant.claude_model', 'Claude 模型（未驗證）'),
    (75, 3213, 'assistant.claude_haiku', 'Haiku（快、省額度）'),
    (75, 3214, 'assistant.claude_sonnet', 'Sonnet（平衡）'),
    (75, 3215, 'assistant.claude_opus', 'Opus（最強、較慢）'),
    (75, 3216, 'assistant.claude_consent_title', '同意本次 Claude Code 請求（未驗證）'),
    (
        75,
        3217,
        'assistant.claude_consent_body',
        '本次輸入文字會交給這台電腦上已登入的 Claude Code，並送到 Anthropic，使用你的 Claude 訂閱額度。'
        '不傳送歷史、資料集、金鑰或檔案，Claude Code 也不會被允許使用任何工具。'
        '請勿輸入憑證、樣本外或最終保留資料。是否同意本次網路請求？',
    ),
    (75, 3218, 'assistant.claude_unavailable', '找不到這台電腦上的 Claude Code；請先安裝並登入後再試。'),
    (75, 3219, 'assistant.claude_login_required', 'Claude Code 尚未登入；請先在終端機執行 claude 並完成登入。'),
)

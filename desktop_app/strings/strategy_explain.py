"""The question prefilled for the AI assistant when the user asks it to explain the selected strategy."""

ENTRIES = (
    (
        76,
        3220,
        'assistant.explain_intro',
        '請用繁體中文，以白話向投資新手解釋下面這個策略的設定與目前結果，指出看起來不合理或風險偏高的地方，並列出還需要確認的問題。只根據下列事實，不要編造數字，不要建議下單。',
    ),
    (76, 3221, 'assistant.explain_strategy', '策略：{0}（第 {1} 版）　商品：{2}　持有政策：{3}'),
    (76, 3222, 'assistant.explain_params', '資金配置 {0} 元　單筆風險 {1}%　停損 {2}%　進場金額 {3} 元'),
    (76, 3223, 'assistant.explain_state', '研究狀態：{0}　證據：{1}'),
    (76, 3224, 'assistant.explain_results', '今日損益 {0}　累計淨損益 {1}　成本 {2}　最大回落 {3}'),
    (76, 3225, 'assistant.explain_checks', '程式已檢查：'),
    (76, 3226, 'assistant.explain_check_none', '未發現明顯的設定問題。'),
    (76, 3227, 'assistant.explain_check_entry_over_allocation', '進場金額高於資金配置，實際只會用到配置金額以內。'),
    (76, 3228, 'assistant.explain_check_allocation_below_lot', '資金配置買不起一張，策略不會下單。'),
    (76, 3229, 'assistant.explain_check_risk_below_lot', '依單筆風險與停損，風險預算不足一張，策略不會下單。'),
    (76, 3230, 'assistant.explain_check_stop_tight', '停損小於 1%，容易被正常波動洗出場。'),
    (76, 3231, 'assistant.explain_check_stop_wide', '停損大於 10%，單筆虧損可能很大。'),
    (76, 3232, 'assistant.explain_check_costs', '成本占累計虧損一半以上，可能是交易太頻繁。'),
    (76, 3233, 'assistant.explain_check_unresearched', '尚未完成研究或研究已過期，結果不能當作依據。'),
)

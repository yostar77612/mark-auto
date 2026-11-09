"""Texts for the read-only minute research of a typed micro-TAIEX day-trade strategy."""

ENTRIES = (
    (
        78,
        3236,
        'research.minute.summary',
        '分鐘研究完成（{0}～{1}，{2} K 線）：{3} 筆交易，淨損益 {4}，成本 {5}，最大回落 {6}，共 {7} 根 K 線。\n僅供研究：這個結果不能啟用策略，也不含保護性停損。',
    ),
    (
        78,
        3237,
        'research.minute.need_connection',
        '分鐘研究要用微台 K 線，需要已連到「券商模擬」並選好帳戶的永豐連線；也可能是 K 線補抓暫停或失敗。請到「設定」頁確認連線後再試。',
    ),
    (78, 3238, 'research.minute.too_few_days', '目前微台合約可用的已收盤交易日太少（至少需要 3 天），等累積足夠的交易日後再試。'),
    (78, 3239, 'research.minute.source', '永豐 1 分 K（僅研究）'),
)

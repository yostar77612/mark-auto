"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (15, 1605, 'orders.line', '紙上 {0} · 剩餘 {1} · {2}'),
    (15, 1606, 'orders.buy', '買'),
    (15, 1607, 'orders.sell', '賣'),
    (15, 1608, 'orders.invalid_snapshot', '需要有效的紙上帳戶快照。'),
    (15, 1609, 'orders.pending', '改價處理中；以紙上帳本回讀為準。'),
    (15, 1610, 'orders.failed', '紙上改價失敗；原價格維持不變。'),
)

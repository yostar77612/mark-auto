"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (11, 1570, 'outcome.success.title', '連線作業已完成'),
    (11, 1571, 'outcome.success.body', '本次官方服務作業成功完成。'),
    (11, 1572, 'outcome.quota_exhausted.title', '可用額度已達限制'),
    (11, 1573, 'outcome.quota_exhausted.body', '方案用量已受限制；已消耗的額度不會退還。請核對官方用量，等待額度恢復後再安排作業。'),
    (11, 1574, 'outcome.auth_expired.title', '需要重新授權'),
    (11, 1575, 'outcome.auth_expired.body', '連線授權已失效或未被接受。請重新授權後核對連線狀態。'),
    (11, 1576, 'outcome.auth_expired.action', '重新授權'),
    (11, 1577, 'outcome.generic_failure.title', '本次作業未完成'),
    (11, 1578, 'outcome.generic_failure.body', '請保留現有紀錄並核對連線與作業狀態；不會自動重送。'),
)

"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (16, 1611, 'connection_test.button', '測試連線（少量額度／唯讀／unverified）'),
    (
        16,
        1612,
        'connection_test.disclosure',
        '本次測試會連網並使用少量額度，僅作唯讀連線查詢。成功僅表示連線有回應，不代表推論已驗證（unverified）。每次呼叫均需同意；不自動重試。',
    ),
    (16, 1613, 'connection_test.untested', '連線尚未測試或結果已過期（unverified）；更換帳號或模型後請重測。'),
    (16, 1614, 'connection_test.responded', '連線有回應（connection responded）；推論仍未驗證（unverified）。'),
    (16, 1615, 'connection_test.usage', '本次觀察用量：輸入 {0}、輸出 {1}、合計 {2} tokens。'),
    (16, 1616, 'connection_test.usage_unknown', '本次額度用量未知；可能已消耗額度，請核對官方用量。推論仍未驗證（unverified）。'),
)

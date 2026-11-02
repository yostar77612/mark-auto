"""M2-9 maintenance controls; append-only catalogue registration."""

ENTRIES = (
    (64, 2952, 'm2.maintenance.expiry', 'API 金鑰到期日'),
    (64, 2953, 'm2.maintenance.expiry_hint', 'YYYY-MM-DD；留空表示未知'),
    (64, 2954, 'm2.maintenance.expiry_unknown', 'API 金鑰到期日：未知'),
    (64, 2955, 'm2.maintenance.expired', 'API 金鑰已到期，請更新金鑰與到期日後重新連線。'),
    (64, 2956, 'm2.maintenance.expiry_due', 'API 金鑰剩餘 {} 天，請提前更新。'),
    (64, 2957, 'm2.maintenance.expiry_days', 'API 金鑰剩餘 {} 天。'),
    (64, 2958, 'm2.maintenance.minimum_fee', '每筆最低手續費（元）'),
    (64, 2959, 'm2.maintenance.tmf_fee', '微台每口手續費（元）'),
)

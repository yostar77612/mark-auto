"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (0, 73, 'expiry.product', '商品'),
    (0, 74, 'expiry.unavailable', '內建到期日資料未通過來源驗證，請手動提供到期日；不推算日期。'),
    (0, 75, 'expiry.month', '已核對合約月份'),
    (0, 76, 'expiry.manual', '手動輸入'),
    (0, 77, 'expiry.source', '檢視來源'),
    (0, 78, 'expiry.date', '已核對最後結算日：{}；可在原表格手動修改。'),
    (0, 79, 'expiry.uncovered', '內建到期日僅涵蓋 202510–202609 月契約；其他月份或週契約請手動提供到期日，不推算。交易日曆仍須手動提供。'),
    (
        0,
        80,
        'expiry.provenance',
        '官方來源：{}\n資料版本：{}\n核對日期：{}\n擷取日期：{}\n交易日曆未內建：官方 2026 年行事曆為彩色標記 PDF，無法機器核對；請沿用手動日曆。',
    ),
)

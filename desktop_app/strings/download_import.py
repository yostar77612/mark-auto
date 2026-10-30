"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (52, 2190, 'download_import.enabled', '下載後自動匯入研究資料'),
    (52, 2191, 'download_import.contract', '本次 TMF 明確合約'),
    (52, 2192, 'download_import.contract_example', 'TAIFEX:TMF:YYYYMM'),
    (52, 2193, 'download_import.calendar', '已核對的版本化交易日曆 JSON'),
    (52, 2194, 'download_import.browse_calendar', '選擇自動匯入交易日曆'),
    (
        52,
        2195,
        'download_import.hint',
        '下載的逐筆資料會依此合約合併，通過既有完整時段與資料品質檢查後才切換研究資料。日曆須涵蓋本次資料；不會推算休市、夜盤歸屬或補造缺失行情。',
    ),
    (52, 2196, 'download_import.action', '下載並自動匯入'),
    (52, 2197, 'download_import.consent', '同意本次連線至 TAIFEX，並依已核對的合約與交易日曆自動匯入'),
    (52, 2198, 'download_import.completed', '已下載 {0} 份資料，並匯入 {1} 根 K 棒（{2}）。可前往策略中心。'),
    (52, 2199, 'download_import.downloaded_only', '已下載 {0} 份資料；本次選擇僅下載，尚未匯入。'),
)

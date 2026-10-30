"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (11, 1579, 'job.stage.unknown', '作業處理中'),
    (11, 1580, 'job.stage.prepare_operation', '準備作業'),
    (11, 1581, 'job.stage.load_data', '讀取資料'),
    (11, 1582, 'job.stage.build_candidates', '準備策略'),
    (11, 1583, 'job.stage.run_backtest', '執行回測'),
    (11, 1584, 'job.stage.run_campaign', '執行研究'),
    (11, 1585, 'job.stage.run_operation', '執行作業'),
    (11, 1586, 'job.stage.write_result', '儲存結果'),
    (11, 1587, 'job.cancel', '取消'),
    (11, 1588, 'job.cancel_notice', '取消作業；已消耗的額度不會退還。'),
    (11, 1589, 'job.cancelled', '作業已取消；既有紀錄已保留，已消耗的額度不會退還。'),
    (34, 1780, 'job.idle_hint', '\u76ee\u524d\u6c92\u6709\u80cc\u666f\u4f5c\u696d'),
)

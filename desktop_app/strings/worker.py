"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (8, 1546, 'worker.stage.unknown', '作業失敗；既有資料已保留，請檢查輸入後重試。'),
    (8, 1547, 'worker.stage.prepare_operation', '作業準備失敗，請確認工作區狀態後重試。'),
    (8, 1548, 'worker.stage.load_data', '資料讀取失敗，請重新選取並檢查資料。'),
    (8, 1549, 'worker.stage.build_candidates', '策略準備失敗，請檢查策略設定與研究來源。'),
    (8, 1550, 'worker.stage.run_backtest', '回測執行失敗，請檢查資料與回測設定。'),
    (8, 1551, 'worker.stage.run_campaign', '研究執行失敗，請檢查資料、研究設定與來源狀態。'),
    (8, 1552, 'worker.stage.run_operation', '作業執行失敗，請檢查輸入與作業狀態後重試。'),
    (8, 1553, 'worker.stage.write_result', '結果儲存失敗，請檢查工作區權限與可用空間。'),
)

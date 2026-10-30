"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (0, 31, 'replay.unpaced', '不限速（單次執行）'),
    (0, 32, 'replay.speed', '重播速度'),
    (0, 33, 'replay.speed_tip', '1、2、5、10、50、100 倍；最高 100 倍。僅改變每次一根 K 棒操作之間的等待，不改變成交結果。'),
    (0, 34, 'replay.speed_value', '{}x'),
    (0, 35, 'replay.pause', '暫停重播'),
    (0, 36, 'replay.stop', '停止重播'),
    (0, 37, 'replay.stop_tip', '停止重播並開啟停止開關；保留游標。再次開始需要重新確認。'),
    (0, 38, 'replay.resume', '繼續重播'),
    (0, 39, 'replay.pause_tip', '在目前一根 K 棒完成後暫停並保存游標；不開啟停止開關。繼續從原游標重播。停止新委託仍會開啟停止開關。'),
    (0, 40, 'replay.state', '重播狀態'),
    (0, 41, 'replay.idle', '重播已停止'),
    (0, 42, 'replay.running', '重播進行中'),
    (0, 43, 'replay.paused', '重播已暫停'),
)

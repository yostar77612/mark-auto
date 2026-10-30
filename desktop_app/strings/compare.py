"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (2, 1412, 'compare.saved', '已儲存結果：勾選後比較，點欄名排序'),
    (2, 1413, 'compare.name', '選取／結果名稱'),
    (2, 1414, 'compare.family', '策略家族'),
    (2, 1415, 'compare.parameters', '主要參數'),
    (2, 1416, 'compare.range', '資料範圍'),
    (2, 1417, 'compare.created', '建立時間（台北）'),
    (2, 1418, 'compare.metric', '指標'),
    (2, 1419, 'compare.result', '結果 {0}'),
    (30, 1762, 'compare.overlay.title', 'Saved in-sample equity and drawdown overlay'),
    (30, 1763, 'compare.overlay.empty', 'No saved equity to display.'),
    (30, 1764, 'compare.overlay.equity', 'Equity (rebased)'),
    (30, 1765, 'compare.overlay.drawdown', 'Drawdown (peak-to-trough fraction)'),
    (30, 1766, 'compare.overlay.value', '{}: equity {}; drawdown {}'),
    (30, 1767, 'compare.overlay.legend', '{} {} {}'),
    (30, 1768, 'compare.overlay.summary', '{} series | {} - {} | {} invalid observations omitted'),
    (30, 1769, 'compare.overlay.cap', 'Displaying up to {} of {} selected results.'),
    (
        30,
        1770,
        'compare.overlay.normalisation',
        'Daily closing in-sample equity; each series rebased to 1.0 at its own first observation (positive initial equity required). Missing dates remain gaps. Left/Right keys inspect dates.',
    ),
)

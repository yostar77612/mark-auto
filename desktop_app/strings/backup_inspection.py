"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (32, 1773, 'backup_inspection.preview', '\u9810\u89bd\u5fa9\u539f\u5099\u4efd'),
    (32, 1774, 'backup_inspection.masked', '\u5df2\u96b1\u85cf'),
    (32, 1775, 'backup_inspection.unavailable', '\u5c1a\u7121\u5099\u4efd\u6216\u7121\u6cd5\u53d6\u5f97'),
    (32, 1776, 'backup_inspection.latest', '\u6700\u8fd1\u5099\u4efd\u6642\u9593\uff08\u672c\u6a5f\uff09\uff1a{0}\n\u5099\u4efd\u5927\u5c0f\uff1a{1}'),
    (32, 1777, 'backup_inspection.required', '\u8acb\u5148\u9810\u89bd\u9078\u53d6\u7684\u5099\u4efd\uff0c\u518d\u52fe\u9078\u540c\u610f\u5fa9\u539f\u3002'),
    (
        32,
        1778,
        'backup_inspection.summary',
        '\u552f\u8b80\u9810\u89bd\uff1a{0} \u500b\u9805\u76ee\uff08\u542b \u6e05\u55ae\uff09\n{1}\n\u5176\u4ed6\u6a94\u540d\u5df2\u96b1\u85cf\uff1a{2}\uff1b\u8d85\u904e\u5217\u8868\u4e0a\u9650\uff1a{3}\u3002\n\u50c5\u6aa2\u67e5\u76ee\u9304\u4e2d\u7e7c\u8cc7\u6599\uff1b\u5fa9\u539f\u6642\u4ecd\u9808\u901a\u904e\u5b8c\u6574\u9a57\u8b49\u3002',
    ),
    (
        33,
        1779,
        'backup_inspection.optional',
        '\u53ef\u9078\u64c7\u9810\u89bd\u5099\u4efd\u5167\u5bb9\uff1b\u5fa9\u539f\u4ecd\u9700\u540c\u610f\u8207\u78ba\u8a8d\u3002',
    ),
)

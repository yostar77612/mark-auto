"""Traditional Chinese feature literals; ordered records preserve the original catalog."""

ENTRIES = (
    (43, 1853, 'capital.title', '\u8cc7\u91d1\u60c5\u5883'),
    (43, 1854, 'capital.start', '\u8d77\u59cb\u8cc7\u91d1'),
    (43, 1855, 'capital.threshold', '\u8b66\u6212\u7dda'),
    (43, 1856, 'capital.days', '\u5929\u6578'),
    (43, 1857, 'capital.paths', '\u8def\u5f91\u6578'),
    (43, 1858, 'capital.run', '\u57f7\u884c\u8cc7\u91d1\u60c5\u5883'),
    (
        43,
        1859,
        'capital.run_tip',
        '\u4f7f\u7528\u5df2\u5132\u5b58\u7684\u6a23\u672c\u5916\u6bcf\u65e5\u5831\u916c\uff1b\u56fa\u5b9a\u7a2e\u5b50 1729\uff0c\u8def\u5f91\u6578\u4e58\u5929\u6578\u4e0a\u9650 1,000,000\u3002',
    ),
    (
        43,
        1860,
        'capital.disclaimer',
        '\u5047\u8a2d\u6bcf\u65e5\u7368\u7acb\u540c\u5206\u5e03\u3001\u4e0d\u8907\u5229\u3001\u4e0d\u4ee3\u8868\u5e02\u5834\u9810\u6e2c\u3001\u4e0d\u662f\u5f37\u5236\u5e73\u5009\u6a21\u578b',
    ),
    (
        43,
        1861,
        'capital.invalid',
        '\u8acb\u8f38\u5165\u6709\u6548\u6b63\u6578\uff1b\u8b66\u6212\u7dda\u9808\u4f4e\u65bc\u8d77\u59cb\u8cc7\u91d1\uff0c\u5929\u6578\u8207\u8def\u5f91\u6578\u9808\u70ba\u6b63\u6574\u6578\uff0c\u4e58\u7a4d\u4e0d\u5f97\u8d85\u904e 1,000,000\u3002',
    ),
    (43, 1862, 'capital.completed', '\u8cc7\u91d1\u60c5\u5883\u5df2\u5b8c\u6210\u3002'),
    (43, 1863, 'capital.cancelled', '\u8cc7\u91d1\u60c5\u5883\u5df2\u53d6\u6d88\uff1b\u4e0d\u986f\u793a\u90e8\u5206\u7d71\u8a08\u3002'),
    (43, 1864, 'capital.timed_out', '\u8cc7\u91d1\u60c5\u5883\u5df2\u903e\u6642\uff1b\u4e0d\u986f\u793a\u90e8\u5206\u7d71\u8a08\u3002'),
    (43, 1865, 'capital.rejected', '\u8cc7\u91d1\u60c5\u5883\u7121\u6cd5\u8a08\u7b97\uff1b\u8acb\u6838\u5c0d\u8f38\u5165\u8207\u6a23\u672c\u3002'),
    (43, 1866, 'capital.result', '\u8dcc\u7834\u6bd4\u4f8b\uff1a{0}\uff1b\u5be6\u969b\u8def\u5f91\u6578\uff1a{1}'),
    (43, 1867, 'capital.percentile', '\u671f\u672b\u6b0a\u76ca {0}% \u5206\u4f4d\u6578\uff1a{1}'),
)

"""The v2 application error catalogue; legacy keys and text remain immutable.

Composition copies the v1 catalogue. Importing v2 never adds codes to the public
v1 table, its ErrorCode enum, display labels or historical pickle identities.
"""

from types import MappingProxyType

from quantlab.errors import ERROR_TABLE as LEGACY_ERROR_TABLE, ErrorText


V2_ERROR_TEXT = {
    'capability_missing': ErrorText('目前帳戶或環境尚未具備這項能力。', '核對帳戶、商品、交易資格與權限證據；可先使用本機跨日模擬。'),
    'intraday_eligibility_missing': ErrorText(
        '尚未確認現股當沖資格，此策略的持有政策未變更。', '可建立現股做多、持有三至五個交易日的跨日版本；資格核實後再驗證當沖版本。'
    ),
    'eligibility_unknown': ErrorText('交易資格或可退出數量尚未確認。', '停止新倉，核對有效資格與券商可賣／可平量後再操作。'),
    'insufficient_funds': ErrorText('可用資金扣除既有承諾後不足。', '核對分帳配置、交割、保證金與未成交單；未交割賣款不能當作現金。'),
    'risk_rejected': ErrorText('這項操作未通過目前風險限制。', '核對單筆與當日上限、成本、滑價及既有風險預留，不會自行放寬限制。'),
    'risk_resized': ErrorText('原數量超過目前可承擔的風險或資金。', '重新預覽合法張股或口數後再送出；原單尚未送出。'),
    'stale_quote': ErrorText('行情或部位估值不新鮮，不能增加曝險。', '恢復有效行情並核對來源時間；無資料不會以零價格代替。'),
    'state_conflict': ErrorText('畫面或命令使用的狀態已變更。', '重新整理並核對目前委託與部位，再決定操作。'),
    'rate_limited': ErrorText('連接器查詢頻率已達限制。', '等待允許的查詢時點；結果未知的交易命令不會自動重送。'),
    'broker_rejected': ErrorText('券商拒絕這項委託。', '核對帳戶、商品與拒絕分類，保留原委託紀錄。'),
    'outcome_unknown': ErrorText('委託是否已被接受尚未確認。', '保留全部潛在資金與風險預留，先查詢及對帳，不要重送。'),
    'reconciliation_required': ErrorText('委託、成交、部位或資金仍有待核對項目。', '停止新倉並完成對帳；未知項目不會被清除或自動補送。'),
    'journal_failed': ErrorText('交易日誌無法可靠保存，新倉已停止。', '保留現有檔案，確認磁碟與儲存狀態後重新啟動並對帳。'),
    'research_timeout': ErrorText('隔離研究程序未在期限內完成。', '本次未產生可用證據；保護與行情程序仍獨立運作，請縮小資料範圍後明確重試。'),
    'research_worker_failed': ErrorText('隔離研究程序中斷或未回傳可驗證結果。', '保留原策略與交易狀態；核對本機診斷後明確重試，不會使用部分績效。'),
    'strategy_evidence_stale': ErrorText(
        '策略的規則、商品、費用、日曆或引擎來源已更新，需要重新研究。', '既有部位保留原政策與保護；重新驗證並研究新進場版本後再啟用。'
    ),
    'daily_baseline_required': ErrorText(
        '交易日已更新，前一交易日的損益基準尚未確認。', '先完成帳戶對帳並取得可信的前收盤估值；新倉保持停止，合法保護退出仍獨立核對。'
    ),
    'ownership_conflict': ErrorText('交易引擎未持有有效的執行權。', '使用目前有效引擎；舊程序不得繼續送出委託。'),
    'instrument_unresolved': ErrorText('商品規格或實際期貨月份尚未確認。', '核對有效規格、實際月份及到期日，不會猜測近月。'),
    'calendar_missing': ErrorText('版本化交易日曆未涵蓋所需時段。', '提供明確交易日與時段；不會自行推算休市日或虛構成交。'),
    'session_closed': ErrorText('目前不在已核准的執行時段。', '核對商品時段與日曆；夜盤執行預設關閉。'),
    'exit_unavailable': ErrorText('這筆部位目前沒有可合法退出的數量。', '核對部位來源與可賣／可平量；當日新買現股不會假設具備當沖資格。'),
    'exit_already_pending': ErrorText('這筆部位已有退出委託待處理。', '先核對現有退出單，不會重複送單或反向開倉。'),
    'external_position_difference': ErrorText('帳戶持股與系統管理部位不同。', '核對手機或人工交易；外部持股不會被自動賣出。'),
    'external_order_difference': ErrorText('帳戶存在系統未接管的活動委託。', '核對手機或人工委託並完成對帳，停止新倉。'),
}
if V2_ERROR_TEXT.keys() & LEGACY_ERROR_TABLE.keys():
    raise RuntimeError('v2 error code shadows the legacy catalogue')
ERROR_TABLE = MappingProxyType({**LEGACY_ERROR_TABLE, **V2_ERROR_TEXT})

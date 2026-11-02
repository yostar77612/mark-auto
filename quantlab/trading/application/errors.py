"""The v2 application error catalogue; legacy keys and text remain immutable.

Composition copies the v1 catalogue. Importing v2 never adds codes to the public
v1 table, its ErrorCode enum, display labels or historical pickle identities.
"""

from types import MappingProxyType

from quantlab.errors import ERROR_TABLE as LEGACY_ERROR_TABLE, ErrorText


V2_ERROR_TEXT = {
    'daily_not_sent_confirmation_required': ErrorText('宣告日 K 委託未送出需要擁有者確認。', '核對意圖與對帳結果後明確確認；此操作不會恢復交易或重送。'),
    'daily_not_sent_unproven': ErrorText('日誌尚不能證明這筆日 K 委託未送出。', '保留未知狀態，核對完整日誌；已持久化送單紀錄者不可宣告未送出。'),
    'daily_not_sent_order_found': ErrorText('對帳找到可能相符的券商委託。', '保留未知狀態並核對券商紀錄，不可宣告未送出。'),
    'daily_declared_not_sent': ErrorText('擁有者已確認這筆日 K 委託未送出。', '意圖已結案，交易仍暫停；完成對帳與明確恢復後才可評估新訊號。'),
    'daily_waiting_session': ErrorText('日 K 訊號已保存，等待下一個可信交易時段。', '保持程式與連線正常；下一交易日仍會重新核對報價、帳戶與風險。'),
    'daily_signal_expired': ErrorText('日 K 訊號已超過下一個可執行交易時段。', '不會追送舊訊號；等待新的完整日 K 評估。'),
    'daily_signal_invalidated': ErrorText('已保存訊號的策略、商品或證據已變更。', '核對策略版本與紀錄；舊訊號不會改套新版本或新合約。'),
    'daily_signal_unresolved': ErrorText('日 K 執行紀錄仍有未確認結果。', '保持停止新倉，先完成對帳；不會自動重送。'),
    'daily_close_unverified': ErrorText('缺少可驗證的帳戶收盤基準。', '核對收盤報價、完整對帳及日期；不會使用今日損益代替昨收。'),
    'daily_signal_not_authorized': ErrorText('日 K 送單缺少有效的已保存訊號授權。', '先完成對帳與檢查，並由使用者恢復；沒有明確訊號不會下單。'),
    'daily_signal_source_unverified': ErrorText('日 K 訊號來源尚未驗證。', '先取得與研究一致的官方日 K 證據；不會使用分鐘合成或未知來源開新倉。'),
    'daily_signal_basis_mismatch': ErrorText('研究與執行的日 K 價格基準不一致。', '核對官方來源、還原方式及觀察日期後重新研究，不會拼接不同基準。'),
    'daily_signal_not_available': ErrorText('官方日 K 尚未完整可用。', '等待可信資料完成；不補造缺少的價格或跨交易日追單。'),
    'research_cancelled': ErrorText('研究已取消，未發布新的證據。', '既有研究結果保留；需要時可重新執行。'),
    'stock_entitlement_unknown': ErrorText(
        '研究持倉跨越尚未確認經濟權益的除權息事件，未產生證據。', '補齊可驗證的現金或股票權益資訊；不得由參考價比率猜測損益。'
    ),
    'official_stock_invalid': ErrorText('官方股票資料未通過驗證，原資料已保留。', '核對上市／上櫃來源格式與日期後重新匯入。'),
    'official_stock_consent_required': ErrorText('尚未同意下載官方股票資料。', '確認來源及日期後明確執行下載。'),
    'official_stock_coverage_missing': ErrorText('股票日線尚未完整涵蓋研究區間。', '補齊至少五年的官方日線與除權息資料，不使用不完整資料產生證據。'),
    'api_key_expiry_unknown': ErrorText('API 金鑰到期日未知。', '核對永豐金鑰有效期限並填寫到期日。'),
    'api_key_expired': ErrorText('設定的 API 金鑰已到期，不能登入或自動開新倉。', '更新金鑰引用及到期日後重新連線。'),
    'api_key_renewal_due': ErrorText('API 金鑰將在十四天內到期。', '請提前更新金鑰與到期日。'),
    'calendar_coverage_missing': ErrorText('交易日曆未涵蓋未來三十個交易日。', '更新已驗證且版本化的日曆；自動新倉保持停止。'),
    'expiry_coverage_missing': ErrorText('期貨到期資料未涵蓋未來三十個交易日。', '沿用既有期交所到期日更新工具，核對官方資料後匯入。'),
    'calendar_annual_update_due': ErrorText('十二月起請更新下一年度交易日曆與期貨到期資料。', '核對官方版本與覆蓋範圍，未涵蓋時不自動開新倉。'),
    'automatic_paused': ErrorText('自動交易已暫停，等待恢復。', '先核對暫停原因、完成對帳，再由使用者恢復。'),
    'automatic_daily_execution_pending': ErrorText(
        '日 K 自動送單尚待下一交易時段執行支援。', '目前可使用已完成驗證的分鐘策略；日 K 研究與本機交易日推進仍可使用。'
    ),
    'program_restarted': ErrorText('程式重新啟動，自動新倉保持停止。', '先完成對帳及檢查，再由使用者恢復。'),
    'order_result_unknown': ErrorText('自動委託結果未知。', '保留資金與委託紀錄；對帳確認前不會重送。'),
    'automatic_overdue_position': ErrorText('收盤後仍有當沖部位待處理。', '核對券商回報與剩餘部位，保持停止新倉。'),
    'automatic_bar_overflow': ErrorText('自動交易的完成 K 棒佇列已超出容量。', '核對行情與執行狀態，完成對帳後再恢復。'),
    'automatic_market_gap': ErrorText('自動交易行情序列或連線世代已改變。', '完成對帳與行情檢查後，再由使用者恢復。'),
    'intraday_force_exit': ErrorText('已到當沖強制平倉時間，自動新倉已停止。', '核對平倉委託及剩餘部位；只有已確認取消的委託才可重送。'),
    'reconciled_waiting_resume': ErrorText('自動交易已完成對帳，等待恢復。', '確認檢查結果後，由使用者恢復新倉。'),
    'account_daily_loss_limit': ErrorText('帳戶已達單日虧損上限，新倉停止。', '今日不能解除；核對部位並保留保護性出場。'),
    'account_order_limit': ErrorText('委託金額超過帳戶單筆上限。', '調整策略新版本的數量或帳戶上限，再明確恢復。'),
    'account_position_limit': ErrorText('帳戶已達最大同時持倉數。', '未成交進場單也占用名額；核對後明確恢復。'),
    'account_daily_baseline_required': ErrorText('缺少帳戶前一交易日的可靠結算紀錄。', '新倉保持暫停；取得對應日期的結算證據後再恢復。'),
    'preflight_blocked': ErrorText('今日開盤檢查尚未通過。', '查看檢查清單；當日失敗紀錄會保留，保護性出場不受影響。'),
    'preflight_connection': ErrorText('開盤檢查：連線未就緒。', '確認永豐連線；今日自動新倉保持停止。'),
    'preflight_account': ErrorText('開盤檢查：帳戶未就緒。', '確認已選帳戶及簽署狀態。'),
    'preflight_permission': ErrorText('開盤檢查：交易權限尚未證實。', '完成目前連線的模擬下單測試；登入不代表有交易權限。'),
    'preflight_ca': ErrorText('開盤檢查：憑證狀態未就緒。', '模擬環境不需要 CA；正式環境仍不能送單。'),
    'preflight_market': ErrorText('開盤檢查：行情不是即時資料。', '確認目前連線的行情時間與資料完整性。'),
    'preflight_service': ErrorText('開盤檢查：目前不在可驗證的模擬服務時段。', '核對交易日曆與券商回應。'),
    'preflight_reconciliation': ErrorText('開盤檢查：對帳未通過。', '核對委託、成交與部位；未知結果不會自動重送。'),
    'strategy_parameters_invalid': ErrorText('策略參數不符合型態規則。', '依型態的週期、停損及口數範圍調整。'),
    'strategy_instrument_restricted': ErrorText('此型態不支援選取的商品。', '當沖選微台；短波與長波選股票或 ETF。'),
    'strategy_daytrade_confirmation_required': ErrorText('現股當沖尚未勾選並確認資格。', '確認具備現股當沖資格與額度後再建立。'),
    'strategy_allocation_exceeded': ErrorText('啟用策略的資金總和超過帳戶配置。', '降低配置或先停用其他策略。'),
    'strategy_has_fills': ErrorText('已有成交紀錄的策略不能刪除。', '停用策略並保留成交紀錄。'),
    'strategy_settlement_day': ErrorText('微台結算日停止自動開新倉。', '保留保護性出場，下一交易日再確認。'),
    'strategy_size_insufficient': ErrorText('可用資金不足以建立指定部位。', '股票至少一整張；微台須涵蓋保證金與成本。'),
    'manual_allocation_exceeds_settings': ErrorText(
        '人工模擬帳本的已確認額度超過目前配置。', '核對證券及期貨配置後再操作；原帳本與損益紀錄不會重設，合法退出仍可另行核對。'
    ),
    'manual_not_submitted': ErrorText('日誌已確認這個要求尚未進入券商送單流程。', '原要求不會重送；核對帳本並明確恢復後，重新預覽建立新的要求。'),
    'manual_book_not_enabled': ErrorText('尚未啟用這個帳戶的人工模擬帳本。', '確認應用程式虛擬額度及空倉對帳結果後啟用；這不是券商餘額。'),
    'manual_confirmation_required': ErrorText('這項人工模擬操作需要明確確認。', '核對帳戶、目前狀態與風險預覽後再確認。'),
    'manual_account_observation_required': ErrorText('尚未取得完整且新鮮的委託與部位對帳。', '等待帳戶查詢完成；未知資料不會視為空倉或零餘額。'),
    'manual_test_required': ErrorText('尚未完成這次連線的微台模擬測試。', '確認虛擬額度後執行單筆測試；遠離行情的價格仍可能成交。'),
    'manual_futures_test_required': ErrorText('請先切換已勾選的期貨帳戶完成微台測試。', '測試只證明這次連線的微台委託結果，其他商品仍以券商實際回報為準。'),
    'manual_test_pending': ErrorText('微台測試委託仍待確認。', '保留原要求與風險預留，等待回報與對帳，不要重送。'),
    'manual_unprotected_position': ErrorText('人工模擬帳本仍有未建立保護單的部位。', '風險估算價不代表已掛停損；請人工管理並核對部位。'),
    'manual_restarted': ErrorText('人工模擬帳本已重新啟動，新單暫停。', '重新對帳後明確確認恢復；原額度與損益紀錄會保留。'),
    'manual_day_baseline_required': ErrorText('人工模擬帳本缺少跨日收盤證據。', '新倉保持停止，不會虛構前收盤損益或重設額度。'),
    'manual_declared_not_sent': ErrorText('擁有者已確認這筆委託從未送到券商。', '原要求不會重送；對帳完成並明確恢復後，重新預覽建立新的要求。'),
    'manual_amend_not_applied': ErrorText('券商對帳顯示改價沒有生效，原委託價格不變。', '原委託仍在；需要時可撤單或重新提出改價。'),
    'manual_cancel_not_applied': ErrorText('券商對帳顯示撤單沒有生效，委託仍在。', '確認仍要撤單時可再次撤單；重複撤單不會增加風險。'),
    'price_deviation': ErrorText('限價偏離目前買賣價太多，可能以不利價格成交。', '把限價調回接近目前買賣價後重新預覽；原單尚未送出。'),
    'manual_quantity_amend_unsupported': ErrorText('本輪人工模擬只支援不增加風險的改價。', '數量修改尚未開放；先核對已成交及剩餘委託，必要時明確撤單。'),
    'production_orders_disabled': ErrorText('正式環境的下單、改單與撤單尚未啟用。', '此環境可查看行情與帳務；請切換至券商模擬測試委託。'),
    'market_data_not_configured': ErrorText('尚未設定行情連線。', '到設定頁填入環境與 API 金鑰引用名稱。'),
    'market_data_login_failed': ErrorText('行情登入失敗。', '確認金鑰已用 store_sinopac_key.py 存入，並檢查網路後重試。'),
    'market_sdk_missing': ErrorText('此安裝版未包含永豐元件，', '請安裝新版'),
    'market_data_not_connected': ErrorText('行情未連線。', '先連線，或改看本機已有的歷史 K 線。'),
    'history_quota_low': ErrorText('今日行情流量將滿。', '歷史更新已暫停，明日或額度恢復後再試。'),
    'history_query_failed': ErrorText('歷史 K 線更新失敗。', '保留本機已有資料，恢復行情連線後按重試。'),
    'symbol_not_found': ErrorText('找不到這個商品。', '確認股號；未連線時只能搜尋本機已有資料。'),
    'kline_store_unavailable': ErrorText('本機 K 線庫無法使用。', '原檔已保留，已建立新檔；可重新更新歷史。'),
    'alert_invalid_params': ErrorText('警示參數不正確。', '依欄位提示修正後再建立。'),
    'alert_store_unavailable': ErrorText('警示檔案無法使用。', '保留原檔，檢查工作區寫入權限後重試。'),
    'subscription_limit_reached': ErrorText('行情訂閱額度已滿。', '移除自選商品後再試；既有策略訂閱保留。'),
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

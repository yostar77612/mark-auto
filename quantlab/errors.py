"""Shared failure construction and the fixed desktop error-code catalogue.

Legacy exception modules remain their public import and pickle paths. Messages
are passed through verbatim; validation does not infer codes from arbitrary text.
"""

from dataclasses import dataclass
from enum import Enum


class RecoveryError(ValueError):
    pass


# Preserve the original public pickle path.
RecoveryError.__module__ = 'quantlab.analysis_recovery'


def fail(message, exception_type, *args):
    raise exception_type(message, *args)


def saved_candidate_reason(message):
    code = 'source_invalid_evidence'
    for fragment, reason in (
        ('strictly before', 'source_temporal_overlap'),
        ('Duplicate source candidate', 'source_duplicate_structure'),
        ('terminal completed', 'source_not_completed'),
        ('producer protocol', 'source_producer_unsupported'),
        ('Source registry', 'source_registry_mismatch'),
        ('Manual source', 'source_manual_exchange_missing'),
        ('Source provider Decimal context', 'source_provider_decimal_context_unsupported'),
        ('provider protocol implementation', 'source_provider_provenance_invalid'),
        ('provider protocol descriptor', 'source_provider_provenance_invalid'),
        ('Source provider receipt', 'source_provider_receipt_invalid'),
        ('provider protocol', 'source_provider_unsupported'),
        ('journal/export mismatch', 'source_journal_mismatch'),
        ('original dataset identity', 'source_dataset_mismatch'),
        ('Original dataset', 'source_dataset_mismatch'),
        ('original Dataset', 'source_dataset_mismatch'),
        ('No evaluated candidates', 'source_no_evaluated_candidates'),
        ('1..15', 'source_candidate_limit'),
        ('resource bounds', 'source_resource_limit'),
        ('audit byte limit', 'source_resource_limit'),
        ('Missing', 'source_missing_evidence'),
    ):
        if fragment in message:
            code = reason
            break
    return code


@dataclass(frozen=True)
class ErrorText:
    explanation: str
    action: str


# Define each code exactly once; labels below are a compatibility projection.
ERROR_TABLE = {
    'paper_manual_order_lock': ErrorText(
        '\u5df2\u505c\u6b62\u65b0\u59d4\u8a17\uff1b\u8acb\u5148\u6309\u300c\u6062\u5fa9\u65b0\u59d4\u8a17\u300d',
        '\u8acb\u5148\u6838\u5c0d\u5b8c\u6574\u53c3\u8003\u5feb\u7167\u4e26\u5c0d\u5e33\u3002',
    ),
    'agent_reference_not_found': ErrorText('找不到唯一且有效的訓練引用。', '請重新從 @ 清單選擇。'),
    'agent_tool_refused': ErrorText('AI 工具請求被拒絕：工具未註冊、未宣告能力或輸入格式不符。', '請改用已註冊的唯讀工具、明確的能力宣告與有效的 JSON 輸入。'),
    'explicit_host_recovery_required': ErrorText(
        '發現先前的 ChatGPT 記錄；不會重建識別或重設額度。請先檢查原登入資料，必要時使用進階明確復原。', '請核對官方連線與本機紀錄後再操作。'
    ),
    'first_use_check_unavailable': ErrorText('無法核對是否為首次設定；不會開始登入。', '請核對官方連線與本機紀錄後再操作。'),
    'registration_retry_required': ErrorText(
        '授權碼已失效；已保留待驗證註冊。請讀取本機連線，選定該紀錄後明確重新授權。尚未授予身分或推論權限。', '請核對官方連線與本機紀錄後再操作。'
    ),
    'host_initialization_required': ErrorText('尚未初始化本機安全識別。請明確選擇首次設定／復原。', '請核對官方連線與本機紀錄後再操作。'),
    'authorization_failed': ErrorText('本次授權未完成；請核對官方登入與本機連線狀態。不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'authorization_exchange_failed': ErrorText('授權交換階段未完成；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'authorization_identity_failed': ErrorText('官方身分驗證階段未完成；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'authorization_tokens_failed': ErrorText('登入回應格式驗證未完成；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'authorization_storage_failed': ErrorText('本機連線儲存階段未完成；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'authorization_busy': ErrorText('已有授權作業，請先等待或停止。', '請核對官方連線與本機紀錄後再操作。'),
    'authorization_timeout': ErrorText('官方授權等待逾時。', '請核對官方連線與本機紀錄後再操作。'),
    'account_mismatch': ErrorText('帳戶與原連線不符，原紀錄保留。', '請核對官方連線與本機紀錄後再操作。'),
    'previous_completion_unknown': ErrorText('先前請求完成狀態未知，禁止重送或退還次數。', '請核對官方連線與本機紀錄後再操作。'),
    'account_paused': ErrorText('此帳戶已暫停；新研究或模型不會解除限制。', '請核對官方連線與本機紀錄後再操作。'),
    'active_or_unknown_request': ErrorText('仍有執行中或結果未知的請求，無法解除暫停。', '請核對官方連線與本機紀錄後再操作。'),
    'unknown_outcome_requires_manual_resolution': ErrorText('完成狀態未知，須另行核對；不能重設或退還次數。', '請核對官方連線與本機紀錄後再操作。'),
    'local_signout_persistence_failed': ErrorText('本機登出保存失敗，請勿假設已登出。', '請核對官方連線與本機紀錄後再操作。'),
    'network_disabled': ErrorText('尚未同意本次連線。', '請核對官方連線與本機紀錄後再操作。'),
    'plan_scope_missing': ErrorText('此連線沒有訂閱推論權限。', '請核對官方連線與本機紀錄後再操作。'),
    'refresh_required': ErrorText('連線到期，請明確更新或重新授權。', '請核對官方連線與本機紀錄後再操作。'),
    'reauthorization_required': ErrorText('必須重新授權；不會重用不確定的舊憑證。', '請核對官方連線與本機紀錄後再操作。'),
    'http_transport_failed': ErrorText('連線官方模型服務時傳輸失敗（網路／TLS／連線中斷）；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'deadline_exceeded': ErrorText('官方模型服務在期限內未完成；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'redirect_rejected': ErrorText('官方模型服務要求轉址；依規則拒絕，不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'invalid_content_type': ErrorText('官方回應的內容類型不符；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'compressed_response': ErrorText('官方回應使用不支援的壓縮；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'stream_byte_limit': ErrorText('官方回應超過大小限制；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'invalid_catalog': ErrorText('官方模型清單格式驗證未完成；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'duplicate_model': ErrorText('官方模型清單含重複項目，已拒絕；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'invalid_credential': ErrorText('本機存取憑證格式不符；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'credential_diagnosis': ErrorText('官方回應 401：存取憑證未被接受；請重新授權，不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'grant_blocked': ErrorText('官方回應 403：此連線未被授予所需權限；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'transient_blocked': ErrorText('官方服務暫時不可用（503 或使用量暫不可用）；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'eligibility_blocked': ErrorText('官方表示此帳戶目前不符合訂閱共用資格；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'quota_paused': ErrorText('官方表示方案用量已達上限；已暫停，不切換付費 API。', '請核對官方連線與本機紀錄後再操作。'),
    'configuration_blocked': ErrorText('官方表示此路由不受支援；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'invalid_request': ErrorText('官方表示此請求能力不受支援；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'models_http_bad_request': ErrorText('官方模型服務回應 400；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'models_http_not_found': ErrorText('官方模型服務回應 404；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'models_http_rate_limited': ErrorText('官方模型服務回應 429；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'models_http_server_error': ErrorText('官方模型服務回應 5xx；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'models_http_other': ErrorText('官方模型服務回應其他非成功狀態；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'operation_failed_plan': ErrorText('官方模型服務作業未完成（未列入固定分類的本機檢查）；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'operation_failed_auth': ErrorText('本機連線授權檢查未完成（未列入固定分類）；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'operation_failed_local': ErrorText('本機檔案或儲存作業未完成；不會自動重試。', '請核對官方連線與本機紀錄後再操作。'),
    'history_confirmation_required': ErrorText('請先確認此時段的實際契約與日期歸屬。', '請核對並勾選時段確認。'),
    'history_expiry_invalid': ErrorText('請填寫有效到期年月 YYYYMM。', '請核對契約到期年月。'),
    'history_date_invalid': ErrorText('請明確填寫有效 YYYY-MM-DD 日期。', '請核對時段起迄日期。'),
    'history_session_invalid': ErrorText('時段驗證失敗。', '請核對實際契約、交易日與起迄時間。'),
    'history_session_limit': ErrorText('單次最多 128 個明確時段。', '請移除多餘時段後再加入。'),
    'history_session_duplicate': ErrorText('這個時段已加入。', '請核對已加入的時段清單。'),
    'history_session_day_overlap': ErrorText('同契約交易日的時段不可重複或重疊。', '請核對已加入的時段清單。'),
    'history_session_overlap': ErrorText('同契約時段不可重疊。', '請核對時段起迄時間與收盤端點。'),
    'history_file_required': ErrorText('請選擇本機 CSV 或 RPT 檔案。', '請重新選取歷史逐筆資料檔。'),
    'history_sessions_required': ErrorText('請先加入至少一個已確認時段。', '請核對時段並加入清單後再匯入。'),
    'operation_failed': ErrorText('作業失敗，未能完成。', '請保留現有資料，核對狀態後再操作。'),
    'validation_failed': ErrorText('輸入驗證失敗，作業未完成。', '請選擇資料並核對輸入、同意與確認欄位。'),
    'market_data_invalid': ErrorText('市場資料驗證失敗。', '請核對資料格式與週期，保留原檔。'),
    'restore_refresh_failed': ErrorText('還原登入時更新連線失敗。', '請重新登入 ChatGPT；不會自動重試。'),
    'authorization_cleanup_failed': ErrorText('授權收尾階段未完成。', '請等待背景程序停止，再核對連線並重新登入。'),
    'startup_sqlite_old': ErrorText('無法啟動：資料庫引擎版本過舊。', '請安裝含 SQLite 3.51.3 或更新版本的 MarkAuto 安裝包。'),
    'startup_workspace_incompatible': ErrorText('無法啟動：工作區格式與此版本不相容。', '請使用相容版本開啟，或還原相容備份；原資料已保留。'),
    'startup_workspace_busy': ErrorText('無法啟動：工作區正由另一個程序使用。', '請切回既有視窗，或關閉該程序後再啟動。'),
    'startup_failed': ErrorText('程式啟動失敗，原資料已保留。', '請重新安裝相容版本，或還原相容備份。'),
}
ERROR_LABELS = {code: text.explanation for code, text in ERROR_TABLE.items()}


# The catalogue is the sole code list. Keep public table keys plain strings.
ErrorCode = Enum('ErrorCode', {code.upper(): code for code in ERROR_TABLE}, type=str)

# ErrorText is still publicly re-exported by the desktop catalogue module.
ErrorText.__module__ = 'quantlab.desktop_errors'

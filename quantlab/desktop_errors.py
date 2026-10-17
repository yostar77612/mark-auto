"""Fixed desktop error catalogue. Exception values never become display/log text."""
from dataclasses import dataclass
import sqlite3

@dataclass(frozen=True)
class ErrorText:
    explanation: str
    action: str

ERROR_LABELS = {'explicit_host_recovery_required':'發現先前的 ChatGPT 記錄；不會重建識別或重設額度。請先檢查原登入資料，必要時使用進階明確復原。',
    'first_use_check_unavailable':'無法核對是否為首次設定；不會開始登入。',
    'registration_retry_required':'授權碼已失效；已保留待驗證註冊。請讀取本機連線，選定該紀錄後明確重新授權。尚未授予身分或推論權限。',
    'host_initialization_required':'尚未初始化本機安全識別。請明確選擇首次設定／復原。',
    'authorization_failed':'本次授權未完成；請核對官方登入與本機連線狀態。不會自動重試。',
    'authorization_exchange_failed':'授權交換階段未完成；不會自動重試。',
    'authorization_identity_failed':'官方身分驗證階段未完成；不會自動重試。',
    'authorization_tokens_failed':'登入回應格式驗證未完成；不會自動重試。',
    'authorization_storage_failed':'本機連線儲存階段未完成；不會自動重試。',
    'authorization_busy':'已有授權作業，請先等待或停止。', 'authorization_timeout':'官方授權等待逾時。',
    'account_mismatch':'帳戶與原連線不符，原紀錄保留。', 'previous_completion_unknown':'先前請求完成狀態未知，禁止重送或退還次數。',
    'account_paused':'此帳戶已暫停；新研究或模型不會解除限制。',
    'active_or_unknown_request':'仍有執行中或結果未知的請求，無法解除暫停。',
    'unknown_outcome_requires_manual_resolution':'完成狀態未知，須另行核對；不能重設或退還次數。',
    'local_signout_persistence_failed':'本機登出保存失敗，請勿假設已登出。',
    'network_disabled':'尚未同意本次連線。', 'plan_scope_missing':'此連線沒有訂閱推論權限。',
    'refresh_required':'連線到期，請明確更新或重新授權。',
    'reauthorization_required':'必須重新授權；不會重用不確定的舊憑證。'}
ERROR_LABELS.update({
    'http_transport_failed':'連線官方模型服務時傳輸失敗（網路／TLS／連線中斷）；不會自動重試。',
    'deadline_exceeded':'官方模型服務在期限內未完成；不會自動重試。',
    'redirect_rejected':'官方模型服務要求轉址；依規則拒絕，不會自動重試。',
    'invalid_content_type':'官方回應的內容類型不符；不會自動重試。',
    'compressed_response':'官方回應使用不支援的壓縮；不會自動重試。',
    'stream_byte_limit':'官方回應超過大小限制；不會自動重試。',
    'invalid_catalog':'官方模型清單格式驗證未完成；不會自動重試。',
    'duplicate_model':'官方模型清單含重複項目，已拒絕；不會自動重試。',
    'invalid_credential':'本機存取憑證格式不符；不會自動重試。',
    'credential_diagnosis':'官方回應 401：存取憑證未被接受；請重新授權，不會自動重試。',
    'grant_blocked':'官方回應 403：此連線未被授予所需權限；不會自動重試。',
    'transient_blocked':'官方服務暫時不可用（503 或使用量暫不可用）；不會自動重試。',
    'eligibility_blocked':'官方表示此帳戶目前不符合訂閱共用資格；不會自動重試。',
    'quota_paused':'官方表示方案用量已達上限；已暫停，不切換付費 API。',
    'configuration_blocked':'官方表示此路由不受支援；不會自動重試。',
    'invalid_request':'官方表示此請求能力不受支援；不會自動重試。',
    'models_http_bad_request':'官方模型服務回應 400；不會自動重試。',
    'models_http_not_found':'官方模型服務回應 404；不會自動重試。',
    'models_http_rate_limited':'官方模型服務回應 429；不會自動重試。',
    'models_http_server_error':'官方模型服務回應 5xx；不會自動重試。',
    'models_http_other':'官方模型服務回應其他非成功狀態；不會自動重試。',
    'operation_failed_plan':'官方模型服務作業未完成（未列入固定分類的本機檢查）；不會自動重試。',
    'operation_failed_auth':'本機連線授權檢查未完成（未列入固定分類）；不會自動重試。',
    'operation_failed_local':'本機檔案或儲存作業未完成；不會自動重試。'})

ERROR_TABLE = {code: ErrorText(label, '請核對官方連線與本機紀錄後再操作。') for code, label in ERROR_LABELS.items()}
ERROR_TABLE.update({
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
})
ERROR_LABELS = {code: text.explanation for code, text in ERROR_TABLE.items()}


def error_message(code):
    code = code if isinstance(code, str) and code in ERROR_TABLE else 'operation_failed'
    text = ERROR_TABLE[code]
    return f'{text.explanation} {text.action}（錯誤代碼：{code}）'


def exception_code(exc):
    # Only exact allowlisted constants may be inspected; never call str/repr.
    code = getattr(exc, 'code', None)
    if isinstance(code, str) and code in ERROR_TABLE:
        return code
    if len(exc.args) == 1 and type(exc.args[0]) is str and exc.args[0] in ERROR_TABLE:
        return exc.args[0]
    if isinstance(exc, (OSError, sqlite3.Error)):
        return 'operation_failed_local'
    if isinstance(exc, ValueError):
        return 'validation_failed'
    return 'operation_failed'


def startup_error_code(exc):
    from quantlab.desktop_runtime import RuntimeSafetyError
    if isinstance(exc, RuntimeSafetyError) and len(exc.args) == 1 and type(exc.args[0]) is str:
        return {
            'This workspace requires a WAL-safe SQLite runtime (3.51.3 or newer)': 'startup_sqlite_old',
            'Unsupported workspace version; original preserved': 'startup_workspace_incompatible',
            'Unsupported workspace pointer; original preserved': 'startup_workspace_incompatible',
            'Another MarkAuto instance is using this installation': 'startup_workspace_busy',
        }.get(exc.args[0], 'startup_failed')
    return 'startup_failed'

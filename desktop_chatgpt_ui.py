"""Official subscription connection UI, wired into the desktop host.

The host owns an allowlisted bounded PROCESS, cancellation/join, the fixed
bootstrap/control paths and browser presentation. No token, vault, HTTP, browser
or process work occurs at import/construction. AuthSession must be created inside
one worker and remain there through begin/poll. All test transports are fixtures.
"""
from dataclasses import dataclass, field, asdict
import re
import time
from urllib.parse import urlsplit, parse_qsl

from PySide6.QtCore import QObject, Signal, Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox, QMessageBox)

USAGE_SETTINGS_URL = 'https://chatgpt.com/settings/usage'

ACTIONS = frozenset(('initialize', 'begin', 'first_sign_in', 'enable_plan', 'list', 'select', 'sign_out', 'refresh', 'models', 'clear_pause'))
STATES = frozenset(('host_initialization_required', 'disconnected', 'initialized', 'authorizing', 'validating', 'plan_ready',
    'identity_only', 'refresh_required', 'registration_retry_required', 'reauthorization_required', 'authorization_failed',
    'timeout', 'cancelled', 'transient_blocked', 'client_configuration_required', 'unknown'))
STATE_LABELS = {'host_initialization_required':'尚未初始化本機識別；只能由您明確設定或復原', 'disconnected':'未連線', 'initialized':'本機識別已初始化，尚未授權',
    'authorizing':'等待您在官方網站授權', 'validating':'正在驗證官方回應',
    'plan_ready':'本機憑證具訂閱權限；實際推論尚未驗證', 'identity_only':'僅身分登入，沒有訂閱推論權限',
    'refresh_required':'需要明確更新連線', 'reauthorization_required':'需要重新授權',
    'registration_retry_required':'註冊待驗證；請明確重新授權，此紀錄沒有身分或推論權限',
    'authorization_failed':'授權未完成', 'timeout':'授權逾時', 'cancelled':'本次授權已取消',
    'transient_blocked':'暫時無法使用；不會自動重試', 'client_configuration_required':'需檢查官方用戶端設定',
    'unknown':'狀態待核對；不能視為已登出或未扣額度'}
ERROR_LABELS = {'explicit_host_recovery_required':'發現先前的 ChatGPT 記錄；不會重建識別或重設額度。請先檢查原登入資料，必要時使用進階明確復原。',
    'first_use_check_unavailable':'無法核對是否為首次設定；不會開始登入。',
    'registration_retry_required':'授權碼已失效；已保留待驗證註冊。請讀取本機連線，選定該紀錄後明確重新授權。尚未授予身分或推論權限。',
    'host_initialization_required':'尚未初始化本機安全識別。請明確選擇首次設定／復原。',
    'authorization_busy':'已有授權作業，請先等待或停止。', 'authorization_timeout':'官方授權等待逾時。',
    'account_mismatch':'帳戶與原連線不符，原紀錄保留。', 'previous_completion_unknown':'先前請求完成狀態未知，禁止重送或退還次數。',
    'account_paused':'此帳戶已暫停；新研究或模型不會解除限制。',
    'active_or_unknown_request':'仍有執行中或結果未知的請求，無法解除暫停。',
    'unknown_outcome_requires_manual_resolution':'完成狀態未知，須另行核對；不能重設或退還次數。',
    'local_signout_persistence_failed':'本機登出保存失敗，請勿假設已登出。',
    'network_disabled':'尚未同意本次連線。', 'plan_scope_missing':'此連線沒有訂閱推論權限。',
    'refresh_required':'連線到期，請明確更新或重新授權。',
    'reauthorization_required':'必須重新授權；不會重用不確定的舊憑證。'}
RECOVERABLE_PAUSES = frozenset(('eligibility_blocked','quota_paused','transient_blocked','invalid_request','configuration_blocked','credential_diagnosis','grant_blocked'))
REF = r'[a-f0-9]{32}'
MODEL = r'[A-Za-z0-9._:-]{1,128}'


def _ref(value, optional=False):
    if optional and value is None: return
    if not isinstance(value,str) or not re.fullmatch(REF, value): raise ValueError('invalid opaque registration')


def official_authorization_url(value):
    """Validate only an auth worker URL; never accepts tokens, hints or arbitrary URLs."""
    if not isinstance(value,str) or len(value)>8192: raise ValueError('invalid authorization destination')
    url=urlsplit(value)
    if (url.scheme!='https' or url.netloc!='auth.openai.com' or url.path!='/api/accounts/authorize'
        or url.fragment or any(c.isspace() for c in value)): raise ValueError('invalid authorization destination')
    pairs=parse_qsl(url.query,keep_blank_values=True,strict_parsing=True)
    params=dict(pairs)
    required={'client_id','ext_agent_host_id','response_type','redirect_uri','scope','resource','state','nonce','code_challenge_method','code_challenge'}
    if len(params)!=len(pairs) or not required<=params.keys() or set(params)-required-{'agent_name_hint','prompt'}:
        raise ValueError('invalid authorization parameters')
    callback=urlsplit(params['redirect_uri'])
    try: port=callback.port
    except ValueError: raise ValueError('invalid callback') from None
    if (callback.scheme!='http' or callback.hostname!='127.0.0.1' or not port or callback.username
        or callback.password or callback.path!='/auth/callback' or callback.query or callback.fragment): raise ValueError('invalid callback')
    if params['response_type']!='code' or params['resource']!='https://api.openai.com/v1' or params['code_challenge_method']!='S256':
        raise ValueError('invalid authorization flow')
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,256}',params['client_id']) or not re.fullmatch(r'urn:uuid:[a-fA-F0-9-]{36}',params['ext_agent_host_id']):raise ValueError('invalid public client binding')
    for key in ('state','nonce','code_challenge'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',params[key]): raise ValueError('invalid authorization binding')
    if set(params['scope'].split())!={'openid','profile','email','offline_access','resource.invoke','chatgpt.tokens.use.direct'}:
        raise ValueError('invalid authorization scope')
    if 'prompt' in params and (params['prompt']!='consent' or params['client_id']=='dynamic_agent_client'):
        raise ValueError('explicit plan consent requires an existing registration')
    return value


@dataclass(frozen=True)
class ConnectionRequest:
    request_id: int
    action: str
    registration: str | None = None
    max_runtime_seconds: int = 120
    user_confirmed: bool = False

    def __post_init__(self):
        if type(self.request_id) is not int or self.request_id<1 or self.action not in ACTIONS: raise ValueError('invalid connection request')
        _ref(self.registration,optional=True)
        if self.action=='first_sign_in' and self.registration is not None:raise ValueError('first sign-in cannot select an existing account')
        if self.action in ('enable_plan','select','sign_out','refresh','models','clear_pause') and self.registration is None: raise ValueError('registration required')
        if type(self.max_runtime_seconds) is not int or not 1<=self.max_runtime_seconds<=600: raise ValueError('bounded runtime required')
        if type(self.user_confirmed) is not bool or (self.action!='list' and not self.user_confirmed): raise ValueError('explicit user action required')

    def payload(self): return asdict(self)


@dataclass(frozen=True)
class ConnectionEvent:
    request_id: int
    kind: str
    state: str = 'unknown'
    registrations: tuple = ()
    active_registration: str | None = None
    authorization_url: str | None = field(default=None,repr=False)
    error_code: str = ''
    revocation_confirmed: bool | None = None
    models: tuple = ()
    model_labels: tuple = ()
    account_labels: tuple = ()

    def __post_init__(self):
        if type(self.request_id) is not int or self.request_id<1 or self.kind not in ('progress','authorization','result','error'): raise ValueError('invalid connection event')
        if self.state not in STATES: raise ValueError('invalid connection state')
        _ref(self.active_registration,optional=True)
        if not isinstance(self.registrations,tuple) or len(self.registrations)>64: raise ValueError('invalid registrations')
        seen=set()
        for row in self.registrations:
            if not isinstance(row,tuple) or len(row)!=2: raise ValueError('invalid registration summary')
            _ref(row[0])
            if row[0] in seen or row[1] not in STATES: raise ValueError('invalid registration summary')
            seen.add(row[0])
        if self.active_registration is not None and self.kind=='result' and self.active_registration not in seen: raise ValueError('active registration missing from verified summary')
        if self.kind=='result' and self.state in ('plan_ready','identity_only','refresh_required','reauthorization_required') and self.active_registration is None:raise ValueError('connected status requires an active verified registration')
        if self.authorization_url is not None:
            if self.kind!='authorization': raise ValueError('authorization URL only in transient event')
            official_authorization_url(self.authorization_url)
        if not isinstance(self.error_code,str) or not re.fullmatch(r'[a-z_]{0,80}',self.error_code): raise ValueError('invalid sanitized error code')
        if self.revocation_confirmed is not None and type(self.revocation_confirmed) is not bool: raise ValueError('invalid revocation status')
        if not isinstance(self.models,tuple) or len(self.models)>1024 or any(not isinstance(x,str) or not re.fullmatch(MODEL, x) for x in self.models): raise ValueError('invalid model summary')
        if len(set(self.models))!=len(self.models): raise ValueError('duplicate model summary')
        if not isinstance(self.model_labels,tuple) or len(self.model_labels)>1024: raise ValueError('invalid model labels')
        for row in self.model_labels:
            if (not isinstance(row,tuple) or len(row)!=2 or row[0] not in self.models
                or not isinstance(row[1],str) or not 1<=len(row[1])<=256
                or any(ord(c)<32 for c in row[1])): raise ValueError('invalid model labels')
        if self.model_labels and tuple(row[0] for row in self.model_labels)!=self.models:
            raise ValueError('model label/account mismatch')
        if not isinstance(self.account_labels,tuple) or len(self.account_labels)>64:raise ValueError('invalid account labels')
        states=dict(self.registrations);label_refs=set()
        for row in self.account_labels:
            if (not isinstance(row,tuple) or len(row)!=2 or row[0] not in states or row[0] in label_refs
                or states[row[0]]=='registration_retry_required' or not isinstance(row[1],str)
                or not re.fullmatch(r'已驗證帳戶 ••••[a-f0-9]{8}（電子郵件未提供）',row[1])):
                raise ValueError('invalid verified account label')
            label_refs.add(row[0])


@dataclass(frozen=True)
class SubscriptionOptions:
    registration: str
    model: str
    max_calls: int
    timeout_seconds: int
    network_opt_in: bool = False
    included_usage_policy_confirmed: bool = False
    mode: str = 'chatgpt_plan'
    paid_api_fallback: bool = False

    def __post_init__(self):
        _ref(self.registration)
        if not isinstance(self.model,str) or not re.fullmatch(MODEL, self.model): raise ValueError('invalid model')
        if type(self.max_calls) is not int or not 1<=self.max_calls<=100: raise ValueError('explicit call budget required')
        if type(self.timeout_seconds) is not int or not 1<=self.timeout_seconds<=120: raise ValueError('invalid runtime')
        if self.mode!='chatgpt_plan' or self.paid_api_fallback is not False or self.network_opt_in is not True or self.included_usage_policy_confirmed is not True: raise ValueError('no paid fallback or implicit consent')


class ConnectionController(QObject):
    """Host must wire requests to bounded jobs and acknowledge ACTUAL joins.

    quiesce_requested(request): stop/join every auth/inference worker first.
    request_ready(request): now safe to submit the allowlisted job.
    cancel_requested(id): stop/join that job, then call worker_joined(id).
    browser_requested(url): host opens only this transient, validated URL, never logs it.
    apply_event accepts typed worker messages only; late/stale IDs cannot change state.
    """
    quiesce_requested=Signal(object)
    request_ready=Signal(object)
    cancel_requested=Signal(int)
    browser_requested=Signal(str)
    changed=Signal()
    request_finished=Signal(object,bool)

    def __init__(self,parent=None):
        super().__init__(parent);self.host_available=False;self.busy=False;self.stopping=False
        self.state='unknown';self.message='尚未核對本機連線；沒有自動登入或網路請求。'
        self.registrations=();self.account_labels=();self.active_registration=None;self.models=();self.model_labels=();self._counter=0
        self._request=None;self._awaiting_join=False;self._authorization_url=None;self._terminal_received=False;self._terminal_ok=False
        self.usage_known=False;self.reserved_count=None;self.unknown_count=None;self.account_paused=False;self.account_pending=False;self.account_state='blocked';self.account_status_known=False

    def set_host_available(self,available):
        if type(available) is not bool:raise ValueError('host availability must be explicit')
        self.host_available=available;self.changed.emit()

    def request(self,action,registration=None,*,confirmed=False):
        if not self.host_available or self.busy:raise ValueError('主程式尚未接入，或已有作業。')
        if action=='models' and (registration!=self.active_registration or self.state!='plan_ready' or not self.account_status_known or self.account_paused or self.account_pending):raise ValueError('先核對連線與持久請求紀錄，才能連線取得模型。')
        if action=='clear_pause' and (registration!=self.active_registration or not self.account_status_known or self.account_pending or self.unknown_count or self.account_state not in RECOVERABLE_PAUSES):raise ValueError('未知請求或未核對紀錄不能解除暫停。')
        if action in ('select','sign_out','refresh','models','clear_pause','enable_plan') and dict(self.registrations).get(registration)=='registration_retry_required':
            raise ValueError('unverified registration permits reauthorization only')
        if action=='enable_plan' and (registration!=self.active_registration or self.state!='identity_only'):
            raise ValueError('select an identity-only account before enabling plan use')
        self._counter+=1
        request=ConnectionRequest(self._counter,action,registration,600 if action in ('begin','first_sign_in','enable_plan') else 120,confirmed)
        self.busy=True;self.stopping=False;self._request=request;self._authorization_url=None;self._terminal_received=False;self._terminal_ok=False
        self._awaiting_join=action!='list';self.message='先等待主程式停止並確認所有背景請求已結束。' if self._awaiting_join else '正在讀取本機已保存的連線狀態。'
        self.changed.emit()
        (self.quiesce_requested if self._awaiting_join else self.request_ready).emit(request)
        return request

    def acknowledge_quiescence(self,request_id,*,joined):
        if not self._request or request_id!=self._request.request_id or not self._awaiting_join:return False
        if joined is not True:
            self.message='背景程序尚未確認結束；不會切換帳戶、登出或啟動新授權。';self.changed.emit();return False
        if self.stopping:return False
        self._awaiting_join=False;self.message='背景作業進行中；授權仍由您在官方網站完成。'
        self.changed.emit();self.request_ready.emit(self._request);return True

    def apply_event(self,event):
        if not isinstance(event,ConnectionEvent):raise ValueError('typed sanitized event required')
        if not self._request or event.request_id!=self._request.request_id or self._awaiting_join or self.stopping:return False
        if event.kind=='authorization':
            self._authorization_url=event.authorization_url;self.state='authorizing';self.message='官方目的地：https://auth.openai.com。請按「在官方網站繼續」，自行核對並授權。'
        elif event.kind=='progress':self.state=event.state;self.message=STATE_LABELS[event.state]
        else:
            action=self._request.action;self.state=event.state
            self._terminal_received=True;self._terminal_ok=event.kind=='result'
            self._authorization_url=None
            if event.kind=='error':self.message=ERROR_LABELS.get(event.error_code,'作業未完成。請核對官方連線或本機紀錄；不會自動重試。')
            else:
                if action=='models' and event.active_registration!=self._request.registration: raise ValueError('model/account mismatch')
                if self.active_registration!=event.active_registration:
                    self.usage_known=False;self.account_status_known=False
                self.registrations=event.registrations;self.account_labels=event.account_labels;self.active_registration=event.active_registration
                if action in ('begin','first_sign_in','enable_plan','select','sign_out','refresh'):self.models=();self.model_labels=()
                if action=='models':
                    self.models=event.models;self.model_labels=event.model_labels
                    self.usage_known=False;self.reserved_count=None;self.unknown_count=None
                self.message=STATE_LABELS[event.state]
                if action=='sign_out':self.message=('本機已登出；官方撤銷已確認。' if event.revocation_confirmed is True else '本機已登出；官方撤銷未獲確認，不能保證遠端授權已撤銷。')
            # Terminal message is not process-exit evidence. Keep controls locked until joined.
            self.stopping=True;self.message+=' 等待主程式確認背景程序已結束。'
        self.changed.emit();return True

    def open_authorization(self):
        if not self.busy or self.stopping or not self._authorization_url:raise ValueError('沒有可開啟的本次官方授權。')
        value=official_authorization_url(self._authorization_url)
        self._authorization_url=None;self.changed.emit();self.browser_requested.emit(value)

    def cancel(self):
        if not self.busy:return
        self.stopping=True;self._authorization_url=None;self._terminal_received=False;self._terminal_ok=False
        self.message='正在停止並等待背景程序結束；這不代表遠端請求已取消或額度已退還。'
        self.changed.emit();self.cancel_requested.emit(self._request.request_id)

    def worker_joined(self,request_id,*,joined,terminal_received=True):
        if not self._request or request_id!=self._request.request_id or joined is not True:return False
        finished=self._request
        succeeded=terminal_received is True and self._terminal_received and self._terminal_ok
        if terminal_received is not True or not self._terminal_received:
            self.state='unknown';self.message='背景程序已結束，結果須重新核對。遠端完成與額度不明；不自動重送或退還次數。'
            self.usage_known=False;self.unknown_count=None;self.account_status_known=False
        self.message=self.message.removesuffix(' 等待主程式確認背景程序已結束。')
        self.busy=False;self.stopping=False;self._awaiting_join=False;self._authorization_url=None;self._request=None
        self.changed.emit();self.request_finished.emit(finished,succeeded);return True

    def set_account_status(self,registration,status):
        """Verified local account barrier only; never invents campaign call counts."""
        _ref(registration)
        if registration!=self.active_registration:raise ValueError('account status/account mismatch')
        allowed=RECOVERABLE_PAUSES|{'ready','reserved_unknown','blocked'}
        if not isinstance(status,dict) or set(status)!={'state','pending'} or status['state'] not in allowed or type(status['pending']) is not bool:raise ValueError('verified account status required')
        self.account_paused=status['state']!='ready';self.account_pending=status['pending'];self.account_state=status['state'];self.account_status_known=True
        self.changed.emit()

    def invalidate_campaign_usage(self):
        self.usage_known=False;self.reserved_count=None;self.unknown_count=None;self.changed.emit()

    def set_usage(self,registration,receipts,*,account_status):
        _ref(registration)
        if registration!=self.active_registration:raise ValueError('receipt/account mismatch')
        allowed={'ready','reserved_unknown','eligibility_blocked','quota_paused','transient_blocked','invalid_request','configuration_blocked','credential_diagnosis','grant_blocked','blocked'}
        if not isinstance(account_status,dict) or set(account_status)!={'state','pending'} or account_status['state'] not in allowed or type(account_status['pending']) is not bool:raise ValueError('verified account status required')
        if not isinstance(receipts,(list,tuple)) or len(receipts)>10000:raise ValueError('bounded verified receipts required')
        sequences=[];unknown=0
        for row in receipts:
            if not isinstance(row,dict) or type(row.get('sequence')) is not int or row['sequence']<1 or not isinstance(row.get('status'),str):raise ValueError('invalid receipt summary')
            sequences.append(row['sequence']);unknown+=row['status'] not in RECOVERABLE_PAUSES|{'completed'}
        if len(set(sequences))!=len(sequences):raise ValueError('duplicate receipts')
        self.usage_known=True;self.reserved_count=len(sequences);self.unknown_count=unknown;self.account_paused=account_status['state']!='ready';self.account_pending=account_status['pending'];self.account_state=account_status['state'];self.account_status_known=True
        self.changed.emit()


class ChatGPTConnectionPanel(QWidget):
    """Traditional Chinese standalone settings panel; no credentials in widgets."""
    def __init__(self,controller=None,parent=None):
        super().__init__(parent);self.controller=controller or ConnectionController(self)
        self._rendered_active=None
        self._included_usage_registration=None
        self._primary_flow=None
        self.setObjectName('chatgpt_subscription_panel');layout=QVBoxLayout(self)
        title=QLabel('ChatGPT 訂閱連線（官方授權）');layout.addWidget(title)
        self.disclosure=QLabel('此模式只使用您明確授權的 ChatGPT 方案內用量；額度不足就停止，不切換付費 API，也不要求啟用 credits。\n開始研究前，請在官方用量設定確認：已關閉「允許應用程式使用 credits」，或此應用程式的用量上限低於 100%。自動購買 credits 是另一項設定。\n本程式無法讀取或強制執行官方 credits 設定；勾選僅記錄您本次的確認，不保證零費用。登入成功不代表實際推論已驗證，也不開啟實盤交易。')
        self.disclosure.setWordWrap(True);self.disclosure.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.disclosure)
        self.consent=QCheckBox('我已核對官方帳戶，並同意本次連線動作。');layout.addWidget(self.consent)
        self.included_usage_only=QCheckBox('我已在官方用量設定確認此連線不會使用 credits\n（已停用，或此應用程式上限低於 100%）；僅同意本次研究使用方案內用量。')
        self.included_usage_only.setObjectName('chatgpt_included_usage_only');layout.addWidget(self.included_usage_only)
        self.included_usage_only.toggled.connect(self._confirm_included_usage)
        self.manage_usage=QPushButton('管理 ChatGPT 用量（官方設定）');layout.addWidget(self.manage_usage)
        self.manage_usage.clicked.connect(self._open_usage_settings)
        self.active_account=QLabel('目前尚未登入 ChatGPT');self.active_account.setTextFormat(Qt.TextFormat.PlainText);self.active_account.setWordWrap(True);layout.addWidget(self.active_account)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.status)
        self.primary_sign_in=QPushButton('使用 ChatGPT 帳戶登入（Continue with ChatGPT）')
        self.primary_sign_in.setObjectName('chatgpt_primary_sign_in');layout.addWidget(self.primary_sign_in)
        self.primary_sign_in.clicked.connect(lambda:self._safe(self._start_primary_sign_in))
        self.account=QComboBox();self.account.setAccessibleName('本機已保存連線與待驗證註冊的遮罩識別');layout.addWidget(self.account)
        self.advanced_toggle=QPushButton('進階連線管理');self.advanced_toggle.setCheckable(True);layout.addWidget(self.advanced_toggle)
        self.advanced=QWidget();advanced_layout=QVBoxLayout(self.advanced);layout.addWidget(self.advanced);self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        self.advanced_toggle.toggled.connect(self._render)
        self.buttons={}
        for action,label in [('list','讀取本機連線（不連網）'),('initialize','首次設定／明確復原本機識別'),('begin','Continue with ChatGPT（新增連線）'),('reauthorize','重新授權選定連線（保留原紀錄）'),('enable_plan','明確啟用此連線的 ChatGPT 方案用量'),('select','切換至選定連線'),('refresh','明確更新選定連線'),('models','取得此連線可用模型'),('sign_out','停止背景請求後登出'),('clear_pause','核對額度後申請解除已知暫停')]:
            button=QPushButton(label);button.setObjectName('chatgpt_'+action)
            (layout if action in ('select','models','sign_out','enable_plan') else advanced_layout).addWidget(button);self.buttons[action]=button
            button.clicked.connect(lambda checked=False,a=action:self._act(a))
        self.open_button=QPushButton('Continue with ChatGPT（您自行授權）');self.open_button.setObjectName('chatgpt_open_official');advanced_layout.addWidget(self.open_button)
        self.open_button.clicked.connect(lambda:self._safe(self.controller.open_authorization))
        self.cancel_button=QPushButton('取消並等待背景程序結束');layout.addWidget(self.cancel_button);self.cancel_button.clicked.connect(self._cancel_primary)
        form=QFormLayout();self.model_form=form;layout.addLayout(form)
        self.model=QComboBox();form.addRow('官方回應中的可用模型',self.model)
        self.max_calls=QSpinBox();self.max_calls.setRange(0,100);form.addRow('本次固定研究最多請求（0 = 停用）',self.max_calls)
        self.timeout=QSpinBox();self.timeout.setRange(1,120);self.timeout.setValue(30);form.addRow('每次最長秒數（不保證遠端取消）',self.timeout)
        self.usage=QLabel();self.usage.setWordWrap(True);layout.addWidget(self.usage)
        self.controller.changed.connect(self._render)
        self.controller.request_finished.connect(self._primary_finished)
        self.account.currentIndexChanged.connect(self._reset_included_usage)
        self.model.currentIndexChanged.connect(self._reset_included_usage)
        self.model.currentIndexChanged.connect(self.controller.invalidate_campaign_usage)
        self.max_calls.valueChanged.connect(self._reset_included_usage)
        self.max_calls.valueChanged.connect(self.controller.invalidate_campaign_usage)
        self.timeout.valueChanged.connect(self._reset_included_usage)
        self.timeout.valueChanged.connect(self.controller.invalidate_campaign_usage)
        for index,widget in enumerate((self.primary_sign_in,self.active_account,self.status,self.account),1):
            layout.removeWidget(widget);layout.insertWidget(index,widget)
        layout.addStretch(1)
        self._render()

    def _start_primary_sign_in(self):
        c=self.controller
        if not c.host_available or c.busy:raise ValueError('connection is busy')
        # This click authorizes the local read and opening the official page,
        # never granting scopes or starting model requests for the user.
        self._reset_included_usage()
        self._primary_flow={'phase':'list','request_id':c._counter+1,
                            'selected':self.account.currentData(),'browser_queued':False}
        try:c.request('list')
        except Exception:self._primary_flow=None;raise

    def _primary_finished(self,request,succeeded):
        flow=self._primary_flow
        if flow is None or request.request_id!=flow['request_id']:return
        if not succeeded or flow['phase']!='list':
            self._primary_flow=None;return
        QTimer.singleShot(0,lambda:self._safe(lambda:self._continue_primary(request.request_id)))

    def _continue_primary(self,request_id):
        c=self.controller;flow=self._primary_flow
        if flow is None or flow['request_id']!=request_id or c.busy or flow['phase']!='list':return
        action='begin';registration=flow['selected']
        if c.state=='host_initialization_required':
            answer=QMessageBox.question(self,'首次使用 ChatGPT 登入',
                '這台安裝尚未找到 ChatGPT 登入資料。\n如果這是第一次設定，可建立本機安全識別並前往官方登入。\n如果曾經登入，可能是資料遺失；請取消並先檢查原資料，不要當作首次設定。\n這只會開啟官方登入頁面，授權仍由您決定。是否首次設定？',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
            if self._primary_flow is not flow:return
            if answer!=QMessageBox.StandardButton.Yes:self._primary_flow=None;return
            action='first_sign_in';registration=None
        else:
            refs={ref for ref,_ in c.registrations}
            if registration not in refs:registration=c.active_registration
            if registration is None and len(refs)==1:registration=next(iter(refs))
            if registration is None and len(refs)>1:
                self._primary_flow=None;self.status.setText('請先選擇要登入的 ChatGPT 連線，再按登入。');return
        flow.update(phase='authorization',request_id=c._counter+1,browser_queued=False)
        try:c.request(action,registration,confirmed=True)
        except Exception:self._primary_flow=None;raise

    def _open_primary_authorization(self,request_id):
        c=self.controller;flow=self._primary_flow
        if (flow is None or flow['request_id']!=request_id or not c.busy or c.stopping
            or c._request is None or c._request.request_id!=request_id or c._authorization_url is None):return
        self._safe(c.open_authorization)

    @property
    def primary_sign_in_pending(self):
        """Host schedulers must include the post-join queued authorization gap."""
        return self._primary_flow is not None

    def abandon_primary_sign_in(self):
        # The desktop host calls this before shutdown, cancel, or freeze so a
        # queued post-join step cannot start another authentication worker.
        self._primary_flow=None

    def _cancel_primary(self):
        self.abandon_primary_sign_in();self.controller.cancel()

    def hideEvent(self,event):
        self.abandon_primary_sign_in();super().hideEvent(event)

    def _reset_included_usage(self,*_):
        self._included_usage_registration=None
        self.included_usage_only.setChecked(False)

    def _confirm_included_usage(self,checked):
        c=self.controller
        if checked and c.state=='plan_ready' and c.active_registration and not c.busy and self.account.currentData()==c.active_registration:
            self._included_usage_registration=c.active_registration
        else:
            self._reset_included_usage()

    def _open_usage_settings(self):
        # Only this fixed official destination opens, and only on a user click.
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if not QDesktopServices.openUrl(QUrl(USAGE_SETTINGS_URL)):
            self.status.setText('無法開啟官方用量設定；請先完成核對，尚未授權任何研究請求。')

    def _safe(self,call):
        try:return call()
        except ValueError:self.status.setText('操作未送出。請先核對本次同意、連線與背景作業狀態。')

    def _act(self,action):
        self._primary_flow=None
        def run():
            if action!='list' and not self.consent.isChecked():raise ValueError('consent required')
            registration=self.account.currentData() if action in ('reauthorize','enable_plan','select','sign_out','refresh','models','clear_pause') else None
            if action=='models' and registration!=self.controller.active_registration:raise ValueError('select account first')
            if action=='clear_pause' and (not self.controller.account_status_known or self.controller.unknown_count or self.controller.account_pending):raise ValueError('unknown reservations cannot clear')
            result=self.controller.request('begin' if action=='reauthorize' else action,registration,confirmed=self.consent.isChecked())
            self.consent.setChecked(False);return result
        return self._safe(run)

    def _render(self):
        c=self.controller;self.status.setText(c.message)
        if c.busy or c.state!='plan_ready' or self._rendered_active!=c.active_registration:
            self._reset_included_usage()
        selected=self.account.currentData();self.account.blockSignals(True);self.account.clear()
        labels=dict(c.account_labels)
        for reference,state in c.registrations:
            label=labels.get(reference,'待驗證註冊' if state=='registration_retry_required' else '已保存連線（帳戶識別尚未載入）')
            self.account.addItem(label+' · 連線 ••••'+reference[-8:]+' · '+STATE_LABELS[state],reference)
        self.active_account.setText(('目前登入：'+labels.get(c.active_registration,'已保存帳戶（識別資訊尚未載入）')) if c.active_registration is not None else '目前尚未登入 ChatGPT')
        selection=c.active_registration if c.active_registration!=self._rendered_active else selected or c.active_registration
        self._rendered_active=c.active_registration
        index=self.account.findData(selection)
        if index>=0:self.account.setCurrentIndex(index)
        self.account.blockSignals(False)
        chosen=self.model.currentData();self.model.blockSignals(True);self.model.clear()
        labels=dict(c.model_labels)
        for slug in c.models:self.model.addItem(labels.get(slug,slug),slug)
        if chosen in c.models:self.model.setCurrentIndex(self.model.findData(chosen))
        self.model.blockSignals(False)
        ready=c.host_available and not c.busy
        self.primary_sign_in.setEnabled(ready)
        self.buttons['enable_plan'].setVisible(c.state=='identity_only')
        self.buttons['select'].setVisible(len(c.registrations)>1)
        self.buttons['models'].setVisible(c.state=='plan_ready')
        self.buttons['sign_out'].setVisible(c.active_registration is not None)
        self.cancel_button.setVisible(c.busy)
        self.consent.setVisible(c.active_registration is not None or self.advanced_toggle.isChecked())
        self.included_usage_only.setVisible(c.state=='plan_ready')
        for row in range(3):self.model_form.setRowVisible(row,c.state=='plan_ready')
        flow=self._primary_flow
        if (flow is not None and flow['phase']=='authorization' and not flow['browser_queued']
            and c._request is not None and c._request.request_id==flow['request_id']
            and c._authorization_url is not None and c.busy and not c.stopping):
            flow['browser_queued']=True
            QTimer.singleShot(0,lambda rid=flow['request_id']:self._open_primary_authorization(rid))
        for action,button in self.buttons.items():button.setEnabled(ready and (action in ('list','initialize','begin') or self.account.count()>0))
        self.buttons['enable_plan'].setEnabled(ready and c.state=='identity_only' and c.active_registration is not None)
        self.included_usage_only.setEnabled(ready and c.state=='plan_ready' and c.active_registration is not None)
        self.buttons['models'].setEnabled(ready and c.state=='plan_ready' and c.account_status_known and not c.account_paused and not c.account_pending)
        self.buttons['clear_pause'].setEnabled(ready and self.account.count()>0 and c.account_state in RECOVERABLE_PAUSES and c.account_status_known and not c.unknown_count and not c.account_pending)
        self.open_button.setEnabled(c.busy and not c.stopping and c._authorization_url is not None)
        self.cancel_button.setEnabled(c.busy and not c.stopping)
        self.account.setEnabled(ready);self.model.setEnabled(ready)
        self.usage.setText('本機請求紀錄尚未核對；不能視為已用 0 次。' if not c.usage_known else f'此研究本機已保留請求：{c.reserved_count} 次；未完成或待核對：{c.unknown_count} 次。\n未知結果不會退還或重設；重開程式、換模型／工作區不會解除帳戶暫停。')
        if c.account_status_known:
            barrier = '存在執行中或完成未知請求；禁止重送與退還。' if c.account_pending else ('帳戶已暫停，請核對官方狀態。' if c.account_paused else '本機帳戶未暫停；不代表訂閱可用或費用已受限制。')
            self.usage.setText(self.usage.text()+'\n'+barrier)

    def build_plan_options(self):
        c=self.controller
        if c.busy or c.state!='plan_ready' or not c.active_registration or not c.account_status_known or c.account_paused or c.account_pending or not c.usage_known or c.unknown_count:raise ValueError('subscription is not ready')
        if not self.consent.isChecked() or self.model.currentData() not in c.models:raise ValueError('explicit consent and discovered model required')
        if (not self.included_usage_only.isChecked() or self._included_usage_registration!=c.active_registration
            or self.account.currentData()!=c.active_registration):raise ValueError('included usage only confirmation required for this account')
        result=SubscriptionOptions(c.active_registration,self.model.currentData(),self.max_calls.value(),self.timeout.value(),
                                   network_opt_in=True,included_usage_policy_confirmed=True)
        self.consent.setChecked(False);self._reset_included_usage();return result

    def preferences(self):return {'version':1,'max_calls':self.max_calls.value(),'timeout_seconds':self.timeout.value()}

    def restore_preferences(self,value):
        if not isinstance(value,dict) or set(value)!={'version','max_calls','timeout_seconds'} or value['version']!=1:raise ValueError('invalid connection preferences')
        for key,minimum,maximum in [('max_calls',0,100),('timeout_seconds',1,120)]:
            if type(value[key]) is not int or not minimum<=value[key]<=maximum:raise ValueError('invalid bounded preference')
        self.max_calls.setValue(value['max_calls']);self.timeout.setValue(value['timeout_seconds']);self.consent.setChecked(False);self._reset_included_usage()

    def closeEvent(self,event):
        self.abandon_primary_sign_in()
        if self.controller.busy:self.controller.cancel();event.ignore()
        else:event.accept()


def run_connection_request(request,*,bootstrap,emit,cancelled,session_factory=None,clock=time.monotonic):
    """Worker-only adapter. Parent MUST enforce process deadline/terminate/join.

    No unbounded work on the GUI thread. The parent fixes bootstrap, never accepts
    it from user/model JSON, and forwards only ConnectionEvent through private IPC.
    The official URL is transient IPC, never a log/result/history field.
    """
    if not isinstance(request,ConnectionRequest):raise ValueError('typed connection request required')
    session=None;deadline=clock()+request.max_runtime_seconds
    def snapshot(state=None,**extra):
        summary=session.status_summary()
        rows=tuple((row['registration'],row['state']) for row in summary['registrations'])
        return ConnectionEvent(request.request_id,'result',state or summary['state'],rows,summary['active_registration'],
                               account_labels=tuple((row['registration'],row['account_label']) for row in summary['registrations'] if 'account_label' in row),**extra)
    try:
        if session_factory is None:
            from desktop_chatgpt_auth import AuthSession,DPAPIVault
            session_factory=lambda:AuthSession(DPAPIVault(str(bootstrap)))
        session=session_factory()
        if cancelled():session.cancel();return ConnectionEvent(request.request_id,'result','cancelled')
        if request.action=='initialize':session.initialize_host();return snapshot()
        if request.action=='list':return snapshot()
        if request.action in ('begin','first_sign_in','enable_plan'):
            if request.action=='first_sign_in':
                session.initialize_host(first_use_only=True)
            url=(session.begin(request.registration,enable_plan=True) if request.action=='enable_plan'
                 else session.begin(request.registration))
            emit(ConnectionEvent(request.request_id,'authorization','authorizing',authorization_url=url))
            while session.state in ('authorizing','validating'):
                if cancelled():session.cancel();return snapshot()
                if clock()>=deadline:session.cancel();return ConnectionEvent(request.request_id,'error','timeout',error_code='authorization_timeout')
                session.poll(timeout=.1)
            return snapshot(state='registration_retry_required' if session.state=='registration_retry_required' else None)
        if request.action=='select':session.select(request.registration);return snapshot()
        if request.action=='refresh':session.refresh(request.registration);return snapshot()
        if request.action=='sign_out':return snapshot(revocation_confirmed=session.sign_out(request.registration))
        if request.action in ('models','clear_pause'):
            from desktop_chatgpt_auth import OAuthCredentialReference
            from desktop_chatgpt_provider import discover_models,clear_account_pause,read_account_status
            from pathlib import Path
            reference=OAuthCredentialReference(str(bootstrap),request.registration)
            if request.action=='models':
                status=read_account_status(reference,Path(bootstrap)/'control-v1')
                if status!={'state':'ready','pending':False}:raise ValueError('account_paused')
                models=discover_models(reference,network_opt_in=request.user_confirmed,timeout_seconds=min(request.max_runtime_seconds,120),cancelled=cancelled)
                return snapshot(models=tuple(row['slug'] for row in models),
                                model_labels=tuple((row['slug'],row['display_name']) for row in models))
            clear_account_pause(reference,Path(bootstrap)/'control-v1',user_confirmed=request.user_confirmed)
            return snapshot()
    except Exception as exc:
        code=str(exc)
        # Only known safe constants cross IPC; never exception repr, responses or tokens.
        code=code if code in ERROR_LABELS else 'operation_failed'
        return ConnectionEvent(request.request_id,'error','unknown',error_code=code)
    finally:
        if request.action in ('begin','first_sign_in','enable_plan') and session is not None and session.state in ('authorizing','validating'):
            try:session.cancel()
            except Exception:pass

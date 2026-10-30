"""Provider responsibility; original guards and ordering preserved."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
from datetime import timezone
from pathlib import Path
from quantlab.assistant.adapters.chatgpt.account_paths import _controls_for
from quantlab.assistant.adapters.chatgpt.account_paths import _reject_links
from quantlab.assistant.adapters.chatgpt.account_store import _installation_barrier
from quantlab.assistant.adapters.chatgpt.account_store import _open_account_controls
from quantlab.assistant.adapters.chatgpt.account_store import _persist_account_pause
from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference
from quantlab.assistant.adapters.chatgpt.campaign_receipts import _checked_campaign_rows
from quantlab.assistant.adapters.chatgpt.campaign_receipts import _rows_to_receipts
from quantlab.assistant.adapters.chatgpt.finished_reconciliation import _create_finished_resolution_audit
from quantlab.assistant.adapters.chatgpt.finished_reconciliation import _finished_request_snapshot
from quantlab.assistant.adapters.chatgpt.provenance import implementation_provenance
from quantlab.assistant.adapters.chatgpt.resolution_audit import _receipt_digest
from quantlab.assistant.adapters.chatgpt.resolution_audit import _resolution_controls
from quantlab.assistant.adapters.chatgpt.response_stream import SSEParser
from quantlab.assistant.adapters.chatgpt.response_stream import _CompletedItems
from quantlab.assistant.adapters.chatgpt.response_stream import _completed_payload
from quantlab.assistant.adapters.chatgpt.transport import PlanHTTPTransport
from quantlab.assistant.adapters.chatgpt.transport import _check
from quantlab.assistant.adapters.chatgpt.unknown_reconciliation import _create_resolution_audit
from quantlab.assistant.adapters.chatgpt.unknown_reconciliation import _unknown_request_snapshot
from quantlab.assistant.domain.plan_protocol import ACKNOWLEDGEMENT_VERSION
from quantlab.assistant.domain.plan_protocol import ERROR_STATES
from quantlab.assistant.domain.plan_protocol import FINISHED_ACKNOWLEDGEMENT_VERSION
from quantlab.assistant.domain.plan_protocol import MODELS_MAX_RESPONSE_BYTES
from quantlab.assistant.domain.plan_protocol import PlanError
from quantlab.assistant.domain.plan_protocol import RESPONSES_URL
from quantlab.assistant.domain.plan_protocol import _CONFIRMED_CONSUMED
from quantlab.assistant.domain.plan_protocol import _FINISHED_UNKNOWN_STATUSES
from quantlab.assistant.domain.plan_protocol import _RESOLUTION_MIN_AGE_SECONDS
from quantlab.assistant.domain.plan_protocol import _fail
from quantlab.assistant.domain.plan_protocol import _integer
from quantlab.assistant.domain.plan_protocol import _remote_error
from quantlab.assistant.domain.plan_protocol import parse_models
from quantlab.core import ValidationError
from quantlab.core import canonical_json
from quantlab.core import content_hash
from quantlab.research import PARAMETER_CONTRACTS
from quantlab.research import PROMPT
from quantlab.research import validate_dsl
from quantlab.windows_paths import sqlite_uri
import copy
import json
import re
import sqlite3
import time


def parse_completed(response, family):
    candidate,usage=_completed_payload(response)
    validate_dsl(candidate)
    if candidate['family']!=family: _fail('candidate_family_mismatch')
    # AI selects signal parameters only. The general engine also accepts manual
    # risk sizing/stops, which are never an authorized model output here.
    if set(candidate['parameters'])!=set(PARAMETER_CONTRACTS[family]):
        _fail('invalid_output')
    return candidate,usage


class ChatGPTPlanProvider:
    mode='chatgpt_plan'
    endpoint=RESPONSES_URL
    real_model_status='not_verified'

    def __init__(self, *, model, credential_reference, budget_path, campaign_id,
                 network_opt_in=False, included_usage_policy_confirmed=False,
                 max_calls=0, timeout_seconds=30, stall_seconds=10,
                 max_request_bytes=65536, max_response_bytes=262144,
                 hard_token_limit=None):
        if type(credential_reference) is not OAuthCredentialReference:_fail('oauth_reference_required')
        if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',model):_fail('invalid_model')
        if not isinstance(campaign_id,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',campaign_id):_fail('invalid_campaign_id')
        if hard_token_limit is not None:_fail('hard_token_limit_unsupported')
        self.model=model;self.credential_reference=credential_reference
        controls=_controls_for(credential_reference)
        self.path=Path(budget_path)
        if (not self.path.is_absolute() or '..' in self.path.parts
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',self.path.name)):
            _fail('installation_controls_path_required')
        _reject_links(self.path)
        if self.path.parent!=controls or self.path.name=='chatgpt-plan-account-controls.sqlite':
            _fail('installation_controls_path_required')
        self.campaign_id=campaign_id
        self.network_opt_in=network_opt_in is True
        self.included_usage_policy_confirmed=included_usage_policy_confirmed is True
        self.max_calls=_integer(max_calls,0,100)
        self.timeout=_integer(timeout_seconds,1,120);self.stall=_integer(stall_seconds,1,120)
        self.max_request_bytes=_integer(max_request_bytes,1024,65536)
        self.max_response_bytes=_integer(max_response_bytes,1024,1048576)
        self.receipts=[]

    def provider_descriptor(self):
        return {**implementation_provenance(),'version':1,'mode':self.mode,'model':self.model,'endpoint':self.endpoint,
            'registration':self.credential_reference.registration,'campaign_id':self.campaign_id,
            'max_calls':self.max_calls,'timeout_seconds':self.timeout,'stall_seconds':self.stall,
            'max_request_bytes':self.max_request_bytes,'max_response_bytes':self.max_response_bytes,
            'max_event_bytes':65536,'max_candidate_bytes':16384,'max_events':2048,
            'billing_route':'chatgpt_plan','paid_api_fallback':False,
            'token_upper_bound_enforced':False,'spend_upper_bound_enforced':False,
            'account_credit_policy':'unverified_user_setting',
            'included_usage_policy_ack_required':True}

    @property
    def account_path(self):
        path=_controls_for(self.credential_reference)/'chatgpt-plan-account-controls.sqlite'
        _reject_links(path)
        return path

    def _db(self):
        _reject_links(self.path)
        marker=Path(self.credential_reference.bootstrap)/'chatgpt-plan-controls-v1.marker'
        if not marker.exists() and self.path.exists():_fail('account_control_marker_missing')
        account=_open_account_controls(self.credential_reference,initialize=True)
        try:
            expected=account.execute('SELECT binding,calls FROM plan_ledgers WHERE filename=?',(self.path.name,)).fetchone()
            if expected and not self.path.is_file():_fail('campaign_controls_missing')
            mode='rw' if expected or self.path.exists() else 'rwc'
        finally:account.close()
        db=None
        try:
            db=sqlite3.connect(sqlite_uri(self.path)+'?mode='+mode,uri=True,timeout=30)
            db.execute('ATTACH DATABASE ? AS account_controls',(sqlite_uri(self.account_path)+'?mode=rw',))
            for schema in ('main','account_controls'):
                if db.execute('PRAGMA '+schema+'.journal_mode').fetchone()[0]!='delete':
                    _fail('unsupported_control_journal_mode')
                db.execute('PRAGMA '+schema+'.synchronous=FULL')
            return db
        except Exception as exc:
            if db is not None:db.close()
            if isinstance(exc,PlanError):raise
            raise PlanError('campaign_controls_unavailable') from None

    def _account_state(self):
        db=_open_account_controls(self.credential_reference)
        if db is None:return None
        with closing(db):
            status=_installation_barrier(db,_controls_for(self.credential_reference))
            return None if status['state']=='ready' else status['state']

    def _pause_account(self,status):
        _persist_account_pause(self.credential_reference,status)

    def _reserve(self,request_hash,request_bytes):
        binding=content_hash(self.provider_descriptor())
        with closing(self._db()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            expected=db.execute('SELECT binding,calls FROM account_controls.plan_ledgers WHERE filename=?',(self.path.name,)).fetchone()
            if expected:
                row,_=_checked_campaign_rows(db,'main',expected)
            else:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                    _fail('unexpected_campaign_controls')
                db.execute('CREATE TABLE plan_budget (id INTEGER PRIMARY KEY CHECK(id=1),binding TEXT,calls INTEGER,blocked TEXT)')
                db.execute('CREATE TABLE plan_calls (sequence INTEGER PRIMARY KEY, request_hash TEXT,request_bytes INTEGER,status TEXT,response_hash TEXT,usage TEXT,received_bytes INTEGER,elapsed_seconds REAL)')
                row=(binding,0,None);db.execute('INSERT INTO plan_budget VALUES (1,?,?,?)',row)
            if _installation_barrier(db,self.path.parent,'account_controls')['state']!='ready':
                _fail('account_paused')
            if row[0]!=binding:_fail('immutable_budget_binding')
            if row[2]:_fail('campaign_paused')
            if db.execute("SELECT 1 FROM plan_calls WHERE status='reserved_unknown'").fetchone():_fail('previous_completion_unknown')
            if row[1]>=self.max_calls:_fail('call_budget_exhausted')
            sequence=row[1]+1
            db.execute('INSERT INTO account_controls.plan_accounts (registration,state,owner) VALUES (?,?,?) ON CONFLICT(registration) DO UPDATE SET state=excluded.state,owner=excluded.owner',
                       (self.credential_reference.registration,'reserved_unknown',binding))
            db.execute('INSERT INTO account_controls.plan_ledgers VALUES (?,?,?) ON CONFLICT(filename) DO UPDATE SET calls=excluded.calls',
                       (self.path.name,binding,sequence))
            db.execute('UPDATE plan_budget SET calls=? WHERE id=1',(sequence,))
            db.execute('INSERT INTO plan_calls VALUES (?,?,?,?,?,?,?,?)',
                (sequence,request_hash,request_bytes,'reserved_unknown',None,json.dumps('unknown'),None,None))
        return sequence

    def _finish(self,sequence,status,response_hash=None,usage='unknown',received_bytes=None,elapsed_seconds=None):
        # R2/D7: never persist an outcome outside the research receipt allowlist.
        if status!='completed' and status not in _FINISHED_UNKNOWN_STATUSES and status not in set(ERROR_STATES.values()):
            status='failed_or_interrupted'
        with closing(self._db()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            binding=content_hash(self.provider_descriptor())
            expected=db.execute('SELECT binding,calls FROM account_controls.plan_ledgers WHERE filename=?',(self.path.name,)).fetchone()
            budget,rows=_checked_campaign_rows(db,'main',expected)
            if budget[0]!=binding or not 1<=sequence<=len(rows) or rows[sequence-1][3]!='reserved_unknown':
                _fail('invalid_receipt_transition')
            if status=='completed':
                db.execute("UPDATE account_controls.plan_accounts SET state=CASE WHEN state='reserved_unknown' THEN NULL ELSE state END,owner=NULL WHERE registration=? AND owner=?",
                           (self.credential_reference.registration,binding))
            else:
                db.execute('UPDATE account_controls.plan_accounts SET state=?,owner=NULL WHERE registration=? AND owner=?',
                           (status,self.credential_reference.registration,binding))
            db.execute('UPDATE plan_calls SET status=?,response_hash=?,usage=?,received_bytes=?,elapsed_seconds=? WHERE sequence=?',
                       (status,response_hash,canonical_json(usage),received_bytes,elapsed_seconds,sequence))
            if status!='completed':db.execute('UPDATE plan_budget SET blocked=? WHERE id=1',(status,))

    def read_receipts(self):
        return self.read_receipt_snapshot()['receipts']

    def read_receipt_snapshot(self):
        """One read-only transaction binds global expectation, budget and rows."""
        descriptor=self.provider_descriptor();binding=content_hash(descriptor)
        db=_open_account_controls(self.credential_reference)
        rows=[]
        if db is None:
            if self.path.exists():_fail('account_controls_missing')
        else:
            with closing(db):
                try:
                    expected=db.execute('SELECT binding,calls FROM plan_ledgers WHERE filename=?',(self.path.name,)).fetchone()
                    if expected:
                        if expected[0]!=binding:_fail('immutable_budget_binding')
                        _reject_links(self.path)
                        if not self.path.is_file():_fail('campaign_controls_missing')
                        db.execute('ATTACH DATABASE ? AS campaign',(sqlite_uri(self.path)+'?mode=ro',))
                        _,rows=_checked_campaign_rows(db,'campaign',expected)
                    elif self.path.exists():
                        # A failed pre-reservation operation may leave an empty
                        # never-used file; no tables/rows are accepted as first use.
                        _reject_links(self.path)
                        db.execute('ATTACH DATABASE ? AS campaign',(sqlite_uri(self.path)+'?mode=ro',))
                        if db.execute("SELECT 1 FROM campaign.sqlite_master WHERE type='table'").fetchone():
                            _fail('unexpected_campaign_controls')
                except sqlite3.Error:
                    raise PlanError('campaign_controls_unavailable') from None
        receipts=_rows_to_receipts(rows)
        return {'version':1,'provider_descriptor_hash':binding,'receipts':receipts}

    def _preflight(self):
        if self._account_state():_fail('account_paused')
        receipts=self.read_receipts()
        if any(row['status']!='completed' for row in receipts):_fail('campaign_paused')
        if len(receipts)>=self.max_calls:_fail('call_budget_exhausted')

    def generate(self,context, *, cancelled=None):
        return self._execute(context,cancelled=cancelled)

    def _analysis_purpose(self):
        if self.max_calls!=1:_fail('invalid_limit')
        if (not isinstance(self.campaign_id,str)
            or not re.fullmatch(r'analysis-[a-f0-9]{64}',self.campaign_id)
            or self.path.name!='chatgpt-'+self.campaign_id+'.sqlite3'):
            _fail('analysis_purpose_required')

    def analysis_preflight(self):
        self._analysis_purpose()
        self._preflight()

    def analyze(self,context, *, cancelled=None):
        self._analysis_purpose()
        from quantlab.research_analysis import validate_analysis_context
        context=validate_analysis_context(context)
        return self._execute(context,cancelled=cancelled,analysis=True)

    def _execute(self,context, *, cancelled=None,analysis=False):
        if not self.network_opt_in:_fail('network_disabled')
        if not self.included_usage_policy_confirmed:_fail('included_usage_policy_confirmation_required')
        if not self.max_calls:_fail('call_budget_exhausted')
        self._preflight()
        started=time.monotonic()
        limits={'deadline':started+self.timeout,'stall_seconds':self.stall,
                'max_request_bytes':self.max_request_bytes,'max_response_bytes':self.max_response_bytes}
        instructions=PROMPT
        if analysis:
            from quantlab.research_analysis import ANALYSIS_PROMPT
            instructions=ANALYSIS_PROMPT
        request={'model':self.model,'instructions':instructions,'input':[{'role':'user','content':canonical_json(context)}],
                 'store':False,'stream':True}
        raw=canonical_json(request).encode('utf-8')
        if len(raw)>self.max_request_bytes:_fail('request_byte_limit')
        _check(limits['deadline'],cancelled)
        # No cached catalog can silently carry account selection across calls.
        transport=PlanHTTPTransport()
        try:
            # The catalog check uses the catalog-sized cap, not the inference cap.
            catalog_limits={**limits,'max_response_bytes':MODELS_MAX_RESPONSE_BYTES}
            catalog=parse_models(transport.models(self.credential_reference,catalog_limits,cancelled))
        except PlanError as exc:
            if exc.code in set(ERROR_STATES.values()):self._pause_account(exc.code)
            raise
        if self.model not in {item['slug'] for item in catalog}:_fail('selected_model_unavailable')
        _check(limits['deadline'],cancelled)
        sequence=self._reserve(content_hash(request),len(raw))
        parser=SSEParser(max_bytes=self.max_response_bytes);response_id=None;completed=None
        completed_items=_CompletedItems()
        stream=None
        try:
            stream=transport.stream(self.credential_reference,request,limits,cancelled)
            for chunk in stream:
                _check(limits['deadline'],cancelled)
                batch=parser.feed(chunk)
                terminals=[e for e in batch if e.get('type') in ('response.completed','response.failed','response.incomplete','error')]
                if len(terminals)>1:_fail('ambiguous_terminal')
                for event in batch:
                    kind=event.get('type')
                    if not isinstance(kind,str):_fail('invalid_event')
                    response=event.get('response',{})
                    # Every supplied identity is evidence. Do not let a valid
                    # top-level ID mask a contradictory or invalid nested ID.
                    identities=[]
                    if 'response_id' in event:identities.append(event['response_id'])
                    if isinstance(response,dict) and 'id' in response:identities.append(response['id'])
                    for rid in identities:
                        if not isinstance(rid,str) or not 1<=len(rid)<=256:_fail('invalid_response_id')
                        if response_id is not None and response_id!=rid:_fail('response_id_mismatch')
                        response_id=rid
                    completed_items.observe(event)
                    if kind in ('response.failed','error'):_remote_error(response if kind=='response.failed' else event)
                    if kind=='response.incomplete':_fail('response_incomplete')
                    if 'refusal' in kind or 'function_call' in kind or 'tool_call' in kind:_fail('refusal_or_tool_event')
                    if kind=='response.completed':
                        response=completed_items.complete(response,response_id)
                        if analysis:
                            from quantlab.research_analysis import validate_analysis_response
                            value,usage=_completed_payload(response)
                            try:value=validate_analysis_response(value,context)
                            except ValidationError:_fail('invalid_output')
                            completed=(value,usage)
                        else:
                            completed=parse_completed(response,context.get('family'))
                if completed is not None:break
            if completed is None:
                parser.finish();_fail('eof_without_completion')
            _check(limits['deadline'],cancelled)
            candidate,usage=completed
            self._finish(sequence,'completed',content_hash(candidate),usage,parser.total,time.monotonic()-started)
            self.receipts=self.read_receipts()
            return candidate
        except BaseException as exc:
            self._finish(sequence,exc.code if isinstance(exc,PlanError) else 'failed_or_interrupted',
                         received_bytes=parser.total,elapsed_seconds=time.monotonic()-started)
            if isinstance(exc,PlanError): raise
            if isinstance(exc,(KeyboardInterrupt,SystemExit)): raise
            raise PlanError('failed_or_interrupted') from None
        finally:
            if stream is not None:stream.close()

    def improve(self,context):
        context=copy.deepcopy(context);context['task']='improve_previous_candidate'
        context['improvement_instruction']='Propose a distinct candidate in the same family using training and validation feedback only. Keep risk controls unchanged.'
        return self.generate(context)


def analysis_provider(plan, credential_reference, *, network_opt_in=False,
                      included_usage_policy_confirmed=False):
    """Reconstruct exactly one separately budgeted analysis, never a campaign."""
    from quantlab.research_analysis import validate_analysis_plan
    validate_analysis_plan(plan)
    if (type(credential_reference) is not OAuthCredentialReference
        or credential_reference.registration != plan['binding']['registration']):
        _fail('oauth_reference_required')
    return ChatGPTPlanProvider(model=plan['binding']['model'],credential_reference=credential_reference,
        budget_path=_controls_for(credential_reference)/('chatgpt-analysis-'+plan['analysis_id']+'.sqlite3'),
        campaign_id='analysis-'+plan['analysis_id'],max_calls=1,
        timeout_seconds=plan['binding']['timeout_seconds'],network_opt_in=network_opt_in,
        included_usage_policy_confirmed=included_usage_policy_confirmed)


def discover_models(credential_reference, *, network_opt_in=False, timeout_seconds=30, cancelled=None):
    if network_opt_in is not True:_fail('network_disabled')
    if type(credential_reference) is not OAuthCredentialReference:_fail('oauth_reference_required')
    timeout=_integer(timeout_seconds,1,120)
    if read_account_status(credential_reference,_controls_for(credential_reference))['state']!='ready':
        _fail('account_paused')
    limits={'deadline':time.monotonic()+timeout,'stall_seconds':min(10,timeout),
            # Official catalog rows carry long per-model fields; only slug/name/visibility are kept.
            'max_response_bytes':MODELS_MAX_RESPONSE_BYTES,'max_request_bytes':65536}
    try:
        return parse_models(PlanHTTPTransport().models(credential_reference,limits,cancelled))
    except PlanError as exc:
        if exc.code in set(ERROR_STATES.values()):_persist_account_pause(credential_reference,exc.code)
        raise


def inspect_unknown_request(credential_reference, controls_path):
    """Host-only offline diagnosis; expose no identities, filenames or hashes."""
    controls = _resolution_controls(credential_reference, controls_path)
    result = {'kind': 'none', 'sequence': None, 'calls': None, 'max_age_ok': False}
    db = _open_account_controls(credential_reference)
    if db is None:
        return result
    try:
        with closing(db):
            kind, target = _unknown_request_snapshot(db, controls, credential_reference.registration)
            result['kind'] = kind
            if target is not None:
                path, _, calls, receipt = target
                result.update(sequence=receipt[0], calls=calls, max_age_ok=time.time() - path.stat().st_mtime >= _RESOLUTION_MIN_AGE_SECONDS)
        return result
    except (sqlite3.Error, OSError):
        raise PlanError('account_controls_unavailable') from None


def resolve_unknown_request(credential_reference, controls_path, *, user_confirmed=False, acknowledgement_version=None):
    """Manually consume one old K1 receipt atomically, retaining a known pause."""
    if user_confirmed is not True or type(acknowledgement_version) is not int or acknowledgement_version != ACKNOWLEDGEMENT_VERSION:
        _fail('resolution_confirmation_required')
    controls = _resolution_controls(credential_reference, controls_path)
    db = _open_account_controls(credential_reference, readonly=False)
    if db is None:
        _fail('no_resolvable_unknown_request')
    try:
        with closing(db), db:
            if db.execute('PRAGMA main.journal_mode').fetchone() != ('delete',):
                _fail('unsupported_control_journal_mode')
            db.execute('PRAGMA main.synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            kind, target = _unknown_request_snapshot(db, controls, credential_reference.registration)
            if target is None:
                _fail('unknown_request_owned_by_another_registration' if kind == 'k1_other_registration' else 'no_resolvable_unknown_request')
            path, binding, calls, receipt = target
            _reject_links(path)
            if time.time() - path.stat().st_mtime < _RESOLUTION_MIN_AGE_SECONDS:
                _fail('unknown_request_too_recent')
            db.execute('ATTACH DATABASE ? AS resolution_ledger', (sqlite_uri(path) + '?mode=rw',))
            if db.execute('PRAGMA resolution_ledger.journal_mode').fetchone() != ('delete',):
                _fail('unsupported_control_journal_mode')
            if db.execute('PRAGMA resolution_ledger.synchronous').fetchone() != (2,):
                _fail('unsupported_control_synchronous_mode')
            budget, rows = _checked_campaign_rows(db, 'resolution_ledger', (binding, calls))
            if budget[2] is not None or rows[-1] != receipt or receipt[3] != 'reserved_unknown':
                _fail('campaign_controls_inconsistent')
            provenance_hash = content_hash(implementation_provenance())
            _create_resolution_audit(db)
            db.execute(
                'INSERT INTO plan_resolutions (filename,sequence,request_hash,registration,previous_status,new_status,'
                'acknowledgement_version,official_usage_checked,no_refund_acknowledged,no_other_tool_acknowledged,confirmed_at_utc,implementation_hash) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (path.name, calls, receipt[1], credential_reference.registration, 'reserved_unknown', _CONFIRMED_CONSUMED,
                 ACKNOWLEDGEMENT_VERSION, 1, 1, 1, datetime.now(timezone.utc).isoformat(), provenance_hash),
            )
            db.execute('UPDATE resolution_ledger.plan_calls SET status=? WHERE sequence=?', (_CONFIRMED_CONSUMED, calls))
            db.execute('UPDATE resolution_ledger.plan_budget SET blocked=? WHERE id=1', (_CONFIRMED_CONSUMED,))
            db.execute('UPDATE plan_accounts SET state=?,owner=NULL WHERE registration=?', (_CONFIRMED_CONSUMED, credential_reference.registration))
    except (sqlite3.Error, OSError):
        raise PlanError('account_controls_unavailable') from None


def inspect_finished_unknown_request(credential_reference, controls_path):
    """Host-only offline K2 diagnosis; expose no identities, filenames or hashes."""
    controls = _resolution_controls(credential_reference, controls_path)
    result = {'kind': 'none', 'sequence': None, 'calls': None, 'max_age_ok': False, 'outcome': None}
    db = _open_account_controls(credential_reference)
    if db is None:
        return result
    try:
        with closing(db):
            kind, target = _finished_request_snapshot(db, controls, credential_reference.registration)
            result['kind'] = kind
            if target is not None:
                path, _, calls, _, receipt = target
                result.update(
                    sequence=receipt[0],
                    calls=calls,
                    max_age_ok=time.time() - path.stat().st_mtime >= _RESOLUTION_MIN_AGE_SECONDS,
                    outcome=receipt[3],
                )
        return result
    except (sqlite3.Error, OSError):
        raise PlanError('account_controls_unavailable') from None


def resolve_finished_unknown_request(
    credential_reference,
    controls_path,
    *,
    user_confirmed=False,
    acknowledgement_version=None,
    expected_sequence=None,
    expected_calls=None,
    expected_outcome=None,
):
    """Manually consume one uniquely mapped K2 receipt atomically, retaining a known pause."""
    if (
        user_confirmed is not True
        or type(acknowledgement_version) is not int
        or acknowledgement_version != FINISHED_ACKNOWLEDGEMENT_VERSION
        or any(type(value) is not int or not 1 <= value <= 100 for value in (expected_sequence, expected_calls))
        or type(expected_outcome) is not str
        or expected_outcome not in _FINISHED_UNKNOWN_STATUSES
    ):
        _fail('resolution_confirmation_required')
    controls = _resolution_controls(credential_reference, controls_path)
    db = _open_account_controls(credential_reference, readonly=False)
    if db is None:
        _fail('no_resolvable_unknown_request')
    try:
        with closing(db), db:
            if db.execute('PRAGMA main.journal_mode').fetchone() != ('delete',):
                _fail('unsupported_control_journal_mode')
            db.execute('PRAGMA main.synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            kind, target = _finished_request_snapshot(db, controls, credential_reference.registration)
            if target is None:
                _fail(
                    {
                        'none': 'no_resolvable_unknown_request',
                        'k2_other_registration': 'unknown_request_owned_by_another_registration',
                    }.get(kind, 'finished_request_unmappable')
                )
            path, binding, calls, budget, receipt = target
            if (receipt[0], calls, receipt[3]) != (expected_sequence, expected_calls, expected_outcome):
                _fail('no_resolvable_unknown_request')
            _reject_links(path)
            if time.time() - path.stat().st_mtime < _RESOLUTION_MIN_AGE_SECONDS:
                _fail('unknown_request_too_recent')
            db.execute('ATTACH DATABASE ? AS resolution_ledger', (sqlite_uri(path) + '?mode=rw',))
            if db.execute('PRAGMA resolution_ledger.journal_mode').fetchone() != ('delete',):
                _fail('unsupported_control_journal_mode')
            if db.execute('PRAGMA resolution_ledger.synchronous').fetchone() != (2,):
                _fail('unsupported_control_synchronous_mode')
            current_budget, rows = _checked_campaign_rows(db, 'resolution_ledger', (binding, calls))
            if current_budget != budget or rows[-1] != receipt:
                _fail('campaign_controls_inconsistent')
            tables = {
                name
                for (name,) in db.execute(
                    "SELECT name FROM main.sqlite_master WHERE type='table' AND name IN ('plan_resolutions','plan_finished_resolutions')"
                ).fetchall()
            }
            for table in sorted(tables):
                if db.execute('SELECT 1 FROM main.' + table + ' WHERE filename=? AND sequence=?', (path.name, calls)).fetchone():
                    _fail('campaign_controls_inconsistent')
            provenance_hash = content_hash(implementation_provenance())
            _create_finished_resolution_audit(db)
            db.execute(
                'INSERT INTO plan_finished_resolutions (filename,sequence,request_hash,receipt_hash,registration,previous_status,'
                'new_status,acknowledgement_version,official_usage_checked,no_refund_acknowledged,other_usage_acknowledged,'
                'confirmed_at_utc,implementation_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (
                    path.name, calls, receipt[1], _receipt_digest(receipt), credential_reference.registration, receipt[3],
                    _CONFIRMED_CONSUMED, FINISHED_ACKNOWLEDGEMENT_VERSION, 1, 1, 1,
                    datetime.now(timezone.utc).isoformat(), provenance_hash,
                ),
            )
            updated = db.execute(
                'UPDATE resolution_ledger.plan_calls SET status=? WHERE sequence=? AND status=?', (_CONFIRMED_CONSUMED, calls, receipt[3])
            )
            if updated.rowcount != 1:
                _fail('campaign_controls_inconsistent')
            updated = db.execute(
                'UPDATE plan_accounts SET state=? WHERE registration=? AND state=? AND owner IS NULL',
                (_CONFIRMED_CONSUMED, credential_reference.registration, receipt[3]),
            )
            if updated.rowcount != 1:
                _fail('campaign_controls_inconsistent')
    except (sqlite3.Error, OSError):
        raise PlanError('account_controls_unavailable') from None


def clear_account_pause(credential_reference, controls_path, *, user_confirmed=False):
    """Host-only explicit recovery after the user verifies quota/account status.

    Never called by generation, refresh, sign-in or elapsed-time logic. Does not
    refund campaign reservations, reset call caps, or clear unknown crash states.
    """
    if user_confirmed is not True:_fail('explicit_recovery_confirmation_required')
    if type(credential_reference) is not OAuthCredentialReference:_fail('oauth_reference_required')
    controls=_controls_for(credential_reference)
    if Path(controls_path)!=controls:_fail('installation_controls_path_required')
    path=controls/'chatgpt-plan-account-controls.sqlite'
    _reject_links(path)
    db=_open_account_controls(credential_reference,readonly=False)
    if db is None:return
    with closing(db),db:
        db.execute('BEGIN IMMEDIATE')
        barrier=_installation_barrier(db,controls)
        if barrier['pending']:_fail('active_or_unknown_request')
        row=db.execute('SELECT state,owner FROM plan_accounts WHERE registration=?',
                       (credential_reference.registration,)).fetchone()
        if row and row[0]:
            if row[1] is not None:_fail('active_or_unknown_request')
            if row[0] not in set(ERROR_STATES.values())|{_CONFIRMED_CONSUMED}:_fail('unknown_outcome_requires_manual_resolution')
            db.execute('UPDATE plan_accounts SET state=NULL WHERE registration=?',(credential_reference.registration,))
        elif barrier['state']!='ready':
            _fail('pause_owned_by_another_registration')


def read_account_status(credential_reference, controls_path):
    """Read-only installation-wide pause status; no other identities disclosed."""
    if type(credential_reference) is not OAuthCredentialReference:_fail('oauth_reference_required')
    controls=_controls_for(credential_reference)
    if Path(controls_path)!=controls:_fail('installation_controls_path_required')
    path=controls/'chatgpt-plan-account-controls.sqlite'
    _reject_links(path)
    db=_open_account_controls(credential_reference)
    if db is None:return {'state':'ready','pending':False}
    with closing(db):
        return _installation_barrier(db,controls)

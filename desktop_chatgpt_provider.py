"""Official ChatGPT plan Responses adapter, default off; no API-key fallback.

Only completed, locally validated JSON is a candidate. Call/runtime/byte budgets
are local limits, never token or monetary upper bounds. Account credit settings
cannot be verified or enforced here. Live OAuth/inference needs separate consent.
Protocol baseline: developers.openai.com/siwc/token-sharing-open-source/
models-and-inference and preview-limitations (reviewed 2026-10-10).
"""
from __future__ import annotations

import codecs
from contextlib import closing, contextmanager
import copy
import http.client
import hashlib
import importlib.metadata
import platform
import sys
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import threading
import time

from desktop_chatgpt_auth import OAuthCredentialReference
from quantlab.core import ValidationError, canonical_json, content_hash
from quantlab.research import PROMPT, validate_dsl, _validated_receipt_snapshot

MODELS_URL = 'https://api.openai.com/v1/models'
RESPONSES_URL = 'https://api.openai.com/v1/responses'
ERROR_STATES = {
    'subscription_sharing_user_not_eligible': 'eligibility_blocked',
    'subscription_sharing_usage_limit_exceeded': 'quota_paused',
    'subscription_sharing_usage_unavailable': 'transient_blocked',
    'subscription_sharing_user_unavailable': 'transient_blocked',
    'subscription_sharing_unsupported_capability': 'invalid_request',
    'subscription_sharing_route_not_supported': 'configuration_blocked',
    'subscription_sharing_invalid_user': 'credential_diagnosis',
    'chatpass_v2_scope_not_authorized': 'grant_blocked',
    'chatpass_v2_invalid_authorization_context': 'grant_blocked',
}

class PlanError(ValidationError):
    """Fixed allowlisted local codes only, never remote text or tokens."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise PlanError(code)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: _fail('duplicate_json_key')
        result[key] = value
    return result


def _json(text):
    try:
        value = json.loads(text, object_pairs_hook=_unique,
                          parse_constant=lambda _: _fail('nonfinite_json'))
        def walk(item, depth=0):
            if depth > 24: _fail('json_depth')
            if isinstance(item, float) and not math.isfinite(item): _fail('nonfinite_json')
            if isinstance(item, dict):
                for v in item.values(): walk(v, depth+1)
            elif isinstance(item, list):
                for v in item: walk(v, depth+1)
        walk(value)
        if type(value) is not dict: _fail('json_object_required')
        return value
    except (ValueError, UnicodeError, RecursionError):
        _fail('invalid_json')


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum: _fail('invalid_limit')
    return value


def _check(deadline, cancelled):
    if cancelled is not None and cancelled(): _fail('cancelled')
    if time.monotonic() >= deadline: _fail('deadline_exceeded')


def _remote_error(value):
    error = value.get('error', value.get('detail', {})) if isinstance(value, dict) else {}
    if isinstance(error, dict): code = error.get('code', error.get('type'))
    else: code = error
    _fail(ERROR_STATES.get(code, 'remote_error') if isinstance(code,str) else 'remote_error')


def parse_models(value):
    """Return only visible slugs/display names, preserving official ordering."""
    if not isinstance(value, dict) or not isinstance(value.get('models'), list): _fail('invalid_catalog')
    if not 1 <= len(value['models']) <= 1024: _fail('invalid_catalog')
    result, seen = [], set()
    for item in value['models']:
        if (not isinstance(item, dict) or not isinstance(item.get('slug'),str)
            or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',item['slug'])
            or not isinstance(item.get('display_name'),str) or not 1 <= len(item['display_name']) <= 256
            or any(ord(c)<32 for c in item['display_name'])
            or not isinstance(item.get('visibility'),str) or not item['visibility']): _fail('invalid_catalog')
        if item['slug'] in seen: _fail('duplicate_model')
        seen.add(item['slug'])
        if item['visibility']=='list': result.append({'slug':item['slug'],'display_name':item['display_name']})
    if not result: _fail('empty_catalog')
    return result


def _controls_for(reference):
    """Installation-local only; reject link/reparse redirection, never relocate."""
    root=Path(reference.bootstrap)
    if not root.is_absolute() or '..' in root.parts:_fail('installation_controls_path_required')
    controls=root/'control-v1'
    _reject_links(controls)
    return controls


def _reject_links(path):
    for part in (path,*path.parents):
        try:
            info=part.lstat()
        except FileNotFoundError:
            continue
        if part.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
            _fail('linked_controls_path_rejected')


class SSEParser:
    """Incremental UTF-8/SSE framing; no partial text is treated as completion."""
    def __init__(self, max_bytes=262144, max_event_bytes=65536, max_events=2048):
        self.max_bytes, self.max_event_bytes, self.max_events = max_bytes, max_event_bytes, max_events
        self.total = self.events = self.event_bytes = 0
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.pending = ''; self.data = []; self.event_type = None; self.after_cr = False

    def _line(self, line):
        if not line:
            if not self.data:
                self.event_bytes=0; self.event_type=None
                return None
            self.events += 1
            if self.events > self.max_events: _fail('event_count')
            text='\n'.join(self.data); self.data=[]; self.event_bytes=0
            if text=='[DONE]': _fail('done_without_completion')
            value=_json(text)
            if self.event_type and value.get('type') != self.event_type: _fail('ambiguous_event_type')
            self.event_type=None
            return value
        if line.startswith(':'): return None
        name,sep,value=line.partition(':')
        if value.startswith(' '): value=value[1:]
        if name=='data': self.data.append(value)
        elif name=='event':
            if self.event_type is not None: _fail('duplicate_event_type')
            self.event_type=value
        return None

    def feed(self, raw):
        if not isinstance(raw,bytes): _fail('invalid_stream_chunk')
        self.total += len(raw)
        if self.total > self.max_bytes: _fail('stream_byte_limit')
        try: text=self.decoder.decode(raw)
        except UnicodeError: _fail('invalid_utf8')
        events=[]
        for char in text:
            if self.after_cr:
                self.after_cr=False
                if char=='\n': continue
            self.event_bytes += len(char.encode('utf-8'))
            if self.event_bytes > self.max_event_bytes: _fail('event_byte_limit')
            if char in '\r\n':
                value=self._line(self.pending);self.pending='';self.after_cr=char=='\r'
                if value is not None:events.append(value)
            else:self.pending += char
        return events

    def finish(self):
        try:self.decoder.decode(b'',final=True)
        except UnicodeError:_fail('invalid_utf8')
        if self.pending or self.data:_fail('truncated_event')


def parse_completed(response, family):
    if not isinstance(response,dict) or response.get('status')!='completed':_fail('invalid_terminal_status')
    if response.get('error') or response.get('incomplete_details'): _fail('ambiguous_terminal')
    output=response.get('output')
    if not isinstance(output,list) or not output: _fail('missing_output')
    texts=[]
    for item in output:
        if not isinstance(item,dict): _fail('invalid_output')
        # Reasoning metadata is not candidate text and can accompany a message.
        if item.get('type')=='reasoning': continue
        if item.get('type')!='message' or item.get('role')!='assistant': _fail('tools_or_unknown_output')
        if item.get('status') not in (None,'completed'): _fail('incomplete_message')
        parts=item.get('content')
        if not isinstance(parts,list) or not parts:_fail('missing_output')
        for part in parts:
            if not isinstance(part,dict) or part.get('type')!='output_text' or not isinstance(part.get('text'),str):
                _fail('refusal_or_unknown_content')
            texts.append(part['text'])
    if len(texts)!=1: _fail('ambiguous_candidate')
    if len(texts[0].encode('utf-8'))>16384:_fail('candidate_byte_limit')
    candidate=_json(texts[0]);validate_dsl(candidate)
    if candidate['family']!=family: _fail('candidate_family_mismatch')
    usage=response.get('usage');observed='unknown'
    if isinstance(usage,dict) and all(type(usage.get(k)) is int and 0 <= usage[k] <= 2**53
                                    for k in ('input_tokens','output_tokens','total_tokens')):
        if usage['input_tokens']+usage['output_tokens']==usage['total_tokens']:
            observed={k:usage[k] for k in ('input_tokens','output_tokens','total_tokens')}
    return candidate,observed


class PlanHTTPTransport:
    """Fixed HTTPS origins, verified TLS, no redirects/proxies/cookies/retries."""
    @contextmanager
    def _response(self, reference, method, url, body, limits, cancelled):
        if (method,url) not in (('GET',MODELS_URL),('POST',RESPONSES_URL)): _fail('invalid_endpoint')
        deadline=limits['deadline'];_check(deadline,cancelled)
        token=reference()  # scope and expiry checked, no implicit refresh
        if not isinstance(token,str) or not 1<=len(token)<=16384 or any(ord(c)<33 or ord(c)>126 for c in token):
            _fail('invalid_credential')
        headers={'Authorization':'Bearer '+token,'Accept':'text/event-stream' if method=='POST' else 'application/json',
                 'Accept-Encoding':'identity','Content-Type':'application/json'}
        connection=http.client.HTTPSConnection('api.openai.com',443,context=ssl.create_default_context(),
            timeout=min(limits['stall_seconds'],max(.001,deadline-time.monotonic())))
        active=[None];stop=threading.Event()
        def watchdog():
            while not stop.wait(.05):
                if time.monotonic()>=deadline or (cancelled is not None and cancelled()):
                    sock=active[0] or connection.sock
                    if sock is not None:
                        try:sock.shutdown(socket.SHUT_RDWR)
                        except OSError:pass
                        sock.close()
                    return
        watcher=threading.Thread(target=watchdog,daemon=True);watcher.start()
        try:
            _check(deadline,cancelled)
            connection.request(method,'/v1/models' if method=='GET' else '/v1/responses',body=body,headers=headers)
            active[0]=connection.sock
            _check(deadline,cancelled)
            response=connection.getresponse()
            if response.getheader('Content-Encoding','identity').lower()!='identity':_fail('compressed_response')
            length=response.getheader('Content-Length')
            if length is not None and (not length.isdecimal() or int(length)>limits['max_response_bytes']):_fail('stream_byte_limit')
            def chunks():
                total=0
                while True:
                    _check(deadline,cancelled)
                    if active[0] is not None:
                        active[0].settimeout(min(limits['stall_seconds'],max(.001,deadline-time.monotonic())))
                    raw=response.read1(min(8192,limits['max_response_bytes']+1-total))
                    _check(deadline,cancelled)
                    if not raw:break
                    total+=len(raw)
                    if total>limits['max_response_bytes']:_fail('stream_byte_limit')
                    yield raw
            if not 200<=response.status<300:
                if 300<=response.status<400:_fail('redirect_rejected')
                raw=b''.join(chunks())
                _remote_error(_json(raw))
            expected='text/event-stream' if method=='POST' else 'application/json'
            if response.getheader('Content-Type','').split(';',1)[0].strip().lower()!=expected:_fail('invalid_content_type')
            yield chunks()
        except (OSError,http.client.HTTPException):
            _check(deadline,cancelled)
            _fail('http_transport_failed')
        finally:
            stop.set();connection.close();watcher.join(timeout=.1)

    def stream(self,reference,request,limits,cancelled=None):
        body=canonical_json(request).encode('utf-8')
        if len(body)>limits['max_request_bytes']:_fail('request_byte_limit')
        with self._response(reference,'POST',RESPONSES_URL,body,limits,cancelled) as chunks:
            yield from chunks

    def models(self,reference,limits,cancelled=None):
        with self._response(reference,'GET',MODELS_URL,None,limits,cancelled) as chunks:
            return _json(b''.join(chunks))


def discover_models(credential_reference, *, network_opt_in=False, timeout_seconds=30, cancelled=None):
    if network_opt_in is not True:_fail('network_disabled')
    if type(credential_reference) is not OAuthCredentialReference:_fail('oauth_reference_required')
    timeout=_integer(timeout_seconds,1,120)
    limits={'deadline':time.monotonic()+timeout,'stall_seconds':min(10,timeout),
            'max_response_bytes':262144,'max_request_bytes':65536}
    return parse_models(PlanHTTPTransport().models(credential_reference,limits,cancelled))


def implementation_provenance():
    """Exact shipped source/build-manifest hashes; invoked only at admission.

    Wheel digests are hash-locked build evidence, not a runtime audit of every
    installed distribution byte. Missing source, metadata or manifest blocks.
    """
    try:
        root=Path(__file__).parent
        sources={}
        for name in ('desktop_chatgpt_auth.py','desktop_chatgpt_provider.py'):
            raw=(root/name).read_bytes()
            if not 1<=len(raw)<=1048576:_fail('invalid_packaged_source')
            sources[name]=hashlib.sha256(raw).hexdigest()
        raw=(root/'desktop_chatgpt_dependency_manifest.json').read_bytes()
        if not 1<=len(raw)<=16384:_fail('invalid_dependency_manifest')
        manifest=_json(raw)
        targets={'windows-cp313-amd64','linux-cp312-x86_64'}
        if (set(manifest)!={'version','targets'} or type(manifest['version']) is not int
            or manifest['version']!=1 or type(manifest['targets']) is not dict or set(manifest['targets'])!=targets):
            _fail('invalid_dependency_manifest')
        expected={'PyJWT':'2.15.1','cryptography':'50.0.2','cffi':'2.1.1','pycparser':'3.11'}
        for entry in manifest['targets'].values():
            if type(entry) is not dict or set(entry)!={'dependencies'} or type(entry['dependencies']) is not list or len(entry['dependencies'])!=4:
                _fail('invalid_dependency_manifest')
            seen=set()
            for item in entry['dependencies']:
                if type(item) is not dict or set(item)!={'distribution','version','wheel_sha256'}:
                    _fail('invalid_dependency_manifest')
                name=item['distribution']
                if type(name) is not str or name not in expected or name in seen or item['version']!=expected[name]:
                    _fail('invalid_dependency_manifest')
                if type(item['wheel_sha256']) is not str or not re.fullmatch('[a-f0-9]{64}',item['wheel_sha256']):
                    _fail('invalid_dependency_manifest')
                seen.add(name)
        if platform.python_implementation()!='CPython':_fail('unsupported_dependency_target')
        machine=platform.machine().lower()
        if sys.platform=='win32' and sys.version_info[:2]==(3,13) and machine in ('amd64','x86_64'):
            target='windows-cp313-amd64'
        elif sys.platform=='linux' and sys.version_info[:2]==(3,12) and machine in ('amd64','x86_64'):
            target='linux-cp312-x86_64'
        else:_fail('unsupported_dependency_target')
        observed={name:importlib.metadata.version(name) for name in expected}
        if observed!=expected:_fail('dependency_version_mismatch')
        return {'source_sha256':sources,'dependency_versions':observed,
                'dependency_manifest_sha256':hashlib.sha256(raw).hexdigest(),
                'dependency_target':target,'dependency_artifact_evidence':'hash_locked_build_manifest'}
    except PlanError:
        raise
    except Exception:
        raise PlanError('implementation_provenance_unavailable') from None

_CONTROL_MARKER = b'markauto-chatgpt-plan-controls-v1\n'


def _open_account_controls(reference, *, initialize=False, readonly=True):
    """Fixed bootstrap existence marker distinguishes first use from lost audit.

    A crash during first initialization intentionally leaves a blocking marker.
    There is no implicit repair/reset, and no directory scan or workspace input.
    """
    controls=_controls_for(reference)
    marker=Path(reference.bootstrap)/'chatgpt-plan-controls-v1.marker'
    account=controls/'chatgpt-plan-account-controls.sqlite'
    _reject_links(marker);_reject_links(account)
    db=None
    try:
        if not marker.exists():
            if account.exists():_fail('account_control_marker_missing')
            if not initialize:return None
            controls.mkdir(parents=True,exist_ok=True)
            # Persist expectation BEFORE any DB creation; partial setup is blocked.
            with marker.open('xb') as output:
                output.write(_CONTROL_MARKER);output.flush();os.fsync(output.fileno())
            if os.name!='nt':
                directory=os.open(marker.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
                try:os.fsync(directory)
                finally:os.close(directory)
            db=sqlite3.connect(account.as_uri()+'?mode=rwc',uri=True,timeout=30)
            db.execute('PRAGMA synchronous=FULL')
            with db:
                db.execute('CREATE TABLE control_identity (id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER)')
                db.execute('INSERT INTO control_identity VALUES (1,1)')
                db.execute('CREATE TABLE plan_accounts (registration TEXT PRIMARY KEY,state TEXT,owner TEXT)')
                db.execute('CREATE TABLE plan_ledgers (filename TEXT PRIMARY KEY,binding TEXT,calls INTEGER)')
            db.close();db=None
        with marker.open('rb') as source:
            if source.read(len(_CONTROL_MARKER)+1)!=_CONTROL_MARKER:_fail('account_control_marker_invalid')
        if not account.is_file():_fail('account_controls_missing')
        db=sqlite3.connect(account.as_uri()+('?mode=ro' if readonly else '?mode=rw'),uri=True,timeout=5)
        if readonly:db.execute('BEGIN')
        if db.execute('SELECT version FROM control_identity WHERE id=1').fetchall()!=[(1,)]:
            _fail('account_controls_invalid')
        db.execute('SELECT registration,state,owner FROM plan_accounts LIMIT 0')
        db.execute('SELECT filename,binding,calls FROM plan_ledgers LIMIT 0')
        return db
    except Exception as exc:
        if db is not None:db.close()
        if isinstance(exc,PlanError):raise
        raise PlanError('account_controls_unavailable') from None


def _checked_campaign_rows(db, schema, expected):
    """Must run in the same transaction as the global expectation read."""
    try:
        budget=db.execute('SELECT binding,calls,blocked FROM '+schema+'.plan_budget WHERE id=1').fetchone()
        rows=db.execute('SELECT sequence,request_hash,request_bytes,status,response_hash,usage,received_bytes,elapsed_seconds FROM '+schema+'.plan_calls ORDER BY sequence').fetchall()
        if (not budget or expected is None or budget[:2]!=expected or type(budget[1]) is not int
            or not 1<=budget[1]<=100 or len(rows)!=budget[1]
            or [row[0] for row in rows]!=list(range(1,budget[1]+1))):
            _fail('campaign_controls_inconsistent')
        _rows_to_receipts(rows)
        return budget,rows
    except sqlite3.Error:
        raise PlanError('campaign_controls_unavailable') from None


def _rows_to_receipts(rows):
    claims={'billing_route':'chatgpt_plan','paid_api_fallback':False,
            'token_upper_bound_enforced':False,'spend_upper_bound_enforced':False,
            'account_credit_policy':'unverified_user_setting'}
    try:
        receipts=[]
        for row in rows:
            if type(row[5]) is not str or len(row[5])>512:_fail('campaign_controls_invalid')
            usage=json.loads(row[5],object_pairs_hook=_unique,parse_constant=lambda _:_fail('campaign_controls_invalid'))
            receipts.append(dict(claims,sequence=row[0],request_hash=row[1],request_bytes=row[2],status=row[3],
                response_hash=row[4],token_usage=usage,received_bytes=row[6],elapsed_seconds=row[7]))
        # Reuse the same strict, allowlisted receipt schema as parent persistence.
        descriptor={'version':1}
        return _validated_receipt_snapshot({'version':1,'provider_descriptor_hash':content_hash(descriptor),
                                           'receipts':receipts},descriptor)
    except Exception:
        raise PlanError('campaign_controls_invalid') from None


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
            db=sqlite3.connect(self.path.as_uri()+'?mode='+mode,uri=True,timeout=30)
            db.execute('ATTACH DATABASE ? AS account_controls',(self.account_path.as_uri()+'?mode=rw',))
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
            row=db.execute('SELECT state FROM plan_accounts WHERE registration=?',
                           (self.credential_reference.registration,)).fetchone()
            return row[0] if row else None

    def _pause_account(self,status):
        db=_open_account_controls(self.credential_reference,initialize=True,readonly=False)
        with closing(db),db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO plan_accounts (registration,state) VALUES (?,?) ON CONFLICT(registration) DO UPDATE SET state=excluded.state',
                       (self.credential_reference.registration,status))

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
            account=db.execute('SELECT state FROM account_controls.plan_accounts WHERE registration=?',
                               (self.credential_reference.registration,)).fetchone()
            if account and account[0]:_fail('account_paused')
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
                        db.execute('ATTACH DATABASE ? AS campaign',(self.path.as_uri()+'?mode=ro',))
                        _,rows=_checked_campaign_rows(db,'campaign',expected)
                    elif self.path.exists():
                        # A failed pre-reservation operation may leave an empty
                        # never-used file; no tables/rows are accepted as first use.
                        _reject_links(self.path)
                        db.execute('ATTACH DATABASE ? AS campaign',(self.path.as_uri()+'?mode=ro',))
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
        if not self.network_opt_in:_fail('network_disabled')
        if not self.included_usage_policy_confirmed:_fail('included_usage_policy_confirmation_required')
        if not self.max_calls:_fail('call_budget_exhausted')
        self._preflight()
        started=time.monotonic()
        limits={'deadline':started+self.timeout,'stall_seconds':self.stall,
                'max_request_bytes':self.max_request_bytes,'max_response_bytes':self.max_response_bytes}
        request={'model':self.model,'instructions':PROMPT,'input':[{'role':'user','content':canonical_json(context)}],
                 'store':False,'stream':True}
        raw=canonical_json(request).encode('utf-8')
        if len(raw)>self.max_request_bytes:_fail('request_byte_limit')
        _check(limits['deadline'],cancelled)
        # No cached catalog can silently carry account selection across calls.
        transport=PlanHTTPTransport()
        try:
            catalog=parse_models(transport.models(self.credential_reference,limits,cancelled))
        except PlanError as exc:
            if exc.code in set(ERROR_STATES.values()):self._pause_account(exc.code)
            raise
        if self.model not in {item['slug'] for item in catalog}:_fail('selected_model_unavailable')
        _check(limits['deadline'],cancelled)
        sequence=self._reserve(content_hash(request),len(raw))
        parser=SSEParser(max_bytes=self.max_response_bytes);response_id=None;completed=None
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
                    rid=event.get('response_id') or (response.get('id') if isinstance(response,dict) else None)
                    if rid is not None:
                        if not isinstance(rid,str) or not 1<=len(rid)<=256:_fail('invalid_response_id')
                        if response_id is not None and response_id!=rid:_fail('response_id_mismatch')
                        response_id=rid
                    if kind in ('response.failed','error'):_remote_error(response if kind=='response.failed' else event)
                    if kind=='response.incomplete':_fail('response_incomplete')
                    if 'refusal' in kind or 'function_call' in kind or 'tool_call' in kind:_fail('refusal_or_tool_event')
                    if kind=='response.completed':
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
        row=db.execute('SELECT state,owner FROM plan_accounts WHERE registration=?',
                       (credential_reference.registration,)).fetchone()
        if row and row[0]:
            if row[1] is not None:_fail('active_or_unknown_request')
            if row[0] not in set(ERROR_STATES.values()):_fail('unknown_outcome_requires_manual_resolution')
            db.execute('UPDATE plan_accounts SET state=NULL WHERE registration=?',(credential_reference.registration,))


def read_account_status(credential_reference, controls_path):
    """Read-only, sanitized account pause status for UI; never repairs/resumes."""
    if type(credential_reference) is not OAuthCredentialReference:_fail('oauth_reference_required')
    controls=_controls_for(credential_reference)
    if Path(controls_path)!=controls:_fail('installation_controls_path_required')
    path=controls/'chatgpt-plan-account-controls.sqlite'
    _reject_links(path)
    db=_open_account_controls(credential_reference)
    if db is None:return {'state':'ready','pending':False}
    try:
        with closing(db):
            row=db.execute('SELECT state,owner FROM plan_accounts WHERE registration=?',
                           (credential_reference.registration,)).fetchone()
    except sqlite3.Error:
        raise PlanError('account_controls_unavailable') from None
    if not row or row[0] is None:return {'state':'ready','pending':False}
    state=row[0] if row[0] in set(ERROR_STATES.values())|{'reserved_unknown'} else 'blocked'
    return {'state':state,'pending':row[1] is not None or row[0]=='reserved_unknown'}

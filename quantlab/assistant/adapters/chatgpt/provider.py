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
from datetime import datetime, timezone
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

from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference, official_tls_context
from quantlab.core import ValidationError, canonical_json, content_hash
from quantlab.windows_paths import sqlite_uri
from quantlab.research import PROMPT, PARAMETER_CONTRACTS, validate_dsl, _validated_receipt_snapshot

MODELS_URL = 'https://api.openai.com/v1/models'
MODELS_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
RESPONSES_URL = 'https://api.openai.com/v1/responses'
ACKNOWLEDGEMENT_VERSION = 1
_CONFIRMED_CONSUMED = 'user_confirmed_consumed'
_RESOLUTION_MIN_AGE_SECONDS = 300
# R2: finished-unknown (K2) outcome codes, frozen as literals; the audit CHECK
# below uses the same list. A drift test pins it to the research allowlist.
_FINISHED_UNKNOWN_STATUSES = frozenset((
    'ambiguous_candidate', 'ambiguous_event_type', 'ambiguous_terminal', 'cancelled', 'candidate_byte_limit',
    'candidate_family_mismatch', 'compressed_response', 'deadline_exceeded', 'done_without_completion',
    'duplicate_event_type', 'duplicate_json_key', 'eof_without_completion', 'event_byte_limit', 'event_count',
    'failed_or_interrupted', 'http_transport_failed', 'incomplete_message', 'invalid_content_type', 'invalid_credential',
    'invalid_event', 'invalid_json', 'invalid_output', 'invalid_response_id', 'invalid_stream_chunk',
    'invalid_terminal_status', 'invalid_utf8', 'json_depth', 'json_object_required', 'missing_output', 'nonfinite_json',
    'redirect_rejected', 'refusal_or_tool_event', 'refusal_or_unknown_content', 'remote_error', 'request_byte_limit',
    'response_id_mismatch', 'response_incomplete', 'stream_byte_limit', 'tools_or_unknown_output', 'truncated_event',
))
FINISHED_ACKNOWLEDGEMENT_VERSION = 1
_FINISHED_ACKNOWLEDGEMENT_VERSIONS = frozenset((1,))
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
    def __init__(self, code, *, http_status=None, remote_code=None):
        self.code = code
        self.http_status = http_status if type(http_status) is int and 100<=http_status<=599 else None
        self.remote_code = remote_code if isinstance(remote_code,str) and remote_code in ERROR_STATES else None
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


def _remote_error(value, *, http_status=None):
    # Admission `detail` is diagnostic prose, never a stable machine code.
    # Retain only safe status and documented codes; no remote prose or URLs.
    error = value.get('error') if isinstance(value, dict) else None
    code = error.get('code') if isinstance(error,dict) else None
    code = code if isinstance(code,str) and code in ERROR_STATES else None
    fallback = {401:'credential_diagnosis',403:'grant_blocked',503:'transient_blocked'}.get(http_status,'remote_error')
    raise PlanError(ERROR_STATES.get(code,fallback),http_status=http_status,remote_code=code)


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


class _CompletedItems:
    """Pinned recovery from completed items; deltas never supply candidate text."""

    def __init__(self):
        self.items = {}
        self.invalid = False

    def observe(self, event):
        if event.get('type') != 'response.output_item.done':
            return
        index, item = event.get('output_index'), event.get('item')
        if type(index) is not int or not 0 <= index < 64 or not isinstance(item, dict) or index in self.items:
            self.invalid = True
        else:
            self.items[index] = copy.deepcopy(item)

    def complete(self, response, response_id):
        if not isinstance(response, dict) or response.get('output') not in (None, []):
            return response
        if response.get('status') != 'completed' or response.get('error') or response.get('incomplete_details'):
            return response
        if not self.items or self.invalid:
            return response
        if response_id is None or response.get('id') != response_id:
            _fail('invalid_response_id')
        if sorted(self.items) != list(range(len(self.items))):
            _fail('ambiguous_output')
        identities = set()
        for item in self.items.values():
            identity = item.get('id')
            if not isinstance(identity, str) or not 1 <= len(identity) <= 256 or identity in identities:
                _fail('ambiguous_output')
            identities.add(identity)
            if item.get('type') != 'reasoning' and item.get('status') != 'completed':
                _fail('incomplete_message')
        return {**response, 'output': [self.items[index] for index in sorted(self.items)]}


def _completed_payload(response):
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
    candidate=_json(texts[0])
    usage=response.get('usage');observed='unknown'
    if isinstance(usage,dict) and all(type(usage.get(k)) is int and 0 <= usage[k] <= 2**53
                                    for k in ('input_tokens','output_tokens','total_tokens')):
        if usage['input_tokens']+usage['output_tokens']==usage['total_tokens']:
            observed={k:usage[k] for k in ('input_tokens','output_tokens','total_tokens')}
    return candidate,observed


def parse_completed(response, family):
    candidate,usage=_completed_payload(response)
    validate_dsl(candidate)
    if candidate['family']!=family: _fail('candidate_family_mismatch')
    # AI selects signal parameters only. The general engine also accepts manual
    # risk sizing/stops, which are never an authorized model output here.
    if set(candidate['parameters'])!=set(PARAMETER_CONTRACTS[family]):
        _fail('invalid_output')
    return candidate,usage


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
        connection=http.client.HTTPSConnection('api.openai.com',443,context=official_tls_context(),
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
                try:value=_json(raw)
                except PlanError:value={}
                _remote_error(value,http_status=response.status)
            expected='text/event-stream' if method=='POST' else 'application/json'
            # Owner-approved (2026-10-23): the official streamed Responses reply can omit the
            # header entirely. Only a POST with no Content-Type header at all is read as a
            # stream; any present but different type is still refused, and the consumer's
            # strict SSE parsing and response.completed requirement remain the gate.
            content_type=response.getheader('Content-Type')  # None only when the header is absent
            if not (method=='POST' and content_type is None) and (
                    (content_type or '').split(';',1)[0].strip().lower()!=expected):_fail('invalid_content_type')
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


def _dependency_manifest():
    """Strict build inputs shared by admission and the CI-only hash installer."""
    root=Path(__file__).parent
    raw=(root/'desktop_chatgpt_dependency_manifest.json').read_bytes()
    if not 1<=len(raw)<=16384:_fail('invalid_dependency_manifest')
    manifest=_json(raw)
    targets={'windows-cp311-amd64','windows-cp312-amd64','windows-cp313-amd64',
             'linux-cp311-x86_64','linux-cp312-x86_64'}
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
    return raw,manifest,expected


def _dependency_target():
    """Only declared 64-bit CPython runtimes; never infer other wheel targets."""
    if (platform.python_implementation()!='CPython' or sys.maxsize<=2**32
        or platform.machine().lower() not in ('amd64','x86_64')):
        _fail('unsupported_dependency_target')
    version=sys.version_info[:2]
    if sys.platform=='win32' and version in ((3,11),(3,12),(3,13)):
        return f'windows-cp{version[0]}{version[1]}-amd64'
    if sys.platform=='linux' and version in ((3,11),(3,12)):
        return f'linux-cp{version[0]}{version[1]}-x86_64'
    _fail('unsupported_dependency_target')


def implementation_provenance():
    """Exact shipped source/build-manifest hashes; invoked only at admission.

    Wheel digests are hash-locked build evidence, not a runtime audit of every
    installed distribution byte. Missing source, metadata or manifest blocks.
    """
    try:
        root=Path(__file__).parent
        sources={}
        for name in ('desktop_chatgpt_auth.py','desktop_chatgpt_provider.py'):
            raw=(root/{'desktop_chatgpt_auth.py':'auth.py','desktop_chatgpt_provider.py':'provider.py'}[name]).read_bytes()
            if not 1<=len(raw)<=1048576:_fail('invalid_packaged_source')
            sources[name]=hashlib.sha256(raw).hexdigest()
        raw,manifest,expected=_dependency_manifest()
        target=_dependency_target()
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
            db=sqlite3.connect(sqlite_uri(account)+'?mode=rwc',uri=True,timeout=30)
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
        db=sqlite3.connect(sqlite_uri(account)+('?mode=ro' if readonly else '?mode=rw'),uri=True,timeout=5)
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


def _persist_account_pause(credential_reference,status):
    if status not in set(ERROR_STATES.values()):_fail('invalid_pause_state')
    db=_open_account_controls(credential_reference,initialize=True,readonly=False)
    with closing(db),db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT state,owner FROM plan_accounts WHERE registration=?',
                            (credential_reference.registration,)).fetchone()
        # A delayed known metadata error cannot downgrade a prior unknown
        # inference outcome into a user-clearable pause. Active owners remain
        # attached so a completed call can still retain a new known pause.
        if existing and existing[0] is not None:
            if existing[0] not in set(ERROR_STATES.values())|{'reserved_unknown'}:
                return
            if existing[0]=='reserved_unknown' and existing[1] is None:
                return
        db.execute('INSERT INTO plan_accounts (registration,state) VALUES (?,?) ON CONFLICT(registration) DO UPDATE SET state=excluded.state',
                   (credential_reference.registration,status))


def _installation_barrier(db, controls, schema='main'):
    """Conservative local barrier across grants; never infer a human identity.

    The row owners and their receipt ledgers remain distinct. Public status does
    not reveal which other registration caused the installation-wide pause.
    """
    if schema not in ('main','account_controls'):_fail('account_controls_invalid')
    try:
        expectations=db.execute('SELECT filename,binding,calls FROM '+schema+'.plan_ledgers LIMIT 1025').fetchall()
        if len(expectations)>1024:_fail('account_controls_invalid')
        unknown_receipt=False
        resolved_registrations=set()
        deadline=time.monotonic()+5
        seen=set()
        for filename,binding,calls in expectations:
            if time.monotonic()>=deadline:_fail('account_controls_unavailable')
            if (type(filename) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',filename)
                or filename in ('.','..','chatgpt-plan-account-controls.sqlite')
                or filename.casefold() in seen or type(binding) is not str
                or not re.fullmatch('[a-f0-9]{64}',binding) or type(calls) is not int or not 1<=calls<=100):
                _fail('account_controls_invalid')
            seen.add(filename.casefold())
            path=controls/filename
            _reject_links(path)
            if not path.is_file():_fail('campaign_controls_missing')
            # The caller retains the global read/write transaction while each
            # indexed ledger is inspected. Every legitimate ledger mutation also
            # needs that global write transaction. No directory scan/identities.
            with closing(sqlite3.connect(sqlite_uri(path)+'?mode=ro',uri=True,timeout=min(1,max(.001,deadline-time.monotonic())))) as ledger:
                ledger.execute('BEGIN')
                budget,receipts=_checked_campaign_rows(ledger,'main',(binding,calls))
                for row in receipts:
                    if row[3]==_CONFIRMED_CONSUMED:
                        registration=_confirmed_registration(db,schema,filename,row,budget)
                        if registration is None:unknown_receipt=True
                        else:resolved_registrations.add(registration)
                    elif row[3]!='completed' and row[3] not in set(ERROR_STATES.values()):
                        unknown_receipt=True
            if time.monotonic()>=deadline:_fail('account_controls_unavailable')
        rows=db.execute('SELECT registration,state,owner FROM '+schema+'.plan_accounts '
                        'WHERE state IS NOT NULL OR owner IS NOT NULL LIMIT 1025').fetchall()
    except sqlite3.Error:
        raise PlanError('account_controls_unavailable') from None
    if unknown_receipt:return {'state':'reserved_unknown','pending':True}
    if not rows:return {'state':'ready','pending':False}
    if len(rows)>1024:return {'state':'blocked','pending':True}
    if any(owner is not None or state=='reserved_unknown' for _,state,owner in rows):
        return {'state':'reserved_unknown','pending':True}
    known=set(ERROR_STATES.values())
    if any(state==_CONFIRMED_CONSUMED and registration not in resolved_registrations for registration,state,_ in rows):
        return {'state':'blocked','pending':True}
    known.add(_CONFIRMED_CONSUMED)
    if any(type(state) is not str or state not in known for _,state,_ in rows):
        return {'state':'blocked','pending':True}
    # A deterministic known state is sufficient for admission; no identities or
    # details about other account registrations are returned to the UI.
    return {'state':sorted(state for _,state,_ in rows)[0],'pending':False}


def _resolution_registration(db, schema, filename, receipt):
    """Only complete, matching local audit evidence makes a receipt final."""
    if schema not in ('main', 'account_controls'):
        _fail('account_controls_invalid')
    if not _resolution_audit_triggers(db, schema):
        return None
    try:
        rows = db.execute(
            'SELECT request_hash,registration,previous_status,new_status,acknowledgement_version,'
            'official_usage_checked,no_refund_acknowledged,no_other_tool_acknowledged,confirmed_at_utc,implementation_hash '
            'FROM ' + schema + '.plan_resolutions WHERE filename=? AND sequence=? LIMIT 2',
            (filename, receipt[0]),
        ).fetchall()
    except sqlite3.Error:
        return None
    if len(rows) != 1:
        return None
    row = rows[0]
    if (
        row[0] != receipt[1]
        or type(row[1]) is not str
        or not re.fullmatch('[a-f0-9]{32}', row[1])
        or row[2:4] != ('reserved_unknown', _CONFIRMED_CONSUMED)
        or type(row[4]) is not int
        or row[4] != ACKNOWLEDGEMENT_VERSION
        or any(type(value) is not int or value != 1 for value in row[5:8])
        or type(row[8]) is not str
        or type(row[9]) is not str
        or not re.fullmatch('[a-f0-9]{64}', row[9])
    ):
        return None
    try:
        recorded = datetime.fromisoformat(row[8])
        if recorded.utcoffset() != timezone.utc.utcoffset(recorded):
            return None
    except ValueError:
        return None
    return row[1]


def _resolution_audit_triggers(db, schema='main'):
    """Require the append-only guards, including for an existing audit table."""
    if schema not in ('main', 'account_controls'):
        _fail('account_controls_invalid')
    expected = {
        'plan_resolutions_no_' + operation.lower():
        'CREATE TRIGGER plan_resolutions_no_' + operation.lower() + ' BEFORE ' + operation
        + " ON plan_resolutions BEGIN SELECT RAISE(ABORT,'append_only'); END"
        for operation in ('UPDATE', 'DELETE')
    }
    normalize = lambda sql: re.sub(r'\s+', '', sql).lower().replace('ifnotexists', '').rstrip(';')
    try:
        rows = db.execute(
            'SELECT name,sql FROM ' + schema + ".sqlite_master WHERE type='trigger' AND tbl_name='plan_resolutions' "
            "AND name IN ('plan_resolutions_no_update','plan_resolutions_no_delete')"
        ).fetchall()
        return len(rows) == 2 and all(type(sql) is str and normalize(sql) == normalize(expected[name]) for name, sql in rows)
    except sqlite3.Error:
        return False


def _resolution_controls(credential_reference, controls_path):
    if type(credential_reference) is not OAuthCredentialReference:
        _fail('oauth_reference_required')
    controls = _controls_for(credential_reference)
    try:
        supplied = Path(controls_path)
    except (TypeError, ValueError):
        _fail('installation_controls_path_required')
    if supplied != controls:
        _fail('installation_controls_path_required')
    _reject_links(supplied)
    return controls


def _unknown_request_snapshot(db, controls, registration):
    """Read under the installation transaction; never regenerate old bindings."""
    barrier = _installation_barrier(db, controls)
    accounts = db.execute('SELECT registration,state,owner FROM plan_accounts LIMIT 1025').fetchall()
    if len(accounts) > 1024:
        _fail('account_controls_invalid')
    own = next((row for row in accounts if row[0] == registration and row[1] == 'reserved_unknown' and row[2] is not None), None)
    if own is None:
        other = any(state == 'reserved_unknown' and owner is not None for _, state, owner in accounts)
        kind = 'k1_other_registration' if other else 'k2_unresolvable' if barrier['pending'] else 'none'
        return kind, None
    matches = db.execute('SELECT filename,binding,calls FROM plan_ledgers WHERE binding=? LIMIT 2', (own[2],)).fetchall()
    if len(matches) != 1:
        _fail('campaign_controls_inconsistent')
    filename, binding, calls = matches[0]
    path = controls / filename
    with closing(sqlite3.connect(sqlite_uri(path) + '?mode=ro', uri=True, timeout=5)) as ledger:
        ledger.execute('BEGIN')
        budget, receipts = _checked_campaign_rows(ledger, 'main', (binding, calls))
    if budget[2] is not None or receipts[-1][0] != calls or receipts[-1][3] != 'reserved_unknown':
        _fail('no_resolvable_unknown_request')
    resolved_registrations = set()
    deadline = time.monotonic() + 5
    for other_filename, other_binding, other_calls in db.execute('SELECT filename,binding,calls FROM plan_ledgers').fetchall():
        if time.monotonic() >= deadline:
            _fail('account_controls_unavailable')
        with closing(sqlite3.connect(sqlite_uri(controls / other_filename) + '?mode=ro', uri=True, timeout=1)) as ledger:
            ledger.execute('BEGIN')
            other_budget, rows = _checked_campaign_rows(ledger, 'main', (other_binding, other_calls))
        for row in rows:
            if other_filename == filename and row[0] == calls:
                continue
            if row[3] == _CONFIRMED_CONSUMED:
                resolved = _confirmed_registration(db, 'main', other_filename, row, other_budget)
                if resolved is None:
                    _fail('active_or_unknown_request')
                resolved_registrations.add(resolved)
            elif row[3] != 'completed' and row[3] not in set(ERROR_STATES.values()):
                _fail('active_or_unknown_request')
    for account_registration, state, owner in accounts:
        if account_registration == registration:
            continue
        if owner is not None or state not in set(ERROR_STATES.values()) | {None, _CONFIRMED_CONSUMED}:
            _fail('active_or_unknown_request')
        if state == _CONFIRMED_CONSUMED and account_registration not in resolved_registrations:
            _fail('active_or_unknown_request')
    return 'k1_resolvable', (path, binding, calls, receipts[-1])


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


def _create_resolution_audit(db):
    # execute (not executescript) preserves the caller's cross-database transaction.
    db.execute(
        'CREATE TABLE IF NOT EXISTS plan_resolutions ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, sequence INTEGER NOT NULL, request_hash TEXT NOT NULL,'
        'registration TEXT NOT NULL, previous_status TEXT NOT NULL CHECK(previous_status=\'reserved_unknown\'),'
        'new_status TEXT NOT NULL CHECK(new_status=\'user_confirmed_consumed\'), acknowledgement_version INTEGER NOT NULL,'
        'official_usage_checked INTEGER NOT NULL CHECK(official_usage_checked=1),'
        'no_refund_acknowledged INTEGER NOT NULL CHECK(no_refund_acknowledged=1),'
        'no_other_tool_acknowledged INTEGER NOT NULL CHECK(no_other_tool_acknowledged=1),'
        'confirmed_at_utc TEXT NOT NULL, implementation_hash TEXT NOT NULL, UNIQUE(filename,sequence))'
    )
    for operation in ('UPDATE', 'DELETE'):
        db.execute(
            'CREATE TRIGGER IF NOT EXISTS plan_resolutions_no_' + operation.lower() + ' BEFORE ' + operation
            + ' ON plan_resolutions BEGIN SELECT RAISE(ABORT,\'append_only\'); END'
        )
    if not _resolution_audit_triggers(db):
        _fail('account_controls_invalid')


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


# R2: manual reconciliation of finished-unknown (K2) receipts. R1 entry points,
# _reserve, _finish and clear_account_pause keep their behaviour.
_FINISHED_AUDIT_TABLE_SQL = (
    'CREATE TABLE IF NOT EXISTS plan_finished_resolutions ('
    'id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, sequence INTEGER NOT NULL, request_hash TEXT NOT NULL,'
    'receipt_hash TEXT NOT NULL, registration TEXT NOT NULL,'
    'previous_status TEXT NOT NULL CHECK(previous_status IN ('
    + ','.join("'" + status + "'" for status in sorted(_FINISHED_UNKNOWN_STATUSES))
    + ')), new_status TEXT NOT NULL CHECK(new_status=\'user_confirmed_consumed\'), acknowledgement_version INTEGER NOT NULL,'
    'official_usage_checked INTEGER NOT NULL CHECK(official_usage_checked=1),'
    'no_refund_acknowledged INTEGER NOT NULL CHECK(no_refund_acknowledged=1),'
    'other_usage_acknowledged INTEGER NOT NULL CHECK(other_usage_acknowledged=1),'
    'confirmed_at_utc TEXT NOT NULL, implementation_hash TEXT NOT NULL, UNIQUE(filename,sequence))'
)


def _finished_audit_triggers_sql():
    return {
        'plan_finished_resolutions_no_' + operation.lower():
        'CREATE TRIGGER IF NOT EXISTS plan_finished_resolutions_no_' + operation.lower() + ' BEFORE ' + operation
        + " ON plan_finished_resolutions BEGIN SELECT RAISE(ABORT,'append_only'); END"
        for operation in ('UPDATE', 'DELETE')
    }


def _normalized_sql(sql):
    return re.sub(r'\s+', '', sql).lower().replace('ifnotexists', '').rstrip(';')


def _finished_audit_valid(db, schema):
    """The exact K2 table and append-only triggers; a permissive table is never adopted."""
    if schema not in ('main', 'account_controls'):
        _fail('account_controls_invalid')
    expected = {'plan_finished_resolutions': _FINISHED_AUDIT_TABLE_SQL, **_finished_audit_triggers_sql()}
    try:
        rows = db.execute(
            'SELECT name,sql FROM ' + schema + ".sqlite_master WHERE tbl_name='plan_finished_resolutions' "
            "AND type IN ('table','trigger')"
        ).fetchall()
    except sqlite3.Error:
        return False
    return len(rows) == len(expected) and all(
        name in expected and type(sql) is str and _normalized_sql(sql) == _normalized_sql(expected[name]) for name, sql in rows
    )


def _receipt_digest(row):
    """One digest over the exact 8-column plan_calls tuple, used by writer and verifier."""
    return content_hash(list(row))


def _confirmed_registration(db, schema, filename, receipt, budget):
    """Exactly one valid R1 or R2 audit row makes a consumed receipt final."""
    if schema not in ('main', 'account_controls'):
        _fail('account_controls_invalid')
    try:
        tables = {
            name
            for (name,) in db.execute(
                'SELECT name FROM ' + schema + ".sqlite_master WHERE type='table' "
                "AND name IN ('plan_resolutions','plan_finished_resolutions')"
            ).fetchall()
        }
        k1 = []
        k2 = []
        if 'plan_resolutions' in tables:
            k1 = db.execute(
                'SELECT 1 FROM ' + schema + '.plan_resolutions WHERE filename=? AND sequence=? LIMIT 2', (filename, receipt[0])
            ).fetchall()
        if 'plan_finished_resolutions' in tables:
            k2 = db.execute(
                'SELECT request_hash,receipt_hash,registration,previous_status,new_status,acknowledgement_version,'
                'official_usage_checked,no_refund_acknowledged,other_usage_acknowledged,confirmed_at_utc,implementation_hash '
                'FROM ' + schema + '.plan_finished_resolutions WHERE filename=? AND sequence=? LIMIT 2',
                (filename, receipt[0]),
            ).fetchall()
    except sqlite3.Error:
        return None
    if len(k1) + len(k2) != 1:
        return None
    if k1:
        # A genuine R1 resolution always records blocked=user_confirmed_consumed.
        if budget[2] != _CONFIRMED_CONSUMED:
            return None
        return _resolution_registration(db, schema, filename, receipt)
    if not _finished_audit_valid(db, schema):
        return None
    row = k2[0]
    original = (*receipt[:3], row[3], *receipt[4:])
    if (
        row[0] != receipt[1]
        or type(row[1]) is not str
        or row[1] != _receipt_digest(original)
        or type(row[2]) is not str
        or not re.fullmatch('[a-f0-9]{32}', row[2])
        or row[3] not in _FINISHED_UNKNOWN_STATUSES
        or row[3] != budget[2]
        or row[4] != _CONFIRMED_CONSUMED
        or receipt[0] != budget[1]
        or receipt[4] is not None
        or receipt[5] != '"unknown"'
        or type(row[5]) is not int
        or row[5] not in _FINISHED_ACKNOWLEDGEMENT_VERSIONS
        or any(type(value) is not int or value != 1 for value in row[6:9])
        or type(row[9]) is not str
        or type(row[10]) is not str
        or not re.fullmatch('[a-f0-9]{64}', row[10])
    ):
        return None
    try:
        recorded = datetime.fromisoformat(row[9])
        if recorded.utcoffset() != timezone.utc.utcoffset(recorded):
            return None
    except ValueError:
        return None
    return row[2]


def _finished_request_snapshot(db, controls, registration):
    """Map one K2 receipt to one registration from existing data, or refuse."""
    barrier = _installation_barrier(db, controls)
    if not barrier['pending']:
        return 'none', None
    accounts = db.execute('SELECT registration,state,owner FROM plan_accounts LIMIT 1025').fetchall()
    if len(accounts) > 1024:
        _fail('account_controls_invalid')
    if any(owner is not None or state == 'reserved_unknown' for _, state, owner in accounts):
        return 'k2_unresolvable', None
    known = set(ERROR_STATES.values())
    candidates = []
    resolved_registrations = set()
    deadline = time.monotonic() + 5
    for filename, binding, calls in db.execute('SELECT filename,binding,calls FROM plan_ledgers').fetchall():
        if time.monotonic() >= deadline:
            _fail('account_controls_unavailable')
        path = controls / filename
        with closing(sqlite3.connect(sqlite_uri(path) + '?mode=ro', uri=True, timeout=1)) as ledger:
            ledger.execute('BEGIN')
            budget, rows = _checked_campaign_rows(ledger, 'main', (binding, calls))
        for row in rows:
            if row[3] == 'completed' or row[3] in known:
                continue
            if row[3] == _CONFIRMED_CONSUMED:
                resolved = _confirmed_registration(db, 'main', filename, row, budget)
                if resolved is None:
                    return 'k2_unresolvable', None
                resolved_registrations.add(resolved)
            elif row[3] in _FINISHED_UNKNOWN_STATUSES:
                candidates.append((path, binding, calls, budget, rows, row))
            else:
                return 'k2_unresolvable', None
    if len(candidates) != 1:
        return 'k2_unresolvable', None
    path, binding, calls, budget, rows, receipt = candidates[0]
    if (
        receipt[0] != calls
        or budget[1] != calls
        or any(row[3] != 'completed' for row in rows[:-1])
        or budget[2] != receipt[3]
        or receipt[4] is not None
        or receipt[5] != '"unknown"'
    ):
        return 'k2_unresolvable', None
    unresolved = []
    for account_registration, state, _ in accounts:
        if state is None or state in known:
            continue
        if state == _CONFIRMED_CONSUMED:
            if account_registration not in resolved_registrations:
                return 'k2_unresolvable', None
            continue
        unresolved.append((account_registration, state))
    if len(unresolved) != 1 or unresolved[0][1] != receipt[3]:
        return 'k2_unresolvable', None
    if unresolved[0][0] != registration:
        return 'k2_other_registration', None
    return 'k2_resolvable', (path, binding, calls, budget, receipt)


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


def _create_finished_resolution_audit(db):
    # execute (not executescript) preserves the caller's cross-database transaction.
    db.execute(_FINISHED_AUDIT_TABLE_SQL)
    for sql in _finished_audit_triggers_sql().values():
        db.execute(sql)
    if not _finished_audit_valid(db, 'main'):
        _fail('account_controls_invalid')


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


def _checked_campaign_rows(db, schema, expected):
    """Must run in the same transaction as the global expectation read."""
    try:
        budget=db.execute('SELECT binding,calls,blocked FROM '+schema+'.plan_budget WHERE id=1').fetchone()
        rows=db.execute('SELECT sequence,request_hash,request_bytes,status,response_hash,usage,received_bytes,elapsed_seconds FROM '+schema+'.plan_calls ORDER BY sequence LIMIT 101').fetchall()
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

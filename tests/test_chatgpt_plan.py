"""P1–P6 synthetic protocol fixtures only. No live sign-in or inference."""
import json
import pickle
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import unittest
import tempfile
from pathlib import Path
from desktop_chatgpt_auth import OAuthCredentialReference
from quantlab.core import ValidationError
from desktop_chatgpt_provider import (ChatGPTPlanProvider, PlanError, SSEParser,
    parse_models, parse_completed, ERROR_STATES, RESPONSES_URL, PlanHTTPTransport as RealTransport, clear_account_pause, read_account_status)

CANDIDATE = {'strategy_id':'mock_trend','family':'trend','parameters':{'fast':5,'slow':20},'rules':{}}

def terminal(usage=None):
    response = {'id':'resp_fixture','status':'completed','output':[{'type':'message','role':'assistant',
       'content':[{'type':'output_text','text':json.dumps(CANDIDATE)}]}]}
    if usage is not None: response['usage']=usage
    return {'type':'response.completed','response':response}

def frame(event):
    return ('data: '+json.dumps(event,ensure_ascii=False)+'\r\n\r\n').encode()

def provider(tmp_path, **kwargs):
    opts=dict(model='fixture-model',credential_reference=OAuthCredentialReference(str(tmp_path/'auth'),'a'*32),
      budget_path=tmp_path/'auth'/'control-v1'/'plan.sqlite',campaign_id='test-campaign',network_opt_in=True,
      included_usage_policy_confirmed=True,max_calls=2)
    opts.update(kwargs)
    return ChatGPTPlanProvider(**opts)

class MockTransport:
    """In-memory wire fixture, never represents actual model verification."""
    requests=[]
    events=None
    def stream(self, reference, request, limits, cancelled):
        self.requests.append((RESPONSES_URL,request))
        yield from (self.events if self.events is not None else [frame(terminal())])
    def models(self, reference, limits, cancelled):
        return {'models':[{'slug':'fixture-model','display_name':'Fixture','visibility':'list'}]}

def crash_after_reservation(path):
    with patch('desktop_chatgpt_provider.implementation_provenance',return_value={'source_sha256': {'offline_fixture':'a'*64}}):
        p=provider(Path(path));p._reserve('0'*64,100)
    os._exit(0)  # Synthetic worker death, no network or remote operation.

def competing_reservation(path, queue):
    try:
        with patch('desktop_chatgpt_provider.implementation_provenance',return_value={'source_sha256': {'offline_fixture':'a'*64}}):
            queue.put(provider(Path(path))._reserve('0'*64,100))
    except PlanError:queue.put(None)

class FakeSocket:
    def settimeout(self,value):pass
    def shutdown(self,value):pass
    def close(self):pass

class FakeResponse:
    status=200
    headers={'Content-Type':'text/event-stream'}
    chunks=[]
    def getheader(self,name,default=None):return self.headers.get(name,default)
    def read1(self,size):
        if not self.chunks:return b''
        item=self.chunks.pop(0)
        if isinstance(item,BaseException):raise item
        return item

class FakeHTTPS:
    requests=[]
    def __init__(self,*args,**kwargs):
        self.args=args;self.kwargs=kwargs;self.sock=FakeSocket()
    def request(self,*args,**kwargs):self.requests.append((self.args,args,kwargs))
    def getresponse(self):return FakeResponse()
    def close(self):pass

SYNTHETIC_PROVENANCE = {'source_sha256': {'offline_fixture': 'a'*64}}

class PlanTests(unittest.TestCase):
    def setUp(self):
        patcher=patch('desktop_chatgpt_provider.implementation_provenance',return_value=SYNTHETIC_PROVENANCE)
        patcher.start();self.addCleanup(patcher.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.tmp_path=Path(self.temp.name)
        MockTransport.requests=[];MockTransport.events=None
        patcher=patch('http.client.HTTPSConnection',side_effect=AssertionError('No live HTTP'))
        patcher.start();self.addCleanup(patcher.stop)
        patcher=patch('desktop_chatgpt_provider.PlanHTTPTransport',MockTransport)
        patcher.start();self.addCleanup(patcher.stop)

# P1: exact payload; inert construction and explicit admission.
    def test_p1_golden_request(self):
        tmp_path=self.tmp_path
        p=provider(tmp_path)
        assert not p.path.exists()
        assert p.generate({'family':'trend'})==CANDIDATE
        endpoint,request=MockTransport.requests[0]
        assert endpoint=='https://api.openai.com/v1/responses'
        assert set(request)=={'model','instructions','input','store','stream'}
        assert request['store'] is False and request['stream'] is True
        assert request['input'][0]['role']=='user'
        assert p.real_model_status=='not_verified'
        assert b'fixture-model' in pickle.dumps(p)

    def test_p1_admission(self):
        tmp_path=self.tmp_path
        for setting in [{'network_opt_in':False},{'included_usage_policy_confirmed':False},{'hard_token_limit':100}]:
            with self.subTest(setting=setting):
                tmp_path=self.tmp_path/str(len(list(self.tmp_path.iterdir())))
                tmp_path.mkdir()
                with self.assertRaises(ValidationError):provider(tmp_path,**setting).generate({'family':'trend'})
                assert not (tmp_path/'auth'/'control-v1'/'plan.sqlite').exists()

# P2: catalog shape and ordering, hidden model cannot be selected.
    def test_p2_models(self):
        tmp_path=self.tmp_path
        assert parse_models({'models':[{'slug':'b','display_name':'B','visibility':'list'},
          {'slug':'hide','display_name':'H','visibility':'hidden'},{'slug':'a','display_name':'A','visibility':'list'}]})==[
          {'slug':'b','display_name':'B'},{'slug':'a','display_name':'A'}]
        for bad in ({'data':[]},{'models':[]},{'models':[{'slug':'a'}]},
                    {'models':[{'slug':'a','display_name':'A','visibility':'list'}]*2}):
            with self.assertRaises(ValidationError):parse_models(bad)

    def test_p2_unavailable(self):
        tmp_path=self.tmp_path
        with self.assertRaises(ValidationError):provider(tmp_path,model='missing').generate({'family':'trend'})
        assert MockTransport.requests==[]

# P3: every byte split, UTF8/comments/CRLF/multiline.
    def test_p3_split_matrix(self):
        tmp_path=self.tmp_path
        raw=b': comment\r\n\r\n'+frame({'type':'response.output_text.delta','delta':'\u4e2d'})+frame(terminal())
        for split in range(len(raw)+1):
            p=SSEParser();events=p.feed(raw[:split])+p.feed(raw[split:]);p.finish()
            assert len(events)==2
            assert parse_completed(events[-1]['response'],'trend')[0]==CANDIDATE
        p=SSEParser()
        assert p.feed(b'data: {"type":\r\ndata: "ping"}\r\n\r\n')==[{'type':'ping'}]

# P4: incomplete outcomes cannot yield candidates; reservation is irreversible.
    def test_p4_failures(self):
        tmp_path=self.tmp_path
        for events in [
    [],[b'data: [DONE]\n\n'],[frame({'type':'response.failed','response':{'error':{'code':'unknown'}}})],
    [frame({'type':'response.incomplete'})],[frame({'type':'error'})],
    [frame(terminal())+frame({'type':'response.failed'})],
    [b'data: {"type":"response.completed","type":"x"}\n\n'],
]:
            with self.subTest(events=events):
                tmp_path=self.tmp_path/str(len(list(self.tmp_path.iterdir())))
                tmp_path.mkdir()
                MockTransport.events=events;p=provider(tmp_path)
                with self.assertRaises(ValidationError):p.generate({'family':'trend'})
                receipts=p.read_receipts()
                assert len(receipts)==1 and receipts[0]['status']!='completed'
                assert receipts[0]['token_usage']=='unknown'

    def test_p4_terminal_rejection(self):
        tmp_path=self.tmp_path
        for change in [
    {'output':[{'type':'function_call','name':'tool'}]},
    {'output':[{'type':'message','role':'assistant','content':[{'type':'refusal','refusal':'no'}]}]},
    {'status':'incomplete'},{'output':[]},
]:
            with self.subTest(change=change):
                response=terminal()['response'];response.update(change)
                with self.assertRaises(ValidationError):parse_completed(response,'trend')

    def test_p4_bounds(self):
        tmp_path=self.tmp_path
        with self.assertRaises(ValidationError):SSEParser(max_bytes=8).feed(b'x'*9)
        with self.assertRaises(ValidationError):SSEParser().feed(b'data: {"x":NaN}\n\n')
        with self.assertRaises(ValidationError):SSEParser().feed(b'data: {"x":1e999}\n\n')

# P5: concurrent processes use the same atomic SQLite contract; restart cannot refund.
    def test_p5_concurrent_reservations(self):
        tmp_path=self.tmp_path
        p=provider(tmp_path,max_calls=3)
        def reserve(_):
            try:
                sequence=p._reserve('0'*64,100)
                p._finish(sequence,'completed')
                return sequence
            except ValidationError:return None
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(20)))
        while len(p.read_receipts())<3:
            results.append(reserve(None))
        assert sorted(x for x in results if x is not None)==[1,2,3]
        assert len(provider(tmp_path,max_calls=3).read_receipts())==3
        with self.assertRaises(ValidationError):provider(tmp_path,max_calls=4)._reserve('0'*64,100)
        assert all(r['token_usage']=='unknown' for r in p.read_receipts())

    def test_p5_usage_and_claims(self):
        tmp_path=self.tmp_path
        p=provider(tmp_path);p.generate({'family':'trend'})
        d=p.provider_descriptor()
        assert d['token_upper_bound_enforced'] is False and d['spend_upper_bound_enforced'] is False
        for usage in (None,{'input_tokens':1,'output_tokens':2,'total_tokens':3}, {'total_tokens':-1}):
            _,observed=parse_completed(terminal(usage)['response'],'trend')
            assert (observed=='unknown') == (usage is None or usage.get('total_tokens')==-1)

# P6: all documented error codes stop without retries or alternate billing.
    def test_p6_errors(self):
        tmp_path=self.tmp_path
        for code in list(ERROR_STATES):
            with self.subTest(code=code):
                tmp_path=self.tmp_path/code
                MockTransport.requests=[]
                MockTransport.events=[frame({'type':'response.failed','response':{'error':{'code':code}}})]
                p=provider(tmp_path)
                with self.assertRaises(PlanError) as caught:p.generate({'family':'trend'})
                assert caught.exception.code==ERROR_STATES[code]
                assert len(MockTransport.requests)==1
                with self.assertRaises(ValidationError):p.generate({'family':'trend'})
                assert len(MockTransport.requests)==1

    def test_p5_crash_barrier(self):
        p=provider(self.tmp_path);p._reserve('0'*64,100)
        restarted=provider(self.tmp_path)
        with self.assertRaises(PlanError):restarted._reserve('1'*64,100)
        with self.assertRaises(PlanError):restarted.generate({'family':'trend'})
        assert MockTransport.requests==[]
        assert restarted.read_receipts()[0]['status']=='reserved_unknown'

    def test_p4_cancel_and_absolute_deadline(self):
        p=provider(self.tmp_path)
        with self.assertRaises(PlanError):p.generate({'family':'trend'},cancelled=lambda:True)
        assert MockTransport.requests==[]
        p=provider(self.tmp_path/'slow')
        import time
        expired=time.monotonic()+p.timeout+1
        def slow_stream(*args):
            with patch('desktop_chatgpt_provider.time.monotonic',return_value=expired):
                yield frame(terminal())
        with patch.object(MockTransport,'stream',slow_stream):
            with self.assertRaises(PlanError):p.generate({'family':'trend'})
        assert p.read_receipts()[0]['status']=='deadline_exceeded'

    def test_p3_mismatched_response_ids(self):
        MockTransport.events=[frame({'type':'response.created','response':{'id':'different'}}),frame(terminal())]
        p=provider(self.tmp_path)
        with self.assertRaises(PlanError):p.generate({'family':'trend'})
        assert p.read_receipts()[0]['status']=='response_id_mismatch'

    def test_p5_actual_worker_death(self):
        process=multiprocessing.get_context('spawn').Process(target=crash_after_reservation,args=(str(self.tmp_path),))
        process.start();process.join(10)
        try:
            assert process.exitcode==0
            p=provider(self.tmp_path)
            with self.assertRaises(PlanError):p.generate({'family':'trend'})
            assert len(p.read_receipts())==1
            assert MockTransport.requests==[]
        finally:
            if process.is_alive():process.kill();process.join()
            process.close()

    def test_p1_http_wire_and_failures(self):
        import time
        reference=provider(self.tmp_path).credential_reference
        limits=dict(deadline=time.monotonic()+30,stall_seconds=10,max_request_bytes=65536,max_response_bytes=262144)
        request={'model':'fixture-model','input':[],'instructions':'mock','stream':True,'store':False}
        FakeHTTPS.requests=[]
        with patch('http.client.HTTPSConnection',FakeHTTPS), patch.object(OAuthCredentialReference,'__call__',return_value='fixture-oauth-secret'):
            FakeResponse.status=200;FakeResponse.headers={'Content-Type':'text/event-stream'}
            FakeResponse.chunks=[frame(terminal())]
            assert list(RealTransport().stream(reference,request,limits))==[frame(terminal())]
            host,args,kwargs=FakeHTTPS.requests[-1]
            assert host==('api.openai.com',443)
            assert args==('POST','/v1/responses')
            assert kwargs['headers']['Authorization']=='Bearer fixture-oauth-secret'
            assert json.loads(kwargs['body'])==request
            for status,headers,chunks in (
                (302,{},[]),(200,{'Content-Type':'application/json'},[]),
                (200,{'Content-Encoding':'gzip'},[]),
                (200,{'Content-Length':'999999999'},[]),
                (200,{'Content-Type':'text/event-stream'},[TimeoutError()]),
                (403,{'Content-Type':'application/json'},[b'{"detail":"subscription_sharing_user_not_eligible"}']),
            ):
                with self.subTest(status=status,headers=headers):
                    FakeResponse.status=status;FakeResponse.headers=headers;FakeResponse.chunks=chunks
                    with self.assertRaises(PlanError):list(RealTransport().stream(reference,request,limits))
            with self.assertRaises(PlanError):
                with RealTransport()._response(reference,'POST','https://attacker.invalid',None,limits,None):pass
        assert b'fixture-oauth-secret' not in pickle.dumps(provider(self.tmp_path))

    def test_p5_multiprocess_atomic_pending_barrier(self):
        context=multiprocessing.get_context('spawn');queue=context.Queue()
        processes=[context.Process(target=competing_reservation,args=(str(self.tmp_path),queue)) for _ in range(6)]
        try:
            for process in processes:process.start()
            results=[queue.get(timeout=10) for _ in processes]
            for process in processes:process.join(10)
            assert [value for value in results if value is not None]==[1]
            assert len(provider(self.tmp_path).read_receipts())==1
        finally:
            for process in processes:
                if process.is_alive():process.kill();process.join()
                process.close()
            queue.close();queue.join_thread()

    def test_p6_account_pause_cross_campaign_and_explicit_recovery(self):
        p=provider(self.tmp_path)
        MockTransport.events=[frame({'type':'response.failed','response':{'error':{'code':'subscription_sharing_usage_limit_exceeded'}}})]
        with self.assertRaises(PlanError):p.generate({'family':'trend'})
        other=provider(self.tmp_path,budget_path=p.path.parent/'other.sqlite',campaign_id='second')
        with self.assertRaises(PlanError):other.generate({'family':'trend'})
        assert len(MockTransport.requests)==1
        with self.assertRaises(PlanError):clear_account_pause(p.credential_reference,p.path.parent)
        clear_account_pause(p.credential_reference,p.path.parent,user_confirmed=True)
        MockTransport.events=None
        assert other.generate({'family':'trend'})==CANDIDATE
        # Recovery never refunds/resets the failed campaign itself.
        with self.assertRaises(PlanError):p.generate({'family':'trend'})
        assert len(MockTransport.requests)==2

    def test_p5_account_unknown_cross_campaign(self):
        p=provider(self.tmp_path);p._reserve('0'*64,100)
        other=provider(self.tmp_path,budget_path=p.path.parent/'other.sqlite',campaign_id='second')
        with self.assertRaises(PlanError):other.generate({'family':'trend'})
        with self.assertRaises(PlanError):other._reserve('1'*64,100)
        with self.assertRaises(PlanError):clear_account_pause(p.credential_reference,p.path.parent,user_confirmed=True)
        assert MockTransport.requests==[]

    def test_p5_changed_control_directory_rejected(self):
        p=provider(self.tmp_path);p._reserve('0'*64,100)
        for path in (self.tmp_path/'restored'/'plan.sqlite',self.tmp_path/'other'/'plan.sqlite'):
            with self.subTest(path=path):
                with self.assertRaises(PlanError):
                    provider(self.tmp_path,budget_path=path,campaign_id='changed',model='another-model')
        with self.assertRaises(PlanError):
            clear_account_pause(p.credential_reference,self.tmp_path/'restored',user_confirmed=True)
        assert not (self.tmp_path/'restored').exists()
        assert MockTransport.requests==[]

    def test_p5_noncanonical_control_paths(self):
        for path in ('relative.sqlite',':memory:','file:controls.sqlite?mode=memory'):
            with self.subTest(path=path):
                with self.assertRaises(PlanError):provider(self.tmp_path,budget_path=path)
        p=provider(self.tmp_path)
        with self.assertRaises(PlanError):provider(self.tmp_path,budget_path=p.account_path)
        p.path.parent.mkdir(parents=True)
        target=self.tmp_path/'target.sqlite';target.touch()
        try:p.path.symlink_to(target)
        except OSError:self.skipTest('Host does not permit synthetic symlink creation')
        with self.assertRaises(PlanError):provider(self.tmp_path)

    def test_p5_readonly_sanitized_account_status(self):
        p=provider(self.tmp_path)
        assert read_account_status(p.credential_reference,p.path.parent)=={'state':'ready','pending':False}
        assert not p.path.parent.exists()
        p._reserve('0'*64,100)
        assert read_account_status(p.credential_reference,p.path.parent)=={'state':'reserved_unknown','pending':True}
        p._finish(1,'quota_paused')
        assert read_account_status(p.credential_reference,p.path.parent)=={'state':'quota_paused','pending':False}
        with self.assertRaises(PlanError):read_account_status(p.credential_reference,self.tmp_path/'different')

    def test_readonly_identity_without_new_consent(self):
        acknowledged=provider(self.tmp_path)
        readonly=provider(self.tmp_path,network_opt_in=False,included_usage_policy_confirmed=False)
        assert readonly.provider_descriptor()==acknowledged.provider_descriptor()
        assert readonly.provider_descriptor()['included_usage_policy_ack_required'] is True
        with self.assertRaises(PlanError):readonly.generate({'family':'trend'})
        network_only=provider(self.tmp_path,network_opt_in=True,included_usage_policy_confirmed=False)
        with self.assertRaises(PlanError):network_only.generate({'family':'trend'})
        assert MockTransport.requests==[] and not readonly.path.exists()
        acknowledged.generate({'family':'trend'})
        assert len(readonly.read_receipt_snapshot()['receipts'])==1

    def test_missing_global_control_database_never_reinitializes(self):
        p=provider(self.tmp_path);p._reserve('a'*64,100)
        p.account_path.unlink()
        other=provider(self.tmp_path,budget_path=p.path.parent/'other.sqlite',campaign_id='other')
        with self.assertRaises(PlanError):other._reserve('b'*64,100)
        with self.assertRaises(PlanError):read_account_status(p.credential_reference,p.path.parent)
        with patch.object(MockTransport,'models') as metadata:
            with self.assertRaises(PlanError):other.generate({'family':'trend'})
            metadata.assert_not_called()
        assert not p.account_path.exists() and not other.path.exists()

    def test_missing_expected_campaign_database_is_not_empty_success(self):
        p=provider(self.tmp_path);p._reserve('a'*64,100);p.path.unlink()
        with self.assertRaises(PlanError):p.read_receipt_snapshot()
        with self.assertRaises(PlanError):p.read_receipts()
        with self.assertRaises(PlanError):p._reserve('b'*64,100)
        assert not p.path.exists()

    def test_old_or_reset_campaign_database_rejected(self):
        p=provider(self.tmp_path,max_calls=3);p._reserve('a'*64,100);p._finish(1,'completed')
        old=p.path.read_bytes();p._reserve('b'*64,100);p._finish(2,'completed')
        for replacement in (old,b''):
            p.path.write_bytes(replacement)
            with self.assertRaises(PlanError):p.read_receipt_snapshot()
            with self.assertRaises(PlanError):p._reserve('c'*64,100)
            assert p.path.read_bytes()==replacement

    def test_corrupt_global_campaign_and_receipt_fail_closed(self):
        import sqlite3
        for kind in ('global','campaign','receipt'):
            with self.subTest(kind=kind):
                p=provider(self.tmp_path/kind);p._reserve('a'*64,100)
                if kind=='global':p.account_path.write_bytes(b'not a sqlite database')
                elif kind=='campaign':p.path.write_bytes(b'not a sqlite database')
                else:
                    with sqlite3.connect(p.path) as db:db.execute('UPDATE plan_calls SET usage=?',('{"api_key":"SECRET_FIXTURE"}',))
                for operation in (p.read_receipt_snapshot,lambda:p._reserve('b'*64,100)):
                    with self.assertRaises(PlanError) as caught:operation()
                    assert 'SECRET_FIXTURE' not in str(caught.exception)

    def test_partial_initialization_is_not_silently_retried(self):
        import sqlite3
        p=provider(self.tmp_path)
        with patch('desktop_chatgpt_provider.sqlite3.connect',side_effect=sqlite3.OperationalError('synthetic init crash')):
            with self.assertRaises(PlanError):p._reserve('a'*64,100)
        marker=Path(p.credential_reference.bootstrap)/'chatgpt-plan-controls-v1.marker'
        assert marker.exists() and not p.account_path.exists()
        with self.assertRaises(PlanError):p._reserve('a'*64,100)
        with self.assertRaises(PlanError):p.read_receipt_snapshot()
        assert not p.account_path.exists()

    def test_first_use_and_unused_campaign_reads_are_inert(self):
        p=provider(self.tmp_path)
        assert p.read_receipt_snapshot()['receipts']==[]
        assert not p.path.parent.exists()
        p._reserve('a'*64,100);p._finish(1,'completed')
        unused=provider(self.tmp_path,budget_path=p.path.parent/'unused.sqlite',campaign_id='unused')
        assert unused.read_receipt_snapshot()['receipts']==[] and not unused.path.exists()
        assert p.read_receipt_snapshot()['receipts'][0]['sequence']==1

    def test_missing_marker_does_not_adopt_existing_controls(self):
        p=provider(self.tmp_path);p._reserve('a'*64,100)
        marker=Path(p.credential_reference.bootstrap)/'chatgpt-plan-controls-v1.marker';marker.unlink()
        with self.assertRaises(PlanError):p.read_receipt_snapshot()
        with self.assertRaises(PlanError):p._reserve('b'*64,100)
        assert not marker.exists()

    def test_partial_global_schema_is_not_repaired(self):
        import sqlite3
        p=provider(self.tmp_path);original=sqlite3.connect
        class InterruptedInit(sqlite3.Connection):
            def execute(self,statement,*args,**kwargs):
                if statement.startswith('CREATE TABLE plan_ledgers'):raise sqlite3.OperationalError('synthetic interrupted schema')
                return super().execute(statement,*args,**kwargs)
        def connect(*args,**kwargs):return original(*args,**kwargs,factory=InterruptedInit)
        with patch('desktop_chatgpt_provider.sqlite3.connect',connect):
            with self.assertRaises(PlanError):p._reserve('a'*64,100)
        before=p.account_path.read_bytes()
        with self.assertRaises(PlanError):p._reserve('a'*64,100)
        assert p.account_path.read_bytes()==before

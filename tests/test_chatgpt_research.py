"""Offline receipt-hook proposals; all model/worker results are synthetic."""
import copy
from contextlib import closing
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from quantlab.core import ValidationError, content_hash
from desktop_chatgpt_auth import OAuthCredentialReference
from tests.test_research import inputs, tracked_sqlite_connections
from quantlab import research as r
import desktop_chatgpt_provider as pmod


def receipt(sequence,status='completed'):
    return {'billing_route':'chatgpt_plan','paid_api_fallback':False,'token_upper_bound_enforced':False,
      'spend_upper_bound_enforced':False,'account_credit_policy':'unverified_user_setting',
      'sequence':sequence,'request_hash':'a'*64,'request_bytes':100,'status':status,
      'response_hash':None,'token_usage':'unknown','received_bytes':None,'elapsed_seconds':None}

class SyntheticProvider(r.FixtureGenerator):
    def __init__(self):self.rows=[];self.bad=False
    def provider_descriptor(self):return {'version':1,'registration':'a'*32,'campaign_id':'fixture'}
    def read_receipt_snapshot(self):
        return {'version':1,'provider_descriptor_hash':('b'*64 if self.bad else content_hash(self.provider_descriptor())),
                'receipts':copy.deepcopy(self.rows)}

class Tests(unittest.TestCase):
    def setUp(self):
        mock=patch.object(pmod,'implementation_provenance',return_value={'source_sha256':{'offline_fixture':'a'*64}})
        mock.start();self.addCleanup(mock.stop)
    def test_snapshot_replaces_without_duplicates(self):
        p=SyntheticProvider();provider=r._provider_identity(p);state={'provider_receipts':[],'status':'running'};attempt={'warnings':[]}
        for sequence in (1,2,3):
            p.rows.append(receipt(sequence))
            r._reconcile_provider_receipts(p,provider,state,attempt,True)
            assert len(state['provider_receipts'])==sequence
        assert [row['sequence'] for row in state['provider_receipts']]==[1,2,3]

    def test_unknown_retained_and_blocks(self):
        p=SyntheticProvider();p.rows=[receipt(1,'reserved_unknown')]
        state={'provider_receipts':[],'status':'running'};attempt={'warnings':[]}
        r._reconcile_provider_receipts(p,r._provider_identity(p),state,attempt,False)
        assert state['provider_receipts'][0]['status']=='reserved_unknown'
        assert state['status']=='blocked_provider_outcome'

    def test_malformed_cannot_replace_validated_snapshot(self):
        for mutate in (lambda s:s.update(provider_descriptor_hash='b'*64),
                       lambda s:s['receipts'][0].update(access_token='SECRET'),
                       lambda s:s['receipts'][0].update(status='SECRET'),
                       lambda s:s['receipts'][0].update(request_hash='/private/path'),
                       lambda s:s['receipts'][0].update(elapsed_seconds=float('nan'))):
            p=SyntheticProvider();p.rows=[receipt(1)];snapshot=p.read_receipt_snapshot();mutate(snapshot)
            p.read_receipt_snapshot=lambda:snapshot
            state={'provider_receipts':[receipt(1)],'status':'running'};attempt={'warnings':[]}
            r._reconcile_provider_receipts(p,r._provider_identity(p),state,attempt,True)
            assert state['status']=='blocked_provider_audit'
            assert state['provider_receipts']==[receipt(1)]
            assert 'SECRET' not in str(state)

    def test_wrong_account_and_campaign_ledger_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);reference=OAuthCredentialReference(str(root),'a'*32)
            settings=dict(model='mock',credential_reference=reference,budget_path=root/'control-v1'/'campaign.sqlite',campaign_id='first',max_calls=3)
            p=pmod.ChatGPTPlanProvider(**settings);p._reserve('a'*64,100);p._finish(1,'completed')
            assert len(p.read_receipt_snapshot()['receipts'])==1
            for change in ({'campaign_id':'different'},{'credential_reference':OAuthCredentialReference(str(root),'b'*32)}):
                with self.assertRaises(ValidationError):pmod.ChatGPTPlanProvider(**{**settings,**change}).read_receipt_snapshot()

    def test_full_campaign_failure_blocks_holdout(self):
        data,config=inputs();config.update(families=['trend'],max_improvements=0,max_trials=1)
        for malformed in (False,True):
            p=SyntheticProvider();p.rows=[receipt(1,'reserved_unknown')];p.bad=malformed
            with tempfile.TemporaryDirectory() as directory, patch.object(r,'_run_bounded',side_effect=r.ResourceTimeout('synthetic killed worker')), patch.object(r,'_reserve_holdout',side_effect=AssertionError('Holdout must not advance')):
                state=r.run_campaign(data,config=config,generator=p,output_dir=Path(directory)/'campaign')
            assert state['status']==('blocked_provider_audit' if malformed else 'blocked_provider_outcome')
            assert state['holdout_consumed'] is False
            assert state['evaluations']=={'oos':[],'holdout':[]}
            if not malformed:assert state['provider_receipts'][0]['status']=='reserved_unknown'

    def test_legacy_receipts_reconciliation_is_noop(self):
        state={'provider_receipts':[{'legacy':'unchanged'}],'status':'running'}
        r._reconcile_provider_receipts(r.FixtureGenerator(),{},state,{'warnings':[]},False)
        assert state=={'provider_receipts':[{'legacy':'unchanged'}],'status':'running'}


class SyntheticWire:
    """Offline mocked official wire; never reports real-model verification."""
    def models(self, reference, limits, cancelled):
        return {'models':[{'slug':'fixture-model','display_name':'Synthetic','visibility':'list'}]}
    def stream(self, reference, request, limits, cancelled):
        import json
        from quantlab.core import to_dict
        from quantlab.strategies import builtin_strategies
        context=json.loads(request['input'][0]['content'])
        candidate=to_dict(next(s for s in builtin_strategies() if s.family==context['family']))
        candidate['parameters']['fast']+=context.get('iteration',0)
        response={'id':'resp_synthetic','status':'completed','output':[{'type':'message','role':'assistant',
            'content':[{'type':'output_text','text':json.dumps(candidate)}]}]}
        yield ('data: '+json.dumps({'type':'response.completed','response':response})+'\n\n').encode()

class SyntheticPlanProvider(pmod.ChatGPTPlanProvider):
    def provider_descriptor(self):
        with patch.object(pmod,'implementation_provenance',return_value={'source_sha256':{'offline_fixture':'a'*64}}):
            return super().provider_descriptor()
    def generate(self,context):
        with patch.object(pmod,'PlanHTTPTransport',SyntheticWire), patch('http.client.HTTPSConnection',side_effect=AssertionError('No live HTTP')):
            return super().generate(context)

class CampaignIntegrationTests(unittest.TestCase):
    def provider(self,root,**changes):
        options=dict(model='fixture-model',credential_reference=OAuthCredentialReference(str(root),'a'*32),
            budget_path=root/'control-v1'/'campaign.sqlite',campaign_id='synthetic-campaign',
            network_opt_in=True,included_usage_policy_confirmed=True,max_calls=3)
        options.update(changes)
        return SyntheticPlanProvider(**options)

    def test_real_new_provider_through_existing_campaign(self):
        data,config=inputs();config.update(families=['trend'],max_improvements=1,max_trials=2)
        config['ranking']['minimum']='-1000000'
        # Spawn is exercised even on Linux; mock transport lives in the worker's
        # importable trusted fixture subclass, never inherited monkeypatch state.
        config['process_start_method']='spawn'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=self.provider(root)
            state=r.run_campaign(data,config=config,generator=p,output_dir=root/'research')
            assert len(state['attempts'])==2
            assert len(state['provider_receipts'])==2
            assert all(row['status']=='completed' for row in state['provider_receipts'])
            assert state['real_model_status']=='not_verified'
            assert state['binding']['provider']['descriptor']['registration']=='a'*32
            assert state['holdout_consumed'] is True
            assert len(p.read_receipt_snapshot()['receipts'])==2

    def test_changed_real_engine_hash_rejects_rerun_without_ledger_reset(self):
        data,config=inputs();config.update(families=['trend'],max_improvements=0,max_trials=1)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=self.provider(root)
            state=r.run_campaign(data,config=config,generator=p,output_dir=root/'research')
            before=p.path.read_bytes();original=Path.read_text
            def changed(path,*args,**kwargs):
                value=original(path,*args,**kwargs)
                return value+'\n# synthetic changed engine source\n' if path==Path(r.__file__) else value
            with patch.object(Path,'read_text',changed):
                with self.assertRaises(ValidationError):
                    r.run_campaign(data,config=config,generator=p,output_dir=root/'research')
            assert p.path.read_bytes()==before
            import json
            assert json.loads((root/'research'/'campaign.json').read_text())['campaign_id']==state['campaign_id']
            assert len(p.read_receipt_snapshot()['receipts'])==1

    def test_legacy_subbindings(self):
        assert r._provider_identity(r.FixtureGenerator())=={'mode':'fixture','model':None,'endpoint':None}
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('json_object','registry_json_schema'):
                p=r.CompatibleProvider(model='mock',endpoint='https://example.invalid/v1/chat/completions',
                    transport=lambda *args:None,budget_path=Path(directory)/'budget',output_mode=mode)
                expected={'mode':p.mode,'model':p.model,'endpoint':p.endpoint,'limits':{
                    'calls':p.max_calls,'tokens':p.max_tokens,'spend':str(p.max_spend),'rate':str(p.cost_per_token),
                    'tokens_per_call':p.tokens_per_call,'timeout':p.timeout},'network_opt_in':p.network_opt_in,
                    'transport_type':type(p.transport).__module__+'.'+type(p.transport).__qualname__}
                if mode!='json_object':expected['output_mode']=mode
                assert r.canonical_json(r._provider_identity(p))==r.canonical_json(expected)

class CrashingSyntheticPlanProvider(SyntheticPlanProvider):
    def generate(self,context):
        import os
        self._reserve('a'*64,100)
        os._exit(71)  # Offline worker death after commit; no HTTP.

class ActualWorkerFailureTests(unittest.TestCase):
    def test_killed_worker_durable_snapshot_blocks_entire_campaign(self):
        data,config=inputs();config.update(families=['trend'],max_improvements=0,max_trials=1,process_start_method='spawn')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            p=CrashingSyntheticPlanProvider(model='fixture-model',credential_reference=OAuthCredentialReference(str(root),'a'*32),
                budget_path=root/'control-v1'/'campaign.sqlite',campaign_id='crash',max_calls=3)
            with patch.object(r,'_reserve_holdout',side_effect=AssertionError('Holdout must not advance')):
                state=r.run_campaign(data,config=config,generator=p,output_dir=root/'research')
            assert state['status']=='blocked_provider_outcome'
            assert state['holdout_consumed'] is False and state['selected']==[]
            assert len(state['provider_receipts'])==1
            assert state['provider_receipts'][0]['status']=='reserved_unknown'
            assert state['provider_receipts'][0]['token_usage']=='unknown'
            assert pmod.read_account_status(p.credential_reference,p.path.parent)['pending'] is True

class CompatibleImprovementReminderTests(unittest.TestCase):
    def test_generate_unchanged_improve_only_nonduplicate_tail(self):
        import json
        captured=[]
        def transport(endpoint,request,timeout):
            captured.append(copy.deepcopy(request))
            return {'choices':[{'message':{'content':'{}'}}]}
        context={'family':'trend','iteration':0,'previous':{'output':{'parameters':{'fast':2,'slow':4}}}}
        with tempfile.TemporaryDirectory() as directory:
            provider=r.CompatibleProvider(model='offline-fixture',endpoint='https://example.invalid/v1',
                transport=transport,budget_path=Path(directory)/'budget.sqlite',network_opt_in=True,
                max_calls=2,max_tokens=30000)
            provider.generate(context);provider.improve(context)
        assert captured[0]['messages'][-1]['content']==r.canonical_json(context)
        content=captured[1]['messages'][-1]['content']
        decoded,end=json.JSONDecoder().raw_decode(content)
        assert decoded['task']=='improve_previous_candidate'
        assert decoded['previous']['output']['parameters']=={'fast':2,'slow':4}
        tail=content[end:]
        assert tail==('\nBefore returning JSON, compare your chosen parameters with previous.output.parameters. '
            'At least one parameter value must differ. A new strategy_id alone is invalid. '
            'Choose the changed value yourself within the same schema; do not alter risk controls.')
        assert not any(char.isdigit() for char in tail)
        assert 'fast' not in tail and 'slow' not in tail
        assert 'task' not in context
        assert captured[0]['max_tokens']==captured[1]['max_tokens']
        assert captured[0]['response_format']==captured[1]['response_format']

def outer_fixture_provider(root):
    return SyntheticPlanProvider(model='fixture-model',credential_reference=OAuthCredentialReference(str(root),'a'*32),
        budget_path=root/'control-v1'/'outer.sqlite',campaign_id='outer-crash',max_calls=3)


def outer_campaign_wait_after_reservation(directory, ready):
    """Actual outer process fixture; reserves locally, never starts HTTP/children."""
    import time
    root=Path(directory);provider=outer_fixture_provider(root)
    data,config=inputs();config.update(families=['trend'],max_improvements=0,max_trials=1)
    def reserve_and_wait(*args,**kwargs):
        provider._reserve('a'*64,100)
        ready.send_bytes(b'reserved')
        while True:time.sleep(1)
    with patch.object(r,'_run_bounded',reserve_and_wait):
        r.run_campaign(data,config=config,generator=provider,output_dir=root/'research')

class OuterCampaignReconciliationTests(unittest.TestCase):
    def setUp(self):
        import multiprocessing
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        context=multiprocessing.get_context('spawn');receiver,sender=context.Pipe(duplex=False)
        process=context.Process(target=outer_campaign_wait_after_reservation,args=(str(self.root),sender))
        process.start();sender.close()
        try:
            assert receiver.poll(10) and receiver.recv_bytes()==b'reserved'
            process.terminate();process.join(10)
            assert not process.is_alive()
        finally:
            if process.is_alive():process.kill();process.join()
            process.close();receiver.close()
        self.provider=outer_fixture_provider(self.root);self.output=self.root/'research'
        # Hold references until after the assertion: garbage collection must
        # never turn an unclosed parent-side handle into a passing cleanup test.
        tracker=tracked_sqlite_connections()
        self.opened_connections=tracker.__enter__()
        self.addCleanup(tracker.__exit__,None,None,None)
        self.addCleanup(self.assert_parent_connections_closed)

    def assert_parent_connections_closed(self):
        self.assertTrue(self.opened_connections)
        self.assertTrue(all(db.closed_explicitly for db in self.opened_connections),
                        'Every fixture and reconciliation handle must close explicitly')

    def payload(self):
        import sqlite3,json
        with closing(sqlite3.connect(self.output/'campaign.sqlite3')) as db, db:
            return json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])

    def test_actual_outer_kill_reconciles_new_receipt_without_holdout(self):
        before=self.payload();assert before['provider_receipts']==[]
        with self.assertRaises(ValidationError):r.reconcile_interrupted_campaign(output_dir=self.output,generator=self.provider)
        with patch.object(r,'_reserve_holdout',side_effect=AssertionError('No holdout action')),patch.object(r,'_run_bounded',side_effect=AssertionError('No worker action')):
            state=r.reconcile_interrupted_campaign(output_dir=self.output,generator=self.provider,descendants_stopped=True)
        assert state['status']=='blocked_interrupted'
        assert state['attempts'][0]['status']=='interrupted'
        assert len(state['provider_receipts'])==1 and state['provider_receipts'][0]['status']=='reserved_unknown'
        assert not state['holdout_consumed'] and state['selected']==[]
        assert self.payload()==state
        assert pmod.read_account_status(self.provider.credential_reference,self.provider.path.parent)['pending'] is True

    def test_wrong_identity_and_busy_lock_leave_state_unchanged(self):
        import sqlite3
        before=self.payload();changed=outer_fixture_provider(self.root);changed.model='different'
        with self.assertRaises(ValidationError):r.reconcile_interrupted_campaign(output_dir=self.output,generator=changed,descendants_stopped=True)
        with closing(sqlite3.connect(self.output/'campaign.lock.sqlite3')) as lock, lock:
            lock.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(ValidationError):r.reconcile_interrupted_campaign(output_dir=self.output,generator=self.provider,descendants_stopped=True)
        assert self.payload()==before

    def test_retains_prior_attempts_and_consumed_holdout_state(self):
        import sqlite3,json
        before=self.payload();previous=copy.deepcopy(before['attempts'][0]);previous.update(status='evaluated',sequence=0)
        before['attempts'].insert(0,previous);before['holdout_consumed']=True
        before['holdout_status']='reserved';before['holdout_registry']={'fixture':'must-remain','status':'reserved'}
        before['evaluations']={'oos':[{'fixture':'prior-result'}],'holdout':[]}
        with closing(sqlite3.connect(self.output/'campaign.sqlite3')) as db, db:db.execute('UPDATE state SET payload=? WHERE id=1',(json.dumps(before),))
        state=r.reconcile_interrupted_campaign(output_dir=self.output,generator=self.provider,descendants_stopped=True)
        assert state['attempts'][0]==previous and state['attempts'][1]['status']=='interrupted'
        for key in ('holdout_consumed','holdout_status','holdout_registry','evaluations','selected'):
            assert state[key]==before[key]

    def test_missing_or_corrupt_campaign_is_not_created_or_overwritten(self):
        import sqlite3
        absent=self.root/'absent'
        with self.assertRaises(ValidationError):r.reconcile_interrupted_campaign(output_dir=absent,generator=self.provider,descendants_stopped=True)
        assert not absent.exists()
        with closing(sqlite3.connect(self.output/'campaign.sqlite3')) as db, db:db.execute('UPDATE state SET payload=? WHERE id=1',('{corrupt',))
        before_json=(self.output/'campaign.json').read_bytes()
        with self.assertRaises(ValidationError):r.reconcile_interrupted_campaign(output_dir=self.output,generator=self.provider,descendants_stopped=True)
        with closing(sqlite3.connect(self.output/'campaign.sqlite3')) as db, db:assert db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]=='{corrupt'
        assert (self.output/'campaign.json').read_bytes()==before_json

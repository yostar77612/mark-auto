"""OFFLINE fixtures only: no grant, network, real vault or subscription verification."""
import importlib.util
import os
import unittest
from urllib.parse import urlencode
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=importlib.util.find_spec('PySide6') is not None
REF='a'*32
OTHER='b'*32


def authorization_url(**changes):
    params=dict(client_id='dynamic_agent_client',ext_agent_host_id='urn:uuid:12345678-1234-1234-1234-123456789012',
        response_type='code',redirect_uri='http://127.0.0.1:12345/auth/callback',
        scope='openid profile email offline_access resource.invoke chatgpt.tokens.use.direct',resource='https://api.openai.com/v1',
        state='s'*43,nonce='n'*43,code_challenge_method='S256',code_challenge='c'*43)
    params.update(changes);return 'https://auth.openai.com/api/accounts/authorize?'+urlencode(params)


class FixtureSession:
    def __init__(self):self.state='disconnected';self.active_registration=None;self.calls=[];self.rows=[]
    def initialize_host(self):self.calls.append('initialize');return 'fixture-host'
    def begin(self,registration=None):self.calls.append('begin');self.state='authorizing';return authorization_url()
    def poll(self,timeout):
        self.calls.append('poll');self.state='plan_ready';self.active_registration=REF;self.rows=[{'registration':REF,'state':'plan_ready'}]
    def cancel(self):self.calls.append('cancel');self.state='cancelled'
    def select(self,ref):self.calls.append('select');self.active_registration=ref;self.state='plan_ready'
    def refresh(self,ref):self.calls.append('refresh');self.state='plan_ready'
    def sign_out(self,ref):self.calls.append('sign_out');self.state='disconnected';self.active_registration=None;return False
    def status_summary(self):return {'registrations':self.rows,'active_registration':self.active_registration,'state':self.state}


def fixture_process(request,queue,cancelled,block=False):
    import time
    from desktop_chatgpt_ui import run_connection_request
    class BlockingSession(FixtureSession):
        def begin(self,registration=None):
            time.sleep(60)
            return super().begin(registration)
    result=run_connection_request(request,bootstrap='/fixture',emit=queue.put,cancelled=cancelled.is_set,
        session_factory=BlockingSession if block else FixtureSession)
    queue.put(result)


@unittest.skipUnless(HAS_QT,'Install pinned desktop requirements to test Qt widgets')
class ChatGPTConnectionUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        import desktop_chatgpt_ui as ui
        self.ui=ui;self.controller=ui.ConnectionController();self.panel=ui.ChatGPTConnectionPanel(self.controller)
        self.requests=[];self.quiesce=[];self.cancel=[];self.browser=[]
        self.controller.request_ready.connect(self.requests.append);self.controller.quiesce_requested.connect(self.quiesce.append)
        self.controller.cancel_requested.connect(self.cancel.append);self.controller.browser_requested.connect(self.browser.append)
        self.addCleanup(self.panel.deleteLater)

    def ready(self):
        c=self.controller;c.set_host_available(True)
        request=c.request('list');c.apply_event(self.ui.ConnectionEvent(request.request_id,'result','plan_ready',((REF,'plan_ready'),),REF))
        c.worker_joined(request.request_id,joined=True)
        c.set_usage(REF,[],account_status={'state':'ready','pending':False})
        return c

    def test_construct_is_inert_and_host_disabled(self):
        self.assertEqual(self.requests,[]);self.assertEqual(self.quiesce,[]);self.assertFalse(self.controller.busy)
        self.assertFalse(self.panel.buttons['begin'].isEnabled());self.assertFalse(self.panel.consent.isChecked())
        self.assertIn('不能視為已用 0',self.panel.usage.text())
        self.assertIn('不保證零費用',self.panel.disclosure.text());self.assertIn('不會偷偷切換',self.panel.disclosure.text())

    def test_connect_requires_user_ack_and_actual_join_then_explicit_browser(self):
        c=self.controller;c.set_host_available(True)
        self.panel._act('begin');self.assertFalse(c.busy);self.assertEqual(self.requests,[])
        self.panel.consent.setChecked(True);self.panel._act('begin')
        request=self.quiesce[-1];self.assertEqual(request.action,'begin');self.assertFalse(self.panel.consent.isChecked())
        self.assertEqual(self.requests,[]);self.assertFalse(c.acknowledge_quiescence(request.request_id,joined=False))
        self.assertTrue(c.acknowledge_quiescence(request.request_id,joined=True));self.assertEqual(len(self.requests),1)
        event=self.ui.ConnectionEvent(request.request_id,'authorization','authorizing',authorization_url=authorization_url())
        self.assertNotIn('s'*43,repr(event));c.apply_event(event);self.assertEqual(self.browser,[])
        self.assertNotIn('nonce',self.panel.status.text());c.open_authorization();self.assertEqual(self.browser,[authorization_url()])
        with self.assertRaises(ValueError):c.open_authorization()

    def test_repeated_actions_late_events_and_terminal_message_cannot_bypass_join(self):
        c=self.ready();r=c.request('begin',confirmed=True)
        with self.assertRaises(ValueError):c.request('begin',confirmed=True)
        c.acknowledge_quiescence(r.request_id,joined=True)
        self.assertFalse(c.apply_event(self.ui.ConnectionEvent(r.request_id+1,'result','disconnected')))
        c.apply_event(self.ui.ConnectionEvent(r.request_id,'result','plan_ready',((REF,'plan_ready'),),REF))
        self.assertTrue(c.busy);self.assertFalse(c.worker_joined(r.request_id,joined=False));self.assertTrue(c.busy)
        self.assertTrue(c.worker_joined(r.request_id,joined=True));self.assertFalse(c.busy)

    def test_account_switch_and_signout_cannot_dispatch_before_join(self):
        c=self.ready()
        for action in ('select','sign_out'):
            before=len(self.requests);r=c.request(action,REF,confirmed=True)
            self.assertEqual(len(self.requests),before);self.assertEqual(self.quiesce[-1],r)
            c.acknowledge_quiescence(r.request_id,joined=True);self.assertEqual(len(self.requests),before+1)
            c.apply_event(self.ui.ConnectionEvent(r.request_id,'result','disconnected',revocation_confirmed=False))
            c.worker_joined(r.request_id,joined=True)
        self.assertIn('未獲確認',c.message)

    def test_cancel_close_and_worker_death_preserve_unknown(self):
        from PySide6.QtGui import QCloseEvent
        c=self.ready();r=c.request('begin',confirmed=True);c.acknowledge_quiescence(r.request_id,joined=True)
        event=QCloseEvent();self.panel.closeEvent(event);self.assertFalse(event.isAccepted());self.assertEqual(self.cancel,[r.request_id])
        self.assertFalse(c.apply_event(self.ui.ConnectionEvent(r.request_id,'result','plan_ready',((REF,'plan_ready'),),REF)))
        c.worker_joined(r.request_id,joined=True)
        self.assertEqual(c.state,'unknown');self.assertIn('不自動重送',c.message);self.assertFalse(c.usage_known)
        event=QCloseEvent();self.panel.closeEvent(event);self.assertTrue(event.isAccepted())

    def test_official_url_validation_rejects_injected_destination_secrets_and_duplicate(self):
        good=authorization_url();self.assertEqual(self.ui.official_authorization_url(good),good)
        invalid=[good.replace('auth.openai.com','evil.invalid'),good+'#token',good+'&state='+'x'*43,
            authorization_url(access_token='fixture-secret'),authorization_url(redirect_uri='https://evil.invalid/auth/callback'),
            authorization_url(scope='openid'),authorization_url(resource='https://evil.invalid'),authorization_url(code_challenge_method='plain')]
        for url in invalid:
            with self.subTest(url=url[:60]),self.assertRaises(ValueError):self.ui.official_authorization_url(url)

    def test_usage_unknown_global_pending_and_other_account_cannot_reset(self):
        c=self.ready();c.set_usage(REF,[{'sequence':1,'status':'reserved_unknown'}],account_status={'state':'reserved_unknown','pending':True})
        self.assertEqual(c.unknown_count,1);self.assertIn('待核對：1',self.panel.usage.text())
        self.assertFalse(self.panel.buttons['clear_pause'].isEnabled())
        with self.assertRaises(ValueError):c.set_usage(OTHER,[],account_status={'state':'ready','pending':False})
        self.assertEqual(c.unknown_count,1)
        self.panel.consent.setChecked(True);self.panel._act('clear_pause');self.assertFalse(c.busy)
        c.set_usage(REF,[],account_status={'state':'reserved_unknown','pending':True})
        self.assertFalse(self.panel.buttons['clear_pause'].isEnabled())
        self.panel.consent.setChecked(True);self.panel._act('clear_pause');self.assertFalse(c.busy)

    def test_subscription_options_require_exact_account_discovered_model_and_known_usage(self):
        c=self.ready();r=c.request('models',REF,confirmed=True);c.acknowledge_quiescence(r.request_id,joined=True)
        c.apply_event(self.ui.ConnectionEvent(r.request_id,'result','plan_ready',((REF,'plan_ready'),),REF,models=('official-fixture-model',)))
        c.worker_joined(r.request_id,joined=True);self.panel.max_calls.setValue(2)
        with self.assertRaises(ValueError):self.panel.build_plan_options()
        c.set_usage(REF,[],account_status={'state':'ready','pending':False})
        self.panel.consent.setChecked(True);options=self.panel.build_plan_options()
        self.assertEqual(options.mode,'chatgpt_plan');self.assertFalse(options.paid_api_fallback);self.assertEqual(options.registration,REF)
        self.assertFalse(self.panel.consent.isChecked())
        c.usage_known=False;self.panel.consent.setChecked(True)
        with self.assertRaises(ValueError):self.panel.build_plan_options()

    def test_discovery_needs_account_barrier_but_not_campaign_receipts(self):
        c=self.ready();c.invalidate_campaign_usage()
        c.set_account_status(REF,{'state':'ready','pending':False})
        r=c.request('models',REF,confirmed=True)
        self.assertEqual(r.action,'models')
        self.assertFalse(c.usage_known);self.assertIsNone(c.reserved_count)
        with self.assertRaises(ValueError):self.panel.build_plan_options()

    def test_pending_account_blocks_discovery_and_execution(self):
        c=self.ready();c.set_account_status(REF,{'state':'reserved_unknown','pending':True})
        with self.assertRaises(ValueError):c.request('models',REF,confirmed=True)
        with self.assertRaises(ValueError):self.panel.build_plan_options()

    def test_late_account_barrier_rejected(self):
        c=self.ready();c.account_status_known=False
        with self.assertRaises(ValueError):c.set_account_status(OTHER,{'state':'ready','pending':False})
        self.assertFalse(c.account_status_known)

    def test_preferences_exclude_account_consent_endpoint_or_tokens(self):
        self.ready();self.panel.consent.setChecked(True);self.panel.max_calls.setValue(3)
        value=self.panel.preferences();self.assertEqual(set(value),{'version','max_calls','timeout_seconds'})
        self.panel.restore_preferences(value);self.assertFalse(self.panel.consent.isChecked())
        for extra in ('api_key','registration','network_opt_in'):
            with self.assertRaises(ValueError):self.panel.restore_preferences({**value,extra:'fixture'})

    def test_worker_begin_is_one_session_no_implicit_initialize_and_transient_url(self):
        session=FixtureSession();events=[]
        request=self.ui.ConnectionRequest(1,'begin',user_confirmed=True)
        result=self.ui.run_connection_request(request,bootstrap='/fixture',emit=events.append,cancelled=lambda:False,session_factory=lambda:session)
        self.assertEqual(session.calls,['begin','poll']);self.assertEqual(result.state,'plan_ready')
        self.assertEqual(events[0].kind,'authorization');self.assertIsNone(result.authorization_url)
        self.assertNotIn('s'*43,repr(events[0]));self.assertEqual(result.active_registration,REF)

    def test_worker_sanitizes_failures_and_bounds_timeout(self):
        class Failure(FixtureSession):
            def begin(self,registration=None):raise RuntimeError('Bearer FIXTURE_SECRET_RAW_TOKEN')
        result=self.ui.run_connection_request(self.ui.ConnectionRequest(1,'begin',user_confirmed=True),bootstrap='/fixture',emit=lambda x:None,cancelled=lambda:False,session_factory=Failure)
        self.assertEqual(result.error_code,'operation_failed');self.assertNotIn('SECRET',repr(result))
        class Waiting(FixtureSession):
            def poll(self,timeout):pass
        times=iter((0,2));session=Waiting()
        result=self.ui.run_connection_request(self.ui.ConnectionRequest(2,'begin',max_runtime_seconds=1,user_confirmed=True),bootstrap='/fixture',emit=lambda x:None,cancelled=lambda:False,session_factory=lambda:session,clock=lambda:next(times))
        self.assertEqual(result.state,'timeout');self.assertIn('cancel',session.calls)

    def test_fixture_managed_process_handoff_and_join_without_real_auth(self):
        import multiprocessing
        context=multiprocessing.get_context('spawn');queue=context.Queue();cancel=context.Event()
        c=self.controller;c.set_host_available(True);request=c.request('begin',confirmed=True)
        c.acknowledge_quiescence(request.request_id,joined=True)
        process=context.Process(target=fixture_process,args=(request,queue,cancel))
        process.start()
        try:
            authorization=queue.get(timeout=10);result=queue.get(timeout=10)
            self.assertEqual(authorization.kind,'authorization');c.apply_event(authorization);c.apply_event(result)
            self.assertTrue(c.busy);process.join(timeout=10);self.assertFalse(process.is_alive())
            c.worker_joined(request.request_id,joined=True);self.assertFalse(c.busy)
            self.assertEqual(c.state,'plan_ready');self.assertEqual(self.browser,[])
        finally:
            if process.is_alive():process.terminate();process.join(timeout=5)
            queue.close();queue.join_thread()

    def test_fixture_unresponsive_process_requires_termination_join_and_unknown(self):
        import multiprocessing
        context=multiprocessing.get_context('spawn');queue=context.Queue();cancel=context.Event()
        c=self.controller;c.set_host_available(True);request=c.request('begin',confirmed=True)
        c.acknowledge_quiescence(request.request_id,joined=True)
        process=context.Process(target=fixture_process,args=(request,queue,cancel,True));process.start()
        try:
            process.join(timeout=.2);self.assertTrue(process.is_alive())
            c.cancel();self.assertTrue(c.busy);self.assertFalse(c.worker_joined(request.request_id,joined=False))
            process.terminate();process.join(timeout=5);self.assertFalse(process.is_alive())
            c.worker_joined(request.request_id,joined=True,terminal_received=False)
            self.assertEqual(c.state,'unknown');self.assertFalse(c.usage_known)
            self.assertIn('不自動重送',c.message)
        finally:
            if process.is_alive():process.terminate();process.join(timeout=5)
            queue.close();queue.join_thread()

    def test_identity_only_and_paused_accounts_cannot_discover_or_generate(self):
        c=self.ready();c.state='identity_only'
        with self.assertRaises(ValueError):c.request('models',REF,confirmed=True)
        c.state='plan_ready';c.set_usage(REF,[],account_status={'state':'quota_paused','pending':False})
        with self.assertRaises(ValueError):c.request('models',REF,confirmed=True)
        self.assertEqual(self.panel.account.currentData(),REF)
        self.assertNotIn(REF,self.panel.account.currentText())
        self.assertTrue(self.panel.buttons['clear_pause'].isEnabled())
        self.panel.consent.setChecked(True);self.panel._act('clear_pause')
        self.assertEqual(self.quiesce[-1].action,'clear_pause');self.assertEqual(self.requests[-1].action,'list')

    def test_finished_transport_failure_stays_unresolved_without_clear_or_refund(self):
        c=self.ready()
        c.set_usage(REF,[{'sequence':1,'status':'failed_or_interrupted'}],account_status={'state':'blocked','pending':False})
        self.assertEqual(c.reserved_count,1);self.assertEqual(c.unknown_count,1)
        self.assertFalse(self.panel.buttons['clear_pause'].isEnabled())
        with self.assertRaises(ValueError):c.request('clear_pause',REF,confirmed=True)
        self.assertFalse(c.busy)

    def test_existing_connection_reauthorization_preserves_opaque_reference(self):
        c=self.ready();self.panel.consent.setChecked(True);self.panel._act('reauthorize')
        self.assertEqual(self.quiesce[-1].action,'begin');self.assertEqual(self.quiesce[-1].registration,REF)
        self.assertFalse(self.panel.consent.isChecked())

    def test_worker_list_uses_public_verified_restart_summary_only(self):
        session=FixtureSession();session.state='plan_ready';session.active_registration=REF;session.rows=[{'registration':REF,'state':'plan_ready'}]
        result=self.ui.run_connection_request(self.ui.ConnectionRequest(1,'list'),bootstrap='/fixture',emit=lambda x:None,cancelled=lambda:False,session_factory=lambda:session)
        self.assertEqual(result.active_registration,REF);self.assertEqual(result.state,'plan_ready');self.assertEqual(session.calls,[])

if __name__=='__main__':unittest.main()

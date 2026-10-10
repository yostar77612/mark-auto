"""Offline fixture host integration only; no real grant or subscription evidence."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from dataclasses import asdict
from tests import test_desktop_ui as support
REF='a'*32

@unittest.skipUnless(support.HAS_QT,'Pinned Qt needed')
class ChatGPTHostTests(unittest.TestCase):
    setUpClass=support.NativeDesktopTests.__dict__['setUpClass']
    setUp=support.NativeDesktopTests.setUp
    cleanup_window=support.NativeDesktopTests.cleanup_window

    def test_startup_inert_and_legacy_provider_indices(self):
        w=self.window
        self.assertFalse(self.jobs.active)
        self.assertEqual(w.chatgpt_controller.state,'unknown')
        self.assertFalse(w.chatgpt_controller.account_status_known)
        self.assertEqual([w.provider_mode.itemData(i) for i in range(4)],['fixture','compatible','manual','chatgpt_plan'])
        self.assertFalse(w.chatgpt_panel.consent.isChecked())

    def test_explicit_local_status_runs_existing_manager_without_network(self):
        w=self.window
        with patch.object(self.jobs,'start',return_value='fixture-job') as start:
            request=w.chatgpt_controller.request('list')
        self.assertEqual(start.call_args.args,('ui_chatgpt_auth',{'request':request.payload()}))
        self.assertIs(w.jobs,self.jobs)
        from desktop_chatgpt_ui import ConnectionEvent
        result=asdict(ConnectionEvent(request.request_id,'result','host_initialization_required'))
        self.assertTrue(w._chatgpt_event({'job_id':'fixture-job','type':'result','result':{'auth_event':result}}))
        self.assertFalse(w.chatgpt_controller.busy)
        self.assertFalse(self.jobs.active)
        self.assertNotIn('auth_event',w.summary.toPlainText())

    def test_switch_requires_actual_stop_join_before_dispatch(self):
        w=self.window; trace=[]
        with patch.object(w,'_quiesce_and_recover',side_effect=lambda:trace.append('joined')), patch.object(w,'poll_jobs'), patch.object(w,'start_job',side_effect=lambda *a:trace.append('dispatch')):
            r=w.chatgpt_controller.request('select',REF,confirmed=True)
        self.assertEqual(trace,['joined','dispatch'])
        w.chatgpt_controller.worker_joined(r.request_id,joined=True,terminal_received=False)

    def test_failed_join_never_dispatches_switch(self):
        w=self.window
        with patch.object(w,'_quiesce_and_recover',side_effect=ValueError('fixture')),patch.object(w,'start_job') as start:
            r=w.chatgpt_controller.request('sign_out',REF,confirmed=True)
        start.assert_not_called();self.assertTrue(w.chatgpt_controller.busy)
        w.chatgpt_controller.worker_joined(r.request_id,joined=True,terminal_received=False)

    def test_worker_failure_clears_url_and_marks_unknown(self):
        w=self.window
        with patch.object(self.jobs,'start',return_value='fixture-job'):
            r=w.chatgpt_controller.request('list')
        w._chatgpt_event({'job_id':'fixture-job','type':'error','message':'fixture'})
        self.assertFalse(w.chatgpt_controller.busy);self.assertEqual(w.chatgpt_controller.state,'unknown')
        self.assertFalse(w.chatgpt_controller.usage_known)

    def test_account_read_never_invents_campaign_zero_or_accepts_other_account(self):
        w=self.window;c=w.chatgpt_controller;c.active_registration=REF;c.state='plan_ready';w.last_operation='ui_chatgpt_usage'
        w._chatgpt_event({'type':'result','result':{'registration':REF,'account_status':{'state':'ready','pending':False}}})
        self.assertTrue(c.account_status_known);self.assertFalse(c.usage_known);self.assertIsNone(c.reserved_count)
        w._chatgpt_event({'type':'result','result':{'registration':'b'*32,'account_status':{'state':'blocked','pending':True}}})
        self.assertFalse(c.account_pending)

    def test_unauthorized_plan_never_reaches_campaign_worker(self):
        w=self.window;w.provider_mode.setCurrentIndex(3)
        with patch.object(w,'start_job') as start:
            with self.assertRaises(ValueError):w.run_campaign()
        start.assert_not_called()

    def test_runtime_rejects_unbounded_auth_before_spawn(self):
        from quantlab.desktop_runtime import RuntimeSafetyError
        with patch('quantlab.desktop_runtime.mp.get_context') as context:
            with self.assertRaises(RuntimeSafetyError):self.jobs.start('ui_chatgpt_auth',{'request':{'request_id':1}})
        context.assert_not_called()

    def test_worker_local_status_dispatch_has_no_implicit_initialization(self):
        from desktop_ui import execute_ui_operation
        from desktop_chatgpt_ui import ConnectionRequest,ConnectionEvent
        request=ConnectionRequest(1,'list')
        with patch('desktop_chatgpt_ui.run_connection_request',return_value=ConnectionEvent(1,'result','host_initialization_required')) as run:
            result=execute_ui_operation('ui_chatgpt_auth',{'request':request.payload()},self.paths)
        self.assertEqual(result['auth_event']['state'],'host_initialization_required')
        self.assertEqual(run.call_args.args[0].action,'list')

    def test_private_authorization_progress_is_not_persisted(self):
        import json
        from unittest.mock import Mock
        from desktop_chatgpt_ui import ConnectionEvent
        from tests.test_desktop_chatgpt_ui import authorization_url
        manager=self.jobs;manager.job_id='fixture';manager._operation='ui_chatgpt_auth';manager._auth_request_id=1
        manager.process=Mock(pid=None);manager.process.is_alive.return_value=True
        manager.receiver=Mock();manager.receiver.poll.side_effect=[True,False]
        url=authorization_url()
        manager.receiver.recv_bytes.return_value=json.dumps({'job_id':'fixture','type':'auth_progress','auth_event':asdict(ConnectionEvent(1,'authorization','authorizing',authorization_url=url))}).encode()
        with patch.object(manager,'_log') as log:
            events=manager.poll()
        log.assert_not_called();self.assertEqual(events[0]['auth_event']['authorization_url'],url)
        manager.cancel()

    def test_parent_deadline_stops_and_joins_before_unknown_result(self):
        from unittest.mock import Mock
        manager=self.jobs;manager.job_id='fixture';manager._operation='ui_chatgpt_auth';manager._deadline=0
        proc=Mock(pid=123);proc.is_alive.side_effect=[True,True,False,False]
        manager.process=proc;manager.receiver=Mock();manager.receiver.poll.return_value=False
        with patch('quantlab.desktop_runtime.os.killpg') as kill:
            events=manager.poll()
        kill.assert_called_once();proc.join.assert_called();proc.close.assert_called_once()
        self.assertFalse(manager.active)
        self.assertEqual(events[-1]['error_type'],'DeadlineExceeded')
        self.assertFalse(any(e['type']=='cancelled' for e in events))

    def test_plan_binding_stable_and_requires_current_usage_identity(self):
        from desktop_ui import plan_provider,execute_ui_operation,_dataset,demo_config
        from quantlab.research import demo_campaign_config
        from quantlab.core import ValidationError
        execute_ui_operation('ui_demo',{},self.paths)
        data=_dataset(self.paths.state,{})
        config=demo_campaign_config(data,demo_config())
        options=dict(mode='chatgpt_plan',registration=REF,model='fixture-model',max_calls=2,timeout_seconds=30,network_opt_in=False,included_usage_policy_confirmed=False,paid_api_fallback=False)
        p,binding=plan_provider(self.paths,data,config,options,for_usage=True)
        self.assertEqual(binding,plan_provider(self.paths,data,config,options,for_usage=True)[1])
        self.assertEqual(p.path.parent,(self.paths.bootstrap or self.paths.root)/'control-v1')
        with self.assertRaises(ValidationError):plan_provider(self.paths,data,config,{**options,'network_opt_in':True,'included_usage_policy_confirmed':True})
        p2,b2=plan_provider(self.paths,data,config,{**options,'expected_binding':binding,'network_opt_in':True,'included_usage_policy_confirmed':True})
        self.assertEqual(p2.path,p.path);self.assertEqual(binding,b2)
        with self.assertRaises(ValidationError):plan_provider(self.paths,data,config,{**options,'model':'changed-model','expected_binding':binding,'network_opt_in':True,'included_usage_policy_confirmed':True})
    def test_sleep_freeze_clears_transient_authorization_and_consent(self):
        from desktop_chatgpt_ui import ConnectionEvent
        from tests.test_desktop_chatgpt_ui import authorization_url
        w=self.window
        with patch.object(w,'start_job',return_value='fixture'):
            r=w.chatgpt_controller.request('begin',confirmed=True)
        w.chatgpt_controller.apply_event(ConnectionEvent(r.request_id,'authorization','authorizing',authorization_url=authorization_url()))
        w.chatgpt_panel.consent.setChecked(True)
        w.freeze_paper('fixture sleep')
        self.assertFalse(w.chatgpt_controller.busy)
        self.assertIsNone(w.chatgpt_controller._authorization_url)
        self.assertFalse(w.chatgpt_panel.consent.isChecked())
        self.assertFalse(w.chatgpt_controller.account_status_known)

    def test_shutdown_clears_transient_authorization(self):
        from desktop_chatgpt_ui import ConnectionEvent
        from tests.test_desktop_chatgpt_ui import authorization_url
        w=self.window
        with patch.object(w,'start_job',return_value='fixture'):
            r=w.chatgpt_controller.request('begin',confirmed=True)
        w.chatgpt_controller.apply_event(ConnectionEvent(r.request_id,'authorization','authorizing',authorization_url=authorization_url()))
        w.close()
        self.assertFalse(w.chatgpt_controller.busy)
        self.assertIsNone(w.chatgpt_controller._authorization_url)
    def test_model_worker_rechecks_durable_account_before_network(self):
        from desktop_chatgpt_ui import run_connection_request,ConnectionRequest
        from tests.test_desktop_chatgpt_ui import FixtureSession
        session=FixtureSession()
        with patch('desktop_chatgpt_provider.read_account_status',return_value={'state':'reserved_unknown','pending':True}),patch('desktop_chatgpt_provider.discover_models') as discover:
            result=run_connection_request(ConnectionRequest(1,'models',REF,120,True),bootstrap=str(self.paths.root),emit=lambda e:None,cancelled=lambda:False,session_factory=lambda:session)
        discover.assert_not_called();self.assertEqual(result.kind,'error');self.assertEqual(result.error_code,'account_paused')

    def test_reconciliation_requires_same_manager_subtree_proof(self):
        from quantlab.desktop_runtime import RuntimeSafetyError
        from desktop_ui import execute_ui_operation
        from quantlab.core import ValidationError
        with self.assertRaises(RuntimeSafetyError):self.jobs.start('ui_chatgpt_reconcile',{'stopped_job_id':'guessed'})
        with self.assertRaises(ValidationError):execute_ui_operation('ui_chatgpt_reconcile',{},self.paths)

    def test_unknown_descendant_observation_retains_busy_slot(self):
        from unittest.mock import Mock
        from quantlab.desktop_runtime import RuntimeSafetyError
        m=self.jobs;m.process=Mock(pid=None);m.receiver=Mock();m._requires_tree_quiescence=True
        with patch.object(m,'_join_descendants',side_effect=RuntimeSafetyError('fixture unknown')):
            with self.assertRaises(RuntimeSafetyError):m.cancel()
        self.assertTrue(m.active)
        with patch.object(m,'_join_descendants'):m.cancel()

    def test_plan_campaign_uses_exact_provider_and_local_reconcile_never_enables_network(self):
        from desktop_ui import plan_provider,execute_ui_operation,_dataset,demo_config
        from quantlab.research import demo_campaign_config
        from quantlab.core import to_dict
        execute_ui_operation('ui_demo',{},self.paths)
        data=_dataset(self.paths.state,{});config=demo_campaign_config(data,demo_config())
        options=dict(mode='chatgpt_plan',registration=REF,model='fixture-model',max_calls=2,timeout_seconds=30,network_opt_in=False,included_usage_policy_confirmed=False,paid_api_fallback=False)
        _,binding=plan_provider(self.paths,data,config,options,for_usage=True)
        active={**options,'network_opt_in':True,'included_usage_policy_confirmed':True,'expected_binding':binding}
        with patch('quantlab.research.run_campaign',return_value={'status':'fixture'}) as run:
            execute_ui_operation('ui_campaign',{'config':to_dict(config),'provider':active},self.paths)
        generator=run.call_args.kwargs['generator']
        self.assertEqual(generator.mode,'chatgpt_plan');self.assertTrue(generator.network_opt_in)
        with patch('quantlab.research.reconcile_interrupted_campaign',return_value={'status':'blocked_interrupted'}) as reconcile:
            result=execute_ui_operation('ui_chatgpt_reconcile',{'config':to_dict(config),'provider':options,'binding':binding,'stopped_job_id':'fixture'},self.paths,descendants_stopped=True)
        local=reconcile.call_args.kwargs['generator']
        self.assertFalse(local.network_opt_in);self.assertFalse(local.included_usage_policy_confirmed)
        self.assertEqual(local.path,generator.path);self.assertTrue(reconcile.call_args.kwargs['descendants_stopped'])
        with patch('desktop_chatgpt_provider.implementation_provenance',return_value={'fixture_only':True}):
            self.assertEqual(local.provider_descriptor(),generator.provider_descriptor())
        self.assertEqual(reconcile.call_args.kwargs['output_dir'],run.call_args.kwargs['output_dir'])
        self.assertEqual(result['binding'],binding)

    def test_close_runs_local_reconciliation_from_immutable_launch(self):
        from unittest.mock import Mock
        w=self.window
        launch={'config':{'fixture':'original'},'provider':{'network_opt_in':False},'binding':'original','stopped_job_id':'old-job'}
        w._subscription_campaign=True;w._plan_launch=launch
        event=Mock()
        with patch.object(w,'start_job',return_value='local-reconcile') as start:
            w.closeEvent(event)
        start.assert_called_once_with('ui_chatgpt_reconcile',launch)
        event.ignore.assert_called_once();event.accept.assert_not_called()
        self.assertTrue(w._close_after_reconcile)
        w._close_after_reconcile=False


    def test_repeated_campaign_click_cannot_relabel_running_subscription(self):
        w=self.window;w._subscription_campaign=True
        with patch.object(w,'start_job',side_effect=ValueError('fixture busy')):
            with self.assertRaises(ValueError):w.run_campaign()
        self.assertTrue(w._subscription_campaign)
        w._subscription_campaign=False



def _fixture_stubborn_tree(sender,ready):
    """Offline adversarial child: ignores TERM; never performs network I/O."""
    import subprocess,sys,signal,time
    os.setsid()
    child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(60)'],stdout=subprocess.PIPE)
    child.stdout.readline()
    ready.send(child.pid);ready.close()
    while True:time.sleep(.1)

@unittest.skipUnless(os.name=='posix' and os.path.isdir('/proc'),'Linux process evidence')
class DescendantQuiescenceTests(unittest.TestCase):
    def test_term_ignoring_descendant_cannot_survive_cancel(self):
        import multiprocessing,tempfile,time
        from pathlib import Path
        from quantlab.desktop_runtime import AppPaths,JobManager
        with tempfile.TemporaryDirectory() as tmp:
            manager=JobManager(AppPaths(Path(tmp)/'app').ensure())
            context=multiprocessing.get_context('spawn')
            receiver,sender=context.Pipe(False);ready_receiver,ready_sender=context.Pipe(False)
            process=context.Process(target=_fixture_stubborn_tree,args=(sender,ready_sender));process.start();sender.close();ready_sender.close()
            self.assertTrue(ready_receiver.poll(10));child=ready_receiver.recv();ready_receiver.close()
            manager.process=process;manager.receiver=receiver;manager.job_id='fixture-tree';manager._operation='ui_chatgpt_auth';manager._requires_tree_quiescence=True
            try:
                manager.cancel();self.assertFalse(manager.active)
                path=Path('/proc')/str(child)/'stat'
                if path.exists():self.assertEqual(path.read_text().rsplit(')',1)[1].split()[0],'Z')
            finally:
                if manager.active:manager.cancel()

class WindowsTreeProtocolFixtureTests(unittest.TestCase):
    """Mock Win32 protocol, explicitly not native Windows execution evidence."""
    def test_keeps_job_handle_until_zero_active_processes(self):
        from unittest.mock import Mock
        from quantlab.desktop_runtime import _WindowsProcessTree
        tree=object.__new__(_WindowsProcessTree);tree.handle=123;tree.kernel=Mock()
        counts=iter((2,0))
        def query(handle,info_class,pointer,size,returned):
            pointer._obj.ActiveProcesses=next(counts);return True
        tree.kernel.QueryInformationJobObject.side_effect=query
        with patch('quantlab.desktop_runtime.time.sleep'):tree.stop_and_join()
        tree.kernel.TerminateJobObject.assert_called_once_with(123,1)
        self.assertEqual(tree.kernel.QueryInformationJobObject.call_count,2)
        tree.kernel.CloseHandle.assert_not_called();self.assertEqual(tree.handle,123)

    def test_unknown_win32_observation_preserves_handle(self):
        from unittest.mock import Mock
        from quantlab.desktop_runtime import _WindowsProcessTree,RuntimeSafetyError
        tree=object.__new__(_WindowsProcessTree);tree.handle=123;tree.kernel=Mock()
        tree.kernel.QueryInformationJobObject.return_value=False
        with self.assertRaises(RuntimeSafetyError):tree.stop_and_join()
        tree.kernel.CloseHandle.assert_not_called();self.assertEqual(tree.handle,123)

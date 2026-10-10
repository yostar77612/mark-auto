"""Offline local-AI UI/process contracts, not actual model or Windows evidence."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None


class RuntimeAdapterTests(unittest.TestCase):
    def test_nonwindows_refused_before_verifying_or_starting(self):
        import desktop_local_ai_runtime as runtime
        with patch.object(runtime.sys, 'platform', 'linux'), patch.object(runtime, 'verify_install') as verify, patch.object(runtime.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ValueError, 'Windows'): runtime.serve(None, Mock())
            verify.assert_not_called(); start.assert_not_called()

    def test_busy_port_never_adopts_or_stops_external_server(self):
        import desktop_local_ai_runtime as runtime
        from quantlab.local_ai import LocalAIError
        with patch.object(runtime, 'locked_runtime') as locked, patch.object(runtime.sys, 'platform', 'win32'), patch.object(runtime.platform, 'machine', return_value='AMD64'), patch.object(runtime, 'verify_install', return_value=(Path('/verified/llama-server.exe'), Path('/verified/model.gguf'))), patch.object(runtime, 'ensure_port_free', side_effect=LocalAIError('occupied')), patch.object(runtime.subprocess, 'Popen') as start:
            locked.return_value.__enter__.return_value=(Path('/verified/llama-server.exe'),Path('/verified/model.gguf'),Path('/trusted'))
            with self.assertRaises(LocalAIError): runtime.serve(None, Mock())
            start.assert_not_called()

    def test_launch_is_shell_free_owned_handle_and_private_dll_path(self):
        import desktop_local_ai_runtime as runtime
        process = Mock(); process.poll.return_value = None
        with patch.object(runtime, 'locked_runtime') as locked, patch.object(runtime.sys, 'platform', 'win32'), patch.object(runtime.platform, 'machine', return_value='AMD64'), patch.object(runtime, 'verify_install', return_value=(Path('/verified/runtime/llama-server.exe'), Path('/verified/model.gguf'))), patch.object(runtime, 'ensure_port_free'), patch.object(runtime, 'clear_inherited_dll_directory'), patch.object(runtime, 'system_directories', return_value=('C:\\Windows','C:\\Windows\\System32')), patch.object(runtime, 'process_creation_time', return_value=123), patch.object(runtime, 'health', side_effect=ValueError('inert failure')), patch.object(runtime.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), patch.object(runtime.subprocess, 'Popen', return_value=process) as start, patch.dict(os.environ, {'PATH':'/evil', 'PYTHONPATH':'/evil', 'LLAMA_ARG_MODEL':'evil', 'SYSTEMROOT':'C:\\Windows', 'MARKAUTO_LOCAL_AI_SESSION_TOKEN':'x'*43}):
            locked.return_value.__enter__.return_value=(Path('/verified/runtime/llama-server.exe'),Path('/verified/model.gguf'),Path('/trusted'))
            with self.assertRaises(ValueError): runtime.serve(None, Mock())
            args, options = start.call_args
            self.assertEqual(args[0][0], str(Path('/verified/runtime/llama-server.exe')))
            self.assertFalse(options['shell']); self.assertEqual(options['cwd'], str(Path('/verified/runtime')))
            self.assertNotIn('/evil', options['env']['PATH'])
            self.assertNotIn('LLAMA_ARG_MODEL', options['env'])
            self.assertNotIn('PYTHONPATH', options['env'])
            self.assertEqual(options['env']['LLAMA_API_KEY'], 'x'*43)
            self.assertNotIn('x'*43, repr(args[0]))
            self.assertIn('127.0.0.1', args[0]); self.assertIn('18765', args[0])
            process.terminate.assert_called_once(); process.wait.assert_called_once_with(timeout=5)

    def test_local_operations_require_explicit_bounded_payload(self):
        from quantlab.desktop_runtime import AppPaths, JobManager, RuntimeSafetyError
        with tempfile.TemporaryDirectory() as directory:
            manager = JobManager(AppPaths(Path(directory)))
            for payload in ({}, {'action':'serve'}, {'action':'serve','consent':False},
                            {'action':'serve','consent':True,'executable':'evil'}, {'action':'shell','consent':True}):
                with self.assertRaises(RuntimeSafetyError): manager.start('ui_local_ai', payload)
                self.assertFalse(manager.active)

    def test_packaged_manifest_digest_and_dependencies(self):
        from quantlab.local_ai import manifest
        spec = manifest()
        self.assertEqual(set(spec['support_dlls']), {'msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll'})
        self.assertEqual(len(spec['runtime_members']), 51)
        self.assertEqual(spec['model']['bytes'],1117320736)


@unittest.skipUnless(HAS_QT, 'Qt required')
class LocalPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore, BackupManager
        from desktop_ui import MainWindow
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(Path(self.temp.name)).ensure()
        self.jobs = JobManager(self.paths)
        self.window = MainWindow(self.paths, self.jobs, SettingsStore(self.paths.state/'settings.json'), BackupManager(self.paths,self.jobs))
        self.panel = self.window.local_ai_panel
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.panel.close_workers(); self.jobs.close(); self.window.close(); self.app.processEvents()

    def test_open_is_inert_and_profile_does_not_overwrite_generic_settings(self):
        self.assertFalse(self.panel.server.active); self.assertFalse(self.panel.task.active)
        self.assertFalse(self.panel.ready); self.assertFalse(self.panel.consent.isChecked())
        self.window.ai_endpoint.setText('https://example.test/v1/chat/completions')
        self.window.ai_model.setText('other-model')
        self.panel.select()
        self.assertEqual(self.window.provider_mode.currentData(),'local')
        self.assertEqual(self.window.ai_model.text(),'other-model')
        self.assertEqual(self.window.ai_endpoint.text(),'https://example.test/v1/chat/completions')
        self.assertFalse((self.paths.cache/'local-ai').exists())

    def test_launch_only_after_explicit_button_and_repeat_start_ignored(self):
        fake = Mock(active=False); fake.start.return_value = 'owned-server'
        with patch.object(self.panel,'server',fake):
            self.panel.start()
            fake.start.assert_called_once_with('ui_local_ai', {'action':'serve','consent':True})
            fake.active=True
            self.panel.start()
            self.assertEqual(fake.start.call_count,1)

    def test_close_and_emergency_stop_both_local_managers(self):
        server=Mock(active=False); task=Mock(active=False)
        with patch.object(self.panel,'server',server),patch.object(self.panel,'task',task):
            self.panel.ready=True; self.panel.consent.setChecked(True)
            self.window.freeze_paper('test')
            server.close.assert_called_once(); task.close.assert_called_once()
            self.assertFalse(self.panel.ready); self.assertFalse(self.panel.consent.isChecked())
            self.assertTrue(self.panel.timer.isActive())

    def test_local_server_does_not_occupy_research_manager(self):
        server=Mock(active=True); task=Mock(active=False)
        with patch.object(self.panel,'server',server),patch.object(self.panel,'task',task),patch.object(self.jobs,'start',return_value='research') as start:
            self.window.start_job('ui_demo', {'bars':240})
            start.assert_called_once_with('ui_demo', {'bars':240})
            server.close.assert_not_called()

    def test_setup_probe_prevents_parallel_main_job(self):
        from quantlab.core import ValidationError
        with patch.object(self.panel,'task',Mock(active=True)),patch.object(self.jobs,'start') as start:
            with self.assertRaises(ValidationError):self.window.start_job('ui_demo', {'bars':240})
            start.assert_not_called()

    def test_backup_workspace_blocked_while_local_server_active(self):
        from quantlab.core import ValidationError
        with patch.object(self.panel,'server',Mock(active=True)):
            with self.assertRaises(ValidationError):self.window.backup(False)
            with self.assertRaises(ValidationError):self.window.configure_workspace()

    def test_cancel_setup_confirms_both_owned_workers_stopped(self):
        server=Mock(active=True); task=Mock(active=True)
        with patch.object(self.panel,'server',server),patch.object(self.panel,'task',task):
            self.panel.stop()
            server.close.assert_called_once(); task.close.assert_called_once()
            self.assertFalse(self.panel.ready)

    def test_stale_server_events_cannot_restore_readiness(self):
        server=Mock(active=False); server.poll.return_value=[{'job_id':'old','type':'progress','local_ai_ready':True}]
        with patch.object(self.panel,'server',server):
            self.panel.server_job='new'; self.panel.poll()
            self.assertFalse(self.panel.ready)

    def test_failed_stop_does_not_claim_confirmed_cleanup(self):
        server=Mock(active=True); server.close.side_effect=RuntimeError('not stopped')
        with patch.object(self.panel,'server',server):
            self.panel.safe(self.panel.stop)
            self.assertNotIn('已停止並確認',self.panel.status.text())
            self.assertFalse(self.panel.ready)

    def test_logging_preference_covers_all_three_managers(self):
        self.window.persist_logs.setChecked(False)
        self.window.save_settings()
        self.assertFalse(self.jobs.logging_enabled)
        self.assertFalse(self.panel.server.logging_enabled)
        self.assertFalse(self.panel.task.logging_enabled)
        self.panel.server.logging_enabled=True;self.panel.task.logging_enabled=True
        self.window.load_settings()
        self.assertFalse(self.panel.server.logging_enabled)
        self.assertFalse(self.panel.task.logging_enabled)

    def test_download_decline_is_inert(self):
        from PySide6.QtWidgets import QMessageBox
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No),patch.object(self.panel.task,'start') as start:
            self.panel.download();start.assert_not_called()

class NativeSmokeBoundaryTests(unittest.TestCase):
    def test_entry_requires_all_explicit_paths(self):
        import desktop
        with self.assertRaises(SystemExit) as result:
            desktop.main(['--local-ai-smoke', '/tmp/report.json'])
        self.assertEqual(result.exception.code, 2)

    @unittest.skipUnless(HAS_QT, 'Qt required')
    def test_nonwindows_cannot_claim_native_model_pass(self):
        import desktop_local_ai_smoke as smoke
        import json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            report=root/'result.json'
            with patch.object(smoke.sys,'platform','linux'):
                self.assertEqual(smoke.run(report,root/'runtime.zip',root/'model.gguf',root/'state'),1)
            result=json.loads(report.read_text())
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['model_calls'],0)
            self.assertEqual(result['real_model_status'],'not_verified')
            self.assertFalse((root/'state').exists())

    def test_static_gate_keeps_other_subprocess_forbidden(self):
        from tools.quality_gate import python_findings
        self.assertTrue(python_findings('import subprocess\n','quantlab/other.py',research=True))
        self.assertTrue(python_findings('import subprocess\nsubprocess.Popen([],shell=True)\n','desktop_local_ai_runtime.py',desktop=True))
        self.assertTrue(python_findings('import subprocess\nsubprocess.run([])\n','desktop_local_ai_runtime.py',desktop=True))

class WindowsLockedRuntimeTests(unittest.TestCase):
    def exercise(self, defect=None):
        import ctypes
        from ctypes import wintypes
        import desktop_local_ai_runtime as runtime
        from quantlab.desktop_runtime import AppPaths
        from quantlab.local_ai import LocalAIError, PROFILE
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        paths=AppPaths(Path(temp.name))
        root=paths.root/'cache/local-ai'/PROFILE
        server=root/'runtime/llama-server.exe';model=root/'model.gguf'
        spec={'runtime_members':{'llama-server.exe':{}},'model':{'filename':'model.gguf'},
              'licenses':{'LICENSE.txt':{}},'support_dlls':{'msvcp140.dll':{}}}
        opened=[];closed=[];by_handle={};verified=[]
        base=1<<40
        def create(path,access,sharing,security,disposition,flags,template):
            is_dir=bool(flags & 0x02000000)
            if defect=='invalid' and not is_dir:return ctypes.c_void_p(-1).value
            handle=base+len(opened)+1
            opened.append((handle,Path(path),access,sharing,flags));by_handle[handle]=is_dir
            return handle
        def information(handle,pointer):
            info=pointer._obj
            info.attributes=0x10 if by_handle[handle] else 0
            info.links=1
            if not by_handle[handle]:
                if defect=='reparse':info.attributes|=0x400
                if defect=='hardlink':info.links=2
                if defect=='information':return 0
            return 1
        kernel=Mock();kernel.CreateFileW.side_effect=create
        kernel.GetFileInformationByHandle.side_effect=information
        kernel.CloseHandle.side_effect=lambda h:closed.append(h)
        def verify(_):
            verified.append(len(opened))
            if len(verified)>1:
                self.assertEqual(sum(not by_handle[h] for h in by_handle),4)
                self.assertFalse(closed)
                if defect=='rehash':raise LocalAIError('artifact')
            return server,model
        with patch.object(runtime,'manifest',return_value=spec),patch.object(runtime,'verify_install',side_effect=verify),patch.object(runtime,'safe_path'),patch.object(runtime.ctypes,'WinDLL',return_value=kernel,create=True),patch.object(runtime.subprocess,'Popen') as launch:
            if defect:
                with self.assertRaises(LocalAIError):
                    with runtime.locked_runtime(paths):self.fail('Unsafe lock yielded')
            else:
                with runtime.locked_runtime(paths) as actual:
                    self.assertEqual(actual,(server,model,server.parent))
                    self.assertFalse(closed)
                    self.assertEqual(kernel.CreateFileW.restype,wintypes.HANDLE)
                    for handle,path,access,sharing,flags in opened:
                        self.assertGreater(handle,2**32)
                        self.assertFalse(sharing & 4)  # no delete sharing
                        self.assertTrue(flags & 0x00200000)  # inspect reparse node
                        if by_handle[handle]:self.assertEqual(sharing,3)
                        else:self.assertEqual(sharing,1);self.assertEqual(access,0x80000000)
            launch.assert_not_called()
        self.assertEqual(closed,[row[0] for row in reversed(opened)])
        if defect in ('invalid','reparse','hardlink','information'):self.assertEqual(len(verified),1)
        return opened,verified

    def test_handles_pin_files_and_ancestry_until_context_exit(self):self.exercise()

    def test_failures_release_all_acquired_handles_without_launch(self):
        for defect in ('invalid','reparse','hardlink','information','rehash'):
            with self.subTest(defect=defect):self.exercise(defect)

    def test_loader_reset_must_succeed(self):
        import desktop_local_ai_runtime as runtime
        from quantlab.local_ai import LocalAIError
        kernel=Mock();kernel.SetDllDirectoryW.return_value=0
        with patch.object(runtime.ctypes,'WinDLL',return_value=kernel,create=True):
            with self.assertRaises(LocalAIError):runtime.clear_inherited_dll_directory()
            kernel.SetDllDirectoryW.assert_called_once_with(None)

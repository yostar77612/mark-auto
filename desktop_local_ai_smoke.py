"""Explicit once-only native/frozen local-AI technical validation, no market input.

Not invoked by startup or ordinary tests. Caller supplies exact downloaded pins
and a dedicated root outside real user state. The result never awards strategy,
clean-client, provider-general, holdout or investment acceptance.
"""
import json
import os
from pathlib import Path
import platform
import sys
import time


def run(report_path, runtime_archive, model_file, root):
    from quantlab.local_ai import (manifest, usage, verify_owner, safe_path, SESSION_TOKEN_ENV,
                                  MANIFEST_SHA256, PROFILE, loaded_support_modules, cache_root)
    from quantlab.desktop_runtime import AppPaths, SettingsStore, BackupManager, JobManager, atomic_write, _json_bytes
    from quantlab import __version__
    from PySide6.QtWidgets import QApplication
    from desktop_ui import MainWindow
    result = {'status':'failed', 'scope':'one actual local structured-output technical probe only',
        'version':__version__, 'frozen':getattr(sys,'frozen',False), 'platform':sys.platform,
        'os':platform.platform(), 'profile':PROFILE, 'manifest_sha256':MANIFEST_SHA256,
        'real_model_status':'not_verified', 'clean_windows_client_status':'not_verified',
        'external_api_spend':'0', 'paid_fallback':False, 'research_evaluations':0,
        'oos_or_holdout_access':False, 'model_calls':0, 'cleanup_verified':False, 'stages':[]}
    window = jobs = paths = None
    active_stage = None
    def begin_stage(name, cap):
        nonlocal active_stage
        active_stage={'stage':name,'cap_seconds':cap,'status':'running','started':time.monotonic()}
        result['stages'].append(active_stage)
    def finish_stage(status):
        nonlocal active_stage
        if active_stage is not None:
            active_stage['seconds']=round(time.monotonic()-active_stage.pop('started'),3)
            active_stage['status']=status
            active_stage=None
    try:
        if sys.platform != 'win32': raise ValueError('Native Windows required')
        for path in (report_path, runtime_archive, model_file, root): safe_path(Path(path))
        # Retain all prior evidence; never silently reset a successful/failed attempt.
        if Path(report_path).exists(): raise ValueError('Report already exists')
        if Path(root).exists() and any(Path(root).iterdir()): raise ValueError('Use a fresh dedicated validation root')
        paths = AppPaths(Path(root)).ensure()
        app = QApplication.instance() or QApplication(sys.argv[:1])
        jobs = JobManager(paths)
        window = MainWindow(paths,jobs,SettingsStore(paths.state/'settings.json'),BackupManager(paths,jobs))
        panel = window.local_ai_panel
        window.show(); window.navigation.setCurrentRow(6); app.processEvents()
        def wait(predicate, seconds):
            deadline=time.monotonic()+seconds
            while not predicate():
                app.processEvents(); panel.poll()
                if time.monotonic() >= deadline: raise TimeoutError('Bounded validation step expired')
                time.sleep(.02)
            app.processEvents(); panel.poll()
        panel.archive.setText(str(runtime_archive)); panel.model.setText(str(model_file))
        begin_stage('verified_setup',300)
        panel.install(); wait(lambda:not panel.task.active,300)
        if not panel.last_result or panel.last_result.get('status') != 'installed': raise ValueError('Pinned setup failed')
        finish_stage('passed')
        spec=manifest()
        result.update(runtime_sha256=spec['runtime']['sha256'],model_sha256=spec['model']['sha256'],
            runtime_members_verified=len(spec['runtime_members']), licenses_verified=len(spec['licenses']))
        begin_stage('owned_server_start',150)
        panel.start(); wait(lambda:panel.ready or not panel.server.active,150)
        if not panel.ready or not panel.owner: raise ValueError('Owned native server did not become ready')
        verify_owner(**{'pid':panel.owner['pid'],'created':panel.owner['created']})
        result['owned_server']=dict(panel.owner)
        result['application_vc_dependencies_verified']=len(spec['support_dlls'])
        finish_stage('passed')
        if usage(paths.controls)['calls'] != 0: raise ValueError('Probe already attempted')
        begin_stage('one_schema_probe',135)
        panel.launch_task({'action':'probe','consent':True,'owner':dict(panel.owner)})
        wait(lambda:not panel.task.active,135)
        result['model_calls']=usage(paths.controls)['calls']
        if (not panel.last_result or panel.last_result.get('status') != 'schema_probe_pass'
            or result['model_calls'] != 1): raise ValueError('Actual structured probe failed')
        finish_stage('passed')
        result['probe']=panel.last_result
        result['loaded_vc_runtime_modules']=loaded_support_modules(panel.owner['pid'],panel.owner['created'],cache_root(paths)/'runtime')
        # Report includes response/candidate hashes and permanent reservation, no raw prompt, secret or market data.
        screenshot = Path(report_path).with_suffix('.png')
        if screenshot.exists(): raise ValueError('Screenshot already exists')
        window.stack.currentWidget().ensureWidgetVisible(panel.status,0,30)
        app.processEvents()
        result['native_window_screenshot_saved']=window.grab().save(str(screenshot))
        if result['native_window_screenshot_saved'] is not True: raise ValueError('Native screenshot was not saved')
        result['status']='passed'
    except BaseException as exc:
        finish_stage('failed')
        result['error_type']=type(exc).__name__
    finally:
        if paths is not None:
            try: result['model_calls']=usage(paths.controls)['calls']
            except Exception: result['budget_status']='unavailable'
        try:
            if jobs is not None: jobs.close()
            if window is not None:
                window.local_ai_panel.close_workers()
                if window.local_ai_panel.server.active or window.local_ai_panel.task.active or jobs.active:
                    raise ValueError('Workers remain active')
                window.close()
            result['cleanup_verified']=True
        except BaseException as exc:
            result['status']='failed';result['cleanup_error_type']=type(exc).__name__
        os.environ.pop(SESSION_TOKEN_ENV,None)
        # Keep the immutable attempt data even if the caller chose an occupied report.
        if not Path(report_path).exists():
            safe_path(Path(report_path))
            atomic_write(Path(report_path),_json_bytes(result))
    return 0 if result['status']=='passed' and result['cleanup_verified'] else 1

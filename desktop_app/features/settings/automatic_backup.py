"""Small opt-in backup settings panel using the existing background job slot."""

from desktop_app.strings.catalog import ui_text
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QLineEdit, QPushButton, QFileDialog
from quantlab.automatic_backup import AutomaticBackup


class AutomaticBackupPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.scheduler = AutomaticBackup(window.paths)
        self.archive = self.job_id = None
        self.paused = False
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox(ui_text('automatic_backup.init.enable'))
        layout.addWidget(self.enabled)
        self.directory = QLineEdit()
        self.directory.setPlaceholderText(ui_text('automatic_backup.init.directory'))
        layout.addWidget(self.directory)
        browse = QPushButton(ui_text('automatic_backup.init.browse'))
        browse.clicked.connect(self.browse)
        layout.addWidget(browse)
        save = QPushButton(ui_text('automatic_backup.init.save'))
        save.setObjectName('save_automatic_backup')
        save.clicked.connect(self.save)
        layout.addWidget(save)
        note = QLabel(ui_text('automatic_backup.init.schedule_hint'))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        try:
            settings = self.scheduler.load()
            self.enabled.setChecked(settings['enabled'])
            self.directory.setText(settings['directory'])
            labels = {
                'never': ui_text('automatic_backup.init.never_attempted'),
                'attempted': ui_text('automatic_backup.init.last_unknown'),
                'success': ui_text('automatic_backup.init.last_success'),
                'error': ui_text('automatic_backup.init.last_failed'),
                'cancelled': ui_text('automatic_backup.init.last_cancelled'),
            }
            self.status.setText(labels[settings['last_status']])
        except Exception as exc:
            self.paused = True
            self.status.setText(ui_text('automatic_backup.init.suspended').format(str(exc)))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(60000)

    def browse(self):
        selected = QFileDialog.getExistingDirectory(self, ui_text('automatic_backup.browse.dialog_title'), self.directory.text())
        if selected:
            self.directory.setText(selected)

    def save(self):
        try:
            if self.archive is not None:
                self.status.setText(ui_text('automatic_backup.save.job_busy'))
                return
            self.scheduler.configure(enabled=self.enabled.isChecked(), directory=self.directory.text().strip())
            self.paused = False
            self.status.setText(ui_text('automatic_backup.save.saved') if self.enabled.isChecked() else ui_text('automatic_backup.save.disabled'))
        except Exception as exc:
            self.paused = True
            self.status.setText(ui_text('automatic_backup.save.save_failed').format(str(exc)))

    def tick(self):
        w = self.window
        if self.paused or self.archive is not None or getattr(w, '_closing', False):
            return
        busy = (
            w.jobs.active
            or getattr(getattr(w, 'chatgpt_panel', None), 'primary_sign_in_pending', False)
            or w.chatgpt_controller.busy
            or w._wf_pending_reconcile
            or w._pending_plan_reconcile
            or w._pending_usage_refresh
            or getattr(w, '_kill_pending', False)
        )
        if busy:
            if self.enabled.isChecked():
                self.status.setText(ui_text('automatic_backup.tick.waiting_idle'))
            return
        from quantlab.analysis_recovery import operation_guard, RecoveryError

        try:
            # Hold the shared admission lock through the claim and dispatch;
            # rejection before an attempt must not consume today's watermark.
            with operation_guard(w.paths, 'ui_backup_create'):
                payload = self.scheduler.claim_due(quiescent=True)
                if payload is None:
                    return
                self.archive = payload['path']
                self.job_id = w.start_job('ui_backup_create', payload)
                self.status.setText(ui_text('automatic_backup.tick.running'))
        except RecoveryError:
            if self.archive is not None:
                # A genuine attempted launch keeps the existing no-retry rule.
                try:
                    self.scheduler.complete(archive=self.archive, status='error')
                except Exception:
                    pass
                self.archive = self.job_id = None
                self.paused = True
            self.status.setText(ui_text('automatic_backup.tick.recovery_unconfirmed'))
        except Exception as exc:
            # A storage/configuration failure is sticky and visible, never a
            # timer error loop. Saving corrected settings explicitly resumes.
            self.paused = True
            if self.archive is not None:
                try:
                    self.scheduler.complete(archive=self.archive, status='error')
                except Exception:
                    pass
                self.archive = self.job_id = None
            self.status.setText(ui_text('automatic_backup.tick.suspended').format(str(exc)))

    def handle_job_event(self, event):
        window = getattr(self, 'window', None)
        panel = getattr(window, 'backup_inspection_panel', None)
        backup_event = (self.archive is not None and event.get('job_id') == self.job_id) or getattr(window, 'last_operation', None) in (
            'ui_backup_create',
            'ui_backup_restore',
        )
        if panel is not None and backup_event and event.get('type') in ('result', 'error', 'cancelled'):
            archive = None
            if event.get('type') == 'result' and getattr(window, 'last_operation', None) == 'ui_backup_create':
                archive = self.archive or window.backup_path.text()
            panel.refresh(archive)
            panel.invalidate()
        if self.archive is None or event.get('job_id') != self.job_id:
            return
        status = {'result': 'success', 'error': 'error', 'cancelled': 'cancelled'}.get(event.get('type'))
        if status is None:
            return
        try:
            self.scheduler.complete(archive=self.archive, status=status)
            self.status.setText(
                {
                    'success': ui_text('automatic_backup.handle_job_event.success'),
                    'error': ui_text('automatic_backup.handle_job_event.failed'),
                    'cancelled': ui_text('automatic_backup.handle_job_event.cancelled'),
                }[status]
            )
        except Exception as exc:
            self.paused = True
            self.status.setText(ui_text('automatic_backup.handle_job_event.outcome_unknown').format(str(exc)))
        finally:
            self.archive = self.job_id = None
            if panel is not None:
                panel.refresh()

"""Small opt-in backup settings panel using the existing background job slot."""

from desktop_strings import ui_text
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
        self.enabled = QCheckBox(ui_text('automatic_backup.__init__.text_1'))
        layout.addWidget(self.enabled)
        self.directory = QLineEdit()
        self.directory.setPlaceholderText(ui_text('automatic_backup.__init__.text_2'))
        layout.addWidget(self.directory)
        browse = QPushButton(ui_text('automatic_backup.__init__.text_3'))
        browse.clicked.connect(self.browse)
        layout.addWidget(browse)
        save = QPushButton(ui_text('automatic_backup.__init__.text_4'))
        save.setObjectName('save_automatic_backup')
        save.clicked.connect(self.save)
        layout.addWidget(save)
        note = QLabel(ui_text('automatic_backup.__init__.text_5'))
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
                'never': ui_text('automatic_backup.__init__.text_6'),
                'attempted': ui_text('automatic_backup.__init__.text_7'),
                'success': ui_text('automatic_backup.__init__.text_8'),
                'error': ui_text('automatic_backup.__init__.text_9'),
                'cancelled': ui_text('automatic_backup.__init__.text_10'),
            }
            self.status.setText(labels[settings['last_status']])
        except Exception as exc:
            self.paused = True
            self.status.setText(ui_text('automatic_backup.__init__.text_11').format(str(exc)))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(60000)

    def browse(self):
        selected = QFileDialog.getExistingDirectory(self, ui_text('automatic_backup.browse.text_1'), self.directory.text())
        if selected:
            self.directory.setText(selected)

    def save(self):
        try:
            if self.archive is not None:
                self.status.setText(ui_text('automatic_backup.save.text_1'))
                return
            self.scheduler.configure(enabled=self.enabled.isChecked(), directory=self.directory.text().strip())
            self.paused = False
            self.status.setText(ui_text('automatic_backup.save.text_2') if self.enabled.isChecked() else ui_text('automatic_backup.save.text_3'))
        except Exception as exc:
            self.paused = True
            self.status.setText(ui_text('automatic_backup.save.text_4').format(str(exc)))

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
                self.status.setText(ui_text('automatic_backup.tick.text_1'))
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
                self.status.setText(ui_text('automatic_backup.tick.text_2'))
        except RecoveryError:
            if self.archive is not None:
                # A genuine attempted launch keeps the existing no-retry rule.
                try:
                    self.scheduler.complete(archive=self.archive, status='error')
                except Exception:
                    pass
                self.archive = self.job_id = None
                self.paused = True
            self.status.setText(ui_text('automatic_backup.tick.text_3'))
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
            self.status.setText(ui_text('automatic_backup.tick.text_4').format(str(exc)))

    def handle_job_event(self, event):
        if self.archive is None or event.get('job_id') != self.job_id:
            return
        status = {'result': 'success', 'error': 'error', 'cancelled': 'cancelled'}.get(event.get('type'))
        if status is None:
            return
        try:
            self.scheduler.complete(archive=self.archive, status=status)
            self.status.setText(
                {
                    'success': ui_text('automatic_backup.handle_job_event.text_1'),
                    'error': ui_text('automatic_backup.handle_job_event.text_2'),
                    'cancelled': ui_text('automatic_backup.handle_job_event.text_3'),
                }[status]
            )
        except Exception as exc:
            self.paused = True
            self.status.setText(ui_text('automatic_backup.handle_job_event.text_4').format(str(exc)))
        finally:
            self.archive = self.job_id = None

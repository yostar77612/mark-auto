"""Small opt-in backup settings panel using the existing background job slot."""
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
        self.enabled = QCheckBox('啟用每日自動備份（預設關閉）'); layout.addWidget(self.enabled)
        self.directory = QLineEdit(); self.directory.setPlaceholderText('工作區與應用資料夾以外的備份資料夾'); layout.addWidget(self.directory)
        browse = QPushButton('選取自動備份資料夾'); browse.clicked.connect(self.browse); layout.addWidget(browse)
        save = QPushButton('儲存自動備份設定'); save.setObjectName('save_automatic_backup'); save.clicked.connect(self.save); layout.addWidget(save)
        note = QLabel('程式開啟且研究／模型服務／設定作業全部停止後，每 UTC 日最多嘗試一次；取消、失敗或關閉後不會當日自動重試。'
                      '最多 7 個封存檔、2 GiB；空間不足即停止並提示，永不自動刪除。備份不含金鑰、快取、模型與不可逆預算紀錄。還原仍須手動確認。')
        note.setWordWrap(True); layout.addWidget(note)
        self.status = QLabel(''); self.status.setWordWrap(True); layout.addWidget(self.status)
        try:
            settings = self.scheduler.load()
            self.enabled.setChecked(settings['enabled']); self.directory.setText(settings['directory'])
            labels = {'never':'尚無備份', 'attempted':'上次嘗試結果未確認；不會當日重送', 'success':'上次備份成功', 'error':'上次備份失敗', 'cancelled':'上次備份已取消'}
            self.status.setText(labels[settings['last_status']])
        except Exception as exc:
            self.paused = True; self.status.setText('自動備份已暫停：' + str(exc))
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(60000)

    def browse(self):
        selected = QFileDialog.getExistingDirectory(self, '選取自動備份資料夾', self.directory.text())
        if selected: self.directory.setText(selected)

    def save(self):
        try:
            if self.archive is not None:
                self.status.setText('請先等待或取消目前自動備份。'); return
            self.scheduler.configure(enabled=self.enabled.isChecked(), directory=self.directory.text().strip())
            self.paused = False
            self.status.setText('設定已保存；下次閒置檢查時執行。' if self.enabled.isChecked() else '自動備份已關閉。')
        except Exception as exc:
            self.paused = True; self.status.setText('設定未保存：' + str(exc))

    def tick(self):
        w = self.window
        if self.paused or self.archive is not None or getattr(w, '_closing', False): return
        panel = getattr(w, 'local_ai_panel', None)
        busy = (w.jobs.active or (panel is not None and (panel.server.active or panel.task.active))
                or w.chatgpt_controller.busy or w._wf_pending_reconcile or w._pending_plan_reconcile
                or w._pending_usage_refresh or getattr(w, '_kill_pending', False))
        if busy:
            if self.enabled.isChecked(): self.status.setText('等待研究、模型服務與設定作業全部停止後備份。')
            return
        try:
            payload = self.scheduler.claim_due(quiescent=True)
            if payload is None: return
            self.archive = payload['path']
            self.job_id = w.start_job('ui_backup_create', payload)
            self.status.setText('每日自動備份進行中；可使用下方取消背景作業。')
        except Exception as exc:
            # A storage/configuration failure is sticky and visible, never a
            # timer error loop. Saving corrected settings explicitly resumes.
            self.paused = True
            if self.archive is not None:
                try: self.scheduler.complete(archive=self.archive, status='error')
                except Exception: pass
                self.archive = self.job_id = None
            self.status.setText('自動備份已暫停；修正後重新儲存設定：' + str(exc))

    def handle_job_event(self, event):
        if self.archive is None or event.get('job_id') != self.job_id: return
        status = {'result':'success', 'error':'error', 'cancelled':'cancelled'}.get(event.get('type'))
        if status is None: return
        try:
            self.scheduler.complete(archive=self.archive, status=status)
            self.status.setText({'success':'每日自動備份成功。', 'error':'每日自動備份失敗；今天不會自動重試。', 'cancelled':'每日自動備份已取消；今天不會自動重試。'}[status])
        except Exception as exc:
            self.paused = True; self.status.setText('備份結果未能確認；已暫停：' + str(exc))
        finally:
            self.archive = self.job_id = None

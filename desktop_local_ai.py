"""Native local-AI setup panel; separate isolated setup/server workers, no CLI."""
import os
import secrets
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, QLineEdit,
                              QCheckBox, QFileDialog, QMessageBox)
from quantlab.desktop_runtime import JobManager
from quantlab.local_ai import ERROR_MESSAGES, ENDPOINT, MODEL, MAX_CALLS, MAX_TOKENS, SESSION_TOKEN_ENV


class LocalAIPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.server = JobManager(window.paths)
        self.task = JobManager(window.paths)
        self.ready = False
        self.owner = None
        self.last_result = None
        self.server_job = self.task_job = None
        layout = QVBoxLayout(self)
        title = QLabel('免費本機 AI｜llama.cpp b11429 / Qwen2.5 1.5B Q4_K_M')
        title.setWordWrap(True); layout.addWidget(title)
        note = QLabel('Windows x64 CPU。模型約 1.12 GB，請預留至少 3 GB 磁碟與足夠記憶體。'
            '不需 Python、API 金鑰或 ChatGPT 訂閱。下載與啟動皆須自行按鈕；不會自動使用付費 API。'
            '本機推論仍使用電力與硬體。服務只在 127.0.0.1:18765 運作，關閉程式會停止，最長 8 小時。')
        note.setWordWrap(True); layout.addWidget(note)
        licenses = QLabel('<a style="color:#8ec1ff" href="https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/LICENSE">llama.cpp MIT 授權</a> · '
            '<a style="color:#8ec1ff" href="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/blob/91cad51170dc346986eccefdc2dd33a9da36ead9/LICENSE">Qwen Apache-2.0 授權</a>')
        licenses.setOpenExternalLinks(True); layout.addWidget(licenses)
        self.archive = QLineEdit(); self.archive.setPlaceholderText('已下載的固定版本 Windows CPU ZIP（可選）'); layout.addWidget(self.archive)
        self.model = QLineEdit(); self.model.setPlaceholderText('已下載的固定版本 Qwen GGUF（可選）'); layout.addWidget(self.model)
        self.buttons = []
        def button(text, name, action):
            item = QPushButton(text); item.setObjectName(name)
            item.clicked.connect(lambda: self.safe(action)); layout.addWidget(item); self.buttons.append(item)
            return item
        button('選取官方 Windows CPU ZIP', 'local_ai_browse_runtime', lambda: self.browse(self.archive, 'ZIP (*.zip)'))
        button('選取官方 Qwen GGUF', 'local_ai_browse_model', lambda: self.browse(self.model, 'GGUF (*.gguf)'))
        button('驗證並使用已下載檔案', 'local_ai_install', self.install)
        button('下載並設定固定免費版本', 'local_ai_download', self.download)
        button('啟動已驗證本機模型', 'local_ai_start', self.start)
        button('執行一次結構化推論檢查', 'local_ai_probe', self.probe)
        button('選用免費本機 AI 研究', 'local_ai_select', self.select)
        self.stop_button = button('取消設定／停止本機模型', 'local_ai_stop', self.stop)
        self.consent = QCheckBox('我同意下一次研究使用已啟動的免費本機模型（不含 OOS／保留集）'); layout.addWidget(self.consent)
        self.status = QLabel('尚未啟動。健康檢查只代表服務就緒，不代表真實模型、Windows 客戶端或策略驗收通過。')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        budget = QLabel(f'此固定版本共用永久上限：{MAX_CALLS} 次、{MAX_TOKENS:,} 個保守 tokens；包含推論檢查與失敗。'
            '重啟、切換工作區及還原不會重設。若額度用完會停止，不會改用其他供應商。')
        budget.setWordWrap(True); layout.addWidget(budget)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(150)

    def safe(self, action):
        try: action()
        except Exception:
            self.status.setText('本機 AI 操作未完成；請核對檔案與作業狀態。既有紀錄保留。')

    def idle(self):
        if self.window.jobs.active or self.task.active:
            self.status.setText('請先完成或取消目前背景作業。'); return False
        return True

    def browse(self, target, pattern):
        filename, _ = QFileDialog.getOpenFileName(self, '選取固定官方版本', '', pattern)
        if filename: target.setText(filename)

    def launch_task(self, payload):
        if not self.idle(): return
        self.last_result = None
        self.task_job = self.task.start('ui_local_ai', payload)
        self.status.setText('正在處理本機模型；可取消，下載及雜湊驗證不在介面執行。')

    def install(self):
        if self.server.active:
            self.status.setText('請先停止本機模型再設定檔案。'); return
        self.launch_task({'action': 'install', 'consent': True,
            'runtime_archive': self.archive.text().strip(), 'model_file': self.model.text().strip()})

    def download(self):
        if not self.idle() or self.server.active: return
        answer = QMessageBox.question(self, '下載免費本機 AI',
            '從官方 GitHub 與 Hugging Face 下載固定 llama.cpp b11429 CPU ZIP（19.4 MB）與 Qwen 1.5B GGUF（1.12 GB），'
            '套用上方 MIT／Apache-2.0 授權並附 OpenMP 授權。沒有付費 API、訂閱或登入。檔案保存在本機快取且不包含於研究備份。是否下載？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.launch_task({'action': 'download', 'consent': True})

    def start(self):
        if not self.idle() or self.server.active: return
        self.ready = False
        os.environ[SESSION_TOKEN_ENV] = secrets.token_urlsafe(32)
        self.server_job = self.server.start('ui_local_ai', {'action': 'serve', 'consent': True})
        self.status.setText('正在驗證完整模型與執行檔，再啟動服務；初次讀取約 1.12 GB。')

    def probe(self):
        if not self.ready or not self.server.active:
            self.status.setText('請先啟動已驗證本機模型。'); return
        if not self.idle(): return
        answer = QMessageBox.question(self, '一次本機推論檢查',
            '使用 1 次共用永久呼叫額度，最多 1024 輸出 tokens／120 秒；失敗也保留額度。'
            '僅傳送固定技術題目，不傳市場資料、不回測、不讀取 OOS／保留集。是否繼續？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.launch_task({'action': 'probe', 'consent': True, 'owner':dict(self.owner or {})})

    def select(self):
        self.window.provider_mode.setCurrentIndex(self.window.provider_mode.findData('local'))
        self.consent.setChecked(False)
        self.status.setText('已選用免費本機 AI；每次研究仍須勾選本次同意。相容 HTTP 設定不會被覆寫。')

    def stop(self):
        if self.window.jobs.active:
            self.status.setText('請先取消目前研究，再停止本機模型。'); return
        self.consent.setChecked(False); self.ready = False; self.owner = None
        self.task.close(); self.server.close()
        os.environ.pop(SESSION_TOKEN_ENV, None)
        self.task.poll(); self.server.poll()
        self.status.setText('已停止並確認本機背景程序退出。消耗紀錄保留；未完成下載可再次明確重試。')

    def poll(self):
        try:
            for manager, identity in ((self.server, self.server_job), (self.task, self.task_job)):
                for event in manager.poll():
                    if event.get('job_id') != identity: continue
                    kind = event.get('type')
                    if manager is self.server and kind == 'progress' and event.get('local_ai_ready') is True:
                        owner = event.get('local_ai_owner')
                        if not isinstance(owner, dict) or set(owner) != {'pid','created'}: raise ValueError()
                        self.owner = owner
                        self.ready = True
                    if kind == 'progress': self.status.setText(event.get('message', '處理中'))
                    elif kind == 'result':
                        result = event.get('result', {})
                        if manager is self.task: self.last_result = result
                        code = result.get('error_code')
                        if code: self.status.setText(ERROR_MESSAGES.get(code, ERROR_MESSAGES['request']))
                        elif result.get('status') == 'installed': self.status.setText('官方固定檔案驗證完成。請按啟動模型；尚未呼叫 AI。')
                        elif result.get('status') == 'schema_probe_pass':
                            used = result['usage']['calls']
                            self.status.setText(f'一次結構化技術推論成功，共用額度已用 {used}/{MAX_CALLS} 次。未回測、未晉級；真實模型整體狀態仍未驗證。')
                    elif kind in ('error', 'cancelled'):
                        if manager is self.server: self.ready = False
                        self.status.setText(event.get('message', '作業已停止；消耗紀錄保留。'))
            if not self.server.active:
                self.ready = False; self.owner = None
                os.environ.pop(SESSION_TOKEN_ENV, None)
        except Exception:
            self.ready = False
            self.status.setText('本機程序狀態無法確認，禁止研究；請停止並確認清理。')

    def close_workers(self, *, stop_timer=True):
        self.consent.setChecked(False); self.ready = False; self.owner = None
        self.task.close(); self.server.close()
        os.environ.pop(SESSION_TOKEN_ENV, None)
        if stop_timer: self.timer.stop()

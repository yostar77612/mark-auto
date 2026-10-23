"""Timer-paced paper workers. Pause is applied between single-bar operations."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from desktop_strings import ui_text
from quantlab.replay_pacing import ReplayPacer, SPEEDS
from .paper_readiness import refresh_readiness


class ReplayControls:
    def __init__(self, page, layout, *, options_layout=None, session_layout=None):
        self.page = page
        self.pacer = ReplayPacer()
        self.running = False
        self.pending = None
        self.remaining = 0
        self.payload = None
        self.inflight = False
        self.paused = False
        self.speed = QComboBox()
        self.speed.setObjectName('paper_replay_speed')
        self.speed.setAccessibleName(ui_text('replay.speed'))
        self.speed.setToolTip(ui_text('replay.speed_tip'))
        for speed in SPEEDS:
            self.speed.addItem(ui_text('replay.speed_value').format(speed), speed)
        self.speed.insertItem(0, ui_text('replay.unpaced'), None)
        self.speed.setCurrentIndex(0)
        self.speed.currentIndexChanged.connect(self.change_speed)
        layout = options_layout if options_layout is not None else layout
        layout.addWidget(self.speed)
        layout = session_layout if session_layout is not None else layout
        self.button = QPushButton(ui_text('replay.pause'))
        self.button.setObjectName('paper_replay_pause')
        self.button.setAccessibleName(ui_text('replay.pause'))
        self.button.setToolTip(ui_text('replay.pause_tip'))
        self.button.setEnabled(False)
        self.button.clicked.connect(lambda: page.host.safe(self.toggle))
        layout.addWidget(self.button)
        self.stop_button = QPushButton(ui_text('replay.stop'))
        self.stop_button.setObjectName('paper_replay_stop')
        self.stop_button.setAccessibleName(ui_text('replay.stop'))
        self.stop_button.setToolTip(ui_text('replay.stop_tip'))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(lambda: page.host.safe(self.stop))
        layout.addWidget(self.stop_button)
        self.label = QLabel(ui_text('replay.idle'))
        self.label.setObjectName('paper_replay_state')
        self.label.setAccessibleName(ui_text('replay.state'))
        layout.addWidget(self.label)
        self.timer = QTimer(page)
        self.timer.setInterval(10)
        self.timer.timeout.connect(lambda: page.host.safe(self.tick))
        self._show_session(False)

    def _show_session(self, visible):
        # Session controls stay beside the replay action while a paced run exists.
        for widget in (self.button, self.stop_button, self.label):
            widget.setVisible(visible)

    def change_speed(self):
        self.pacer.set_speed(self.speed.currentData() or 1)
        self.pacer.defer()

    def begin(self, payload):
        # Consent and the initial snapshot were checked by PaperPage.paper_job.
        if self.running or self.inflight:
            return
        self.payload = dict(payload)
        self.remaining = payload['max_bars']
        self.running = True
        self._show_session(True)
        self.pending = 'inspect'
        self.timer.start()
        self.tick()
        refresh_readiness(self.page)

    def toggle(self):
        if not self.running:
            return
        self.pending = 'resume' if self.paused else 'pause'
        self.button.setEnabled(False)
        self.tick()

    def stop(self):
        if self.running:
            self.pending = 'stop'
            self.button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.tick()

    def tick(self):
        if not self.running or self.inflight or self.page.jobs.active:
            return
        action = self.pending
        if action is None:
            if self.paused or not self.pacer.ready():
                return
            action = 'tick' if self.remaining > 0 else 'stop'
        self.pending = None
        self.inflight = True
        self.action = action
        try:
            self.page.start_job('ui_paper_replay', dict(self.payload, replay_action=action))
        except Exception:
            self.cancel()
            raise

    def result(self, result):
        if not self.running or not self.inflight:
            return
        self.inflight = False
        state = result['replay']
        self.payload['snapshot'] = result['account']
        if self.action == 'tick':
            self.remaining -= 1
            # Safety gates must end the loop, even if the cursor did not move.
            if result['account']['kill_switch'] or result['account']['reconciliation_required']:
                self.pending = 'stop'
        self.paused = state.get('paused', False)
        if state['complete'] and self.action != 'stop':
            self.pending = 'stop'
        if self.action == 'stop':
            self.cancel()
        else:
            self.label.setText(ui_text('replay.paused') if self.paused else ui_text('replay.running'))
            self.button.setText(ui_text('replay.resume') if self.paused else ui_text('replay.pause'))
            self.button.setAccessibleName(self.button.text())
            self.button.setEnabled(True)
            self.stop_button.setEnabled(True)
            self.pacer.defer()
        refresh_readiness(self.page)

    def cancel(self):
        self.timer.stop()
        self.running = self.inflight = False
        self.pending = None
        self.button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.label.setText(ui_text('replay.idle'))
        self._show_session(False)
        refresh_readiness(self.page)

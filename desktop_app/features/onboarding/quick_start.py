"""Confirmed synthetic walkthrough, using the shell's existing job lifecycle."""

from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton
from desktop_app.strings.catalog import ui_text
from quantlab.desktop_errors import error_message
from quantlab.core import to_dict
from quantlab.reporting import demo_config
from quantlab.strategies import builtin_strategies
from desktop_app.features.onboarding.quick_start_chain import QuickStartChain


class QuickStart:
    def __init__(self, shell, layout):
        self.shell = shell
        self.button = QPushButton(ui_text('quick_start.action'))
        self.button.setObjectName('synthetic_quick_start')
        self.button.setAccessibleName(ui_text('quick_start.action'))
        self.button.setProperty('role', 'secondary')
        self.message = QLabel()
        self.message.setObjectName('synthetic_quick_start_status')
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.button)
        layout.addWidget(self.message)
        self.chain = QuickStartChain(shell.start_job, self.apply_strategy, self.results, self.notice)
        self.button.clicked.connect(self.confirm)
        self.refresh()

    def refresh(self):
        busy = bool(getattr(getattr(self.shell, 'jobs', None), 'active', False))
        self.button.setEnabled(not busy and self.chain.stage is None)
        self.button.setToolTip(ui_text('quick_start.busy') if busy or self.chain.stage is not None else ui_text('quick_start.tooltip'))

    def confirm(self):
        if not self.button.isEnabled():
            return
        answer = QMessageBox.question(
            self.button,
            ui_text('quick_start.action'),
            ui_text('quick_start.confirm'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        self.chain.begin(answer == QMessageBox.StandardButton.Yes, bool(getattr(getattr(self.shell, 'jobs', None), 'active', False)))
        self.refresh()

    def apply_strategy(self):
        spec = builtin_strategies()[0]
        return {
            'family': spec.family,
            'parameters': dict(spec.parameters),
            'config': to_dict(demo_config()),
            'start_date': '',
            'end_date': '',
            'batch': False,
            'candidate': None,
        }

    def notice(self, stage):
        messages = {
            'data': ui_text('quick_start.data'),
            'backtest': ui_text('quick_start.backtest'),
            'done': ui_text('quick_start.done'),
            'cancelled': ui_text('quick_start.cancelled'),
            'error': error_message('operation_failed_local'),
        }
        self.message.setText(messages[stage])
        self.message.setAccessibleName(messages[stage])
        self.message.show()

    def results(self, result):
        path = result['reports'][0]['result']
        choice = self.shell.result_choice
        index = choice.findData(path)
        if index < 0:
            choice.addItem(ui_text('quick_start.dataset'), path)
            index = choice.count() - 1
        choice.setCurrentIndex(index)
        if self.shell.backtest_page.show_result() is False:
            raise ValueError()
        self.shell.navigation.setCurrentRow(2)

    def tick(self):
        if getattr(self.shell, '_closing', False):
            self.chain.stop()
        self.chain.advance(bool(getattr(getattr(self.shell, 'jobs', None), 'active', False)))
        self.refresh()

"""Explicit local reconciliation, displayed only after its inspection worker joins."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from desktop_strings import ui_text


class ReconciliationDialog(QDialog):
    def __init__(self, sequence, calls, parent=None):
        super().__init__(parent)
        self.setObjectName('chatgpt_reconciliation_dialog')
        self.setWindowTitle(ui_text('chatgpt_reconciliation.title'))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAccessibleName(ui_text('chatgpt_reconciliation.title'))
        layout = QVBoxLayout(self)
        for key, text in (
            ('summary', ui_text('chatgpt_reconciliation.summary').format(sequence, calls)),
            ('explanation', ui_text('chatgpt_reconciliation.explanation')),
        ):
            label = QLabel(text, self)
            label.setObjectName('chatgpt_reconciliation_' + key)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.acknowledgements = []
        for key, text in (
            ('usage_checked', ui_text('chatgpt_reconciliation.usage_checked')),
            ('no_refund', ui_text('chatgpt_reconciliation.no_refund')),
            ('no_other_tool', ui_text('chatgpt_reconciliation.no_other_tool')),
        ):
            check = QCheckBox(text, self)
            check.setObjectName('chatgpt_reconciliation_' + key)
            check.setAccessibleName(check.text())
            check.setChecked(False)
            check.toggled.connect(self._update_confirmation)
            layout.addWidget(check)
            self.acknowledgements.append(check)
        self.buttons = QDialogButtonBox(self)
        self.confirm = self.buttons.addButton(ui_text('chatgpt_reconciliation.confirm'), QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel = self.buttons.addButton(ui_text('chatgpt_reconciliation.cancel'), QDialogButtonBox.ButtonRole.RejectRole)
        self.confirm.setObjectName('chatgpt_reconciliation_confirm')
        self.cancel.setObjectName('chatgpt_reconciliation_cancel')
        self.confirm.setAccessibleName(ui_text('chatgpt_reconciliation.confirm'))
        self.cancel.setAccessibleName(ui_text('chatgpt_reconciliation.cancel'))
        self.confirm.setAutoDefault(False)
        self.cancel.setDefault(True)
        self.confirm.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        chain = [*self.acknowledgements, self.cancel, self.confirm]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)
        self.resize(620, self.sizeHint().height())
        self.cancel.setFocus()

    def _update_confirmation(self):
        self.confirm.setEnabled(all(check.isChecked() for check in self.acknowledgements))

    def accept(self):
        if all(check.isChecked() for check in self.acknowledgements):
            super().accept()


class ReconciliationFlow:
    def __init__(self, panel):
        self.panel = panel
        self.flow = None
        self.dialog = None
        panel.controller.request_finished.connect(self._finished)
        panel.controller.changed.connect(self._changed)
        panel.account.currentIndexChanged.connect(self._account_changed)

    def start(self):
        self.abandon()
        p, c = self.panel, self.panel.controller
        registration = p.account.currentData()
        if not p.isVisible() or not c.host_available or c.busy or c.background_busy or registration != c.active_registration or registration is None:
            raise ValueError('active_or_unknown_request')
        self.flow = {'request_id': c._counter + 1, 'registration': registration}
        try:
            return c.request('inspect_unknown', registration)
        except Exception:
            self.abandon()
            raise

    def abandon(self):
        self.flow = None
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            dialog.reject()
            dialog.deleteLater()

    def _account_changed(self, *_):
        # Every selection change invalidates the previous three acknowledgements.
        self.abandon()
        self.panel._render()

    def _changed(self):
        flow, c = self.flow, self.panel.controller
        if flow is None:
            return
        if (
            not c.host_available
            or flow['registration'] != c.active_registration
            or c._counter != flow['request_id']
            or c.stopping
            and not c._terminal_received
            or self.dialog is not None
            and (c.busy or c.background_busy)
        ):
            self.abandon()

    def _finished(self, request, succeeded):
        flow = self.flow
        if flow is None or request.request_id != flow['request_id']:
            return
        if not succeeded or request.action != 'inspect_unknown':
            self.abandon()
            return
        QTimer.singleShot(0, lambda: self._show(request.request_id))

    def _eligible(self, request_id):
        p, c, flow = self.panel, self.panel.controller, self.flow
        return bool(
            flow is not None
            and flow['request_id'] == request_id
            and c._counter == request_id
            and p.isVisible()
            and c.host_available
            and not c.busy
            and not c.background_busy
            and p.account.currentData() == flow['registration'] == c.active_registration
            and c.account_status_known
            and c.account_pending
            and c.account_state == 'reserved_unknown'
        )

    def _show(self, request_id):
        c = self.panel.controller
        if not self._eligible(request_id):
            self.abandon()
            return
        inspection = c.reconciliation_inspection
        if inspection is None or inspection[0] != 'k1_resolvable' or inspection[3] is not True:
            self.abandon()
            return
        dialog = ReconciliationDialog(inspection[1], inspection[2], self.panel)
        self.dialog = dialog
        dialog.finished.connect(lambda result: self._submit(request_id, dialog, result))
        dialog.open()

    def _submit(self, request_id, dialog, result):
        from desktop_chatgpt_ui import RECONCILIATION_ACKNOWLEDGEMENT_VERSION

        if self.dialog is not dialog:
            dialog.deleteLater()
            return
        valid = result == QDialog.DialogCode.Accepted and self._eligible(request_id) and all(check.isChecked() for check in dialog.acknowledgements)
        registration = self.flow['registration'] if self.flow is not None else None
        self.dialog = None
        self.flow = None
        dialog.deleteLater()
        if valid:
            self.panel._safe(
                lambda: self.panel.controller.request(
                    'resolve_unknown',
                    registration,
                    confirmed=True,
                    acknowledgement_version=RECONCILIATION_ACKNOWLEDGEMENT_VERSION,
                )
            )

"""Explicit resolution of unknown manual submissions; never resubmits an order."""

from uuid import uuid4

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QComboBox, QLabel

from desktop_app.features.trading.widgets import button
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import ManualMutationForm, UiAction
from quantlab.trading.domain.models import Environment


RESOLUTION_ACTIONS = frozenset((UiAction.ADOPT_MANUAL_ORDER, UiAction.DECLARE_MANUAL_NOT_SENT))


class ManualRecovery:
    def __init__(self, controller, row):
        self.controller = controller
        self.resolutions = {}
        self.caption = QLabel(ui_text('u2.candidates'))
        self.candidates = QComboBox()
        self.candidates.setObjectName('manual_recovery_candidates')
        self.candidates.setAccessibleName(ui_text('u2.candidates'))
        self.candidates.setMinimumContentsLength(14)
        self.candidates.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.candidates.setMaximumWidth(240)
        self.caption.setBuddy(self.candidates)
        self.adopt = button('u2.adopt', 'manual_adopt')
        self.declare = button('u2.declare', 'manual_declare_not_sent', role='danger')
        for widget in (self.caption, self.candidates, self.adopt, self.declare):
            row.addWidget(widget)
        self.adopt.clicked.connect(lambda: self.resolve(True))
        self.declare.clicked.connect(lambda: self.resolve(False))

    def pending(self, state):
        pending = state.manual.pending
        if (
            self.controller.matches(state)
            and pending is not None
            and not pending.outcome_known
            and pending.operation == 'SUBMIT'
            and pending.status == 'UNKNOWN'
            and pending.order_id in state.manual.manual_order_ids
            and (pending.scope.context_id, pending.scope.account_ref, pending.scope.environment) == (state.context_id, state.account_ref, state.environment)
        ):
            return pending
        return None

    def observe(self, state):
        result = state.manual.last_result
        for request_id, (mutation, original) in tuple(self.resolutions.items()):
            if (
                result is not None
                and result.request_id == mutation.request_id
                and result.scope == mutation.scope
                and result.outcome_known
                and result.status == 'RESOLVED'
                and result.operation in ('ADOPT', 'DECLARE')
                and self.controller.matches(state)
                and (state.manual.pending is None or state.manual.pending.request_id != original.request_id)
            ):
                if self.controller.intents.pending.get(original.request_id) == original.scope:
                    del self.controller.intents.pending[original.request_id]
                del self.resolutions[request_id]

    def received(self, command, receipt):
        if command is not None and command.action in RESOLUTION_ACTIONS and receipt is not None:
            if not receipt.accepted and receipt.code != 'outcome_unknown':
                for request_id, (mutation, _) in tuple(self.resolutions.items()):
                    if mutation == command.manual_mutation:
                        del self.resolutions[request_id]

    def render(self, state):
        self.observe(state)
        for widget in (self.caption, self.candidates, self.adopt, self.declare):
            widget.setVisible(state.environment is Environment.BROKER_SIMULATION)
        pending = self.pending(state)
        selected = self.candidates.currentData()
        candidates = pending.candidates if pending else ()
        current = tuple(self.candidates.itemData(index) for index in range(self.candidates.count()))
        if current != candidates:
            with QSignalBlocker(self.candidates):
                self.candidates.clear()
                for reference in candidates:
                    self.candidates.addItem(reference, reference)
                self.candidates.setCurrentIndex(max(0, self.candidates.findData(selected)))
        waiting = pending is not None and pending.request_id in self.resolutions
        ready = pending is not None and state.manual.confirmed and not self.controller.busy() and not waiting
        self.candidates.setEnabled(ready and bool(candidates))
        self.adopt.setEnabled(ready and bool(candidates))
        self.declare.setEnabled(ready and not candidates)
        hint = (
            ui_text('m2t.orders_disabled') if state.environment is Environment.LIVE else ui_text('u2.recovery_wait') if waiting else ui_text('u2.recovery_hint')
        )
        self.candidates.setToolTip(hint)
        self.adopt.setToolTip(hint)
        self.declare.setToolTip(ui_text('u2.candidate_exists') if candidates else hint)

    def resolve(self, adopt):
        controller, state = self.controller, self.controller.window.state
        pending = self.pending(state)
        if pending is None or controller.busy() or not state.manual.confirmed or pending.request_id in self.resolutions:
            return
        reference = self.candidates.currentData() if adopt else ''
        if adopt and reference not in pending.candidates or not adopt and pending.candidates:
            return
        text = ui_text('u2.confirm_adopt').format(pending.order_id, reference) if adopt else ui_text('u2.confirm_declare').format(pending.order_id)
        if not controller._confirm(text):
            return
        current = controller.window.state
        if controller.busy() or self.pending(current) != pending or (adopt and self.candidates.currentData() != reference):
            controller.window._feedback(ui_text('v2.state_conflict'))
            return
        mutation = ManualMutationForm(current.manual.scope, str(uuid4()), pending.order_id, confirmed=True)
        self.resolutions[pending.request_id] = mutation, pending
        controller._send(UiAction.ADOPT_MANUAL_ORDER if adopt else UiAction.DECLARE_MANUAL_NOT_SENT, mutation=mutation, target_id=reference)

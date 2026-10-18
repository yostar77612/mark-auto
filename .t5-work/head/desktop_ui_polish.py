"""Presentation-only labels and disabled-action explanations for the desktop host."""
from desktop_strings import ui_text
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QLabel, QPushButton, QBoxLayout, QFormLayout


class DisabledHint(QObject):
    """Follow Qt's effective enabled state, including disabled parent containers."""
    def __init__(self, button, label, prerequisite):
        super().__init__(button)
        self.button, self.label, self.prerequisite = button, label, prerequisite
        self.original_tooltip = button.toolTip()
        button.installEventFilter(self)
        self.update()

    def update(self):
        disabled = not self.button.isEnabled()
        jobs = getattr(self.button.window(), 'jobs', None)
        prerequisite = (ui_text('ui_polish.update.text_1') if jobs is not None and jobs.active
                        and self.button.objectName() != 'cancel_job' else self.prerequisite)
        text = ui_text('ui_polish.update.text_2').format(prerequisite) if disabled else ''
        self.button.setToolTip(text if disabled else self.original_tooltip)
        self.button.setProperty('disabled_hint', text)
        self.label.setText(text)
        self.label.setVisible(disabled)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.update()
        return False


def _insert_after(layout, widget, label, *, before=False):
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget:
            if isinstance(layout, QBoxLayout):
                layout.insertWidget(index if before else index + 1, label)
            elif isinstance(layout, QFormLayout):
                row, _ = layout.getWidgetPosition(widget)
                layout.insertRow(row if before else row + 1, label)
            else:
                return False
            return True
        if item.layout() and _insert_after(item.layout(), widget, label, before=before):
            return True
    return False


def _label_field(widget, text):
    label = QLabel(text, widget.parentWidget())
    label.setBuddy(widget)
    layout = widget.parentWidget().layout()
    if layout is None or not _insert_after(layout, widget, label, before=True):
        raise ValueError('Input label has no supported layout: ' + text)
    widget.setAccessibleName(text)


def install_polish(window):
    """Install once after construction; never change action eligibility or payloads."""
    fields = {
        'market_provider': ui_text('ui_polish.install_polish.text_1'), 'import_kind': ui_text('ui_polish.install_polish.text_2'),
        'bars': ui_text('ui_polish.install_polish.text_3'), 'days': ui_text('ui_polish.install_polish.text_4'),
        'family': ui_text('ui_polish.install_polish.text_5'), 'provider_mode': ui_text('ui_polish.install_polish.text_6'),
        'candidate_choice': ui_text('ui_polish.install_polish.text_7'), 'walk_forward_choice': ui_text('ui_polish.install_polish.text_8'),
        'result_choice': ui_text('ui_polish.install_polish.text_9'), 'analysis_saved': ui_text('ui_polish.install_polish.text_10'),
        'replay_bars': ui_text('ui_polish.install_polish.text_11'),
    }
    for name, text in fields.items():
        _label_field(getattr(window, name), text)
    _label_field(window.chatgpt_panel.account, ui_text('ui_polish.install_polish.text_12'))
    _label_field(window.automatic_backup_panel.directory, ui_text('ui_polish.install_polish.text_13'))
    for widget, suffix in ((window.bars, ui_text('ui_polish.install_polish.text_14')), (window.days, ui_text('ui_polish.install_polish.text_15')),
                           (window.replay_bars, ui_text('ui_polish.install_polish.text_16')), (window.chatgpt_panel.max_calls, ui_text('ui_polish.install_polish.text_17')),
                           (window.chatgpt_panel.timeout, ui_text('ui_polish.install_polish.text_18'))):
        widget.setSuffix(suffix)
    for _, controls in window.market._indicator_widgets.values():
        for key, widget in controls.items():
            widget.setSuffix(ui_text('ui_polish.install_polish.text_19') if key == 'deviations' else ui_text('ui_polish.install_polish.text_20'))
    prerequisites = {
        'run_backtest': ui_text('ui_polish.install_polish.text_21'),
        'use_candidate': ui_text('ui_polish.install_polish.text_22'),
        'select_strategy': ui_text('ui_polish.install_polish.text_23'),
        'run_walk_forward': ui_text('ui_polish.install_polish.text_24'),
        'pick_walk_forward_original': ui_text('ui_polish.install_polish.text_25'),
        'run_candidate_analysis': ui_text('ui_polish.install_polish.text_26'),
        'reconcile_saved_analysis': ui_text('ui_polish.install_polish.text_27'),
        'cancel_job': ui_text('ui_polish.install_polish.text_28'),
        'market_add': ui_text('ui_polish.install_polish.text_29'),
        'market_refresh': ui_text('ui_polish.install_polish.text_30'),
        'chatgpt_enable_plan': ui_text('ui_polish.install_polish.text_31'),
        'chatgpt_models': ui_text('ui_polish.install_polish.text_32'),
        'chatgpt_clear_pause': ui_text('ui_polish.install_polish.text_33'),
        'chatgpt_open_official': ui_text('ui_polish.install_polish.text_34'),
    }
    window._disabled_hints = []
    for button in window.findChildren(QPushButton):
        if not button.property('role'):
            button.setProperty('role', 'secondary')
        name = button.objectName()
        prerequisite = prerequisites.get(name, ui_text('ui_polish.install_polish.text_35'))
        if button in window.chatgpt_panel.buttons.values() and name not in prerequisites:
            prerequisite = ui_text('ui_polish.install_polish.text_36')
        if button is window.chatgpt_panel.cancel_button:
            prerequisite = ui_text('ui_polish.install_polish.text_37')
        label = QLabel(button.parentWidget())
        label.setWordWrap(True)
        label.setProperty('prerequisite', True)
        label.setObjectName(name + '_prerequisite')
        layout = button.parentWidget().layout()
        if layout and _insert_after(layout, button, label):
            window._disabled_hints.append(DisabledHint(button, label, prerequisite))
        else:
            label.deleteLater()

"""Presentation-only labels and disabled-action explanations for the desktop host."""

from desktop_strings import ui_text
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QLabel, QPushButton, QBoxLayout, QFormLayout


class DisabledHint(QObject):
    """Follow Qt's effective enabled state, including disabled parent containers."""

    def __init__(self, button, label, prerequisite, *, host=None):
        super().__init__(button)
        self.button, self.label, self.prerequisite = button, label, prerequisite
        self.host = host
        self.original_tooltip = button.toolTip()
        button.installEventFilter(self)
        self.update()

    def update(self):
        disabled = not self.button.isEnabled()
        host = self.host if self.host is not None else self.button.window()
        jobs = getattr(host, 'jobs', None)
        prerequisite = self.prerequisite
        prerequisite = ui_text('ui_polish.update.job_busy') if jobs is not None and jobs.active and self.button.objectName() != 'cancel_job' else prerequisite
        paper = getattr(host, 'paper_page', None)
        if self.button.objectName() in ('paper_submit', 'paper_replay', 'paper_cancel') and getattr(
            getattr(paper, 'page_state', None), 'manual_order_lock', False
        ):
            prerequisite = ui_text('paper.lock.rejected')
        text = ui_text('ui_polish.update.prerequisite_required').format(prerequisite) if disabled else ''
        if disabled and self.button.objectName() == 'cancel_job':
            progress = getattr(host, 'job_progress', self.button.parentWidget())
            text = ui_text('job.cancel_notice') if getattr(progress, 'running', False) else ui_text('job.idle_hint')
        self.button.setToolTip(text if disabled else self.original_tooltip)
        self.button.setProperty('disabled_hint', text)
        self.label.setText(text)
        self.label.setVisible(disabled and not self.button.isHidden())

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.EnabledChange, QEvent.Type.Show, QEvent.Type.Hide):
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
    _install_input_tooltips(window)
    fields = {
        'market_provider': ui_text('ui_polish.install_polish.official_format'),
        'import_kind': ui_text('ui_polish.install_polish.import_format'),
        'bars': ui_text('ui_polish.install_polish.synthetic_bars'),
        'days': ui_text('ui_polish.install_polish.recent_days'),
        'family': ui_text('ui_polish.install_polish.strategy_family'),
        'provider_mode': ui_text('ui_polish.install_polish.generator_source'),
        'candidate_choice': ui_text('ui_polish.install_polish.saved_candidate'),
        'walk_forward_choice': ui_text('ui_polish.install_polish.saved_walk_forward'),
        'result_choice': ui_text('ui_polish.install_polish.saved_backtest'),
        'analysis_saved': ui_text('ui_polish.install_polish.saved_analysis'),
        'replay_bars': ui_text('ui_polish.install_polish.replay_bars'),
    }
    for name, text in fields.items():
        _label_field(getattr(window, name), text)
    _label_field(window.chatgpt_panel.account, ui_text('ui_polish.install_polish.saved_connection'))
    _label_field(window.automatic_backup_panel.directory, ui_text('ui_polish.install_polish.backup_directory'))
    for widget, suffix in (
        (window.bars, ui_text('ui_polish.install_polish.bars_suffix')),
        (window.days, ui_text('ui_polish.install_polish.days_suffix')),
        (window.replay_bars, ui_text('ui_polish.install_polish.bars_suffix')),
        (window.chatgpt_panel.max_calls, ui_text('ui_polish.install_polish.attempts_suffix')),
        (window.chatgpt_panel.timeout, ui_text('ui_polish.install_polish.seconds_suffix')),
    ):
        widget.setSuffix(suffix)
    for _, controls in window.market._indicator_widgets.values():
        for key, widget in controls.items():
            widget.setSuffix(ui_text('ui_polish.install_polish.speed_suffix') if key == 'deviations' else ui_text('ui_polish.install_polish.bars_suffix'))
    prerequisites = {
        'run_backtest': ui_text('ui_polish.install_polish.import_prerequisite'),
        'use_candidate': ui_text('ui_polish.install_polish.candidate_prerequisite'),
        'select_strategy': ui_text('ui_polish.install_polish.strategy_prerequisite'),
        'run_walk_forward': ui_text('ui_polish.install_polish.walk_forward_prerequisite'),
        'pick_walk_forward_original': ui_text('ui_polish.install_polish.saved_pool_prerequisite'),
        'run_candidate_analysis': ui_text('ui_polish.install_polish.analysis_prerequisite'),
        'reconcile_saved_analysis': ui_text('ui_polish.install_polish.recovery_prerequisite'),
        'cancel_job': ui_text('job.idle_hint'),
        'market_add': ui_text('ui_polish.install_polish.market_catalog_prerequisite'),
        'market_refresh': ui_text('ui_polish.install_polish.market_update_prerequisite'),
        'chatgpt_enable_plan': ui_text('ui_polish.install_polish.connection_prerequisite'),
        'chatgpt_models': ui_text('ui_polish.install_polish.usage_prerequisite'),
        'chatgpt_clear_pause': ui_text('ui_polish.install_polish.quota_prerequisite'),
        'chatgpt_open_official': ui_text('ui_polish.install_polish.authorization_prerequisite'),
    }
    window._disabled_hints = []
    for button in window.findChildren(QPushButton):
        if not button.property('role'):
            button.setProperty('role', 'secondary')
        name = button.objectName()
        prerequisite = prerequisites.get(name, ui_text('ui_polish.install_polish.idle_prerequisite'))
        if button in window.chatgpt_panel.buttons.values() and name not in prerequisites:
            prerequisite = ui_text('ui_polish.install_polish.saved_connection_prerequisite')
        if button is window.chatgpt_panel.cancel_button:
            prerequisite = ui_text('ui_polish.install_polish.connection_job_prerequisite')
        label = QLabel(button.parentWidget())
        label.setWordWrap(True)
        label.setProperty('prerequisite', True)
        label.setObjectName(name + '_prerequisite')
        layout = button.parentWidget().layout()
        if layout and _insert_after(layout, button, label):
            window._disabled_hints.append(DisabledHint(button, label, prerequisite))
        else:
            label.deleteLater()


def _install_input_tooltips(window):
    """Explain units and consequences without changing geometry or payloads."""
    fields = (
        (window.market_provider, ui_text('tooltip.market_provider')),
        (window.import_path, ui_text('tooltip.import_path')),
        (window.calendar_path, ui_text('tooltip.calendar_path')),
        (window.import_kind, ui_text('tooltip.import_kind')),
        (window.bars, ui_text('tooltip.bars')),
        (window.days, ui_text('tooltip.days')),
        (window.result_choice, ui_text('tooltip.result_choice')),
        (window.replay_bars, ui_text('tooltip.replay_bars')),
        (window.cancel_order, ui_text('tooltip.cancel_order')),
        (window.paper_time.enabled_value, ui_text('tooltip.paper_time')),
        (window.paper_time.picker, ui_text('tooltip.paper_time')),
        (window.market.contract_combo, ui_text('tooltip.market_contract')),
        (window.market.timeframe_combo, ui_text('tooltip.market_timeframe')),
        (window.market.search, ui_text('tooltip.market_search')),
        (window.market.catalog_combo, ui_text('tooltip.market_catalog')),
        (window.workspace_path, ui_text('tooltip.workspace_path')),
        (window.backup_path, ui_text('tooltip.backup_path')),
        (window.automatic_backup_panel.directory, ui_text('tooltip.backup_directory')),
    )
    for widget, text in fields:
        widget.setToolTip(text)
    from PySide6.QtWidgets import QCheckBox

    for widget in window.findChildren(QCheckBox):
        if widget.objectName().startswith('advanced_'):
            widget.setToolTip(ui_text('tooltip.advanced'))

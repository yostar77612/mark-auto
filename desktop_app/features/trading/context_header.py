"""A single-line trading context with the existing detailed read models in a dialog."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QToolButton, QVBoxLayout

from desktop_app.strings.catalog import ui_text
from quantlab.trading.domain.models import Environment


def install_context_header(window):
    outer = window.centralWidget().layout()
    header, summary_row = outer.itemAt(0).layout(), outer.itemAt(1).layout()
    header.removeWidget(window.context)
    for widget in (window.summary, window.research_job, window.cancel_research_button):
        summary_row.removeWidget(widget)
    outer.takeAt(1)
    outer.removeWidget(window.notice)
    window.context_details = QDialog(window)
    window.context_details.setObjectName('trading_context_details')
    window.context_details.setWindowTitle(ui_text('m1u.header_details'))
    window.context_details.resize(720, 190)
    details = QVBoxLayout(window.context_details)
    for widget in (window.context, window.summary, window.notice):
        details.addWidget(widget)
    window.compact_context = QToolButton()
    window.compact_context.setObjectName('trading_compact_context')
    window.compact_context.setAccessibleName(ui_text('v2.persistent_context'))
    window.compact_context.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    window.compact_context.setMaximumHeight(36)
    window.compact_context.clicked.connect(window.context_details.show)
    header.insertWidget(0, window.compact_context, 1)
    header.addWidget(window.research_job)
    header.addWidget(window.cancel_research_button)


def refresh_context_header(window, state):
    known = state.financial_facts_verified
    pnl = f'{state.daily_pnl:,.2f} TWD' if known and state.daily_pnl is not None else ui_text('watch.unknown')
    risk = f'{state.remaining_risk:,.2f} TWD' if known and state.remaining_risk is not None else ui_text('watch.unknown')
    today = datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Taipei')).strftime('%m/%d')
    simulated = state.trading_day[-5:].replace('-', '/') or ui_text('v2.context_unknown_day')
    dates = ui_text('m2t.local_dates').format(today, simulated) if state.environment is Environment.LOCAL else ui_text('m2t.today').format(today)
    window.compact_context.setText(ui_text('m2t.header').format(window._environment_label(state.environment), dates, pnl, risk, len(state.issues)))
    details = [window.compact_context.text(), window.summary.text(), window.notice.text(), state.account_ref]
    if state.environment is Environment.LOCAL:
        details.append(ui_text('m1u.header').format(window._environment_label(state.environment), simulated, pnl, risk, len(state.issues)))
    window.compact_context.setToolTip('\n'.join(details))

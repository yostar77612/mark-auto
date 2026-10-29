"""Display-only privacy adapters. Raw exports and model roles never use these."""

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QToolTip, QWidget
from desktop_app.components.formatting import AMOUNTS
from desktop_app.strings.catalog import ui_text

MONEY_FIELDS = AMOUNTS | frozenset(
    (
        'equity',
        'price',
        'average_price',
        'open',
        'high',
        'low',
        'close',
        'cost',
        'fees',
        'pnl',
        'balance',
        'limit_price',
        'fill_price',
        'stop_price',
        'initial_margin_per_contract',
        'maintenance_margin_per_contract',
    )
)
ACCOUNT_FIELDS = frozenset(('account_id',))
ACCESS_ROLES = (Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.AccessibleTextRole, Qt.ItemDataRole.AccessibleDescriptionRole)


def mask_money(value):
    return '••••'


def mask_account_id(value):
    text = '' if value is None else str(value)
    return '••••' + (text[-4:] if len(text) > 4 else '')


def enabled(widget):
    state = getattr(widget.window(), 'privacy', None)
    return state is not None and state.enabled


def display(widget, value, key):
    if enabled(widget):
        if key in ACCOUNT_FIELDS:
            return mask_account_id(value)
        if key in MONEY_FIELDS:
            return mask_money(value)
    return value


def preview_text(text, private):
    """Redact structured export/detail previews without changing their source."""
    if not private:
        return text
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        # Unknown detail formats fail closed rather than echoing an amount.
        return mask_money(text) if text else text

    def redact(value, key=''):
        if key in ACCOUNT_FIELDS:
            return mask_account_id(value)
        if key in MONEY_FIELDS:
            return mask_money(value)
        if isinstance(value, dict):
            return {k: redact(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value

    return json.dumps(redact(value), ensure_ascii=False, sort_keys=True)


def item_display(table, item, key):
    """Cache display text outside Qt data roles; UserRole remains authoritative."""
    item._privacy_key = key
    item._privacy_raw = (item.text(), tuple(item.data(role) for role in ACCESS_ROLES))
    refresh_item(table, item)


def item_tooltip(table, item, text):
    raw, roles = item._privacy_raw
    item._privacy_raw = (raw, (text, *roles[1:]))
    refresh_item(table, item)


def refresh_item(table, item):
    if not hasattr(item, '_privacy_raw'):
        return
    text, roles = item._privacy_raw
    masked = display(table, text, item._privacy_key)
    item.setText(masked)
    for role, raw in zip(ACCESS_ROLES, roles):
        item.setData(role, masked if enabled(table) and item._privacy_key in MONEY_FIELDS | ACCOUNT_FIELDS else raw)


def bind_text(widget, render):
    """Keep the source renderer for immediate, query-free toggles."""
    widget._privacy_render = render
    render()


class PrivacyState:
    def __init__(self, window, layout, banner, *, compact=False):
        self.window = window
        self.enabled = False
        layout.removeWidget(banner)
        row = layout if compact else QHBoxLayout()
        row.addWidget(banner)
        self.toggle = QCheckBox(ui_text('privacy.toggle'))
        self.toggle.setObjectName('privacy_toggle')
        self.toggle.setAccessibleName(ui_text('privacy.toggle'))
        self.notice = QLabel(ui_text('privacy.exports_raw'))
        self.notice.setObjectName('privacy_export_notice')
        self.notice.setWordWrap(not compact)
        row.addWidget(self.toggle)
        row.addWidget(self.notice)
        if not compact:
            layout.insertLayout(0, row)
        self.toggle.toggled.connect(self.set_enabled)

    def restore(self, settings):
        self.toggle.setChecked(settings.get('privacy_mode') is True)

    def set_enabled(self, value):
        self.enabled = value is True
        QToolTip.hideText()
        for widget in self.window.findChildren(QWidget):
            if hasattr(widget, '_privacy_render'):
                widget._privacy_render()
            if hasattr(widget, 'rowCount') and hasattr(widget, 'columnCount') and hasattr(widget, 'item'):
                sorting = widget.isSortingEnabled()
                widget.setSortingEnabled(False)
                for r in range(widget.rowCount()):
                    for c in range(widget.columnCount()):
                        item = widget.item(r, c)
                        if item is not None:
                            refresh_item(widget, item)
                widget.setSortingEnabled(sorting)
            if hasattr(widget, '_privacy_preview_raw'):
                self._preview(widget, widget._privacy_preview_raw)
            if hasattr(widget, 'bar_details') or hasattr(widget, 'axis_labels'):
                widget.setToolTip('')
                widget.update()
        if self.window.settings is not None:
            settings = self.window.settings.load()
            settings['privacy_mode'] = self.enabled
            self.window.settings.save(settings)

    def attach_previews(self):
        for editor in self.window.findChildren(QPlainTextEdit):
            if editor.isReadOnly() and not hasattr(editor, '_privacy_render'):
                editor._privacy_preview_raw = editor.toPlainText()
                editor.textChanged.connect(lambda editor=editor: self._preview_changed(editor))

    def _preview_changed(self, editor):
        if not getattr(editor, '_privacy_writing', False):
            self._preview(editor, editor.toPlainText())

    def _preview(self, editor, text):
        editor._privacy_preview_raw = text
        editor._privacy_writing = True
        try:
            shown = preview_text(text, self.enabled)
            if editor.toPlainText() != shown:
                editor.setPlainText(shown)
        finally:
            editor._privacy_writing = False

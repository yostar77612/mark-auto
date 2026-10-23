"""Progressive disclosure for page explanations; input values stay untouched."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolButton, QWidget, QVBoxLayout, QPushButton, QSizePolicy
from desktop_strings import ui_text
import desktop_strings as _strings
from desktop_pages.preferences import disclosure_value, load_store


# Every relocated static explanation is still attached to its original widget.
MOVED_STRINGS = (
    'ui.settings_page.workspace_path',
    'ui.settings_page.state_path',
    'ui.settings_page.irreversible_records_hint',
    'ui.settings_page.log_path',
    'ui.settings_page.manual_update_hint',
    'chatgpt_ui.init.included_usage_hint',
    'automatic_backup.init.schedule_hint',
    'ui.compare_page.comparison_hint',
    'ui.backtest_page.strategy_hint',
    'ui.paper_page.reconciliation_hint',
    'ui.strategy_page.bounded_families_hint',
)
# Help widget identities predate semantic catalog keys and stay stable for
# accessibility consumers and snapshots. Only the lookup identifiers change.
_HELP_OBJECT_NAMES = {'help_' + new: 'help_' + old for old, new in _strings.TEXT_ALIASES.items() if new in MOVED_STRINGS}


def help_button(layout, key, text):
    button = QToolButton()
    button.setText(ui_text('help.symbol'))
    button.setObjectName(_HELP_OBJECT_NAMES.get('help_' + key, 'help_' + key))
    button.setAccessibleName(ui_text('help.accessible'))
    button.setToolTip(text)
    button.setProperty('themePart', 'helpButton')
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
    return button


def advanced_section(shell, page, name):
    layout = page.layout()
    toggle = QToolButton()
    toggle.setText(ui_text('ui.advanced.default_title'))
    toggle.setObjectName(name + '_help_advanced')
    toggle.setAccessibleName(ui_text('help.accessible'))
    toggle.setToolTip(ui_text('help.advanced'))
    toggle.setCheckable(True)
    box = QWidget()
    box.setObjectName(name + '_help_details')
    inner = QVBoxLayout(box)
    layout.addWidget(toggle)
    layout.addWidget(box)
    box.hide()
    toggle.toggled.connect(box.setVisible)
    key = name + ':help'
    shell._section_toggles[key] = toggle
    value = load_store(shell.settings)
    toggle.setChecked(disclosure_value(key, toggle, value.get('advanced_sections')))
    toggle.toggled.connect(lambda checked: shell._safe(shell._save_section_preferences))
    return inner


def install_page_help(shell):
    pages = {
        'data': shell.data_page,
        'strategy': shell.strategy_page,
        'backtest': shell.backtest_page,
        'compare': shell.compare_page,
        'paper': shell.paper_page,
        'market': shell.market.page_scroll.widget(),
        'settings': shell.settings_page,
    }
    shell.help_relocations = []
    texts = {
        'ui.settings_page.workspace_path': ui_text('ui.settings_page.workspace_path'),
        'ui.settings_page.state_path': ui_text('ui.settings_page.state_path'),
        'ui.settings_page.irreversible_records_hint': ui_text('ui.settings_page.irreversible_records_hint'),
        'ui.settings_page.log_path': ui_text('ui.settings_page.log_path'),
        'ui.settings_page.manual_update_hint': ui_text('ui.settings_page.manual_update_hint'),
        'chatgpt_ui.init.included_usage_hint': ui_text('chatgpt_ui.init.included_usage_hint'),
        'automatic_backup.init.schedule_hint': ui_text('automatic_backup.init.schedule_hint'),
        'ui.compare_page.comparison_hint': ui_text('ui.compare_page.comparison_hint'),
        'ui.backtest_page.strategy_hint': ui_text('ui.backtest_page.strategy_hint'),
        'ui.paper_page.reconciliation_hint': ui_text('ui.paper_page.reconciliation_hint'),
        'ui.strategy_page.bounded_families_hint': ui_text('ui.strategy_page.bounded_families_hint'),
        'ui.data_page.local_file_path': ui_text('ui.data_page.local_file_path'),
        'help.caption.file': ui_text('help.caption.file'),
        'ui.data_page.calendar_path': ui_text('ui.data_page.calendar_path'),
        'help.caption.calendar': ui_text('help.caption.calendar'),
        'ui_polish.install_polish.official_format': ui_text('ui_polish.install_polish.official_format'),
        'help.caption.source': ui_text('help.caption.source'),
        'ui_polish.install_polish.import_format': ui_text('ui_polish.install_polish.import_format'),
        'help.caption.format': ui_text('help.caption.format'),
        'ui_polish.install_polish.synthetic_bars': ui_text('ui_polish.install_polish.synthetic_bars'),
        'help.caption.bars': ui_text('help.caption.bars'),
        'ui_polish.install_polish.recent_days': ui_text('ui_polish.install_polish.recent_days'),
        'help.caption.days': ui_text('help.caption.days'),
        'ui.settings_page.next_workspace': ui_text('ui.settings_page.next_workspace'),
        'help.caption.workspace': ui_text('help.caption.workspace'),
        'ui.settings_page.backup_path': ui_text('ui.settings_page.backup_path'),
        'help.caption.backup': ui_text('help.caption.backup'),
    }
    hints = {
        'data': ui_text('help.hint.data'),
        'strategy': ui_text('redesign.strategy.page_hint'),
        'backtest': ui_text('help.hint.backtest'),
        'compare': ui_text('help.hint.compare'),
        'paper': ui_text('help.hint.paper'),
        'market': ui_text('help.hint.market'),
        'settings': ui_text('help.hint.settings'),
    }
    for name, page in pages.items():
        layout = page.layout()
        hint = QLabel(hints[name])
        hint.setObjectName(name + '_page_hint')
        hint.setProperty('page_hint', True)
        layout.insertWidget(1, hint)
        if name in ('strategy', 'data'):
            hint.hide()  # The task selector already owns the visible introduction.
        for key in MOVED_STRINGS:
            template = texts[key]
            prefix = template.split('{')[0]
            for label in page.findChildren(QLabel):
                if label.text() and (label.text() == template or ('{' in template and label.text().startswith(prefix))):
                    related_layout = label.parentWidget().layout()
                    button = help_button(related_layout, key, label.text())
                    position = related_layout.indexOf(label)
                    if position >= 0 and hasattr(related_layout, 'insertWidget'):
                        related_layout.removeWidget(button)
                        related_layout.insertWidget(position + 1, button, alignment=Qt.AlignmentFlag.AlignLeft)
                    button.setProperty('help_string_key', key)
                    label.hide()
                    shell.help_relocations.append((key, button))
        for key in ('ui.strategy_page.bounded_families_hint',) if name == 'strategy' else ('ui.backtest_page.strategy_hint',) if name == 'backtest' else ():
            button = help_button(layout, key, texts[key])
            button.setProperty('help_string_key', key)
            shell.help_relocations.append((key, button))
        # Compact field captions retain the complete previous caption on hover.
        for label in page.findChildren(QLabel):
            for key, short in CAPTIONS.get(name, ()):
                if label.text() == texts[key]:
                    label.setToolTip(label.text())
                    label.setAccessibleName(label.text())
                    label.setText(texts[short])
                    label.setProperty('help_string_key', key)
                    shell.help_relocations.append((key, label))
    data = shell.data_page
    details = advanced_section(shell, data, 'data')
    details.addWidget(data.overview)
    settings = shell.settings_page
    # Settings now owns its path disclosure inside the General section.
    shell._section_toggles['settings:help'] = settings.paths_toggle
    value = load_store(shell.settings)
    settings.paths_toggle.setChecked(disclosure_value('settings:help', settings.paths_toggle, value.get('advanced_sections')))
    settings.paths_toggle.toggled.connect(lambda checked: shell._safe(shell._save_section_preferences))
    for label in settings.paths_advanced.findChildren(QLabel):
        if any(
            label.text().startswith(texts[key].split('{')[0])
            for key in ('ui.settings_page.workspace_path', 'ui.settings_page.state_path', 'ui.settings_page.log_path')
        ):
            label.show()
    market = shell.market
    market_details = advanced_section(shell, pages['market'], 'market')
    for widget in (
        market.source_status,
        market.message,
        market.indicator_summary,
        market.findChild(QLabel, 'market_vwap_disclosure'),
        market.trading_labels['strategy'].parentWidget(),
        market._indicator_widgets['MA'][0].parentWidget(),
    ):
        market_details.addWidget(widget)
    # Empty-state guidance already provides the short hint on these pages.
    for name in ('market', 'strategy', 'backtest', 'compare', 'paper'):
        empty = shell.findChild(QWidget, 'empty_' + name)
        if empty is not None:
            label = empty.findChild(QLabel)
            action = empty.findChild(QPushButton)
            action.setToolTip(label.text())
            shell.help_relocations.append(('onboarding.empty.' + name, action))
            label.hide()
    # Keep comparison tables useful while recovering the T8 one-window budget.
    shell.compare_page.layout().setSpacing(4)


CAPTIONS = {
    'data': (
        ('ui.data_page.local_file_path', 'help.caption.file'),
        ('ui.data_page.calendar_path', 'help.caption.calendar'),
        ('ui_polish.install_polish.official_format', 'help.caption.source'),
        ('ui_polish.install_polish.import_format', 'help.caption.format'),
        ('ui_polish.install_polish.synthetic_bars', 'help.caption.bars'),
        ('ui_polish.install_polish.recent_days', 'help.caption.days'),
    ),
    'settings': (
        ('ui.settings_page.next_workspace', 'help.caption.workspace'),
        ('ui.settings_page.backup_path', 'help.caption.backup'),
    ),
}

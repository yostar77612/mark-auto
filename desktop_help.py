"""Progressive disclosure for page explanations; input values stay untouched."""
from PySide6.QtWidgets import QLabel, QToolButton, QWidget, QVBoxLayout, QPushButton
from desktop_strings import ui_text


# Every relocated static explanation is still attached to its original widget.
MOVED_STRINGS = (
    'ui._settings_page.text_2', 'ui._settings_page.text_3',
    'ui._settings_page.text_4', 'ui._settings_page.text_5',
    'ui._settings_page.text_16', 'chatgpt_ui.__init__.text_3',
    'automatic_backup.__init__.text_5', 'ui._compare_page.text_2',
    'ui._backtest_page.text_2', 'ui._paper_page.text_2',
    'ui._strategy_page.text_3',
)


def help_button(layout, key, text):
    button = QToolButton()
    button.setText(ui_text('help.symbol'))
    button.setObjectName('help_' + key)
    button.setAccessibleName(ui_text('help.accessible'))
    button.setToolTip(text)
    layout.addWidget(button)
    return button


def advanced_section(shell, page, name):
    layout = page.layout()
    toggle = QToolButton()
    toggle.setText(ui_text('ui.advanced.default_title'))
    toggle.setObjectName(name + '_help_advanced')
    toggle.setAccessibleName(ui_text('help.accessible'))
    toggle.setToolTip(ui_text('help.advanced'))
    toggle.setCheckable(True)
    box = QWidget(); box.setObjectName(name + '_help_details')
    inner = QVBoxLayout(box)
    layout.addWidget(toggle); layout.addWidget(box)
    box.hide(); toggle.toggled.connect(box.setVisible)
    key = name + ':help'
    shell._section_toggles[key] = toggle
    toggle.toggled.connect(lambda checked: shell._safe(shell._save_section_preferences))
    value = shell.settings.load() if shell.settings else {}
    toggle.setChecked(value.get('advanced_sections', {}).get(key) is True)
    return inner


def install_page_help(shell):
    pages = {
        'data': shell.data_page, 'strategy': shell.strategy_page,
        'backtest': shell.backtest_page, 'compare': shell.compare_page,
        'paper': shell.paper_page, 'market': shell.market.page_scroll.widget(),
        'settings': shell.settings_page,
    }
    shell.help_relocations = []
    texts = {
        'ui._settings_page.text_2': ui_text('ui._settings_page.text_2'),
        'ui._settings_page.text_3': ui_text('ui._settings_page.text_3'),
        'ui._settings_page.text_4': ui_text('ui._settings_page.text_4'),
        'ui._settings_page.text_5': ui_text('ui._settings_page.text_5'),
        'ui._settings_page.text_16': ui_text('ui._settings_page.text_16'),
        'chatgpt_ui.__init__.text_3': ui_text('chatgpt_ui.__init__.text_3'),
        'automatic_backup.__init__.text_5': ui_text('automatic_backup.__init__.text_5'),
        'ui._compare_page.text_2': ui_text('ui._compare_page.text_2'),
        'ui._backtest_page.text_2': ui_text('ui._backtest_page.text_2'),
        'ui._paper_page.text_2': ui_text('ui._paper_page.text_2'),
        'ui._strategy_page.text_3': ui_text('ui._strategy_page.text_3'),
        'ui._data_page.text_7': ui_text('ui._data_page.text_7'),
        'help.caption.file': ui_text('help.caption.file'),
        'ui._data_page.text_9': ui_text('ui._data_page.text_9'),
        'help.caption.calendar': ui_text('help.caption.calendar'),
        'ui_polish.install_polish.text_1': ui_text('ui_polish.install_polish.text_1'),
        'help.caption.source': ui_text('help.caption.source'),
        'ui_polish.install_polish.text_2': ui_text('ui_polish.install_polish.text_2'),
        'help.caption.format': ui_text('help.caption.format'),
        'ui_polish.install_polish.text_3': ui_text('ui_polish.install_polish.text_3'),
        'help.caption.bars': ui_text('help.caption.bars'),
        'ui_polish.install_polish.text_4': ui_text('ui_polish.install_polish.text_4'),
        'help.caption.days': ui_text('help.caption.days'),
        'ui._settings_page.text_6': ui_text('ui._settings_page.text_6'),
        'help.caption.workspace': ui_text('help.caption.workspace'),
        'ui._settings_page.text_11': ui_text('ui._settings_page.text_11'),
        'help.caption.backup': ui_text('help.caption.backup'),
    }
    hints = {
        'data': ui_text('help.hint.data'),
        'strategy': ui_text('help.hint.strategy'),
        'backtest': ui_text('help.hint.backtest'),
        'compare': ui_text('help.hint.compare'),
        'paper': ui_text('help.hint.paper'),
        'market': ui_text('help.hint.market'),
        'settings': ui_text('help.hint.settings'),
    }
    for name, page in pages.items():
        layout = page.layout()
        hint = QLabel(hints[name])
        hint.setObjectName(name + '_page_hint'); hint.setProperty('page_hint', True)
        layout.insertWidget(1, hint)
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
                        related_layout.insertWidget(position + 1, button)
                    button.setProperty('help_string_key', key)
                    label.hide()
                    shell.help_relocations.append((key, button))
        # Compact field captions retain the complete previous caption on hover.
        for label in page.findChildren(QLabel):
            for key, short in CAPTIONS.get(name, ()):
                if label.text() == texts[key]:
                    label.setToolTip(label.text()); label.setAccessibleName(label.text())
                    label.setText(texts[short])
                    label.setProperty('help_string_key', key)
                    shell.help_relocations.append((key, label))
    data = shell.data_page
    details = advanced_section(shell, data, 'data')
    details.addWidget(data.overview)
    settings = shell.settings_page
    # Settings now owns its path disclosure inside the General section.
    shell._section_toggles['settings:help'] = settings.paths_toggle
    settings.paths_toggle.toggled.connect(lambda checked: shell._safe(shell._save_section_preferences))
    value = shell.settings.load() if shell.settings else {}
    settings.paths_toggle.setChecked(value.get('advanced_sections', {}).get('settings:help') is True)
    for label in settings.paths_advanced.findChildren(QLabel):
        if any(label.text().startswith(texts[key].split('{')[0]) for key in (
                'ui._settings_page.text_2', 'ui._settings_page.text_3', 'ui._settings_page.text_5')):
            label.show()
    market = shell.market
    market_details = advanced_section(shell, pages['market'], 'market')
    for widget in (market.source_status, market.message, market.indicator_summary,
                   market.findChild(QLabel, 'market_vwap_disclosure'),
                   market.trading_labels['strategy'].parentWidget(),
                   market._indicator_widgets['MA'][0].parentWidget()):
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
        ('ui._data_page.text_7', 'help.caption.file'),
        ('ui._data_page.text_9', 'help.caption.calendar'),
        ('ui_polish.install_polish.text_1', 'help.caption.source'),
        ('ui_polish.install_polish.text_2', 'help.caption.format'),
        ('ui_polish.install_polish.text_3', 'help.caption.bars'),
        ('ui_polish.install_polish.text_4', 'help.caption.days'),
    ),
    'settings': (
        ('ui._settings_page.text_6', 'help.caption.workspace'),
        ('ui._settings_page.text_11', 'help.caption.backup'),
    ),
}

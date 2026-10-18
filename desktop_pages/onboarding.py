"""Read-only workflow guidance; completion comes from persisted app state."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from desktop_strings import ui_text
from desktop_theme import set_theme_property
from quantlab.paper import PaperBroker
import sqlite3


# Original page identities remain stable even when their visual order changes.
WORKFLOW_ORDER = (1, 2, 3, 4, 5, 0, 6)


class GettingStarted(QWidget):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.setObjectName('getting_started')
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel(ui_text('onboarding.title')))
        dismiss = QPushButton(ui_text('onboarding.dismiss'))
        dismiss.setObjectName('onboarding_dismiss')
        dismiss.clicked.connect(lambda: self.set_dismissed(True))
        header.addWidget(dismiss); layout.addLayout(header)
        self.labels = []
        self.buttons = []
        captions = {
            'data': ui_text('onboarding.data'),
            'strategy': ui_text('onboarding.strategy'),
            'backtest': ui_text('onboarding.backtest'),
            'compare': ui_text('onboarding.compare'),
            'paper': ui_text('onboarding.paper'),
        }
        for index, page in enumerate(('data', 'strategy', 'backtest', 'compare', 'paper')):
            row = QHBoxLayout()
            label = QLabel(); label.setObjectName('onboarding_status_' + page)
            button = QPushButton(captions[page])
            button.setObjectName('onboarding_go_' + page)
            button.clicked.connect(lambda checked=False, target=index: self.go(target))
            row.addWidget(label); row.addWidget(button); layout.addLayout(row)
            self.labels.append(label); self.buttons.append(button)
        self.refresh()
        self.restore_visibility()

    def restore_visibility(self):
        value = self.shell.settings.load() if self.shell.settings else {}
        self.setVisible(not value.get('onboarding_dismissed', False) and not any(self.completed))

    def go(self, index):
        self.shell.navigation.setCurrentRow(index)

    def set_dismissed(self, dismissed):
        if self.shell.settings:
            value = self.shell.settings.load()
            value['onboarding_dismissed'] = dismissed
            self.shell.settings.save(value)
        self.setVisible(not dismissed)
        self.refresh()

    def refresh(self):
        shell, root = self.shell, self.shell.root
        account_ready = False
        if (root / 'paper.sqlite3').is_file():
            try:
                account_ready = bool(PaperBroker.read_snapshot(root / 'paper.sqlite3').get('account_id'))
            except (OSError, ValueError, sqlite3.Error):
                pass
        self.completed = (
            bool(getattr(shell, '_dataset_ready', False)),
            (root / 'active_candidate.json').is_file() or (root / 'selection.json').is_file(),
            shell.result_choice.count() > 0,
            bool(shell.comparison_list.selectedItems()) or (root / 'selection.json').is_file(),
            account_ready,
        )
        for index, (label, done) in enumerate(zip(self.labels, self.completed), 1):
            from desktop_presentation import display_number
            label.setText(ui_text('onboarding.step').format(display_number(index, 'count'),
                          (ui_text('onboarding.done') if done else ui_text('onboarding.pending'))))
        empty = (not bool(getattr(shell.market, '_quote_series', ())),
                 shell.candidate_choice.count() == 0, shell.result_choice.count() == 0,
                 shell.comparison_list.count() == 0, not self.completed[4])
        for widget, visible in zip(getattr(self, 'empty_states', ()), empty):
            widget.setVisible(visible)
            set_theme_property(widget.findChild(QPushButton), 'role', 'primary' if visible else 'secondary')
        # An empty result panel has one primary next action.
        for name, is_empty in (('run_campaign', empty[1]), ('run_backtest', empty[2]),
                               ('compare_results', empty[3]), ('paper_submit', empty[4])):
            set_theme_property(shell.findChild(QPushButton, name), 'role', 'secondary' if is_empty else 'primary')


def install_onboarding(shell):
    items = [shell.navigation.takeItem(0) for _ in range(shell.navigation.count())]
    pages = [shell.stack.widget(index) for index in range(shell.stack.count())]
    for page in pages:
        shell.stack.removeWidget(page)
    hints = (
        ui_text('onboarding.hint.0'),
        ui_text('onboarding.hint.1'),
        ui_text('onboarding.hint.2'),
        ui_text('onboarding.hint.3'),
        ui_text('onboarding.hint.4'),
        ui_text('onboarding.hint.5'),
        ui_text('onboarding.hint.6'),
    )
    for old_index in WORKFLOW_ORDER:
        item = items[old_index]
        item.setToolTip(hints[old_index])
        shell.navigation.addItem(item); shell.stack.addWidget(pages[old_index])
    shell.onboarding = GettingStarted(shell)
    shell.page_state.onboarding = shell.onboarding
    outer = shell.centralWidget().layout()
    outer.insertWidget(1, shell.onboarding)
    help_button = QPushButton(ui_text('onboarding.help'))
    help_button.setObjectName('onboarding_help')
    help_button.setToolTip(ui_text('onboarding.glossary'))
    help_button.clicked.connect(lambda: shell.onboarding.set_dismissed(False))
    outer.insertWidget(1, help_button)
    targets = (shell.market.page_scroll.widget(), shell.strategy_page.tabs.widget(1).widget(),
               shell.backtest_page, shell.compare_page, shell.paper_page)
    callbacks = (lambda: shell.navigation.setCurrentRow(0),
                 lambda: shell.strategy_page.tabs.setCurrentIndex(0),
                 lambda: shell.navigation.setCurrentRow(0 if not shell._dataset_ready else 1),
                 lambda: shell.navigation.setCurrentRow(2),
                 lambda: shell.navigation.setCurrentRow(0))
    guidance = {
        'market': (ui_text('onboarding.empty.market'), ui_text('onboarding.next.market')),
        'strategy': (ui_text('onboarding.empty.strategy'), ui_text('onboarding.next.strategy')),
        'backtest': (ui_text('onboarding.empty.backtest'), ui_text('onboarding.next.backtest')),
        'compare': (ui_text('onboarding.empty.compare'), ui_text('onboarding.next.compare')),
        'paper': (ui_text('onboarding.empty.paper'), ui_text('onboarding.next.paper')),
    }
    shell.onboarding.empty_states = []
    for key, parent, callback in zip(('market', 'strategy', 'backtest', 'compare', 'paper'), targets, callbacks):
        box = QWidget(); box.setObjectName('empty_' + key)
        layout = QVBoxLayout(box)
        label = QLabel(guidance[key][0]); label.setWordWrap(True)
        layout.addWidget(label)
        button = QPushButton(guidance[key][1])
        button.setObjectName('empty_' + key + '_action'); button.setProperty('role', 'primary')
        button.clicked.connect(callback); layout.addWidget(button)
        parent.layout().insertWidget(1, box)
        shell.onboarding.empty_states.append(box)
    shell.comparison_list.itemSelectionChanged.connect(shell.onboarding.refresh)
    shell.use_candidate_button.clicked.connect(shell.onboarding.refresh)
    shell.onboarding.refresh()

"""Read-only workflow guidance; completion comes from persisted app state."""

from PySide6.QtWidgets import QWidget, QDialog, QBoxLayout, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from desktop_app.strings.catalog import ui_text
from desktop_app.components.async_status import AsyncStatus
from desktop_app.features.onboarding.quick_start import QuickStart
from desktop_app.features.settings.preferences import load_store
from desktop_app.shell.palette_commands import MOUNT_PAGE_ORDER, page_index, register_pages
from desktop_app.shell.theme import set_theme_property
from quantlab.paper import PaperBroker
import sqlite3


# Legacy construction positions mapped to the unchanged default visual order.
# Identities are captured before this positional compatibility mapping is applied.
WORKFLOW_ORDER = (1, 2, 3, 4, 5, 0, 6)


class GettingStarted(QWidget):
    def __init__(self, shell):
        super().__init__(shell if isinstance(shell, QWidget) else None)
        self.shell = shell
        self._dismissed = False
        self.setObjectName('getting_started')
        self.setMaximumHeight(40)
        self.setMinimumWidth(1)  # let narrow windows shrink the strip instead of forcing a wider window
        self.setToolTip(ui_text('onboarding.title'))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        dismiss = QPushButton(ui_text('onboarding.dismiss'))
        dismiss.setObjectName('onboarding_dismiss')
        dismiss.clicked.connect(lambda: self.set_dismissed(True))
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
            button = QPushButton(captions[page])
            # Preserve status-label lookup for automation; the visible chip includes its text.
            label = QLabel(button)
            label.setObjectName('onboarding_status_' + page)
            label.hide()
            button.setObjectName('onboarding_go_' + page)
            button.setProperty('onboardingCaption', captions[page])
            set_theme_property(button, 'role', 'onboardingChip')
            button.clicked.connect(lambda checked=False, target=index: self.go(target))
            layout.addWidget(button)
            self.labels.append(label)
            self.buttons.append(button)
        layout.addStretch()
        layout.addWidget(dismiss)
        self.refresh()

    def restore_visibility(self):
        settings = getattr(self.shell, 'settings', None)
        value = load_store(settings)
        self._dismissed = value.get('onboarding_dismissed', self._dismissed)
        self.setVisible(not self._dismissed and not any(self.completed))

    def go(self, index):
        self.shell.navigation.setCurrentRow(index)

    def set_dismissed(self, dismissed):
        self._dismissed = dismissed
        settings = getattr(self.shell, 'settings', None)
        if settings:
            value = settings.load()
            value['onboarding_dismissed'] = dismissed
            settings.save(value)
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
            getattr(getattr(shell, 'result_choice', None), 'count', lambda: 0)() > 0,
            bool(getattr(getattr(shell, 'comparison_list', None), 'selectedItems', lambda: ())()) or (root / 'selection.json').is_file(),
            account_ready,
        )
        for index, (label, done) in enumerate(zip(self.labels, self.completed), 1):
            # Load presentation formatting when refreshing status labels.
            from desktop_app.components.formatting import display_number

            label.setText(
                ui_text('onboarding.step').format(display_number(index, 'count'), (ui_text('onboarding.done') if done else ui_text('onboarding.pending')))
            )
            button = self.buttons[index - 1]
            button.setText(
                ui_text('onboarding.step').format(button.property('onboardingCaption'), ui_text('onboarding.done') if done else ui_text('onboarding.pending'))
            )
            set_theme_property(button, 'state', 'done' if done else 'pending')
            button.setMinimumWidth(button.sizeHint().width())
        empty = (
            not bool(getattr(getattr(shell, 'market', None), '_quote_series', ())),
            getattr(getattr(shell, 'candidate_choice', None), 'count', lambda: 0)() == 0,
            getattr(getattr(shell, 'result_choice', None), 'count', lambda: 0)() == 0,
            getattr(getattr(shell, 'comparison_list', None), 'count', lambda: 0)() == 0,
            not self.completed[4],
        )
        for widget, visible in zip(getattr(self, 'empty_states', ()), empty):
            widget.setVisible(visible)
            set_theme_property(widget.findChild(QPushButton), 'role', 'primary' if visible else 'secondary')
        # An empty result panel has one primary next action.
        for name, is_empty in (
            ('run_campaign', empty[1] or bool(getattr(shell, '_candidate_valid', False))),
            ('run_backtest', empty[2]),
            ('compare_results', empty[3]),
            ('paper_submit', empty[4]),
            ('paper_replay', empty[4]),
        ):
            button = shell.findChild(QPushButton, name) if isinstance(shell, QWidget) else None
            if button is not None:
                set_theme_property(button, 'role', 'secondary' if is_empty else 'primary')
        self.restore_visibility()


def install_onboarding(shell):
    register_pages(shell, MOUNT_PAGE_ORDER)
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
        shell.navigation.addItem(item)
        shell.stack.addWidget(pages[old_index])
    # Comparison remains the same page/shortcut, reached from saved results.
    # The primary sidebar follows data -> strategy -> backtest -> paper.
    shell.navigation.item(page_index(shell, 'compare')).setHidden(True)
    captions = {
        'data': ui_text('redesign.nav.data'),
        'strategy': ui_text('redesign.nav.strategy'),
        'backtest': ui_text('redesign.nav.backtest'),
        'compare': ui_text('redesign.nav.compare'),
        'paper': ui_text('redesign.nav.paper'),
        'market': ui_text('redesign.nav.market'),
        'settings': ui_text('redesign.nav.settings'),
    }
    for page_id, caption in captions.items():
        shell.navigation.item(page_index(shell, page_id)).setText(caption)
    shell.onboarding = GettingStarted(shell)
    shell.page_state.onboarding = shell.onboarding
    outer = shell.centralWidget().layout()
    quick_row = QWidget(shell)
    shell.quick_start = QuickStart(shell, QHBoxLayout(quick_row))
    outer.insertWidget(1, shell.onboarding)
    help_button = QPushButton(ui_text('onboarding.help'))
    help_button.setObjectName('onboarding_help')
    help_button.setToolTip(ui_text('onboarding.glossary'))
    shell.guide_dialog = QDialog(shell)
    shell.guide_dialog.setWindowTitle(ui_text('redesign.guide.title'))
    shell.guide_dialog.resize(660, 220)
    guide = QVBoxLayout(shell.guide_dialog)
    description = QLabel(ui_text('redesign.guide.description'))
    description.setWordWrap(True)
    guide.addWidget(description)
    guide.addWidget(quick_row)

    def show_guide():
        shell.onboarding.set_dismissed(False)
        shell.guide_dialog.show()
        shell.guide_dialog.raise_()

    help_button.clicked.connect(show_guide)
    shell.app_header.layout().addWidget(help_button)
    targets = (shell.market.page_scroll.widget(), shell.strategy_page.tabs.widget(1).widget(), shell.backtest_page, shell.compare_page, shell.paper_page)
    callbacks = (
        lambda: shell.navigation.setCurrentRow(0),
        lambda: shell.strategy_page.tabs.setCurrentIndex(0),
        lambda: shell.navigation.setCurrentRow(0 if not shell._dataset_ready else 1),
        lambda: shell.navigation.setCurrentRow(2),
        lambda: shell.navigation.setCurrentRow(0),
    )
    guidance = {
        'market': (ui_text('onboarding.empty.market'), ui_text('onboarding.next.market')),
        'strategy': (ui_text('onboarding.empty.strategy'), ui_text('onboarding.next.strategy')),
        'backtest': (ui_text('onboarding.empty.backtest'), ui_text('onboarding.next.backtest')),
        'compare': (ui_text('onboarding.empty.compare'), ui_text('onboarding.next.compare')),
        'paper': (ui_text('onboarding.empty.paper'), ui_text('onboarding.next.paper')),
    }
    shell.onboarding.empty_states = []
    for key, parent, callback in zip(('market', 'strategy', 'backtest', 'compare', 'paper'), targets, callbacks):
        box = AsyncStatus()
        box.setObjectName('empty_' + key)
        box.action.setObjectName('empty_' + key + '_action')
        box.set_state('empty', message=guidance[key][0], action_text=guidance[key][1], action=callback)
        box.layout().setDirection(QBoxLayout.Direction.LeftToRight)
        box.layout().setContentsMargins(0, 2, 0, 2)
        box.layout().setStretch(0, 1)
        parent.layout().insertWidget(1, box)
        shell.onboarding.empty_states.append(box)
    shell.comparison_list.itemSelectionChanged.connect(shell.onboarding.refresh)
    shell.use_candidate_button.clicked.connect(shell.onboarding.refresh)
    shell.onboarding.refresh()

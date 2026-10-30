from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services
from PySide6.QtWidgets import QWidget, QTabBar, QTabWidget
from tests.t10_fixture import WindowFixture
from desktop_app.shell.accessibility import INTERACTIVE, visual_focus_order
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6
import unittest

from desktop_app.features.market.dashboard import MarketDashboard
from desktop_app.shell.theme import apply_market_theme, build_market_stylesheet
from desktop_app.strings.catalog import ZH_TW, ui_text

from pathlib import Path
import tempfile
from time import perf_counter
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QScrollArea, QPushButton
from tests.test_t9_onboarding import sandbox_ui


class CompleteOffscreenWalkTests(unittest.TestCase):
    """U10: one unshown window, bounded tree walks, no workers or network."""

    COVERED_PAGES = {'DataPage', 'StrategyPage', 'BacktestPage', 'ComparePage', 'PaperPage', 'MarketPage', 'SettingsPage'}

    @classmethod
    def setUpClass(cls):
        from desktop_app.shell.window import MainWindow
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore

        cls.started = perf_counter()
        cls.app = QApplication.instance() or QApplication([])
        for target in ('socket.socket', 'socket.create_connection'):
            guard = patch(target, side_effect=AssertionError('The accessibility walk must stay offline.'))
            guard.start()
            cls.addClassCleanup(guard.stop)
        cls.context = sandbox_ui()
        cls.context.__enter__()
        cls.addClassCleanup(cls.context.__exit__, None, None, None)
        cls.folder = tempfile.TemporaryDirectory(prefix='u10-access-')
        cls.addClassCleanup(cls.folder.cleanup)
        paths = AppPaths(Path(cls.folder.name) / 'workspace').ensure()
        cls.jobs = JobManager(paths)
        cls.addClassCleanup(cls.jobs.close)
        guard = patch.object(cls.jobs, 'start', side_effect=AssertionError('The accessibility walk must not start jobs.'))
        guard.start()
        cls.addClassCleanup(guard.stop)
        cls.window = MainWindow(paths, cls.jobs, SettingsStore(paths.state / 'settings.json'), services=_c_create_ui_services(_c_create_operation_ports()))
        cls.addClassCleanup(shiboken6.delete, cls.window)
        cls.addClassCleanup(cls.window.close)
        for timer in cls.window.findChildren(QTimer):
            timer.stop()
        from desktop_app.features.paper.paper_tabs import open_timeline
        from desktop_app.features.paper.paper import stop_dialog

        paper = cls.window.paper_page
        open_timeline(paper, paper.findChild(QTabWidget, 'paper_account_tabs'))
        cls.popout = cls.window.market.popout.open(visible=False)
        cls.addClassCleanup(shiboken6.delete, cls.popout)
        cls.addClassCleanup(cls.popout.close)
        cls.dialog = stop_dialog(cls.window, '')
        cls.addClassCleanup(shiboken6.delete, cls.dialog)
        cls.window.settings_page.assistant_panel.reply('```python\npass\n```')

    def pages(self):
        for index in range(self.window.stack.count()):
            container = self.window.stack.widget(index)
            yield container.widget() if isinstance(container, QScrollArea) else container

    def logical_controls(self, page):
        """Qt popup views, headers and embedded editors belong to their owner."""
        for widget in page.findChildren(QWidget):
            if not isinstance(widget, INTERACTIVE):
                continue
            parent = widget.parentWidget()
            while parent is not None and parent is not page and not isinstance(parent, INTERACTIVE):
                parent = parent.parentWidget()
            if parent is None or parent is page:
                yield widget

    def assert_mount_coverage(self):
        self.assertEqual({type(page).__name__ for page in self.pages()}, self.COVERED_PAGES)
        self.assertEqual(self.window.stack.count(), len(self.COVERED_PAGES))
        self.assertEqual(self.window.navigation.count(), len(self.COVERED_PAGES))

    def test_mount_registry_guard(self):
        self.assert_mount_coverage()
        self.assertTrue(self.window.settings_page.isAncestorOf(self.window.settings_page.assistant_panel))
        self.assertTrue(self.window.findChild(QPushButton, 'synthetic_quick_start').accessibleName())
        self.assertEqual(self.window.app_header.job.accessibleName(), ui_text('access.header_job'))
        extra = QWidget()
        self.window._mount_page(extra, ui_text('access.field'))
        try:
            with self.assertRaises(AssertionError):
                self.assert_mount_coverage()
        finally:
            container = self.window.stack.widget(self.window.stack.count() - 1)
            self.window.stack.removeWidget(container)
            self.window.navigation.takeItem(self.window.navigation.count() - 1)
            shiboken6.delete(container)
        self.assert_mount_coverage()

    def test_dynamic_names_audit(self):
        w = self.window
        roots = [*self.pages(), w.app_header, w.command_palette, w.notification_center, self.popout, self.dialog]
        offenders = []
        for root in roots:
            for widget in root.findChildren(QWidget):
                if isinstance(widget, INTERACTIVE) and not widget.accessibleName().strip():
                    offenders.append((type(root).__name__, type(widget).__name__, widget.objectName()))
                if isinstance(widget, QTabBar):
                    for index in range(widget.count()):
                        if not widget.accessibleTabName(index).strip():
                            offenders.append((type(root).__name__, 'tab', widget.tabText(index)))
        self.assertEqual(offenders, [])
        self.assertTrue(self.window.paper_page.timeline_filter.accessibleName())
        self.assertTrue(self.window.paper_page.replay_controls.button.accessibleName())

    def test_next_step_hint_has_catalog_accessible_text(self):
        from desktop_app.components.async_status import AsyncStatus
        from desktop_app.components.error_guidance import next_step

        status = self.window.findChildren(AsyncStatus)[0]
        status.set_state('error', error_code='validation_failed')
        self.assertEqual(status.label.accessibleName(), status.label.text())
        self.assertIn(next_step('validation_failed'), status.label.accessibleName())
        self.assertNotIn('\u003f\u003f\u003f', status.label.accessibleName())
        status.set_state('empty')

    def test_no_focus_audit(self):
        no_focus = {'assistant_completions': 'Arrow keys in the input select completions; focus stays in the input.'}
        offenders = []
        for page in [*self.pages(), self.window.app_header, self.window.command_palette, self.window.notification_center, self.popout, self.dialog]:
            for widget in self.logical_controls(page):
                if widget.focusPolicy() == Qt.FocusPolicy.NoFocus and widget.objectName() not in no_focus:
                    offenders.append((type(page).__name__, type(widget).__name__, widget.objectName(), widget.accessibleName()))
        self.assertEqual(offenders, [])

    def test_duplicate_names_audit(self):
        from collections import defaultdict

        # Exact upper bounds preserve context-scoped names without allowing new
        # ambiguous controls. Dates belong to separately labelled DateInputs;
        # other repeats live in distinct form panels, tabs or disclosure bodies.
        allowed = {
            ('DataPage', ui_text('access.editor')): (2, 'Separate read-only data panels.'),
            ('StrategyPage', ui_text('forms.init.results_accessible_name')): (5, 'Distinct result tabs.'),
            ('StrategyPage', ui_text('access.editor')): (8, 'Distinct preview and diagnostic panels.'),
            ('StrategyPage', ui_text('ui.advanced.default_title')): (2, 'Separate research form disclosures.'),
            ('BacktestPage', ui_text('timeinput.set')): (3, 'Individually labelled DateInput owners.'),
            ('BacktestPage', ui_text('timeinput.taipei')): (3, 'Individually labelled DateInput owners.'),
            ('PaperPage', ui_text('access.table')): (2, 'Policy risk sessions and margin schedule panels.'),
            ('PaperPage', ui_text('forms.init.add_row')): (2, 'One row action per policy table.'),
            ('PaperPage', ui_text('forms.init.remove_row')): (2, 'One row action per policy table.'),
            ('PaperPage', ui_text('forms.init.results_accessible_name')): (3, 'Separate snapshot result tables.'),
            ('PaperPage', ui_text('forms.init.explicit_contract')): (2, 'Intent and quote form context.'),
            ('PaperPage', ui_text('timeinput.set')): (6, 'Individually labelled DateInput owners.'),
            ('PaperPage', ui_text('timeinput.taipei')): (6, 'Individually labelled DateInput owners.'),
            ('SettingsPage', ui_text('help.accessible')): (8, 'Help buttons announce the associated field through their description.'),
            ('SettingsPage', ui_text('assistant.permission_label')): (2, 'Settings and assistant share the permission model.'),
            ('SettingsPage', ui_text('assistant.thinking')): (2, 'Disclosure and its read-only body.'),
            ('SettingsPage', ui_text('assistant.code')): (2, 'Disclosure and its read-only code body.'),
            ('SettingsPage', ui_text('ui.settings_page.read_logs')): (2, 'Log action and its read-only output.'),
        }
        offenders = []
        for page in self.pages():
            names = defaultdict(list)
            for widget in self.logical_controls(page):
                names[widget.accessibleName()].append(widget.objectName())
            for name, controls in names.items():
                limit, reason = allowed.get((type(page).__name__, name), (1, 'Names must distinguish controls.'))
                if len(controls) > limit:
                    offenders.append((type(page).__name__, name, controls, reason))
        self.maxDiff = None
        self.assertEqual(offenders, [])

    def test_catalog_names_and_disabled_hints(self):
        import re
        import string

        # Catalog templates may contain runtime counts; only the literal parts
        # and format slots are accepted, never an arbitrary widget-derived name.
        formatter = string.Formatter()
        patterns = [
            re.compile(''.join(re.escape(text) + ('.*' if field is not None else '') for text, field, _, _ in formatter.parse(value)), re.S)
            for value in ZH_TW.values()
            if isinstance(value, str) and any(text.strip() for text, _, _, _ in formatter.parse(value))
        ]
        offenders = []
        for widget in self.window.findChildren(QWidget):
            if isinstance(widget, INTERACTIVE):
                name = widget.accessibleName().strip()
                if not name or '\u003f\u003f\u003f' in name or not any(pattern.fullmatch(name) for pattern in patterns):
                    offenders.append((type(widget).__name__, widget.objectName(), name))
        self.maxDiff = None
        self.assertEqual(offenders, [])
        self.assertTrue(self.window._disabled_hints)
        for hint in self.window._disabled_hints:
            if not hint.button.isEnabled():
                self.assertTrue(hint.button.accessibleName())
                self.assertIn(hint.label.text(), hint.button.toolTip())
                self.assertTrue(hint.button.toolTip().strip())

    def test_offscreen_focus_chain_has_no_orphans(self):
        w = self.window
        # Expand all existing disclosures without saving display preferences.
        w._restoring_sections = True
        for toggle in w._section_toggles.values():
            toggle.setChecked(True)
        for index, page in enumerate(self.pages()):
            w.navigation.setCurrentRow(index)
            tabs = page.findChildren(QTabWidget)
            variants = [(None, 0)] + [(tab, i) for tab in tabs for i in range(tab.count())]
            for tab, position in variants:
                if tab is not None:
                    tab.setCurrentIndex(position)
                w.accessible_layout.update_order()
                actions = (w.notification_center.button, w.cancel_button)
                header = [control for control in visual_focus_order(w.app_header) if control not in actions]
                expected = [w.navigation, *visual_focus_order(w.stack.currentWidget()), *header]
                expected.extend(control for control in (w.notification_center.button, w.cancel_button) if control.isEnabled() and control.isVisibleTo(w))
                self.assertEqual(len(expected), len(set(expected)))
                visible = {
                    control
                    for control in self.logical_controls(page)
                    if control.isVisibleTo(page) and control.isEnabled() and control.focusPolicy() & Qt.FocusPolicy.TabFocus
                }
                self.assertTrue(visible <= set(expected), [control.objectName() for control in visible - set(expected)])
                current = w.navigation.nextInFocusChain()
                actual, seen = [w.navigation], {w.navigation}
                while current not in seen:
                    seen.add(current)
                    if current in expected:
                        actual.append(current)
                    current = current.nextInFocusChain()
                self.assertEqual(actual, expected, (type(page).__name__, position))

    def test_pushbuttons_enter_and_space_without_dispatch(self):
        # Signal blocking keeps every existing confirmation/job callback intact
        # and uncalled; check-state transitions still prove Qt activation.
        from PySide6.QtCore import QSignalBlocker

        offenders = []
        for root in [*self.pages(), self.popout, self.dialog, self.window.notification_center]:
            for button in root.findChildren(QPushButton):
                if not button.isEnabled():
                    continue
                checkable, checked = button.isCheckable(), button.isChecked()
                group = button.group()
                exclusive = group.exclusive() if group is not None else False
                button.setFocus()
                with QSignalBlocker(button):
                    # Exclusive task selectors correctly keep their active task
                    # selected. This synthetic toggle probe temporarily removes
                    # exclusivity; the strategy keyboard test verifies real
                    # exclusive activation without blocking its signals.
                    if exclusive:
                        group.setExclusive(False)
                    try:
                        button.setCheckable(True)
                        for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
                            before = button.isChecked()
                            QTest.keyClick(button, key)
                            if button.isChecked() == before:
                                offenders.append((button.objectName(), button.accessibleName(), key))
                        button.setChecked(checked)
                        button.setCheckable(checkable)
                    finally:
                        if exclusive:
                            group.setExclusive(True)
        self.assertEqual(offenders, [])
        self.assertFalse(self.window.jobs.active)

    def test_keyboard_buttons_escape_and_privacy(self):
        from PySide6.QtTest import QSignalSpy
        from desktop_app.features.paper.paper import stop_dialog, stop_exposure_text

        w = self.window
        button = w.app_header.disclosure
        button.setFocus()
        spy = QSignalSpy(button.clicked)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
            QTest.keyClick(button, key)
        self.assertEqual(spy.count(), 2)
        palette = w.command_palette
        with patch.object(palette, 'hide', wraps=palette.hide) as close:
            QTest.keyClick(palette.filter, Qt.Key.Key_Escape)
            close.assert_called_once()
        with patch.object(w.notification_center, 'hide', wraps=w.notification_center.hide) as close:
            QTest.keyClick(w.notification_center.rows, Qt.Key.Key_Escape)
            close.assert_called_once()
        dialog = stop_dialog(w, '')
        self.addCleanup(shiboken6.delete, dialog)
        spy = QSignalSpy(dialog.rejected)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertEqual(spy.count(), 1)
        w.privacy.set_enabled(True)
        try:
            w.app_header.refresh()
            self.assertTrue(w.app_header.privacy_toggle.isChecked())
            self.assertNotIn('123456', stop_exposure_text({'positions': {'TMF': 123456}}, private=True))
            panel = w.settings_page.assistant_panel
            panel.append_transcript('123456')
            self.assertNotIn('123456', panel.transcript.toPlainText())
            self.assertFalse(w.paper_page.paper_confirm.isChecked())
            self.assertFalse(w.jobs.active)
        finally:
            w.privacy.set_enabled(False)

    def test_z_offscreen_small_time_bound(self):
        self.assertTrue(self.window.isHidden())
        self.assertTrue(self.popout.isHidden())
        self.assertLess(perf_counter() - self.started, 10, 'The complete U10 walk has a ten-second budget.')


class WorkspaceAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_workspace_controls_themes_font_and_keyboard_disclosure(self):
        page = MarketDashboard()
        try:
            workspace = page.workspace
            controls = [workspace.button, *(panel.handle for panel in workspace.panels.values())]
            for theme in ('dark', 'light'):
                page.setProperty('appearanceTheme', theme)
                apply_market_theme(page)
                self.assertIn('QToolButton:focus', build_market_stylesheet(theme))
                for factor in (1, 2):
                    font = QFont(page.font())
                    font.setPointSizeF(11 * factor)
                    page.setFont(font)
                    for control in controls:
                        control.ensurePolished()
                        self.assertTrue(control.accessibleName())
                        self.assertTrue(control.accessibleDescription())
                        self.assertTrue(control.toolTip())
                        self.assertTrue(control.focusPolicy() & Qt.FocusPolicy.TabFocus)
                        self.assertGreaterEqual(control.sizeHint().width(), control.fontMetrics().horizontalAdvance(control.text()))
            for key in workspace.preset_ids:
                workspace.actions[key].trigger()
                for panel in workspace.panels.values():
                    QTest.keyClick(panel.handle, Qt.Key.Key_C)
                    collapsed = panel.content.isHidden()
                    QTest.keyClick(panel.handle, Qt.Key.Key_C)
                    self.assertNotEqual(collapsed, panel.content.isHidden())
                    self.assertTrue(panel.handle.isVisibleTo(page))
            for size in ((1366, 768), (1280, 720), (1024, 600)):
                page.resize(*size)
                workspace.reset()
                self.assertTrue(all(panel.isVisibleTo(page) for panel in workspace.panels.values()))
                self.assertLessEqual(page.minimumWidth(), 1280)
            self.assertTrue({'save', 'reset', 'overview', 'chart_focus', 'watchlist_focus'} <= set(workspace.actions))
            self.assertIn(workspace.restore_menu.menuAction(), workspace.menu.actions())
            self.assertIn(workspace.delete_menu.menuAction(), workspace.menu.actions())
        finally:
            shiboken6.delete(page)


class AccessibilityWalkTests(WindowFixture):
    def test_all_controls_including_hidden_sections_have_names(self):
        offenders = []
        for widget in self.window.findChildren(QWidget):
            if isinstance(widget, INTERACTIVE) and not widget.accessibleName().strip():
                offenders.append((type(widget).__name__, widget.objectName()))
            if isinstance(widget, QTabBar):
                for index in range(widget.count()):
                    if not widget.accessibleTabName(index).strip():
                        offenders.append(('tab', widget.tabText(index)))
        self.assertEqual(offenders, [])

    def test_focus_chain_follows_visible_rows(self):
        w = self.window
        for index in range(7):
            w.navigation.setCurrentRow(index)
            self.settle()
            page = w.stack.currentWidget()
            tabs = page.findChildren(QTabWidget)
            variants = [(None, 0)] + [(tab, i) for tab in tabs for i in range(tab.count())]
            for tab, position in variants:
                if tab:
                    tab.setCurrentIndex(position)
                self.settle()
                expected = visual_focus_order(page)
                if not expected:
                    continue
                actual = []
                current = expected[0]
                for _ in range(len(w.findChildren(QWidget)) + 1):
                    if current in expected:
                        actual.append(current)
                    current = current.nextInFocusChain()
                    if current is expected[0]:
                        break
                self.assertEqual([x.objectName() for x in actual], [x.objectName() for x in expected], (index, position))

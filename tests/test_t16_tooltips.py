"""Default budgets and live help coverage through the redesigned task routes."""

import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QAbstractButton, QApplication, QGroupBox, QScrollArea, QToolButton, QWidget
import desktop_ui
from desktop_strings import ui_text
from desktop_ui import MainWindow
from quantlab.desktop_runtime import AppPaths
from tests.test_t9_onboarding import sandbox_ui
from tests.snapshot_cache import default_metrics
from tools.ui_snapshot import _has_label, _input_widgets

ROOT = Path(__file__).resolve().parents[1]


def coverage_policy():
    document = (ROOT / 'docs/analysis/t16_final_targets.md').read_text(encoding='utf-8')
    return json.loads(document.split('<!-- t16-input-policy -->\n```json\n', 1)[1].split('\n```', 1)[0])


def redesign_policy():
    return json.loads((ROOT / 'tests/fixtures/ui_redesign_tooltip_coverage.json').read_text(encoding='utf-8'))


class TooltipCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        context = sandbox_ui()
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        network = patch('socket.socket', side_effect=AssertionError('network forbidden'))
        network.start()
        self.addCleanup(network.stop)
        folder = tempfile.TemporaryDirectory(prefix='t16-tooltips-')
        self.addCleanup(folder.cleanup)
        paths = AppPaths(Path(folder.name) / 'workspace').ensure()
        jobs = SimpleNamespace(active=False, poll=lambda: [], start=Mock(), close=Mock())
        self.window = MainWindow(paths, jobs)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)
        for timer in self.window.findChildren(QTimer):
            timer.stop()
        # Never shown: isVisibleTo() answers from widget flags, and painting is slow on software-rendering CI hosts.
        self.window.resize(1366, 768)

    def pages(self):
        for index in range(self.window.stack.count()):
            self.window.navigation.setCurrentRow(index)
            page = self.window.stack.widget(index)
            yield index, page.widget() if isinstance(page, QScrollArea) else page

    def page(self, index):
        self.window.navigation.setCurrentRow(index)
        container = self.window.stack.widget(index)
        return container.widget() if isinstance(container, QScrollArea) else container

    def expand_disclosures(self, page):
        # Operate only real disclosure controls, never consent/action controls.
        toggles = [*self.window._section_toggles.values(), *page.findChildren(QToolButton)]
        for _ in range(len(toggles)):
            changed = False
            for toggle in toggles:
                registered = toggle in self.window._section_toggles.values()
                if not (registered or toggle.property('designDisclosure')) or not toggle.isVisibleTo(page) or toggle.isChecked():
                    continue
                if isinstance(toggle, QGroupBox):
                    toggle.setChecked(True)
                else:
                    toggle.click()
                self.assertTrue(toggle.isChecked(), toggle.objectName())
                changed = True
            if not changed:
                break

    def assert_help(self, page, controls, seen):
        obvious = {ui_text(key): key for key in coverage_policy()['obvious_controls']}
        for widget in controls:
            identity = (widget.objectName(), widget.accessibleName())
            self.assertTrue(widget.isVisibleTo(page), identity)
            self.assertTrue(_has_label(widget, page), identity)
            if widget.toolTip().strip():
                continue
            if isinstance(widget, QAbstractButton) and widget.text() in obvious:
                seen.add(obvious[widget.text()])
            else:
                self.fail(f'Non-obvious input without tooltip: {identity}')

    def resolve_control(self, path):
        value = self.window
        for part in path.split('.'):
            value = value.get(part) if isinstance(value, dict) else getattr(value, part, None)
            if value is None:
                break
        return value

    def assert_route(self, page, seen):
        """All fields keep explicit labels; original tooltip obligations stay exact.

        Baseline default inputs were measured on committed 567dbb23: 21 fields
        had tooltips, nine disclosure checkboxes shared tooltip.advanced, and
        eleven fully worded checkboxes were the original documented exceptions.
        Typed advanced forms were never part of that default-tooltip contract.
        They are now additionally checked for actual reachability and labels.
        """
        controls = _input_widgets(page)
        for widget in controls:
            self.assertTrue(widget.isVisibleTo(page), widget.objectName())
            self.assertTrue(_has_label(widget, page), (widget.objectName(), widget.accessibleName()))
            self.assertTrue(widget.accessibleName().strip(), widget.objectName())
            if widget.objectName().startswith('advanced_'):
                self.assertEqual(widget.toolTip(), ui_text('tooltip.advanced'))
        policy = redesign_policy()
        for path, key in policy['original_tooltips'].items():
            widget = self.resolve_control(path)
            if widget in controls:
                self.assert_help(page, [widget], seen)
                self.assertEqual(widget.toolTip(), ui_text(key), path)
                self.original_help_seen.add(path)
        for path in policy['new_tooltip_controls']:
            widget = self.resolve_control(path)
            if widget in controls:
                self.assert_help(page, [widget], seen)
                self.new_help_seen.add(path)
        obvious = {ui_text(key) for key in coverage_policy()['obvious_controls']}
        self.assert_help(page, [control for control in controls if isinstance(control, QAbstractButton) and control.text() in obvious], seen)

    def test_every_default_input_has_tooltip_or_explicit_obvious_label(self):
        policy = coverage_policy()
        seen = set()
        counts = []
        for index, page in self.pages():
            inputs = _input_widgets(page)
            counts.append(len(inputs))
            with self.subTest(page=index):
                self.assert_help(page, inputs, seen)
        self.assertEqual(counts, redesign_policy()['default_input_counts'])
        self.assertLessEqual(seen, set(policy['obvious_controls']))
        self.assertTrue(all(policy['obvious_controls'].values()))

    def test_moved_inputs_keep_labels_and_tooltips_on_their_real_routes(self):
        w, seen = self.window, set()
        self.original_help_seen, self.new_help_seen = set(), set()
        data = self.page(0)
        self.assertEqual(w.data_page.sources.count(), redesign_policy()['data_sources'])
        self.assertEqual(w.import_kind.count(), redesign_policy()['import_formats'])
        for source in range(w.data_page.sources.count()):
            w.data_page.sources.setCurrentIndex(source)
            if source == 2:
                # Both deliberate download modes retain reachable, explicit consent labels.
                w.data_page.download_import.enabled.setChecked(False)
                self.assert_route(data, seen)
                w.data_page.download_import.enabled.setChecked(True)
            for kind in range(w.import_kind.count()) if source == 0 else (0,):
                w.import_kind.setCurrentIndex(kind)
                w.data_page.contract_filter.setChecked(True)
                with self.subTest(source=source, kind=kind):
                    self.assert_route(data, seen)
        strategy = self.page(1)
        page = w.strategy_page
        self.assertEqual(set(page.mode_buttons) | {'walk_forward'}, set(redesign_policy()['strategy_modes']))
        page.mode_buttons['manual'].click()
        for family in range(w.strategy_form.family.count()):
            w.strategy_form.family.setCurrentIndex(family)
            self.assert_route(strategy, seen)
            self.assertTrue(all(field.isVisibleTo(strategy) for field in w.strategy_form.fields.values()))
        page.mode_buttons['research'].click()
        self.expand_disclosures(strategy)
        for provider in range(w.provider_mode.count()):
            w.provider_mode.setCurrentIndex(provider)
            self.assert_route(strategy, seen)
            self.assertTrue(all(field.isVisibleTo(strategy) for field in page.campaign_form.fields.values()))
        self.assertTrue(page.manual_path.isVisibleTo(strategy))
        self.assertTrue(page.manual_response.isVisibleTo(strategy))

        # Real offline outputs expose the result-only controls and let the
        # wizard's normal navigation guards admit its data/window steps.
        from quantlab.core import to_dict
        from quantlab.reporting import demo_config

        desktop_ui.execute_ui_operation('ui_demo', {'bars': 120}, w.paths)
        desktop_ui.execute_ui_operation('ui_backtest', {'family': 'trend', 'parameters': {'fast': 5, 'slow': 20}, 'config': to_dict(demo_config())}, w.paths)
        w.refresh_views()
        page.findChild(QAbstractButton, 'strategy_walk_forward_entry').click()
        wizard = page.wf_wizard
        self.assert_route(strategy, seen)
        wizard.next.click()
        self.assertEqual(wizard.position, 1)
        self.assert_route(strategy, seen)
        wizard.next.click()
        self.assertEqual(wizard.position, 2)
        wizard.preset.setCurrentIndex(wizard.preset.findData('custom'))
        self.assert_route(strategy, seen)
        self.assertTrue(all(field.isVisibleTo(strategy) for key, field in page.walk_forward_form.fields.items() if key not in ('pool_origin', 'evidence_mode')))

        backtest = self.page(2)
        self.expand_disclosures(backtest)
        self.assert_route(backtest, seen)
        self.assertTrue(all(field.isVisibleTo(backtest) for field in w.backtest_form.fields.values()))
        self.assertTrue(w.result_choice.isVisibleTo(backtest))
        compare = self.page(3)
        self.expand_disclosures(compare)
        self.assert_route(compare, seen)
        paper = self.page(4)
        self.expand_disclosures(paper)
        self.assert_route(paper, seen)
        for form in (w.policy_form, w.snapshot_form, w.intent_form, w.quote_form):
            self.assertTrue(all(field.isVisibleTo(paper) for field in form.fields.values()))
        self.assert_route(self.page(5), seen)
        settings = self.page(6)
        self.expand_disclosures(settings)
        self.assertEqual([widget.objectName() for widget in _input_widgets(settings) if not _has_label(widget, settings)], [])
        self.assert_help(settings, [w.persist_logs, w.local_notifications, w.workspace_path, w.backup_path], seen)
        obvious_texts = {ui_text(key) for key in coverage_policy()['obvious_controls']}
        for control in settings.findChildren(QAbstractButton):
            if control.isVisibleTo(settings) and control.text() in obvious_texts:
                self.assert_help(settings, [control], seen)
        self.assertEqual(seen, set(coverage_policy()['obvious_controls']), 'Every original exception still has a reachable, explicit label')
        self.assertEqual(self.original_help_seen, set(redesign_policy()['original_tooltips']))
        self.assertEqual(self.new_help_seen, set(redesign_policy()['new_tooltip_controls']))
        w.jobs.start.assert_not_called()

    def test_other_strategy_families_keep_tooltips_after_rebuilding_fields(self):
        form = self.window.strategy_form
        for index in range(form.family.count()):
            form.family.setCurrentIndex(index)
            for key, field in form.fields.items():
                self.assertTrue(field.toolTip().strip(), (index, key))
            payload = form.build_payload()
            form.from_payload(payload)
            self.assertEqual(form.build_payload(), payload)
            self.assertTrue(all(field.toolTip().strip() for field in form.fields.values()))

    def test_default_text_has_only_allowlisted_domain_tokens_and_no_hashes(self):
        # Shared metrics-only capture: rasterising or re-measuring pages is slow on CI hosts.
        tokens = set()
        for metrics in default_metrics()['pages'].values():
            text = '\n'.join(metrics['visible_text'] + metrics['combo_items'] + metrics['table_headers'])
            tokens.update(re.findall(r'\b[A-Z][A-Z_]{2,}\b', text))
            self.assertNotRegex(text, r'\b[a-f0-9]{32,}\b')
        self.assertEqual(tokens, set(redesign_policy()['default_domain_terms']))
        self.assertLessEqual(tokens, set(coverage_policy()['domain_terms']))

    def test_presentation_keeps_public_identities_and_default_readability_budgets(self):
        names = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        widgets = [self.window, *self.window.findChildren(QWidget)]
        self.assertEqual(sorted({widget.objectName() for widget in widgets if widget.objectName()}), names)
        public_names = json.loads((ROOT / 'tests/fixtures/desktop_ui_public_names.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(name for name in vars(desktop_ui) if not name.startswith('_')), public_names)
        actual_pages = default_metrics()['pages']
        self.assertEqual(len(actual_pages), 7)
        policy = redesign_policy()
        self.assertEqual([page['visible_input_count'] for page in actual_pages.values()], policy['default_input_counts'])
        for name, metrics in actual_pages.items():
            self.assertLessEqual(metrics['page_height'], policy['max_default_page_height'], name)
            self.assertLessEqual(metrics['primary_button_count'], policy['max_default_primary_buttons'], name)
            self.assertEqual(metrics['unlabeled_inputs'], [], name)
            for button in metrics['disabled_buttons']:
                self.assertTrue(button['tooltip'] or button['hint'], (name, button['object_name']))


if __name__ == '__main__':
    unittest.main()

"""Regression tests for the PR #169 cloud-review findings (offline only)."""

import unittest

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from desktop_app.components.async_status import AsyncStatus
from desktop_app.features.trading import TradingWindow
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contextnavigation import CompositeFacade
from quantlab.trading.domain.validation import DomainError
from tests import test_context_navigation_v2 as navigation_support
from tests.test_m3_ui import view


class CatalogueView(navigation_support.ViewStub):
    def __init__(self, *args):
        super().__init__(*args)
        self.catalogue = ('ref-1', 'ref-2')
        self.failure = None

    def candidates(self):
        if self.failure is not None:
            raise self.failure
        return self.catalogue


class CompositeCandidatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.port = navigation_support.NavigationStub()
        self.port.facades['local'] = CatalogueView(
            *self.port.facades['local'].state.environment and (self.port.facades['local'].state.environment, 'local-stock', 90, 'LOCAL_BOOK')
        )
        self.facade = CompositeFacade(self.port, 'local', self.port.facades['local'])

    def test_real_composite_delegates_candidates_to_selected_context(self):
        self.assertEqual(self.facade.candidates(), ('ref-1', 'ref-2'))

    def test_composite_propagates_domain_error(self):
        self.port.facades['local'].failure = DomainError('candidate_unavailable')
        with self.assertRaises(DomainError):
            self.facade.candidates()

    def test_widget_with_real_composite_loads_candidates(self):
        from dataclasses import replace

        state = replace(self.facade.snapshot(), auto_strategies=(view(),))
        window = TradingWindow(self.facade, state, research_status_factory=AsyncStatus)
        window.poll.stop()
        window.setProperty('allow_close_for_tests', True)
        try:
            controls = window.auto_strategies
            controls.load_candidates()
            self._wait(window)
            self.assertEqual(controls.candidates.count(), 2)
            self.assertTrue(controls.build_button.isEnabled())
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_program_error_is_not_reported_as_empty_catalogue(self):
        from dataclasses import replace

        self.port.facades['local'].failure = AttributeError('programming error')
        state = replace(self.facade.snapshot(), auto_strategies=(view(),))
        window = TradingWindow(self.facade, state, research_status_factory=AsyncStatus)
        window.poll.stop()
        window.setProperty('allow_close_for_tests', True)
        try:
            controls = window.auto_strategies
            controls.load_candidates()
            self._wait(window)
            text = controls.status.label.text()
            self.assertIn(ui_text('v2.connection_failed'), text)
            self.assertNotIn(ui_text('m3.candidates_unavailable'), text)
            self.assertNotIn('programming error', text)
            self.assertFalse(controls.build_button.isEnabled())
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_quote_ticks_do_not_redraw_auto_strategy_table(self):
        from dataclasses import replace
        from unittest.mock import patch

        state = replace(self.facade.snapshot(), auto_strategies=(view(),))
        window = TradingWindow(self.facade, state, research_status_factory=AsyncStatus)
        window.poll.stop()
        window.setProperty('allow_close_for_tests', True)
        try:
            with patch.object(window.auto_strategies, 'render', wraps=window.auto_strategies.render) as render:
                window.apply_state(replace(state, quote_revision=state.quote_revision + 1))
                window.apply_state(replace(state, quote_revision=state.quote_revision + 2))
                self.assertEqual(render.call_count, 0)
                window.apply_state(replace(state, version=state.version + 1))
                self.assertEqual(render.call_count, 1)
                window.apply_state(replace(state, version=state.version + 1, context_epoch=state.context_epoch + 1))
                self.assertEqual(render.call_count, 2)
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _wait(self, window):
        import time

        deadline = time.monotonic() + 5
        while window.auto_strategies.worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertIsNone(window.auto_strategies.worker)


if __name__ == '__main__':
    unittest.main()

"""Feature form defaults must stay identical to the existing backtest demo."""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
import shiboken6

from desktop_app.features.backtest.forms import BacktestForm
from quantlab.core import to_dict
from quantlab.reporting import demo_config


class FormDefaultsTests(unittest.TestCase):
    def test_backtest_default_payload_matches_existing_demo_config(self):
        app = QApplication.instance() or QApplication([])
        form = BacktestForm()
        try:
            payload = form.build_payload()
            self.assertEqual(payload['config'], to_dict(demo_config()))
            self.assertEqual((payload['start_date'], payload['end_date']), ('', ''))
        finally:
            shiboken6.delete(form)
            app.processEvents()

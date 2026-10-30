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


class IdeaStoreTimingTests(unittest.TestCase):
    def test_dialog_defers_store_and_uses_a_fresh_instance_for_each_action(self):
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock
        from PySide6.QtWidgets import QComboBox
        from desktop_app.features.strategy.idea_research import IdeaResearchDialog

        app = QApplication.instance() or QApplication([])
        calls, instances = [], []
        task = 'idea-' + 'b' * 32
        root = Path('unused-idea-store-timing')

        class Store:
            def __init__(self, location):
                calls.append(('construct', location))
                instances.append(self)

            def purge(self, count, *, max_age):
                calls.append(('purge', count, max_age))
                return 0

            def load(self, task_id):
                calls.append(('load', task_id))
                return {'task_id': task_id, 'status': 'completed', 'searches': [], 'sources': [], 'candidates': []}

            def read_text(self, task_id, source_id):
                calls.append(('read_text', task_id, source_id))
                return 'plain text'

        model = QComboBox()
        model.addItem('Fixture', 'model')
        state = SimpleNamespace(root=root, jobs=SimpleNamespace(active=False), chatgpt_panel=SimpleNamespace(model=model))
        host = SimpleNamespace(state=state, safe=lambda callback: callback(), start_job=Mock(), payload=Mock(), idea_records=Store)
        dialog = IdeaResearchDialog(host)
        try:
            self.assertEqual(calls, [])
            dialog.clear_temp()
            dialog.load_record(task)
            dialog.record['sources'] = [{'source_id': 's1'}]
            dialog.sources.blockSignals(True)
            dialog.sources.setRowCount(1)
            dialog.sources.setCurrentCell(0, 0)
            dialog.sources.blockSignals(False)
            dialog.show_source()
            self.assertEqual(calls, [('construct', root), ('purge', 0, 0), ('construct', root), ('load', task), ('construct', root), ('read_text', task, 's1')])
            self.assertEqual(len({id(instance) for instance in instances}), 3)
            self.assertEqual(dialog.reader.toPlainText(), 'plain text')
        finally:
            shiboken6.delete(dialog)
            shiboken6.delete(model)
            app.processEvents()

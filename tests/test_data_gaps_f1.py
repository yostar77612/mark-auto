"""F1 projections and lazy UI checks without jobs, network or shown windows."""

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import random
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QVBoxLayout, QWidget

from desktop_app.features.data.data import DataPage
from desktop_app.features.data.data_gaps import GapPanel, import_event, timeline_rows
from desktop_app.components.job_progress import JobFeedback
from desktop_app.strings.catalog import ui_text
from quantlab.core import ValidationError, canonical_json, to_dict
from quantlab.data import SessionCalendar, aggregate_ticks, parse_timestamp, validate_dataset
from quantlab.data_gap_report import MAX_GAPS, build_gap_report, reject_invalid_import
from quantlab.desktop_errors import error_message


def gap(day='2026-10-07', minute=46, contract='TAIFEX:TMF:202610'):
    return dict(trade_date=day, start=f'{day}T00:{minute:02}:00+00:00', end=f'{day}T00:{minute + 1:02}:00+00:00', contract_id=contract, session='day')


def fixture(complete=False):
    day = '2026-10-07'
    calendar = SessionCalendar([dict(open=day + 'T08:45:00+08:00', end=day + 'T08:48:00+08:00', trade_date=day, session='day', source='fixture')], version='f1')
    ticks = [
        dict(
            timestamp=parse_timestamp(f'{day}T08:{minute}:00+08:00'),
            contract_id='TAIFEX:TMF:202610',
            price=Decimal('20000'),
            quantity=1,
            source_type='official_local',
        )
        for minute in ((45, 46, 47) if complete else (45, 47))
    ]
    return aggregate_ticks(ticks, timeframe_minutes=1, calendar=calendar)


class GapProjectionTests(unittest.TestCase):
    def test_empty_malformed_unknown_code_and_bounded(self):
        for value in (None, [], 'path-secret.csv', {}, {'session_coverage_gaps': None}, {'session_coverage_gaps': [None, {}, gap(minute=59)]}):
            self.assertEqual(build_gap_report(value).gaps, ())
        unknown = build_gap_report({'session_coverage_gaps': [gap()]}, 'untrusted.csv')
        self.assertEqual(unknown.gaps, ())
        self.assertEqual(unknown.message, error_message('operation_failed'))
        report = build_gap_report({'session_coverage_gaps': [gap()] * 10000})
        self.assertEqual(len(report.gaps), MAX_GAPS)
        self.assertEqual(report.more, 9500)

    def test_shuffled_date_then_start_contract_and_no_payload_echo(self):
        rows = [gap('2026-10-08', 48), gap(minute=49), gap(), gap(contract='TAIFEX:TMF:202611')]
        expected = build_gap_report({'session_coverage_gaps': rows})
        random.Random(42).shuffle(rows)
        self.assertEqual(build_gap_report({'session_coverage_gaps': rows, 'oos': {'secret': 'excluded-marker'}, 'path': 'private.csv'}), expected)
        self.assertEqual(expected.gaps[0].trade_date, '2026-10-07')
        self.assertEqual([g.start for g in expected.gaps], sorted(g.start for g in expected.gaps))
        self.assertNotIn('excluded-marker', repr(expected))
        self.assertEqual(len(timeline_rows(expected.gaps)), 3)
        for scope in ('oos', 'out_of_sample', 'holdout', 'final_holdout'):
            self.assertEqual(build_gap_report({'scope': scope, 'session_coverage_gaps': rows}).gaps, ())
            self.assertEqual(build_gap_report({'session_coverage_gaps': [dict(gap(), split=scope)]}).gaps, ())

    def test_oct7_rule_message_coordinates_and_accepted_bytes_unchanged(self):
        data = fixture()
        before = canonical_json(to_dict(data))
        with self.assertRaisesRegex(ValidationError, '^dataset quality is not valid$'):
            validate_dataset(data)
        report = build_gap_report(data.quality)
        self.assertEqual(report.gaps[0].trade_date, '2026-10-07')
        self.assertEqual(datetime.fromisoformat(report.gaps[0].start), datetime(2026, 10, 7, 0, 46, tzinfo=timezone.utc))
        self.assertEqual(datetime.fromisoformat(report.gaps[0].end).minute, 47)
        packets = []
        with self.assertRaisesRegex(ValidationError, '^dataset quality is not valid$'):
            reject_invalid_import(data, lambda kind, **values: packets.append(values))
        self.assertEqual(len(packets), 1)
        self.assertEqual(build_gap_report(packets[0]['gap_report']['quality']).gaps, report.gaps)
        self.assertEqual(canonical_json(to_dict(data)), before)
        accepted = fixture(True)
        before = canonical_json(to_dict(accepted))
        validate_dataset(accepted)
        reject_invalid_import(accepted)
        self.assertEqual(canonical_json(to_dict(accepted)), before)

    def test_import_rejected_before_store_accepted_write_preserved(self):
        import desktop_app.shell.main_window

        payload = dict(calendar='calendar.json', path='input.csv', kind='ticks')
        cal = dict(version='f1', sessions=[])
        data = fixture()
        with (
            patch.object(desktop_app.shell.main_window, 'read_json', return_value=cal),
            patch('quantlab.data.import_taifex', return_value=data),
            patch.object(desktop_app.shell.main_window, 'save_dataset') as save,
            patch.object(desktop_app.shell.main_window, 'write_json') as write,
        ):
            with self.assertRaisesRegex(ValidationError, '^dataset quality is not valid$'):
                desktop_app.shell.main_window._handle_ui_import(payload, None, Path('.'))
            save.assert_not_called()
            write.assert_not_called()
        data = fixture(True)
        with (
            patch.object(desktop_app.shell.main_window, 'read_json', return_value=cal),
            patch('quantlab.data.import_taifex', return_value=data),
            patch.object(desktop_app.shell.main_window, 'save_dataset') as save,
            patch.object(desktop_app.shell.main_window, 'write_json'),
        ):
            desktop_app.shell.main_window._handle_ui_import(payload, None, Path('.'))
            self.assertIs(save.call_args.args[0], data)

    def test_catalog_fix_options_and_no_automatic_action(self):
        source = Path('desktop_app/features/data/data_gaps.py').read_text(encoding='utf-8')
        self.assertNotIn('start_job', source)
        self.assertNotIn('QPushButton', source)
        self.assertNotIn('deleteLater', source)
        text = ui_text('data.gaps.options')
        self.assertTrue(all(word in text for word in ('\u91cd\u65b0\u4e0b\u8f09', '\u7f3a\u6f0f\u6642\u6bb5', '\u5176\u4ed6\u7bc4\u570d')))


class GapWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_privacy_oos_absence_readonly_bounded_and_paint(self):
        parent = QWidget()
        parent.privacy = SimpleNamespace(enabled=False)
        panel = GapPanel(parent)
        quality = {'session_coverage_gaps': [gap()] * 10000, 'oos': {'secret': 'oos-marker'}, 'source_filename': 'private.csv', 'path': 'C:/private.csv'}
        for private in (False, True):
            parent.privacy.enabled = private
            panel.set_report(build_gap_report(quality))
            self.assertEqual(panel.table.rowCount(), 500)
            self.assertIn(ui_text('data.gaps.more').format(9500), panel.notice.text())
            self.assertEqual(panel.table.editTriggers(), panel.table.EditTrigger.NoEditTriggers)
            texts = panel.notice.text() + panel.timeline.accessibleDescription()
            texts += ''.join(
                panel.table.item(row, col).text() + panel.table.item(row, col).toolTip() for row in range(panel.table.rowCount()) for col in range(3)
            )
            self.assertNotIn('private.csv', texts)
            self.assertNotIn('oos-marker', texts)
            self.assertIn('2026-10-07T08:46', texts)
        self.assertTrue(panel.timeline.accessibleName())
        panel.timeline.resize(640, 40)

        def render():
            image = QImage(640, 40, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            panel.timeline.render(painter, QPoint())
            painter.end()
            return image

        self.assertEqual(render(), render())
        parent.close()

    def test_lazy_page_rejection_success_reset_and_no_jobs(self):
        def mount(page, title):
            return QVBoxLayout(page)

        def button(layout, text, *args, **kwargs):
            widget = QPushButton(text)
            layout.addWidget(widget)
            return widget

        host = SimpleNamespace(
            state=SimpleNamespace(jobs=SimpleNamespace(active=False)),
            mount_page=mount,
            button=button,
            text=lambda *a: QLineEdit(),
            advanced=lambda layout: layout,
            start_job=lambda *a: self.fail('unexpected job'),
        )
        page = DataPage(host)
        self.assertIsNone(page.gap_panel)
        self.assertEqual(page.findChildren(GapPanel), [])
        report = build_gap_report({'session_coverage_gaps': [gap()]})
        import_event(page, {'type': 'progress', 'gap_report': {'code': report.code, 'quality': {'session_coverage_gaps': [asdict(g) for g in report.gaps]}}})
        self.assertEqual(page.gap_panel.table.rowCount(), 1)
        import_event(page, {'type': 'result'})
        self.assertEqual(page.gap_panel.table.rowCount(), 0)
        self.assertEqual(page.gap_panel.timeline.rows, ())
        self.assertEqual(page.gap_panel.timeline.accessibleDescription(), '')
        self.assertTrue(page.gap_panel.isHidden())
        page.show_gap_report(report)
        page.reset_gap_report()
        self.assertEqual(page.gap_panel.report.gaps, ())
        page.close()

    def test_feedback_rejects_stale_report_packets_and_tolerates_bare_host(self):
        feedback = JobFeedback(SimpleNamespace(begin=lambda: None, update_event=lambda event: None))
        feedback.begin('current')
        page = SimpleNamespace(show_gap_report=lambda report: self.fail('stale report'))
        self.assertFalse(feedback.accept(SimpleNamespace(last_operation='ui_import', data_page=page), {'type': 'progress', 'job_id': 'old', 'gap_report': {}}))
        self.assertTrue(feedback.accept(SimpleNamespace(), {'type': 'progress', 'job_id': 'current'}))

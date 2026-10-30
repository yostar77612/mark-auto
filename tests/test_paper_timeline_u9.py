"""Cheap read-only timeline evidence: automation establishes only not broken."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from shiboken6 import delete

from desktop_app.features.paper.paper_tabs import build_tabs, existing_journal, refresh_tables
from desktop_app.strings.catalog import ui_text
from quantlab.paper_tab_data import TIMELINE_LIMIT, event_type, timeline_rows

ROOT = Path(__file__).resolve().parents[1]


class TimelineDataTests(unittest.TestCase):
    def test_operation_mapping_and_wrapped_events(self):
        for operation, expected in (
            ('intent', 'intent'),
            ('ack', 'ack'),
            ('fill', 'fill'),
            ('reject', 'reject'),
            ('risk_reject', 'reject'),
            ('reconcile', 'reconcile'),
            ('kill', 'lock'),
            ('manual_order_lock', 'lock'),
            ('manual_lock', 'lock'),
            ('unknown', 'other'),
            (None, 'other'),
            ([], 'other'),
        ):
            with self.subTest(operation=operation):
                self.assertEqual(event_type(operation), expected)
        for kind in ('ack', 'fill', 'reject'):
            self.assertEqual(event_type('event', {'type': kind}), kind)
        self.assertEqual(event_type('event', {'type': 'untrusted'}), 'other')

    def test_chronology_sequence_ties_and_timezone_normalization(self):
        events = [
            {'operation': 'fill', 'sequence': 8, 'payload': {'timestamp': '2026-10-20T09:00:00+08:00'}},
            {'operation': 'ack', 'sequence': 4, 'timestamp': '2026-10-20T01:00:00Z'},
            {'operation': 'intent', 'sequence': 2, 'payload': {'now': '2026-10-20T00:00:00Z'}},
        ]
        before = copy.deepcopy(events)
        rows, truncated = timeline_rows(journal=events)
        self.assertEqual([row['sequence'] for row in rows], [2, 4, 8])
        self.assertFalse(truncated)
        self.assertEqual(events, before)
        rows, _ = timeline_rows(journal=[events[0], events[0]])
        self.assertEqual(rows[0], rows[1])

    def test_legacy_malformed_and_missing_times_are_other(self):
        fixture = json.loads((ROOT / 'tests/fixtures/lb_b10_legacy_journal.json').read_text(encoding='utf-8'))
        rows, _ = timeline_rows(journal=fixture['journal'])
        self.assertEqual(len(rows), len(fixture['journal']))
        self.assertTrue(all(row['type'] == 'other' for row in rows))
        rows, _ = timeline_rows(journal=[None, 'bad', {'operation': 'alien', 'timestamp': 'not a date'}, {'timestamp': '2026-01-01'}])
        self.assertTrue(all(row['time'] is None and row['type'] == 'other' for row in rows))
        self.assertEqual(timeline_rows({'events': object()}), ([], False))

    def test_large_input_projects_only_capped_tail(self):
        class Counted(dict):
            reads = 0

            def get(self, *args):
                type(self).reads += 1
                return super().get(*args)

        journal = [Counted(operation='intent', sequence=i + 1) for i in range(10000)]
        rows, truncated = timeline_rows(journal=journal)
        self.assertEqual(len(rows), TIMELINE_LIMIT)
        self.assertTrue(truncated)
        self.assertEqual(rows[0]['sequence'], 10001 - TIMELINE_LIMIT)
        self.assertLessEqual(Counted.reads, TIMELINE_LIMIT * 6)


class TimelineWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.addCleanup(delete, self.owner)
        self.page = SimpleNamespace(root=ROOT)
        self.tabs = build_tabs(self.page, QVBoxLayout(self.owner))

    def refresh(self, journal):
        with patch('desktop_app.features.paper.paper_tabs.existing_journal', return_value=journal):
            refresh_tables(self.page, {}, [], [])

    def open(self):
        self.tabs.setCurrentWidget(self.page.events_table)
        self.tabs.setCurrentIndex(4)

    def text(self):
        table = self.page.timeline_table
        return '\n'.join(table.item(r, c).text() for r in range(table.rowCount()) for c in range(table.columnCount()))

    def test_lazy_additive_preserves_existing_widgets_and_empty_placeholder(self):
        original = self.page.events_table
        self.refresh([])
        self.assertEqual(self.tabs.count(), 4)
        self.assertFalse(hasattr(self.page, 'timeline_table'))
        self.open()
        self.assertIs(self.page.events_table, original)
        self.assertEqual(self.page.timeline_table.rowCount(), 0)
        self.assertEqual(self.page.timeline_notice.text(), ui_text('paper.timeline.empty'))
        self.tabs.setCurrentIndex(0)
        self.assertFalse(self.tabs.isTabVisible(4))
        self.open()
        self.assertTrue(self.tabs.isTabVisible(4))
        self.assertEqual(self.tabs.count(), 5)

    def test_filter_round_trip_and_refresh_preserve_source_and_selection(self):
        journal = [{'operation': kind, 'sequence': index} for index, kind in enumerate(('intent', 'ack', 'fill', 'reject', 'reconcile', 'kill'), 1)]
        before = copy.deepcopy(journal)
        self.refresh(journal)
        self.open()
        table, selector = self.page.timeline_table, self.page.timeline_filter
        for kind in ('intent', 'ack', 'fill', 'reject', 'reconcile', 'lock'):
            selector.setCurrentIndex(selector.findData(kind))
            self.assertEqual(sum(not table.isRowHidden(r) for r in range(table.rowCount())), 1)
        self.refresh(journal)
        self.assertEqual(selector.currentData(), 'lock')
        self.assertEqual(sum(not table.isRowHidden(r) for r in range(table.rowCount())), 1)
        selector.setCurrentIndex(0)
        self.assertFalse(any(table.isRowHidden(r) for r in range(table.rowCount())))
        self.assertEqual(journal, before)

    def test_read_only_reader_stub_raises_on_write_and_no_actions(self):
        class ReadOnlyJournal:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size):
                self_size = 4 * 1024 * 1024 + 1
                self_outer.assertEqual(size, self_size)
                return '[{"operation":"fill","sequence":1}]'

            def write(self, *args):
                raise AssertionError('journal writes forbidden')

        self_outer = self

        def read_only_open(path, *args, **kwargs):
            self.assertNotIn(kwargs.get('mode', 'r'), ('w', 'a', 'r+'))
            self.assertFalse(args)
            return ReadOnlyJournal()

        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=42)), patch.object(Path, 'open', read_only_open):
            self.assertEqual(existing_journal(self.page)[0]['operation'], 'fill')
            refresh_tables(self.page, {}, [], [])
            self.open()
            self.page.timeline_filter.setCurrentIndex(1)
        table = self.page.timeline_table
        self.assertEqual(table.editTriggers(), table.EditTrigger.NoEditTriggers)
        self.assertFalse(table.isSortingEnabled())
        self.assertFalse(table.actions())
        self.assertFalse(self.tabs.widget(4).findChildren(QPushButton))

    def test_privacy_and_payload_exclusion_with_dynamic_toggle(self):
        self.owner.privacy = SimpleNamespace(enabled=True)
        event = {
            'operation': 'event',
            'identity': 'SECRET-ORDER',
            'payload': {
                'type': 'fill',
                'timestamp': '2026-10-20T01:00:00Z',
                'price': '987654321',
                'quantity': '123456789',
                'order_id': 'SECRET-ORDER',
                'account_id': 'SECRET-ACCOUNT',
                'summary': 'PRIVATE-PAYLOAD',
                'oos': 'PRIVATE-PAYLOAD',
                'holdout': 'PRIVATE-PAYLOAD',
            },
        }
        self.refresh([event])
        self.open()
        for private in (True, False, True):
            self.owner.privacy.enabled = private
            self.refresh([event])
            shown = self.text()
            for secret in ('987654321', '123456789', 'SECRET', 'PRIVATE', 'oos', 'holdout'):
                self.assertNotIn(secret, shown)
            self.assertEqual(self.page.timeline_table.item(0, 1).text(), ui_text('paper.timeline.fill'))

    def test_10000_rows_capped_indicator_and_accessibility(self):
        self.refresh([{'operation': 'fill'}] * 10000)
        self.open()
        self.assertEqual(self.page.timeline_table.rowCount(), TIMELINE_LIMIT)
        self.assertEqual(self.page.timeline_notice.text(), ui_text('paper.timeline.truncated').format(TIMELINE_LIMIT))
        self.assertTrue(self.page.timeline_filter.accessibleName())
        self.assertTrue(self.page.timeline_table.accessibleName())
        self.assertEqual(self.page.timeline_filter.focusPolicy(), Qt.FocusPolicy.WheelFocus)
        widget = self.page.timeline_filter.nextInFocusChain()
        for _ in range(6):
            if widget is self.page.timeline_table:
                break
            widget = widget.nextInFocusChain()
        self.assertIs(widget, self.page.timeline_table)


if __name__ == '__main__':
    unittest.main()

"""Metadata-only checkpoint discovery; no Qt, journal admission or recovery authority."""

from contextlib import ExitStack
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quantlab import reporting, research_analysis
from quantlab.core import ValidationError
from tests import test_desktop_ui as ui_support


class SavedAnalysisDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'analyses'

    def entry(self, name, *, journal=False, projection=False):
        folder = self.root / name
        folder.mkdir(parents=True)
        if journal:
            (folder / 'analysis.sqlite3').write_bytes(b'UNVALIDATED JOURNAL CONTENT')
        if projection:
            (folder / 'analysis.json').write_bytes(b'UNVALIDATED PROJECTION CONTENT')
        return folder

    def discover(self):
        return reporting.saved_analysis_entries(self.root)

    def link(self, path, target, *, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation unavailable')

    def test_missing_root_stays_missing(self):
        self.assertEqual(self.discover(), ())
        self.assertFalse(self.root.exists())

    def test_journal_only_is_unvalidated_checkpoint_metadata(self):
        self.entry('a' * 64, journal=True)
        # Presence is not a claim that these deliberately invalid bytes validate.
        self.assertEqual(self.discover(), (('a' * 64, True),))
        with self.assertRaises((sqlite3.DatabaseError, ValidationError)):
            research_analysis.read_analysis(self.root, 'a' * 64)

    def test_existing_projection_keeps_ordinary_read_route_and_order(self):
        self.entry('c' * 64, journal=True)
        self.entry('b' * 64, journal=True, projection=True)
        self.entry('a' * 64, projection=True)
        self.assertEqual(self.discover(), (('a' * 64, False), ('b' * 64, False), ('c' * 64, True)))

    def test_only_direct_lowercase_hash_directories_are_candidates(self):
        for name in ('short', 'A' * 64, 'g' * 64, 'a' * 63, 'b' * 65, 'nested/' + 'c' * 64):
            self.entry(name, journal=True, projection=True)
        (self.root / ('d' * 64)).write_bytes(b'not a directory')
        self.entry('e' * 64)
        self.assertEqual(self.discover(), ())

    def test_directories_are_not_journal_or_missing_projection(self):
        folder = self.entry('a' * 64)
        (folder / 'analysis.sqlite3').mkdir()
        other = self.entry('b' * 64, journal=True)
        (other / 'analysis.json').mkdir()
        self.assertEqual(self.discover(), ())

    def test_discovery_never_opens_content_connects_or_writes(self):
        self.entry('a' * 64, journal=True)
        self.entry('b' * 64, journal=True, projection=True)
        before = {str(p.relative_to(self.base)): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        forbidden = (
            'pathlib.Path.open',
            'pathlib.Path.mkdir',
            'pathlib.Path.unlink',
            'pathlib.Path.replace',
            'sqlite3.connect',
            'quantlab.research_analysis.read_analysis',
            'quantlab.research_analysis._read_analysis_journal',
            'quantlab.research_analysis.run_analysis',
            'quantlab.research_analysis.reconcile_analysis',
            'quantlab.assistant.adapters.chatgpt.provider.ChatGPTPlanProvider',
        )
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(name, side_effect=AssertionError(name))) for name in forbidden]
            self.assertEqual(self.discover(), (('a' * 64, True), ('b' * 64, False)))
        for mock in mocks:
            mock.assert_not_called()
        after = {str(p.relative_to(self.base)): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_linked_candidate_directory_is_not_followed(self):
        self.root.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'analysis.sqlite3').write_bytes(b'OUTSIDE CONTENT')
        self.link(self.root / ('a' * 64), outside, directory=True)
        with patch.object(Path, 'open', side_effect=AssertionError('No content reads')):
            self.assertEqual(self.discover(), ())

    def test_linked_journal_or_projection_is_not_a_checkpoint(self):
        target = self.base / 'outside'
        target.write_bytes(b'OUTSIDE CONTENT')
        journal = self.entry('a' * 64)
        self.link(journal / 'analysis.sqlite3', target)
        projection = self.entry('b' * 64, journal=True)
        self.link(projection / 'analysis.json', target)
        dangling = self.entry('c' * 64, journal=True)
        self.link(dangling / 'analysis.json', self.base / 'missing')
        with patch.object(Path, 'open', side_effect=AssertionError('No content reads')):
            self.assertEqual(self.discover(), ())

    def test_linked_root_and_ancestor_are_not_enumerated(self):
        actual = self.base / 'actual'
        actual.mkdir()
        (actual / ('a' * 64)).mkdir()
        self.link(self.root, actual, directory=True)
        with patch.object(Path, 'iterdir', side_effect=AssertionError('No linked enumeration')):
            with self.assertRaisesRegex(ValidationError, 'links refused'):
                self.discover()
            with self.assertRaisesRegex(ValidationError, 'links refused'):
                reporting.saved_analysis_entries(self.root / 'nested')

    def test_relative_and_parent_traversal_roots_are_not_enumerated(self):
        with patch.object(Path, 'iterdir', side_effect=AssertionError('No unsafe enumeration')):
            with self.assertRaises(ValidationError):
                reporting.saved_analysis_entries(Path('analyses'))
            with self.assertRaises(ValidationError):
                reporting.saved_analysis_entries(self.root / '..' / 'outside')

    def test_root_enumeration_error_reaches_the_ui_boundary(self):
        self.root.mkdir()
        with patch.object(Path, 'iterdir', side_effect=PermissionError('fixture denial')):
            with self.assertRaises(PermissionError):
                self.discover()

    def test_reparse_point_is_refused_before_enumeration(self):
        self.root.mkdir()
        original = Path.stat

        def stat(path, *args, **kwargs):
            if path == self.root:
                return SimpleNamespace(st_file_attributes=0x400)
            return original(path, *args, **kwargs)

        with (
            patch.object(Path, 'is_symlink', return_value=False),
            patch.object(Path, 'stat', stat),
            patch.object(Path, 'iterdir', side_effect=AssertionError('No reparse enumeration')),
        ):
            with self.assertRaisesRegex(ValidationError, 'reparse points refused'):
                self.discover()

    def test_projection_appearance_removes_checkpoint_marker_without_repair(self):
        folder = self.entry('a' * 64, journal=True)
        self.assertEqual(self.discover(), (('a' * 64, True),))
        (folder / 'analysis.json').write_bytes(b'EXTERNALLY CREATED PROJECTION')
        self.assertEqual(self.discover(), (('a' * 64, False),))


@unittest.skipUnless(ui_support.HAS_QT, 'Pinned Qt needed for native checkpoint selection')
class SavedAnalysisCheckpointWidgetTests(unittest.TestCase):
    setUpClass = ui_support.NativeDesktopTests.__dict__['setUpClass']
    setUp = ui_support.NativeDesktopTests.setUp
    cleanup_window = ui_support.NativeDesktopTests.cleanup_window

    def entry(self, identity, *, projection=False):
        folder = self.paths.state / 'analyses' / identity
        folder.mkdir(parents=True)
        (folder / 'analysis.sqlite3').write_bytes(b'UNVALIDATED JOURNAL CONTENT')
        if projection:
            (folder / 'analysis.json').write_bytes(b'UNVALIDATED PROJECTION CONTENT')
        return folder

    def test_checkpoint_selection_clears_stale_findings_and_only_explains(self):
        w = self.window
        self.entry('a' * 64, projection=True)
        self.entry('b' * 64)
        w._refresh_analysis_saved()
        w.analysis_findings.setPlainText('stale completed findings')
        w.analysis_evidence.setPlainText('stale evidence')
        w.analysis_consent.setChecked(True)
        with (
            patch.object(w, 'start_job') as start,
            patch('quantlab.research_core.application.analysis_operations.analysis_provider_for', side_effect=AssertionError('No provider')),
        ):
            w.analysis_saved.setCurrentIndex(w.analysis_saved.findData('b' * 64))
            self.assertIn('中斷檢查點／尚未完成安全復原', w.analysis_saved.currentText())
            self.assertIn('尚未核對', w.analysis_checkpoint_notice.text())
            self.assertIn('分析狀態紀錄', w.analysis_checkpoint_notice.text())
            self.assertIn('缺少可讀取的結果匯出', w.analysis_checkpoint_notice.text())
            self.assertNotIn('analysis.json', w.analysis_checkpoint_notice.text())
            self.assertNotIn('UNVALIDATED', w.analysis_checkpoint_notice.text())
            self.assertEqual(w.analysis_findings.toPlainText(), '')
            self.assertEqual(w.analysis_evidence.toPlainText(), '')
            self.assertFalse(w.analysis_consent.isChecked())
            w.read_analysis()
            w._refresh_analysis_saved()
            self.assertEqual(w.analysis_saved.currentData(), 'b' * 64)
            self.assertEqual(w.analysis_saved.count(), 2)
            w.read_analysis()
        start.assert_not_called()
        self.assertIsNone(w._analysis_launch)
        self.assertFalse((self.paths.state / 'analyses' / ('b' * 64) / 'analysis.json').exists())

    def test_return_to_ordinary_entry_uses_only_strict_saved_read(self):
        w = self.window
        self.entry('a' * 64)
        self.entry('b' * 64, projection=True)
        w._refresh_analysis_saved()
        self.assertIn('中斷檢查點', w.analysis_checkpoint_notice.text())
        w.analysis_saved.setCurrentIndex(w.analysis_saved.findData('b' * 64))
        self.assertEqual(w.analysis_checkpoint_notice.text(), '')
        self.assertNotIn('中斷檢查點', w.status.text())
        with patch.object(w, 'start_job') as start:
            w.read_analysis()
        start.assert_called_once_with('ui_analysis_read', {'analysis_id': 'b' * 64})

    def test_refresh_reclassifies_projection_without_reading_it(self):
        w = self.window
        folder = self.entry('a' * 64)
        w._refresh_analysis_saved()
        (folder / 'analysis.json').write_bytes(b'NEW UNVALIDATED PROJECTION')
        w._refresh_analysis_saved()
        self.assertEqual(w.analysis_saved.currentText(), 'a' * 64)
        self.assertEqual(w.analysis_checkpoint_notice.text(), '')
        self.assertEqual(w.analysis_findings.toPlainText(), '')
        with patch.object(w, 'start_job') as start:
            w.read_analysis()
        start.assert_called_once_with('ui_analysis_read', {'analysis_id': 'a' * 64})

    def test_ordinary_refresh_preserves_loaded_findings_and_evidence(self):
        w = self.window
        self.entry('a' * 64, projection=True)
        w._refresh_analysis_saved()
        w.analysis_findings.setPlainText('previously validated findings')
        w.analysis_evidence.setPlainText('previously validated evidence')
        w._refresh_analysis_saved()
        self.assertEqual(w.analysis_findings.toPlainText(), 'previously validated findings')
        self.assertEqual(w.analysis_evidence.toPlainText(), 'previously validated evidence')

    def test_discovery_error_is_visible_without_startup_or_worker_failure(self):
        w = self.window
        for error in (ValidationError('unsafe path'), PermissionError('unreadable directory')):
            with (
                self.subTest(error=type(error).__name__),
                patch('quantlab.reporting.saved_analysis_entries', side_effect=error),
                patch.object(w, 'start_job') as start,
            ):
                w._refresh_analysis_saved()
                self.assertEqual(w.analysis_saved.count(), 0)
                self.assertIn('無法安全列出', w.analysis_checkpoint_notice.text())
                start.assert_not_called()

    def test_async_result_selects_its_own_projection_after_checkpoint_selection(self):
        from quantlab.core import canonical_json

        w = self.window
        self.entry('a' * 64)
        self.entry('b' * 64, projection=True)
        context = {'fixture': 'already validated by the worker'}
        result = {'analysis_id': 'b' * 64, 'record': {'plan': {'binding': {'packet': {'context': context}}}}}
        for operation in ('ui_analysis_run', 'ui_analysis_read', 'ui_analysis_reconcile'):
            with self.subTest(operation=operation):
                w._refresh_analysis_saved()
                w._analysis_running = operation == 'ui_analysis_run'
                w.analysis_saved.setCurrentIndex(w.analysis_saved.findData('a' * 64))
                w.last_operation = operation
                with (
                    patch('desktop_app.features.analysis.presenter.analysis_record_text', return_value='validated worker findings'),
                    patch.object(w, 'record_event'),
                ):
                    self.assertTrue(w._analysis_event({'type': 'result', 'result': result}))
                self.assertEqual(w.analysis_saved.currentData(), 'b' * 64)
                self.assertEqual(w.analysis_findings.toPlainText(), 'validated worker findings')
                self.assertEqual(w.analysis_evidence.toPlainText(), canonical_json(context))
                self.assertEqual(w.analysis_checkpoint_notice.text(), '')
                self.assertNotIn('中斷檢查點', w.status.text())
                w._refresh_analysis_saved()
                self.assertEqual(w.analysis_findings.toPlainText(), 'validated worker findings')

    def test_async_result_does_not_paint_completed_findings_over_checkpoint(self):
        w = self.window
        self.entry('a' * 64)
        w._refresh_analysis_saved()
        for identity in ('a' * 64, 'b' * 64):
            with (
                self.subTest(identity=identity),
                patch('desktop_app.features.analysis.presenter.analysis_record_text') as render,
                patch.object(w, 'record_event'),
            ):
                w.last_operation = 'ui_analysis_read'
                w._analysis_event({'type': 'result', 'result': {'analysis_id': identity, 'record': {}}})
                render.assert_not_called()
                self.assertEqual(w.analysis_findings.toPlainText(), '')
                self.assertNotIn('已保存／唯讀載入 AI 解讀', w.status.text())

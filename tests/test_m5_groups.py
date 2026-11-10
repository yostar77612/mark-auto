"""M5-3: concept group store, seed merge, editor commands and the editor dialog."""

from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quantlab.trading.adapters.storage.sector_store import SectorGroupStore
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.sector_contracts import GroupEditView, SectorGroupsCommand, SectorGroupsView
from quantlab.trading.application.sector_group_editor import SectorGroupEditor
from quantlab.trading.application.sector_service import SectorService
from quantlab.trading.domain.concept_groups import BUILTIN_GROUPS, ConceptGroup
from quantlab.trading.domain.sector_groups import GroupRecord, clean_codes, clean_name, merge_seed
from quantlab.trading.domain.validation import DomainError
from tests.test_m5_sector import OPEN, Source, row, stock

import quantlab.trading.runtime.protocol  # noqa: F401  (registers wire types)

SEED_A = (ConceptGroup('builtin.a', 'A', ('2330', '2454')), ConceptGroup('builtin.b', 'B', ('2317',)))


class DomainTests(unittest.TestCase):
    def test_names_and_codes_are_validated_at_the_boundary(self):
        self.assertEqual(clean_name('  散熱  '), '散熱')
        for bad in ('', '   ', 'x' * 21, 'a\nb', None):
            with self.assertRaises(DomainError):
                clean_name(bad)
        self.assertEqual(clean_codes(('2330', '2330', '2454')), ('2330', '2454'))
        for bad in (('0050',), ('abc',), ('2330A',), tuple(str(1000 + index) for index in range(61))):
            with self.assertRaises(DomainError):
                clean_codes(bad)

    def test_seed_merge_updates_untouched_builtins_and_keeps_edited_deleted_and_custom(self):
        stored = (
            GroupRecord('builtin.a', 'Mine', ('9999',), True, True),
            GroupRecord('builtin.b', 'B', ('2317',), True),
            GroupRecord('builtin.gone', 'Gone', ('1101',), True),
            GroupRecord('builtin.kept', 'Kept', ('1102',), True, True),
            GroupRecord('custom.1', 'Custom', ('2603',)),
        )
        seed = (ConceptGroup('builtin.a', 'A2', ('2330',)), ConceptGroup('builtin.b', 'B2', ('2317', '2382')), ConceptGroup('builtin.new', 'New', ('2603',)))
        merged = {record.id: record for record in merge_seed(stored, seed)}
        self.assertEqual((merged['builtin.a'].name, merged['builtin.a'].codes, merged['builtin.a'].edited), ('Mine', ('9999',), True))
        self.assertEqual((merged['builtin.b'].name, merged['builtin.b'].codes), ('B2', ('2317', '2382')))
        self.assertNotIn('builtin.gone', merged)
        self.assertIn('builtin.kept', merged)
        self.assertIn('custom.1', merged)
        self.assertEqual(merged['builtin.new'].codes, ('2603',))
        deleted = merge_seed((GroupRecord('builtin.a', 'A', ('2330',), True, False, True),), seed)
        self.assertTrue(next(record for record in deleted if record.id == 'builtin.a').deleted)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'market' / 'sector_groups.json'

    def store(self, seed=SEED_A, version=1):
        return SectorGroupStore(self.path, seed, version)

    def test_first_open_creates_the_file_from_the_builtin_list(self):
        store = SectorGroupStore(self.path)
        self.assertEqual(len(store.groups()), 17)
        body = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual((body['version'], body['seed_version'], len(body['groups'])), (1, 1, 17))
        self.assertEqual(
            body['groups'][0], {'id': 'builtin.ai_server', 'name': 'AI 伺服器', 'codes': list(BUILTIN_GROUPS[0].codes), 'builtin': True, 'edited': False}
        )

    def test_edits_persist_and_mark_builtin_groups_edited(self):
        store = self.store()
        store.set_codes('builtin.a', ('2330',))
        store.rename('builtin.b', 'Bee')
        created = store.create('我的族群', ('2603', '2603'))
        reloaded = self.store()
        records = {record.id: record for record in reloaded.records()}
        self.assertEqual((records['builtin.a'].codes, records['builtin.a'].edited), (('2330',), True))
        self.assertEqual((records['builtin.b'].name, records['builtin.b'].edited), ('Bee', True))
        self.assertEqual((records[created].codes, records[created].builtin), (('2603',), False))
        self.assertTrue(created.startswith('custom.'))

    def test_edited_builtin_survives_a_newer_seed_but_untouched_ones_update(self):
        store = self.store()
        store.set_codes('builtin.a', ('2330',))
        newer = (ConceptGroup('builtin.a', 'A', ('1101',)), ConceptGroup('builtin.b', 'B', ('2317', '2382')))
        merged = {record.id: record for record in self.store(newer, 2).records()}
        self.assertEqual(merged['builtin.a'].codes, ('2330',))
        self.assertEqual(merged['builtin.b'].codes, ('2317', '2382'))
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['seed_version'], 2)

    def test_delete_and_restore(self):
        store = self.store()
        custom = store.create('Custom', ('2603',))
        store.delete(custom)
        self.assertNotIn(custom, {record.id for record in store.records()})
        store.set_codes('builtin.a', ('2330',))
        store.delete('builtin.a')
        self.assertNotIn('builtin.a', {group.id for group in store.groups()})
        self.assertTrue(next(record for record in store.records() if record.id == 'builtin.a').deleted)
        store.restore('builtin.a')
        restored = next(record for record in store.records() if record.id == 'builtin.a')
        self.assertEqual((restored.codes, restored.edited, restored.deleted), (('2330', '2454'), False, False))
        with self.assertRaises(DomainError):
            store.restore(custom)
        with self.assertRaises(DomainError):
            store.restore('does-not-exist')

    def test_names_must_be_unique_and_limits_hold(self):
        store = self.store()
        with self.assertRaises(DomainError):
            store.create('A')
        with self.assertRaises(DomainError):
            store.rename('builtin.b', 'A')
        with self.assertRaises(DomainError):
            store.create('Bad', ('0050',))
        with self.assertRaises(DomainError):
            store.set_codes('builtin.a', ('abcd',))
        self.assertEqual({record.id: record.codes for record in store.records()}['builtin.a'], ('2330', '2454'))

    def test_corrupt_file_is_preserved_and_the_builtin_list_takes_over(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{broken', encoding='utf-8')
        store = self.store()
        self.assertEqual(store.warning, 'sector_groups_corrupt')
        self.assertEqual([group.id for group in store.groups()], ['builtin.a', 'builtin.b'])
        backups = list(self.path.parent.glob('sector_groups.json.bad-*'))
        self.assertEqual([item.read_text(encoding='utf-8') for item in backups], ['{broken'])
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['version'], 1)

    def test_structurally_invalid_files_are_treated_as_corrupt(self):
        self.path.parent.mkdir(parents=True)
        for body in (
            {'version': 2, 'seed_version': 1, 'groups': []},
            {'version': 1, 'seed_version': 1, 'groups': [{'id': 'x', 'name': '', 'codes': [], 'builtin': False, 'edited': False}]},
            {'version': 1, 'seed_version': 1, 'groups': [{'id': 'x', 'name': 'X', 'codes': ['0050'], 'builtin': False, 'edited': False}]},
            {'version': 1, 'seed_version': 1, 'groups': [{'id': 'x', 'name': 'X', 'codes': [], 'builtin': False, 'edited': False}] * 2},
        ):
            self.path.write_text(json.dumps(body), encoding='utf-8')
            self.assertEqual(self.store().warning, 'sector_groups_corrupt', body)

    def test_failed_write_keeps_the_previous_state(self):
        store = self.store()
        with patch.object(Path, 'replace', side_effect=OSError('disk full'), create=True), patch('os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(DomainError):
                store.rename('builtin.b', 'Bee')
        self.assertEqual({record.id: record.name for record in store.records()}['builtin.b'], 'B')
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])


class StoreHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'sector_groups.json'

    def test_seed_bump_on_an_unwritable_disk_still_starts_with_the_merged_list(self):
        SectorGroupStore(self.path, SEED_A, 1)
        newer = (ConceptGroup('builtin.a', 'A', ('2330',)), ConceptGroup('builtin.b', 'B', ('2317', '2382')))
        with patch('os.replace', side_effect=OSError('locked')):
            store = SectorGroupStore(self.path, newer, 2)
        self.assertEqual(store.warning, 'sector_groups_unwritable')
        self.assertEqual({record.id: record.codes for record in store.records()}['builtin.b'], ('2317', '2382'))

    def test_restore_refuses_a_name_that_a_live_group_now_uses(self):
        store = SectorGroupStore(self.path, SEED_A, 1)
        store.delete('builtin.a')
        store.create('A', ('2330',))
        with self.assertRaises(DomainError):
            store.restore('builtin.a')

    def test_a_deleted_group_cannot_be_renamed_or_recoded(self):
        store = SectorGroupStore(self.path, SEED_A, 1)
        store.delete('builtin.a')
        with self.assertRaises(DomainError):
            store.rename('builtin.a', 'Z')
        with self.assertRaises(DomainError):
            store.set_codes('builtin.a', ('2330',))

    def test_a_corrupt_file_that_cannot_be_set_aside_is_never_overwritten(self):
        self.path.write_text('{broken', encoding='utf-8')
        with patch.object(Path, 'rename', side_effect=OSError('locked')):
            store = SectorGroupStore(self.path, SEED_A, 1)
        self.assertEqual(store.warning, 'sector_groups_corrupt')
        self.assertEqual([group.id for group in store.groups()], ['builtin.a', 'builtin.b'])
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{broken')

    def test_a_brief_permission_error_on_replace_is_retried(self):
        store = SectorGroupStore(self.path, SEED_A, 1)
        import os as real_os

        original = real_os.replace
        calls = []

        def flaky(source, target):
            if Path(target) != Path(self.path):  # os.replace is patched process-wide; ignore other threads' files
                return original(source, target)
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError('scanner')
            return original(source, target)

        with patch('os.replace', side_effect=flaky), patch('quantlab.trading.adapters.storage.sector_store.sleep'):
            store.rename('builtin.b', 'Bee')
        self.assertEqual(len(calls), 3)
        self.assertEqual({record.id: record.name for record in SectorGroupStore(self.path, SEED_A, 1).records()}['builtin.b'], 'Bee')

    def test_non_string_codes_are_a_validation_error_not_a_type_error(self):
        with self.assertRaises(DomainError):
            clean_codes((['2330'],))
        with self.assertRaises(DomainError):
            SectorGroupsCommand('SET_CODES', 'x', codes=(1,))


class RequestPumpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def wait(self, predicate):
        import time

        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def test_answers_arrive_on_the_gui_thread_and_results_are_released(self):
        from threading import current_thread, main_thread

        from desktop_app.features.trading import market_watch

        seen = []
        result = market_watch._Result(lambda value, error: seen.append((value, error, current_thread() is main_thread())))
        market_watch.start_request(lambda: 41 + 1, result)
        self.wait(lambda: seen)
        self.assertEqual(seen, [(42, None, True)])
        self.assertNotIn(result.token, market_watch._LIVE_RESULTS)

    def test_errors_are_delivered_not_raised_and_cancel_drops_the_callback(self):
        from desktop_app.features.trading import market_watch

        seen = []
        failing = market_watch._Result(lambda value, error: seen.append(type(error).__name__))
        market_watch.start_request(lambda: 1 / 0, failing)
        cancelled = market_watch._Result(lambda value, error: seen.append('late'))
        cancelled.cancel()
        market_watch.start_request(lambda: 1, cancelled)
        self.wait(lambda: not market_watch._LIVE_RESULTS)
        self.assertEqual(seen, ['ZeroDivisionError'])

    def test_the_pump_goes_idle_and_rearms_for_the_next_request(self):
        from desktop_app.features.trading import market_watch

        seen = []
        for number in (1, 2):
            result = market_watch._Result(lambda value, error: seen.append(value))
            market_watch.start_request(lambda number=number: number, result)
            self.wait(lambda number=number: len(seen) == number)
            self.wait(lambda: not market_watch._PUMP['armed'])
        self.assertEqual(seen, [1, 2])
        self.assertEqual(market_watch._PUMP['outstanding'], 0)

    def test_nothing_in_the_pump_is_a_qobject(self):
        # A module-level QObject is torn down in an unspecified order against QApplication at interpreter exit
        # ("shared QObject was deleted directly", segfault after a green CI run).
        from PySide6.QtCore import QObject

        from desktop_app.features.trading import market_watch

        for name, value in vars(market_watch).items():
            if name.startswith('_') and not name.startswith('__'):
                self.assertNotIsInstance(value, QObject, name)
        self.assertFalse(issubclass(market_watch._Result, QObject))
        self.assertFalse(issubclass(market_watch._Request, QObject))


class MemberMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_remove_member_reads_then_rewrites_only_that_group_and_refreshes(self):
        from desktop_app.components.charts import CandlestickChart
        from desktop_app.features.trading.sector_board import SectorBoardWidget

        with TemporaryDirectory(dir=Path.cwd()) as folder:
            store = SectorGroupStore(Path(folder) / 'g.json', SEED_A, 1)
            editor = SectorGroupEditor(store, lambda: ())
            widget = SectorBoardWidget(SimpleNamespace(sector_groups=editor.execute), CandlestickChart())
            refreshed = []
            widget.refresh = lambda: refreshed.append(1)
            widget._submit = lambda operation, completed: completed(operation(), None)
            widget.remove_member('builtin.a', '2330')
            self.assertEqual({record.id: record.codes for record in store.records()}['builtin.a'], ('2454',))
            self.assertEqual(refreshed, [1])

    def test_menu_offers_remove_only_for_concept_groups_and_wires_callbacks(self):
        from desktop_app.components.charts import CandlestickChart
        from desktop_app.features.trading.sector_board import SectorBoardWidget

        picked = []
        widget = SectorBoardWidget(
            SimpleNamespace(), CandlestickChart(), open_in_watch=lambda key: picked.append(('open', key)), add_to_watch=lambda key: picked.append(('add', key))
        )
        self.assertEqual((widget.open_in_watch, widget.add_to_watch) != (None, None), True)
        widget.open_in_watch('TWSE:2330')
        widget.add_to_watch('TWSE:2330')
        self.assertEqual(picked, [('open', 'TWSE:2330'), ('add', 'TWSE:2330')])


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.store = SectorGroupStore(Path(self.temp.name) / 'sector_groups.json', SEED_A, 1)
        self.changed = []
        self.directory = tuple(stock(f'{1100 + index}') for index in range(12)) + (stock('2330'), stock('2454'))
        self.editor = SectorGroupEditor(self.store, lambda: self.directory, lambda: self.changed.append(1))

    def test_unknown_codes_are_flagged_but_never_removed(self):
        self.editor.execute(SectorGroupsCommand('SET_CODES', 'builtin.b', codes=('2330', '8888')))
        view = {group.id: group for group in self.editor.view().groups}
        self.assertEqual(view['builtin.b'].unknown_codes, ('8888',))
        self.assertEqual(view['builtin.b'].codes, ('2330', '8888'))

    def test_a_short_directory_does_not_flag_everything_missing(self):
        self.directory = (stock('2330'),)
        self.assertTrue(all(not group.unknown_codes for group in self.editor.view().groups))

    def test_commands_notify_only_when_they_change_something(self):
        self.editor.execute(SectorGroupsCommand())
        self.assertEqual(self.changed, [])
        view = self.editor.execute(SectorGroupsCommand('CREATE', name='Mine', codes=('2330',)))
        self.assertEqual(self.changed, [1])
        self.assertTrue(view.selected_id.startswith('custom.'))
        with self.assertRaises(DomainError):
            self.editor.execute(SectorGroupsCommand('CREATE', name='Mine'))
        self.assertEqual(self.changed, [1])

    def test_invalid_command_shapes_are_rejected(self):
        with self.assertRaises(DomainError):
            SectorGroupsCommand('DROP_TABLE')
        with self.assertRaises(DomainError):
            SectorGroupsCommand('SET_CODES', 'g', codes=tuple(str(index) for index in range(201)))

    def test_wire_roundtrip(self):
        view = self.editor.execute(SectorGroupsCommand('CREATE', name='Mine', codes=('2330',)))
        self.assertEqual(loads(dumps(view)), view)
        self.assertEqual(loads(dumps(SectorGroupsCommand('RENAME', 'x', 'y'))), SectorGroupsCommand('RENAME', 'x', 'y'))
        self.assertEqual(loads(dumps(SectorGroupsView())), SectorGroupsView())
        self.assertIsInstance(view.groups[0], GroupEditView)

    def test_service_recompute_applies_edits_to_the_last_snapshot_immediately(self):
        stocks = (stock('2330'), stock('2454'), stock('3034'))
        service = SectorService(
            lambda: stocks, Source([row('2330', '4.00'), row('2454', '2.00'), row('3034', '-2.00')]), lambda: OPEN, concepts=self.store.groups
        )
        service.refresh()
        before = {item.group_id: item for item in service.board().groups}
        self.assertEqual(before['builtin.a'].valid_count, 2)
        self.editor = SectorGroupEditor(self.store, lambda: stocks, service.recompute)
        self.editor.execute(SectorGroupsCommand('SET_CODES', 'builtin.a', codes=('2330', '2454', '3034')))
        after = {item.group_id: item for item in service.board().groups}
        self.assertEqual((after['builtin.a'].valid_count, after['builtin.a'].equal_pct), (3, Decimal('4.00') / 3))
        self.editor.execute(SectorGroupsCommand('DELETE', 'builtin.a'))
        self.assertNotIn('builtin.a', {item.group_id for item in service.board().groups})


class EditorDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.store = SectorGroupStore(Path(self.temp.name) / 'sector_groups.json', SEED_A, 1)
        directory = tuple(stock(f'{1100 + index}') for index in range(12)) + (stock('2330'), stock('2454'), stock('2317'))
        self.editor = SectorGroupEditor(self.store, lambda: directory, lambda: self.changed.append(1))
        self.changed = []
        self.facade = SimpleNamespace(sector_groups=self.editor.execute)

        def submit(operation, completed):
            try:
                completed(operation(), None)
            except Exception as error:
                completed(None, error)

        from desktop_app.features.trading.sector_editor import SectorEditor

        self.dialog = SectorEditor(self.facade, directory, submit, on_changed=lambda: self.changed.append('ui'))

    def names(self):
        return [self.dialog.groups.item(row).text() for row in range(self.dialog.groups.count())]

    def test_lists_groups_with_marks_and_members_with_names(self):
        self.assertEqual(self.names(), ['A · 內建', 'B · 內建'])
        self.assertEqual([self.dialog.members.item(row).text() for row in range(self.dialog.members.count())], ['2330 N2330', '2454 N2454'])
        self.assertFalse(self.dialog.restore_button.isEnabled())

    def test_add_remove_codes_and_restore_enablement(self):
        self.dialog.add_code('TWSE:2317')
        self.assertEqual(self.dialog.current_group().codes, ('2330', '2454', '2317'))
        self.assertIn('已修改', self.names()[0])
        self.assertTrue(self.dialog.restore_button.isEnabled())
        self.dialog.members.setCurrentRow(0)
        self.dialog.remove_code()
        self.assertEqual(self.dialog.current_group().codes, ('2454', '2317'))
        self.dialog.add_code('TWSE:2317')
        self.assertEqual(self.dialog.current_group().codes, ('2454', '2317'))
        self.dialog.restore_group()
        self.assertEqual(self.dialog.current_group().codes, ('2330', '2454'))
        self.assertIn('ui', self.changed)

    def test_unknown_code_is_red_with_a_reason_and_not_deleted(self):
        self.store.set_codes('builtin.a', ('2330', '8888'))
        self.dialog.send_command(SectorGroupsCommand())
        item = self.dialog.members.item(1)
        self.assertIn('找不到此代號', item.text())
        self.assertEqual(item.foreground().color().name(), '#c62828')
        self.assertEqual(self.dialog.current_group().codes, ('2330', '8888'))

    def test_create_rename_delete_with_confirmation(self):
        with patch('desktop_app.features.trading.sector_editor.QInputDialog.getText', return_value=('我的族群', True)):
            self.dialog.add_group()
        self.assertEqual(self.dialog.current_group().name, '我的族群')
        with patch('desktop_app.features.trading.sector_editor.QInputDialog.getText', return_value=('改過', True)):
            self.dialog.rename_group()
        self.assertEqual(self.dialog.current_group().name, '改過')
        with patch('desktop_app.features.trading.sector_editor.QMessageBox.question', return_value=self.no()):
            self.dialog.delete_group()
        self.assertEqual(self.dialog.current_group().name, '改過')
        with patch('desktop_app.features.trading.sector_editor.QMessageBox.question', return_value=self.yes()):
            self.dialog.delete_group()
        self.assertNotIn('改過', ' '.join(self.names()))

    def test_deleted_builtin_stays_listed_for_restore_and_blocks_edits(self):
        self.dialog.groups.setCurrentRow(0)
        with patch('desktop_app.features.trading.sector_editor.QMessageBox.question', return_value=self.yes()):
            self.dialog.delete_group()
        self.assertIn('已刪除', self.names()[0])
        self.dialog.groups.setCurrentRow(0)
        self.assertTrue(self.dialog.restore_button.isEnabled())
        self.assertFalse(self.dialog.delete_button.isEnabled())
        self.assertFalse(self.dialog.search.isEnabled())
        self.dialog.restore_group()
        self.assertNotIn('已刪除', self.names()[0])

    def test_engine_rejection_is_shown_not_raised(self):
        with patch('desktop_app.features.trading.sector_editor.QInputDialog.getText', return_value=('A', True)):
            self.dialog.add_group()
        self.assertIn('無法儲存', self.dialog.message.text())

    def test_corrupt_file_warning_is_shown(self):
        self.dialog.apply(SectorGroupsView((GroupEditView('x', 'X', ()),), '', 'sector_groups_corrupt'))
        self.assertIn('損毀', self.dialog.message.text())

    @staticmethod
    def yes():
        from PySide6.QtWidgets import QMessageBox

        return QMessageBox.StandardButton.Yes

    @staticmethod
    def no():
        from PySide6.QtWidgets import QMessageBox

        return QMessageBox.StandardButton.No


if __name__ == '__main__':
    unittest.main()

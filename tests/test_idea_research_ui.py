"""Idea research dialog: plain text, clickable cited URLs, consent and event-only states (T4, T11, T19)."""

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QComboBox, QTableWidgetItem

import desktop_app.features.strategy.idea_research as page
from desktop_app.features.strategy.idea_labels import COLUMNS as _c_page_COLUMNS
from desktop_app.features.strategy.idea_events import event as _c_page_event
from desktop_app.features.strategy.idea_links import open_url as _c_page_open_url
from desktop_app.features.strategy import idea_links as _c_idea_links
from desktop_app.shell.host import PageState
from desktop_app.strings.catalog import ui_text
from quantlab.idea_research import IdeaStore

TASK = 'idea-' + 'b' * 32


def source(index, url, *, state='read', cited=False, title='Title'):
    return {
        'source_id': 's%d' % index,
        'url': url,
        'final_url': url,
        'title': title,
        'state': state,
        'cited_by_model': cited,
        'text_chars': 10,
        'error': None,
    }


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='idea-ui-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        model = QComboBox()
        model.addItem('Fixture model', 'gpt-fixture')
        self.state = PageState(
            root=self.root,
            jobs=SimpleNamespace(active=False, cancel=Mock()),
            chatgpt_controller=SimpleNamespace(active_registration='a' * 32),
            chatgpt_panel=SimpleNamespace(model=model),
            last_operation=None,
            strategy_page=SimpleNamespace(campaign_config=None, campaign_form=None),
            backtest_form=SimpleNamespace(build_payload=lambda: {'config': {}}),
        )
        self.host = SimpleNamespace(
            state=self.state,
            idea_records=IdeaStore,
            safe=lambda callback: callback(),
            start_job=Mock(return_value='job-1'),
            payload=Mock(return_value={'families': ['trend']}),
        )
        self.dialog = page.IdeaResearchDialog(self.host)
        self.addCleanup(self.dialog.deleteLater)

    def feed(self, *events):
        for event in events:
            self.dialog.apply({'task_id': TASK, **event})

    def start_task(self):
        self.feed({'kind': 'task', 'task': {'task_id': TASK, 'status': 'running', 'discovery': 'web_search'}})

    def test_consent_is_required_and_reset_after_each_run(self):
        self.dialog.start_button.click()
        self.host.start_job.assert_not_called()
        self.assertEqual(self.dialog.status.text(), ui_text('idea.consent_required'))
        self.dialog.consent_network.setChecked(True)
        self.dialog.start_button.click()
        self.host.start_job.assert_not_called()
        self.dialog.consent_plan.setChecked(True)
        self.dialog.start_button.click()
        operation, payload = self.host.start_job.call_args.args
        self.assertEqual(operation, 'ui_idea_research')
        self.assertEqual(payload['request']['consent'], {'network': True, 'plan_usage': True})
        self.assertEqual((payload['registration'], payload['model']), ('a' * 32, 'gpt-fixture'))
        self.assertEqual(payload['request']['instrument'], 'TMF')
        self.assertFalse(self.dialog.consent_network.isChecked() or self.dialog.consent_plan.isChecked())

    def test_t1_search_log_and_source_states_follow_worker_events(self):
        self.start_task()
        self.feed(
            {'kind': 'search', 'search': {'search_id': 'q1', 'query': None, 'status': 'in_progress', 'sources_returned': 0}},
            {'kind': 'search', 'search': {'search_id': 'q1', 'query': '台指期 通道突破', 'status': 'completed', 'sources_returned': 3}},
            {'kind': 'search', 'search': {'search_id': 'q2', 'query': 'breakout rules', 'status': 'completed', 'sources_returned': 2}},
            {'kind': 'source', 'source': source(1, 'https://alpha.example.org/a', state='pending')},
        )
        self.assertEqual(self.dialog.search_log.count(), 2)
        self.assertEqual(self.dialog.search_log.item(0).text(), ui_text('idea.search_line').format('台指期 通道突破', 3))
        self.assertEqual(self.dialog.sources.item(0, 0).text(), ui_text('idea.state.pending'))
        self.feed({'kind': 'source', 'source': source(1, 'https://alpha.example.org/a', state='loading')})
        self.assertEqual(self.dialog.sources.item(0, 0).text(), ui_text('idea.state.loading'))
        self.feed({'kind': 'source', 'source': source(1, 'https://alpha.example.org/a')})
        self.assertEqual(self.dialog.sources.item(0, 0).text(), ui_text('idea.state.read'))

    def test_t19_cited_urls_are_visible_and_open_in_system_browser(self):
        self.start_task()
        urls = ['https://alpha.example.org/a', 'https://beta.example.org/b?x=1&y=<2>']
        self.feed(
            {'kind': 'urls', 'urls': [{'url': urls[0], 'origin': ['sources', 'url_citation']}, {'url': urls[1], 'origin': ['sources']}]},
            {'kind': 'source', 'source': source(1, urls[0], cited=True)},
            {'kind': 'source', 'source': source(2, urls[1])},
        )
        column = _c_page_COLUMNS.index('url')
        for row, url in enumerate(urls):
            self.assertEqual(self.dialog.sources.item(row, column).text(), url)
        self.assertEqual(self.dialog.sources.item(0, _c_page_COLUMNS.index('origin')).text(), ui_text('idea.origin.cited'))
        self.assertEqual(self.dialog.sources.item(1, _c_page_COLUMNS.index('origin')).text(), ui_text('idea.origin.search_only'))
        with patch.object(_c_idea_links.QDesktopServices, 'openUrl', return_value=True) as opened:
            for row in range(2):
                button = self.dialog.sources.cellWidget(row, _c_page_COLUMNS.index('open'))
                self.assertTrue(button.isVisible() or not self.dialog.isVisible())
                button.click()
            self.dialog.sources.cellDoubleClicked.emit(0, column)
        self.assertEqual([call.args[0].toString() for call in opened.call_args_list], [urls[0], _c_idea_links.QUrl(urls[1]).toString(), urls[0]])
        # A cited URL the app refused to fetch is still listed and clickable.
        refused = 'https://www.yuanta.com.tw/report'
        self.feed({'kind': 'urls', 'urls': self.dialog.record['urls'] + [{'url': refused, 'origin': ['url_citation'], 'reject_reason': 'policy_blocked'}]})
        self.assertEqual(self.dialog.sources.rowCount(), 3)
        self.assertEqual(self.dialog.sources.item(2, column).text(), refused)
        self.assertEqual(self.dialog.sources.item(2, 0).text(), ui_text('idea.state.not_fetched'))
        self.assertEqual(self.dialog.sources.item(2, _c_page_COLUMNS.index('reason')).text(), 'policy_blocked')
        with patch.object(_c_idea_links.QDesktopServices, 'openUrl', return_value=True) as opened:
            self.dialog.sources.cellWidget(2, _c_page_COLUMNS.index('open')).click()
        self.assertEqual(opened.call_args.args[0].toString(), refused)
        with patch.object(_c_idea_links.QDesktopServices, 'openUrl') as opened:
            self.assertFalse(_c_page_open_url('http://alpha.example.org/'))
            self.assertFalse(_c_page_open_url('file:///C:/Windows/win.ini'))
            self.assertFalse(_c_page_open_url('javascript:alert(1)'))
        opened.assert_not_called()

    def test_web_text_is_plain_text_only(self):
        self.start_task()
        hostile = '<b>bold</b><img src="https://tracker.example/x.png"><script>alert(1)</script>'
        self.feed({'kind': 'source', 'source': source(1, 'https://alpha.example.org/a', title=hostile)})
        item = self.dialog.sources.item(0, _c_page_COLUMNS.index('title'))
        self.assertIsInstance(item, QTableWidgetItem)
        self.assertEqual(item.text(), hostile)
        IdeaStore(self.root).write_text(TASK, 's1', hostile)
        self.dialog.sources.selectRow(0)
        self.assertEqual(self.dialog.reader.toPlainText(), hostile)
        self.assertEqual(type(self.dialog.reader).__name__, 'QPlainTextEdit')
        self.assertEqual(type(self.dialog.candidate_detail).__name__, 'QPlainTextEdit')

    def test_t4_unavailable_search_shows_fallbacks(self):
        self.start_task()
        self.assertFalse(self.dialog.fallback.isVisibleTo(self.dialog))
        self.feed({'kind': 'status', 'status': 'search_unavailable', 'stop_reason': None, 'error': 'subscription_sharing_unsupported_capability'})
        self.assertTrue(self.dialog.fallback.isVisibleTo(self.dialog))
        self.assertEqual(self.dialog.fallback.text(), ui_text('idea.unavailable'))
        self.dialog.use_urls.click()
        self.assertEqual(self.dialog.discovery_mode(), 'user_urls')
        self.dialog.consent_network.setChecked(True)
        self.dialog.consent_plan.setChecked(True)
        self.dialog.urls.setPlainText('https://alpha.example.org/a\n\nhttps://beta.example.org/b\n')
        self.dialog.start_button.click()
        payload = self.host.start_job.call_args.args[1]
        self.assertEqual(payload['request']['discovery'], 'user_urls')
        self.assertEqual(payload['request']['urls'], ['https://alpha.example.org/a', 'https://beta.example.org/b'])
        self.dialog.use_fixed.click()
        self.assertEqual(self.dialog.discovery_mode(), 'fixed_sources')

    def test_t11_stopped_worker_leaves_unfinished_sources_cancelled(self):
        self.start_task()
        self.feed(
            {'kind': 'source', 'source': source(1, 'https://alpha.example.org/a')},
            {'kind': 'source', 'source': source(2, 'https://beta.example.org/b', state='loading')},
            {'kind': 'source', 'source': source(3, 'https://gamma.example.org/c', state='pending')},
        )
        self.state.jobs.active = True
        self.state.last_operation = 'ui_idea_research'
        self.dialog.refresh_controls()
        self.assertTrue(self.dialog.cancel_button.isEnabled())
        self.dialog.cancel_button.click()
        self.state.jobs.cancel.assert_called_once()
        shell = SimpleNamespace(
            last_operation='ui_idea_research', strategy_page=SimpleNamespace(idea_dialog=self.dialog), record_event=Mock(), notify_local=Mock(), status=Mock()
        )
        self.state.jobs.active = False
        self.assertTrue(_c_page_event(shell, {'type': 'cancelled'}))
        self.assertEqual([s['state'] for s in self.dialog.record['sources']], ['read', 'cancelled', 'cancelled'])
        self.assertEqual(self.dialog.record['status'], 'cancelled')
        shell.record_event.assert_called_once_with('ui_idea_research', 'cancelled')

    def test_adopt_only_backtestable_candidates(self):
        self.start_task()
        candidates = [
            {
                'candidate_id': 'c1',
                'name': 'ok',
                'backtestable': True,
                'rejection_reason': None,
                'family': 'trend',
                'parameters': {'fast': 5, 'slow': 20},
                'evidence': [],
            },
            {'candidate_id': 'c2', 'name': 'bad', 'backtestable': False, 'rejection_reason': 'quote_not_found', 'evidence': []},
        ]
        self.feed({'kind': 'candidates', 'candidates': candidates}, {'kind': 'status', 'status': 'completed'})
        self.dialog.candidates.setCurrentRow(1)
        self.assertFalse(self.dialog.adopt_button.isEnabled())
        self.assertIn('quote_not_found', self.dialog.candidate_detail.toPlainText())
        self.dialog.candidates.setCurrentRow(0)
        self.assertTrue(self.dialog.adopt_button.isEnabled())
        self.dialog.adopt_button.click()
        operation, payload = self.host.start_job.call_args.args
        self.assertEqual(operation, 'ui_idea_adopt')
        self.assertEqual(payload, {'task_id': TASK, 'candidate_id': 'c1', 'config': {'families': ['trend']}})

    def test_event_hook_ignores_other_operations(self):
        shell = SimpleNamespace(last_operation='ui_backtest')
        self.assertFalse(_c_page_event(shell, {'type': 'result'}))

    def test_missing_sign_in_blocks_start(self):
        self.state.chatgpt_controller.active_registration = None
        self.dialog.consent_network.setChecked(True)
        self.dialog.consent_plan.setChecked(True)
        self.dialog.start_button.click()
        self.host.start_job.assert_not_called()
        self.assertEqual(self.dialog.status.text(), ui_text('idea.sign_in_required'))


if __name__ == '__main__':
    unittest.main()

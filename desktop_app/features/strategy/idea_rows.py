from PySide6.QtWidgets import QListWidgetItem, QPushButton, QTableWidgetItem
from desktop_app.strings.catalog import ui_text
from desktop_app.features.strategy.idea_labels import COLUMNS, STATES, STATE_TEXT, STATUS_TEXT, STOP_TEXT
from desktop_app.features.strategy.idea_links import open_url


def _plain(value):
    item = QTableWidgetItem(str(value) if value is not None else '')
    item.setToolTip(item.text())
    return item


class IdeaRows:
    def __init__(self, view):
        self.view = view

    def render_searches(self):
        self.view.search_log.clear()
        for search in (self.view.record or {}).get('searches', []):
            if search.get('query'):
                text = ui_text('idea.search_line').format(search['query'], search.get('sources_returned', 0))
            else:
                text = ui_text('idea.search_line_pending')
            self.view.search_log.addItem(QListWidgetItem(text))

    def _origin(self, source):
        row = next((r for r in (self.view.record or {}).get('urls', []) if r.get('url') == source.get('url')), {})
        origin = row.get('origin') or []
        if source.get('cited_by_model') or 'url_citation' in origin:
            return ui_text('idea.origin.cited')
        if 'fixed_sources' in origin:
            return ui_text('idea.origin.fixed')
        if 'user_urls' in origin:
            return ui_text('idea.origin.pasted')
        return ui_text('idea.origin.search_only')

    def _row_url(self, row):
        item = self.view.sources.item(row, COLUMNS.index('url'))
        return item.text() if item is not None else None

    def render_sources(self):
        sources = (self.view.record or {}).get('sources', [])
        fetched = {s.get('url') for s in sources}
        cited = [r for r in (self.view.record or {}).get('urls', []) if 'url_citation' in (r.get('origin') or []) and r.get('url') not in fetched]
        rows = [
            (
                ui_text(STATE_TEXT[s.get('state') if s.get('state') in STATES else 'failed']),
                s.get('title') or '',
                s.get('final_url') or s.get('url'),
                s.get('text_chars', 0),
                self.view._origin(s),
                s.get('error') or '',
            )
            for s in sources
        ]
        rows += [(ui_text('idea.state.not_fetched'), '', r['url'], 0, ui_text('idea.origin.cited'), r.get('reject_reason') or '') for r in cited]
        self.view.sources.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.view.sources.setItem(row, column, _plain(value))
            button = QPushButton(ui_text('idea.open_url'))
            button.setObjectName('idea_open_url_%d' % row)
            button.clicked.connect(lambda checked=False, target=values[2]: open_url(target))
            self.view.sources.setCellWidget(row, COLUMNS.index('open'), button)

    def show_source(self):
        row = self.view.sources.currentRow()
        sources = (self.view.record or {}).get('sources', [])
        if not 0 <= row < len(sources):
            return
        self.view.reader.setPlainText(self.view.records().read_text(self.view.record['task_id'], sources[row]['source_id']))

    def render_candidates(self):
        selected = self.view.candidates.currentRow()
        self.view.candidates.clear()
        for candidate in (self.view.record or {}).get('candidates', []):
            mark = ui_text('idea.candidate.backtestable') if candidate.get('backtestable') else ui_text('idea.candidate.not_backtestable')
            self.view.candidates.addItem(QListWidgetItem('%s  [%s]' % (candidate.get('name') or candidate.get('candidate_id'), mark)))
        self.view.candidate_detail.clear()
        self.view.candidate_summary.setText(ui_text('redesign.strategy.idea_empty'))
        if self.view.candidates.count():
            self.view.candidates.setCurrentRow(min(max(0, selected), self.view.candidates.count() - 1))

    def show_candidate(self, row):
        candidates = (self.view.record or {}).get('candidates', [])
        if not 0 <= row < len(candidates):
            self.view.candidate_detail.clear()
            self.view.candidate_summary.setText(ui_text('redesign.strategy.idea_empty'))
            self.view.refresh_controls()
            return
        c = candidates[row]
        urls = {s['source_id']: s.get('final_url') or s.get('url') for s in self.view.record.get('sources', [])}
        lines = [
            ui_text('idea.candidate.idea') + (c.get('idea') or ''),
            ui_text('idea.candidate.family') + '%s %s' % (c.get('family') or '-', c.get('parameters') or {}),
            ui_text('idea.candidate.rules') + (c.get('rules_zh') or ''),
            ui_text('idea.candidate.explicit_rules') + '; '.join(c.get('explicit_rules') or []),
            ui_text('idea.candidate.assumptions') + '; '.join(c.get('assumptions') or []),
            ui_text('idea.candidate.data') + ', '.join(c.get('data_required') or []),
        ]
        for item in c.get('evidence') or []:
            lines.append(ui_text('idea.candidate.evidence').format(item.get('source_id'), urls.get(item.get('source_id'), ''), item.get('quote')))
        lines += [ui_text('idea.candidate.claims') + '; '.join(c.get('source_claims') or [])]
        lines += [ui_text('idea.candidate.limitations') + '; '.join(c.get('limitations') or [])]
        if c.get('rejection_reason'):
            lines.append(ui_text('idea.candidate.reason') + c['rejection_reason'])
        reason = c.get('rejection_reason') or ui_text('redesign.strategy.idea_pending')
        eligibility = (
            ui_text('redesign.strategy.idea_ready')
            if c.get('backtestable') is True and self.view.record.get('status') == 'completed'
            else ui_text('redesign.strategy.idea_blocked').format(reason)
        )
        self.view.candidate_summary.setText((c.get('idea') or c.get('name') or '') + '\n\n' + eligibility)
        self.view.candidate_detail.setPlainText('\n'.join(lines))
        self.view.refresh_controls()

    def render_status(self):
        record = self.view.record or {}
        status = record.get('status') or 'running'
        text = (
            ui_text(STATUS_TEXT[status])
            if status in ('running', 'completed', 'cancelled', 'search_unavailable', 'quota_paused', 'no_sources', 'failed')
            else ''
        )
        if record.get('stop_reason') in ('search_limit', 'search_timeout'):
            text += ' ' + ui_text(STOP_TEXT[record['stop_reason']])
        if record.get('error') and status == 'failed':
            text += ' (' + str(record['error']) + ')'
        self.view.status.setText(text)
        self.view._set_fallback(status == 'search_unavailable')
        self.view.show_candidate(self.view.candidates.currentRow())

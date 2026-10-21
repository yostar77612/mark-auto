"""Strategy idea research dialog: search log, source cards, reader and candidates.

Every web-derived string is shown as plain text. Source states change only on
worker events; URLs open in the system browser and never load in this app.
"""

import urllib.parse

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from desktop_strings import ui_text

FAMILY_TEXT = {
    'trend': 'idea.family.trend',
    'mean_reversion': 'idea.family.mean_reversion',
    'channel_breakout': 'idea.family.channel_breakout',
    'momentum': 'idea.family.momentum',
    'volatility_compression': 'idea.family.volatility_compression',
}
TIMEFRAME_TEXT = {'1d': 'idea.timeframe_1d', '1h': 'idea.timeframe_1h', '5m': 'idea.timeframe_5m'}
DISCOVERY_TEXT = {
    'web_search': 'idea.discovery.web_search',
    'fixed_sources': 'idea.discovery.fixed_sources',
    'user_urls': 'idea.discovery.user_urls',
}
STATE_TEXT = {
    'pending': 'idea.state.pending',
    'loading': 'idea.state.loading',
    'read': 'idea.state.read',
    'partial': 'idea.state.partial',
    'failed': 'idea.state.failed',
    'blocked': 'idea.state.blocked',
    'cancelled': 'idea.state.cancelled',
}
STATUS_TEXT = {
    'running': 'idea.status.running',
    'completed': 'idea.status.completed',
    'cancelled': 'idea.status.cancelled',
    'search_unavailable': 'idea.status.search_unavailable',
    'quota_paused': 'idea.status.quota_paused',
    'no_sources': 'idea.status.no_sources',
    'failed': 'idea.status.failed',
}
STOP_TEXT = {'search_limit': 'idea.stop_reason.search_limit', 'search_timeout': 'idea.stop_reason.search_timeout'}
COLUMN_TEXT = {
    'state': 'idea.column.state',
    'title': 'idea.column.title',
    'url': 'idea.column.url',
    'chars': 'idea.column.chars',
    'origin': 'idea.column.origin',
    'reason': 'idea.column.reason',
    'open': 'idea.column.open',
}
FAMILIES = tuple(FAMILY_TEXT)
STATES = tuple(STATE_TEXT)
COLUMNS = tuple(COLUMN_TEXT)


def open_url(url):
    """Hand only https URLs to the system browser; nothing is rendered in-process."""
    if type(url) is not str or urllib.parse.urlsplit(url).scheme != 'https':
        return False
    return QDesktopServices.openUrl(QUrl(url))


def _plain(value):
    item = QTableWidgetItem(str(value) if value is not None else '')
    item.setToolTip(item.text())
    return item


class IdeaResearchDialog(QDialog):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.state = host.state
        self.record = None
        self.setObjectName('idea_research_dialog')
        self.setWindowTitle(ui_text('idea.dialog_title'))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.market = QComboBox()
        self.market.addItem(ui_text('idea.market_tmf'), 'TMF')
        form.addRow(ui_text('idea.market'), self.market)
        scope = QLabel(ui_text('idea.market_scope_note'))
        scope.setWordWrap(True)
        form.addRow(scope)
        self.timeframe = QComboBox()
        for value in ('1d', '1h', '5m'):
            self.timeframe.addItem(ui_text(TIMEFRAME_TEXT[value]), value)
        form.addRow(ui_text('idea.timeframe'), self.timeframe)
        self.family = QComboBox()
        self.family.addItem(ui_text('idea.direction_any'), None)
        for family in FAMILIES:
            self.family.addItem(ui_text(FAMILY_TEXT[family]), family)
        form.addRow(ui_text('idea.direction_family'), self.family)
        self.direction = QLineEdit()
        self.direction.setMaxLength(40)
        self.direction.setObjectName('idea_direction_text')
        form.addRow(ui_text('idea.direction_text'), self.direction)
        self.discovery = QButtonGroup(self)
        discovery = QHBoxLayout()
        for index, value in enumerate(('web_search', 'fixed_sources', 'user_urls')):
            button = QRadioButton(ui_text(DISCOVERY_TEXT[value]))
            button.setObjectName('idea_discovery_' + value)
            button.setProperty('discovery', value)
            button.setChecked(index == 0)
            self.discovery.addButton(button, index)
            discovery.addWidget(button)
        form.addRow(ui_text('idea.discovery'), discovery)
        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText(ui_text('idea.urls_placeholder'))
        self.urls.setObjectName('idea_user_urls')
        self.urls.setMaximumHeight(90)
        form.addRow(self.urls)
        self.discovery.buttonToggled.connect(lambda *_: self.urls.setVisible(self.discovery_mode() == 'user_urls'))
        self.urls.setVisible(False)
        self.consent_network = QCheckBox(ui_text('idea.consent_network'))
        self.consent_network.setObjectName('idea_consent_network')
        self.consent_plan = QCheckBox(ui_text('idea.consent_plan'))
        self.consent_plan.setObjectName('idea_consent_plan')
        layout.addWidget(self.consent_network)
        layout.addWidget(self.consent_plan)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.start_button = self._button(actions, 'idea.start', 'idea_start', self.start)
        self.cancel_button = self._button(actions, 'idea.cancel', 'idea_cancel', self.cancel)
        self.retry_button = self._button(actions, 'idea.retry_failed', 'idea_retry', self.retry)
        self.clear_button = self._button(actions, 'idea.clear_temp', 'idea_clear_temp', self.clear_temp)
        self.status = QLabel('')
        self.status.setObjectName('idea_status')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.fallback = QLabel(ui_text('idea.unavailable'))
        self.fallback.setWordWrap(True)
        fallback = QHBoxLayout()
        self.use_fixed = self._button(fallback, 'idea.use_fixed', 'idea_use_fixed', lambda: self._choose('fixed_sources'))
        self.use_urls = self._button(fallback, 'idea.use_urls', 'idea_use_urls', lambda: self._choose('user_urls'))
        layout.addWidget(self.fallback)
        layout.addLayout(fallback)
        self._set_fallback(False)
        layout.addWidget(QLabel(ui_text('idea.search_log')))
        self.search_log = QListWidget()
        self.search_log.setObjectName('idea_search_log')
        self.search_log.setMaximumHeight(110)
        layout.addWidget(self.search_log)
        layout.addWidget(QLabel(ui_text('idea.sources')))
        self.sources = QTableWidget(0, len(COLUMNS))
        self.sources.setObjectName('idea_sources')
        self.sources.setHorizontalHeaderLabels([ui_text(COLUMN_TEXT[c]) for c in COLUMNS])
        self.sources.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.sources.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sources.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sources.itemSelectionChanged.connect(self.show_source)
        self.sources.cellDoubleClicked.connect(lambda row, column: column == COLUMNS.index('url') and open_url(self._row_url(row)))
        layout.addWidget(self.sources)
        layout.addWidget(QLabel(ui_text('idea.reader')))
        self.reader = QPlainTextEdit()
        self.reader.setObjectName('idea_reader')
        self.reader.setReadOnly(True)
        layout.addWidget(self.reader)
        layout.addWidget(QLabel(ui_text('idea.candidates')))
        self.candidates = QListWidget()
        self.candidates.setObjectName('idea_candidates')
        self.candidates.currentRowChanged.connect(self.show_candidate)
        layout.addWidget(self.candidates)
        self.candidate_detail = QPlainTextEdit()
        self.candidate_detail.setObjectName('idea_candidate_detail')
        self.candidate_detail.setReadOnly(True)
        layout.addWidget(self.candidate_detail)
        adopt = QHBoxLayout()
        layout.addLayout(adopt)
        self.adopt_button = self._button(adopt, 'idea.adopt', 'idea_adopt', self.adopt)
        self.refresh_controls()

    def _button(self, layout, key, name, callback):
        button = QPushButton(ui_text(key))
        button.setObjectName(name)
        button.clicked.connect(lambda checked=False: self.host.safe(callback))
        layout.addWidget(button)
        return button

    def discovery_mode(self):
        button = self.discovery.checkedButton()
        return button.property('discovery') if button is not None else 'web_search'

    def _choose(self, mode):
        for button in self.discovery.buttons():
            button.setChecked(button.property('discovery') == mode)
        self._set_fallback(False)

    def _set_fallback(self, visible):
        for widget in (self.fallback, self.use_fixed, self.use_urls):
            widget.setVisible(visible)

    def busy(self):
        return bool(getattr(self.state, 'jobs', None) is not None and self.state.jobs.active)

    def refresh_controls(self):
        busy = self.busy()
        status = (self.record or {}).get('status')
        self.start_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy and status == 'running')
        failed = any(s.get('state') in ('failed', 'cancelled') for s in (self.record or {}).get('sources', []))
        self.retry_button.setEnabled(not busy and status in ('completed', 'no_sources', 'failed', 'cancelled') and failed)
        self.clear_button.setEnabled(not busy)
        row = self.candidates.currentRow()
        candidates = (self.record or {}).get('candidates', [])
        selectable = 0 <= row < len(candidates) and candidates[row].get('backtestable') is True and status == 'completed'
        self.adopt_button.setEnabled(not busy and selectable)

    def _identity(self):
        controller = getattr(self.state, 'chatgpt_controller', None)
        panel = getattr(self.state, 'chatgpt_panel', None)
        registration = getattr(controller, 'active_registration', None)
        model = panel.model.currentData() if panel is not None and hasattr(panel, 'model') else None
        if not registration or not model:
            self.status.setText(ui_text('idea.sign_in_required'))
            return None
        return registration, model

    def _consent(self):
        if not (self.consent_network.isChecked() and self.consent_plan.isChecked()):
            self.status.setText(ui_text('idea.consent_required'))
            return None
        return {'network': True, 'plan_usage': True}

    def _reset_consent(self):
        # Consent covers exactly one run; every new run asks again.
        self.consent_network.setChecked(False)
        self.consent_plan.setChecked(False)

    def start(self):
        consent = self._consent()
        if consent is None:
            return None
        identity = self._identity()
        if identity is None:
            return None
        registration, model = identity
        request = {
            'instrument': self.market.currentData(),
            'timeframe': self.timeframe.currentData(),
            'direction': {'family_hint': self.family.currentData(), 'text': self.direction.text().strip()},
            'discovery': self.discovery_mode(),
            'consent': consent,
        }
        if request['discovery'] == 'user_urls':
            request['urls'] = [line.strip() for line in self.urls.toPlainText().splitlines() if line.strip()]
            if not 1 <= len(request['urls']) <= 8:
                self.status.setText(ui_text('idea.need_urls'))
                return None
        job = self.host.start_job('ui_idea_research', {'request': request, 'registration': registration, 'model': model})
        self._reset_consent()
        self._set_fallback(False)
        self.status.setText(ui_text('idea.status.running'))
        self.refresh_controls()
        return job

    def retry(self):
        if self.record is None:
            return None
        consent = self._consent()
        if consent is None:
            return None
        identity = self._identity()
        if identity is None:
            return None
        registration, model = identity
        job = self.host.start_job(
            'ui_idea_research', {'retry_task_id': self.record['task_id'], 'consent': consent, 'registration': registration, 'model': model}
        )
        self._reset_consent()
        self.refresh_controls()
        return job

    def cancel(self):
        if self.busy() and getattr(self.state, 'last_operation', None) == 'ui_idea_research':
            self.state.jobs.cancel()
            self.status.setText(ui_text('job.cancel_notice'))

    def clear_temp(self):
        if self.busy():
            self.status.setText(ui_text('ui.start_job.job_busy'))
            return
        # Keep operation-specific dependencies out of module startup.
        from quantlab.idea_research import IdeaStore

        removed = IdeaStore(self.state.root).purge(0, max_age=0)
        self.reader.clear()
        self.status.setText(ui_text('idea.cleared').format(removed))

    def adopt(self):
        row = self.candidates.currentRow()
        candidate = self.record['candidates'][row]
        page = self.state.strategy_page
        config = self.host.payload(page.campaign_config, lambda: page.campaign_form.build_payload(self.state.backtest_form.build_payload()['config']))
        job = self.host.start_job('ui_idea_adopt', {'task_id': self.record['task_id'], 'candidate_id': candidate['candidate_id'], 'config': config})
        self.status.setText(ui_text('idea.adopting'))
        self.refresh_controls()
        return job

    # Worker events only.
    def apply(self, event):
        kind = event.get('kind')
        if kind == 'task':
            self.record = {**event['task'], 'searches': [], 'urls': [], 'sources': [], 'candidates': []}
            if self.record.get('status') == 'running' and self.record.get('discovery') is not None:
                self.search_log.clear()
                self.sources.setRowCount(0)
                self.candidates.clear()
                self.candidate_detail.clear()
                self.reader.clear()
        if self.record is None or event.get('task_id') != self.record.get('task_id'):
            return
        if kind == 'search':
            self._upsert('searches', 'search_id', event['search'])
            self.render_searches()
        elif kind == 'urls':
            self.record['urls'] = event['urls']
            self.render_sources()
        elif kind == 'source':
            self._upsert('sources', 'source_id', event['source'])
            self.render_sources()
        elif kind == 'extracting':
            self.status.setText(ui_text('idea.progress.extracting'))
        elif kind == 'candidates':
            self.record['candidates'] = event['candidates']
            self.render_candidates()
        elif kind == 'status':
            self.record.update(status=event['status'], stop_reason=event.get('stop_reason'), error=event.get('error'))
            self.render_status()
        self.refresh_controls()

    def _upsert(self, field, key, value):
        rows = self.record.setdefault(field, [])
        for index, row in enumerate(rows):
            if row.get(key) == value.get(key):
                rows[index] = value
                return
        rows.append(value)

    def load_record(self, task_id):
        # Keep operation-specific dependencies out of module startup.
        from quantlab.idea_research import IdeaStore

        self.record = IdeaStore(self.state.root).load(task_id)
        self.render_searches()
        self.render_sources()
        self.render_candidates()
        self.render_status()
        self.refresh_controls()

    def job_ended(self, kind):
        """A stopped worker cannot report again; unfinished sources end as cancelled."""
        if self.record is not None and self.record.get('status') == 'running':
            status = 'cancelled' if kind in ('cancelled', 'canceled') else 'failed'
            self.record['status'] = status
            for source in self.record.get('sources', []):
                if source.get('state') in ('pending', 'loading'):
                    source['state'] = 'cancelled'
            self.render_sources()
            self.render_status()
        self.refresh_controls()

    def render_searches(self):
        self.search_log.clear()
        for search in (self.record or {}).get('searches', []):
            if search.get('query'):
                text = ui_text('idea.search_line').format(search['query'], search.get('sources_returned', 0))
            else:
                text = ui_text('idea.search_line_pending')
            self.search_log.addItem(QListWidgetItem(text))

    def _origin(self, source):
        row = next((r for r in (self.record or {}).get('urls', []) if r.get('url') == source.get('url')), {})
        origin = row.get('origin') or []
        if source.get('cited_by_model') or 'url_citation' in origin:
            return ui_text('idea.origin.cited')
        if 'fixed_sources' in origin:
            return ui_text('idea.origin.fixed')
        if 'user_urls' in origin:
            return ui_text('idea.origin.pasted')
        return ui_text('idea.origin.search_only')

    def _row_url(self, row):
        item = self.sources.item(row, COLUMNS.index('url'))
        return item.text() if item is not None else None

    def render_sources(self):
        sources = (self.record or {}).get('sources', [])
        fetched = {s.get('url') for s in sources}
        # Every URL GPT cited stays visible and clickable, including ones the app did not fetch.
        cited = [r for r in (self.record or {}).get('urls', []) if 'url_citation' in (r.get('origin') or []) and r.get('url') not in fetched]
        rows = [
            (
                ui_text(STATE_TEXT[s.get('state') if s.get('state') in STATES else 'failed']),
                s.get('title') or '',
                s.get('final_url') or s.get('url'),
                s.get('text_chars', 0),
                self._origin(s),
                s.get('error') or '',
            )
            for s in sources
        ]
        rows += [(ui_text('idea.state.not_fetched'), '', r['url'], 0, ui_text('idea.origin.cited'), r.get('reject_reason') or '') for r in cited]
        self.sources.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.sources.setItem(row, column, _plain(value))
            button = QPushButton(ui_text('idea.open_url'))
            button.setObjectName('idea_open_url_%d' % row)
            button.clicked.connect(lambda checked=False, target=values[2]: open_url(target))
            self.sources.setCellWidget(row, COLUMNS.index('open'), button)

    def show_source(self):
        row = self.sources.currentRow()
        sources = (self.record or {}).get('sources', [])
        if not 0 <= row < len(sources):
            return
        # Keep operation-specific dependencies out of module startup.
        from quantlab.idea_research import IdeaStore

        self.reader.setPlainText(IdeaStore(self.state.root).read_text(self.record['task_id'], sources[row]['source_id']))

    def render_candidates(self):
        self.candidates.clear()
        for candidate in (self.record or {}).get('candidates', []):
            mark = ui_text('idea.candidate.backtestable') if candidate.get('backtestable') else ui_text('idea.candidate.not_backtestable')
            self.candidates.addItem(QListWidgetItem('%s  [%s]' % (candidate.get('name') or candidate.get('candidate_id'), mark)))
        self.candidate_detail.clear()

    def show_candidate(self, row):
        candidates = (self.record or {}).get('candidates', [])
        if not 0 <= row < len(candidates):
            self.candidate_detail.clear()
            self.refresh_controls()
            return
        c = candidates[row]
        urls = {s['source_id']: s.get('final_url') or s.get('url') for s in self.record.get('sources', [])}
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
        self.candidate_detail.setPlainText('\n'.join(lines))
        self.refresh_controls()

    def render_status(self):
        record = self.record or {}
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
        self.status.setText(text)
        self._set_fallback(status == 'search_unavailable')


def dialog_for(shell):
    page = getattr(shell, 'strategy_page', None)
    return getattr(page, 'idea_dialog', None) if page is not None else None


def event(shell, packet):
    """Route ui_idea_research worker events to the dialog. Other operations pass through."""
    if getattr(shell, 'last_operation', None) != 'ui_idea_research':
        return False
    dialog = dialog_for(shell)
    kind = packet.get('type')
    if dialog is not None:
        if kind == 'progress' and isinstance(packet.get('idea_event'), dict):
            dialog.apply(packet['idea_event'])
        elif kind == 'result':
            task_id = (packet.get('result') or {}).get('task_id')
            if task_id:
                dialog.load_record(task_id)
        elif kind in ('cancelled', 'canceled', 'error', 'failed'):
            dialog.job_ended(kind)
    record = getattr(shell, 'record_event', None)
    if record is not None and kind != 'progress':
        record('ui_idea_research', kind)
    notify = getattr(shell, 'notify_local', None)
    if notify is not None and kind == 'result':
        status = (packet.get('result') or {}).get('status')
        notify(
            ui_text(STATUS_TEXT[status]) if status in ('completed', 'cancelled', 'search_unavailable', 'quota_paused', 'no_sources', 'failed') else '',
            completion=True,
        )
    elif notify is not None and kind in ('error', 'failed'):
        # Keep operation-specific dependencies out of module startup.
        from desktop_pages.job_progress import failure_notice

        notify(failure_notice(shell, packet), error=True, completion=True)
    status = getattr(shell, 'status', None)
    if status is not None and kind in ('result', 'error', 'failed', 'cancelled', 'canceled'):
        status.clear()
    elif status is not None and kind == 'progress':
        status.setText(packet.get('message') or '')
    return True

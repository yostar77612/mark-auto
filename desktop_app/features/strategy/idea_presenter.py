from desktop_app.strings.catalog import ui_text


class IdeaPresenter:
    def __init__(self, view):
        self.view = view

    def discovery_mode(self):
        button = self.view.discovery.checkedButton()
        return button.property('discovery') if button is not None else 'web_search'

    def _choose(self, mode):
        for button in self.view.discovery.buttons():
            button.setChecked(button.property('discovery') == mode)
        self.view._set_fallback(False)

    def _set_fallback(self, visible):
        for widget in (self.view.fallback, self.view.use_fixed, self.view.use_urls):
            widget.setVisible(visible)

    def busy(self):
        return bool(getattr(self.view.state, 'jobs', None) is not None and self.view.state.jobs.active)

    def refresh_controls(self):
        busy = self.view.busy()
        status = (self.view.record or {}).get('status')
        self.view.start_button.setEnabled(not busy)
        self.view.cancel_button.setEnabled(busy and status == 'running')
        failed = any((s.get('state') in ('failed', 'cancelled') for s in (self.view.record or {}).get('sources', [])))
        self.view.retry_button.setEnabled(not busy and status in ('completed', 'no_sources', 'failed', 'cancelled') and failed)
        self.view.clear_button.setEnabled(not busy)
        row = self.view.candidates.currentRow()
        candidates = (self.view.record or {}).get('candidates', [])
        selectable = 0 <= row < len(candidates) and candidates[row].get('backtestable') is True and (status == 'completed')
        self.view.adopt_button.setEnabled(not busy and selectable)

    def _identity(self):
        controller = getattr(self.view.state, 'chatgpt_controller', None)
        panel = getattr(self.view.state, 'chatgpt_panel', None)
        registration = getattr(controller, 'active_registration', None)
        model = panel.model.currentData() if panel is not None and hasattr(panel, 'model') else None
        if not registration or not model:
            self.view.status.setText(ui_text('idea.sign_in_required'))
            return None
        return (registration, model)

    def _consent(self):
        if not (self.view.consent_network.isChecked() and self.view.consent_plan.isChecked()):
            self.view.status.setText(ui_text('idea.consent_required'))
            return None
        return {'network': True, 'plan_usage': True}

    def _reset_consent(self):
        self.view.consent_network.setChecked(False)
        self.view.consent_plan.setChecked(False)

    def start(self):
        consent = self.view._consent()
        if consent is None:
            return None
        identity = self.view._identity()
        if identity is None:
            return None
        registration, model = identity
        request = {
            'instrument': self.view.market.currentData(),
            'timeframe': self.view.timeframe.currentData(),
            'direction': {'family_hint': self.view.family.currentData(), 'text': self.view.direction.text().strip()},
            'discovery': self.view.discovery_mode(),
            'consent': consent,
        }
        if request['discovery'] == 'user_urls':
            request['urls'] = [line.strip() for line in self.view.urls.toPlainText().splitlines() if line.strip()]
            if not 1 <= len(request['urls']) <= 8:
                self.view.status.setText(ui_text('idea.need_urls'))
                return None
        job = self.view.host.start_job('ui_idea_research', {'request': request, 'registration': registration, 'model': model})
        self.view._reset_consent()
        self.view._set_fallback(False)
        self.view.status.setText(ui_text('idea.status.running'))
        self.view.workspaces.setCurrentIndex(1)
        self.view.refresh_controls()
        return job

    def retry(self):
        if self.view.record is None:
            return None
        consent = self.view._consent()
        if consent is None:
            return None
        identity = self.view._identity()
        if identity is None:
            return None
        registration, model = identity
        job = self.view.host.start_job(
            'ui_idea_research', {'retry_task_id': self.view.record['task_id'], 'consent': consent, 'registration': registration, 'model': model}
        )
        self.view._reset_consent()
        self.view.refresh_controls()
        return job

    def cancel(self):
        if self.view.busy() and getattr(self.view.state, 'last_operation', None) == 'ui_idea_research':
            self.view.state.jobs.cancel()
            self.view.status.setText(ui_text('job.cancel_notice'))

    def clear_temp(self):
        if self.view.busy():
            self.view.status.setText(ui_text('ui.start_job.job_busy'))
            return
        removed = self.view.records().purge(0, max_age=0)
        self.view.reader.clear()
        self.view.status.setText(ui_text('idea.cleared').format(removed))

    def adopt(self):
        row = self.view.candidates.currentRow()
        candidate = self.view.record['candidates'][row]
        page = self.view.state.strategy_page
        config = self.view.host.payload(page.campaign_config, lambda: page.campaign_form.build_payload(self.view.state.backtest_form.build_payload()['config']))
        job = self.view.host.start_job('ui_idea_adopt', {'task_id': self.view.record['task_id'], 'candidate_id': candidate['candidate_id'], 'config': config})
        self.view.status.setText(ui_text('idea.adopting'))
        self.view.refresh_controls()
        return job

    def apply(self, event):
        kind = event.get('kind')
        if kind == 'task':
            self.view.record = {**event['task'], 'searches': [], 'urls': [], 'sources': [], 'candidates': []}
            if self.view.record.get('status') == 'running' and self.view.record.get('discovery') is not None:
                self.view.search_log.clear()
                self.view.sources.setRowCount(0)
                self.view.candidates.clear()
                self.view.candidate_detail.clear()
                self.view.reader.clear()
        if self.view.record is None or event.get('task_id') != self.view.record.get('task_id'):
            return
        if kind == 'search':
            self.view._upsert('searches', 'search_id', event['search'])
            self.view.render_searches()
        elif kind == 'urls':
            self.view.record['urls'] = event['urls']
            self.view.render_sources()
        elif kind == 'source':
            self.view._upsert('sources', 'source_id', event['source'])
            self.view.render_sources()
        elif kind == 'extracting':
            self.view.status.setText(ui_text('idea.progress.extracting'))
        elif kind == 'candidates':
            self.view.record['candidates'] = event['candidates']
            self.view.render_candidates()
        elif kind == 'status':
            self.view.record.update(status=event['status'], stop_reason=event.get('stop_reason'), error=event.get('error'))
            self.view.render_status()
        self.view.refresh_controls()

    def _upsert(self, field, key, value):
        rows = self.view.record.setdefault(field, [])
        for index, row in enumerate(rows):
            if row.get(key) == value.get(key):
                rows[index] = value
                return
        rows.append(value)

    def load_record(self, task_id):
        self.view.record = self.view.records().load(task_id)
        self.view.render_searches()
        self.view.render_sources()
        self.view.render_candidates()
        self.view.render_status()
        self.view.refresh_controls()

    def job_ended(self, kind):
        """A stopped worker cannot report again; unfinished sources end as cancelled."""
        if self.view.record is not None and self.view.record.get('status') == 'running':
            status = 'cancelled' if kind in ('cancelled', 'canceled') else 'failed'
            self.view.record['status'] = status
            for source in self.view.record.get('sources', []):
                if source.get('state') in ('pending', 'loading'):
                    source['state'] = 'cancelled'
            self.view.render_sources()
            self.view.render_status()
        self.view.refresh_controls()

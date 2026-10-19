"""Paper account presentation and consent-preserving paper actions."""

from desktop_theme import set_status, status_for_color
from desktop_strings import ui_text
from desktop_timeinput import DateInput
from pathlib import Path
from quantlab.desktop_feedback import stop_presentation
import json
from uuid import uuid4
from quantlab.core import ValidationError, canonical_json, content_hash
from quantlab.reporting import read_json, write_json, load_dataset, load_selection
from PySide6.QtWidgets import QWidget, QLabel, QPlainTextEdit, QSpinBox, QCheckBox, QFileDialog, QTabWidget
from desktop_presentation import display_number
from desktop_forms import PaperPolicyForm, PaperIntentForm, PaperQuoteForm, PaperSnapshotForm, SummaryCard
from .bindings import PageContext
from .result_widgets import KpiCards, ResultTable
from .replay_controls import ReplayControls


class PaperPage(PageContext, QWidget):
    def __init__(self, host):
        super().__init__()
        self.setup_context(host)
        layout = self.host.mount_page(self, ui_text('ui._paper_page.text_1'))
        note = QLabel(ui_text('ui._paper_page.text_2'))
        note.setWordWrap(True)
        layout.addWidget(note)
        limits = self.host.callbacks['paper_risk_limits']()
        self.paper_risk_summary = QLabel(
            ui_text('ui._paper_page.text_3').format(
                limits.max_position,
                limits.max_order_quantity,
                display_number(limits.max_daily_loss, "cash"),
                limits.max_quote_age_seconds,
                limits.max_consecutive_losses,
                limits.window_seconds,
                limits.max_orders_per_window,
            )
        )
        self.paper_risk_summary.setObjectName('paper_fixed_risk_summary')
        self.paper_risk_summary.setWordWrap(True)
        layout.addWidget(self.paper_risk_summary)
        advanced = self._advanced(layout)
        policy_layout = self._advanced(layout, ui_text('ui._paper_page.text_4'))
        self.policy_form = PaperPolicyForm()
        policy_layout.addWidget(self.policy_form)
        self.paper_policy = self._text(advanced, ui_text('ui._paper_page.text_5'), '{}', True)
        self._remember(self.paper_policy)
        self._button(layout, ui_text('ui._paper_page.text_6'), 'load_policy_file', lambda: self.load_form_file(self.policy_form, self.paper_policy))
        self._button(layout, ui_text('ui._paper_page.text_7'), 'demo_policy', self.demo_paper_policy)
        self._button(layout, ui_text('ui._paper_page.text_8'), 'paper_snapshot', lambda: self.paper_job('snapshot'))
        snapshot_layout = self._advanced(layout, ui_text('ui._paper_page.text_9'))
        self.snapshot_form = PaperSnapshotForm()
        snapshot_layout.addWidget(self.snapshot_form)
        self.snapshot = self._text(
            advanced,
            ui_text('ui._paper_page.text_10'),
            canonical_json({'account_id': 'paper-demo', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}}),
            True,
        )
        self.snapshot_form.from_payload(json.loads(self.snapshot.toPlainText()))
        self._remember(self.snapshot)
        self._button(layout, ui_text('ui._paper_page.text_11'), 'load_snapshot_file', lambda: self.load_form_file(self.snapshot_form, self.snapshot))
        self._button(
            layout,
            ui_text('ui._paper_page.text_12'),
            'paper_reconcile',
            lambda: self.paper_job('reconcile', snapshot=self._payload(self.snapshot, self.snapshot_form.build_payload)),
        )
        self.kill_button = self._button(layout, ui_text('ui._paper_page.text_13'), 'paper_kill', self.kill_paper, role='danger')
        self._button(advanced, ui_text('paper.manual_lock'), 'paper_manual_lock', lambda: self.paper_job('kill', manual_order_lock=True))
        self._button(
            advanced,
            ui_text('paper.manual_unlock'),
            'paper_manual_unlock',
            lambda: self.paper_job('reconcile', snapshot=self._payload(self.snapshot, self.snapshot_form.build_payload), manual_order_lock=False),
        )
        self.replay_bars = QSpinBox()
        self.replay_bars.setRange(1, 1000)
        self.replay_bars.setValue(100)
        layout.addWidget(self.replay_bars)
        self.paper_confirm = QCheckBox(ui_text('ui._paper_page.text_14'))
        layout.addWidget(self.paper_confirm)
        self.replay_controls = ReplayControls(self, layout, options_layout=advanced)
        self.page_state.replay_controls = self.replay_controls
        self._button(
            layout,
            ui_text('ui._paper_page.text_15'),
            'paper_replay',
            lambda: self.paper_job('replay', max_bars=self.replay_bars.value(), _paced=self.replay_controls.speed.currentData() is not None),
        )
        order_layout = self._advanced(layout, ui_text('ui._paper_page.text_16'))
        self.intent_form = PaperIntentForm()
        order_layout.addWidget(self.intent_form)
        self.quote_form = PaperQuoteForm()
        order_layout.addWidget(self.quote_form)
        self.intent = self._text(advanced, ui_text('ui._paper_page.text_17'), '{}', True)
        self.quote = self._text(advanced, ui_text('ui._paper_page.text_18'), '{}', True)
        self._remember(self.intent)
        self._remember(self.quote)
        layout.addWidget(QLabel(ui_text('timeinput.paper_clock')))
        self.paper_time = DateInput('2026-01-05T01:00:00Z', timestamp=True)
        self.paper_time.setAccessibleName(ui_text('timeinput.paper_clock'))
        layout.addWidget(self.paper_time)
        self._button(
            layout,
            ui_text('ui._paper_page.text_20'),
            'paper_submit',
            lambda: self.paper_job(
                'submit',
                intent=self._payload(self.intent, self.intent_form.build_payload),
                quote=self._payload(self.quote, self.quote_form.build_payload),
                now=self.paper_time.text(),
            ),
            role='primary',
        )
        self.cancel_order = self._text(layout, ui_text('ui._paper_page.text_21'))
        self._button(
            layout,
            ui_text('ui._paper_page.text_22'),
            'paper_cancel',
            lambda: self.paper_job('cancel', order_id=self.cancel_order.text(), now=self.paper_time.text()),
            role='danger',
        )
        self.paper_detail = QPlainTextEdit()
        self.paper_detail.setReadOnly(True)
        advanced.addWidget(self.paper_detail)
        self.paper_card = SummaryCard()
        advanced.addWidget(self.paper_card)
        self.kpis = KpiCards(('cash', 'positions', 'orders', 'fills', 'reconciliation_required', 'stop'))
        layout.insertWidget(2, self.kpis)
        tables = QTabWidget()
        layout.addWidget(tables)
        self.positions_table = ResultTable()
        self.positions_table.setObjectName('paper_positions_results')
        tables.addTab(self.positions_table, ui_text('results.positions'))
        self.orders_table = ResultTable()
        self.orders_table.setObjectName('paper_orders_results')
        tables.addTab(self.orders_table, ui_text('results.orders'))
        self.account_fills_table = ResultTable()
        self.account_fills_table.setObjectName('paper_fills_results')
        tables.addTab(self.account_fills_table, ui_text('results.fills'))

    def load_form_file(self, form, editor):
        name, _ = self.host.open_file(ui_text('ui.load_form_file.text_1'), '', 'JSON (*.json)')
        if not name:
            return
        path = Path(name)
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValidationError(ui_text('ui.load_form_file.text_2'))
        value = self.host.callbacks['read_json'](path)
        form.from_payload(value)
        editor.setPlainText(canonical_json(value))
        self._remember(editor)
        self.paper_confirm.setChecked(False)
        self.form_feedback(form, ui_text('ui.load_form_file.text_3'))

    def demo_paper_policy(self):
        data = self.host.callbacks['load_dataset'](self.root / 'dataset.json')
        if data.manifest['source_type'] != 'synthetic':
            raise ValidationError(ui_text('ui.demo_paper_policy.text_1'))
        sessions = []
        for day in sorted({b.trade_date for b in data.bars}):
            bars = [b for b in data.bars if b.trade_date == day]
            sessions.append(
                {
                    'open': bars[0].timestamp.isoformat(),
                    'end': bars[-1].end.isoformat(),
                    'trade_date': day,
                    'session': bars[0].session,
                    'contract_id': bars[0].contract_id,
                    'source': 'explicit synthetic demonstration',
                }
            )
        policy = {
            'contract_id': data.bars[0].contract_id,
            'risk_sessions': sessions,
            'margin_schedule': [{'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'synthetic-assumption-v1'}],
        }
        self.paper_policy.setPlainText(canonical_json(policy))
        self.policy_form.from_payload(policy)
        self._remember(self.paper_policy)
        self.form_feedback(self.policy_form.sessions, ui_text('ui.demo_paper_policy.text_2').format(len(sessions)))

    def paper_job(self, op, **payload):
        if op in ('submit', 'replay'):
            if not self.paper_confirm.isChecked():
                raise ValidationError(ui_text('ui.paper_job.text_1'))
            payload.update(snapshot=self._payload(self.snapshot, self.snapshot_form.build_payload), reconcile_confirmed=True)
        payload['policy'] = self._payload(self.paper_policy, self.policy_form.build_payload)
        if op == 'replay' and payload.pop('_paced', False):
            self.replay_controls.begin(payload)
        else:
            self.start_job('ui_paper_' + op, payload)
        self.paper_confirm.setChecked(False)

    def kill_paper(self):
        self.replay_controls.cancel()
        self.freeze_paper(ui_text('ui.kill_paper.text_1'))
        self.status.setText(ui_text('ui.kill_paper.text_2'))

    def _amend_order(self, order_id, price):
        if self.jobs.active or not self.paper_confirm.isChecked():
            raise ValidationError(ui_text('ui.paper_job.text_1'))
        self.paper_job(
            'cancel',
            action='amend',
            mode='paper',
            order_id=order_id,
            price=str(price),
            amend_key=uuid4().hex,
            quote=self._payload(self.quote, self.quote_form.build_payload),
            now=self.paper_time.text(),
            snapshot=self.market.chart.paper_orders.snapshot,
            reconcile_confirmed=True,
        )

    def _show_account(self, account, strategy=None):
        chart = self.market.chart
        mode = 'paper' if account.get('verification') == 'synthetic_paper_only' and chart.trace is None and self.last_operation != 'ui_paper_replay' else None
        chart.set_paper_snapshot(account, mode=mode, request=self._amend_order)
        values = {k: account.get(k) for k in ('account_id', 'cash', 'reconciliation_required')}
        if not account.get('account_id'):
            values['cash'] = None
        values.update(
            {
                ui_text('ui._show_account.text_1'): len(account.get('positions', {})),
                ui_text('ui._show_account.text_2'): len(account.get('orders', {})),
                ui_text('ui._show_account.text_3'): len(account.get('fills', {})),
                ui_text('ui._show_account.text_4'): account.get('positions', {}),
            }
        )
        reason = None
        marker = self.root / 'paper_stop_display.json'
        try:
            saved = self.host.callbacks['read_json'](marker) if marker.exists() else {}
            if saved.get('account_hash') == content_hash(account):
                reason = saved.get('reason')
        except (OSError, ValueError):
            pass
        stop_text, color = stop_presentation(account, reason, manual_lock_text=ui_text('paper.manual_locked'))
        values[ui_text('ui._show_account.text_5')] = stop_text
        self.paper_card.set_values(values)
        set_status(self.paper_card.label, status_for_color(color))
        positions = [{'contract_id': key, 'quantity': value} for key, value in account.get('positions', {}).items()]
        orders = []
        for key, value in account.get('orders', {}).items():
            row = {**value.get('intent', {}), **value, 'order_id': key}
            if 'quantity' in row and 'contract_id' in row:
                orders.append(row)
        fills = []
        for key, value in account.get('fills', {}).items():
            intent = account.get('orders', {}).get(value.get('order_id'), {}).get('intent', {})
            fills.append({**intent, **value, 'fill_id': key})
        self.market.set_account_tables(positions=positions, orders=orders, fills=fills)
        self.kpis.set_values(
            {
                'cash': values['cash'],
                'positions': len(positions) if 'positions' in account else None,
                'orders': len(account['orders']) if 'orders' in account else None,
                'fills': len(fills) if 'fills' in account else None,
                'reconciliation_required': account.get('reconciliation_required'),
                'stop': stop_text,
            }
        )
        self.positions_table.set_rows([{'contract_id': row['contract_id'], 'position': row['quantity']} for row in positions], ('contract_id', 'position'))
        self.orders_table.set_rows(orders, ('order_id', 'contract_id', 'side', 'quantity', 'status'))
        self.account_fills_table.set_rows(fills, ('timestamp', 'contract_id', 'side', 'quantity', 'price', 'commission', 'tax'))
        if strategy is None:
            selection = self.root / 'selection.json'
            strategy = (
                (ui_text('ui._show_account.text_6').format(load_selection(selection)['strategy_hash'][:16]))
                if selection.exists()
                else ui_text('ui._show_account.text_7')
            )
        self.market.set_trading_status(
            strategy=strategy,
            paper=(ui_text('ui._show_account.text_8').format(str(account['account_id']))) if account.get('account_id') else ui_text('ui._show_account.text_9'),
            risk=stop_text,
        )

    def _remember_stop(self, account, reason):
        self.host.callbacks['write_json'](self.root / 'paper_stop_display.json', {'account_hash': content_hash(account), 'reason': reason})

    def freeze_paper(self, reason):
        self.replay_controls.cancel()
        self._quiesce_and_recover()
        self.chatgpt_panel.consent.setChecked(False)
        self._pending_usage_refresh = False
        if self._chatgpt_job_request:
            self.chatgpt_controller.worker_joined(self._chatgpt_job_request.request_id, joined=True, terminal_received=False)
            self._chatgpt_job_request = None
        self.chatgpt_controller.account_status_known = False
        self.chatgpt_controller.invalidate_campaign_usage()
        self.paper_confirm.setChecked(False)
        if self.guard is not None:
            self.guard.reconciliation_required = True
        self.host.callbacks['write_json'](self.root / 'desktop_safety.json', {'reconciliation_required': True, 'reason': str(reason)})
        if (self.root / 'paper_policy.json').exists():
            broker = self.host.callbacks['_paper'](self.root)
            broker.set_kill_switch(True)
            self._remember_stop(broker.snapshot(), 'user' if ui_text('ui.freeze_paper.text_1') in str(reason) else 'freeze')
            self._show_account(broker.snapshot())
        self.status.setText(ui_text('ui.freeze_paper.text_2').format(str(reason)))

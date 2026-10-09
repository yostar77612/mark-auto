"""Native Traditional Chinese Qt workspace. No web server or live execution imports.

The GUI only schedules work. execute_ui_operation runs in the runtime's isolated
worker process; its inputs are data, never executable strategy source.
"""
from pathlib import Path
import json
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass
from urllib.parse import urlsplit
import ipaddress

from quantlab.core import (Dataset, StrategySpec, Instrument, ValidationError, canonical_json,
                   content_hash, to_dict)
from quantlab.reporting import (read_json, write_json, load_dataset, save_dataset, synthetic_dataset,
                        demo_config, export_report, load_result, comparison_rows,
                        save_selection, load_selection)

UI_OPERATIONS = frozenset('ui_' + op for op in (
    'demo', 'import', 'refresh', 'backtest', 'campaign', 'compare', 'select', 'disable',
    'paper_snapshot', 'paper_reconcile', 'paper_kill', 'paper_replay', 'paper_submit', 'paper_cancel',
    'backup_create', 'backup_restore'))


def validate_endpoint(endpoint):
    try:
        url = urlsplit(endpoint)
        loopback = url.hostname == 'localhost'
        if url.hostname and not loopback:
            try: loopback = ipaddress.ip_address(url.hostname).is_loopback
            except ValueError: pass
        if not url.hostname or url.username or url.password or '?' in endpoint or '#' in endpoint or any(c.isspace() for c in endpoint):
            raise ValueError()
        if url.scheme != 'https' and not (url.scheme == 'http' and loopback): raise ValueError()
        if url.port == 0: raise ValueError()
        return loopback
    except ValueError:
        raise ValidationError('模型端點不得包含帳密、查詢參數或片段；遠端必須 HTTPS，本機可使用 loopback HTTP') from None


@dataclass(frozen=True)
class DesktopCredentialTransport:
    """Pickle-safe root/name only; credentials resolve in isolated provider child."""
    root: str
    use_credential: bool = True

    def __call__(self, endpoint, request, timeout_seconds):
        from quantlab.provider import HTTPTransport
        from quantlab.desktop_runtime import DesktopCredentialReference
        resolver = DesktopCredentialReference(root=self.root, name='model_api_key') if self.use_credential else None
        return HTTPTransport(allow_network=True, credential_resolver=resolver)(endpoint, request, timeout_seconds)


def campaign_generator(paths, options):
    from quantlab.research import FixtureGenerator, CompatibleProvider
    if options.get('mode', 'fixture') == 'fixture': return FixtureGenerator()
    if options.get('mode') != 'compatible' or options.get('network_opt_in') is not True:
        raise ValidationError('真實模型必須明確同意本次網路與可能費用')
    local = validate_endpoint(options['endpoint'])
    if not local and (Decimal(options['cost_per_token']) <= 0 or Decimal(options['max_spend']) <= 0):
        raise ValidationError('遠端模型必須填寫正數單位費率及最高費用；不得假設免費')
    if not local and options.get('use_credential') is not True:
        raise ValidationError('遠端模型必須使用 Windows 安全儲存金鑰')
    identity = content_hash({k:v for k,v in options.items() if k != 'network_opt_in'})
    return CompatibleProvider(model=options['model'], endpoint=options['endpoint'],
        transport=DesktopCredentialTransport(str(paths.root), options.get('use_credential', True)),
        budget_path=Path(paths.state)/'provider_budgets'/(identity+'.sqlite3'), network_opt_in=True,
        max_calls=options['max_calls'], max_tokens=options['max_tokens'], max_spend=options['max_spend'],
        tokens_per_call=options['tokens_per_call'], cost_per_token=options['cost_per_token'], timeout_seconds=options['timeout_seconds'])


def _root(paths):
    root = Path(paths.state)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dataset(root, payload):
    data = load_dataset(Path(payload.get('dataset') or root / 'dataset.json'))
    start, end = payload.get('start_date'), payload.get('end_date')
    if start or end:
        if start and end and start > end:
            raise ValidationError('開始日期不得晚於結束日期')
        bars = tuple(b for b in data.bars if (not start or b.trade_date >= start) and (not end or b.trade_date <= end))
        if not bars:
            raise ValidationError('選定日期沒有資料')
        manifest = {**data.manifest, 'parent_data_hash': data.manifest['data_hash'],
                    'data_hash': content_hash(bars), 'date_filter': {'start': start, 'end': end}}
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
        data = Dataset(bars, manifest, dict(data.quality))
    return data


def _paper(root):
    from quantlab.paper import PaperBroker, RiskLimits
    policy = read_json(root / 'paper_policy.json')
    return PaperBroker(root / 'paper.sqlite3', instrument=Instrument(policy['contract_id']),
                       costs=demo_config().costs, limits=RiskLimits(1, 1, Decimal('1000'), 30),
                       risk_sessions=tuple(policy['risk_sessions']), margin_schedule=tuple(policy['margin_schedule']))


def execute_ui_operation(operation, payload, paths):
    """Allowlisted process-worker adapter; no Qt objects are created here."""
    if operation not in UI_OPERATIONS:
        raise ValidationError('未知桌面作業')
    root = _root(paths)
    if operation in ('ui_backup_create', 'ui_backup_restore'):
        from quantlab.desktop_runtime import BackupManager
        manager = BackupManager(paths)
        if operation == 'ui_backup_restore':
            manager.restore(Path(payload['path']))
            return {'restored': True, 'reconciliation_required': True}
        return {'backup': str(manager.create(Path(payload['path'])))}
    if operation == 'ui_demo':
        data = synthetic_dataset(payload.get('bars', 960))
        save_dataset(data, root / 'dataset.json')
        return {'dataset': str(root / 'dataset.json'), 'source_type': 'synthetic', 'bars': len(data.bars)}
    if operation == 'ui_import':
        from quantlab.data import SessionCalendar, import_taifex
        cal = read_json(Path(payload['calendar']))
        data = import_taifex(Path(payload['path']), kind=payload['kind'],
                            calendar=SessionCalendar(cal['sessions'], version=cal['version']),
                            contract_id=payload.get('contract') or None, encoding=payload.get('encoding'))
        save_dataset(data, root / 'dataset.json')
        return {'dataset': str(root / 'dataset.json'), 'manifest': to_dict(data.manifest), 'quality': to_dict(data.quality)}
    if operation == 'ui_refresh':
        if payload.get('network_opt_in') is not True:
            raise ValidationError('需明確同意連線至臺灣期交所下載公開資料')
        from quantlab.downloads import refresh
        return refresh(Path(paths.cache), days=payload.get('days', 1), kind=payload.get('format', 'csv'))
    if operation == 'ui_backtest':
        from quantlab.strategies import builtin_strategies, validate_strategy
        from quantlab.backtest import run_backtest
        from quantlab.__main__ import config_from_json
        data = _dataset(root, payload)
        config = config_from_json(payload['config'])
        specs = list(builtin_strategies())
        if not payload.get('batch'):
            spec = next((s for s in specs if s.family == payload['family']), None)
            if spec is None:
                raise ValidationError('未知策略家族')
            spec = StrategySpec(spec.strategy_id, spec.family, payload.get('parameters', dict(spec.parameters)), dict(spec.rules))
            validate_strategy(spec)
            specs = [spec]
        reports = []
        for spec in specs:
            result = run_backtest(data, spec, config)
            # Publish a complete immutable report folder, never a half-written result.
            import tempfile
            reports_root = root / 'reports'; reports_root.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.partial-', dir=reports_root) as staging:
                files = export_report(result, Path(staging))
                folder = Path(files['result']).parent
                write_json(folder / 'strategy.json', spec)
                destination = reports_root / files['result_hash']
                if destination.exists():
                    if content_hash(load_result(destination / 'result.json')) != files['result_hash'] or read_json(destination / 'strategy.json') != to_dict(spec):
                        raise ValidationError('已存在的報告不完整或不符合雜湊；原檔保留')
                else: folder.rename(destination)
                files = {key: str(destination / Path(value).name) if key != 'result_hash' else value for key, value in files.items()}
            reports.append(files)
        write_json(root / 'active_result.json', {'result_hash': reports[-1]['result_hash']})
        return {'reports': reports, 'source_type': data.manifest['source_type'], 'scope': 'research_only'}
    if operation == 'ui_campaign':
        from quantlab.research import FixtureGenerator, run_campaign, demo_campaign_config
        from quantlab.__main__ import config_from_json
        data = _dataset(root, payload)
        config = payload.get('config') or demo_campaign_config(data, demo_config())
        if isinstance(config.get('backtest_config'), dict):
            config['backtest_config'] = config_from_json(config['backtest_config'])
        options = payload.get('provider', {'mode':'fixture'})
        generator = campaign_generator(paths, options)
        name = content_hash({'dataset': data.manifest['data_hash'], 'config': config, 'provider': {k:v for k,v in options.items() if k != 'network_opt_in'}})
        return run_campaign(data, config=config, generator=generator, output_dir=root / 'campaigns' / name)
    if operation == 'ui_compare':
        if not payload.get('results'): raise ValidationError('請至少選擇一個結果')
        return {'rows': comparison_rows([load_result(p) for p in payload['results']])}
    if operation == 'ui_select':
        folder = Path(payload['result']).parent
        result = load_result(folder / 'result.json')
        return save_selection(read_json(folder / 'strategy.json'), result, root / 'selection.json')
    if operation == 'ui_disable':
        selection = root / 'selection.json'
        if selection.exists():
            archive = root / 'disabled_selections'
            archive.mkdir(exist_ok=True)
            value = read_json(selection)
            write_json(archive / (content_hash(value) + '.json'), value)
            selection.unlink()
        if (root / 'paper_policy.json').exists():
            _paper(root).set_kill_switch(True)
        return {'selection': 'disabled', 'scope': 'research_and_paper_only'}
    if operation.startswith('ui_paper_'):
        # Explicit policy is required; never infer an official calendar from prices.
        if 'policy' in payload:
            policy = payload['policy']
            existing = root / 'paper_policy.json'
            if existing.exists() and read_json(existing) != policy:
                raise ValidationError('紙上帳戶政策已鎖定；請使用新工作區')
            if not existing.exists():
                from quantlab.paper import PaperBroker, RiskLimits
                if not isinstance(policy, dict) or set(policy) != {'contract_id', 'risk_sessions', 'margin_schedule'}:
                    raise ValidationError('政策必須包含 contract_id、risk_sessions、margin_schedule')
                # Validate in a disposable journal first: invalid policy cannot poison startup.
                import tempfile
                with tempfile.TemporaryDirectory(prefix='policy-', dir=root) as staging:
                    PaperBroker(Path(staging) / 'validation.sqlite3', instrument=Instrument(policy['contract_id']),
                                costs=demo_config().costs, limits=RiskLimits(1, 1, Decimal('1000'), 30),
                                risk_sessions=tuple(policy['risk_sessions']), margin_schedule=tuple(policy['margin_schedule']))
                write_json(existing, policy)
        broker = _paper(root)
        if operation == 'ui_paper_reconcile':
            broker.reconcile(payload['snapshot'])
        elif operation == 'ui_paper_kill':
            broker.set_kill_switch(True)
        elif operation == 'ui_paper_submit':
            if payload.get('reconcile_confirmed') is not True:
                raise ValidationError('每次紙上執行前須明確確認參考快照')
            broker.reconcile(payload['snapshot'])
            selection = load_selection(root / 'selection.json')
            if payload['intent'].get('strategy_hash') != selection['strategy_hash']:
                raise ValidationError('委託與啟用策略雜湊不符')
            broker.set_kill_switch(False)
            broker.submit(payload['intent'], quote=payload['quote'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
        elif operation == 'ui_paper_cancel':
            broker.cancel(payload['order_id'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
        elif operation == 'ui_paper_replay':
            if payload.get('reconcile_confirmed') is not True:
                raise ValidationError('每次紙上重播前須明確確認參考快照')
            broker.reconcile(payload['snapshot'])
            from quantlab.paper_replay import PaperReplay
            data = _dataset(root, payload)
            selection = load_selection(root / 'selection.json')
            binding = content_hash([data.manifest['data_hash'], selection['strategy_hash']])
            replay = PaperReplay(root / 'replays' / (binding + '.sqlite3'), dataset=data,
                                 strategy=StrategySpec(**selection['strategy']), broker=broker,
                                 margin_per_contract=Decimal('100000'), margin_version='synthetic-assumption-v1')
            replay.start()
            try:
                replay.step(max_bars=payload.get('max_bars', 100))
            finally:
                replay.stop()
            return {'replay': replay.snapshot(), 'account': broker.snapshot()}
        state = broker.snapshot()
        journal = broker.journal_events()
        write_json(root / 'paper_snapshot.json', state)
        write_json(root / 'paper_journal_export.json', journal)
        return {'account': state, 'journal_tail': journal[-20:], 'journal_file': str(root / 'paper_journal_export.json')}
    raise ValidationError('未實作作業')


from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QStackedWidget, QPushButton, QLineEdit, QPlainTextEdit, QComboBox,
    QSpinBox, QCheckBox, QProgressBar, QFileDialog, QFormLayout, QScrollArea,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QMessageBox)


class EquityPlot(QWidget):
    """Small native paint widget; no browser or extra plotting dependency."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = []
        self.setMinimumHeight(180)
        self.setAccessibleName('權益曲線，依時間排序')

    def set_values(self, rows):
        self.values = [float(row['equity']) for row in rows]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#f5f7fa'))
        painter.setPen(QColor('#334155'))
        if not self.values:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '尚無權益資料')
            return
        lo, hi = min(self.values), max(self.values)
        painter.drawText(8, 18, f'權益 TWD  最低 {lo:,.0f}  最高 {hi:,.0f} | 時間 →')
        points = QPolygonF([QPointF(16 + i * (self.width()-32) / max(1, len(self.values)-1),
                       self.height()-20-(v-lo) * (self.height()-55) / max(1, hi-lo)) for i, v in enumerate(self.values)])
        painter.setPen(QPen(QColor('#2563eb'), 2))
        painter.drawPolyline(points)


class MainWindow(QMainWindow):
    def __init__(self, paths, jobs, settings=None, backups=None, guard=None):
        super().__init__()
        self.paths, self.jobs, self.settings, self.backups, self.guard = paths, jobs, settings, backups, guard
        self.root = _root(paths)
        self.actions = []
        self.last_operation = None
        self.setWindowTitle('TMF 量化研究桌面｜研究與紙上模擬')
        self.resize(1180, 800)
        self.setStyleSheet('''
            QMainWindow, QScrollArea, QStackedWidget { background: #f3f6fb; }
            QWidget { font-family: "Microsoft JhengHei UI", "Noto Sans CJK TC", sans-serif; font-size: 14px; color: #172b4d; }
            QLabel { padding: 3px 0; }
            QListWidget { background: #12243b; color: #e3edf9; border: none; border-radius: 9px; padding: 9px; }
            QListWidget::item { padding: 12px 8px; border-radius: 5px; }
            QListWidget::item:selected { background: #2865c4; color: white; }
            QPushButton { background: #2563ba; color: white; border: none; border-radius: 6px; padding: 9px 14px; min-height: 20px; }
            QPushButton:hover { background: #1b4f9b; }
            QPushButton:disabled { background: #cbd5e1; color: #64748b; }
            QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background: white; border: 1px solid #cad5e3; border-radius: 5px; padding: 7px; selection-background-color: #2563ba; }
            QCheckBox { padding: 7px 0; }
            QProgressBar { border: 1px solid #d7e0ec; border-radius: 4px; background: white; text-align: center; }
            QProgressBar::chunk { background: #2563ba; }
        ''')
        body = QWidget(); outer = QVBoxLayout(body)
        banner = QLabel('僅研究／紙上模擬 · 本版實單交易固定停用 · Fixture 並非真實 AI · 合成資料並非市場績效')
        banner.setWordWrap(True); banner.setStyleSheet('background:#fff3cd;color:#664d03;padding:10px')
        outer.addWidget(banner)
        horizontal = QHBoxLayout(); outer.addLayout(horizontal, 1)
        self.navigation = QListWidget(); self.navigation.setObjectName('navigation'); self.navigation.setMaximumWidth(180)
        self.stack = QStackedWidget(); horizontal.addWidget(self.navigation); horizontal.addWidget(self.stack, 1)
        self.status = QLabel('就緒'); self.status.setObjectName('status'); self.status.setWordWrap(True)
        outer.addWidget(self.status)
        progress = QHBoxLayout(); self.progress = QProgressBar(); self.progress.setRange(0, 100)
        self.cancel_button = QPushButton('取消背景作業'); self.cancel_button.setObjectName('cancel_job')
        self.cancel_button.clicked.connect(self.cancel_job); self.cancel_button.setEnabled(False)
        progress.addWidget(self.progress); progress.addWidget(self.cancel_button); outer.addLayout(progress)
        self.setCentralWidget(body)
        self._dashboard(); self._data_page(); self._strategy_page(); self._backtest_page(); self._compare_page(); self._paper_page(); self._settings_page()
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex); self.navigation.setCurrentRow(0)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll_jobs); self.timer.start(150)
        self._safe(self.refresh_views)
        self._safe(self.load_settings)

    def _page(self, label):
        self.navigation.addItem(label)
        page = QWidget(); layout = QVBoxLayout(page)
        title = QLabel(label); title.setStyleSheet('font-size:22px;font-weight:600'); layout.addWidget(title)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page); self.stack.addWidget(scroll)
        return layout

    def _button(self, layout, text, name, callback):
        button = QPushButton(text); button.setObjectName(name); button.clicked.connect(lambda checked=False: self._safe(callback))
        layout.addWidget(button); self.actions.append(button)
        return button

    def _text(self, layout, label, value='', multiline=False):
        layout.addWidget(QLabel(label))
        field = QPlainTextEdit(value) if multiline else QLineEdit(value)
        if multiline: field.setMaximumHeight(150)
        layout.addWidget(field)
        return field

    def _dashboard(self):
        layout = self._page('總覽')
        self.overview = QLabel(); self.overview.setWordWrap(True); layout.addWidget(self.overview)
        self._button(layout, '重新讀取本機狀態', 'refresh_views', self.refresh_views)
        cards = QHBoxLayout()
        for title, value in [('資料來源', '尚未載入'), ('模型驗證', 'Fixture / 未驗證'), ('執行範圍', '研究與紙上'), ('風險邊界', '實單已停用')]:
            card = QLabel(title + '\n\n' + value); card.setMinimumHeight(100); card.setWordWrap(True)
            card.setStyleSheet('background:white;border:1px solid #dce4ef;border-radius:9px;padding:16px;font-weight:600')
            cards.addWidget(card)
            if title == '資料來源': self.data_card = card
        layout.addLayout(cards)
        self.summary = QPlainTextEdit(); self.summary.setReadOnly(True); self.summary.setMaximumHeight(280)
        self.summary.setPlaceholderText('從「資料匯入與更新」開始。完成的背景作業結果會顯示在這裡。\n所有績效需核對來源、費用假設與樣本外表現。')
        layout.addWidget(self.summary)
        layout.addStretch()

    def _data_page(self):
        layout = self._page('資料匯入與更新')
        self.import_path = self._text(layout, '本機 CSV / RPT / JSON 檔案')
        self._button(layout, '選擇資料檔案', 'browse_data', lambda: self._browse(self.import_path))
        self.calendar_path = self._text(layout, '版本化交易日曆 JSON（必填）')
        self._button(layout, '選擇交易日曆', 'browse_calendar', lambda: self._browse(self.calendar_path))
        self.import_kind = QComboBox(); self.import_kind.addItems(['ticks', 'ticks_rpt', 'daily_json', 'synthetic_daily_json', 'synthetic_bars', 'synthetic_ticks', 'proxy_bars', 'proxy_ticks']); layout.addWidget(self.import_kind)
        self.contract = self._text(layout, '合約（可留空）', 'TAIFEX:TMF:202601')
        self._button(layout, '匯入並驗證資料', 'import_data', self.import_data)
        self.bars = QSpinBox(); self.bars.setRange(120, 10000); self.bars.setValue(960); layout.addWidget(self.bars)
        self._button(layout, '建立合成示範資料', 'create_demo', lambda: self.start_job('ui_demo', {'bars': self.bars.value()}))
        self.network_data = QCheckBox('同意本次連線至 TAIFEX 下載免費公開資料（不會自動匯入）'); layout.addWidget(self.network_data)
        self.days = QSpinBox(); self.days.setRange(1, 30); layout.addWidget(self.days)
        self._button(layout, '下載最近交易日資料', 'refresh_data', self.download_data)
        self.data_detail = QPlainTextEdit(); self.data_detail.setReadOnly(True); layout.addWidget(self.data_detail)

    def _strategy_page(self):
        from quantlab.strategies import builtin_strategies
        layout = self._page('策略與版本')
        layout.addWidget(QLabel('五種有限策略家族與受驗證參數；禁止任意 Python 策略程式。'))
        self.family = QComboBox(); self.family.addItems([s.family for s in builtin_strategies()]); layout.addWidget(self.family)
        self.parameters = self._text(layout, '策略參數 JSON', '{}', True)
        self.strategy_detail = QPlainTextEdit(); self.strategy_detail.setReadOnly(True); layout.addWidget(self.strategy_detail)
        self.family.currentIndexChanged.connect(self._family_changed); self._family_changed()
        layout.addWidget(QLabel('離線 Fixture 生成器：固定候選與版本紀錄；不是已驗證的真實模型。'))
        self.campaign_config = self._text(layout, '研究設定 JSON（空白使用明示示範切分）', '', True)
        self.provider_mode = QComboBox(); self.provider_mode.addItem('離線 Fixture（預設，非真實 AI）', 'fixture'); self.provider_mode.addItem('相容模型 HTTP（需設定、逐次同意；驗證未完成）', 'compatible'); layout.addWidget(self.provider_mode)
        self._button(layout, '生成／重開研究與 OOS', 'run_campaign', self.run_campaign)
        self.history = QPlainTextEdit(); self.history.setReadOnly(True); layout.addWidget(self.history)

    def _backtest_page(self):
        layout = self._page('回測與結果')
        layout.addWidget(QLabel('使用「策略與版本」目前選定家族及參數。預設費率與保證金為合成假設。'))
        self.start_date = self._text(layout, '起始交易日 YYYY-MM-DD（空白：全部）')
        self.end_date = self._text(layout, '結束交易日 YYYY-MM-DD（含當日）')
        self.config = self._text(layout, '費用／資金／保證金設定 JSON', canonical_json(demo_config()), True)
        self.batch = QCheckBox('批次執行五個家族的預設參數'); layout.addWidget(self.batch)
        self.run_button = self._button(layout, '執行回測', 'run_backtest', self.run_backtest)
        self.result_choice = QComboBox(); self.result_choice.currentIndexChanged.connect(self.show_result); layout.addWidget(self.result_choice)
        self.plot = EquityPlot(); layout.addWidget(self.plot)
        self.result_detail = QPlainTextEdit(); self.result_detail.setReadOnly(True); layout.addWidget(self.result_detail)

    def _compare_page(self):
        layout = self._page('比較與策略選擇')
        layout.addWidget(QLabel('勾選多個已保存結果進行比較。OOS／保留集詳細結果見策略研究紀錄。'))
        self.comparison_list = QListWidget(); self.comparison_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection); layout.addWidget(self.comparison_list)
        self._button(layout, '比較選取結果', 'compare_results', lambda: self.start_job('ui_compare', {'results': [i.data(Qt.ItemDataRole.UserRole) for i in self.comparison_list.selectedItems()]}))
        self.comparison = QPlainTextEdit(); self.comparison.setReadOnly(True); layout.addWidget(self.comparison)
        self._button(layout, '啟用目前回測策略（僅研究／紙上）', 'select_strategy', self.select_strategy)
        self._button(layout, '停用策略並停止紙上新委託', 'disable_strategy', lambda: self.start_job('ui_disable', {}))
        self.selection_status = QLabel(); self.selection_status.setWordWrap(True); layout.addWidget(self.selection_status)

    def _paper_page(self):
        layout = self._page('紙上交易與復原')
        note = QLabel('沒有即時行情或真實券商。重新啟動後必須明確對帳。停止只禁止新委託，不會平倉。\n歷史重播採次棒成交；不支援盤中停損停利。預設示範費率與風控不代表真實條件。'); note.setWordWrap(True); layout.addWidget(note)
        self.paper_policy = self._text(layout, '鎖定政策 JSON（合約、交易時段、保證金版本；不可猜測）', '{}', True)
        self._button(layout, '填入明示合成示範政策', 'demo_policy', self.demo_paper_policy)
        self._button(layout, '讀取／建立紙上帳戶', 'paper_snapshot', lambda: self.paper_job('snapshot'))
        self.snapshot = self._text(layout, '外部紙上參考快照 JSON（初始空帳戶可使用下列示範）', canonical_json({'account_id':'paper-demo','cash':'1000000','positions':{},'orders':{},'fills':{}}), True)
        self._button(layout, '明確對帳紙上帳戶', 'paper_reconcile', lambda: self.paper_job('reconcile', snapshot=json.loads(self.snapshot.toPlainText())))
        self.kill_button = self._button(layout, '緊急停止：禁止紙上新委託', 'paper_kill', self.kill_paper)
        self.replay_bars = QSpinBox(); self.replay_bars.setRange(1, 1000); self.replay_bars.setValue(100); layout.addWidget(self.replay_bars)
        self.paper_confirm = QCheckBox('我已核對上方參考快照，並同意本次重播／委託前對帳'); layout.addWidget(self.paper_confirm)
        self._button(layout, '重播選定策略一批歷史資料', 'paper_replay', lambda: self.paper_job('replay', max_bars=self.replay_bars.value()))
        self.intent = self._text(layout, '紙上委託意圖 JSON（需已啟用策略雜湊）', '{}', True)
        self.quote = self._text(layout, '明示報價與風控條件 JSON', '{}', True)
        self.paper_time = self._text(layout, '紙上事件 UTC 時間', '2026-01-05T01:00:00Z')
        self._button(layout, '送出紙上委託', 'paper_submit', lambda: self.paper_job('submit', intent=json.loads(self.intent.toPlainText()), quote=json.loads(self.quote.toPlainText()), now=self.paper_time.text()))
        self.cancel_order = self._text(layout, '紙上委託 ID')
        self._button(layout, '取消紙上委託', 'paper_cancel', lambda: self.paper_job('cancel', order_id=self.cancel_order.text(), now=self.paper_time.text()))
        self.paper_detail = QPlainTextEdit(); self.paper_detail.setReadOnly(True); layout.addWidget(self.paper_detail)

    def _settings_page(self):
        layout = self._page('設定與備份')
        layout.addWidget(QLabel('本機工作區：' + str(self.paths.root)))
        layout.addWidget(QLabel('資料與帳戶狀態：' + str(self.root)))
        layout.addWidget(QLabel('日誌：' + str(self.paths.logs)))
        self.ai_endpoint = self._text(layout, '模型完整 chat/completions 端點（遠端 HTTPS / 本機 loopback HTTP）')
        self.ai_model = self._text(layout, '模型名稱')
        self.api_key = self._text(layout, 'API 金鑰（只存 Windows DPAPI；不寫入設定、日誌或備份）')
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password); self.api_key.setObjectName('api_key')
        self._button(layout, '儲存金鑰至 Windows 安全儲存庫', 'save_api_key', self.save_api_key)
        self.use_key = QCheckBox('使用 Windows 安全儲存金鑰（遠端必須；本機無驗證服務可取消）'); self.use_key.setChecked(True); layout.addWidget(self.use_key)
        self.max_calls = QSpinBox(); self.max_calls.setRange(1,100); self.max_calls.setValue(1); layout.addWidget(QLabel('最多呼叫次數（失敗仍保留預算）')); layout.addWidget(self.max_calls)
        self.max_tokens = QSpinBox(); self.max_tokens.setRange(1,1000000); self.max_tokens.setValue(20000); layout.addWidget(QLabel('總 token 保守預算（含輸入位元組上限）')); layout.addWidget(self.max_tokens)
        self.tokens_per_call = QSpinBox(); self.tokens_per_call.setRange(1,32768); self.tokens_per_call.setValue(2048); layout.addWidget(QLabel('每次最大輸出 tokens')); layout.addWidget(self.tokens_per_call)
        self.timeout_seconds = QSpinBox(); self.timeout_seconds.setRange(1,120); self.timeout_seconds.setValue(30); layout.addWidget(QLabel('單次逾時秒數')); layout.addWidget(self.timeout_seconds)
        self.max_spend = self._text(layout, '最高費用（USD；供應商實際帳單仍需自行核對）', '0')
        self.cost_per_token = self._text(layout, '保守每 token 費率（USD；遠端不可為零）', '0')
        self.ai_opt_in = QCheckBox('我同意下一次模型研究：傳送策略內容與訓練／驗證統計至上述端點，可能產生費用（不傳 OOS／保留集）'); layout.addWidget(self.ai_opt_in)
        self.ai_status = QLabel('外部真實模型：NOT_VERIFIED。預設 Fixture；只有明確選取相容模型並勾選逐次同意才可連線。預算不是供應商帳單保證。'); self.ai_status.setWordWrap(True); layout.addWidget(self.ai_status)
        self._button(layout, '儲存非敏感偏好', 'save_settings', self.save_settings)
        self.backup_path = self._text(layout, '備份封存檔案路徑')
        self._button(layout, '建立本機備份', 'create_backup', lambda: self.backup(False))
        self.restore_confirm = QCheckBox('我確認還原會替換目前本機狀態，並會要求重新對帳'); layout.addWidget(self.restore_confirm)
        self._button(layout, '驗證並還原備份', 'restore_backup', lambda: self.backup(True))
        layout.addWidget(QLabel('更新：沒有自動下載或更新。請使用已驗證來源的安裝程式。'))
        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setPlaceholderText('本次工作階段的作業狀態。僅記錄作業名稱與結果類型，不記錄金鑰或供應商回應內容。'); layout.addWidget(self.log_view)
        layout.addStretch()

    def _safe(self, callback):
        try:
            return callback()
        except Exception as exc:
            self.status.setText('作業未完成：' + str(exc))
            return None

    def _browse(self, target):
        name, _ = QFileDialog.getOpenFileName(self, '選取本機檔案')
        if name: target.setText(name)

    def _family_changed(self):
        from quantlab.strategies import builtin_strategies
        spec = builtin_strategies()[self.family.currentIndex()]
        self.parameters.setPlainText(canonical_json(spec.parameters))
        self.strategy_detail.setPlainText(canonical_json({'strategy': spec, 'sha256': content_hash(spec), 'scope': 'research_and_paper_only'}))

    def import_data(self):
        if not self.import_path.text().strip() or not self.calendar_path.text().strip():
            raise ValidationError('請選擇資料檔與交易日曆')
        self.start_job('ui_import', {'path': self.import_path.text(), 'calendar': self.calendar_path.text(), 'kind': self.import_kind.currentText(), 'contract': self.contract.text()})

    def download_data(self):
        if not self.network_data.isChecked(): raise ValidationError('請先勾選本次網路下載同意')
        self.start_job('ui_refresh', {'days':self.days.value(), 'network_opt_in':True})
        self.network_data.setChecked(False)

    def run_backtest(self):
        for field in (self.start_date, self.end_date):
            if field.text().strip(): datetime.strptime(field.text().strip(), '%Y-%m-%d')
        self.start_job('ui_backtest', {'family':self.family.currentText(), 'parameters':json.loads(self.parameters.toPlainText()), 'config':json.loads(self.config.toPlainText()), 'start_date':self.start_date.text().strip(), 'end_date':self.end_date.text().strip(), 'batch':self.batch.isChecked()})

    def run_campaign(self):
        text = self.campaign_config.toPlainText().strip()
        options = {'mode':self.provider_mode.currentData()}
        if options['mode'] == 'compatible':
            options.update(endpoint=self.ai_endpoint.text().strip(), model=self.ai_model.text().strip(),
                network_opt_in=self.ai_opt_in.isChecked(), use_credential=self.use_key.isChecked(),
                max_calls=self.max_calls.value(), max_tokens=self.max_tokens.value(),
                max_spend=self.max_spend.text().strip(), cost_per_token=self.cost_per_token.text().strip(),
                tokens_per_call=self.tokens_per_call.value(), timeout_seconds=self.timeout_seconds.value())
            if options['network_opt_in'] is not True: raise ValidationError('請至設定核對供應商、費率與預算，並勾選本次網路及費用同意')
            # Construction checks only; no HTTP or credential reads in the GUI.
            campaign_generator(self.paths, options)
        self.start_job('ui_campaign', {'config':json.loads(text) if text else None, 'provider':options})
        self.ai_opt_in.setChecked(False)

    def select_strategy(self):
        path = self.result_choice.currentData()
        if not path: raise ValidationError('請先執行回測並選擇結果')
        self.start_job('ui_select', {'result':path})

    def demo_paper_policy(self):
        data = load_dataset(self.root / 'dataset.json')
        if data.manifest['source_type'] != 'synthetic': raise ValidationError('只有合成資料可以套用示範政策')
        sessions = []
        for day in sorted({b.trade_date for b in data.bars}):
            bars = [b for b in data.bars if b.trade_date == day]
            sessions.append({'open':bars[0].timestamp.isoformat(), 'end':bars[-1].end.isoformat(), 'trade_date':day, 'session':bars[0].session, 'contract_id':bars[0].contract_id, 'source':'explicit synthetic demonstration'})
        self.paper_policy.setPlainText(canonical_json({'contract_id':data.bars[0].contract_id,'risk_sessions':sessions,'margin_schedule':[{'effective_from':'2026-01-01','margin_per_contract':'100000','version':'synthetic-assumption-v1'}]}))

    def paper_job(self, op, **payload):
        if op in ('submit', 'replay'):
            if not self.paper_confirm.isChecked(): raise ValidationError('請核對參考快照並明確勾選本次對帳同意')
            payload.update(snapshot=json.loads(self.snapshot.toPlainText()), reconcile_confirmed=True)
        payload['policy'] = json.loads(self.paper_policy.toPlainText())
        self.start_job('ui_paper_' + op, payload)
        self.paper_confirm.setChecked(False)

    def kill_paper(self):
        if self.jobs.active:
            self.jobs.cancel()
            self.status.setText('已要求取消；等待背景作業停止後再啟用紙上停止開關')
            self._kill_pending = True
        else: self.paper_job('kill')

    def start_job(self, operation, payload):
        if self.jobs.active: raise ValidationError('已有背景作業，請等待或取消')
        self.jobs.start(operation, payload)
        self.last_operation = operation
        self.status.setText('背景作業進行中；可切換頁面或取消。')
        self._busy(True)

    def _busy(self, active):
        for button in self.actions: button.setEnabled(not active)
        self.kill_button.setEnabled(True)
        self.cancel_button.setEnabled(active)
        self.progress.setRange(0, 0 if active else 100)
        if not active:
            self.progress.setValue(0)
            self.run_button.setEnabled((self.root / 'dataset.json').exists())

    def cancel_job(self):
        self._safe(self.jobs.cancel)
        self.status.setText('已要求取消；正在等待程序退出，未宣告成功。')

    def poll_jobs(self):
        try:
            for event in self.jobs.poll():
                kind = event.get('type', '')
                self.log_view.appendPlainText((self.last_operation or 'background') + ' · ' + str(kind))
                if kind in ('result', 'completed', 'success'):
                    result = event.get('result', {})
                    text = canonical_json(result)
                    self.summary.setPlainText(text)
                    if self.last_operation == 'ui_compare': self.comparison.setPlainText(text)
                    if self.last_operation and self.last_operation.startswith('ui_paper_'): self.paper_detail.setPlainText(text)
                    if self.last_operation == 'ui_backup_restore': self.freeze_paper('備份已還原，請重新核對帳戶')
                    self.status.setText('作業完成，結果已保存於本機。')
                    self.refresh_views()
                elif kind in ('error', 'failed'):
                    if self.last_operation == 'ui_backup_restore':
                        self.backups.recover()
                        self.freeze_paper('還原未完成，請重新核對帳戶')
                    self.status.setText('作業失敗：' + str(event.get('message', event.get('error', '未知錯誤'))))
                elif kind in ('cancelled', 'canceled'):
                    if self.last_operation == 'ui_backup_restore': self.backups.recover()
                    self.freeze_paper('背景作業已取消')
                    self.status.setText('作業已取消；已完成的檔案保留，未完成部分不代表成功。')
                else:
                    self.status.setText(str(event.get('message', '背景作業進行中')))
            if not self.jobs.active:
                self._busy(False)
                if getattr(self, '_kill_pending', False):
                    self._kill_pending = False
                    self.paper_job('kill')
        except Exception as exc:
            self.status.setText('狀態讀取失敗：' + str(exc))

    def refresh_views(self):
        path = self.root / 'dataset.json'
        if path.exists():
            data = load_dataset(path)
            self.overview.setText(f"資料來源：{data.manifest['source_type'].upper()} · {len(data.bars)} 根\n本機資料與紙上交易；實單：DISABLED；真實模型：NOT_VERIFIED")
            self.data_card.setText('資料來源\n\n' + data.manifest['source_type'].upper() + f' · {len(data.bars)} 根')
            self.data_detail.setPlainText(canonical_json({'manifest':data.manifest, 'quality':data.quality}))
        else:
            self.overview.setText('尚無資料。請先匯入本機資料或建立明示合成示範。')
        self.run_button.setEnabled(path.exists() and not self.jobs.active)
        old = self.result_choice.currentData()
        active = self.root / 'active_result.json'
        if self.last_operation == 'ui_backtest' and active.exists():
            digest = read_json(active).get('result_hash', '')
            if len(digest) == 64 and all(c in '0123456789abcdef' for c in digest): old = str(self.root / 'reports' / digest / 'result.json')
        self.result_choice.blockSignals(True); self.result_choice.clear(); self.comparison_list.clear()
        for result_path in sorted((self.root / 'reports').glob('*/result.json')):
            label = result_path.parent.name
            self.result_choice.addItem(label, str(result_path))
            self.comparison_list.addItem(label); self.comparison_list.item(self.comparison_list.count()-1).setData(Qt.ItemDataRole.UserRole, str(result_path))
        index = self.result_choice.findData(old)
        if index >= 0: self.result_choice.setCurrentIndex(index)
        self.result_choice.blockSignals(False); self.show_result()
        selection = self.root / 'selection.json'
        self.selection_status.setText('啟用策略：' + canonical_json(load_selection(selection)) if selection.exists() else '尚未啟用任何策略')
        policy = self.root / 'paper_policy.json'
        if policy.exists(): self.paper_policy.setPlainText(canonical_json(read_json(policy)))
        history = []
        for p in sorted((self.root / 'campaigns').glob('*/*.json'))[:100]:
            history.append({'file':str(p), 'content':read_json(p)})
        self.history.setPlainText(canonical_json(history) if history else '尚無研究版本或 OOS 結果')

    def show_result(self, index=None):
        path = self.result_choice.currentData()
        if not path: self.plot.set_values([]); self.result_detail.setPlainText('尚無回測結果'); return
        try:
            result = load_result(path)
            self.plot.set_values(result.equity)
            self.result_detail.setPlainText(canonical_json({'metrics':result.metrics, 'warnings':result.warnings, 'manifest':result.manifest, 'fills':result.fills, 'rejects':result.rejects}))
        except Exception as exc: self.status.setText('結果驗證失敗：' + str(exc))

    def save_settings(self):
        if self.settings is None: raise ValidationError('設定儲存服務不可用')
        endpoint = self.ai_endpoint.text().strip()
        if endpoint: validate_endpoint(endpoint)
        value = self.settings.load()
        value.update({'ai_endpoint':self.ai_endpoint.text().strip(), 'ai_model':self.ai_model.text().strip(),
            'max_calls':self.max_calls.value(), 'max_tokens':self.max_tokens.value(), 'tokens_per_call':self.tokens_per_call.value(),
            'timeout_seconds':self.timeout_seconds.value(), 'max_spend':self.max_spend.text().strip(), 'cost_per_token':self.cost_per_token.text().strip()})
        self.settings.save(value)
        self.ai_opt_in.setChecked(False)
        self.status.setText('已保存非敏感偏好；網路同意已重設，未在設定中保存金鑰。')

    def load_settings(self):
        if self.settings is None: return
        value = self.settings.load()
        endpoint = value.get('ai_endpoint', '')
        if endpoint: validate_endpoint(endpoint)
        self.ai_endpoint.setText(endpoint)
        self.ai_model.setText(value.get('ai_model', ''))
        for key in ('max_calls', 'max_tokens', 'tokens_per_call', 'timeout_seconds'):
            if key in value: getattr(self, key).setValue(value[key])
        for key in ('max_spend', 'cost_per_token'):
            if key in value: getattr(self, key).setText(value[key])
        self.ai_opt_in.setChecked(False)

    def save_api_key(self):
        from quantlab.desktop_runtime import CredentialVault
        secret = self.api_key.text()
        try:
            CredentialVault(self.paths).save('model_api_key', secret)
            self.status.setText('金鑰已存至目前 Windows 使用者的安全儲存庫；不包含於備份。')
        finally:
            self.api_key.clear()
            del secret

    def backup(self, restore):
        if self.backups is None: raise ValidationError('備份服務不可用')
        if not self.backup_path.text().strip(): raise ValidationError('請填寫備份路徑')
        if restore and not self.restore_confirm.isChecked(): raise ValidationError('請先確認還原取代本機狀態')
        if self.jobs.active: raise ValidationError('請先等待背景作業停止')
        self.start_job('ui_backup_restore' if restore else 'ui_backup_create', {'path':self.backup_path.text()})
        self.restore_confirm.setChecked(False)

    def freeze_paper(self, reason):
        self.paper_confirm.setChecked(False)
        if self.guard is not None: self.guard.reconciliation_required = True
        write_json(self.root / 'desktop_safety.json', {'reconciliation_required':True, 'reason':str(reason)})
        if (self.root / 'paper_policy.json').exists():
            broker = _paper(self.root)
            broker.set_kill_switch(True)
        self.status.setText('紙上執行已凍結：' + str(reason) + '；每次執行需核對快照並明確對帳。')

    def closeEvent(self, event):
        if self.jobs.active and QMessageBox.question(self, '背景作業尚未完成', '取消背景作業並關閉？', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            event.ignore(); return
        try:
            self.jobs.close()
            if self.guard is not None: self.guard.finish()
        except Exception:
            event.ignore(); self.status.setText('關閉失敗，背景作業尚未確認停止。'); return
        self.timer.stop(); event.accept()


def create_window(paths, jobs, settings=None, backups=None, guard=None):
    return MainWindow(paths, jobs, settings, backups, guard)

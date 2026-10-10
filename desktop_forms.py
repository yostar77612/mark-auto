"""Small, data-only Traditional Chinese Qt forms for the existing worker API.

Forms never start work or connect to brokers. ``from_payload`` loads a detached
copy; ``build_payload`` validates without changing external state. Embed these
widgets in the desktop page's QScrollArea. Exact decimal strings avoid float or
QDoubleSpinBox rounding. Backend validation remains authoritative.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QPushButton, QHBoxLayout, QHeaderView)

from quantlab.core import ValidationError, StrategySpec, validate_date, validate_contract, to_dict
from quantlab.strategies import DEFAULTS, FAMILIES, validate_strategy

FAMILY_LABELS = dict(zip(FAMILIES, ('均線趨勢', '均值回歸', '通道突破', '動能', '波動壓縮')))
PARAM_LABELS = {'fast':'快速均線（根）', 'slow':'慢速均線（根）', 'lookback':'回看期間（根）',
    'entry_bps':'進場偏離（基點，1 bp = 0.01%）', 'threshold_bps':'動能門檻（基點）',
    'max_holding_bars':'最長持有（根）', 'max_range_bps':'最大區間（基點）',
    'quantity':'策略數量（口，可留白）', 'stop_ticks':'停損（點，可留白）', 'target_ticks':'停利（點，可留白）'}


def number(text, label, minimum=0, maximum='1e12', *, integer=False, optional=False):
    """Strict bounded decimal input; never silently clamp, round, or default."""
    text = str(text).strip()
    if not text and optional: return None
    if len(text) > 128 or not text:
        raise ValidationError(f'{label}：請輸入有效數字')
    try:
        value = Decimal(text)
        if not value.is_finite() or value < Decimal(str(minimum)) or value > Decimal(str(maximum)):
            raise ValueError()
        # Bound exponent as well as magnitude to avoid enormous decimal expansion.
        if abs(value.as_tuple().exponent) > 32: raise ValueError()
        if integer and (not re.fullmatch(r'[+-]?\d+', text) or value != value.to_integral_value()):
            raise ValueError()
    except (InvalidOperation, ValueError, OverflowError):
        raise ValidationError(f'{label}：須為 {minimum} 至 {maximum} 的' + ('整數' if integer else '有限數值')) from None
    return int(value) if integer else format(value, 'f')


def required(text, label):
    text = text.strip()
    if not text or len(text) > 256: raise ValidationError(f'{label}：請填寫 1 至 256 字元')
    return text


def utc(text, label):
    from quantlab.paper import _time
    value = required(text, label)
    try: _time(value, label)
    except ValidationError: raise ValidationError(f'{label}：須含 UTC 時區，例如 2026-01-05T01:00:00Z') from None
    return value


class _Form(QWidget):
    """Shared label/field plumbing only; each payload is explicit below."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = {}
        self.outer = QVBoxLayout(self)
        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.outer.addLayout(self.form)

    def note(self, text):
        label = QLabel(text); label.setWordWrap(True); self.outer.addWidget(label)
        return label

    def field(self, key, label, value='', choices=None):
        if choices is None:
            widget = QLineEdit(str(value))
        else:
            widget = QComboBox()
            for caption, data in choices: widget.addItem(caption, data)
        widget.setObjectName(key); widget.setAccessibleName(label)
        caption = QLabel(label); caption.setBuddy(widget)
        self.form.addRow(caption, widget); self.fields[key] = widget
        return widget

    def text(self, key): return self.fields[key].text().strip()

    def num(self, key, minimum=0, maximum='1e12', **kwargs):
        return number(self.text(key), self.fields[key].accessibleName(), minimum, maximum, **kwargs)

    def load(self, values):
        for key, value in values.items():
            if key not in self.fields: continue
            field = self.fields[key]
            if isinstance(field, QComboBox):
                index = field.findData(value)
                if index < 0: raise ValidationError(f'{field.accessibleName()}：不支援的選項')
                field.setCurrentIndex(index)
            else: field.setText('' if value is None else str(value))
        return self


class StrategyForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.family = self.field('family', '策略家族', choices=[(FAMILY_LABELS[f], f) for f in FAMILIES])
        self.parameter_form = QFormLayout(); self.outer.addLayout(self.parameter_form)
        self._spec = None
        self.family.currentIndexChanged.connect(self._family_changed)
        self._family_changed()
        self.note('僅內建有限家族；基點為百分之一個百分點。停損／停利於同棒採保守規則。')

    def _family_changed(self):
        while self.parameter_form.rowCount(): self.parameter_form.removeRow(0)
        self.fields = {'family': self.family}
        family = self.family.currentData()
        self._spec = {'strategy_id':f'{family}-v1', 'family':family, 'parameters':dict(DEFAULTS[family]), 'rules':{}, 'schema_version':1}
        for key, value in {**DEFAULTS[family], 'quantity':'', 'stop_ticks':'', 'target_ticks':''}.items():
            widget = QLineEdit(str(value)); widget.setObjectName(key); widget.setAccessibleName(PARAM_LABELS[key])
            label = QLabel(PARAM_LABELS[key]); label.setBuddy(widget)
            self.parameter_form.addRow(label, widget); self.fields[key] = widget

    def from_payload(self, payload):
        spec = StrategySpec(**deepcopy(payload)); validate_strategy(spec)
        if spec.rules: raise ValidationError('自訂 DSL 候選須使用唯讀版本檢視，不可改成內建表單')
        self.family.setCurrentIndex(self.family.findData(spec.family)); self._family_changed()
        self._spec = to_dict(spec); self.load(spec.parameters)
        return self

    def build_payload(self):
        p = {}
        for key in self.fields:
            if key == 'family': continue
            optional = key in ('quantity','stop_ticks','target_ticks')
            if optional and not self.text(key): continue
            p[key] = self.num(key, integer=not key.endswith('_bps'))
        spec = StrategySpec(self._spec['strategy_id'], self.family.currentData(), p, {}, self._spec['schema_version'])
        validate_strategy(spec)
        return to_dict(spec)


class BacktestForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        for key, label in (
            ('initial_cash','初始資金（TWD）'), ('max_position','最大部位（口）'),
            ('commission_per_side','單邊手續費（TWD／口）'), ('tax_rate','交易稅率（比例，0.00002 = 0.002%）'),
            ('slippage_ticks','單邊滑價（點）'), ('effective_from','費率生效日（YYYY-MM-DD）'),
            ('version','費率版本／來源'), ('initial_margin_per_contract','原始保證金（TWD／口，可留白）'),
            ('maintenance_margin_per_contract','維持保證金（TWD／口，可留白）'), ('margin_version','保證金版本／來源'),
            ('seed','固定種子（整數）'), ('start_date','起始交易日（YYYY-MM-DD，空白全部）'),
            ('end_date','結束交易日（YYYY-MM-DD，含當日）')):
            self.field(key, label)
        self.field('tax_rounding','稅額取整方式', choices=[('四捨五入至新台幣元','half_up_twd'), ('向下取整至新台幣元','floor_twd'), ('向上取整至新台幣元','ceiling_twd'), ('不取整','none')])
        self.note('初始值為明示合成假設，並非現行市場費率或保證金。已載入的進階時序政策會完整保留。')
        self.expiry_note = self.note(
            '真實／代理資料須逐一填寫明確合約（TAIFEX:TMF:YYYYMM）及到期日（最後交易日，YYYY-MM-DD）。請先自行核對期交所微臺指期貨契約規格 '
            'https://www.taifex.com.tw/cht/2/tMF、該年度交易行事曆及異動公告，再輸入日期；已載入的日期也須核對。'
            '本表僅檢查格式，不會驗證來源或推算第三個星期三，也不代表已取得結算價格。回測與研究 Campaign 共用此設定。')
        self.expiry_note.setObjectName('instrument_expiries_note')
        self.expiry_note.setTextFormat(Qt.TextFormat.PlainText)
        self.expiry_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.expiries = _Rows('instrument_expiries', [
            ('contract_id','合約代碼'), ('expiry_date','到期日（YYYY-MM-DD）')])
        self.expiries.table.horizontalHeaderItem(0).setToolTip('明確合約（TAIFEX:TMF:YYYYMM）')
        self.expiries.table.horizontalHeaderItem(1).setToolTip('到期日／最後交易日（YYYY-MM-DD）')
        self.expiries.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.expiries.table.setAccessibleName('合約到期日（須自行核對官方來源）')
        self.outer.addWidget(self.expiries)
        from quantlab.reporting import demo_config
        self.from_payload({'config':to_dict(demo_config()), 'start_date':'', 'end_date':''})

    def from_payload(self, payload):
        config = deepcopy(payload.get('config', payload))
        from quantlab.__main__ import config_from_json
        parsed = config_from_json(config)
        config = {**to_dict(parsed), **config}
        self._config = config
        self.load(config); self.load(config['costs'])
        self.expiries.load([{'contract_id':contract, 'expiry_date':expiry}
            for contract,expiry in config['instrument_expiries'].items()])
        self.load({k:payload.get(k, '') for k in ('start_date','end_date')})
        return self

    def build_payload(self):
        config = deepcopy(self._config)
        expiries = {}
        for index,row in enumerate(self.expiries.values(), 1):
            contract, expiry = row['contract_id'], row['expiry_date']
            try:
                validate_contract(contract); validate_date(expiry)
            except ValidationError:
                raise ValidationError(f'合約到期日第 {index} 列：須為 TAIFEX:TMF:YYYYMM 有效合約及 YYYY-MM-DD 有效日期') from None
            if contract in expiries: raise ValidationError(f'合約到期日第 {index} 列：合約重複 {contract}')
            expiries[contract] = expiry
        config['instrument_expiries'] = expiries
        config['initial_cash'] = self.num('initial_cash')
        config['max_position'] = self.num('max_position', 1, 1000000, integer=True)
        config['seed'] = self.num('seed', 0, 2147483647, integer=True)
        for key in ('initial_margin_per_contract','maintenance_margin_per_contract'):
            config[key] = self.num(key, optional=True)
        config['margin_version'] = self.text('margin_version') or None
        costs = deepcopy(config['costs'])
        costs.update(commission_per_side=self.num('commission_per_side'), tax_rate=self.num('tax_rate', 0, 1),
            slippage_ticks=self.num('slippage_ticks', 0, 100000, integer=True),
            effective_from=self.text('effective_from'), version=required(self.text('version'),'費率版本'),
            tax_rounding=self.fields['tax_rounding'].currentData())
        config['costs'] = costs
        from quantlab.__main__ import config_from_json
        config_from_json(config)
        start, end = self.text('start_date'), self.text('end_date')
        for value in (start,end):
            if value: validate_date(value, '交易日')
        if start and end and start > end: raise ValidationError('起始交易日不得晚於結束交易日')
        return dict(config=config, start_date=start, end_date=end)


class CampaignForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = None
        self.note('依資料列索引切分，起點含、終點不含；OOS／保留集不可回饋生成器。執行前仍需另外確認保留集的一次性使用。')
        for split, label in (('train','訓練'),('validation','驗證'),('oos','樣本外 OOS'),('holdout','最終保留集')):
            self.field(split+'_start',label+'起點（第幾根，自 0 起）')
            self.field(split+'_end',label+'終點（不含）')
        for key,label,value in (
            ('max_trials','最多候選嘗試（1–15 次）',15),('max_improvements','每家族最多改良（0–2 次）',2),
            ('seed','固定種子',0),('max_runtime_seconds','總執行上限（秒，1–7200）',300),
            ('max_bars','資料根數上限（1–100000）',100000),('purge_bars','各切分尾端排除（根）',0),
            ('minimum','最低淨損益門檻（TWD）',0),('min_trades','最少成交筆數',0)):
            self.field(key,label,value)
        self.families = {}
        for family in FAMILIES:
            box = QCheckBox(FAMILY_LABELS[family]); box.setObjectName('campaign_'+family); box.setChecked(True)
            box.setAccessibleName('研究家族 '+FAMILY_LABELS[family]); self.outer.addWidget(box); self.families[family] = box

    def from_payload(self, payload):
        families = payload.get('families')
        if not isinstance(families,list) or not families or len(set(families)) != len(families) or any(f not in FAMILIES for f in families):
            raise ValidationError('研究家族缺漏、重複或不支援')
        self._config = deepcopy(payload)
        self.load(payload); self.load(payload['ranking'])
        for split,bounds in payload['splits'].items(): self.load({split+'_start':bounds[0],split+'_end':bounds[1]})
        for family,box in self.families.items(): box.setChecked(family in payload['families'])
        return self

    def build_payload(self, backtest_config=None):
        if self._config is None and backtest_config is None: raise ValidationError('請先載入資料切分與回測費率')
        config = deepcopy(self._config or {})
        if backtest_config is not None: config['backtest_config'] = deepcopy(backtest_config)
        bounds = {'max_trials':(1,15),'max_improvements':(0,2),'seed':(0,2147483647),
            'max_runtime_seconds':(1,7200),'max_bars':(1,100000),'purge_bars':(0,1000)}
        for key,(low,high) in bounds.items(): config[key] = self.num(key,low,high,integer=True)
        config['splits'] = {}; previous = 0
        for split in ('train','validation','oos','holdout'):
            start = self.num(split+'_start',0,config['max_bars'],integer=True)
            end = self.num(split+'_end',0,config['max_bars'],integer=True)
            if start < previous or end <= start + config['purge_bars']: raise ValidationError('切分不可重疊、倒序或在排除後為空')
            config['splits'][split] = [start,end]; previous = end
        config['families'] = [f for f,b in self.families.items() if b.isChecked()]
        if not config['families']: raise ValidationError('請至少選擇一種研究家族')
        config['ranking'] = dict(metric='net_pnl', minimum=self.num('minimum','-1e12'), min_trades=self.num('min_trades',0,1000000,integer=True))
        from quantlab.__main__ import config_from_json
        config_from_json(config['backtest_config'])
        return config


class WalkForwardForm(_Form):
    """Typed chronology editor; saved pools are admitted only by the worker."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.field('pool_origin', '固定候選池來源（只能擇一）', choices=[
            ('五個精確內建規格（預設）', 'exact_builtin_pool'),
            ('已保存 AI 研究的固定候選池', 'saved_campaign_pool')])
        self.field('mode', '訓練窗口', choices=[('固定寬度', 'rolling'), ('固定起點', 'expanding')])
        self.field('evidence_mode', '證據模式（歷史重播必須自行選取）', choices=[
            ('僅合成驗證（預設）', 'synthetic_validation'),
            ('歷史重播，資料暴露未驗證', 'historical_replay')])
        for key, label, value in (
            ('start', '首折起點（自 0 起，含）', 0),
            ('train_bars', '首折訓練寬度（根）', 240),
            ('validation_bars', '驗證寬度（根）', 120), ('oos_bars', '前推 OOS 寬度（根）', 120),
            ('fold_count', '折數（2–20）', 3), ('step_bars', '每折步進（根，至少 OOS 寬度）', 120),
            ('gap_bars', '切分間隙（根）', 0),
            ('final_holdout_start', '排除最終保留集起點（含）', 720),
            ('final_holdout_end', '排除最終保留集終點（不含，等於來源總根數）', 960),
            ('max_evaluations', '全實驗評估額度（1–220，包含失敗／中斷）', 33),
            ('max_runtime_seconds', '全實驗總秒數（1–7200）', 300),
            ('minimum', '驗證最低淨損益（TWD）', '0'),
            ('min_trades', '驗證最少已平倉 lot（至少 1）', 1),
            ('max_drawdown_percent', '驗證最大回撤上限（%，10 表示核心比例 0.10）', '10.00')):
            self.field(key, label, value)
        self._plan = None
        self.fields['pool_origin'].currentIndexChanged.connect(self._pool_origin_changed)
        self._pool_origin_changed()
        self.note('內建池或已保存研究池只能擇一；訓練僅描述，驗證須通過三項門檻，再依淨損益選單一贏家。預覽後門檻鎖定。這是工程護欄，並非投資適合度或獲利證明。')
        self.note('共用「回測與結果」的明示費用／資金／保證金與合約到期日；此處依完整來源列索引切分，不套用回測頁的日期篩選。無新模型呼叫、正式排名或紙上資格。已保存池須另選研究及完整原始資料；原有模型狀態不會升級。最終保留集僅排除，不評估。')

    def _pool_origin_changed(self):
        saved = self.fields['pool_origin'].currentData() == 'saved_campaign_pool'
        cap = 620 if saved else 220
        label = f'全實驗評估額度（1–{cap}，包含失敗／中斷；不自動增加）'
        self.form.labelForField(self.fields['max_evaluations']).setText(label)
        self.fields['max_evaluations'].setAccessibleName(label)

    def defaults_for_bars(self, count):
        if type(count) is not int or count < 8: raise ValidationError('Walk-forward 需要至少 8 根資料')
        train, width = max(1, count // 4), max(1, count // 8)
        values = dict(start=0, train_bars=train, validation_bars=width, oos_bars=width,
            fold_count=3, step_bars=width, gap_bars=0, final_holdout_start=train + 4 * width,
            final_holdout_end=count)
        if self.fields['pool_origin'].currentData() == 'exact_builtin_pool': values['max_evaluations'] = 33
        self.load(values)
        return self

    def from_payload(self, payload):
        from quantlab.walk_forward import walk_forward_plan_from_dict
        from decimal import localcontext
        plan = walk_forward_plan_from_dict(deepcopy(payload))
        if plan.pool_origin != 'exact_builtin_pool':
            raise ValidationError('已保存研究池須使用來源選單與原始資料選取器，不接受原始候選 JSON')
        self._plan = to_dict(plan)
        first, second = plan.folds[:2]
        values = dict(pool_origin=plan.pool_origin, mode=plan.mode, evidence_mode=plan.evidence_mode,
            start=first.train[0], train_bars=first.train[1] - first.train[0],
            validation_bars=first.validation[1] - first.validation[0], oos_bars=first.oos[1] - first.oos[0],
            fold_count=len(plan.folds), step_bars=second.train[1] - first.train[1], gap_bars=plan.gap_bars,
            final_holdout_start=plan.final_holdout[0], final_holdout_end=plan.final_holdout[1],
            max_evaluations=plan.max_evaluations, max_runtime_seconds=plan.max_runtime_seconds,
            minimum=plan.ranking['minimum'], min_trades=plan.ranking['min_trades'])
        with localcontext() as context:
            context.prec = 80
            values['max_drawdown_percent'] = format(Decimal(str(plan.ranking['max_drawdown_pct'])) * 100, 'f')
        self.load(values)
        # This editor promises a uniform step. Reject arbitrary variable-step
        # imported plans rather than silently changing their declared chronology.
        if to_dict(walk_forward_plan_from_dict(self.build_payload())) != self._plan:
            raise ValidationError('表單僅支援固定步進計畫；不會暗中改變匯入範圍')
        return self

    def build_payload(self, backtest_config=None):
        from quantlab.__main__ import config_from_json
        from quantlab.walk_forward import build_walk_forward_plan
        from decimal import localcontext
        stored = deepcopy(self._plan or {})
        config = backtest_config if backtest_config is not None else stored.get('backtest_config')
        if config is None: raise ValidationError('請先核對共用回測費用設定')
        values = {}
        for key in ('start', 'train_bars', 'validation_bars', 'oos_bars', 'step_bars'):
            values[key] = self.num(key, 0 if key == 'start' else 1, 100000, integer=True)
        saved = self.fields['pool_origin'].currentData() == 'saved_campaign_pool'
        for key, low, high in (('fold_count', 2, 20), ('gap_bars', 0, 1000),
                              ('max_evaluations', 1, 620 if saved else 220), ('max_runtime_seconds', 1, 7200)):
            values[key] = self.num(key, low, high, integer=True)
        with localcontext() as context:
            context.prec = 80
            cap = format(Decimal(self.num('max_drawdown_percent', 0, 100)) / 100, 'f')
        values.update(mode=self.fields['mode'].currentData(), evidence_mode=self.fields['evidence_mode'].currentData(),
            final_holdout=(self.num('final_holdout_start', 0, 100000, integer=True), self.num('final_holdout_end', 1, 100000, integer=True)),
            ranking=dict(metric='net_pnl', minimum=self.num('minimum', '-1e12'),
                min_trades=self.num('min_trades', 1, 1000000, integer=True), max_drawdown_pct=cap))
        for key in ('max_bars', 'process_start_method', 'worker_memory_mb', 'max_ipc_bytes', 'schema_version'):
            if key in stored: values[key] = stored[key]
        if not saved:
            return to_dict(build_walk_forward_plan(backtest_config=config_from_json(deepcopy(config)), **values))
        # Validate chronology independently of the still-unadmitted pool. The
        # user's exact budget is restored unchanged; no budget is auto-raised.
        budget = values['max_evaluations']
        template = to_dict(build_walk_forward_plan(backtest_config=config_from_json(deepcopy(config)),
            **{**values, 'max_evaluations': 1}))
        template.pop('candidate_pool', None); template.pop('pool_admission', None)
        template.update(pool_origin='saved_campaign_pool', max_evaluations=budget)
        return template


class PaperIntentForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        for key,label in (('client_order_id','紙上委託識別碼（不可重複）'),('strategy_hash','已啟用策略 SHA-256'),
            ('contract_id','明確合約（TAIFEX:TMF:YYYYMM）'),('quantity','委託數量（口）'),
            ('created_at','建立時間（UTC）'),('limit_price','限價（整數點；市價單留白）')): self.field(key,label)
        self.field('side','方向',choices=[('買進','buy'),('賣出','sell')])
        self.field('order_type','委託類型',choices=[('市價','market'),('限價','limit')])
        self.note('僅建立紙上意圖。未連接即時行情或券商；不會自動送單或模擬成交。')

    def from_payload(self, payload):
        allowed = {'client_order_id','strategy_hash','contract_id','quantity','created_at','limit_price','side','order_type'}
        if set(payload)-allowed: raise ValidationError('不支援的紙上意圖欄位')
        for field in self.fields.values():
            if isinstance(field,QLineEdit): field.clear()
        return self.load(deepcopy(payload))

    def build_payload(self):
        p = {key:required(self.text(key),self.fields[key].accessibleName()) for key in ('client_order_id','strategy_hash','contract_id')}
        validate_contract(p['contract_id'])
        if not re.fullmatch('[0-9a-f]{64}',p['strategy_hash']): raise ValidationError('策略 SHA-256 須為 64 位小寫十六進位')
        p.update(quantity=self.num('quantity',1,1000000,integer=True), created_at=utc(self.text('created_at'),'建立時間'),
            side=self.fields['side'].currentData(),order_type=self.fields['order_type'].currentData())
        if p['order_type'] == 'limit': p['limit_price'] = str(self.num('limit_price',1,1000000000,integer=True))
        elif self.text('limit_price'): raise ValidationError('市價單不得包含限價；請清空限價欄位')
        return p


class PaperQuoteForm(_Form):
    def __init__(self, parent=None):
        super().__init__(parent)
        for key,label in (('account_id','紙上帳戶識別碼'),('contract_id','明確合約（TAIFEX:TMF:YYYYMM）'),
            ('price','參考報價（整數點，需自行核對來源）'),('timestamp','報價時間（UTC）'),
            ('trade_date','交易日（YYYY-MM-DD）'),('session_open','時段開始（UTC）'),
            ('session_end','時段結束（UTC，不含）'),('margin_per_contract','原始保證金（TWD／口，須符合鎖定政策）')): self.field(key,label)
        self.note('報價預設空白。請提供已核對來源；手動輸入不代表即時或已驗證行情。')

    def from_payload(self,payload):
        if set(payload) != set(self.fields): raise ValidationError('報價欄位缺漏或不支援')
        return self.load(deepcopy(payload))

    def build_payload(self):
        p = {key:required(self.text(key), self.fields[key].accessibleName()) for key in ('account_id','contract_id','trade_date')}
        validate_contract(p['contract_id']); validate_date(p['trade_date'],'交易日')
        for key in ('timestamp','session_open','session_end'): p[key] = utc(self.text(key),self.fields[key].accessibleName())
        from quantlab.paper import _time
        if not _time(p['session_open']) <= _time(p['timestamp']) < _time(p['session_end']): raise ValidationError('報價時間必須在指定交易時段內')
        p['price'] = str(self.num('price',1,1000000000,integer=True))
        p['margin_per_contract'] = self.num('margin_per_contract','0.000000000001')
        return p


class PaperSnapshotForm(_Form):
    """Edit account/cash; retain imported position/order/fill records exactly.

    Existing nested records are review-only: never fabricate or clear them to
    force reconciliation. Initial empty records still require action consent.
    """
    def __init__(self,parent=None):
        super().__init__(parent)
        self.field('account_id','外部紙上參考帳戶識別碼')
        self.field('cash','已核對現金（TWD）')
        self._snapshot = {'positions':{},'orders':{},'fills':{}}
        self.records = SummaryCard(); self.outer.addWidget(self.records)
        self.record_tables = {}
        for key,label in (('positions','完整參考部位'),('orders','完整參考委託'),('fills','完整參考成交')):
            self.note(label+'（唯讀）')
            table = ResultTable(); table.setObjectName('snapshot_'+key); table.setMaximumHeight(160)
            self.record_tables[key] = table; self.outer.addWidget(table)
        self.note('初次空帳戶請填明確帳號與資金。既有部位、委託與成交需載入完整參考快照；不會自動覆寫帳戶或宣告對帳成功。')
        self._show_records()

    def _show_records(self):
        self.records.set_values({'部位項目':len(self._snapshot['positions']), '委託項目':len(self._snapshot['orders']), '成交項目':len(self._snapshot['fills'])})
        for key,table in self.record_tables.items():
            table.set_rows([{'識別碼':identifier, **(value if isinstance(value,dict) else {'數量（口）':value})} for identifier,value in self._snapshot[key].items()])

    def from_payload(self,payload):
        for key in ('positions','orders','fills'):
            if not isinstance(payload.get(key),dict): raise ValidationError('快照必須包含完整部位、委託與成交紀錄')
        self._snapshot = deepcopy(payload); self.load(payload); self._show_records()
        return self

    def build_payload(self):
        p = deepcopy(self._snapshot)
        p.update(account_id=required(self.text('account_id'),'帳戶識別碼'),cash=self.num('cash'))
        return p


class PaperActionForm(_Form):
    """Per-action controls; restored input never restores consent."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.field('now','本次紙上事件時間（UTC）')
        self.field('order_id','欲取消的紙上委託 ID')
        self.field('max_bars','本批歷史重播上限（根）','100')
        self.confirm = QCheckBox('我已核對參考快照，明確同意本次對帳／重播／紙上委託')
        self.confirm.setObjectName('paper_action_confirm'); self.outer.addWidget(self.confirm)
        self.note('固定風控：部位最多 1 口、單筆最多 1 口、每日損失 1000 TWD、報價最多 30 秒；連續虧損上限 3 次、60 秒內最多 20 筆。停止新委託不會平倉。')

    def from_payload(self,payload):
        self.load(payload); self.clear_confirmation(); return self

    def clear_confirmation(self): self.confirm.setChecked(False)

    def build_payload(self,action):
        if action not in ('snapshot','reconcile','submit','replay','cancel','kill'): raise ValidationError('未知紙上操作')
        if action in ('snapshot','kill'): return {}
        if action == 'cancel':
            return {'now':utc(self.text('now'),'取消時間'), 'order_id':required(self.text('order_id'),'委託 ID')}
        if not self.confirm.isChecked(): raise ValidationError('請明確確認本次參考快照；取消確認不會送出操作')
        p = {'reconcile_confirmed':True}
        if action == 'submit': p['now'] = utc(self.text('now'),'本次事件時間')
        if action == 'replay': p['max_bars'] = self.num('max_bars',1,1000,integer=True)
        return p


class _Rows(QWidget):
    """Plain typed table for bounded policy rows, with keyboard-accessible buttons."""
    def __init__(self,name,columns,parent=None):
        super().__init__(parent)
        self.columns = columns; self._original = []
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0,len(columns)); self.table.setObjectName(name)
        self.table.setHorizontalHeaderLabels([label for _,label in columns]); layout.addWidget(self.table)
        self.table.resizeColumnsToContents()
        for index, (_, label) in enumerate(columns):
            self.table.horizontalHeaderItem(index).setToolTip(label)
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        add = QPushButton('新增一列'); add.setObjectName(name+'_add'); add.clicked.connect(self.add_row)
        remove = QPushButton('刪除選取列'); remove.setObjectName(name+'_remove'); remove.clicked.connect(self.remove_row)
        buttons.addWidget(add); buttons.addWidget(remove)

    def add_row(self):
        self.table.insertRow(self.table.rowCount()); self._original.append({})

    def remove_row(self):
        row = self.table.currentRow()
        if row >= 0: self.table.removeRow(row); self._original.pop(row)

    def load(self,rows):
        self.table.setRowCount(len(rows)); self._original = deepcopy(rows)
        for i,row in enumerate(rows):
            for j,(key,_) in enumerate(self.columns): self.table.setItem(i,j,QTableWidgetItem(str(row.get(key,''))))

    def values(self):
        rows = deepcopy(self._original)
        for i,row in enumerate(rows):
            for j,(key,label) in enumerate(self.columns):
                item = self.table.item(i,j)
                row[key] = required(item.text() if item else '',label)
        return rows


class PaperPolicyForm(_Form):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.field('contract_id','鎖定合約（TAIFEX:TMF:YYYYMM）')
        self.note('政策須來自明確來源。建立帳戶後不可修改；沒有自動行情或官方日曆推測。所有時間為 UTC。')
        self.sessions = _Rows('risk_sessions',[('open','開始 UTC'),('end','結束 UTC'),('trade_date','交易日'),('source','來源'),('session','day 日盤／night 夜盤')]); self.outer.addWidget(self.sessions)
        self.margins = _Rows('margin_schedule',[('effective_from','生效交易日'),('margin_per_contract','保證金 TWD／口'),('version','版本／來源')]); self.outer.addWidget(self.margins)

    def from_payload(self,payload):
        if set(payload) != {'contract_id','risk_sessions','margin_schedule'}: raise ValidationError('政策欄位缺漏或不支援')
        self.load(payload); self.sessions.load(payload['risk_sessions']); self.margins.load(payload['margin_schedule'])
        return self

    def build_payload(self):
        contract = self.text('contract_id'); validate_contract(contract)
        sessions, margins = self.sessions.values(),self.margins.values()
        if not sessions or not margins: raise ValidationError('請明確填入交易時段與保證金版本')
        for row in sessions:
            utc(row['open'],'時段開始'); utc(row['end'],'時段結束'); validate_date(row['trade_date'],'交易日')
        for row in margins:
            row['margin_per_contract'] = number(row['margin_per_contract'],'保證金','0.000000000001')
        # Invoke the existing pure policy validator without opening a journal.
        from quantlab.paper import PaperBroker
        from quantlab.core import Instrument
        broker = object.__new__(PaperBroker)
        broker.instrument = Instrument(contract); broker._risk_sessions = sessions; broker._margin_schedule = margins
        broker._validate_policy()
        return dict(contract_id=contract,risk_sessions=sessions,margin_schedule=margins)


RESULT_LABELS = {'net_pnl':'淨損益（TWD）','gross_pnl':'毛損益（TWD）','trade_count':'交易筆數',
    'closed_trades':'已平倉交易','fill_count':'成交筆數','max_drawdown':'最大回撤', 'max_drawdown_pct':'最大回撤（比例）',
    'win_rate':'勝率（比例）','profit_factor':'獲利因子','source_type':'資料來源','strategy_hash':'策略版本 SHA-256',
    'result_hash':'結果 SHA-256','warnings':'注意事項','equity_samples':'權益資料點', 'status':'狀態',
    'family':'策略家族','sequence':'候選版本','strategy_id':'策略識別碼','account_id':'帳戶', 'cash':'現金（TWD）',
    'reconciliation_required':'需要對帳','kill_switch':'停止新委託',
    'initial_cash':'初始資金（TWD）','final_equity':'期末權益（TWD）','realized_gross_pnl':'已實現毛損益（TWD）',
    'unrealized_pnl':'未實現損益（TWD）','total_costs':'總費用（TWD）','slippage_cost':'滑價成本（TWD）',
    'return':'報酬率（比例）','closed_lots':'已平倉批次','open_position':'未平倉（口）',
    'sharpe':'夏普值（描述性）','sharpe_reason':'夏普值未定義原因','win_rate_reason':'勝率說明','annualization':'年化假設',
    'profit_factor_reason':'獲利因子未定義原因','profit_factor_basis':'獲利因子計算基礎',
    'sharpe_observations':'夏普值觀測期數','sharpe_note':'夏普值限制',
    'sharpe_sample_count':'有效報酬期數（缺值不略過）',
    'periods_per_year':'假設每年期數','annual_risk_free_rate':'假設年無風險利率',
    'return_frequency':'報酬觀測頻率','first_return':'首期報酬基準','missing_dates':'缺日期處理',
    'standard_deviation':'標準差定義','minimum_observations':'數學最低觀測期數',
    'created_at':'建立時間','side':'方向','quantity':'數量（口）','price':'價格（點）','order_type':'類型',
    'filled_quantity':'已成交（口）','commission':'手續費（TWD）','tax':'交易稅（TWD）'}


def readable(value):
    if value is None: return '未提供'
    if isinstance(value,bool): return '是' if value else '否'
    if isinstance(value,dict): return '；'.join(f'{RESULT_LABELS.get(k,k)}：{readable(v)}' for k,v in value.items())
    if isinstance(value,(list,tuple)): return '；'.join(readable(v) for v in value) or '無'
    return str(value)


class ResultTable(QTableWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('result_table'); self.setAccessibleName('研究與比較結果表')
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)

    def set_rows(self,rows,columns=None):
        columns = columns or list(dict.fromkeys(key for row in rows for key in row))
        self.setSortingEnabled(False); self.clear(); self.setColumnCount(len(columns)); self.setRowCount(len(rows))
        self.setHorizontalHeaderLabels([RESULT_LABELS.get(key,key) for key in columns])
        for i,row in enumerate(rows):
            for j,key in enumerate(columns):
                text = readable(row.get(key)); item = QTableWidgetItem(text); item.setToolTip(text); self.setItem(i,j,item)
        self.resizeColumnsToContents()
        for j in range(len(columns)): self.setColumnWidth(j,min(self.columnWidth(j),340))
        # Stringified decimal metrics deliberately remain in backend-provided order.


class SummaryCard(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); self.label = QLabel(); self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.label.setObjectName('summary_card'); layout.addWidget(self.label)

    def set_values(self,values):
        self.label.setText('\n'.join(f'{RESULT_LABELS.get(k,k)}：{readable(v)}' for k,v in values.items()))


# These adapters only present verified report fields. Raw records remain in the
# host's existing advanced result_detail; no metric or report identity is changed.
_REPORT_TEXT = {
    'no closed lots': '尚無已平倉批次',
    'no losing closed lots': '沒有虧損的已平倉批次，分母為零；不顯示無限大',
    'closed FIFO lot net PnL after allocated entry/exit costs; open lots excluded':
        '採先進先出已平倉批次的完整淨損益，已分攤進出場費用；不含未平倉部位',
    'missing or nonpositive daily equity; no observations discarded':
        '每日權益缺漏、非有限值或不大於零；未略過任何觀測值',
    'at least 2 daily returns required for sample standard deviation':
        '至少需要 2 期有效報酬才能計算樣本標準差',
    'zero daily-return sample variance': '報酬的樣本變異數為零',
    'between last supplied equity per exchange trading date; gaps may span multiple days':
        '依各已提供交易日最後權益計算；間隔可能跨越多日',
    'initial cash to first supplied trading-date equity': '初始資金至首個已提供交易日權益',
    'supplied trading dates only; no imputation': '僅使用已提供交易日，不補值',
    'sample (ddof=1)': '樣本標準差（自由度修正 1）',
    'Descriptive only. Two returns is a mathematical minimum, not evidence of reliability; short samples do not establish strategy quality. The 252-period convention is assumed, not a validated annual trading calendar; gaps may span multiple days.':
        '僅描述本次樣本。2 期只是數學最低需求，不能證明可靠性；短樣本不能證明策略品質。每年 252 期是假設，未驗證全年交易日曆；間隔可能跨越多日。',
}


def _report_text(value):
    if value is None: return '未提供'
    return _REPORT_TEXT.get(value, '未辨識的說明，請查看進階診斷') if isinstance(value, str) else '未辨識的說明，請查看進階診斷'


def _report_number(value):
    if value is None: return '未提供'
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return '請查看進階診斷'
    if len(str(value)) > 128: return '請查看進階診斷'
    try:
        if not Decimal(str(value)).is_finite(): return '請查看進階診斷'
    except (InvalidOperation, ValueError):
        return '請查看進階診斷'
    return str(value)


def backtest_summary_text(values):
    """Bounded Traditional Chinese presentation, preserving exact scalar values."""
    def metric(key):
        value = values.get(key)
        if value is None:
            return '未定義' if key in values and key in ('profit_factor', 'sharpe', 'win_rate') else '未提供'
        return _report_number(value)
    def fields(*keys):
        return '　｜　'.join(f'{RESULT_LABELS[key]}：{metric(key)}' for key in keys)
    def reason(key, metric_key):
        value = values.get(key)
        metric_value = values.get(metric_key)
        if metric_value is not None and _report_number(metric_value) == '請查看進階診斷':
            text = '指標值無法辨識，請查看進階診斷'
        else:
            text = '不適用（已定義）' if value is None and metric_value is not None else _report_text(value)
        return f'{RESULT_LABELS[key]}：{text}'
    lines = [
        fields('net_pnl', 'return'), fields('initial_cash', 'final_equity'),
        fields('max_drawdown', 'max_drawdown_pct'), fields('total_costs', 'slippage_cost'),
        fields('realized_gross_pnl', 'unrealized_pnl'),
        fields('fill_count', 'closed_lots', 'open_position'),
        fields('trade_count', 'win_rate'), reason('win_rate_reason', 'win_rate'),
        '', fields('profit_factor'), reason('profit_factor_reason', 'profit_factor'),
        '獲利因子計算基礎：' + _report_text(values.get('profit_factor_basis')),
        '', fields('sharpe'), reason('sharpe_reason', 'sharpe'),
        fields('sharpe_observations', 'sharpe_sample_count'),
    ]
    assumptions = values.get('annualization')
    if isinstance(assumptions, dict):
        for keys in (('periods_per_year', 'annual_risk_free_rate', 'minimum_observations'),
                     ('return_frequency',), ('first_return',), ('missing_dates', 'standard_deviation')):
            lines.append('　｜　'.join(RESULT_LABELS[key] + '：' +
                (_report_number(assumptions.get(key)) if key in ('periods_per_year', 'annual_risk_free_rate', 'minimum_observations')
                 else _report_text(assumptions.get(key))) for key in keys))
    else:
        lines.append('年化假設：未提供，請查看進階診斷')
    lines.extend(('夏普值限制：' + _report_text(values.get('sharpe_note')),
                  '逐日報酬、未平倉批次、結算／轉倉紀錄及完整識別碼，請展開本頁進階診斷。'))
    return '\n'.join(lines)


class BacktestSummaryCard(SummaryCard):
    """A report-only view; other summary cards retain their original contract."""
    def set_values(self, values):
        self.label.setText(backtest_summary_text(values))


_FILL_REASONS = {
    'target_open': '目標部位進場', 'target_close': '目標部位平倉',
    'gap_stop': '跳空觸及停損', 'gap_target': '跳空觸及停利',
    'stop': '觸及停損', 'target': '觸及停利',
    'maintenance_liquidation': '維持保證金不足平倉',
    'roll_close': '轉倉平舊約', 'roll_open': '轉倉開新約',
    'final_settlement': '到期結算',
}


class BacktestFillsTable(ResultTable):
    """Readable fills first; exact IDs remain in cell tooltips and diagnostics."""
    _columns = ('timestamp', 'contract_id', 'side', 'quantity', 'price', 'commission', 'tax', 'reason')
    _labels = ('成交時間（UTC）', '實際合約', '方向', '數量（口）', '價格（點）', '手續費（TWD）', '交易稅（TWD）', '成交原因')

    def set_rows(self, rows, columns=None):
        from datetime import datetime, timezone
        display = []
        for row in rows:
            shown = {key: row.get(key) for key in self._columns}
            side, reason = row.get('side'), row.get('reason')
            shown['side'] = {'buy': '買進', 'sell': '賣出'}.get(side, '未知，請核對進階診斷') if isinstance(side, str) else '未知，請核對進階診斷'
            shown['reason'] = (_FILL_REASONS.get(reason, '其他，請核對進階診斷') if isinstance(reason, str) and reason
                               else '未提供' if reason is None or reason == '' else '其他，請核對進階診斷')
            timestamp = row.get('timestamp')
            try:
                parsed = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if parsed.tzinfo is None: raise ValueError('timezone required')
                shown['timestamp'] = parsed.astimezone(timezone.utc).isoformat(sep=' ').removesuffix('+00:00')
            except (ValueError, TypeError, AttributeError):
                shown['timestamp'] = '時間未提供，請核對進階診斷'
            display.append(shown)
        super().set_rows(display, self._columns)
        self.setHorizontalHeaderLabels(self._labels)
        for index, row in enumerate(rows):
            detail = '成交識別碼：' + str(row.get('fill_id', '未提供')) + '\n委託識別碼：' + str(row.get('order_id', '未提供'))
            for column in range(self.columnCount()):
                item = self.item(index, column)
                item.setToolTip(item.text() + '\n' + detail)
        self.resizeColumnsToContents()
        for column in range(self.columnCount()): self.setColumnWidth(column, min(self.columnWidth(column), 340))


_CANDIDATE_EVALUATION_LABELS = {
    'evaluated': '已評估', 'running': '評估中', 'failed': '評估失敗',
    'cancelled': '已取消', 'timed_out': '已逾時', 'budget_exhausted': '額度已用盡',
    'not_accessed': '尚未取用', 'not_evaluated': '尚未評估',
}


def candidate_summary_text(values):
    """Bounded view of saved split records; never recalculate qualification."""
    def eligibility(value):
        return '通過' if value is True else '未通過' if value is False else '未提供'
    def metric(metrics, key):
        value = metrics.get(key)
        if value is None:
            return '未定義' if key in metrics and key in ('profit_factor', 'sharpe') else '未提供'
        return _report_number(value)
    def reason(metrics, key):
        value, explanation = metrics.get(key), metrics.get(key+'_reason')
        if value is not None and _report_number(value) == '請查看進階診斷':
            return '指標值無法辨識，請查看進階診斷'
        return '不適用（已定義）' if explanation is None and value is not None else _report_text(explanation)
    name = values.get('策略')
    if not isinstance(name, str): name = '未提供'
    elif re.fullmatch('[0-9a-fA-F]{64}', name): name = '識別碼 ' + name[:12] + '（完整名稱見進階診斷）'
    else: name = ' '.join(name.split())[:80] + ('…（完整名稱見進階診斷）' if len(name) > 80 else '')
    lines = ['候選策略：' + name,
             '已保存研究的紙上門檻：' + eligibility(values.get('紙上資格')),
             '資格僅供研究／紙上；合成資料與固定生成器結果不代表投資或真實模型績效驗證。']
    evaluations = values.get('樣本外與保留集')
    evaluations = evaluations if isinstance(evaluations, dict) else {}
    for split, title in (('oos', '樣本外 OOS'), ('holdout', '最終保留集')):
        saved = evaluations.get(split); saved = saved if isinstance(saved, dict) else {}
        row = saved.get('evaluation'); row = row if isinstance(row, dict) else {}
        state = row.get('status')
        status = ('尚無已保存評估' if not row else '未提供' if state is None else
                  _CANDIDATE_EVALUATION_LABELS.get(state, '未知狀態，請查看進階診斷') if isinstance(state, str) else
                  '未知狀態，請查看進階診斷')
        metrics = row.get('metrics'); metrics = metrics if isinstance(metrics, dict) else {}
        headline = ['net_pnl'] + (['max_drawdown'] if 'max_drawdown' in metrics else []) + ['max_drawdown_pct']
        headline.append('closed_trades' if 'trade_count' not in metrics and 'closed_trades' in metrics else 'trade_count')
        lines.extend(('', f'{title}｜狀態：{status}｜門檻檢查：{eligibility(saved.get("qualified"))}',
                      '　｜　'.join(RESULT_LABELS[key]+'：'+metric(metrics,key) for key in headline)))
        for key in ('profit_factor', 'sharpe'):
            lines.append(RESULT_LABELS[key]+'：'+metric(metrics,key))
            if key in metrics or key+'_reason' in metrics:
                lines.append(RESULT_LABELS[key+'_reason']+'：'+reason(metrics,key))
            if key == 'profit_factor' and key in metrics:
                lines.append('獲利因子計算基礎：'+_report_text(metrics.get('profit_factor_basis')))
        if 'sharpe' in metrics:
            lines.append('　｜　'.join(RESULT_LABELS[key]+'：'+_report_number(metrics.get(key))
                                    for key in ('sharpe_observations','sharpe_sample_count')))
            assumptions = metrics.get('annualization')
            if isinstance(assumptions, dict):
                lines.append('　｜　'.join(RESULT_LABELS[key]+'：'+_report_number(assumptions.get(key))
                                        for key in ('periods_per_year','annual_risk_free_rate','minimum_observations')))
                lines.append('；'.join(RESULT_LABELS[key]+'：'+_report_text(assumptions.get(key))
                                      for key in ('return_frequency','first_return','missing_dates','standard_deviation')))
            else: lines.append('年化假設：未提供，請查看進階診斷')
            lines.append('夏普值限制：'+_report_text(metrics.get('sharpe_note')))
    lines.append('\n完整評估、來源、設定、警告與識別碼，請展開本頁進階診斷；此處不補算缺少的指標。')
    return '\n'.join(lines)


class CandidateSummaryCard(SummaryCard):
    """Only the generated-candidate pane; qualification stays host-owned."""
    def set_values(self, values):
        self.label.setText(candidate_summary_text(values))

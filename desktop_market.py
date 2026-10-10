"""Read-only market dashboard. Host owns fetching, persistence and trading state.

No network, timers, broker imports or embedded observations. refresh_requested is
an intent only; host must perform its existing consent/background-job workflow.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,
    QPushButton,QLineEdit,QComboBox,QListWidget,QListWidgetItem,QSplitter,
    QGroupBox,QCheckBox,QSpinBox,QDoubleSpinBox,QScrollArea,QTabWidget,
    QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QPlainTextEdit)
from quantlab.market import MarketSeries, QuoteSnapshot, MarketValidationError
from quantlab.chart_data import TIMEFRAMES, aggregate_bars
from quantlab import indicators
from desktop_charts import CandlestickChart

DEFAULT_INDICATORS = {
    'MA': {'enabled': True, 'periods': [5,10,20,60]},
    'EMA': {'enabled': False, 'period': 20},
    'RSI': {'enabled': False, 'period': 14},
    'MACD': {'enabled': False, 'fast':12, 'slow':26, 'signal':9},
    'KD': {'enabled': False, 'period':9, 'k_period':3, 'd_period':3},
    'Bollinger': {'enabled':False, 'period':20, 'deviations':2},
    'VWAP': {'enabled':False},
}
DARK_STYLE = '''
QWidget#market_dashboard { background:#101720; color:#dbe4ef; }
QWidget#market_dashboard QWidget { background:#101720; color:#dbe4ef; }
QWidget#market_dashboard QLabel { color:#dbe4ef; }
QWidget#market_dashboard QGroupBox { border:1px solid #354459; border-radius:6px; margin-top:10px; padding:9px; font-weight:600; color:#dbe4ef; }
QWidget#market_dashboard QGroupBox::title { subcontrol-origin:margin; left:10px; }
QWidget#market_dashboard QLineEdit, QWidget#market_dashboard QComboBox, QWidget#market_dashboard QSpinBox, QWidget#market_dashboard QDoubleSpinBox, QWidget#market_dashboard QListWidget, QWidget#market_dashboard QTableWidget { background:#172230; color:#e8edf4; border:1px solid #43566c; border-radius:3px; padding:4px; selection-background-color:#285f89; }
QWidget#market_dashboard QPushButton { background:#24384c; color:#eaf0f7; padding:6px 9px; border:1px solid #506a82; border-radius:4px; }
QWidget#market_dashboard QPushButton:focus, QWidget#market_dashboard QComboBox:focus, QWidget#market_dashboard QLineEdit:focus { border:2px solid #7cb9ed; }
QWidget#market_dashboard QCheckBox { color:#e0e8f3; }
QWidget#market_dashboard QHeaderView::section { background:#243448; color:#e0e8f3; padding:5px; border:0; }
QWidget#market_dashboard QTabBar::tab { background:#243448; color:#e0e8f3; padding:7px; }
QWidget#market_dashboard QTabBar::tab:selected { background:#366487; }
'''


def _identity(value):
    return isinstance(value,str) and (value=='TWSE:TAIEX' or bool(re.fullmatch(r'TAIFEX:(?:TX|MTX|TMF):\d{4}(?:0[1-9]|1[0-2])(?:W[1-5])?',value)))


def _friendly_contract(key):
    if key=='TWSE:TAIEX': return '加權指數'
    parts=key.split(':')
    if len(parts)!=3: return key
    product={'TX':'臺指期','MTX':'小臺指','TMF':'微臺指'}.get(parts[1],parts[1])
    expiry=parts[2]; month=expiry[:4]+'/'+expiry[4:6]
    if len(expiry)>6: month+=' 第'+expiry[-1]+'週'
    return product+' '+month


def _friendly_source(instrument):
    return '臺灣證券交易所' if instrument.exchange=='TWSE' else '臺灣期貨交易所'


def _label(text, name):
    widget=QLabel(text); widget.setObjectName(name); widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def _named(widget,name,label):
    widget.setObjectName(name); widget.setAccessibleName(label)
    return widget


class MarketDashboard(QWidget):
    refresh_requested=Signal()
    selection_changed=Signal(str)
    series_rendered=Signal(str)
    preferences_changed=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('market_dashboard'); self.setStyleSheet(DARK_STYLE)
        self._series={}; self._quote_series=None; self._quote_stale=False; self._watch=[]; self._watch_initialized=False; self._selected=''; self._timeframe='1d'
        self._indicator_config=deepcopy(DEFAULT_INDICATORS); self._restoring=False
        self._stale=False; self._error=''; self._indicator_widgets={}
        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0)
        self.page_scroll=QScrollArea(); self.page_scroll.setWidgetResizable(True); self.page_scroll.setObjectName('market_page_scroll')
        content=QWidget(); self.page_scroll.setWidget(content); outer.addWidget(self.page_scroll)
        root=QVBoxLayout(content); root.setContentsMargins(10,8,10,8)
        header=QHBoxLayout(); title=_label('市場總覽','market_title')
        title.setStyleSheet('font-size:20px;font-weight:700;'); header.addWidget(title)
        header.addStretch(); header.addWidget(_label('唯讀行情 · 實單停用','market_safety'))
        self.refresh_button=_named(QPushButton('更新官方資料'),'market_refresh','更新官方資料')
        self.refresh_button.setToolTip('交由主程式確認網路同意並在背景更新；不啟動交易')
        self.refresh_button.clicked.connect(self.refresh_requested.emit); header.addWidget(self.refresh_button)
        root.addLayout(header)
        cards=QHBoxLayout(); self.cards={}
        for key,title in [('TAIEX','加權指數'),('TX','臺指期 TX'),('MXF','小臺指 MXF / MTX'),('TMF','微臺指 TMF')]:
            group=QGroupBox(title); group.setStyleSheet('QGroupBox { padding:3px; }'); layout=QVBoxLayout(group); layout.setContentsMargins(8,8,8,6)
            value=_label('尚無可用資料\n—','market_card_'+key); layout.addWidget(value)
            cards.addWidget(group); self.cards[key]=value
        root.addLayout(cards)
        self.source_status=_label('離線 · 尚未載入來源；沒有即時行情連線','market_source_status')
        source_row=QHBoxLayout(); source_row.addWidget(self.source_status,1)
        self.diagnostics_button=_named(QPushButton('資料來源與診斷 ▸'),'market_diagnostics_toggle','展開資料來源與診斷')
        self.diagnostics_button.setCheckable(True); source_row.addWidget(self.diagnostics_button); root.addLayout(source_row)
        self.diagnostics=_named(QPlainTextEdit(),'market_diagnostics','完整資料來源與診斷'); self.diagnostics.setReadOnly(True); self.diagnostics.setMaximumHeight(160); self.diagnostics.hide()
        self.diagnostics_button.toggled.connect(self._toggle_diagnostics); root.addWidget(self.diagnostics)
        self.message=_label('選擇實際合約後查看資料。TX／MXF 僅為市場展示，交易研究仍限已驗證 TMF。','market_message')
        self.message.setStyleSheet('color:#e8c37a;'); root.addWidget(self.message)
        self.main_splitter=QSplitter(Qt.Orientation.Horizontal); root.addWidget(self.main_splitter,1)
        left=QWidget(); left_layout=QVBoxLayout(left); left_layout.setContentsMargins(0,0,4,0)
        left_layout.addWidget(_label('商品搜尋 / 自選','market_watch_title'))
        self.search=_named(QLineEdit(),'market_search','搜尋商品或合約月份'); self.search.setPlaceholderText('代碼 / 月份，例如 TMF 202610')
        self.search.textChanged.connect(self._filter_catalog); left_layout.addWidget(self.search)
        self.catalog_combo=_named(QComboBox(),'market_catalog','可用實際合約'); left_layout.addWidget(self.catalog_combo)
        self.add_button=_named(QPushButton('＋ 加入自選'),'market_add','加入自選'); self.add_button.clicked.connect(self._add_watch); left_layout.addWidget(self.add_button)
        self.watchlist=_named(QListWidget(),'market_watchlist','自選商品'); self.watchlist.currentItemChanged.connect(self._watch_selected); left_layout.addWidget(self.watchlist,1)
        row=QHBoxLayout()
        self.remove_button=_named(QPushButton('移除'),'market_remove','移除自選'); self.remove_button.clicked.connect(self._remove_watch); row.addWidget(self.remove_button)
        for text,delta,name in [('↑',-1,'up'),('↓',1,'down')]:
            button=_named(QPushButton(text),'market_watch_'+name,'自選往上移' if delta<0 else '自選往下移'); button.clicked.connect(lambda checked=False,d=delta:self._move_watch(d)); row.addWidget(button)
        left_layout.addLayout(row); self.main_splitter.addWidget(left)
        center=QWidget(); center_layout=QVBoxLayout(center); center_layout.setContentsMargins(4,0,4,0)
        control=QHBoxLayout()
        self.contract_combo=_named(QComboBox(),'market_contract','圖表實際商品合約'); self.contract_combo.currentIndexChanged.connect(self._contract_changed); control.addWidget(self.contract_combo,1)
        self.timeframe_combo=_named(QComboBox(),'market_timeframe','K線週期')
        for text,value in zip(('1 分','3 分','5 分','15 分','30 分','60 分','日','週'),TIMEFRAMES): self.timeframe_combo.addItem(text,value)
        self.timeframe_combo.setCurrentIndex(6); self.timeframe_combo.currentIndexChanged.connect(self._timeframe_changed); control.addWidget(self.timeframe_combo)
        center_layout.addLayout(control)
        self.chart=CandlestickChart(); self.chart.setObjectName('market_candles'); center_layout.addWidget(self.chart,1)
        self.indicator_summary=_label('MA 5 / 10 / 20 / 60 · 未成熟指標不補零','market_indicator_summary'); center_layout.addWidget(self.indicator_summary)
        self.main_splitter.addWidget(center)
        right_scroll=QScrollArea(); right_scroll.setWidgetResizable(True); right_scroll.setMinimumWidth(175)
        right=QWidget(); right_layout=QVBoxLayout(right); self.trading_labels={}
        state=QGroupBox('策略 / 紙上 / 風控'); state_layout=QVBoxLayout(state)
        for key,title in [('strategy','策略'),('paper','紙上交易'),('risk','風控')]:
            label=_label(title+'：未知（主程式未提供）','market_state_'+key); state_layout.addWidget(label); self.trading_labels[key]=label
        state_layout.addWidget(_label('實單：停用','market_live_disabled')); right_layout.addWidget(state)
        group=QGroupBox('技術指標 · 參數按 bar 數'); grid=QGridLayout(group)
        row=0
        for key,config in DEFAULT_INDICATORS.items():
            check=_named(QCheckBox(key),'market_indicator_'+key,key+' 指標'); check.setChecked(config['enabled']); grid.addWidget(check,row,0,1,2); row+=1
            controls={}; self._indicator_widgets[key]=(check,controls)
            for param,value in config.items():
                if param=='enabled': continue
                values=value if isinstance(value,list) else [value]
                for index,number in enumerate(values):
                    spin=QDoubleSpinBox() if param=='deviations' else QSpinBox()
                    spin.setRange(.1 if param=='deviations' else 1,1000); spin.setValue(number)
                    field=f'{param}_{index}' if isinstance(value,list) else param
                    _named(spin,f'market_{key}_{field}',f'{key} {field}')
                    grid.addWidget(_label(('均線 '+str(index+1)) if param=='periods' else {'period':'期數','fast':'快線','slow':'慢線','signal':'訊號','k_period':'K 平滑','d_period':'D 平滑','deviations':'標準差倍數'}[param],'label_'+key+field),row,0); grid.addWidget(spin,row,1); row+=1
                    controls[field]=spin; spin.valueChanged.connect(self._indicators_changed)
            check.toggled.connect(self._indicators_changed)
        right_layout.addWidget(group); right_layout.addWidget(_label('VWAP 為 OHLCV 典型價加權估計；每個交易時段重設。','market_vwap_disclosure')); right_layout.addStretch()
        right_scroll.setWidget(right); self.main_splitter.addWidget(right_scroll)
        self.main_splitter.setSizes([190,740,230]); self.main_splitter.setCollapsible(1,False)
        self.tables=QTabWidget(); self.tables.setMaximumHeight(180); self.tables.setMinimumHeight(95)
        self.positions_table=self._table(('合約','口數','均價'),'market_positions')
        self.orders_table=self._table(('委託編號','合約','方向','口數','狀態'),'market_orders')
        self.fills_table=self._table(('成交編號','合約','方向','口數','成交價'),'market_fills')
        for title,table in [('持倉（主程式資料）',self.positions_table),('委託（主程式資料）',self.orders_table),('成交（主程式資料）',self.fills_table)]: self.tables.addTab(table,title)
        root.addWidget(self.tables)

    def _toggle_diagnostics(self,visible):
        self.diagnostics.setVisible(visible)
        self.diagnostics_button.setText('資料來源與診斷 ▾' if visible else '資料來源與診斷 ▸')

    def _table(self,headers,name):
        table=_named(QTableWidget(0,len(headers)),name,name)
        table.setHorizontalHeaderLabels(headers); table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setAlternatingRowColors(False); return table

    def set_market_series(self,series, *, stale=False,error=''):
        """Replace a validated snapshot atomically; called by host on GUI thread."""
        items=(series,) if isinstance(series,MarketSeries) else tuple(series)
        if any(not isinstance(item,MarketSeries) for item in items) or len(items)>1000 or type(stale) is not bool or not isinstance(error,str): raise ValueError('invalid market snapshot')
        ids=[item.instrument.contract_id for item in items]
        if len(ids)!=len(set(ids)): raise ValueError('duplicate contract')
        self._series=dict(zip(ids,items)); self._stale=stale; self._error=error[:1000]
        if not self._selected and ids: self._selected=ids[0]
        if not self._watch_initialized and ids:
            self._watch=[self._selected] if self._selected in ids else [ids[0]]; self._watch_initialized=True
        self._fill_contracts(); self._filter_catalog(); self._render_watch(); self._render_cards(); self._render_chart()

    def set_quote_series(self,series, *, stale=False):
        """Set independent card observations; historical chart selection is untouched.

        The host supplies its latest verified snapshot. An empty tuple clears cards
        rather than falling back to an older research chart. No reference prices
        are invented and explicit contract identity remains mandatory.
        """
        items=(series,) if isinstance(series,MarketSeries) else tuple(series)
        if any(not isinstance(item,MarketSeries) for item in items) or len(items)>1000 or type(stale) is not bool:
            raise ValueError('invalid market-card snapshot')
        ids=[item.instrument.contract_id for item in items]
        if len(ids)!=len(set(ids)): raise ValueError('duplicate market-card contract')
        self._quote_series=dict(zip(ids,items)); self._quote_stale=stale
        self._render_cards()

    def selected_series(self):
        """Immutable source snapshot for host provenance checks, or None."""
        return self._series.get(self._selected)

    def set_loading(self,loading):
        if type(loading) is not bool: raise ValueError('loading must be boolean')
        self.refresh_button.setEnabled(not loading)
        self.refresh_button.setText('背景更新中…' if loading else '更新官方資料')

    def _fill_contracts(self):
        self.contract_combo.blockSignals(True); self.contract_combo.clear()
        for key,item in self._series.items(): self.contract_combo.addItem(_friendly_contract(key),key)
        self.contract_combo.setCurrentIndex(self.contract_combo.findData(self._selected)); self.contract_combo.blockSignals(False)

    def _filter_catalog(self):
        terms=self.search.text().upper().split(); self.catalog_combo.clear()
        for key,item in self._series.items():
            label=_friendly_contract(key)
            searchable=f'{label} {item.instrument.symbol} {key}'
            if all(term in searchable.upper() for term in terms): self.catalog_combo.addItem(label,key)
        self.add_button.setEnabled(self.catalog_combo.count()>0)

    def _render_watch(self):
        self.watchlist.blockSignals(True); self.watchlist.clear()
        for key in self._watch:
            text=_friendly_contract(key)+(' · 無資料' if key not in self._series else '')
            item=QListWidgetItem(text); item.setToolTip(key); item.setData(Qt.ItemDataRole.UserRole,key); self.watchlist.addItem(item)
            if key==self._selected: self.watchlist.setCurrentItem(item)
        self.watchlist.blockSignals(False)

    def _add_watch(self):
        key=self.catalog_combo.currentData()
        if key and key not in self._watch and len(self._watch)<100:
            self._watch.append(key); self._render_watch(); self.preferences_changed.emit()

    def _remove_watch(self):
        row=self.watchlist.currentRow()
        if row>=0: self._watch.pop(row); self._render_watch(); self.preferences_changed.emit()

    def _move_watch(self,delta):
        row=self.watchlist.currentRow(); target=row+delta
        if 0<=row<len(self._watch) and 0<=target<len(self._watch):
            self._watch[row],self._watch[target]=self._watch[target],self._watch[row]
            self._render_watch(); self.watchlist.setCurrentRow(target); self.preferences_changed.emit()

    def _watch_selected(self,item,previous):
        if item:
            key=item.data(Qt.ItemDataRole.UserRole)
            if key in self._series: self.contract_combo.setCurrentIndex(self.contract_combo.findData(key))
            else: self.message.setText('此自選合約目前沒有資料；保留原有自選，不替換為其他月份。')

    def _contract_changed(self,index):
        key=self.contract_combo.itemData(index)
        if key:
            self._selected=key; self._render_chart(); self._render_cards(); self.selection_changed.emit(key); self.preferences_changed.emit()

    def _timeframe_changed(self,index):
        value=self.timeframe_combo.itemData(index)
        current=self._series.get(self._selected)
        if current and value.endswith('m') and any(not bar.interval.endswith('m') for bar in current.bars):
            self.timeframe_combo.blockSignals(True); self.timeframe_combo.setCurrentIndex(self.timeframe_combo.findData(self._timeframe)); self.timeframe_combo.blockSignals(False)
            self.message.setText('日／時段資料不能轉成分鐘 K 線；需匯入具有明示時段的真實分鐘資料。'); return
        self._timeframe=value; self._render_chart(); self.preferences_changed.emit()

    def _render_cards(self):
        sources=self._series if self._quote_series is None else self._quote_series
        stale=self._stale if self._quote_series is None else self._quote_stale
        for symbol,label in self.cards.items():
            choices=[x for x in sources.values() if x.instrument.symbol==symbol]
            item=next((x for x in choices if x.instrument.contract_id==self._selected),choices[0] if choices else None)
            if not item:
                label.setText('尚無可用資料\n—'); label.setStyleSheet('color:#dbe4ef;'); label.setToolTip(''); continue
            quote=QuoteSnapshot.from_series(item,stale=stale)
            change=quote.change; delta='前收不足' if change is None else f'{change:+f}'
            label.setText(f'{_friendly_contract(item.instrument.contract_id)}\n{quote.last:,.2f}  {delta}\n{quote.trade_date} · '+('過期快取' if stale else '歷史／盤後資料'))
            label.setToolTip(f'實際合約：{item.instrument.contract_id}；顯示代碼 {item.instrument.symbol}\n漲跌參照：前一筆日盤收盤；不是結算價差\n來源：{item.provenance.attribution}\n{item.provenance.source_url}\n交易所時間：{item.provenance.timestamp_basis}\n接收時間（UTC）：{quote.received_at.isoformat()}\n延遲：不適用於歷史快照；並非即時連線')
            label.setStyleSheet('color:'+('#f58b8b' if change is not None and change>0 else '#76d6b0' if change is not None and change<0 else '#dbe4ef')+';')

    def _render_chart(self):
        item=self._series.get(self._selected)
        if item is None:
            self.chart.set_series(()); self._display_bars=()
            self.source_status.setText('離線 · 尚未載入來源；沒有即時行情連線'+(' · '+self._error if self._error else '')); return
        provenance=item.provenance
        # This dashboard consumes historical bar snapshots, never a streaming quote entitlement.
        status='過期快取' if self._stale else '歷史資料' if provenance.mode=='history' else '盤後資料' if provenance.mode=='eod' else '歷史快照（非即時連線）'
        self.source_status.setText(f'圖表：{_friendly_source(item.instrument)}｜{status}｜資料日 {provenance.as_of}｜本機接收 {provenance.received_at:%m/%d %H:%M} UTC')
        try:
            result=aggregate_bars(item.bars,timeframe=self._timeframe)
        except (ValueError,TypeError) as exc:
            self.chart.set_series(()); self._display_bars=(); self.message.setText('無法顯示此週期：'+str(exc)); return
        self._display_bars=result.bars
        self.chart.set_series(result.bars,source_label=_friendly_contract(item.instrument.contract_id)+' · '+_friendly_source(item.instrument),status_label=status)
        warnings=list(provenance.warnings)+list(result.warnings)
        if any(bar.partial for bar in result.bars): warnings.insert(0,'含未完成或完整性未知 K 線')
        if self._error: warnings.insert(0,self._error)
        details=(f'實際合約：{item.instrument.contract_id}；顯示代碼：{item.instrument.symbol}\n'
                 f'資料來源：{provenance.attribution}\n來源網址：{provenance.source_url}\n'
                 f'授權網址：{provenance.license_url}\n來源 SHA-256：{provenance.sha256}\n'
                 f'交易所時間基準：{provenance.timestamp_basis}\n'
                 f'接收時間（UTC）：{provenance.received_at.isoformat()}\n'
                 f'省略來源列數：{provenance.omitted_rows}\n'
                 '漲跌參照：前一筆日盤收盤，並非結算價差。\n'
                 '延遲：不適用於歷史快照；沒有即時行情連線。\n'+ '\n'.join(warnings))
        self.diagnostics.setPlainText(details); self.source_status.setToolTip(details)
        self.message.setToolTip('\n'.join(warnings))
        message='部分區間完整性尚未確認，僅供行情查看。' if warnings else '唯讀行情；歷史資料不代表即時報價。'
        if self._error: message='來源更新失敗，顯示既有資料。'+message
        self.message.setText(message)
        self._apply_indicators()
        self.series_rendered.emit(self._selected)

    def _indicators_changed(self,*args):
        if self._restoring: return
        config={}
        for key,(check,controls) in self._indicator_widgets.items():
            value={'enabled':check.isChecked()}
            if key=='MA': value['periods']=[controls[f'periods_{i}'].value() for i in range(4)]
            else: value.update({name:spin.value() for name,spin in controls.items()})
            config[key]=value
        if config['MACD']['fast']>=config['MACD']['slow']:
            self.message.setText('MACD 快線期數必須小於慢線；保留上一組有效參數。'); return
        self._indicator_config=config; self._apply_indicators(); self.preferences_changed.emit()

    def _apply_indicators(self):
        bars=getattr(self,'_display_bars',()); closes=[]; highs=[]; lows=[]; keep=[]
        for index,bar in enumerate(bars):
            previous=bars[index-1] if index else None
            if previous is not None and bar.interval.endswith('m') and (bar.trade_date,bar.session,bar.session_open)==(previous.trade_date,previous.session,previous.session_open) and bar.timestamp>previous.end:
                closes.append(None); highs.append(None); lows.append(None)
            keep.append(len(closes)); closes.append(bar.close); highs.append(bar.high); lows.append(bar.low)
        overlays={}; panels={}; names=[]
        for key,options in self._indicator_config.items():
            if not options['enabled']: continue
            names.append(key); kwargs={k:v for k,v in options.items() if k!='enabled'}
            if key=='MA':
                for period in kwargs['periods']: overlays[f'MA{period}']=indicators.sma(closes,period=period)
            elif key=='EMA': overlays['EMA']=indicators.ema(closes,**kwargs)
            elif key=='RSI': panels['RSI']={'RSI':indicators.rsi(closes,**kwargs)}
            elif key=='MACD': panels['MACD']=indicators.macd(closes,**kwargs)
            elif key=='KD': panels['KD']=indicators.kd(highs,lows,closes,**kwargs)
            elif key=='Bollinger': overlays.update({'BB '+k:v for k,v in indicators.bollinger(closes,**kwargs).items()})
            elif key=='VWAP': overlays['VWAP 估計']=indicators.session_vwap(bars)
        self.indicator_summary.setText(' / '.join(names)+' · 未成熟指標顯示資料不足；未完成 K 線為暫定值')
        overlays={name:values if name=='VWAP 估計' else tuple(values[i] for i in keep) for name,values in overlays.items()}
        panes={f'{panel} {key}':tuple(values[i] for i in keep) for panel,entries in panels.items() for key,values in entries.items()}
        if 'MACD histogram' in panes:
            panes['MACD histogram 1×'] = panes.pop('MACD histogram')
        self.chart.set_overlays(overlays,panes=panes,pane_styles={'MACD histogram 1×':'histogram'} if 'MACD histogram 1×' in panes else {})

    def preferences(self):
        return {'version':1,'watchlist':list(self._watch),'selected':self._selected,'timeframe':self._timeframe,'indicators':deepcopy(self._indicator_config),'theme':'dark'}

    def restore_preferences(self,payload):
        if not isinstance(payload,dict) or set(payload)-{'version','watchlist','selected','timeframe','indicators','theme'} or type(payload.get('version')) is not int or payload.get('version')!=1: raise ValueError('unsupported preferences')
        watch=payload.get('watchlist',[]); selected=payload.get('selected',''); timeframe=payload.get('timeframe','1d'); config=deepcopy(payload.get('indicators',DEFAULT_INDICATORS))
        if not isinstance(watch,list) or len(watch)>100 or any(not _identity(x) for x in watch) or len(set(watch))!=len(watch): raise ValueError('invalid watchlist')
        if (selected and not _identity(selected)) or not isinstance(selected,str) or timeframe not in TIMEFRAMES or payload.get('theme','dark')!='dark': raise ValueError('invalid selection/theme')
        if not isinstance(config,dict) or set(config)!=set(DEFAULT_INDICATORS): raise ValueError('invalid indicators')
        for key,default in DEFAULT_INDICATORS.items():
            entry=config[key]
            if not isinstance(entry,dict) or set(entry)!=set(default) or type(entry['enabled']) is not bool: raise ValueError('invalid indicator shape')
            for param,value in entry.items():
                if param=='enabled': continue
                values=value if param=='periods' and isinstance(value,list) else [value]
                if param=='periods' and (not isinstance(value,list) or len(value)!=4): raise ValueError('four MA periods required')
                if any(type(v) not in ((int,float) if param=='deviations' else (int,)) or not (.1 if param=='deviations' else 1)<=v<=1000 for v in values): raise ValueError('invalid indicator period')
        if config['MACD']['fast']>=config['MACD']['slow']: raise ValueError('invalid MACD periods')
        self._watch=list(watch); self._watch_initialized=True; self._selected=selected; self._timeframe=timeframe; self._indicator_config=config
        self._restoring=True
        try:
            self.timeframe_combo.blockSignals(True); self.timeframe_combo.setCurrentIndex(self.timeframe_combo.findData(timeframe)); self.timeframe_combo.blockSignals(False)
            for key,(check,controls) in self._indicator_widgets.items():
                check.setChecked(config[key]['enabled'])
                for name,spin in controls.items(): spin.setValue(config[key]['periods'][int(name[-1])] if name.startswith('periods_') else config[key][name])
        finally: self._restoring=False
        self._fill_contracts(); self._render_watch(); self._render_chart()

    def set_trading_status(self, *, strategy=None,paper=None,risk=None):
        values={'strategy':strategy,'paper':paper,'risk':risk}
        if any(value is not None and (not isinstance(value,str) or len(value)>500) for value in values.values()): raise ValueError('invalid host status')
        for key,title in [('strategy','策略'),('paper','紙上交易'),('risk','風控')]: self.trading_labels[key].setText(title+'：'+(values[key] if values[key] is not None else '未知（主程式未提供）'))

    def set_account_tables(self, *, positions=(),orders=(),fills=()):
        """Validated display-only snapshots. Never produces an order or fills blanks."""
        prepared=[]
        for rows,table,columns in [(positions,self.positions_table,('contract_id','quantity','average_price')),(orders,self.orders_table,('order_id','contract_id','side','quantity','status')),(fills,self.fills_table,('fill_id','contract_id','side','quantity','price'))]:
            if not isinstance(rows,(list,tuple)) or len(rows)>10000: raise ValueError('bounded table rows required')
            output=[]
            for row in rows:
                if not isinstance(row,dict) or not _identity(row.get('contract_id')) or type(row.get('quantity')) is not int: raise ValueError('invalid host account row')
                if table is not self.positions_table and (row['quantity']<=0 or row.get('side') not in ('buy','sell')): raise ValueError('invalid direction/quantity')
                cells=[]
                for key in columns:
                    value=row.get(key)
                    if value is None: cells.append('—'); continue
                    if key in ('average_price','price'):
                        try: number=Decimal(str(value))
                        except InvalidOperation: raise ValueError('invalid price') from None
                        if not number.is_finite() or number<0: raise ValueError('invalid price')
                    if not isinstance(value,(str,int,float,Decimal)) or isinstance(value,bool) or len(str(value))>500: raise ValueError('invalid display value')
                    cells.append(str(value))
                output.append(cells)
            prepared.append((table,output))
        for table,rows in prepared:
            table.setRowCount(len(rows))
            for r,cells in enumerate(rows):
                for c,value in enumerate(cells): table.setItem(r,c,QTableWidgetItem(value))

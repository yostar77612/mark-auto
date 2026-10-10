"""Bounded native read-only OHLCV chart. Host owns data, aggregation and indicators.

No network, trading, indicator calculation or inferred execution. All indices refer
exactly to the supplied immutable series. Changing series clears dependent layers.
"""
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
import math
import re
from types import MappingProxyType
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


def _display_time(value, date_only=''):
    """Presentation only; no timezone inference for unverified naive values."""
    if value is None: return date_only or '時間未提供／未驗證'
    if isinstance(value,str):
        try: value=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError: return '時間未提供／未驗證'
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        return '時間未提供／未驗證'
    return value.astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y/%m/%d %H:%M')+' 台北時間'


@dataclass(frozen=True)
class ChartTrace:
    contract_id: str
    data_hash: str
    strategy_hash: str
    mode: str

    def __post_init__(self):
        if not self.contract_id or self.mode not in ('回測','紙上'):
            raise ValueError('圖層須指定合約與回測／紙上模式')
        if any(not re.fullmatch('[0-9a-f]{64}',x) for x in (self.data_hash,self.strategy_hash)):
            raise ValueError('圖層須指定資料與策略 SHA-256')


def _number(value):
    if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):
        raise ValueError('價格與指標必須為有限數值')
    return float(value)


@dataclass(frozen=True)
class ChartMarker:
    index: int
    kind: str
    label: str
    price: Decimal | None = None
    quantity: int | None = None
    cost: Decimal | None = None
    reason: str = ''
    timestamp: object = None
    target_position: int | None = None

    def __post_init__(self):
        if type(self.index) is not int or self.index<0 or self.kind not in ('signal','fill'):
            raise ValueError('無效圖層位置或種類')
        if not self.label: raise ValueError('圖層須有方向／動作文字')
        if self.target_position is not None and type(self.target_position) is not int: raise ValueError('訊號目標須為整數')
        if self.kind=='signal' and self.price is not None: raise ValueError('訊號不可帶有偽造成交價')
        if self.kind=='fill' and (self.price is None or type(self.quantity) is not int or self.quantity<=0):
            raise ValueError('成交必須有實際價與量')
        for value in (self.price,self.cost):
            if value is not None: _number(value)
        if self.cost is not None and self.cost<0: raise ValueError('成本不可負值')


@dataclass(frozen=True)
class ReferenceLine:
    label: str
    price: Decimal

    def __post_init__(self):
        if not self.label: raise ValueError('參考線須標明意義')
        _number(self.price)


class CandlestickChart(QWidget):
    """Wheel zoom / left-drag pan / hover OHLC; arrows pan, +/- zoom, Home reset.

    set_series accepts MarketSeries or sequence of MarketBar. Optional ChartTrace
    binds signal/fill layers to host-verified contract/data/strategy. The host must
    map event timestamps to containing bars (not nearest guessed market prices).
    set_timeframe only emits a host request; it never relabels or resamples bars.
    """
    crosshair_changed=Signal(object)
    timeframe_changed=Signal(str)
    timeframes=('1m','3m','5m','15m','30m','60m','1d','1w')
    MAX_VISIBLE=600
    UP=QColor('#ff6575'); DOWN=QColor('#35cf9b'); TEXT=QColor('#d7e1ee')
    COLORS=('#f8cd68','#6aa9ff','#bd9bff','#64d9df','#f099d1')

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMouseTracking(True); self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(360,280)
        self.setAccessibleName('唯讀 K 線、成交量與指標圖')
        self.bars=(); self.trace=None; self.overlays=MappingProxyType({}); self.panes=MappingProxyType({})
        self._unavailable_overlays=set(); self._unavailable_panes=set(); self.pane_styles={}; self.markers=(); self.reference_lines=(); self.layer_visibility={'signal':True,'fill':True}
        self.source_label='尚無可用資料'; self.status_label=''; self.error=''
        self.timeframe='1d'; self.crosshair_index=None; self._count=100; self._start=0; self._drag=None
        self.last_rendered_bar_count=0

    @property
    def price_rect(self):
        lower=0.55 if self.panes else 0.71
        return QRectF(12,86,max(40,self.width()-102),max(50,self.height()*lower-86))

    @property
    def visible_range(self): return self._start,min(len(self.bars),self._start+self._count)

    def set_series(self,series,*,trace=None,source_label='',status_label=''):
        bars=tuple(getattr(series,'bars',series))
        if len(bars)>100000: raise ValueError('最多 100,000 根資料')
        contracts={b.contract_id for b in bars}
        if len(contracts)>1 or (trace and contracts and contracts!={trace.contract_id}): raise ValueError('資料合約錯配')
        if len({getattr(b,'interval',None) for b in bars})>1: raise ValueError('不可混用 K 線週期')
        for b in bars:
            o,h,l,c=map(_number,(b.open,b.high,b.low,b.close))
            if not l<=min(o,c)<=max(o,c)<=h: raise ValueError('OHLC 不合法')
            if b.volume is not None and (type(b.volume) is not int or b.volume<0): raise ValueError('成交量不合法')
        self.bars=bars; self.trace=trace
        provenance=getattr(series,'provenance',None)
        self.source_label=source_label or (f'{provenance.attribution}｜{provenance.as_of}' if provenance else '來源由主程式提供')
        self.status_label=status_label or (provenance.mode if provenance else '狀態未提供')
        self.overlays=MappingProxyType({}); self.panes=MappingProxyType({}); self.markers=(); self.reference_lines=()
        self._unavailable_overlays=set(); self._unavailable_panes=set(); self.pane_styles={}; self._marker_index={}; self.crosshair_index=None; self.error=''; self.reset_view()

    def reset_view(self):
        self._count=min(self.MAX_VISIBLE,100); self._start=max(0,len(self.bars)-self._count); self.update()

    def set_error(self,message): self.error=str(message); self.update()

    def set_timeframe(self,timeframe):
        if timeframe not in self.timeframes: raise ValueError('不支援週期')
        if timeframe!=self.timeframe:
            self.timeframe=timeframe; self.timeframe_changed.emit(timeframe)

    def set_overlays(self,values,*,panes=None,pane_styles=None):
        def checked(mapping):
            result={}
            for label,sequence in mapping.items():
                sequence=tuple(sequence)
                if not label or len(sequence)!=len(self.bars): raise ValueError('指標須具名稱且與資料等長')
                for v in sequence:
                    if v is not None: _number(v)
                result[str(label)]=sequence
            return MappingProxyType(result)
        overlays=checked(values); extra=checked(panes or {})
        if len(overlays)>16 or len(extra)>8: raise ValueError('指標數量超過繪圖上限')
        styles=dict(pane_styles or {})
        if any(label not in extra or style not in ('line','histogram') for label,style in styles.items()): raise ValueError('副圖樣式不合法')
        self.overlays=overlays; self.panes=extra; self.pane_styles=styles
        self._unavailable_overlays={label for label,seq in overlays.items() if all(v is None for v in seq)}
        self._unavailable_panes={label for label,seq in extra.items() if all(v is None for v in seq)}
        self.update()

    def _legend_label(self,label,*,pane=False):
        unavailable=self._unavailable_panes if pane else self._unavailable_overlays
        return label+' · 資料不足' if label in unavailable else label

    def set_markers(self,markers,*,trace):
        if self.trace is None or trace!=self.trace: raise ValueError('訊號／成交合約、資料或策略版本不一致')
        markers=tuple(markers)
        if len(markers)>100000 or any(not isinstance(m,ChartMarker) or m.index>=len(self.bars) for m in markers): raise ValueError('圖層超出資料範圍')
        self.markers=markers
        indexed={}
        for m in markers: indexed.setdefault(m.index,[]).append(m)
        self._marker_index=indexed; self.update()

    def set_layer_visible(self,kind,visible):
        if kind not in self.layer_visibility: raise ValueError('不支援圖層')
        self.layer_visibility[kind]=bool(visible); self.update()

    def set_reference_lines(self,lines):
        lines=tuple(lines)
        if len(lines)>16 or any(not isinstance(x,ReferenceLine) for x in lines): raise ValueError('參考線不合法')
        self.reference_lines=lines; self.update()

    def bar_details(self,index):
        b=self.bars[index]; timestamp=getattr(b,'timestamp',None)
        change=b.close-b.open
        return {'index':index,'time':_display_time(timestamp,b.trade_date),'trade_date':b.trade_date,
                'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume,
                'change_text':f'{change:+g}','partial':getattr(b,'partial',False),
                'markers':tuple(getattr(self,'_marker_index',{}).get(index,()))}

    def bar_point(self,index):
        start,end=self.visible_range; r=self.price_rect
        return QPointF(r.left()+(index-start+.5)*r.width()/max(1,end-start),r.center().y()).toPoint()

    def _pan(self,bars):
        self._start=max(0,min(max(0,len(self.bars)-self._count),self._start+bars)); self.update()

    def _zoom(self,factor,anchor=.5):
        old=self._count; new=max(10,min(self.MAX_VISIBLE,len(self.bars) or 10,round(old*factor)))
        self._start=max(0,min(max(0,len(self.bars)-new),round(self._start+(old-new)*anchor)))
        self._count=new; self.update()

    def wheelEvent(self,event):
        r=self.price_rect; anchor=max(0,min(1,(event.position().x()-r.left())/r.width()))
        self._zoom(.8 if event.angleDelta().y()>0 else 1.25,anchor); event.accept()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.setFocus(); self._drag=(event.position().x(),self._start); event.accept()

    def mouseReleaseEvent(self,event): self._drag=None; event.accept()

    def mouseMoveEvent(self,event):
        r=self.price_rect; start,end=self.visible_range
        if self._drag is not None:
            x,origin=self._drag
            self._start=max(0,min(max(0,len(self.bars)-self._count),origin-round((event.position().x()-x)/r.width()*max(1,end-start))))
        if self.bars and r.contains(event.position()):
            self.crosshair_index=min(end-1,max(start,start+int((event.position().x()-r.left())/r.width()*max(1,end-start))))
            self.crosshair_changed.emit(self.bar_details(self.crosshair_index))
        else: self.crosshair_index=None
        self.update()

    def leaveEvent(self,event): self.crosshair_index=None; self.crosshair_changed.emit(None); self.update()

    def keyPressEvent(self,event):
        key=event.key()
        if key==Qt.Key.Key_Left: self._pan(-max(1,self._count//10))
        elif key==Qt.Key.Key_Right: self._pan(max(1,self._count//10))
        elif key in (Qt.Key.Key_Plus,Qt.Key.Key_Equal): self._zoom(.8)
        elif key==Qt.Key.Key_Minus: self._zoom(1.25)
        elif key==Qt.Key.Key_Home: self.reset_view()
        else: super().keyPressEvent(event)

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#101722')); p.setPen(self.TEXT)
        def text(x,y,s): p.drawText(QPointF(x,y),str(s))
        fm=p.fontMetrics()
        text(12,22,fm.elidedText(self.source_label+'  ｜  '+self.status_label,Qt.TextElideMode.ElideRight,self.width()-24))
        text(12,43,'K 線漲 + 紅／跌 − 綠   ◇ 訊號   ▲ 成交   滾輪縮放 · 拖曳平移')
        self.last_rendered_bar_count=0
        if self.error or not self.bars:
            p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,self.error or '尚無可用資料，請選擇真實來源'); p.end(); return
        start,end=self.visible_range; visible=self.bars[start:end]; r=self.price_rect
        if not visible: p.end(); return
        self.last_rendered_bar_count=len(visible)
        idx=self.crosshair_index if self.crosshair_index is not None else end-1
        d=self.bar_details(idx)
        detail=f"{d['time']}  開 {d['open']} 高 {d['high']} 低 {d['low']} 收 {d['close']}  Δ{d['change_text']}  量 {d['volume'] if d['volume'] is not None else '未知'}"+('  未完整' if d['partial'] else '')
        text(12,65,fm.elidedText(detail,Qt.TextElideMode.ElideRight,self.width()-24))
        low=min(float(b.low) for b in visible); high=max(float(b.high) for b in visible)
        extras=[float(v) for seq in self.overlays.values() for v in seq[start:end] if v is not None]
        extras.extend(float(line.price) for line in self.reference_lines)
        marker_index=getattr(self,'_marker_index',{})
        extras.extend(float(m.price) for i in range(start,end) for m in marker_index.get(i,()) if m.kind=='fill' and self.layer_visibility['fill'])
        if extras: low=min(low,min(extras)); high=max(high,max(extras))
        pad=max((high-low)*.06,.5); low-=pad; high+=pad
        y=lambda value:r.bottom()-(float(value)-low)/(high-low)*r.height()
        step=r.width()/len(visible); x=lambda i:r.left()+(i-start+.5)*step
        p.setPen(QPen(QColor('#293547'),1))
        for tick in range(5):
            value=low+(high-low)*tick/4; yy=y(value)
            p.drawLine(QPointF(r.left(),yy),QPointF(r.right(),yy)); p.setPen(self.TEXT); text(r.right()+6,yy+4,f'{value:,.2f}'); p.setPen(QColor('#293547'))
        volume_top=r.bottom()+30; volume_bottom=self.height()*(.76 if self.panes else .91)
        volume_max=max((b.volume or 0 for b in visible),default=0) or 1
        for i,b in enumerate(visible,start):
            color=self.UP if b.close>b.open else self.DOWN if b.close<b.open else QColor('#b5c2d3')
            p.setPen(QPen(color,1)); p.setBrush(color)
            p.drawLine(QPointF(x(i),y(b.high)),QPointF(x(i),y(b.low)))
            p.drawRect(QRectF(x(i)-max(.7,step*.3),min(y(b.open),y(b.close)),max(1,step*.6),max(1,abs(y(b.open)-y(b.close)))))
            if b.volume is not None:
                vh=(volume_bottom-volume_top)*b.volume/volume_max
                p.fillRect(QRectF(x(i)-step*.3,volume_bottom-vh,max(1,step*.6),vh),color)
        p.setPen(self.TEXT); text(12,volume_top-5,'成交量（口／股，依來源）')
        self._draw_lines(p,self.overlays,start,end,x,y,r)
        legend_x=r.left()
        for j,label in enumerate(self.overlays):
            p.setPen(QColor('#8290a3') if label in self._unavailable_overlays else QColor(self.COLORS[j%len(self.COLORS)]))
            label=fm.elidedText(self._legend_label(label),Qt.TextElideMode.ElideRight,240)
            if legend_x+fm.horizontalAdvance(label)>r.right(): break
            text(legend_x,r.top()-5,label); legend_x+=fm.horizontalAdvance(label)+14
        for line in self.reference_lines:
            p.setPen(QPen(QColor('#ffcc80'),1,Qt.PenStyle.DashLine)); yy=y(line.price)
            p.drawLine(QPointF(r.left(),yy),QPointF(r.right(),yy)); text(r.left()+5,yy-4,f'{line.label} {line.price}')
        for i in range(start,end):
            for marker in marker_index.get(i,()):
                if not self.layer_visibility[marker.kind]: continue
                xx=x(i)
                if marker.kind=='signal':
                    yy=r.top()+13; points=[QPointF(xx,yy-5),QPointF(xx+5,yy),QPointF(xx,yy+5),QPointF(xx-5,yy)]
                    p.setPen(QColor('#e4b9ff')); p.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    yy=y(marker.price); points=[QPointF(xx,yy-6),QPointF(xx+5,yy+4),QPointF(xx-5,yy+4)]
                    p.setPen(QColor('#ffdb7b')); p.setBrush(QColor('#ffdb7b'))
                p.drawPolygon(QPolygonF(points))
        if self.panes:
            pane_top=volume_bottom+23; height=max(10,(self.height()*.93-pane_top)/len(self.panes))
            for j,(label,seq) in enumerate(self.panes.items()):
                area=QRectF(r.left(),pane_top+j*height,r.width(),max(8,height-15))
                values=[float(v) for v in seq[start:end] if v is not None]
                lo=min(values) if values else 0; hi=max(values) if values else 1
                histogram=self.pane_styles.get(label)=='histogram'
                if histogram: lo=min(0,lo); hi=max(0,hi)
                if hi==lo: hi+=1; lo-=1
                py=lambda v,area=area,lo=lo,hi=hi:area.bottom()-(float(v)-lo)/(hi-lo)*area.height()
                if histogram:
                    p.save(); p.setClipRect(area)
                    for i in range(start,end):
                        if seq[i] is None: continue
                        value=float(seq[i]); baseline=py(0); yy=py(value)
                        p.fillRect(QRectF(x(i)-step*.3,min(baseline,yy),max(1,step*.6),max(1,abs(baseline-yy))),self.UP if value>=0 else self.DOWN)
                    p.restore()
                else: self._draw_lines(p,{label:seq},start,end,x,py,area)
                p.setPen(QColor('#8290a3') if label in self._unavailable_panes else self.TEXT); text(area.left()+3,area.top()+10,self._legend_label(label,pane=True))
        if self.crosshair_index is not None and start<=self.crosshair_index<end:
            xx=x(self.crosshair_index); yy=y(self.bars[self.crosshair_index].close)
            p.setPen(QPen(QColor('#a5b6cc'),1,Qt.PenStyle.DashLine))
            p.drawLine(QPointF(xx,r.top()),QPointF(xx,volume_bottom)); p.drawLine(QPointF(r.left(),yy),QPointF(r.right(),yy))
            marker_text=' / '.join(f"{'訊號' if m.kind=='signal' else '成交'} {m.label} {m.reason}"+(f' 價{m.price} 量{m.quantity} 成本{m.cost if m.cost is not None else "未提供"}' if m.kind=='fill' else f' 目標{m.target_position if m.target_position is not None else "未提供"}')+(f' 時間{_display_time(m.timestamp)}' if m.timestamp is not None else ' 時間未提供') for m in marker_index.get(self.crosshair_index,()))
            self.setToolTip(detail+('\n'+marker_text if marker_text else ''))
        p.setPen(self.TEXT)
        first_time=self.bar_details(start)['time']; last_time=self.bar_details(end-1)['time']
        text(r.left(),self.height()-12,first_time); text(max(r.left(),r.right()-fm.horizontalAdvance(last_time)),self.height()-12,last_time)
        if self.trace: text(r.left()+fm.horizontalAdvance(first_time)+20,self.height()-12,f'{self.trace.mode}｜資料 {self.trace.data_hash[:8]}｜策略 {self.trace.strategy_hash[:8]}')
        p.end()

    def _draw_lines(self,p,series,start,end,x,y,clip):
        p.save(); p.setClipRect(clip)
        for j,(label,values) in enumerate(series.items()):
            p.setPen(QPen(QColor(self.COLORS[j%len(self.COLORS)]),1.4)); previous=None
            for i in range(start,end):
                value=values[i]
                if value is None: previous=None; continue
                point=QPointF(x(i),y(value))
                if previous is not None: p.drawLine(previous,point)
                previous=point
        p.restore()

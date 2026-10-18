"""Explicit, bounded official daily-data reads; never a realtime entitlement.

Parsers accept observed native exchange schemas. Invalid refreshes do not replace
last-good cache. Cached load is always marked stale pending explicit refresh.
"""
import base64
import csv
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from http.client import HTTPSConnection
import io
import json
import os
from pathlib import Path
import re
import ssl
import socket
import threading
import stat
import tempfile
import time
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request

from .market import (InstrumentRef, MarketBar, MarketSeries, SourceProvenance,
                     MarketValidationError, bar_key, utc)

TWSE_URL='https://openapi.twse.com.tw/v1/indicesReport/MI_5MINS_HIST'
TAIFEX_URL='https://openapi.taifex.com.tw/v1/DailyMarketReportFut'
TAIFEX_CSV_URL='https://www.taifex.com.tw/cht/3/futDataDown'
LICENSE_URL='https://data.gov.tw/license'
MAX_BYTES=8*1024*1024
MAX_ROWS=50000
TOTAL_TIMEOUT=30.0
_MISSING=('', '-', '--', 'NULL')
_CSV_FIELDS=('交易日期','契約','到期月份(週別)','開盤價','最高價','最低價','收盤價','漲跌價','漲跌%','成交量','結算價','未沖銷契約數','最後最佳買價','最後最佳賣價','歷史最高價','歷史最低價','是否因訊息面暫停交易','交易時段','價差對單式委託成交量')


def official_url(url):
    if url not in (TWSE_URL,TAIFEX_URL,TAIFEX_CSV_URL):
        raise MarketValidationError('only exact allowlisted official HTTPS endpoints allowed')
    return url


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise MarketValidationError('duplicate JSON key')
        result[key]=value
    return result


def _json(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES: raise MarketValidationError('invalid response byte size')
    try:
        return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=_pairs,parse_constant=lambda s: (_ for _ in ()).throw(MarketValidationError('nonfinite JSON')))
    except (UnicodeError,ValueError,RecursionError) as exc:
        raise MarketValidationError('invalid bounded JSON response') from exc


def _rows(raw):
    rows=_json(raw)
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_ROWS or any(not isinstance(r,dict) or len(r)>64 for r in rows): raise MarketValidationError('expected bounded nonempty native row array')
    for row in rows:
        if any(not isinstance(v,str) or len(v)>512 for v in row.values()): raise MarketValidationError('native fields must be bounded strings')
    return rows


def _num(text, *, optional=False):
    if not isinstance(text,str) or len(text)>40: raise MarketValidationError('invalid numeric field')
    text=text.strip()
    if optional and text in _MISSING: return None
    if not re.fullmatch(r'\d+(?:\.\d+)?',text): raise MarketValidationError('invalid decimal field')
    try: return Decimal(text)
    except InvalidOperation as exc: raise MarketValidationError('invalid decimal') from exc


def _date(text, *, roc=False):
    try:
        text=text.replace('/','')
        if not re.fullmatch(r'\d{7}' if roc else r'\d{8}',text): raise ValueError()
        year=int(text[:-4])+(1911 if roc else 0)
        return date(year,int(text[-4:-2]),int(text[-2:])).isoformat()
    except (ValueError,AttributeError) as exc: raise MarketValidationError('invalid native trade date') from exc


def _series(grouped,raw,received_at,source_url,attribution,omitted=0):
    utc(received_at)
    if not grouped: raise MarketValidationError('no supported complete OHLC rows')
    digest=hashlib.sha256(raw).hexdigest()
    warnings=('Incomplete OHLC or unsupported spread rows omitted; coverage is observed, not certified complete.',) if omitted else ()
    result=[]
    for inst,bars in sorted(grouped.items(),key=lambda item:item[0].contract_id):
        bars=tuple(sorted(bars,key=bar_key))
        prov=SourceProvenance(official_url(source_url),digest,attribution,LICENSE_URL,received_at,bars[-1].trade_date,bars[0].trade_date,bars[-1].trade_date,omitted_rows=omitted,warnings=warnings)
        result.append(MarketSeries(inst,bars,prov))
    return tuple(result)


def parse_twse_daily(raw, *, received_at):
    """TWSE MI_5MINS_HIST is daily index OHLC despite endpoint name."""
    inst=InstrumentRef('TWSE','TAIEX','TWSE:TAIEX')
    bars=[]; digest=hashlib.sha256(raw).hexdigest() if isinstance(raw,bytes) else ''
    for row in _rows(raw):
        fields=('Date','OpeningIndex','HighestIndex','LowestIndex','ClosingIndex')
        if not all(k in row for k in fields): raise MarketValidationError('unsupported TWSE schema')
        bars.append(MarketBar(inst,_date(row['Date'],roc=True),'day',*(_num(row[k]) for k in fields[1:]),None,interval='1d',source_id=digest))
    return _series({inst:bars},raw,received_at,TWSE_URL,'TWSE daily TAIEX OHLC; Government Open Data License v1; no exchange endorsement')


def _csv_rows(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES: raise MarketValidationError('invalid CSV byte size')
    try:
        text=raw.decode('utf-8-sig')
    except UnicodeError:
        try:text=raw.decode('cp950')
        except UnicodeError as exc:raise MarketValidationError('invalid native CSV encoding') from exc
    try:
        reader=csv.reader(io.StringIO(text),strict=True)
        if tuple(next(reader))!=_CSV_FIELDS: raise MarketValidationError('unsupported TAIFEX CSV header')
        mapping={'Date':'交易日期','Contract':'契約','ContractMonth(Week)':'到期月份(週別)','Open':'開盤價','High':'最高價','Low':'最低價','Last':'收盤價','Volume':'成交量','SettlementPrice':'結算價','TradingSession':'交易時段'}
        rows=[]
        for values in reader:
            if len(rows)>=MAX_ROWS: raise MarketValidationError('CSV row limit')
            if len(values)==20 and values[-1]=='':values=values[:-1]
            if len(values)!=19 or any(len(v)>512 for v in values): raise MarketValidationError('invalid CSV row width')
            native=dict(zip(_CSV_FIELDS,values));rows.append({key:native[value] for key,value in mapping.items()})
        if not rows:raise MarketValidationError('empty CSV')
        return rows
    except (csv.Error,StopIteration) as exc:raise MarketValidationError('invalid CSV') from exc


def parse_taifex_daily(raw, *, received_at, format='json'):
    """Return separate real expiries. MTX is native code; MXF is UI label.

    Missing OHLC rows (even nonzero volume) are omitted, never reconstructed.
    Weekly outright expiries are retained; slash spread instruments are omitted.
    Settlement is independent of last/previous close; source Change is not used.
    """
    if format not in ('json','csv'): raise MarketValidationError('unsupported format')
    rows=_rows(raw) if format=='json' else _csv_rows(raw)
    digest=hashlib.sha256(raw).hexdigest(); grouped={};omitted=0;seen=set()
    for row in rows:
        fields=('Date','Contract','ContractMonth(Week)','Open','High','Low','Last','Volume','SettlementPrice','TradingSession')
        if not all(k in row for k in fields): raise MarketValidationError('unsupported TAIFEX schema')
        native=row['Contract'].strip()
        if native not in ('TX','MTX','TMF'):continue
        expiry=row['ContractMonth(Week)'].strip()
        if re.fullmatch(r'\d{6}(?:W[1-5])?/\d{6}(?:W[1-5])?',expiry):omitted+=1;continue
        inst=InstrumentRef('TAIFEX',{'MTX':'MXF'}.get(native,native),f'TAIFEX:{native}:{expiry}',expiry)
        trade_date=_date(row['Date']);session={'一般':'day','盤後':'night'}.get(row['TradingSession'].strip())
        if session is None:raise MarketValidationError('unknown native session')
        identity=(inst.contract_id,trade_date,session)
        if identity in seen:raise MarketValidationError('duplicate native row identity')
        seen.add(identity)
        volume=row['Volume'].strip()
        if not re.fullmatch(r'\d{1,15}',volume):raise MarketValidationError('invalid native volume')
        prices=[_num(row[k],optional=True) for k in ('Open','High','Low','Last')]
        settlement=_num(row['SettlementPrice'],optional=True)
        if any(p is None for p in prices):omitted+=1;continue
        bar=MarketBar(inst,trade_date,session,*prices,int(volume),source_id=digest,settlement=settlement)
        grouped.setdefault(inst,[]).append(bar)
    return _series(grouped,raw,received_at,TAIFEX_URL if format=='json' else TAIFEX_CSV_URL,'TAIFEX daily futures prices; Government Open Data License v1; MTX displayed as MXF; no exchange endorsement',omitted)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise MarketValidationError('official response redirect refused')


class _DeadlineHTTPSHandler(HTTPSHandler):
    """Interrupt a drip-fed header/body at the shared request deadline.

    Socket shutdown (not merely file.close) wakes a blocked SSL read. The timer
    covers response headers as well as body; each request owns its own timers.
    DNS/TCP/TLS establishment still uses the explicit connection timeout.
    """
    def __init__(self,deadline):
        super().__init__(context=ssl.create_default_context())
        self.deadline=deadline
        self.timers=[]

    def https_open(self,req):
        owner=self
        class DeadlineConnection(HTTPSConnection):
            def connect(self):
                remaining=owner.deadline-time.monotonic()
                if remaining<=0:raise MarketValidationError('response time limit')
                self.timeout=min(self.timeout,remaining)
                super().connect()
                remaining=owner.deadline-time.monotonic()
                if remaining<=0:
                    self.close()
                    raise MarketValidationError('response time limit')
                sock=self.sock
                def interrupt():
                    try:sock.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                    finally:sock.close()
                timer=threading.Timer(remaining,interrupt)
                timer.daemon=True
                owner.timers.append(timer)
                timer.start()
        return self.do_open(DeadlineConnection,req,context=self._context)

    def cleanup(self):
        for timer in self.timers:
            timer.cancel()
        for timer in self.timers:
            timer.join(timeout=1)


def fetch_official(url):
    """No cookies, credentials, proxies or redirect following; TLS verified."""
    official_url(url)
    if url==TAIFEX_CSV_URL:raise MarketValidationError('CSV download requires an explicit dated request; use local CSV parser')
    deadline=time.monotonic()+TOTAL_TIMEOUT
    handler=_DeadlineHTTPSHandler(deadline)
    opener=build_opener(ProxyHandler({}),_NoRedirect(),handler)
    request=Request(url,headers={'Accept':'application/json','Accept-Encoding':'identity','User-Agent':'QuantLab-readonly-market/1'})
    try:
        with opener.open(request,timeout=20) as response:
            if time.monotonic()>=deadline:raise MarketValidationError('response time limit')
            if response.status!=200 or response.geturl()!=url:raise MarketValidationError('unexpected official response')
            if response.headers.get('Content-Encoding','identity').lower()!='identity':raise MarketValidationError('encoded response refused')
            length=response.headers.get('Content-Length')
            if length is not None and (not length.isdigit() or int(length)>MAX_BYTES):raise MarketValidationError('invalid response length')
            chunks=[];size=0
            while True:
                if time.monotonic()>=deadline:raise MarketValidationError('response time limit')
                chunk=response.read(min(65536,MAX_BYTES-size+1))
                if time.monotonic()>=deadline:raise MarketValidationError('response time limit')
                if not chunk:break
                size+=len(chunk)
                if size>MAX_BYTES:raise MarketValidationError('response size limit')
                chunks.append(chunk)
            if length is not None and size!=int(length):raise MarketValidationError('truncated response')
            return b''.join(chunks)
    except MarketValidationError:raise
    except Exception as exc:raise MarketValidationError('official fetch failed; no response accepted') from exc
    finally:handler.cleanup()


@dataclass(frozen=True)
class MarketLoad:
    series: tuple[MarketSeries,...]
    stale: bool
    error: str = ''


def _reject_link(path):
    try:
        info=path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
        raise MarketValidationError('cache symlink or Windows reparse point refused')


def _target(provider,root):
    if provider not in ('twse','taifex'):raise MarketValidationError('unsupported provider')
    root=Path(root).absolute()
    if '..' in root.parts:raise MarketValidationError('cache traversal refused')
    for path in (root,*root.parents):
        _reject_link(path)
    root.mkdir(parents=True,exist_ok=True)
    target=root/(provider+'.json')
    _reject_link(target)
    if target.exists() and not target.is_file():raise MarketValidationError('unsafe cache target')
    return target


def _parse(provider,raw,received_at, *, format='json',origin='official_https'):
    if provider not in ('twse','taifex'):raise MarketValidationError('unsupported provider')
    if format not in ('json','csv') or (provider=='twse' and format!='json'):raise MarketValidationError('unsupported provider format')
    if origin not in ('official_https','local_file_unverified'):raise MarketValidationError('unsupported source origin')
    if origin=='official_https' and format!='json':raise MarketValidationError('remote CSV origin unsupported')
    series=(parse_twse_daily(raw,received_at=received_at) if provider=='twse' else
            parse_taifex_daily(raw,received_at=received_at,format=format))
    if origin=='local_file_unverified':
        series=tuple(replace(s,provenance=replace(s.provenance,mode='history',
            attribution='本機檔案採交易所公開資料格式；原始來源與授權尚未核實',
            timestamp_basis='本機接收時間；只有交易日期，沒有來源事件時間或遠端更新證明',
            warnings=s.provenance.warnings+('本機匯入，來源未經連線核實',
                '來源網址僅為格式參考；檔案內容及授權未經驗證，SHA-256 僅識別匯入內容。')))
            for s in series)
    return series


def load_cached(provider,root):
    target=_target(provider,root)
    try:
        if target.stat().st_size>MAX_BYTES*2:raise MarketValidationError('cache size limit')
        with target.open('rb') as stream:content=stream.read(MAX_BYTES*2+1)
        if len(content)>MAX_BYTES*2:raise MarketValidationError('cache size limit')
        payload=json.loads(content,object_pairs_hook=_pairs)
        if not isinstance(payload,dict):raise MarketValidationError('invalid cache schema')
        base={'schema','provider','received_at','sha256','raw_base64'}
        version=payload.get('schema')
        if type(version) is not int or version not in (1,2):raise MarketValidationError('unsupported cache version')
        if set(payload)!=(base if version==1 else base|{'format','origin'}) or payload['provider']!=provider:raise MarketValidationError('invalid cache schema')
        format=payload.get('format','json');origin=payload.get('origin','official_https')
        raw=base64.b64decode(payload['raw_base64'],validate=True)
        if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=payload['sha256']:raise MarketValidationError('cache hash or size mismatch')
        received_at=datetime.fromisoformat(payload['received_at']);utc(received_at)
        return MarketLoad(_parse(provider,raw,received_at,format=format,origin=origin),True,'Cached history; current remote freshness unverified')
    except MarketValidationError:raise
    except (OSError,ValueError,TypeError,KeyError,RecursionError) as exc:raise MarketValidationError('no valid market cache') from exc


def _cache_digest(target):
    with target.open('rb') as stream:content=stream.read(MAX_BYTES*2+1)
    if len(content)>MAX_BYTES*2:raise MarketValidationError('cache size limit')
    return hashlib.sha256(content).digest()


def _write_cache(provider,root,raw,received_at, *, format,origin):
    target=_target(provider,root)
    # An unrelated or malformed existing file is never silently overwritten.
    previous=None
    if target.exists():
        load_cached(provider,root)
        previous=_cache_digest(target)
    payload={'schema':2,'provider':provider,'format':format,'origin':origin,
             'received_at':received_at.isoformat(),'sha256':hashlib.sha256(raw).hexdigest(),
             'raw_base64':base64.b64encode(raw).decode('ascii')}
    content=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
    fd,path=tempfile.mkstemp(prefix='.market-',suffix='.tmp',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
        _target(provider,root)
        if target.exists():
            if previous is None or target.stat().st_size>MAX_BYTES*2 or _cache_digest(target)!=previous:
                raise MarketValidationError('cache changed during write; refusing overwrite')
        elif previous is not None:raise MarketValidationError('cache changed during write')
        os.replace(path,target)
    finally:
        if os.path.exists(path):os.unlink(path)


def import_daily(provider,root,raw, *, format='json',received_at=None):
    """Explicit local-file import. Format recognition is not source proof.

    The caller must bound file reading to MAX_BYTES+1 before passing bytes.
    No network is used. Only a validated managed cache may be replaced.
    """
    _target(provider,root)
    received_at=received_at or datetime.now(timezone.utc)
    series=_parse(provider,raw,received_at,format=format,origin='local_file_unverified')
    _write_cache(provider,root,raw,received_at,format=format,origin='local_file_unverified')
    return MarketLoad(series,True,'本機匯入，來源未經連線核實')


def refresh_daily(provider,root, *, received_at=None,network_enabled=False,transport=fetch_official):
    """Call only from an explicit user refresh action. Never persist consent."""
    if network_enabled is not True:raise MarketValidationError('explicit network consent required for refresh')
    _target(provider,root)
    try:
        raw=transport(TWSE_URL if provider=='twse' else TAIFEX_URL)
        received_at=received_at or datetime.now(timezone.utc)
        series=_parse(provider,raw,received_at)
        _write_cache(provider,root,raw,received_at,format='json',origin='official_https')
        return MarketLoad(series,False)
    except Exception as exc:
        try:cached=load_cached(provider,root)
        except MarketValidationError:raise MarketValidationError('refresh failed and no valid last-good cache exists') from exc
        return MarketLoad(cached.series,True,'Refresh failed; showing last-good cached history')

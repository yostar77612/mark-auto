"""Bounded local TAIFEX tick history for display, never a trading Dataset.

Observed CSV and comma-delimited RPT share the native nine-column schema.
Product rule references do not authenticate local files or dated user calendars.
No network, trading-core imports, archive extraction, or fabricated minute bars.
"""
from dataclasses import dataclass,replace
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
import csv
import hashlib
import io
import json
import os
from pathlib import Path,PureWindowsPath
import re
import stat
import tempfile
import time
from .market import InstrumentRef,MarketBar,MarketSeries,SourceProvenance,MarketValidationError,bar_key,utc,day

MAX_FILE_BYTES=64*1024*1024
MAX_ROWS=1_000_000
MAX_SECONDS=120
MAX_CACHE_BYTES=16*1024*1024
MAX_BARS=100000
MAX_SESSIONS=256
MAX_IMPORTS=64
VERSION='taifex-market-ticks-v1'
SOURCE_URL='https://www.taifex.com.tw/cht/3/futPrevious30DaysSalesData'
PRODUCT_SOURCES={'TX':'https://www.taifex.com.tw/cht/2/tX','MTX':'https://www.taifex.com.tw/cht/2/mTX','TMF':'https://www.taifex.com.tw/cht/2/tMF'}
COLUMNS=('成交日期','商品代號','到期月份(週別)','成交時間','成交價格','成交數量(B+S)','近月價格','遠月價格','開盤集合競價')
WARNINGS=('本機匯入，來源未經連線核實；歷史行情，不是即時報價。',
          '交易日與時段由使用者明確指定；商品規格網址不是該日期行事曆認證。',
          '僅單式成交，B+S數量除以2；排除價差與大額交易，不與每日含價差成交量宣稱相同。',
          '逐筆及衍生分鐘資料之再散布授權未確認；僅供本機私人檢視。',
          '分鐘存在與OHLC吻合不證明逐筆完整；不得當作研究品質或交易資格認證。')
UTC=timezone.utc
TAIPEI=timezone(timedelta(hours=8))


def _fail(message):raise MarketValidationError(message)
def _canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def _hash(value):return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()
def _stamp(text):
    if not isinstance(text,str) or len(text)>40:_fail('invalid session timestamp')
    try:
        value=datetime.fromisoformat(text.replace('Z','+00:00'))
        if value.tzinfo is None:raise ValueError()
        return value.astimezone(UTC)
    except ValueError:_fail('explicit session timezone required')


@dataclass(frozen=True)
class MarketSession:
    instrument: InstrumentRef
    trade_date: str
    session: str
    open: datetime
    end: datetime
    include_end: bool = False
    source: str = ''

    def __post_init__(self):
        if not isinstance(self.instrument,InstrumentRef) or self.instrument.exchange!='TAIFEX':_fail('explicit supported futures contract required')
        day(self.trade_date);utc(self.open);utc(self.end)
        if self.session not in ('day','night') or type(self.include_end) is not bool:_fail('invalid session flags')
        if not timedelta(0)<self.end-self.open<=timedelta(hours=24):_fail('session must be positive and at most 24 hours')
        if self.open.second or self.open.microsecond or self.end.second or self.end.microsecond:_fail('session boundaries must be minute aligned')
        native=self.instrument.contract_id.split(':')[1]
        if self.source!=PRODUCT_SOURCES[native]:_fail('fixed independent official product reference required')
        # Dates are explicitly supplied, never inferred from weekends/holidays.
        local_open=self.open.astimezone(TAIPEI)
        if self.session=='day' and (self.trade_date!=local_open.date().isoformat() or self.end.astimezone(TAIPEI).date()!=local_open.date()):_fail('day session must use its explicit local trade date')
        if self.session=='night' and not local_open.date().isoformat()<self.trade_date:_fail('night attributed trade date must be explicitly later than its opening date')
        if (datetime.fromisoformat(self.trade_date).date()-local_open.date()).days>14:_fail('session trade date attribution exceeds bounded window')


def _session_dict(s):
    return dict(contract_id=s.instrument.contract_id,trade_date=s.trade_date,session=s.session,open=s.open.isoformat(),end=s.end.isoformat(),include_end=s.include_end,source=s.source)


def session_from_dict(value):
    keys={'contract_id','trade_date','session','open','end','include_end','source'}
    if not isinstance(value,dict) or set(value)!=keys:_fail('session fields do not match supported schema')
    cid=value['contract_id']
    if not isinstance(cid,str) or len(cid)>40:_fail('invalid contract identity')
    parts=cid.split(':')
    if len(parts)!=3 or parts[1] not in PRODUCT_SOURCES:_fail('invalid contract identity')
    inst=InstrumentRef(parts[0],{'MTX':'MXF'}.get(parts[1],parts[1]),cid,parts[2])
    return MarketSession(inst,value['trade_date'],value['session'],_stamp(value['open']),_stamp(value['end']),value['include_end'],value['source'])


def _sessions(values):
    if not isinstance(values,(tuple,list)) or not 1<=len(values)<=MAX_SESSIONS:_fail('bounded explicit sessions required')
    if any(not isinstance(s,MarketSession) for s in values):_fail('typed session policy required')
    result=tuple(sorted(values,key=lambda s:(s.instrument.contract_id,s.open,s.trade_date,s.session)))
    if sum(int((s.end-s.open).total_seconds()/60) for s in result)>MAX_BARS:_fail('session minute budget exceeded')
    for i,s in enumerate(result):
        for other in result[i+1:]:
            if s.instrument==other.instrument and (s.trade_date,s.session)==(other.trade_date,other.session):_fail('duplicate contract trade-date session')
            if s.instrument==other.instrument and (other.open<s.end or (other.open==s.end and s.include_end)):_fail('overlapping explicit sessions')
    return result


@dataclass(frozen=True)
class HistoryLoad:
    series: tuple[MarketSeries,...]
    policy_hash: str
    source_hash: str
    counters: tuple[tuple[str,int],...]
    warnings: tuple[str,...]
    cache_id: str


def _local_path_text(path):
    text=os.fspath(path)
    if not isinstance(text,str) or not text or '\x00' in text:_fail('invalid local path')
    normalized=text.replace('\\','/')
    if normalized.startswith('//'):_fail('UNC and device namespace paths are not local imports')
    for index,part in enumerate(normalized.split('/')):
        if ':' in part and not (index==0 and re.fullmatch('[A-Za-z]:',part)):_fail('alternate stream/device path refused')
        stem=part.rstrip(' .').split('.')[0].upper()
        if PureWindowsPath(part).is_reserved() or stem in ('CON','PRN','AUX','NUL','CONIN$','CONOUT$') or re.fullmatch(r'(?:COM|LPT)[1-9]',stem):_fail('reserved device path refused')
    return text


def _windows_local_drive(path):
    # GetDriveType checks the native drive classification before probing a file.
    # Reject mapped remote/unknown roots instead of trusting the absence of UNC.
    import ctypes
    function=ctypes.windll.kernel32.GetDriveTypeW
    function.argtypes=[ctypes.c_wchar_p];function.restype=ctypes.c_uint
    if function(path.anchor) not in (2,3,5,6):_fail('only verified local filesystem drives are supported')


def _safe(path, *, directory=False,create=False):
    path=Path(_local_path_text(path)).absolute()
    if os.name=='nt':_windows_local_drive(path)
    if '..' in path.parts:_fail('path traversal refused')
    for item in (*reversed(path.parents),path):
        try:info=item.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:_fail('symlink or reparse point refused')
    if create:path.mkdir(parents=True,exist_ok=True)
    if path.exists():
        mode=path.stat().st_mode
        if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):_fail('unexpected path type')
    return path


def _check(deadline,cancelled):
    if cancelled is not None and cancelled():_fail('history import cancelled')
    if time.monotonic()>=deadline:_fail('history import time limit')


def _lines(stream,digest,deadline,cancelled):
    size=0;encoding=None
    while True:
        _check(deadline,cancelled)
        raw=stream.readline(4097)
        if not raw:break
        size+=len(raw)
        if size>MAX_FILE_BYTES or len(raw)>4096:_fail('native file byte/line limit')
        digest.update(raw)
        if encoding is None:
            try:raw.decode('utf-8-sig');encoding='utf-8-sig'
            except UnicodeError:encoding='cp950'
        try:line=raw.decode(encoding)
        except UnicodeError:_fail('native file encoding invalid')
        if '\x00' in line:_fail('binary native input refused')
        yield line


def _positive(text,name):
    if not re.fullmatch(r'[0-9]{1,12}',text):_fail('invalid '+name)
    value=int(text)
    if value<=0:_fail('nonpositive '+name)
    return value


def _tick_time(d,t):
    if not re.fullmatch(r'\d{8}',d) or not re.fullmatch(r'\d{6}',t):_fail('invalid native date/time')
    try:return datetime(int(d[:4]),int(d[4:6]),int(d[6:]),int(t[:2]),int(t[2:4]),int(t[4:]),tzinfo=TAIPEI).astimezone(UTC)
    except ValueError:_fail('invalid native date/time')


def _decode(path,sessions,deadline,cancelled):
    by_contract={}
    for index,s in enumerate(sessions):by_contract.setdefault(s.instrument.contract_id,[]).append((index,s))
    counters=dict(rows=0,accepted_ticks=0,spread_rows=0,excluded_rows=0,outside_session_rows=0,missing_minutes=0)
    digest=hashlib.sha256();groups={}
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno())
        if before.st_size>MAX_FILE_BYTES:_fail('native file size limit')
        reader=csv.reader(_lines(stream,digest,deadline,cancelled),strict=True)
        try:
            columns=next(reader)
            if tuple(c.strip().lstrip('\ufeff') for c in columns)!=COLUMNS:_fail('unsupported native tick schema; fixed-width RPT is not supported')
            for line_number,row in enumerate(reader,2):
                counters['rows']+=1
                if counters['rows']>MAX_ROWS:_fail('native row limit')
                if len(row)!=9 or any(len(v)>128 for v in row):_fail('invalid native column width at row '+str(line_number))
                d,native,expiry,t,p,q,near,far,_=(v.strip() for v in row)
                if native not in PRODUCT_SOURCES:
                    counters['excluded_rows']+=1;continue
                if '/' in expiry:
                    if not re.fullmatch(r'\d{6}(?:W[1-5])?/\d{6}(?:W[1-5])?',expiry):_fail('invalid spread identity')
                    counters['spread_rows']+=1;continue
                cid=f'TAIFEX:{native}:{expiry}'
                if cid not in by_contract:
                    counters['excluded_rows']+=1;continue
                stamp=_tick_time(d,t)
                quantity=_positive(q,'B+S quantity')
                if quantity%2:_fail('B+S quantity must be even')
                value=_positive(p,'integral price')
                if value>1_000_000_000 or near!='-' or far!='-':_fail('invalid outright tick price/scope')
                matches=[(i,s) for i,s in by_contract[cid] if s.open<=stamp<s.end or (s.include_end and stamp==s.end)]
                if not matches:counters['outside_session_rows']+=1;continue
                if len(matches)!=1:_fail('ambiguous session membership')
                index,s=matches[0]
                bucket=int((stamp-s.open).total_seconds()//60)
                if stamp==s.end:bucket-=1
                key=(index,bucket)
                order=(stamp,line_number)
                if key not in groups:groups[key]=[order,order,value,value,value,value,quantity//2]
                else:
                    a=groups[key]
                    if order<a[0]:a[0]=order;a[2]=value
                    if order>a[1]:a[1]=order;a[5]=value
                    a[3]=max(a[3],value);a[4]=min(a[4],value);a[6]+=quantity//2
                counters['accepted_ticks']+=1
            after=os.fstat(stream.fileno())
        except (csv.Error,StopIteration) as exc:raise MarketValidationError('malformed native tick file') from exc
    current=path.stat()
    identity=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
    if identity(before)!=identity(after) or identity(after)!=identity(current):_fail('source changed while importing')
    if not groups:_fail('no actual trades within selected contract/session policy')
    source_hash=digest.hexdigest();bars=[]
    for index,s in enumerate(sessions):
        expected=int((s.end-s.open).total_seconds()/60)
        actual={bucket for (i,bucket) in groups if i==index}
        missing=expected-len(actual);counters['missing_minutes']+=missing
        for bucket in sorted(actual):
            a=groups[(index,bucket)];start=s.open+timedelta(minutes=bucket)
            bars.append(MarketBar(s.instrument,s.trade_date,s.session,*[Decimal(x) for x in a[2:6]],a[6],interval='1m',timestamp=start,end=min(start+timedelta(minutes=1),s.end),session_open=s.open,session_end=s.end,partial=bool(missing),source_id=source_hash))
    return tuple(bars),source_hash,counters


def _bar_dict(b):
    return dict(contract_id=b.contract_id,trade_date=b.trade_date,session=b.session,open=str(b.open),high=str(b.high),low=str(b.low),close=str(b.close),volume=b.volume,timestamp=b.timestamp.isoformat(),end=b.end.isoformat(),session_open=b.session_open.isoformat(),session_end=b.session_end.isoformat(),partial=b.partial)


def _result(bars,sessions,source_hash,counters,received_at):
    policy_hash=_hash([_session_dict(s) for s in sessions])
    cache_id=_hash(dict(version=VERSION,source_hash=source_hash,policy_hash=policy_hash))
    warnings=WARNINGS+((f"缺少 {counters['missing_minutes']} 個分鐘區間；未補值，完整性未知。",) if counters['missing_minutes'] else ())
    groups={}
    for b in bars:groups.setdefault(b.instrument,[]).append(b)
    series=[]
    for inst,values in sorted(groups.items(),key=lambda x:x[0].contract_id):
        values=tuple(sorted(values,key=bar_key));start=min(b.trade_date for b in values);end=max(b.trade_date for b in values)
        provenance=SourceProvenance(SOURCE_URL,source_hash,'本機TAIFEX原生格式檔案；來源與日期政策未經連線核實',SOURCE_URL,received_at,end,start,end,mode='history',timestamp_basis='原生成交當地時間轉UTC；交易日由明示使用者時段政策指定；政策SHA256='+policy_hash,omitted_rows=counters['spread_rows']+counters['excluded_rows']+counters['outside_session_rows'],warnings=warnings)
        series.append(MarketSeries(inst,values,provenance))
    return HistoryLoad(tuple(series),policy_hash,source_hash,tuple(sorted(counters.items())),warnings,cache_id)


def _pairs(pairs):
    result={}
    for k,v in pairs:
        if k in result:_fail('duplicate cache key')
        result[k]=v
    return result


def load_history(root,cache_id):
    if not isinstance(cache_id,str) or not re.fullmatch('[a-f0-9]{64}',cache_id):_fail('invalid history cache identity')
    root=_safe(root,directory=True);path=_safe(root/(cache_id+'.json'))
    try:
        with path.open('rb') as stream:raw=stream.read(MAX_CACHE_BYTES+1)
        if len(raw)>MAX_CACHE_BYTES:_fail('history cache byte limit')
        envelope=json.loads(raw,object_pairs_hook=_pairs)
        if not isinstance(envelope,dict) or set(envelope)!={'payload','sha256'}:_fail('invalid history cache envelope')
        payload=envelope['payload']
        if not isinstance(payload,dict) or set(payload)!={'version','source_hash','policy_hash','received_at','sessions','bars','counters'}:_fail('invalid history cache fields')
        if payload['version']!=VERSION or _hash(payload)!=envelope['sha256']:_fail('history cache digest/version mismatch')
        if not re.fullmatch('[a-f0-9]{64}',payload['source_hash']):_fail('invalid source digest')
        sessions=_sessions([session_from_dict(s) for s in payload['sessions']])
        if _hash([_session_dict(s) for s in sessions])!=payload['policy_hash']:_fail('session policy digest mismatch')
        received_at=_stamp(payload['received_at']);utc(received_at)
        if not isinstance(payload['bars'],list) or not 1<=len(payload['bars'])<=MAX_BARS:_fail('history bar count limit')
        counters=payload['counters']
        names={'rows','accepted_ticks','spread_rows','excluded_rows','outside_session_rows','missing_minutes'}
        if not isinstance(counters,dict) or set(counters)!=names or any(type(v) is not int or not 0<=v<=MAX_ROWS for v in counters.values()):_fail('invalid history counters')
        bars=[]
        keys={'contract_id','trade_date','session','open','high','low','close','volume','timestamp','end','session_open','session_end','partial'}
        for row in payload['bars']:
            if not isinstance(row,dict) or set(row)!=keys:_fail('invalid history bar fields')
            matches=[s for s in sessions if (s.instrument.contract_id,s.trade_date,s.session)==(row['contract_id'],row['trade_date'],row['session'])]
            if len(matches)!=1:_fail('history bar outside policy')
            s=matches[0]
            if any(not isinstance(row[k],str) or not re.fullmatch(r'[0-9]{1,10}',row[k]) or int(row[k])<=0 for k in ('open','high','low','close')):_fail('invalid cached integral price')
            b=MarketBar(s.instrument,s.trade_date,s.session,*[Decimal(row[k]) for k in ('open','high','low','close')],row['volume'],interval='1m',timestamp=_stamp(row['timestamp']),end=_stamp(row['end']),session_open=_stamp(row['session_open']),session_end=_stamp(row['session_end']),partial=row['partial'],source_id=payload['source_hash'])
            if b.session_open!=s.open or b.session_end!=s.end:_fail('history bar session mismatch')
            if b.volume<=0 or b.end-b.timestamp!=timedelta(minutes=1):_fail('invalid normalized minute volume/duration')
            bars.append(b)
        missing=0
        for s in sessions:
            selected=[b for b in bars if b.instrument==s.instrument and b.trade_date==s.trade_date and b.session==s.session]
            gap=int((s.end-s.open).total_seconds()/60)-len(selected);missing+=gap
            if any(b.partial!=bool(gap) for b in selected):_fail('history partial coverage mismatch')
        if missing!=counters['missing_minutes']:_fail('history gap counter mismatch')
        if counters['rows']!=sum(counters[k] for k in ('accepted_ticks','spread_rows','excluded_rows','outside_session_rows')):_fail('history row accounting mismatch')
        if counters['accepted_ticks']<len(bars):_fail('history tick count mismatch')
        result=_result(bars,sessions,payload['source_hash'],counters,received_at)
        if result.cache_id!=cache_id:_fail('history identity mismatch')
        return result
    except MarketValidationError:raise
    except (OSError,ValueError,TypeError,KeyError,RecursionError,OverflowError,InvalidOperation) as exc:raise MarketValidationError('invalid or unavailable history cache') from exc


def _entries(root, *, lock_held=False):
    paths=[];total_bytes=0;count=0;identities=set()
    for p in root.iterdir():
        count+=1
        if count>MAX_IMPORTS*3+1:_fail('history directory entry limit')
        temporary=bool(re.fullmatch(r'\.history-[a-zA-Z0-9_-]+\.tmp',p.name))
        try:
            _safe(p);info=p.stat();size=info.st_size
            identity=(info.st_dev,info.st_ino)
        except FileNotFoundError:
            if temporary:continue  # another importer cleaned up its owned temp
            _fail('history cache changed during listing')
        if p.suffix=='.json' and re.fullmatch('[a-f0-9]{64}',p.stem):
            if identity not in identities:total_bytes+=size;identities.add(identity)
            if total_bytes>MAX_FILE_BYTES:_fail('combined history cache byte limit')
            paths.append(p)
            if len(paths)>MAX_IMPORTS:_fail('history cache count limit')
        elif p.name=='.history.lock':
            if size not in (0,1):_fail('unknown history lock file')
            # Windows byte locks prohibit reading byte0 through a second handle.
            # The owning descriptor already validated content after acquisition.
            if not lock_held:
                with p.open('rb') as stream:
                    if stream.read(2) not in (b'',b'\0'):_fail('unknown history lock file')
        elif temporary:
            if size>MAX_CACHE_BYTES:_fail('orphan history temporary file too large')
            if identity not in identities:total_bytes+=size;identities.add(identity)
            if total_bytes>MAX_FILE_BYTES:_fail('combined history cache/temp byte limit')
        else:_fail('unknown history cache entry')
    return paths,total_bytes


@contextmanager
def _cache_lock(root):
    """OS advisory lock is released on cancellation/process death, unlike sentinels."""
    path=_safe(root/'.history.lock')
    try:
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        fd=os.open(path,os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
    locked=False
    try:
        os.lseek(fd,0,os.SEEK_SET)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
            os.lseek(fd,0,os.SEEK_SET)
            if os.read(fd,2) not in (b'',b'\0') or os.fstat(fd).st_size not in (0,1):_fail('unknown history lock content')
            if os.fstat(fd).st_size==0:
                os.lseek(fd,0,os.SEEK_SET);os.write(fd,b'\0');os.fsync(fd)
        except OSError as exc:raise MarketValidationError('another history import is publishing; retry after it finishes') from exc
        yield
    finally:
        if locked:
            os.lseek(fd,0,os.SEEK_SET)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)


def list_history(root):
    root=_safe(root,directory=True)
    if not root.exists():return ()
    paths,_=_entries(root)
    return tuple(load_history(root,p.stem) for p in sorted(paths))


def _existing_result(root,result):
    cached=load_history(root,result.cache_id)
    if (cached.counters!=result.counters or tuple(s.bars for s in cached.series)!=tuple(s.bars for s in result.series)):
        _fail('existing history cache conflicts with decoded source; refusing reuse')
    return cached


def import_history(path,root, *, sessions,received_at=None,cancelled=None):
    deadline=time.monotonic()+MAX_SECONDS
    _check(deadline,cancelled)
    sessions=_sessions(sessions);path=_safe(path)
    if path.suffix.lower() not in ('.csv','.rpt'):_fail('local native CSV or comma-delimited RPT required')
    root=_safe(root,directory=True,create=True)
    received_at=received_at or datetime.now(UTC);utc(received_at)
    bars,source_hash,counters=_decode(path,sessions,deadline,cancelled)
    result=_result(bars,sessions,source_hash,counters,received_at)
    target=_safe(root/(result.cache_id+'.json'))
    _check(deadline,cancelled)
    payload=dict(version=VERSION,source_hash=source_hash,policy_hash=result.policy_hash,received_at=received_at.isoformat(),sessions=[_session_dict(s) for s in sessions],bars=[_bar_dict(b) for b in bars],counters=counters)
    content=_canonical(dict(payload=payload,sha256=_hash(payload))).encode('utf-8')
    if len(content)>MAX_CACHE_BYTES:_fail('normalized history cache byte limit')
    _safe(root,directory=True);_safe(target);_check(deadline,cancelled)
    with _cache_lock(root):
        paths,total_bytes=_entries(root,lock_held=True)
        if target.exists():return _existing_result(root,result)
        if len(paths)>=MAX_IMPORTS or total_bytes+len(content)>MAX_FILE_BYTES:_fail('history cache count/combined byte limit')
        _check(deadline,cancelled)
        fd,temp=tempfile.mkstemp(prefix='.history-',suffix='.tmp',dir=root)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
            _safe(root,directory=True);_safe(target);_check(deadline,cancelled)
            # Exclusive hard-link publication is atomic and never overwrites another file.
            try:os.link(temp,target)
            except FileExistsError:return _existing_result(root,result)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return load_history(root,result.cache_id)

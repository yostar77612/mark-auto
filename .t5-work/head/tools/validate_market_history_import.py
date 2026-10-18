"""Private known-source Oct8 integration check, never a bundled data fixture.

Requires the actual locally acquired CSV/RPT and separate official daily JSON.
No downloads. Outputs contain checks/hashes, not redistributed raw/derived bars.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
import hashlib
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quantlab.market import InstrumentRef
from quantlab.market_history import MarketSession,PRODUCT_SOURCES,import_history
from quantlab.chart_data import aggregate_bars,TIMEFRAMES
EXPECTED_HASH='6807f4c3b7f977cb7e5109b1135fe69bbfe18d7c6b71a445e6576bb6be6163a8'

def validate(source,daily,cache):
    opening=datetime(2026,10,8,0,45,tzinfo=timezone.utc)
    sessions=tuple(MarketSession(InstrumentRef('TAIFEX',{'MTX':'MXF'}.get(n,n),f'TAIFEX:{n}:202610','202610'),'2026-10-08','day',opening,opening+timedelta(minutes=300),True,PRODUCT_SOURCES[n]) for n in ('TX','MTX','TMF'))
    started=time.monotonic();result=import_history(source,cache,sessions=sessions)
    if result.source_hash!=EXPECTED_HASH:raise ValueError('This experiment requires the independently recorded Oct8 source hash')
    with Path(daily).open('rb') as stream:raw=stream.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:raise ValueError('daily reference size limit')
    reference=json.loads(raw);checks=[]
    for series in result.series:
        native=series.instrument.contract_id.split(':')[1];bars=series.bars
        if len(bars)!=300 or {b.timestamp for b in bars}!={opening+timedelta(minutes=i) for i in range(300)}:raise ValueError('actual minute-set mismatch')
        daily_row=next(r for r in reference if r['Date']=='20261008' and r['Contract']==native and r['ContractMonth(Week)']=='202610' and r['TradingSession']=='一般')
        ohlc=[str(bars[0].open),str(max(b.high for b in bars)),str(min(b.low for b in bars)),str(bars[-1].close)]
        if ohlc!=[daily_row[k] for k in ('Open','High','Low','Last')]:raise ValueError('independent official daily OHLC mismatch')
        views={tf:len(aggregate_bars(bars,timeframe=tf,as_of=datetime(2026,10,10,tzinfo=timezone.utc)).bars) for tf in TIMEFRAMES}
        checks.append(dict(contract=series.instrument.contract_id,bars=len(bars),exact_minute_set=True,independent_daily_ohlc_match=True,outright_volume=sum(b.volume for b in bars),daily_inclusive_volume=int(daily_row['Volume']),views=views))
    if len(checks)!=3:raise ValueError('missing requested product')
    return dict(status='PASS',daily_reference_sha256=hashlib.sha256(raw).hexdigest(),daily_reference_trade_date='20261008',source_hash=result.source_hash,policy_hash=result.policy_hash,cache_id=result.cache_id,counters=dict(result.counters),checks=checks,elapsed_seconds=round(time.monotonic()-started,3),scope='Actual local private source; no realtime, dated-calendar authentication, redistribution or research certification')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('source','daily','cache','output'):parser.add_argument('--'+arg,type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('Evidence output already exists; refusing overwrite')
    result=validate(args.source,args.daily,args.cache)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(result['status'],result['source_hash'])

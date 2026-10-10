"""Frozen synthetic edge cases; real-file integration is separate private evidence."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import csv,io,json,tempfile,unittest
from unittest.mock import patch
from quantlab.market import InstrumentRef,MarketValidationError
from quantlab.market_history import (MarketSession,PRODUCT_SOURCES,import_history,load_history,list_history,session_from_dict)

UTC=timezone.utc
OPEN=datetime(2026,10,8,0,45,tzinfo=UTC)
FIELDS=('成交日期','商品代號','到期月份(週別)','成交時間','成交價格','成交數量(B+S)','近月價格','遠月價格','開盤集合競價 ')
def fixture(rows):
    out=io.StringIO();w=csv.writer(out);w.writerow(FIELDS);w.writerows(rows);return out.getvalue().encode('cp950')
def row(t='084500',price='100',q='2',symbol='TX',expiry='202610',day='20261008'):
    return [day,symbol,expiry,t,price,q,'-','-',' ']
def session(symbol='TX',start=OPEN,minutes=3,trade_date='2026-10-08',name='day',include_end=True):
    return MarketSession(InstrumentRef('TAIFEX',{'MTX':'MXF'}.get(symbol,symbol),f'TAIFEX:{symbol}:202610','202610'),trade_date,name,start,start+timedelta(minutes=minutes),include_end,PRODUCT_SOURCES[symbol])
class HistoryTests(unittest.TestCase):
    def run_import(self,rows,sessions=None,suffix='.csv',**kwargs):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name);p=root/('input'+suffix);p.write_bytes(fixture(rows))
        return import_history(p,root/'cache',sessions=tuple(sessions or [session()]),**kwargs),root
    def test_same_second_and_close_tick_and_restart(self):
        result,root=self.run_import([row(price='100'),row(price='102'),row('084600','101'),row('084800','103')])
        bars=result.series[0].bars
        self.assertEqual(len(bars),3);self.assertEqual((bars[0].open,bars[0].close,bars[0].volume),(Decimal(100),Decimal(102),2))
        self.assertEqual(bars[-1].timestamp,OPEN+timedelta(minutes=2));self.assertEqual(bars[-1].close,Decimal(103))
        self.assertEqual(load_history(root/'cache',result.cache_id),result)
        self.assertEqual(list_history(root/'cache'),(result,))
        self.assertEqual(result.series[0].provenance.mode,'history')
        self.assertTrue(any('未經' in w for w in result.warnings))
    def test_all_products_and_spread_scope(self):
        result,_=self.run_import([row(symbol=s) for s in ('TX','MTX','TMF')]+[row(expiry='202610/202611')],sessions=[session(s) for s in ('TX','MTX','TMF')],suffix='.rpt')
        self.assertEqual({s.instrument.symbol for s in result.series},{'TX','MXF','TMF'})
        self.assertEqual(dict(result.counters)['spread_rows'],1)
    def test_missing_minutes_absent_and_partial(self):
        result,_=self.run_import([row(),row('084700')])
        self.assertEqual(len(result.series[0].bars),2);self.assertTrue(all(b.partial for b in result.series[0].bars))
        self.assertEqual(dict(result.counters)['missing_minutes'],1)
    def test_invalid_selected_data_fails(self):
        for r in (row(price='NaN'),row(price='100.5'),row(q='3'),row(q='0'),row(day='20261301'),row(t='246000')):
            with self.subTest(row=r),self.assertRaises(MarketValidationError):self.run_import([r])
    def test_cancel_no_publication_and_repeat_idempotent(self):
        with self.assertRaises(MarketValidationError):self.run_import([row()],cancelled=lambda:True)
        result,root=self.run_import([row()]);again=import_history(root/'input.csv',root/'cache',sessions=(session(),))
        self.assertEqual(result,again);self.assertEqual(len(list((root/'cache').glob('*.json'))),1)
    def test_session_overlap_and_uncovered_selection(self):
        with self.assertRaises(MarketValidationError):self.run_import([row()],sessions=[session(),session()])
        with self.assertRaises(MarketValidationError):self.run_import([row('090000')])
    def test_night_holiday_trade_date_is_explicit(self):
        start=datetime(2026,10,8,7,tzinfo=UTC)
        s=session(start=start,minutes=840,trade_date='2026-10-12',name='night')
        result,_=self.run_import([row('150000'),row('003000',day='20261009'),row('050000',day='20261009')],sessions=[s])
        self.assertTrue(all(b.trade_date=='2026-10-12' and b.session=='night' for b in result.series[0].bars))
        self.assertEqual(result.series[0].bars[-1].end,s.end)
    def test_cache_tamper_symlinks_and_bad_policy(self):
        result,root=self.run_import([row()]);p=root/'cache'/(result.cache_id+'.json');p.write_text('{}')
        with self.assertRaises(MarketValidationError):load_history(root/'cache',result.cache_id)
        with self.assertRaises(MarketValidationError):import_history(root/'input.csv',root/'cache',sessions=(session(),))
        with self.assertRaises(MarketValidationError):load_history(root/'cache','../escape')
        link=root/'link';link.symlink_to(root/'input.csv')
        with self.assertRaises(MarketValidationError):import_history(link,root/'other',sessions=(session(),))
        with self.assertRaises(MarketValidationError):replace(session(),source='https://evil.test')
    def test_normal_session_dict(self):
        s=session_from_dict(dict(contract_id='TAIFEX:MTX:202610',trade_date='2026-10-08',session='day',open=OPEN.isoformat(),end=(OPEN+timedelta(minutes=3)).isoformat(),include_end=True,source=PRODUCT_SOURCES['MTX']))
        self.assertEqual(s.instrument.symbol,'MXF')

class HistoryBoundaryTests(HistoryTests):
    def test_frozen_resource_limits_and_stream_cancel(self):
        from quantlab import market_history as h
        with patch.object(h,'MAX_FILE_BYTES',10):
            with self.assertRaises(MarketValidationError):self.run_import([row()])
        with patch.object(h,'MAX_ROWS',1):
            with self.assertRaises(MarketValidationError):self.run_import([row(),row()])
        with patch.object(h,'MAX_SECONDS',0):
            with self.assertRaises(MarketValidationError):self.run_import([row()])
        checks=[]
        def cancel():checks.append(1);return len(checks)>4
        with self.assertRaises(MarketValidationError):self.run_import([row()]*20,cancelled=cancel)
        self.assertGreater(len(checks),4)
    def test_bad_schema_width_binary_encoding_and_extension(self):
        for raw in (b'fixed width RPT',fixture([row()[:-1]]),b'\x00',fixture([row()])+b'\xff\xff'):
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'bad.rpt';path.write_bytes(raw)
                with self.assertRaises(MarketValidationError):import_history(path,Path(tmp)/'cache',sessions=(session(),))
        with self.assertRaises(MarketValidationError):self.run_import([row()],suffix='.json')
    def test_out_of_order_ticks_are_stable_not_deleted(self):
        result,_=self.run_import([row('084650','104'),row('084500','100'),row('084500','101'),row('084630','102')])
        a,b=result.series[0].bars
        self.assertEqual((a.open,a.close,a.volume),(Decimal(100),Decimal(101),2))
        self.assertEqual((b.open,b.close,b.volume),(Decimal(102),Decimal(104),2))
    def test_weekly_identity_and_expiry_short_end(self):
        inst=InstrumentRef('TAIFEX','MXF','TAIFEX:MTX:202610W2','202610W2')
        s=replace(session('MTX',minutes=285),instrument=inst)
        result,_=self.run_import([row(symbol='MTX',expiry='202610W2'),row('133000','101',symbol='MTX',expiry='202610W2')],sessions=[s])
        self.assertEqual(result.series[0].instrument,inst)
        self.assertEqual(result.series[0].bars[-1].end,s.end)
        self.assertEqual(result.series[0].bars[-1].timestamp,s.end-timedelta(minutes=1))
    def test_source_hash_immutable_and_cache_policy_tamper(self):
        from quantlab import market_history as h
        result,root=self.run_import([row()]);path=root/'cache'/(result.cache_id+'.json')
        envelope=json.loads(path.read_text());envelope['payload']['bars'][0]['session_end']='2026-10-08T05:45:00+00:00'
        envelope['sha256']=h._hash(envelope['payload']);path.write_text(json.dumps(envelope))
        with self.assertRaises(MarketValidationError):load_history(root/'cache',result.cache_id)
    def test_no_core_or_network_import_graph(self):
        import subprocess,sys
        code="import sys,socket; socket.socket=lambda *a,**k: (_ for _ in ()).throw(Exception('network')); import quantlab.market_history; assert not any(x=='quantlab.core' or x.startswith('trader') or x.startswith('shioaji') for x in sys.modules)"
        self.assertEqual(subprocess.run([sys.executable,'-c',code],capture_output=True).returncode,0)
    def test_windows_reparse_and_unsafe_cache_identity(self):
        from quantlab import market_history as h
        from types import SimpleNamespace
        import stat
        with patch.object(Path,'lstat',return_value=SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)):
            with self.assertRaises(MarketValidationError):h._safe(Path('/tmp/cache'),directory=True)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'user.json').write_text('{}')
            with self.assertRaises(MarketValidationError):list_history(tmp)

class HistoryCacheRegressionTests(unittest.TestCase):
    def setup_import(self,tmp,price='100'):
        root=Path(tmp);source=root/('input-'+price+'.csv');source.write_bytes(fixture([row(price=price)]))
        return source,root/'cache'
    def test_reload_rejects_zero_volume_and_subminute_even_with_new_digest(self):
        from quantlab import market_history as h
        for change in ({'volume':0},{'end':'2026-10-08T00:45:30+00:00'},{'open':'0'},{'close':'100.5'}):
            with tempfile.TemporaryDirectory() as tmp:
                source,cache=self.setup_import(tmp);r=import_history(source,cache,sessions=(session(),))
                path=cache/(r.cache_id+'.json');obj=json.loads(path.read_text());obj['payload']['bars'][0].update(change)
                obj['sha256']=h._hash(obj['payload']);path.write_text(json.dumps(obj))
                with self.assertRaises(MarketValidationError):load_history(cache,r.cache_id)
    def test_reimport_compares_source_to_existing_normalized_cache(self):
        from quantlab import market_history as h
        with tempfile.TemporaryDirectory() as tmp:
            source,cache=self.setup_import(tmp);r=import_history(source,cache,sessions=(session(),))
            path=cache/(r.cache_id+'.json');obj=json.loads(path.read_text());obj['payload']['bars'][0]['volume']=2
            obj['sha256']=h._hash(obj['payload']);path.write_text(json.dumps(obj));before=path.read_bytes()
            with self.assertRaises(MarketValidationError):import_history(source,cache,sessions=(session(),))
            self.assertEqual(path.read_bytes(),before)
    def test_atomic_combined_quota_preserves_visible_first_import(self):
        from quantlab import market_history as h
        with tempfile.TemporaryDirectory() as tmp:
            source,cache=self.setup_import(tmp);first=import_history(source,cache,sessions=(session(),))
            size=(cache/(first.cache_id+'.json')).stat().st_size
            second,_=self.setup_import(tmp,'101')
            with patch.object(h,'MAX_FILE_BYTES',size+100):
                with self.assertRaises(MarketValidationError):import_history(second,cache,sessions=(session(),))
                self.assertEqual(list_history(cache),(first,))
    def test_concurrent_imports_respect_count_limit(self):
        from quantlab import market_history as h
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        with tempfile.TemporaryDirectory() as tmp:
            first,cache=self.setup_import(tmp);second,_=self.setup_import(tmp,'101');cache.mkdir()
            barrier=Barrier(2);decode=h._decode
            def synced(*args,**kwargs):
                result=decode(*args,**kwargs);barrier.wait(timeout=5);return result
            def attempt(path):
                try:return import_history(path,cache,sessions=(session(),))
                except MarketValidationError:return None
            with patch.object(h,'MAX_IMPORTS',1),patch.object(h,'_decode',side_effect=synced),ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(attempt,(first,second)))
            self.assertEqual(sum(r is not None for r in results),1)
            self.assertEqual(len(list_history(cache)),1)
    def test_cancelled_empty_lock_recovers_and_orphans_count_toward_quota(self):
        from quantlab import market_history as h
        with tempfile.TemporaryDirectory() as tmp:
            source,cache=self.setup_import(tmp);cache.mkdir();(cache/'.history.lock').touch()
            result=import_history(source,cache,sessions=(session(),))
            self.assertEqual((cache/'.history.lock').read_bytes(),b'\0')
            self.assertEqual(list_history(cache),(result,))
            (cache/'.history-leftover.tmp').write_bytes(b'x'*1000)
            size=(cache/(result.cache_id+'.json')).stat().st_size
            with patch.object(h,'MAX_FILE_BYTES',size+100):
                with self.assertRaises(MarketValidationError):list_history(cache)
                with self.assertRaises(MarketValidationError):import_history(source,cache,sessions=(session(),))
            self.assertEqual((cache/'.history-leftover.tmp').stat().st_size,1000)

    def test_postlink_cancellation_alias_does_not_hide_committed_history(self):
        from quantlab import market_history as h
        import os
        with tempfile.TemporaryDirectory() as tmp:
            source,cache=self.setup_import(tmp);result=import_history(source,cache,sessions=(session(),))
            target=cache/(result.cache_id+'.json');size=target.stat().st_size
            # Exact filesystem state after link publication and kill before unlink.
            os.link(target,cache/'.history-postlink.tmp')
            with patch.object(h,'MAX_FILE_BYTES',size+100):
                self.assertEqual(list_history(cache),(result,))
                self.assertEqual(import_history(source,cache,sessions=(session(),)),result)
            self.assertTrue((cache/'.history-postlink.tmp').exists())

    def test_publication_does_not_reopen_locked_byte_through_second_handle(self):
        from quantlab import market_history as h
        original=Path.open
        def refuse_second_handle(path,*args,**kwargs):
            if path.name=='.history.lock':raise PermissionError('emulated Windows mandatory byte lock')
            return original(path,*args,**kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            source,cache=self.setup_import(tmp)
            with patch.object(Path,'open',refuse_second_handle):
                result=import_history(source,cache,sessions=(session(),))
            self.assertEqual(load_history(cache,result.cache_id),result)

    def test_unc_device_and_reserved_paths_rejected_before_probe(self):
        from quantlab import market_history as h
        for path in ('//server/share/ticks.csv',r'\\server\share\ticks.csv',r'\\?\C:\ticks.csv',r'\\.\NUL','NUL.csv','COM1','COM¹.csv','LPT².rpt','NUL .csv','folder/file.csv:secret'):
            with self.subTest(path=path),patch.object(Path,'lstat',side_effect=AssertionError('must not probe')):
                with self.assertRaises(MarketValidationError):h._safe(path)

    def test_mapped_remote_drive_classification_is_refused(self):
        from quantlab import market_history as h
        from pathlib import PureWindowsPath
        from types import SimpleNamespace
        class DriveType:
            def __init__(self,value):self.value=value
            def __call__(self,root):return self.value
        for code in (0,1,4):
            with patch('ctypes.windll',SimpleNamespace(kernel32=SimpleNamespace(GetDriveTypeW=DriveType(code))),create=True):
                with self.assertRaises(MarketValidationError):h._windows_local_drive(PureWindowsPath('Z:/data'))
        with patch('ctypes.windll',SimpleNamespace(kernel32=SimpleNamespace(GetDriveTypeW=DriveType(3))),create=True):
            h._windows_local_drive(PureWindowsPath('C:/data'))

    def test_unknown_files_refused_but_orphan_temp_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,cache=self.setup_import(tmp);cache.mkdir();(cache/'foreign.txt').write_text('user data')
            with self.assertRaises(MarketValidationError):import_history(source,cache,sessions=(session(),))
            self.assertEqual((cache/'foreign.txt').read_text(),'user data')
            self.assertEqual(list(cache.glob('*.json')),[])


def _process_import(source,cache,barrier,queue):
    from quantlab import market_history as h
    original=h._decode
    def synced(*args,**kwargs):
        value=original(*args,**kwargs);barrier.wait(timeout=10);return value
    h._decode=synced;h.MAX_IMPORTS=1
    try:
        value=h.import_history(Path(source),Path(cache),sessions=(session(),))
        queue.put(('accepted',value.cache_id))
    except MarketValidationError as exc:queue.put(('rejected',str(exc)))

class HistoryProcessAdmissionTests(unittest.TestCase):
    def test_separate_processes_respect_atomic_admission(self):
        import multiprocessing
        ctx=multiprocessing.get_context('spawn');barrier=ctx.Barrier(2);queue=ctx.Queue()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'cache';cache.mkdir();processes=[]
            for price in ('100','101'):
                source=root/(price+'.csv');source.write_bytes(fixture([row(price=price)]))
                process=ctx.Process(target=_process_import,args=(str(source),str(cache),barrier,queue));process.start();processes.append(process)
            try:
                results=[queue.get(timeout=15) for _ in processes]
                for process in processes:process.join(timeout=10);self.assertEqual(process.exitcode,0)
                self.assertEqual(sum(status=='accepted' for status,_ in results),1)
                self.assertEqual(len(list_history(cache)),1)
            finally:
                for process in processes:
                    if process.is_alive():process.terminate();process.join(timeout=5)
                queue.close();queue.join_thread()

"""Frozen market v1 cases. Payload fixtures are synthetic native-schema examples."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io

from quantlab.market import InstrumentRef, MarketBar, MarketSeries, MarketValidationError, QuoteSnapshot
from quantlab.market_providers import (parse_twse_daily, parse_taifex_daily, refresh_daily, load_cached, official_url, TWSE_URL, TAIFEX_URL)

NOW = datetime(2026,10,10,tzinfo=timezone.utc)
TWSE = json.dumps([dict(Date='1151008',OpeningIndex='100',HighestIndex='102',LowestIndex='99',ClosingIndex='101')]).encode()
ROW = dict(Date='20261008',Contract='MTX',**{'ContractMonth(Week)':'202610','Open':'100','High':'102','Low':'99','Last':'101','Volume':'20','SettlementPrice':'100','TradingSession':'一般'})

class MarketTests(unittest.TestCase):
    def test_actual_schema_and_reference_semantics(self):
        s=parse_twse_daily(TWSE,received_at=NOW)[0]
        self.assertEqual(s.bars[0].trade_date,'2026-10-08')
        self.assertIsNone(s.bars[0].timestamp)
        self.assertIsNone(s.bars[0].volume)
        self.assertEqual(s.provenance.sha256,hashlib.sha256(TWSE).hexdigest())
        f=parse_taifex_daily(json.dumps([ROW]).encode(),received_at=NOW)[0]
        self.assertEqual(f.instrument.symbol,'MXF')
        self.assertEqual(f.instrument.contract_id,'TAIFEX:MTX:202610')
        self.assertEqual(f.bars[0].settlement,Decimal('100'))
        q=QuoteSnapshot.from_series(f)
        self.assertEqual(q.mode,'eod')
        self.assertIsNone(q.previous_close)
        self.assertIsNone(q.change)
        self.assertEqual(q.settlement,Decimal('100'))
    def test_immutable_validated_values(self):
        s=parse_twse_daily(TWSE,received_at=NOW)[0]; b=s.bars[0]
        for kw in ({'high':Decimal('90')},{'close':Decimal('NaN')},{'volume':True},{'trade_date':'../bad'},{'timestamp':NOW},{'partial':1}):
            with self.subTest(kw=kw),self.assertRaises(MarketValidationError):replace(b,**kw)
        with self.assertRaises(MarketValidationError):replace(s,bars=(b,b))
        with self.assertRaises(MarketValidationError):replace(s,instrument=InstrumentRef('TAIFEX','TX','TAIFEX:TX:202610','202610'))
    def test_parser_rejections_and_missing_values(self):
        for raw in (b'<html>bad</html>',b'[]',b'{}',b'[{"Date":"a","Date":"b"}]'):
            with self.assertRaises(MarketValidationError):parse_twse_daily(raw,received_at=NOW)
        for kw in ({'High':'NaN'},{'Volume':'-1'},{'TradingSession':'unknown'},{'ContractMonth(Week)':'../../bad'},{'High':'98'}):
            with self.subTest(kw=kw),self.assertRaises(MarketValidationError):parse_taifex_daily(json.dumps([{**ROW,**kw}]).encode(),received_at=NOW)
        with self.assertRaises(MarketValidationError):parse_taifex_daily(json.dumps([ROW,ROW]).encode(),received_at=NOW)
        rows=[ROW,{**ROW,'ContractMonth(Week)':'202611','Open':'-'}]
        s=parse_taifex_daily(json.dumps(rows).encode(),received_at=NOW)[0]
        self.assertEqual(s.provenance.omitted_rows,1)
        self.assertTrue(s.provenance.warnings)
    def test_freshness_never_invents_realtime(self):
        s=parse_twse_daily(TWSE,received_at=NOW)[0]
        q=QuoteSnapshot.from_series(s,stale=True)
        self.assertTrue(q.stale);self.assertEqual(q.mode,'eod')
        with self.assertRaises(MarketValidationError):replace(q,mode='realtime')
    def test_urls_and_explicit_network(self):
        for url in ('http://openapi.twse.com.tw/v1/indicesReport/MI_5MINS_HIST',TWSE_URL+'?secret=x',TWSE_URL+'#x','https://user:pw@openapi.twse.com.tw/v1/indicesReport/MI_5MINS_HIST','https://evil.test/'):
            with self.assertRaises(MarketValidationError):official_url(url)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(MarketValidationError):refresh_daily('twse',Path(root),received_at=NOW)
    def test_atomic_cache_and_failure_preserves_last_good(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            a=refresh_daily('twse',root,received_at=NOW,network_enabled=True,transport=lambda u:TWSE)
            self.assertFalse(a.stale)
            before=(root/'twse.json').read_bytes()
            b=refresh_daily('twse',root,received_at=NOW,network_enabled=True,transport=lambda u:b'bad')
            self.assertTrue(b.stale);self.assertTrue(b.error)
            self.assertEqual(before,(root/'twse.json').read_bytes())
            self.assertTrue(load_cached('twse',root).stale)
            (root/'twse.json').write_text('{}')
            with self.assertRaises(MarketValidationError):load_cached('twse',root)
    def test_cache_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); (root/'real').mkdir(); (root/'link').symlink_to(root/'real',target_is_directory=True)
            with self.assertRaises(MarketValidationError):refresh_daily('twse',root/'link',received_at=NOW,network_enabled=True,transport=lambda u:TWSE)

class MarketAdversarialTests(unittest.TestCase):
    def test_native_csv_roundtrip_and_overflow(self):
        from quantlab.market_providers import _CSV_FIELDS
        import csv
        out=io.StringIO(); writer=csv.writer(out);writer.writerow(_CSV_FIELDS)
        values=['2026/10/08','MTX','202610  ','100','102','99','101','1','1%','20','100','','','','','','','一般','']
        writer.writerow(values+[''])
        series=parse_taifex_daily(out.getvalue().encode('cp950'),received_at=NOW,format='csv')
        self.assertEqual(series[0].bars[0].close,Decimal('101'))
        with self.assertRaises(MarketValidationError):parse_taifex_daily(out.getvalue().replace(',\r\n',',bad\r\n').encode('cp950'),received_at=NOW,format='csv')
    def test_prior_close_and_settlement_are_independent(self):
        rows=[{**ROW,'Date':'20261007','Last':'100','SettlementPrice':'99'},ROW]
        series=parse_taifex_daily(json.dumps(rows).encode(),received_at=NOW)[0]
        q=QuoteSnapshot.from_series(series)
        self.assertEqual(q.previous_close,Decimal('100'))
        self.assertEqual(q.change,Decimal('1'))
        self.assertEqual(q.settlement,Decimal('100'))
    def test_sort_sessions_weeklies_missing_and_spreads(self):
        rows=[ROW,{**ROW,'TradingSession':'盤後','SettlementPrice':'NULL'},
              {**ROW,'ContractMonth(Week)':'202610W2'},
              {**ROW,'ContractMonth(Week)':'202610/202611'},
              {**ROW,'ContractMonth(Week)':'202611','High':'-','Volume':'3'}]
        series=parse_taifex_daily(json.dumps(rows).encode(),received_at=NOW)
        self.assertEqual(len(series),2)
        self.assertEqual([b.session for b in series[0].bars],['night','day'])
        self.assertIsNone(series[0].bars[0].settlement)
        self.assertEqual(series[0].provenance.omitted_rows,2)
    def test_payload_limits_and_timestamps(self):
        from quantlab.market_providers import MAX_BYTES
        with self.assertRaises(MarketValidationError):parse_twse_daily(b' '* (MAX_BYTES+1),received_at=NOW)
        with self.assertRaises(MarketValidationError):parse_twse_daily(TWSE,received_at=NOW.replace(tzinfo=None))
        with self.assertRaises(MarketValidationError):parse_twse_daily(b'['*1200+b']'*1200,received_at=NOW)
    def test_transport_rejects_redirect_encoding_and_truncation(self):
        from quantlab.market_providers import fetch_official, _NoRedirect
        class Response(io.BytesIO):
            status=200
            headers={}
            def geturl(self):return TWSE_URL
        class Opener:
            def __init__(self,response):self.response=response
            def open(self,*a,**kw):return self.response
        for headers,url in [({'Content-Encoding':'gzip'},TWSE_URL),({'Content-Length':'999999999'},TWSE_URL),({'Content-Length':'100'},TWSE_URL),({},TAIFEX_URL)]:
            response=Response(b'[]');response.headers=headers;response.geturl=lambda:url
            with patch('quantlab.market_providers.build_opener',return_value=Opener(response)):
                with self.assertRaises(MarketValidationError):fetch_official(TWSE_URL)
        with self.assertRaises(MarketValidationError):_NoRedirect().redirect_request(None,None,302,'',{},TAIFEX_URL)
    def test_wallclock_checked_after_slow_read_including_eof(self):
        from quantlab.market_providers import fetch_official
        class Response(io.BytesIO):
            status=200
            headers={}
            def geturl(self):return TWSE_URL
        class Opener:
            def open(self,*a,**kw):return Response(b'[]')
        with patch('quantlab.market_providers.build_opener',return_value=Opener()), patch('quantlab.market_providers.time.monotonic',side_effect=[0,0,0,31]):
            with self.assertRaisesRegex(MarketValidationError,'time limit'):fetch_official(TWSE_URL)

    def test_deadline_timer_interrupts_connected_socket(self):
        from quantlab.market_providers import _DeadlineHTTPSHandler
        import threading
        from types import SimpleNamespace
        closed=threading.Event()
        class FakeSocket:
            shutdown_called=False
            def shutdown(self,how):self.shutdown_called=True
            def close(self):closed.set()
        sock=FakeSocket()
        # Only the handler's deadline accounting uses this virtual clock.
        # SSL setup may take any time; the real Timer still fires after 30 ms.
        handler=_DeadlineHTTPSHandler(0.03)
        def fake_connect(connection):connection.sock=sock
        def fake_open(connection_class,req,**kwargs):
            connection=connection_class('official.test',timeout=20)
            connection.connect()
            self.assertTrue(closed.wait(0.5),'deadline must wake blocked connection')
            self.assertTrue(sock.shutdown_called)
        try:
            with patch('quantlab.market_providers.time',SimpleNamespace(monotonic=lambda:0)), patch('quantlab.market_providers.HTTPSConnection.connect',fake_connect), patch.object(handler,'do_open',side_effect=fake_open):handler.https_open(None)
        finally:handler.cleanup()
        self.assertTrue(all(not timer.is_alive() for timer in handler.timers))

    def test_expired_deadline_rejects_before_connect(self):
        from quantlab.market_providers import _DeadlineHTTPSHandler
        from types import SimpleNamespace
        handler=_DeadlineHTTPSHandler(0.03)
        def fake_open(connection_class,req,**kwargs):
            connection=connection_class('official.test',timeout=20)
            self.assertIsNone(connection.sock)
            connection.connect()
        try:
            with patch('quantlab.market_providers.time',SimpleNamespace(monotonic=lambda:0.04)), patch('quantlab.market_providers.HTTPSConnection.connect') as connect, patch.object(handler,'do_open',side_effect=fake_open):
                with self.assertRaisesRegex(MarketValidationError,'time limit'):handler.https_open(None)
                connect.assert_not_called()
            self.assertEqual(handler.timers,[])
        finally:handler.cleanup()

    def test_windows_reparse_points_rejected(self):
        from quantlab.market_providers import _reject_link
        from types import SimpleNamespace
        import stat
        with patch.object(Path,'lstat',return_value=SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)):
            with self.assertRaises(MarketValidationError):_reject_link(Path('/cache/junction'))

    def test_cache_tampering_and_failed_first_refresh(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            with self.assertRaises(MarketValidationError):refresh_daily('twse',root,received_at=NOW,network_enabled=True,transport=lambda u:b'[]')
            refresh_daily('twse',root,received_at=NOW,network_enabled=True,transport=lambda u:TWSE)
            path=root/'twse.json';payload=json.loads(path.read_text());payload['sha256']='0'*64;path.write_text(json.dumps(payload))
            with self.assertRaises(MarketValidationError):load_cached('twse',root)
    def test_night_reference_is_previous_observed_day_close(self):
        rows=[{**ROW,'Date':'20261007','Last':'100'},
              {**ROW,'Date':'20261007','TradingSession':'盤後','Last':'99'},
              {**ROW,'TradingSession':'盤後'}]
        q=QuoteSnapshot.from_series(parse_taifex_daily(json.dumps(rows).encode(),received_at=NOW)[0])
        self.assertEqual(q.previous_close,Decimal('100'))
        self.assertEqual(q.reference_kind,'previous_observed_regular_session_close')
        with self.assertRaises(MarketValidationError):replace(q,status_reason=[])
    def test_minute_alignment_and_duration(self):
        from datetime import timedelta
        b=parse_twse_daily(TWSE,received_at=NOW)[0].bars[0]
        minute=replace(b,interval='1m',timestamp=NOW,end=NOW+timedelta(minutes=1),session_open=NOW,session_end=NOW+timedelta(hours=1))
        with self.assertRaises(MarketValidationError):replace(minute,end=NOW+timedelta(minutes=2))
        with self.assertRaises(MarketValidationError):replace(minute,timestamp=NOW+timedelta(seconds=10),partial=True)
        self.assertTrue(replace(minute,end=NOW+timedelta(seconds=30),partial=True).partial)
    def test_local_import_restart_and_version1_compatibility(self):
        from quantlab.market_providers import import_daily
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            with patch('quantlab.market_providers.fetch_official',side_effect=AssertionError('no network')):
                result=import_daily('twse',root,TWSE,received_at=NOW)
            self.assertTrue(result.stale)
            self.assertEqual(result.series[0].provenance.mode,'history')
            self.assertIn('本機匯入，來源未經連線核實',result.series[0].provenance.warnings)
            cached=load_cached('twse',root)
            self.assertEqual(cached.series,result.series)
            path=root/'twse.json';payload=json.loads(path.read_text())
            self.assertEqual(payload['schema'],2);self.assertEqual(payload['origin'],'local_file_unverified')
            payload['schema']=1;payload.pop('format');payload.pop('origin');path.write_text(json.dumps(payload))
            self.assertEqual(load_cached('twse',root).series[0].provenance.mode,'eod')

    def test_csv_import_and_cache_roundtrip(self):
        from quantlab.market_providers import import_daily,_CSV_FIELDS
        import csv
        out=io.StringIO();writer=csv.writer(out);writer.writerow(_CSV_FIELDS)
        writer.writerow(['2026/10/08','MTX','202610','100','102','99','101','1','1%','20','100','','','','','','','一般','']+[''])
        with tempfile.TemporaryDirectory() as root:
            result=import_daily('taifex',root,out.getvalue().encode('cp950'),format='csv',received_at=NOW)
            self.assertEqual(load_cached('taifex',root).series,result.series)
            self.assertEqual(result.series[0].instrument.symbol,'MXF')
            before=(Path(root)/'taifex.json').read_bytes()
            for fmt in ('unknown','json'):
                with self.assertRaises(MarketValidationError):import_daily('taifex',root,out.getvalue().encode('cp950'),format=fmt,received_at=NOW)
            self.assertEqual(before,(Path(root)/'taifex.json').read_bytes())

    def test_local_import_rejects_unknown_cache_and_format_versions(self):
        from quantlab.market_providers import import_daily
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);path=root/'twse.json';path.write_text('unrelated user data')
            with self.assertRaises(MarketValidationError):import_daily('twse',root,TWSE,received_at=NOW)
            self.assertEqual(path.read_text(),'unrelated user data')
        for updates in ({'format':'csv'},{'format':'pickle'},{'origin':'authenticated_by_user'},{'schema':3},{'schema':True}):
            with tempfile.TemporaryDirectory() as root:
                root=Path(root);import_daily('twse',root,TWSE,received_at=NOW)
                path=root/'twse.json';payload=json.loads(path.read_text());payload.update(updates);path.write_text(json.dumps(payload))
                with self.assertRaises(MarketValidationError):load_cached('twse',root)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(MarketValidationError):import_daily('twse',root,TWSE,format='csv',received_at=NOW)

    def test_import_graph_is_readonly(self):
        import subprocess,sys
        code="import sys; import quantlab.market,quantlab.market_providers; assert not any(x == 'trader' or x.startswith('trader.') or x.startswith('shioaji') or x == 'quantlab.core' for x in sys.modules)"
        self.assertEqual(subprocess.run([sys.executable,'-c',code],capture_output=True).returncode,0)

if __name__=='__main__':unittest.main()

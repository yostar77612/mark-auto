import csv
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError
from quantlab.core import ValidationError
from quantlab.data import (SessionCalendar, aggregate_ticks, import_taifex,
                           validate_dataset, parse_timestamp, taipei_timestamp)

CID = 'TAIFEX:TMF:202610'

def cal(*, include_end=False):
    return SessionCalendar([{'open': '2026-10-08T08:45:00+08:00', 'end': '2026-10-08T13:45:00+08:00',
                             'trade_date': '2026-10-08', 'session': 'day', 'source': 'synthetic-test', 'include_end': include_end}], version='synthetic-v1')

def tick(time, price, quantity=1, **kwargs):
    return {'timestamp': parse_timestamp('2026-10-08T' + time + '+08:00'), 'contract_id': CID,
            'price': D(price), 'quantity': quantity, **kwargs}

class DataTests(unittest.TestCase):
    def test_hand_calculated_ohlcv_same_timestamp(self):
        ticks = [tick('08:45:20', '20010', 2), tick('08:45:00', '20000', 3),
                 tick('08:45:20', '19990', 4), tick('08:46:00', '20005', 1)]
        data = aggregate_ticks(ticks, timeframe_minutes=1, calendar=cal())
        first = data.bars[0]
        self.assertEqual((first.open, first.high, first.low, first.close, first.volume), (D('20000'), D('20010'), D('19990'), D('19990'), 9))
        self.assertEqual(data.bars[1].volume, 1)
        validate_dataset(data)
        hashes = [aggregate_ticks(ticks, timeframe_minutes=1, calendar=cal()).manifest['manifest_hash'] for _ in range(3)]
        self.assertEqual(len(set(hashes)), 1)

    def test_duplicates_only_by_explicit_identity(self):
        t = tick('08:45:00', '20000')
        data = aggregate_ticks([t, t], timeframe_minutes=1, calendar=cal())
        self.assertEqual(data.bars[0].volume, 2)
        t = dict(t, trade_id='1')
        data = aggregate_ticks([t, t], timeframe_minutes=1, calendar=cal())
        self.assertEqual(data.bars[0].volume, 1)
        self.assertEqual(data.quality['duplicate_rows'], 1)
        data = aggregate_ticks([t, dict(t, price=D('20001'))], timeframe_minutes=1, calendar=cal())
        self.assertFalse(data.quality['valid'])

    def test_gaps_invalid_not_filled(self):
        data = aggregate_ticks([tick('08:45:00', '20000'), tick('08:47:00', '20010')], timeframe_minutes=1, calendar=cal())
        self.assertEqual(len(data.bars), 2)
        self.assertEqual(data.quality['missing_intervals'], 1)
        with self.assertRaises(ValidationError): validate_dataset(data)

    def test_close_endpoint_explicit(self):
        t = tick('13:45:00', '20000')
        self.assertFalse(aggregate_ticks([t], timeframe_minutes=1, calendar=cal()).quality['valid'])
        data = aggregate_ticks([t], timeframe_minutes=1, calendar=cal(include_end=True))
        self.assertEqual(data.bars[0].timestamp, parse_timestamp('2026-10-08T13:44:00+08:00'))
        self.assertEqual(data.bars[0].end, t['timestamp'])

    def test_friday_overnight_explicit_monday_trade_date(self):
        calendar = SessionCalendar([{'open': '2026-10-08T15:00:00+08:00', 'end': '2026-10-09T05:00:00+08:00',
                                    'trade_date': '2026-10-12', 'session': 'night', 'source': 'synthetic-holiday-fixture'}], version='test')
        for ts in ('2026-10-08T23:59:00+08:00', '2026-10-09T00:00:00+08:00'):
            self.assertEqual(calendar.lookup(parse_timestamp(ts), CID)['trade_date'], '2026-10-12')
        for ts in ('2026-10-08T14:59:00+08:00', '2026-10-09T08:45:00+08:00'):
            with self.assertRaises(ValidationError): calendar.lookup(parse_timestamp(ts), CID)

    def test_expiry_specific_override(self):
        generic = {'open':'2026-10-21T08:45:00+08:00', 'end':'2026-10-21T13:45:00+08:00', 'trade_date':'2026-10-21', 'session':'day', 'source':'synthetic'}
        specific = dict(generic, contract_id=CID, end='2026-10-21T13:30:00+08:00', include_end=True, expires_at='2026-10-21T13:30:00+08:00')
        calendar = SessionCalendar([generic, specific], version='expiry')
        calendar.lookup(parse_timestamp('2026-10-21T13:30:00+08:00'), CID)
        with self.assertRaises(ValidationError): calendar.lookup(parse_timestamp('2026-10-21T13:31:00+08:00'), CID)
        calendar.lookup(parse_timestamp('2026-10-21T13:31:00+08:00'), 'TAIFEX:TMF:202611')

    def test_invalid_calendar(self):
        r = cal().sessions[0]
        with self.assertRaises(ValidationError): SessionCalendar([r, r], version='dup')
        with self.assertRaises(ValidationError): SessionCalendar([], version='')

    def test_windows_timezone_fallback(self):
        with patch('quantlab.data.ZoneInfo', side_effect=ZoneInfoNotFoundError):
            self.assertEqual(taipei_timestamp(datetime(2026,10,8,8,45)), datetime(2026,10,8,0,45,tzinfo=timezone.utc))

    def test_tampered_manifest(self):
        data = aggregate_ticks([tick('08:45:00', '20000')], timeframe_minutes=1, calendar=cal())
        with self.assertRaises(ValidationError): validate_dataset(replace(data, manifest=dict(data.manifest, data_hash='fake')))

    def test_synthetic_official_format_cp950(self):
        source = Path(__file__).parent / 'fixtures' / 'data_synthetic_taifex.csv'
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'ticks.rpt'
            dest.write_bytes(source.read_text(encoding='utf-8').encode('cp950'))
            data = import_taifex(dest, kind='synthetic_taifex_ticks', calendar=cal())
        self.assertEqual(data.manifest['source_type'], 'synthetic')
        self.assertEqual(data.manifest['encoding'], 'cp950')
        self.assertEqual(data.bars[0].volume, 5)
        self.assertEqual(data.bars[0].close, D('20010'))
        validate_dataset(data)

    def test_wrong_schema_and_malformed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.csv'; path.write_text('x,y\n1,2\n')
            with self.assertRaisesRegex(ValidationError, 'observed columns'):
                import_taifex(path, kind='ticks', calendar=cal())
            path.write_text('timestamp,contract_id,price,quantity\n2026-10-08T08:45:00+08:00,TAIFEX:TMF:202610,20000.5,1\n')
            data = import_taifex(path, kind='synthetic_ticks', calendar=cal())
            self.assertFalse(data.quality['valid'])

    def test_invalid_tick_inputs_fail_closed(self):
        for t in (tick('08:45:00', '20000.5'), tick('08:45:00', '20000', True), tick('08:45:00', '20000', -1)):
            self.assertFalse(aggregate_ticks([t], timeframe_minutes=1, calendar=cal()).quality['valid'])

    def test_daily_api_session_bars_never_minute_fabrication(self):
        import json
        row = {'Date': '20261008', 'Contract': 'TMF', 'ContractMonth(Week)': '202610',
               'Open': '20000', 'High': '20020', 'Low': '19990', 'Last': '20005',
               'Volume': '50', 'TradingSession': '一般', 'SettlementPrice': '20003.5'}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'daily.json'; path.write_text(json.dumps([row]))
            result = import_taifex(path, kind='synthetic_daily_json', calendar=cal())
        self.assertEqual(len(result.bars), 1)
        self.assertEqual(result.bars[0].end - result.bars[0].timestamp, timedelta(hours=5))
        self.assertEqual(result.bars[0].close, D('20005'))
        self.assertEqual(result.manifest['source_type'], 'synthetic')
        validate_dataset(result)

    def test_calendar_records_are_detached_and_immutable(self):
        row = dict(cal().sessions[0]); supplied = dict(row)
        calendar = SessionCalendar([supplied], version='immutable')
        supplied['end'] = parse_timestamp('2026-10-08T14:00:00+08:00')
        self.assertEqual(calendar.sessions[0]['end'], row['end'])
        with self.assertRaises(TypeError): calendar.sessions[0]['end'] = supplied['end']

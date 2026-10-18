"""Small synthetic coverage fixtures; never classified as official data."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from quantlab.core import Dataset, ValidationError, content_hash
from quantlab.data import SessionCalendar, aggregate_ticks
from tools.validate_official_history import (validate_full_sessions, verified_bytes,
                                           verified_oct8_calendar, CONTRACT)


class OfficialHistoryValidationTests(unittest.TestCase):
    def setUp(self):
        self.calendar = SessionCalendar([
            {'open': '2026-10-08T00:45:00Z', 'end': '2026-10-08T00:48:00Z',
             'trade_date': '2026-10-08', 'session': 'day', 'source': 'synthetic test',
             'contract_id': CONTRACT, 'include_end': True},
        ], version='synthetic-coverage-test')
        start = self.calendar.sessions[0]['open']
        self.ticks = [{'timestamp': start + timedelta(minutes=i), 'contract_id': CONTRACT,
                       'price': Decimal('20000'), 'quantity': 1} for i in range(3)]

    def dataset(self, ticks):
        return aggregate_ticks(ticks, timeframe_minutes=1, calendar=self.calendar)

    def test_complete(self):
        self.assertEqual(validate_full_sessions(self.dataset(self.ticks), self.calendar, CONTRACT)['observed_minutes'], 3)

    def test_leading_gap_rejected_even_if_core_quality_valid(self):
        dataset = self.dataset(self.ticks[1:])
        self.assertTrue(dataset.quality['valid'])
        with self.assertRaisesRegex(ValidationError, 'missing=1'):
            validate_full_sessions(dataset, self.calendar, CONTRACT)

    def test_trailing_gap_rejected_even_if_core_quality_valid(self):
        with self.assertRaisesRegex(ValidationError, 'missing=1'):
            validate_full_sessions(self.dataset(self.ticks[:-1]), self.calendar, CONTRACT)

    def test_interior_gap_rejected(self):
        with self.assertRaises(ValidationError):
            validate_full_sessions(self.dataset(self.ticks[::2]), self.calendar, CONTRACT)

    def test_missing_entire_session_rejected(self):
        records = [dict(s) for s in self.calendar.sessions]
        records.append({'open': '2026-10-08T07:00:00Z', 'end': '2026-10-08T07:03:00Z',
                        'trade_date': '2026-10-12', 'session': 'night', 'source': 'synthetic test',
                        'contract_id': CONTRACT})
        extended = SessionCalendar(records, version='synthetic-extra')
        with self.assertRaisesRegex(ValidationError, 'missing=3'):
            validate_full_sessions(self.dataset(self.ticks), extended, CONTRACT)

    def test_explicit_close_bucket_no_fabricated_bar(self):
        close = dict(self.ticks[-1], timestamp=self.calendar.sessions[0]['end'])
        dataset = self.dataset(self.ticks + [close])
        self.assertEqual(len(dataset.bars), 3)
        self.assertEqual(dataset.bars[-1].volume, 2)
        validate_full_sessions(dataset, self.calendar, CONTRACT)

    def test_unknown_day_and_contract_rejected(self):
        calendar = verified_oct8_calendar()
        with self.assertRaises(ValidationError):
            calendar.lookup(calendar.sessions[-1]['end'] + timedelta(days=1), CONTRACT)
        with self.assertRaises(ValidationError):
            calendar.lookup(calendar.sessions[0]['open'], 'TAIFEX:TMF:202611')

    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'input.csv'
            p.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValidationError, 'hash mismatch'):
                verified_bytes(p, '0' * 64)

    def test_mislabeled_session_rejected(self):
        dataset = self.dataset(self.ticks)
        from dataclasses import replace
        bars = (replace(dataset.bars[0], session='night'),) + dataset.bars[1:]
        manifest = dict(dataset.manifest)
        manifest['data_hash'] = content_hash(bars)
        manifest['manifest_hash'] = content_hash({k:v for k,v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
        with self.assertRaisesRegex(ValidationError, 'unexpected=1'):
            validate_full_sessions(Dataset(bars, manifest, dict(dataset.quality)), self.calendar, CONTRACT)



class ExplicitRangeAcceptanceTests(unittest.TestCase):
    """Fabricated tiny files test rejection logic, not official market evidence."""
    def setUp(self):
        import csv, hashlib, io, json, zipfile
        from quantlab.data import OFFICIAL_TICK_COLUMNS
        from tools.validate_official_history import DAILY_CSV_COLUMNS
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.records = []
        self.archives = []
        self.daily_rows = []
        for date in ('2026-10-06', '2026-10-07'):
            self.records.append({'open': date+'T08:45:00+08:00', 'end':date+'T08:47:00+08:00',
                                 'trade_date': date,'session':'day','contract_id':CONTRACT,
                                 'source':'fabricated acceptance-test fixture'})
            stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(OFFICIAL_TICK_COLUMNS)
            for time,price in (('084500','20000'),('084600','20001')):
                writer.writerow([date.replace('-',''),'TMF','202610',time,price,'2','-','-',''])
            raw=stream.getvalue().encode('cp950'); name='Daily_'+date.replace('-','_')+'.csv'
            path=self.root/name;path.write_bytes(raw)
            archive=self.root/(date+'.zip')
            with zipfile.ZipFile(archive,'w') as z:z.writestr(name,raw)
            self.archives.append({'trade_date':date,'format':'csv','source_url':'https://www.taifex.com.tw/test-fixture',
                                  'archive_path':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                                  'files':[{'name':name,'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}]})
            row={key:'' for key in DAILY_CSV_COLUMNS}
            row.update({'交易日期':date.replace('-','/'),'契約':'TMF','到期月份(週別)':'202610',
                        '開盤價':'20000','最高價':'20001','最低價':'20000','收盤價':'20001','交易時段':'一般'})
            self.daily_rows.append(row)
        (self.root/'latest.json').write_text(json.dumps({'archives':self.archives}))
        self.calendar=self.root/'calendar.json';self.calendar.write_text(json.dumps(self.records))
        self.daily=self.root/'daily.csv';self.write_daily()

    def write_daily(self):
        import csv,hashlib,io,json
        from tools.validate_official_history import DAILY_CSV_COLUMNS
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=DAILY_CSV_COLUMNS)
        writer.writeheader();writer.writerows(self.daily_rows);raw=stream.getvalue().encode('cp950')
        self.daily.write_bytes(raw)
        (self.root/'daily-source.json').write_text(json.dumps({'source_url':'https://www.taifex.com.tw/test-fixture',
                                                             'sha256':hashlib.sha256(raw).hexdigest()}))

    def load(self, **overrides):
        from tools.validate_official_history import load_verified_range
        options=dict(start='2026-10-06',end='2026-10-07',contract_id=CONTRACT,calendar_path=self.calendar,
                     calendar_version='synthetic-range-test',daily_csv=[self.daily],as_of='2026-10-09T00:00:00Z')
        options.update(overrides)
        return load_verified_range(self.root,**options)

    def test_repeat_exact_data_hash_and_never_ranking(self):
        first,report=self.load();second,_=self.load()
        self.assertEqual(first.manifest['data_hash'],second.manifest['data_hash'])
        self.assertEqual(report['bars'],4)
        self.assertEqual(report['trading_days'],2)
        self.assertFalse(report['ranking_eligible'])
        self.assertFalse(first.manifest['ranking_eligible'])

    def test_omit_calendar_day_not_silently_accepted(self):
        import json
        self.calendar.write_text(json.dumps(self.records[:1]))
        with self.assertRaisesRegex(ValidationError,'session or trading-date set mismatch'):self.load()

    def test_omit_daily_day_not_silently_accepted(self):
        self.daily_rows.pop();self.write_daily()
        with self.assertRaisesRegex(ValidationError,'session or trading-date set mismatch'):self.load()

    def test_omit_archive_day_not_silently_accepted(self):
        import json
        (self.root/'latest.json').write_text(json.dumps({'archives':self.archives[:1]}))
        with self.assertRaisesRegex(ValidationError,'cache/calendar trading-date set mismatch'):self.load()

    def test_one_missing_minute_rejects_entire_range(self):
        import hashlib,json,zipfile
        r=self.archives[-1];file=Path(r['files'][0]['path']);raw=file.read_bytes().splitlines(keepends=True)
        raw=b''.join(raw[:-1]);file.write_bytes(raw)
        r['files'][0]['sha256']=hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(r['archive_path'],'w') as z:z.writestr(file.name,raw)
        r['sha256']=hashlib.sha256(Path(r['archive_path']).read_bytes()).hexdigest()
        (self.root/'latest.json').write_text(json.dumps({'archives':self.archives}))
        with self.assertRaisesRegex(ValidationError,'2026-10-07: rejected incomplete'):self.load()

    def test_wrong_daily_ohlc_rejected(self):
        self.daily_rows[0]['收盤價']='20002';self.write_daily()
        with self.assertRaisesRegex(ValidationError,'OHLC mismatch'):self.load()

    def test_tampered_daily_hash_rejected(self):
        self.daily.write_bytes(self.daily.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValidationError,'source hash mismatch'):self.load()

    def test_future_session_rejected(self):
        with self.assertRaisesRegex(ValidationError,'as-of cutoff'):self.load(as_of='2026-10-06T00:46:00Z')

    def test_duplicate_daily_session_rejected(self):
        self.daily_rows.append(dict(self.daily_rows[0]));self.write_daily()
        with self.assertRaisesRegex(ValidationError,'duplicate daily'):self.load()


if __name__ == '__main__':
    unittest.main()

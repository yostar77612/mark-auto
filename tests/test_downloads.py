import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from quantlab import downloads as d
from quantlab.core import ValidationError
from quantlab.__main__ import parser, execute

URL = 'https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_2026_10_12.zip'
PAGE = ('<input onclick="window.open(\'' + URL + '\')">').encode()


def zip_bytes(name='Daily_2026_10_12.csv', content=b'a,b\n1,2\n', mode=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo(name)
        info.compress_type = zipfile.ZIP_DEFLATED
        if mode is not None:
            info.external_attr = mode << 16
        z.writestr(info, content)
    return stream.getvalue()


class Response(io.BytesIO):
    def __init__(self, raw, url, headers=None, status=200):
        super().__init__(raw)
        self.url, self.headers, self.status = url, headers or {}, status

    def geturl(self):
        return self.url


class DownloadTests(unittest.TestCase):
    def test_discovery_observed_only_and_future_date(self):
        records = d.discover(PAGE + PAGE + b'https://evil.example/Daily_2026_10_13.zip')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['trade_date'], '2026-10-12')
        self.assertEqual(records[0]['source_url'], URL)
        with self.assertRaises(ValidationError):
            d.discover(b'<html>site changed</html>')

    def test_reject_nonofficial_urls_and_redirects(self):
        for url in ('http://www.taifex.com.tw/a', 'https://www.taifex.com.tw.evil/a',
                    'https://user@www.taifex.com.tw/a', 'https://www.taifex.com.tw:444/a'):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                d.official_url(url)
        with self.assertRaises(ValidationError):
            d.fetch(URL, limit=9, transport=lambda *a: Response(b'x', 'https://evil.example'))
        with self.assertRaises(ValidationError):
            d._OfficialRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example')

    def test_stream_and_header_limits(self):
        for raw, headers, status in ((b'0123456789', {}, 200), (b'x', {'Content-Length': '100'}, 200),
                                     (b'x', {'Content-Length': '2'}, 200), (b'x', {'Content-Length': '-1'}, 200),
                                     (b'x', {'Content-Encoding': 'gzip'}, 200), (b'x', {}, 404)):
            with self.subTest(headers=headers, status=status), self.assertRaises(ValidationError):
                d.fetch(URL, limit=9, transport=lambda *a: Response(raw, URL, headers, status))

    def test_archive_attacks(self):
        for name, mode in (('../x.csv', None), ('/x.csv', None), ('dir/x.csv', None),
                           ('x.exe', None), ('x\\y.csv', None), ('x.csv', stat.S_IFLNK | 0o777)):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                d.inspect_archive(zip_bytes(name=name, mode=mode), 'csv')
        with self.assertRaises(ValidationError):
            d.inspect_archive(zip_bytes(content=b'0' * 1_000_000), 'csv')
        with self.assertRaises(ValidationError):
            d.inspect_archive(b'not a zip', 'csv')
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            for n in range(d.MAX_MEMBERS + 1):
                z.writestr(f'{n}.csv', b'a')
        with self.assertRaises(ValidationError):
            d.inspect_archive(out.getvalue(), 'csv')

    def test_expansion_and_total_time_limits(self):
        with patch.object(d, 'MAX_EXPANDED', 3), self.assertRaises(ValidationError):
            d.inspect_archive(zip_bytes(content=b'1234'), 'csv')
        with patch.object(d.time, 'monotonic', side_effect=[0, 91]), self.assertRaises(ValidationError):
            d.fetch(URL, limit=9, transport=lambda *a: Response(b'x', URL))
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('x.csv', b'a')
            z.writestr('X.csv', b'a')
        with self.assertRaises(ValidationError):
            d.inspect_archive(out.getvalue(), 'csv')

    def test_refresh_idempotence_revisions_corruption_and_provisional(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, archive = [], [zip_bytes()]
            def transport(url, timeout):
                calls.append(url)
                return Response(PAGE if url == d.SOURCE_URL else archive[0], url)
            first = d.refresh(tmp, transport=transport)
            row = first['archives'][0]
            self.assertFalse(row['ranking_eligible'])
            self.assertEqual(row['completion_status'], 'provisional_unverified')
            Path(row['archive_path']).write_bytes(b'corrupted')
            second = d.refresh(tmp, transport=transport)
            self.assertEqual(first['archives'], second['archives'])
            self.assertEqual(Path(row['archive_path']).read_bytes(), archive[0])
            self.assertEqual(calls, [d.SOURCE_URL, URL] * 2)
            archive[0] = zip_bytes(content=b'a,b\n1,3\n')
            third = d.refresh(tmp, transport=transport)
            self.assertNotEqual(row['sha256'], third['archives'][0]['sha256'])
            self.assertTrue(Path(row['archive_path']).exists())
            self.assertEqual(json.loads((Path(tmp) / 'latest.json').read_text())['archives'], third['archives'])

    def test_failure_preserves_latest_and_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            latest = Path(tmp) / 'latest.json'
            latest.write_text('previous')
            with self.assertRaises(ValidationError):
                d.refresh(tmp, transport=lambda url, _: Response(PAGE if url == d.SOURCE_URL else b'bad', url))
            self.assertEqual(latest.read_text(), 'previous')
            target = Path(tmp) / 'target'
            target.write_text('safe')
            link = Path(tmp) / 'link'
            link.symlink_to(target)
            with self.assertRaises(ValidationError):
                d._atomic_write(link, b'bad')
            self.assertEqual(target.read_text(), 'safe')

    def test_cli_no_network_until_execute_and_bounds(self):
        for command in ('refresh', 'download'):
            args = parser().parse_args([command, '--cache', '/tmp/test', '--days', '2', '--format', 'rpt'])
            with patch('quantlab.downloads.refresh', return_value={'ok': True}) as refresh:
                self.assertEqual(execute(args), {'ok': True})
                refresh.assert_called_once_with(Path('/tmp/test'), days=2, kind='rpt')
        for days in (0, 31, True):
            with self.assertRaises(ValidationError):
                d.refresh('/tmp/test', days=days)


if __name__ == '__main__':
    unittest.main()

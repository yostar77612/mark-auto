"""Explicit official RAW daily/cache import; no runtime or automatic downloads.

Offline: python -m tools.import_official_daily --cache ABSOLUTE_DB --instrument
TWSE:6225 --start 2025-06-11 --end 2025-06-13 --manifest MANIFEST.json
Download additionally requires --consent-download and a new --archive directory.
The end is exclusive. Market-calendar completeness is checked by the daily source,
not inferred by this tool from the rows that happened to trade.
"""

import argparse
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from quantlab.trading.adapters.official.daily_signal_events import parse_daily_signal_events
from quantlab.trading.adapters.official.stock_data import MAX_BYTES, StockDataSource, parse_daily, stock_identity
from quantlab.trading.adapters.storage.kline_store import KlineStore
from quantlab.trading.application.stock_history import StockHistorySync
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.stock_history import OfficialPayload
from quantlab.trading.runtime.official_daily_source import _source_scope
from quantlab.trading.runtime.stock_history import fetch_stock_official

MAX_TOTAL_BYTES = 64 * 1024 * 1024


def _scope(payload):
    parts = urlsplit(payload.source_url)
    query = parse_qs(parts.query, strict_parsing=True)
    instrument = 'TWSE:' + query['stockNo'][0] if 'stockNo' in query else 'TWSE:2330'
    stock_identity(instrument)
    return instrument, _source_scope(payload.source_url, instrument)


def load_manifest(path: Path) -> tuple[OfficialPayload, ...]:
    """Read local public-response bytes, verifying the manifest before any DB write."""
    try:
        raw_manifest = path.read_bytes()
        if len(raw_manifest) > 1024 * 1024:
            raise ValueError('manifest size')
        documents = json.loads(raw_manifest)['documents']
        if not isinstance(documents, list) or not 1 <= len(documents) <= 242:
            raise ValueError('manifest documents')
        result, total, seen = [], 0, set()
        for document in documents:
            filename = document['file']
            if not isinstance(filename, str) or Path(filename).name != filename or filename in ('', '.', '..'):
                raise ValueError('manifest file must be adjacent')
            payload_path = path.parent / filename
            if payload_path.is_symlink() or not 0 < payload_path.stat().st_size <= MAX_BYTES:
                raise ValueError('payload file/size')
            raw = payload_path.read_bytes()
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                raise ValueError('manifest total bytes')
            if sha256(raw).hexdigest() != document['sha256']:
                raise ValueError('payload digest differs')
            payload = OfficialPayload(document['url'], document['sha256'], raw)
            _scope(payload)
            key = payload.source_url, payload.digest
            if key in seen:
                raise ValueError('duplicate source')
            seen.add(key)
            result.append(payload)
        return tuple(result)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, DomainError):
        raise DomainError('official_stock_invalid', 'local official manifest refused; cache unchanged') from None


class OfficialDailyImportSource:
    """Only the supplied, unambiguous monthly and complete TWT49U inputs are used."""

    def __init__(self, payloads):
        self.payloads = payloads

    def month(self, instrument_id, month):
        candidates = [p for p in self.payloads if _scope(p) == (instrument_id, ('daily', month, None))]
        if len(candidates) != 1:
            raise DomainError('official_stock_invalid', 'one explicit monthly response required')
        payload = candidates[0]
        rows = parse_daily(payload.raw, instrument_id, month)
        _monthly_identity(payload, instrument_id)
        return rows, payload

    def events(self, instrument_id, start, end):
        candidates = []
        for payload in self.payloads:
            _, (kind, first, stop) = _scope(payload)
            if kind == 'global_events' and first <= start and stop >= end:
                candidates.append(payload)
        if len(candidates) != 1:
            raise DomainError('official_stock_invalid', 'one complete TWT49U response required, including no-event ranges')
        payload = candidates[0]
        events = parse_daily_signal_events(payload.raw, instrument_id, payload.source_url)
        return tuple(row for row in events if start <= row.ex_date < end), payload


def daily_events_url(start: date, end: date) -> str:
    return f'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={start:%Y%m%d}&endDate={end - timedelta(days=1):%Y%m%d}&response=json'


def _monthly_identity(payload, instrument_id):
    # The native response identifies its stock independently of the request URL.
    # parse_daily has already checked bounded JSON/native rows before this read.
    title = json.loads(payload.raw.decode('utf-8-sig')).get('title')
    code = stock_identity(instrument_id)[1]
    if not isinstance(title, str) or not re.search(r'(?<!\d)' + code + r'(?!\d)', title):
        raise DomainError('official_stock_invalid', 'monthly response stock identity differs')


class _DownloadSource:
    def __init__(self, transport):
        self.transport = transport
        self.daily = StockDataSource(transport)

    def month(self, instrument_id, month):
        rows, payload = self.daily.month(instrument_id, month)
        _monthly_identity(payload, instrument_id)
        return rows, payload

    def events(self, instrument_id, start, end):
        url = daily_events_url(start, end)
        raw = self.transport(url)
        return parse_daily_signal_events(raw, instrument_id, url), OfficialPayload(url, sha256(raw).hexdigest(), raw)


class _CollectedBatch:
    def import_daily(self, batch):
        self.batch = batch


def _archive(path: Path, batch, received_at: datetime):
    """Create a replayable archive without replacing an existing recording."""
    path.mkdir(parents=True, exist_ok=False)
    documents = []
    for number, payload in enumerate(batch.payloads):
        filename = f'{number:03d}-{payload.digest}.json'
        (path / filename).write_bytes(payload.raw)
        documents.append({'file': filename, 'url': payload.source_url, 'sha256': payload.digest})
    (path / 'manifest.json').write_text(
        json.dumps({'retrieved_at': received_at.isoformat(), 'documents': documents}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )


def import_official_daily(
    cache: Path,
    instrument_id: str,
    start: date,
    end: date,
    *,
    manifest: Path | None = None,
    consent_download: bool = False,
    archive: Path | None = None,
    transport=fetch_stock_official,
    clock=None,
):
    """Validate all inputs first, then publish one atomic RAW daily/event batch."""
    if stock_identity(instrument_id)[0] != 'TWSE':
        raise DomainError('official_stock_invalid', 'this importer requires verified TWSE TWT49U evidence')
    if manifest is None and consent_download is not True:
        raise DomainError('official_stock_consent_required')
    if manifest is None and (archive is None or archive.exists()):
        raise DomainError('official_stock_invalid', 'a new raw archive directory is required')
    now = clock or (lambda: datetime.now(timezone.utc))
    observed = now()
    source = OfficialDailyImportSource(load_manifest(manifest)) if manifest is not None else _DownloadSource(transport)
    collected = _CollectedBatch()
    batch = StockHistorySync(collected, source).refresh(instrument_id, start, end, today=observed.astimezone(ZoneInfo('Asia/Taipei')).date(), consent=True)
    material = json.dumps(sorted((payload.source_url, payload.digest) for payload in batch.payloads), separators=(',', ':'), ensure_ascii=True)
    source_digest = sha256(material.encode()).hexdigest()
    if manifest is None:
        _archive(archive, batch, now())
    with closing(KlineStore(cache, arrival_clock=now)) as store:
        store.import_daily(batch)
        warning = store.warning_code
    return {
        'status': 'IMPORTED',
        'instrument_id': instrument_id,
        'start': start.isoformat(),
        'end_exclusive': end.isoformat(),
        'bars': len(batch.bars),
        'events': len(batch.events),
        'source_digest': source_digest,
        'cache_warning': warning,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True, type=lambda value: Path(value).absolute())
    parser.add_argument('--instrument', required=True)
    parser.add_argument('--start', required=True, type=date.fromisoformat)
    parser.add_argument('--end', required=True, type=date.fromisoformat)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--consent-download', action='store_true')
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args(argv)
    try:
        result = import_official_daily(
            args.cache, args.instrument, args.start, args.end, manifest=args.manifest, consent_download=args.consent_download, archive=args.archive
        )
    except DomainError as exc:
        print(json.dumps({'status': 'REFUSED', 'code': exc.code}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

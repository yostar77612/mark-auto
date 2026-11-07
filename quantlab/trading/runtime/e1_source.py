"""Host-only official HTTPS capture; no imported source labels confer authority.

The transport is fixed code, never a handler/module/URL supplied by a model. Tests
mock the transport; the application has no fixture producer or fallback endpoint.
"""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import HTTPRedirectHandler, Request, build_opener

from quantlab.core import canonical_json, content_hash
from quantlab.data import import_taifex, validate_dataset
from quantlab.strict_json import loads
from quantlab.trading.runtime.e1_protocol import SOURCE_URL, calendar_for, is_hash, refuse, timestamp

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
FIELDS = ('Date', 'Contract', 'ContractMonth(Week)', 'Open', 'High', 'Low', 'Last', 'Volume', 'TradingSession')
SESSIONS = {'day': '\u4e00\u822c', 'night': '\u76e4\u5f8c'}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        refuse()


def fetch_daily():
    """One bounded request, no retry, credentials, user parameters or logging."""
    request = Request(SOURCE_URL, headers={'Accept': 'application/json', 'User-Agent': 'MarkAuto-E1/1'})
    with build_opener(_NoRedirect()).open(request, timeout=10) as response:
        if response.status != 200 or response.geturl() != SOURCE_URL or response.headers.get_content_type() != 'application/json':
            refuse()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        refuse()
    return raw


def projected_rows(raw, plan, request_started_at):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_RESPONSE_BYTES:
        refuse()
    rows = loads(raw.decode('utf-8-sig'))
    if type(rows) is not list or len(rows) > 10000:
        refuse()
    calendar = calendar_for(plan)
    keys = {(row['trade_date'].replace('-', ''), SESSIONS[row['session']]): index for index, row in enumerate(calendar.sessions)}
    selected = {}
    for row in rows:
        if type(row) is not dict:
            refuse()
        if row.get('Contract') != 'TMF' or row.get('ContractMonth(Week)') != plan['contract_id'][-6:]:
            continue
        slot = keys.get((row.get('Date'), row.get('TradingSession')))
        if slot is None or calendar.sessions[slot]['end'] > request_started_at:
            continue
        if slot in selected or any(type(row.get(key)) is not str or len(row[key]) > 128 for key in FIELDS):
            refuse()
        selected[slot] = {key: row[key] for key in FIELDS}
    return selected, hashlib.sha256(raw).hexdigest()


def captured_dataset(plan, captures):
    """Only the durable, host-captured exact planned sessions enter evaluation."""
    calendar = calendar_for(plan)
    if [row[0] for row in captures] != list(range(len(calendar.sessions))):
        refuse()
    payload = []
    bindings = []
    for slot, encoded, captured_at, digest in captures:
        captured = loads(encoded)
        if (
            type(captured) is not dict
            or set(captured) != {'row', 'response_digest'}
            or not is_hash(captured['response_digest'])
            or content_hash(captured) != digest
            or timestamp(captured_at) < calendar.sessions[slot]['end']
        ):
            refuse()
        payload.append(captured['row'])
        bindings.append({'slot': slot, 'captured_at': captured_at, 'digest': digest})
    # Reuse the original importer/validation; no alternate OHLC/DSL interpreter.
    with TemporaryDirectory(prefix='markauto-e1-') as temporary:
        path = Path(temporary) / 'captured.json'
        path.write_text(canonical_json(payload), encoding='utf-8')
        kind = 'daily_json' if plan['evidence_mode'] == 'production' else 'synthetic_daily_json'
        dataset = import_taifex(path, kind=kind, calendar=calendar, contract_id=plan['contract_id'])
    validate_dataset(dataset)
    expected = [(row['open'], row['end'], row['trade_date'], row['session'], plan['contract_id']) for row in calendar.sessions]
    actual = [(bar.timestamp, bar.end, bar.trade_date, bar.session, bar.contract_id) for bar in dataset.bars]
    if actual != expected or dataset.quality.get('missing_intervals', 0) or dataset.quality.get('session_coverage_gaps'):
        refuse()
    binding = {
        'data_hash': dataset.manifest['data_hash'],
        'source_hash': dataset.manifest['source_hash'],
        'calendar_hash': calendar.hash,
        'capture_hash': content_hash(bindings),
        'source_type': dataset.manifest['source_type'],
        'bar_count': len(dataset.bars),
    }
    return dataset, binding

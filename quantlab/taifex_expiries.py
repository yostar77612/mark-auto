"""Offline, validated final settlement dates; never derive a calendar or date."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

DATA_PATH = Path(__file__).with_name('data_files') / 'taifex_expiries.json'
OFFICIAL_URL = 'https://www.taifex.com.tw/cht/5/futIndxFSP'
RETRIEVAL_METHOD = 'raw HTML table parsed; rows where the TX/MTX/TMF final-settlement-price column is numeric'


def _iso(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid expiry provenance date')
    date.fromisoformat(value)


def validate_data(value):
    """Reject incomplete, ambiguous or unverified records before exposing any row."""
    try:
        if not isinstance(value['data_version'], str) or not value['data_version'].strip():
            raise ValueError('missing data version')
        _iso(value['verified_date'])
        if value['status'] != 'verified' or value['products'] != ['TX', 'MTX', 'TMF']:
            raise ValueError('unverified expiry data')
        sources = value['sources']
        if not isinstance(sources, list) or not sources:
            raise ValueError('missing expiry sources')
        for source in sources:
            url = urlsplit(source['url'])
            if (
                url.scheme != 'https'
                or url.hostname not in ('taifex.com.tw', 'www.taifex.com.tw')
                or url.username
                or url.password
                or url.port not in (None, 443)
            ):
                raise ValueError('non-official expiry source')
            _iso(source['retrieval_date'])
            if not source['retrieval_method'].strip() or not re.fullmatch(r'[a-f0-9]{64}', source['sha256']):
                raise ValueError('missing expiry provenance')
        months = set()
        if not isinstance(value['expiries'], list) or not value['expiries']:
            raise ValueError('missing expiry rows')
        for row in value['expiries']:
            month = row['contract_month']
            if not re.fullmatch(r'[0-9]{4}(?:0[1-9]|1[0-2])', month) or month[:4] == '0000' or month in months:
                raise ValueError('invalid or duplicate contract month')
            months.add(month)
            _iso(row['expiry_date'])
            if row['status'] != 'verified' or type(row['source_index']) is not int or not 0 <= row['source_index'] < len(sources):
                raise ValueError('unverified expiry row')
        calendar = value['trading_calendar']
        if calendar['status'] != 'not_bundled' or not calendar['reason'].strip():
            raise ValueError('trading calendar must not be inferred')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('incomplete expiry data') from exc
    return deepcopy(value)


def load_expiries(path=DATA_PATH):
    return validate_data(json.loads(Path(path).read_text(encoding='utf-8')))


def lookup_expiry(product, contract_month, *, data=None):
    """Return date and detached provenance, or None outside explicit coverage."""
    data = load_expiries() if data is None else validate_data(data)
    if product not in data['products']:
        return None
    for row in data['expiries']:
        if row['contract_month'] == contract_month:
            return {
                'expiry_date': row['expiry_date'],
                'data_version': data['data_version'],
                'verified_date': data['verified_date'],
                'source': deepcopy(data['sources'][row['source_index']]),
            }
    return None

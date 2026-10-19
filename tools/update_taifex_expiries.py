"""Manual online maintenance only. Tests use saved HTML, never this command."""

import argparse
from datetime import date
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quantlab.taifex_expiries import DATA_PATH, OFFICIAL_URL, RETRIEVAL_METHOD, validate_data


class SettlementTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.rows.append(None)
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'table':
            self.rows.append(None)
        elif tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_expiries(html):
    """Only monthly rows with numeric TX/MTX/TMF prices in the named table."""
    parser = SettlementTable()
    parser.feed(html)
    column = None
    found = {}
    for cells in parser.rows:
        if cells is None:
            column = None
            continue
        header = next((i for i, cell in enumerate(cells) if re.search(r'TX\s*/\s*MTX\s*/\s*TMF', cell)), None)
        if header is not None:
            column = header
            continue
        if column is None or len(cells) <= max(1, column):
            continue
        day, month = cells[:2]
        if not re.fullmatch(r'\d{6}', month) or not re.fullmatch(r'\d+(?:\.\d+)?', cells[column]):
            continue
        if not re.fullmatch(r'\d{4}/\d{2}/\d{2}', day):
            raise ValueError('unexpected settlement date format')
        expiry = date.fromisoformat(day.replace('/', '-')).isoformat()
        if month in found:
            raise ValueError('duplicate monthly settlement row')
        found[month] = expiry
    if not found:
        raise ValueError('no verified monthly TX/MTX/TMF settlements')
    return [{'contract_month': month, 'expiry_date': found[month], 'status': 'verified', 'source_index': 0} for month in sorted(found)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DATA_PATH)
    parser.add_argument('--data-version', required=True)
    args = parser.parse_args()
    with urlopen(OFFICIAL_URL, timeout=30) as response:
        if response.url != OFFICIAL_URL:
            raise ValueError('unexpected source redirect')
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('source too large')
    today = date.today().isoformat()
    value = validate_data(
        {
            'data_version': args.data_version,
            'verified_date': today,
            'status': 'verified',
            'sources': [{'url': OFFICIAL_URL, 'retrieval_date': today, 'retrieval_method': RETRIEVAL_METHOD, 'sha256': hashlib.sha256(raw).hexdigest()}],
            'products': ['TX', 'MTX', 'TMF'],
            'expiries': parse_expiries(raw.decode('utf-8-sig')),
            'trading_calendar': {
                'status': 'not_bundled',
                'reason': 'Official 2026 calendar is a colour-coded PDF that cannot be machine-verified; supply the existing manual calendar.',
            },
        }
    )
    args.output.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()

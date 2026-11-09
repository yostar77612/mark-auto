"""Contract V2 directory cache; all name lookups happen during refresh, never search."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from zoneinfo import ZoneInfo

from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import FIXED_INDICES, WatchInstrument, WatchKind
from .sdk import sdk_text, sdk_value
from .sdk_facade import ShioajiSDKFacade


VERSION = 2


class SymbolDirectory:
    def __init__(self, path: Path):
        self.path = path
        self.fetched_at: datetime | None = None
        self.items = FIXED_INDICES
        self.refresh_seconds = 0.0
        self.load()

    def load(self) -> tuple[WatchInstrument, ...]:
        try:
            body = json.loads(self.path.read_text(encoding='utf-8'))
            if body['version'] != VERSION:
                # A version 1 cache has no industry codes: treat it as missing so the next refresh rebuilds it.
                raise ValueError('directory version')
            fetched = datetime.fromisoformat(body['fetched_at'])
            if fetched.tzinfo is None:
                raise ValueError('directory timestamp')
            items = tuple(WatchInstrument(row[0], WatchKind(row[1]), *row[2:]) for row in body['items'])
        except (OSError, ValueError, KeyError, TypeError, IndexError, DomainError):
            return self.items
        self.fetched_at = fetched
        self.items = tuple({item.instrument_id: item for item in (*items, *FIXED_INDICES)}.values())
        return self.items

    def refresh(self, facade: ShioajiSDKFacade, now: datetime) -> tuple[WatchInstrument, ...]:
        zone = ZoneInfo('Asia/Taipei')
        if self.fetched_at is not None and self.fetched_at.astimezone(zone).date() == now.astimezone(zone).date():
            return self.items
        started = perf_counter()
        items = []
        for security in ('STK', 'IND'):
            for base in facade.market_contracts(security):
                code = sdk_text(sdk_value(base, 'code'))
                exchange = sdk_text(sdk_value(base, 'exchange'))
                if security == 'STK' and exchange not in ('TSE', 'OTC'):
                    continue
                if security == 'STK' and not (len(code) == 4 and code.isdigit() or code.startswith('00') and len(code) in (5, 6)):
                    continue
                info = facade.market_contract_info(base)
                name = sdk_text(sdk_value(info, 'name'))
                kind = WatchKind.INDEX if security == 'IND' else WatchKind.STOCK
                exchange = 'INDEX' if security == 'IND' else exchange
                prefix = {'TSE': 'TWSE', 'OTC': 'TPEX', 'INDEX': 'INDEX'}[exchange]
                category = '' if security == 'IND' else str(getattr(base, 'category', '') or '')
                items.append(WatchInstrument(f'{prefix}:{code}', kind, exchange, code, name, category))
        self.refresh_seconds = perf_counter() - started
        result = tuple({item.instrument_id: item for item in (*items, *FIXED_INDICES)}.values())
        body = {
            'version': VERSION,
            'fetched_at': now.astimezone(timezone.utc).isoformat(),
            'items': [[i.instrument_id, i.kind.value, i.exchange, i.code, i.name, i.category] for i in result],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.items, self.fetched_at = result, now
        return result

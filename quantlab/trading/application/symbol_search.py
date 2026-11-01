"""Deterministic local directory search; never performs SDK or file IO."""

import unicodedata
from quantlab.trading.domain.watch import WatchInstrument


def normalize_search(value: str) -> str:
    return unicodedata.normalize('NFKC', value).strip().casefold()


def search_symbols(items: tuple[WatchInstrument, ...], query: str, limit: int = 20) -> tuple[WatchInstrument, ...]:
    needle = normalize_search(query)
    if not needle:
        return ()
    ranked = []
    for item in items:
        code, name = normalize_search(item.code), normalize_search(item.name)
        if code == needle:
            rank = 0
        elif code.startswith(needle):
            rank = 1
        elif name.startswith(needle):
            rank = 2
        elif needle in name:
            rank = 3
        else:
            continue
        ranked.append((rank, code, item))
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return tuple(entry[2] for entry in ranked[:limit])

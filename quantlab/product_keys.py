"""Display-only futures aliases. Unknown values (including non-strings) pass through.

Exact, case-sensitive tables: TX/TXF -> TXF, MTX/MXF -> MXF, TMF -> TMF.
January..December use A..L; futures year suffixes are exactly one digit 0..9.
R1/R2 are the only continuous suffixes. No prefix guessing: options, weekly
contracts, strike/call-put suffixes and malformed keys remain unchanged.
TAIFEX:product:YYYYMM monthly display identities use the same month table as
taifex_expiries (01..12); this recognizes syntax, never invents expiry dates.
"""

import re

PRODUCT_KEYS = {'TX': 'TXF', 'TXF': 'TXF', 'MTX': 'MXF', 'MXF': 'MXF', 'TMF': 'TMF'}
MONTH_CODES = dict(zip(('01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12'), 'ABCDEFGHIJKL'))


def converge_key(symbol, enabled=True):
    """Return a futures product key, default on; disabled returns the input itself.

    Non-bool enabled values raise ValueError. All unrecognized inputs retain
    their original value and identity, without stripping or case conversion.
    """
    if type(enabled) is not bool:
        raise ValueError('convergence requires a boolean')
    if not enabled or not isinstance(symbol, str):
        return symbol
    match = re.fullmatch(r'(TXF|MXF|TMF|MTX|TX)(?:[A-L][0-9]|R[12])?', symbol)
    if match:
        return PRODUCT_KEYS[match[1]]
    match = re.fullmatch(r'TAIFEX:(TX|MTX|TMF):([0-9]{4})([0-9]{2})', symbol)
    if match and match[2] != '0000' and match[3] in MONTH_CODES:
        return PRODUCT_KEYS[match[1]]
    return symbol


def symbol_aliases(key):
    """Finite legacy code aliases, allowing pre-B9 stores to share drawings."""
    return tuple(
        prefix + suffix
        for prefix, product in PRODUCT_KEYS.items()
        if product == key
        for suffix in ('', 'R1', 'R2', *(month + year for month in MONTH_CODES.values() for year in '0123456789'))
    )

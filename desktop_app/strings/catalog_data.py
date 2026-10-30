"""Assemble feature data in original mutation and insertion order."""

from itertools import chain
from .translation_parts import PARTS as _TRANSLATION_PARTS
from .alias_parts import PARTS as _ALIAS_PARTS

ZH_TW_CHUNKS = {}
for phase, order, key, value in sorted(chain.from_iterable(_TRANSLATION_PARTS), key=lambda row: row[1]):
    ZH_TW_CHUNKS.setdefault(phase, {})[key] = value

TEXT_ALIASES = {key: value for order, key, value in sorted(chain.from_iterable(_ALIAS_PARTS))}

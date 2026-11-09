"""User-editable concept groups: validation and the seed merge that never overwrites the user's edits."""

from dataclasses import dataclass

from .concept_groups import ConceptGroup
from .sector import eligible_stock
from .validation import DomainError

MAX_GROUPS = 60
MAX_CODES = 60
MAX_NAME = 20


@dataclass(frozen=True)
class GroupRecord:
    id: str
    name: str
    codes: tuple[str, ...]
    builtin: bool = False
    edited: bool = False
    deleted: bool = False


def clean_name(name: str) -> str:
    text = name.strip() if isinstance(name, str) else ''
    if not text or len(text) > MAX_NAME or any(ord(char) < 32 for char in text):
        raise DomainError('validation_failed', 'sector group name')
    return text


def clean_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    """Four-digit ordinary stock codes only; duplicates collapse, order is kept."""
    result = tuple(dict.fromkeys(codes))
    if len(result) > MAX_CODES or any(not isinstance(code, str) or not eligible_stock(code) for code in result):
        raise DomainError('validation_failed', 'sector group codes')
    return result


def from_seed(group: ConceptGroup) -> GroupRecord:
    return GroupRecord(group.id, group.name, group.codes, builtin=True)


def merge_seed(stored: tuple[GroupRecord, ...], seed: tuple[ConceptGroup, ...]) -> tuple[GroupRecord, ...]:
    """Update only built-in groups the user has not touched; keep edited/deleted ones and all custom groups."""
    seeds = {group.id: group for group in seed}
    result, seen = [], set()
    for record in stored:
        if not record.builtin:
            result.append(record)
        elif record.id in seeds:
            seen.add(record.id)
            result.append(record if record.edited or record.deleted else from_seed(seeds[record.id]))
        elif record.edited:
            result.append(record)
    result.extend(from_seed(group) for group in seed if group.id not in seen)
    return tuple(result)


def concepts(records: tuple[GroupRecord, ...]) -> tuple[ConceptGroup, ...]:
    return tuple(ConceptGroup(record.id, record.name, record.codes) for record in records if not record.deleted)

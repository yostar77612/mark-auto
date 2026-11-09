"""Atomic JSON store for concept groups; a corrupt file is preserved and the built-in list takes over."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from quantlab.trading.domain.concept_groups import BUILTIN_GROUPS, SEED_VERSION, ConceptGroup
from quantlab.trading.domain.sector_groups import MAX_GROUPS, GroupRecord, clean_codes, clean_name, concepts, from_seed, merge_seed
from quantlab.trading.domain.validation import DomainError


class SectorGroupStore:
    def __init__(self, path: Path, seed: tuple[ConceptGroup, ...] = BUILTIN_GROUPS, seed_version: int = SEED_VERSION):
        self.path, self.seed, self.seed_version = path, seed, seed_version
        self.lock = RLock()
        self.warning = ''
        self._records = self._load()

    # --- persistence ---------------------------------------------------
    def _load(self) -> tuple[GroupRecord, ...]:
        try:
            body = json.loads(self.path.read_text(encoding='utf-8'))
            if body['version'] != 1 or type(body['seed_version']) is not int or len(body['groups']) > MAX_GROUPS * 2:
                raise ValueError('sector group file version/limit')
            records = tuple(
                GroupRecord(
                    str(row['id']),
                    clean_name(row['name']),
                    clean_codes(tuple(row['codes'])),
                    row['builtin'] is True,
                    row['edited'] is True,
                    row.get('deleted') is True,
                )
                for row in body['groups']
            )
            if len({record.id for record in records}) != len(records):
                raise ValueError('duplicate sector group id')
        except FileNotFoundError:
            return self._write_initial(tuple(from_seed(group) for group in self.seed))
        except (ValueError, TypeError, KeyError, UnicodeError, DomainError):
            self._preserve_bad_file()
            return self._write_initial(tuple(from_seed(group) for group in self.seed))
        except OSError:
            self.warning = 'sector_groups_unreadable'
            return tuple(from_seed(group) for group in self.seed)
        if body['seed_version'] < self.seed_version:
            merged = merge_seed(records, self.seed)
            self._records = merged
            self._save()
            return merged
        return records

    def _preserve_bad_file(self) -> None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        try:
            self.path.rename(self.path.with_name(self.path.name + '.bad-' + stamp))
        except OSError:
            pass
        self.warning = 'sector_groups_corrupt'

    def _write_initial(self, records: tuple[GroupRecord, ...]) -> tuple[GroupRecord, ...]:
        self._records = records
        try:
            self._save()
        except DomainError:
            self.warning = self.warning or 'sector_groups_unwritable'
        return records

    def _save(self) -> None:
        body = {
            'version': 1,
            'seed_version': self.seed_version,
            'groups': [
                {
                    'id': item.id,
                    'name': item.name,
                    'codes': list(item.codes),
                    'builtin': item.builtin,
                    'edited': item.edited,
                    **({'deleted': True} if item.deleted else {}),
                }
                for item in self._records
            ],
        }
        temporary = self.path.with_name(self.path.name + '.' + uuid4().hex + '.tmp')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.path)
        except OSError:
            raise DomainError('sector_groups_unwritable', 'write sector groups') from None
        finally:
            temporary.unlink(missing_ok=True)

    def _commit(self, records: tuple[GroupRecord, ...]) -> None:
        """Memory changes only after the disk write succeeded."""
        previous, self._records = self._records, records
        try:
            self._save()
        except DomainError:
            self._records = previous
            raise

    # --- reads ---------------------------------------------------------
    def records(self) -> tuple[GroupRecord, ...]:
        with self.lock:
            return self._records

    def groups(self) -> tuple[ConceptGroup, ...]:
        return concepts(self.records())

    def _find(self, group_id: str) -> GroupRecord:
        record = next((item for item in self._records if item.id == group_id), None)
        if record is None:
            raise DomainError('validation_failed', 'sector group not found')
        return record

    def _replace(self, record: GroupRecord) -> None:
        self._commit(tuple(record if item.id == record.id else item for item in self._records))

    # --- edits ---------------------------------------------------------
    def create(self, name: str, codes: tuple[str, ...] = ()) -> str:
        with self.lock:
            live = [item for item in self._records if not item.deleted]
            if len(live) >= MAX_GROUPS:
                raise DomainError('validation_failed', 'sector group limit')
            name = clean_name(name)
            if any(item.name == name for item in live):
                raise DomainError('validation_failed', 'sector group name in use')
            record = GroupRecord('custom.' + uuid4().hex[:8], name, clean_codes(codes))
            self._commit((*self._records, record))
            return record.id

    def rename(self, group_id: str, name: str) -> None:
        with self.lock:
            record = self._find(group_id)
            name = clean_name(name)
            if any(item.name == name and item.id != group_id and not item.deleted for item in self._records):
                raise DomainError('validation_failed', 'sector group name in use')
            self._replace(GroupRecord(record.id, name, record.codes, record.builtin, record.builtin or record.edited, record.deleted))

    def set_codes(self, group_id: str, codes: tuple[str, ...]) -> None:
        with self.lock:
            record = self._find(group_id)
            self._replace(GroupRecord(record.id, record.name, clean_codes(codes), record.builtin, record.builtin or record.edited, record.deleted))

    def delete(self, group_id: str) -> None:
        with self.lock:
            record = self._find(group_id)
            if record.builtin:
                self._replace(GroupRecord(record.id, record.name, record.codes, True, record.edited, True))
            else:
                self._commit(tuple(item for item in self._records if item.id != group_id))

    def restore(self, group_id: str) -> None:
        with self.lock:
            record = self._find(group_id)
            seed = next((group for group in self.seed if group.id == group_id), None)
            if not record.builtin or seed is None:
                raise DomainError('validation_failed', 'only built-in groups can be restored')
            self._replace(from_seed(seed))

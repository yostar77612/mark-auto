"""Sector alert parameters in the workspace settings, preserving other sections."""

from pathlib import Path
from threading import RLock

from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.domain.sector_alerts import SectorAlertParams
from quantlab.trading.domain.validation import DomainError

SECTION = 'sector_alerts_v1'


class SectorAlertSettings:
    def __init__(self, path: Path, *, lock=None):
        self.store = SettingsStore(path)
        self.lock = lock if lock is not None else RLock()
        self.params = self._load()

    def _load(self) -> SectorAlertParams:
        saved = self.store.load().get(SECTION)
        if not isinstance(saved, dict):
            return SectorAlertParams()
        try:
            return SectorAlertParams.from_dict(saved)
        except (DomainError, ValueError, TypeError, ArithmeticError):
            # Out-of-range or damaged values fall back to the defaults; the file itself is left untouched.
            return SectorAlertParams()

    def get(self) -> SectorAlertParams:
        return self.params

    def save(self, params: SectorAlertParams) -> SectorAlertParams:
        with self.lock:
            body = self.store.load()
            body[SECTION] = params.as_dict()
            try:
                self.store.save(body)
            except OSError:
                raise DomainError('operation_failed', 'sector alert settings write failed') from None
            self.params = params
        return params

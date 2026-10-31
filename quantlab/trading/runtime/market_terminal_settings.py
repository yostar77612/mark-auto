"""Atomic terminal preferences in the workspace settings, preserving other sections."""

from pathlib import Path
from threading import RLock

from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.domain.validation import DomainError, identity


class MarketTerminalSettings:
    def __init__(self, path: Path, *, lock=None):
        self.store = SettingsStore(path)
        self.lock = lock if lock is not None else RLock()
        saved = self.store.load().get('market_terminal_v1', {})
        if not isinstance(saved, dict):
            raise DomainError('validation_failed', 'terminal preferences object')
        watches = saved.get('watchlist', [])
        selected = saved.get('selected', 'INDEX:IX0001')
        if not isinstance(watches, list) or len(watches) != len(set(watches)) or len(watches) > 18:
            raise DomainError('validation_failed', 'terminal watchlist')
        for value in (*watches, selected):
            identity(value)
        self.watchlist, self.selected = tuple(watches), selected

    def _save(self) -> None:
        with self.lock:
            body = self.store.load()
            body['market_terminal_v1'] = {'watchlist': list(self.watchlist), 'selected': self.selected}
            self.store.save(body)

    def save_watchlist(self, value: tuple[str, ...]) -> None:
        previous, self.watchlist = self.watchlist, value
        try:
            self._save()
        except OSError:
            self.watchlist = previous
            raise DomainError('operation_failed', 'terminal preferences write failed') from None

    def save_selected(self, value: str) -> None:
        previous, self.selected = self.selected, value
        try:
            self._save()
        except OSError:
            self.selected = previous
            raise DomainError('operation_failed', 'terminal preferences write failed') from None

"""Atomic terminal preferences in the workspace settings, preserving other sections."""

from pathlib import Path
from threading import RLock

from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.domain.screener import ScreenerParams
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
        self.screener, self._screener_saved = self._load_screener(saved.get('screener'))

    @staticmethod
    def _load_screener(saved) -> tuple[ScreenerParams, bool]:
        if not isinstance(saved, dict):
            return ScreenerParams(), False
        try:
            return ScreenerParams.from_dict(saved), True
        except (DomainError, ValueError, TypeError, ArithmeticError):
            # Out-of-range or damaged thresholds fall back to the defaults; the file itself is left untouched.
            return ScreenerParams(), False

    def _save(self) -> None:
        with self.lock:
            body = self.store.load()
            section = {'watchlist': list(self.watchlist), 'selected': self.selected}
            if self._screener_saved:
                section['screener'] = self.screener.as_dict()
            body['market_terminal_v1'] = section
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

    def save_screener(self, value: ScreenerParams) -> ScreenerParams:
        previous, saved, self.screener, self._screener_saved = self.screener, self._screener_saved, value, True
        try:
            self._save()
        except OSError:
            self.screener, self._screener_saved = previous, saved
            raise DomainError('operation_failed', 'terminal preferences write failed') from None
        return value

"""Runtime watchlist settings adapter; no order operations or market calculations.

Uses the existing atomic SettingsStore, retaining unrelated preferences. The
Application service owns subscription allocation and strategy priority.
"""

from quantlab.desktop_runtime import SettingsStore
from quantlab.trading.application.contracts import UiReceipt
from quantlab.trading.application.errors import ERROR_TABLE
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.application.watchlist import apply_watchlist, prepare_watchlist, restore_watchlist, validate_watchlist


class WatchlistSettings:
    def __init__(self, path):
        self.store = SettingsStore(path)
        saved = self.store.load().get('market_watch_v2')
        if saved is not None and type(saved) is not list:
            raise DomainError('validation_failed', 'watchlist settings array required')
        self.watchlist = None if saved is None else validate_watchlist(tuple(saved))

    def restore(self, engine):
        self.watchlist = restore_watchlist(engine, self.watchlist)

    def save(self, engine, requested):
        try:
            if engine is None:
                raise DomainError('capability_missing', 'connect market data before editing watchlist')
            with engine.lock:
                watches = prepare_watchlist(engine, requested)
                body = self.store.load()
                body['market_watch_v2'] = list(watches)
                self.store.save(body)
                self.watchlist = watches
                apply_watchlist(engine, watches)
            return UiReceipt(True, 'completed', '')
        except DomainError as exc:
            error = ERROR_TABLE[exc.code]
            return UiReceipt(False, exc.code, error.explanation + ' ' + error.action)

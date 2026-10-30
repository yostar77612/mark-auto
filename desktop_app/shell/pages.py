"""Desktop pages and their explicit shell interface."""

from desktop_app.shell.host import PageHost, PageState
from desktop_app.features.market.market import MarketPage
from desktop_app.features.data.data import DataPage
from desktop_app.features.strategy.strategy import StrategyPage
from desktop_app.features.backtest.backtest import BacktestPage

from desktop_app.features.compare.compare import ComparePage
from desktop_app.features.paper.paper import PaperPage
from desktop_app.features.settings.settings import SettingsPage

__all__ = ['PageHost', 'PageState', 'MarketPage', 'DataPage', 'StrategyPage', 'BacktestPage', 'ComparePage', 'PaperPage', 'SettingsPage']

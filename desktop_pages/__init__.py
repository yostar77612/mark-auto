"""Desktop pages and their explicit shell interface."""
from .host import PageHost, PageState
from .market import MarketPage
from .data import DataPage
from .strategy import StrategyPage
from .backtest import BacktestPage

from .compare import ComparePage
from .paper import PaperPage
from .settings import SettingsPage

__all__ = ['PageHost', 'PageState', 'MarketPage', 'DataPage', 'StrategyPage',
           'BacktestPage', 'ComparePage', 'PaperPage', 'SettingsPage']

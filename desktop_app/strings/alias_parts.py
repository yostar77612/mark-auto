"""Feature partitions in original registration order."""

from .aliases.ui.strategy import ENTRIES as _part_ui_strategy
from .aliases.ui.assistant import ENTRIES as _part_ui_assistant
from .aliases.ui.data import ENTRIES as _part_ui_data
from .aliases.ui.analysis import ENTRIES as _part_ui_analysis
from .aliases.ui.shell import ENTRIES as _part_ui_shell
from .aliases.ui.market import ENTRIES as _part_ui_market
from .aliases.ui.walk_forward import ENTRIES as _part_ui_walk_forward
from .aliases.ui.backtest import ENTRIES as _part_ui_backtest
from .aliases.ui.results import ENTRIES as _part_ui_results
from .aliases.ui.paper import ENTRIES as _part_ui_paper
from .aliases.ui.settings import ENTRIES as _part_ui_settings
from .aliases.presentation import ENTRIES as _part_presentation
from .aliases.ui.polish import ENTRIES as _part_ui_polish
from .aliases.forms import ENTRIES as _part_forms
from .aliases.market import ENTRIES as _part_market
from .aliases.chatgpt_ui import ENTRIES as _part_chatgpt_ui
from .aliases.walk_forward import ENTRIES as _part_walk_forward
from .aliases.charts import ENTRIES as _part_charts
from .aliases.desktop import ENTRIES as _part_desktop
from .aliases.automatic_backup import ENTRIES as _part_automatic_backup

PARTS = (
    _part_ui_strategy,
    _part_ui_assistant,
    _part_ui_data,
    _part_ui_analysis,
    _part_ui_shell,
    _part_ui_market,
    _part_ui_walk_forward,
    _part_ui_backtest,
    _part_ui_results,
    _part_ui_paper,
    _part_ui_settings,
    _part_presentation,
    _part_ui_polish,
    _part_forms,
    _part_market,
    _part_chatgpt_ui,
    _part_walk_forward,
    _part_charts,
    _part_desktop,
    _part_automatic_backup,
)

"""Closed command metadata and page identities; no Qt or provider dependencies."""

from dataclasses import dataclass
from weakref import ref as _ref

from desktop_strings import ui_text


# Documented mappings: construction order, then the unchanged visible/keyboard order.
MOUNT_PAGE_ORDER = ('market', 'data', 'strategy', 'backtest', 'compare', 'paper', 'settings')
DEFAULT_PAGE_ORDER = ('data', 'strategy', 'backtest', 'compare', 'paper', 'market', 'settings')


def register_pages(host, page_ids):
    """Capture actual stack widgets once, before any reorder, without owning them."""
    host._page_widgets = {page_id: _ref(host.stack.widget(index)) for page_id, index in zip(page_ids, range(host.stack.count()))}
    state = getattr(host, 'page_state', None)
    if state is not None:
        state._page_widgets = host._page_widgets
        state.navigation = host.navigation
        state.stack = host.stack


def page_widget(host, page_id):
    """Resolve an identity in O(1); absent identities/registries return None."""
    reference = getattr(host, '_page_widgets', {}).get(page_id)
    return reference() if reference is not None else None


def page_index(host, page_id):
    """Return the widget's current stack index, or -1 for an unknown/unmounted id."""
    widget = page_widget(host, page_id)
    return host.stack.indexOf(widget) if widget is not None else -1


def command_row(host, command):
    """Named commands follow identity; retain row for existing Command consumers."""
    return page_index(host, command.page_id) if command.page_id else command.row


@dataclass(frozen=True)
class Command:
    id: str
    label_key: str
    label: str
    handler: str
    alias: str
    row: int = -1
    page_id: str = ''


def command_table():
    return (
        Command('page_1', 'palette.cmd.data', ui_text('palette.cmd.data'), 'navigate', 'data page 1', page_id='data'),
        Command('page_2', 'palette.cmd.strategy', ui_text('palette.cmd.strategy'), 'navigate', 'strategy page 2', page_id='strategy'),
        Command('page_3', 'palette.cmd.backtest', ui_text('palette.cmd.backtest'), 'navigate', 'backtest page 3', page_id='backtest'),
        Command('page_4', 'palette.cmd.compare', ui_text('palette.cmd.compare'), 'navigate', 'compare page 4', page_id='compare'),
        Command('page_5', 'palette.cmd.paper', ui_text('palette.cmd.paper'), 'navigate', 'paper page 5', page_id='paper'),
        Command('page_6', 'palette.cmd.market', ui_text('palette.cmd.market'), 'navigate', 'market page 6', page_id='market'),
        Command('page_7', 'palette.cmd.settings', ui_text('palette.cmd.settings'), 'navigate', 'settings page 7', page_id='settings'),
        Command('refresh', 'palette.cmd.refresh', ui_text('palette.cmd.refresh'), 'refresh', 'refresh'),
        Command('cancel_job', 'palette.cmd.cancel', ui_text('palette.cmd.cancel'), 'cancel_job', 'cancel job'),
        Command('theme', 'palette.cmd.theme', ui_text('palette.cmd.theme'), 'theme', 'theme'),
        Command('privacy', 'palette.cmd.privacy', ui_text('palette.cmd.privacy'), 'privacy', 'privacy'),
        Command('focus_import', 'palette.cmd.import', ui_text('palette.cmd.import'), 'focus_import', 'import data', page_id='data'),
        Command('focus_backtest', 'palette.cmd.run', ui_text('palette.cmd.run'), 'focus_backtest', 'start backtest', page_id='backtest'),
    )

"""Pure, closed command metadata; no Qt, account data or provider dependencies."""

from dataclasses import dataclass

from desktop_strings import ui_text


@dataclass(frozen=True)
class Command:
    id: str
    label_key: str
    label: str
    handler: str
    alias: str
    row: int = -1


def command_table():
    return (
        Command('page_1', 'palette.cmd.data', ui_text('palette.cmd.data'), 'navigate', 'data page 1', 0),
        Command('page_2', 'palette.cmd.strategy', ui_text('palette.cmd.strategy'), 'navigate', 'strategy page 2', 1),
        Command('page_3', 'palette.cmd.backtest', ui_text('palette.cmd.backtest'), 'navigate', 'backtest page 3', 2),
        Command('page_4', 'palette.cmd.compare', ui_text('palette.cmd.compare'), 'navigate', 'compare page 4', 3),
        Command('page_5', 'palette.cmd.paper', ui_text('palette.cmd.paper'), 'navigate', 'paper page 5', 4),
        Command('page_6', 'palette.cmd.market', ui_text('palette.cmd.market'), 'navigate', 'market page 6', 5),
        Command('page_7', 'palette.cmd.settings', ui_text('palette.cmd.settings'), 'navigate', 'settings page 7', 6),
        Command('refresh', 'palette.cmd.refresh', ui_text('palette.cmd.refresh'), 'refresh', 'refresh'),
        Command('cancel_job', 'palette.cmd.cancel', ui_text('palette.cmd.cancel'), 'cancel_job', 'cancel job'),
        Command('theme', 'palette.cmd.theme', ui_text('palette.cmd.theme'), 'theme', 'theme'),
        Command('privacy', 'palette.cmd.privacy', ui_text('palette.cmd.privacy'), 'privacy', 'privacy'),
        Command('focus_import', 'palette.cmd.import', ui_text('palette.cmd.import'), 'focus_import', 'import data', 0),
        Command('focus_backtest', 'palette.cmd.run', ui_text('palette.cmd.run'), 'focus_backtest', 'start backtest', 2),
    )

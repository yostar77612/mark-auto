"""Per-workspace startup preferences: a convenience switch, never a credential or a market input."""

import json
from pathlib import Path

FILE_NAME = 'startup-preferences-v1.json'
VERSION = 1


class StartupPreferences:
    """Whether the desktop connects the broker simulation session by itself after it opens.

    Fail closed: a missing, unreadable or malformed file means "do not connect on startup".
    """

    def __init__(self, workspace):
        self.path = Path(workspace) / FILE_NAME

    def auto_connect(self) -> bool:
        try:
            body = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        return type(body) is dict and body.get('version') == VERSION and body.get('auto_connect') is True

    def set_auto_connect(self, value: bool) -> None:
        if type(value) is not bool:
            raise ValueError('auto_connect must be a bool')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': VERSION, 'auto_connect': value}, sort_keys=True), encoding='utf-8')
        temporary.replace(self.path)  # a failed write raises OSError and leaves the old file in place

"""Runtime responsibility extracted with safety ordering preserved."""

from __future__ import annotations

from pathlib import Path
from quantlab.runtime_support import atomic_write
from quantlab.shared.runtime_errors import RuntimeSafetyError
from .state_json import STATE_VERSION, _json_bytes, _read_json


class SettingsStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return {}
        value = _read_json(self.path)
        if not isinstance(value, dict) or value.get('schema_version') != STATE_VERSION or not isinstance(value.get('settings'), dict):
            raise RuntimeSafetyError('Unsupported settings version; original preserved')
        return value['settings']

    def save(self, settings):
        if not isinstance(settings, dict):
            raise RuntimeSafetyError('Settings must be a dictionary')
        if self.path.exists():
            self.load()  # Never silently overwrite future/corrupt settings.
        atomic_write(self.path, _json_bytes({'schema_version': STATE_VERSION, 'settings': settings}))

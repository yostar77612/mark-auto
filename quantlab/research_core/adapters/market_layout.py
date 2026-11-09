"""Bounded, display-only workspace metadata; never reads market inputs."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

PANEL_IDS = ('cards', 'watchlist', 'chart')
AREAS = ('top', 'left', 'center', 'right', 'bottom')
VERSION = 1
MAX_LAYOUTS = 20
MAX_NAME = 64
FILE_NAME = 'market-layout-v1.json'


def preset(preset_id):
    if preset_id not in ('overview', 'chart_focus', 'watchlist_focus'):
        raise ValueError('unknown preset')
    panels = {
        'cards': {'area': 'top', 'position': 0, 'size': 1000, 'collapsed': False},
        'watchlist': {'area': 'left', 'position': 0, 'size': 190, 'collapsed': False},
        'chart': {'area': 'center', 'position': 0, 'size': 740, 'collapsed': False},
    }
    if preset_id == 'chart_focus':
        panels['cards']['collapsed'] = True
        panels['watchlist']['size'] = 120
        panels['chart']['size'] = 810
    elif preset_id == 'watchlist_focus':
        panels['watchlist']['size'] = 460
        panels['chart']['size'] = 470
    return {'version': VERSION, 'panels': panels}


def valid_name(name):
    return (
        type(name) is str
        and 0 < len(name) <= MAX_NAME
        and name == name.strip()
        and not any(c in name for c in '/\\:')
        and not any(ord(c) < 32 for c in name)
        and name.lower() not in ('con', 'prn', 'aux', 'nul', '.', '..')
    )


def validate_layout(value, panel_ids=PANEL_IDS, areas=AREAS, fill=None):
    """Reject structure/type surprises; clamp strictly integral size hints.

    ``fill`` is a default layout: panels it defines that an older saved layout lacks are added from it.
    """
    if type(value) is not dict or set(value) != {'version', 'panels'} or type(value['version']) is not int or value['version'] != VERSION:
        return None
    panels = value['panels']
    if type(panels) is dict and fill is not None:
        panels = {**{key: item for key, item in fill['panels'].items() if key not in panels}, **panels}
    if type(panels) is not dict or set(panels) != set(panel_ids):
        return None
    result = {'version': VERSION, 'panels': {}}
    for key, panel in panels.items():
        if type(panel) is not dict or set(panel) != {'area', 'position', 'size', 'collapsed'}:
            return None
        if type(panel['area']) is not str or panel['area'] not in areas:
            return None
        if type(panel['position']) is not int or not 0 <= panel['position'] < len(panel_ids):
            return None
        if type(panel['size']) is not int or type(panel['collapsed']) is not bool:
            return None
        result['panels'][key] = dict(panel, size=max(80, min(2000, panel['size'])))
    return result


class LayoutStore:
    def __init__(self, directory=None, *, panel_ids=PANEL_IDS, areas=AREAS, file_name=FILE_NAME, default_layout=None):
        self.panel_ids = tuple(panel_ids)
        self.areas = tuple(areas)
        self.default_layout = deepcopy(default_layout) if default_layout is not None else preset('overview')
        self.path = Path(directory) / file_name if directory is not None else None
        self.layouts = {}
        self.current = deepcopy(self.default_layout)
        if self.path is not None:
            self.load()

    def load(self):
        if self.path is None:
            return
        try:
            if self.path.stat().st_size > 128_000:
                return
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if (
                type(value) is not dict
                or set(value) != {'version', 'current', 'layouts'}
                or type(value['version']) is not int
                or value['version'] != VERSION
                or type(value['layouts']) is not dict
                or len(value['layouts']) > MAX_LAYOUTS
            ):
                return
            self.current = validate_layout(value['current'], self.panel_ids, self.areas, self.default_layout) or deepcopy(self.default_layout)
            self.layouts = {
                name: layout
                for name, item in value['layouts'].items()
                if valid_name(name) and (layout := validate_layout(item, self.panel_ids, self.areas, self.default_layout)) is not None
            }
        except (OSError, ValueError, UnicodeError, RecursionError):
            return

    def save(self, layouts, current):
        """Commit memory only after a successful atomic disk replacement."""
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=self.path.parent, prefix='.market-layout-', suffix='.tmp', delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    json.dump({'version': VERSION, 'current': current, 'layouts': layouts}, stream, ensure_ascii=True, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
        self.layouts = deepcopy(layouts)
        self.current = deepcopy(current)

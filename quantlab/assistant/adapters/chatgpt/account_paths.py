"""Account paths responsibility; original guards and ordering preserved."""

from __future__ import annotations

from pathlib import Path
from quantlab.assistant.domain.plan_protocol import _fail


def _controls_for(reference):
    """Installation-local only; reject link/reparse redirection, never relocate."""
    root = Path(reference.bootstrap)
    if not root.is_absolute() or '..' in root.parts:
        _fail('installation_controls_path_required')
    controls = root / 'control-v1'
    _reject_links(controls)
    return controls


def _reject_links(path):
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            _fail('linked_controls_path_rejected')

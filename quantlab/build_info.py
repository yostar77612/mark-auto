"""Source commit of a frozen build, written by packaging/build.ps1 as build-info.json."""

import json
from pathlib import Path
import sys


def build_commit() -> str:
    """Short commit of the installed build; empty when running from source."""
    bundle = getattr(sys, '_MEIPASS', None)
    if bundle is None:
        return ''
    try:
        info = json.loads((Path(bundle) / 'build-info.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    commit = info.get('commit') if isinstance(info, dict) else None
    return commit[:7] if isinstance(commit, str) else ''

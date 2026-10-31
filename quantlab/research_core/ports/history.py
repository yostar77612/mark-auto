"""Capabilities required by local history import; composed with bounded adapters."""

from typing import Any, Callable, Protocol


class HistoryStorage(Protocol):
    check: Callable[..., Any]
    safe: Callable[..., Any]
    decode: Callable[..., Any]
    result: Callable[..., Any]
    bar_dict: Callable[..., Any]
    fail: Callable[..., Any]
    canonical_path: Callable[..., Any]
    publish: Callable[..., Any]
    version: str
    max_cache_bytes: int

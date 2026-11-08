"""Application-owned registry of extra assistant reply providers; the composition root fills it."""

from collections.abc import Callable

_providers: dict[str, tuple[Callable, int]] = {}


def configure_reply_provider(name: str, target: Callable, deadline_seconds: int):
    """target(sender, gate, request, bootstrap) is the spawned child entry point and must be importable by name."""
    _providers[name] = (target, deadline_seconds)


def reply_provider(name: str) -> tuple[Callable, int] | None:
    return _providers.get(name)

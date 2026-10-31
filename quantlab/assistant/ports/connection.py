"""Application-owned connection worker registration and dispatch contract."""

from typing import Protocol


class ConnectionWorker(Protocol):
    def __call__(self, request, *, bootstrap, emit, cancelled): ...


_worker: ConnectionWorker | None = None


def configure_connection_worker(worker: ConnectionWorker):
    global _worker
    _worker = worker


def run_connection_request(request, *, bootstrap, emit, cancelled):
    if _worker is None:
        raise RuntimeError('Connection worker is not configured')
    return _worker(request, bootstrap=bootstrap, emit=emit, cancelled=cancelled)

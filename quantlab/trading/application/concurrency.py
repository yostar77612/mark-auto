"""Serialize state writes; release only while immutable research is elsewhere."""

from contextlib import contextmanager
from threading import RLock, local
from typing import Iterator


class WriterLock:
    def __init__(self) -> None:
        self._lock = RLock()
        self._local = local()

    def acquire(self) -> bool:
        acquired = self._lock.acquire()
        if acquired:
            self._local.depth = getattr(self._local, 'depth', 0) + 1
        return acquired

    def release(self) -> None:
        self._lock.release()
        self._local.depth -= 1

    def __enter__(self) -> 'WriterLock':
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Only pure work may run here. Restore the caller's nesting afterwards."""
        depth = getattr(self._local, 'depth', 0)
        for _ in range(depth):
            self.release()
        try:
            yield
        finally:
            for _ in range(depth):
                self.acquire()

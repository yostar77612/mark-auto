"""Existing production/fake OAuth boundaries, owned by their callers."""

from contextlib import AbstractContextManager
from typing import Protocol
from quantlab.assistant.domain.auth_protocol import HttpResponse


class AuthTransportPort(Protocol):
    def request(self, method: str, url: str, *, form=None) -> HttpResponse: ...


class AuthReadVaultPort(Protocol):
    def lock(self) -> AbstractContextManager: ...
    def load(self) -> dict | None: ...


class AuthVaultPort(AuthReadVaultPort, Protocol):
    def save(self, record: dict) -> None: ...
    def assert_first_use(self) -> None: ...


class AuthStatusSourcePort(Protocol):
    vault: AuthReadVaultPort

    def _state(self, tokens: dict) -> str: ...

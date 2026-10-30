"""Extracted OAuth responsibility; behavior and fixed errors are preserved."""

from __future__ import annotations

from quantlab.assistant.domain.auth_protocol import AuthError
from dataclasses import dataclass
import socket
import time


@dataclass(repr=False)
class _Pending:
    state: str
    nonce: str
    verifier: str
    redirect: str
    deadline: float
    registration: str | None
    identity: dict | None
    listener: object
    client_id: str | None = None


class LoopbackListener:
    """A tiny bounded HTTP/1.x callback listener; no access logs or browser assets."""

    def __init__(self, callback):
        self.callback = callback
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind(('127.0.0.1', 0))
            self.socket.listen(4)
            self.port = self.socket.getsockname()[1]
        except Exception:
            self.socket.close()
            raise

    def close(self):
        self.socket.close()

    def poll(self, timeout=0.1):
        self.socket.settimeout(min(max(timeout, 0), 0.2))
        try:
            connection, peer = self.socket.accept()
        except (TimeoutError, BlockingIOError):
            return
        with connection:
            connection.settimeout(1)
            raw = b''
            deadline = time.monotonic() + 2
            accepted = False
            try:
                while b'\r\n\r\n' not in raw:
                    if len(raw) >= 8192 or time.monotonic() > deadline:
                        raise AuthError('callback_size')
                    part = connection.recv(min(1024, 8192 - len(raw)))
                    if not part:
                        raise AuthError('invalid_callback')
                    raw += part
                head, body = raw.split(b'\r\n\r\n', 1)
                lines = head.decode('ascii').split('\r\n')
                method, target, version = lines[0].split(' ')
                if version not in ('HTTP/1.0', 'HTTP/1.1') or body:
                    raise AuthError('invalid_callback')
                headers = {}
                for line in lines[1:]:
                    key, sep, value = line.partition(':')
                    key = key.lower()
                    if not sep or key in headers or line[:1].isspace():
                        raise AuthError('invalid_callback')
                    headers[key] = value.strip()
                if 'transfer-encoding' in headers or headers.get('content-length', '0') != '0':
                    raise AuthError('invalid_callback')
                self.callback(method, target, headers.get('host', ''), peer[0])
                accepted = True
            except Exception:
                pass
            message = b'You may close this window.' if accepted else b'Authorization callback rejected.'
            response = (
                b'HTTP/1.1 '
                + (b'200 OK' if accepted else b'400 Bad Request')
                + b'\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nContent-Security-Policy: default-src \'none\'\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\nContent-Length: '
                + str(len(message)).encode()
                + b'\r\n\r\n'
                + message
            )
            try:
                connection.sendall(response)
            except OSError:
                pass

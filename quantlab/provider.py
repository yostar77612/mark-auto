"""Explicit, default-off HTTP transport. No requests occur at import/construction."""
from dataclasses import dataclass, field
from typing import Callable
import http.client
import ipaddress
import json
import os
import socket
import ssl
import time
import threading
from urllib.parse import urlsplit

from .core import ValidationError, canonical_json


@dataclass(frozen=True)
class HTTPTransport:
    """Pickle-safe settings for an isolated worker, never stored credential values.

    Endpoint must be the complete chat-completions URL. API keys are resolved
    from an internal credential resolver or a named CLI environment variable
    at call time only. Resolver objects must contain references, never secrets. Plain HTTP
    is restricted to literal loopback addresses or localhost (for local Ollama).
    No redirects, proxies, cookies, retries, or automatic endpoint discovery.
    """
    allow_network: bool = False
    api_key_env: str | None = None
    max_request_bytes: int = 65536
    max_response_bytes: int = 262144
    credential_resolver: Callable[[], str | None] | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.allow_network) is not bool:
            raise ValidationError('allow_network must be boolean')
        for value in (self.max_request_bytes, self.max_response_bytes):
            if type(value) is not int or not 1024 <= value <= 1048576:
                raise ValidationError('HTTP byte limits must be 1024..1048576')
        if self.credential_resolver is not None and not callable(self.credential_resolver):
            raise ValidationError('Credential resolver must be callable')
        if self.credential_resolver is not None and self.api_key_env is not None:
            raise ValidationError('Choose one credential source')
        if self.api_key_env is not None and (not isinstance(self.api_key_env, str) or not self.api_key_env.isidentifier()):
            raise ValidationError('API key environment variable name is invalid')

    def __call__(self, endpoint, request, timeout_seconds):
        if not self.allow_network:
            raise ValidationError('HTTP transport network access disabled')
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
            raise ValidationError('HTTP timeout must be 1..120 seconds')
        parts = urlsplit(endpoint)
        if parts.username or parts.password or parts.fragment or parts.query or not parts.hostname:
            raise ValidationError('Endpoint cannot contain credentials, query or fragment')
        host = parts.hostname
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == 'localhost'
        if parts.scheme not in ('https', 'http') or (parts.scheme == 'http' and not loopback):
            raise ValidationError('Remote provider requires HTTPS; HTTP is loopback-only')
        body = canonical_json(request).encode('utf-8')
        if len(body) > self.max_request_bytes:
            raise ValidationError('HTTP request byte budget exceeded')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if self.api_key_env or self.credential_resolver is not None:
            try:
                key = self.credential_resolver() if self.credential_resolver is not None else os.environ.get(self.api_key_env)
            except Exception:
                raise ValidationError('Configured API credential unavailable') from None
            if not isinstance(key, str) or not 1 <= len(key) <= 8192 or any(c in key for c in '\r\n'):
                raise ValidationError('Configured API credential unavailable or invalid')
            headers['Authorization'] = 'Bearer ' + key
        connection = None
        timer = None
        active_socket = [None]
        deadline = time.monotonic() + timeout_seconds
        try:
            # localhost uses a literal loopback, avoiding external DNS and proxies.
            connect_host = '127.0.0.1' if parts.scheme == 'http' and host == 'localhost' else host
            if parts.scheme == 'https':
                connection = http.client.HTTPSConnection(connect_host, parts.port or 443,
                    timeout=timeout_seconds, context=ssl.create_default_context())
            else:
                connection = http.client.HTTPConnection(connect_host, parts.port or 80, timeout=timeout_seconds)
            def interrupt_socket():
                sock = active_socket[0] or connection.sock
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    sock.close()
            timer = threading.Timer(timeout_seconds, interrupt_socket)
            timer.daemon = True
            timer.start()
            connection.request('POST', parts.path or '/', body=body, headers=headers)
            active_socket[0] = connection.sock
            if time.monotonic() >= deadline:
                raise ValidationError('Provider HTTP deadline exceeded')
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise ValidationError(f'Provider HTTP status {response.status}; redirects and retries disabled')
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValidationError('Compressed provider responses unsupported')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdecimal() or int(length) > self.max_response_bytes):
                raise ValidationError('Provider response byte budget exceeded')
            chunks, total = [], 0
            while True:
                if response.isclosed():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValidationError('Provider HTTP deadline exceeded')
                if active_socket[0]:
                    active_socket[0].settimeout(remaining)
                chunk = response.read1(min(8192, self.max_response_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_response_bytes:
                    raise ValidationError('Provider response byte budget exceeded')
                chunks.append(chunk)
            from .research import _unique_keys
            parsed = json.loads(b''.join(chunks).decode('utf-8'), object_pairs_hook=_unique_keys,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValidationError('Nonfinite provider JSON')))
            if not isinstance(parsed, dict):
                raise ValidationError('Provider response must be an object')
            return parsed
        except (OSError, ValueError, http.client.HTTPException) as exc:
            if isinstance(exc, ValidationError):
                raise
            # Never include exception/request/headers/body: those may carry secrets.
            raise ValidationError('Provider HTTP transport failed') from None
        finally:
            if timer:
                timer.cancel()
            if connection:
                connection.close()

"""Independent authenticated local engine; GUI lifetime does not own positions."""

from datetime import datetime, timezone
import json
from multiprocessing.connection import Client, Listener, answer_challenge, deliver_challenge
from multiprocessing import AuthenticationError
from pathlib import Path
import os
from threading import BoundedSemaphore, Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.codec import MAX_BYTES, dumps, loads
from quantlab.trading.domain.validation import DomainError
from .bootstrap import EngineFactory, RuntimeBundle, build_runtime
from .config import RuntimeLaunch
from .control_secret import protect
from .protocol import Metrics, Operation, Request, Response
from .unix_socket import UnixEndpoint, unix_endpoint


def _metrics(bundle: RuntimeBundle) -> Metrics:
    engine = bundle.engine
    if engine is None:
        return Metrics(0, 0, 0, os.getpid())
    subscriptions = sum(len(getattr(broker, 'subscriptions', ())) for broker in engine.gateways.values())
    return Metrics(
        engine.quote_count,
        len(engine.quotes),
        len(engine.latencies),
        os.getpid(),
        subscriptions,
        sum(s.state == 'ACTIVE' for s in engine.state.strategies),
        len(engine.state.strategies),
    )


def _dispatch(bundle: RuntimeBundle, request: Request) -> Response:
    now = datetime.now(timezone.utc)
    if not now < request.deadline or (request.deadline - now).total_seconds() > 30:
        raise DomainError('state_conflict', 'expired command envelope')
    if request.environment is not bundle.launch.environment or request.account_ref not in bundle.account_refs:
        raise DomainError('capability_missing', 'explicit running account/environment required')
    if request.operation is Operation.SNAPSHOT:
        return Response(request.request_id, state=bundle.snapshot())
    if request.operation is Operation.COMMAND:
        if not isinstance(request.command.action, UiAction):
            raise DomainError('validation_failed', 'typed UI action required')
        if request.command.action.value == 'connect_read_only':
            receipt = bundle.connect_read_only(request.command)
        else:
            receipt = bundle.execute(request.command)
        return Response(request.request_id, state=bundle.snapshot(), receipt=receipt)
    if request.operation is Operation.QUOTES:
        if len(request.quotes.items) > 1000:
            raise DomainError('validation_failed', 'quote batch limit')
        engine = bundle.engine
        if engine is None:
            raise DomainError('capability_missing', 'disconnected context has no market-data port')
        with engine.lock:
            for quote in request.quotes.items:
                engine.quote(quote)
            return Response(request.request_id, metrics=_metrics(bundle))
    if request.operation is Operation.METRICS:
        engine = bundle.engine
        if engine is None:
            return Response(request.request_id, metrics=_metrics(bundle))
        with engine.lock:
            return Response(request.request_id, metrics=_metrics(bundle))
    raise DomainError('validation_failed', 'unsupported operation')


class _BoundedAuthentication:
    def __init__(self, connection):
        self.connection = connection

    def send_bytes(self, value: bytes) -> None:
        self.connection.send_bytes(value)

    def recv_bytes(self, maxlength: int = 256) -> bytes:
        if not self.connection.poll(2):
            raise AuthenticationError('local authentication deadline')
        return self.connection.recv_bytes(min(maxlength, 256))


class _Handlers:
    """Bounded clients may wait for research without owning the writer lock."""

    def __init__(self, bundle: RuntimeBundle, key: bytes):
        self.bundle, self.key = bundle, key
        self.slots, self.lock = BoundedSemaphore(8), Lock()
        self.threads: set[Thread] = set()

    def start(self, connection) -> None:
        if not self.slots.acquire(blocking=False):
            connection.close()
            return
        thread = Thread(target=self._handle, args=(connection,), name='markauto-local-request', daemon=True)
        with self.lock:
            self.threads.add(thread)
        thread.start()

    def _handle(self, connection) -> None:
        try:
            with connection:
                authentication = _BoundedAuthentication(connection)
                deliver_challenge(authentication, self.key)
                answer_challenge(authentication, self.key)
                self._request(connection)
        except (OSError, EOFError, AuthenticationError):
            pass
        finally:
            from threading import current_thread

            with self.lock:
                self.threads.discard(current_thread())
            self.slots.release()

    def _request(self, connection) -> None:
        request_id = ''
        try:
            if not connection.poll(2):
                return
            value = loads(connection.recv_bytes(MAX_BYTES).decode('utf-8'))
            if not isinstance(value, Request):
                raise DomainError('validation_failed', 'typed request required')
            request_id = value.request_id
            response = _dispatch(self.bundle, value)
        except (OSError, EOFError, UnicodeError, DomainError) as exc:
            response = Response(request_id, code=exc.code if isinstance(exc, DomainError) else 'operation_failed')
        try:
            encoded = dumps(response)
        except DomainError:
            encoded = dumps(Response(request_id, code='validation_failed'))
        connection.send_bytes(encoded.encode('utf-8'))

    def join(self) -> None:
        deadline = monotonic() + 3
        while monotonic() < deadline:
            with self.lock:
                active = tuple(self.threads)
            if not active:
                return
            active[0].join(min(0.1, max(0, deadline - monotonic())))
        raise DomainError('operation_failed', 'owned request handlers did not finish')


def serve(root: Path, *, launch: RuntimeLaunch | None = None, engine_factory: EngineFactory | None = None) -> int:
    if os.name == 'nt':
        return _serve(root, launch=launch, engine_factory=engine_factory)
    with unix_endpoint(root) as endpoint:
        return _serve(root, launch=launch, engine_factory=engine_factory, endpoint=endpoint)


def _serve(root: Path, *, launch: RuntimeLaunch | None, engine_factory: EngineFactory | None, endpoint: UnixEndpoint | None = None) -> int:
    root = root.resolve()
    launch = launch or RuntimeLaunch(root)
    if launch.root.resolve() != root:
        raise DomainError('validation_failed', 'launch and server roots differ')
    bundle = build_runtime(launch, engine_factory=engine_factory)
    family = 'AF_PIPE' if os.name == 'nt' else 'AF_UNIX'
    address = '\\\\.\\pipe\\markauto-v2-' + uuid4().hex if os.name == 'nt' else endpoint.address
    key = os.urandom(32)
    # Authenticate in bounded handlers, so an unauthenticated peer cannot hold
    # the accept loop or prevent the ownership heartbeat/protective processing.
    listener = None
    metadata = root / 'engine-session-v2.json'
    temp = root / ('session-' + uuid4().hex + '.tmp')
    try:
        listener = Listener(address, family=family, authkey=None)
        handlers = _Handlers(bundle, key)
        if os.name != 'nt':
            endpoint.secure()
        body = {'schema_version': 2, 'address': address, 'family': family, 'protected_key': protect(key).hex(), 'process_id': os.getpid()}
        temp.write_text(json.dumps(body, sort_keys=True), encoding='utf-8')
        if os.name != 'nt':
            os.chmod(temp, 0o600)
        temp.replace(metadata)
    except BaseException:
        if listener is not None:
            listener.close()
        if temp.exists():
            temp.unlink()
        bundle.close()
        raise
    stopped = Event()

    def heartbeat() -> None:
        while not stopped.wait(5):
            try:
                bundle.heartbeat()
            except Exception:
                target = bundle.engine if bundle.engine is not None else bundle.facade
                target.storage_failed = True

    watcher = Thread(target=heartbeat, name='markauto-ownership-heartbeat', daemon=True)
    watcher.start()

    def coordinate() -> None:
        while not stopped.wait(0.5):
            try:
                bundle.pump()
            except DomainError:
                # The coordinator journals typed issues. Unknown broker state
                # never causes automatic resubmission or an invented fill.
                continue
            except Exception:
                target = bundle.engine if bundle.engine is not None else bundle.facade
                target.storage_failed = True

    coordinator = Thread(target=coordinate, name='markauto-broker-coordinator', daemon=True)
    coordinator.start()

    def poll_broker() -> None:
        while not stopped.wait(0.5):
            try:
                bundle.poll_ports()
            except DomainError:
                continue

    query_worker = Thread(target=poll_broker, name='markauto-broker-query', daemon=True)
    query_worker.start()

    def accept_clients() -> None:
        while not stopped.is_set():
            try:
                connection = listener.accept()
            except (OSError, EOFError):
                continue
            if stopped.is_set():
                connection.close()
                return
            handlers.start(connection)

    acceptor = Thread(target=accept_clients, name='markauto-local-accept', daemon=True)
    acceptor.start()
    try:
        while not stopped.wait(0.1):
            if bundle.closed:
                break
    finally:
        stopped.set()
        try:
            bundle.cancel_owned_workers()
            # Wake our own raw accept without changing ACLs or killing processes.
            try:
                with Client(address, family=family, authkey=None):
                    pass
            except (OSError, EOFError):
                pass
            acceptor.join(2)
            handlers.join()
            watcher.join(2)
            coordinator.join(3)
            # A provider query without a cancellable API may still be waiting.
            # It owns only normalized port/cache state, never a core journal; the
            # cancelled generation drops its late result before any core transition.
            query_worker.join(0.2)
            listener.close()
            if coordinator.is_alive():
                raise DomainError('operation_failed', 'owned connector query did not finish; journal remains fenced')
            bundle.close()
            if metadata.exists():
                try:
                    current = json.loads(metadata.read_text(encoding='utf-8'))
                    if current.get('process_id') == os.getpid():
                        metadata.unlink()
                except (OSError, ValueError):
                    pass
        finally:
            if endpoint is not None:
                # Even when a failed join deliberately keeps the journal fenced,
                # close this Unix listener before releasing its private directory.
                listener.close()
    return 0

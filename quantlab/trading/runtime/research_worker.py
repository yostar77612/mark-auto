"""One owned spawn process per bounded training job; business messages are bytes.

The fixed child target imports only the deterministic training implementation.
No callable, import name, path, broker, account, journal or credential crosses
this boundary. Multiprocessing's own spawn bootstrap is the only pickle use.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import math
import multiprocessing
from multiprocessing.connection import Connection
import os
from threading import Event, Lock, Thread
from time import monotonic, sleep
from uuid import uuid4

from quantlab.trading.application.codec import MAX_BYTES, dumps, loads, register
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.provenance import ProducerProfile
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.research import ResearchResult, research
from quantlab.trading.application.state import StrategyRecord
from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.models import HoldingKind, HoldingPolicy, InstrumentSpec, Side
from quantlab.trading.domain.strategy import CompletedBar
from quantlab.trading.domain.validation import DomainError, aware, decimal_value, identity, integer
from quantlab.trading.ports.interfaces import Clock

MAX_SECONDS = 15 * 60
ERROR_CODES = frozenset(
    ('validation_failed', 'risk_rejected', 'calendar_missing', 'capability_missing', 'source_invalid_evidence', 'research_worker_failed', 'research_timeout')
)


class WorkerFault(str, Enum):
    """Fixed diagnostic faults; no arbitrary target or executable payload."""

    NONE = 'none'
    EXIT_AFTER_DECODE = 'exit_after_decode'
    STALL_AFTER_DECODE = 'stall_after_decode'
    SLOW_COMPLETION = 'slow_completion'


@dataclass(frozen=True)
class ResearchJob:
    request_id: str
    strategy: StrategyRecord
    spec: InstrumentSpec
    calendar: TradingCalendar
    bars: tuple[CompletedBar, ...]
    fees: FeeSchedule
    source_profile: ProducerProfile | None = None
    partition: str = 'TRAINING'

    def __post_init__(self) -> None:
        if type(self.request_id) is not str or len(self.request_id) != 32 or any(c not in '0123456789abcdef' for c in self.request_id):
            raise DomainError('validation_failed', 'training request identity')
        if (
            not isinstance(self.strategy, StrategyRecord)
            or not isinstance(self.spec, InstrumentSpec)
            or not isinstance(self.calendar, TradingCalendar)
            or not isinstance(self.fees, FeeSchedule)
        ):
            raise DomainError('validation_failed', 'typed training dependencies required')
        if (
            self.partition != 'TRAINING'
            or type(self.bars) is not tuple
            or not 1 <= len(self.bars) <= 10000
            or any(not isinstance(bar, CompletedBar) for bar in self.bars)
        ):
            raise DomainError('validation_failed', 'bounded training bars only')
        if self.source_profile is not None and not isinstance(self.source_profile, ProducerProfile):
            raise DomainError('validation_failed', 'typed producer profile required')
        record = self.strategy
        if not isinstance(record.form, StrategyForm) or not isinstance(record.policy, HoldingPolicy):
            raise DomainError('validation_failed', 'typed strategy form/policy required')
        identity(record.strategy_id)
        integer(record.version, 'strategy version', 1)
        decimal_value(record.form.allocation, 'strategy allocation', positive=True)
        decimal_value(record.form.risk_fraction, 'strategy risk fraction', positive=True)
        if (
            not isinstance(record.form.direction, Side)
            or not isinstance(record.form.holding_kind, HoldingKind)
            or type(record.form.min_days) is not int
            or type(record.form.max_days) is not int
        ):
            raise DomainError('validation_failed', 'strategy direction/policy field types')
        if (
            record.state not in ('RULE_VALID', 'RESEARCHED')
            or record.form.instrument_id != self.spec.instrument_id
            or record.form.market is not self.spec.market
        ):
            raise DomainError('validation_failed', 'validated strategy and instrument identity required')
        if (record.policy.kind, record.policy.min_days, record.policy.max_days) != (record.form.holding_kind, record.form.min_days, record.form.max_days):
            raise DomainError('validation_failed', 'strategy policy identity mismatch')


@dataclass(frozen=True)
class ResearchReply:
    request_id: str
    worker_pid: int
    result: ResearchResult | None = None
    error_code: str = ''

    def __post_init__(self) -> None:
        if type(self.worker_pid) is not int or self.worker_pid < 1 or type(self.request_id) is not str:
            raise DomainError('validation_failed', 'worker reply identity')
        if self.error_code and self.error_code not in ERROR_CODES or (self.result is None) == (not self.error_code):
            raise DomainError('validation_failed', 'worker reply result/error shape')
        if self.result is not None and not isinstance(self.result, ResearchResult):
            raise DomainError('validation_failed', 'typed training result required')


@dataclass(frozen=True)
class ResearchStarted:
    request_id: str
    worker_pid: int

    def __post_init__(self) -> None:
        if type(self.request_id) is not str or len(self.request_id) != 32 or type(self.worker_pid) is not int or self.worker_pid < 1:
            raise DomainError('validation_failed', 'training start identity')


def _initialize_types() -> None:
    initialize()
    register(FeeSchedule, ProducerProfile, ResearchJob, ResearchReply, ResearchStarted)


def _owner_guard(finished: Event, absolute_deadline: str) -> None:
    """An orphaned CPU worker exits itself; never sends signals to another PID."""
    parent = multiprocessing.parent_process()
    try:
        seconds = max(0, min(MAX_SECONDS, (aware(datetime.fromisoformat(absolute_deadline)) - datetime.now(timezone.utc)).total_seconds()))
        monotonic_deadline = monotonic() + seconds
        while not finished.wait(0.05):
            if monotonic() >= monotonic_deadline or parent is None or not parent.is_alive():
                os._exit(92)
    except BaseException:
        os._exit(92)


def _research_child(channel: Connection, diagnostic_fault: str, absolute_deadline: str) -> None:
    """Fixed spawn entry point; no runtime capability other than pure training."""
    _initialize_types()
    guard_finished = Event()
    guard = Thread(target=_owner_guard, args=(guard_finished, absolute_deadline), name='MarkAutoTrainingOwnerGuard', daemon=True)
    guard.start()
    request_id = ''
    try:
        payload = channel.recv_bytes(MAX_BYTES)
        if type(payload) is not bytes or len(payload) > MAX_BYTES:
            raise DomainError('validation_failed', 'training input byte bound')
        job = loads(payload.decode('utf-8'))
        if not isinstance(job, ResearchJob):
            raise DomainError('validation_failed', 'training job DTO required')
        request_id = job.request_id
        if job.source_profile is not None:
            from .provenance import compute_profile

            if compute_profile() != job.source_profile:
                raise DomainError('source_invalid_evidence', 'isolated child source profile changed')
        fault = WorkerFault(diagnostic_fault)
        channel.send_bytes(dumps(ResearchStarted(request_id, os.getpid())).encode('utf-8'))
        if fault is WorkerFault.EXIT_AFTER_DECODE:
            os._exit(91)
        if fault is WorkerFault.STALL_AFTER_DECODE:
            sleep(MAX_SECONDS + 1)  # owned diagnostic child is terminated by its parent deadline
        result = research(job.strategy, job.spec, job.calendar, job.bars, job.fees, source_profile=job.source_profile)
        reply = ResearchReply(request_id, os.getpid(), result)
    except DomainError as exc:
        reply = ResearchReply(request_id, os.getpid(), error_code=exc.code if exc.code in ERROR_CODES else 'research_worker_failed')
    except BaseException:
        reply = ResearchReply(request_id, os.getpid(), error_code='research_worker_failed')
    try:
        channel.send_bytes(dumps(reply).encode('utf-8'))
        if diagnostic_fault == WorkerFault.SLOW_COMPLETION.value:
            sleep(0.8)  # fixed diagnostic teardown delay, inside the original deadline
    except (OSError, ValueError):
        pass  # parent already owns failure/reconciliation; never print input/tracebacks
    finally:
        channel.close()
        guard_finished.set()
        guard.join(timeout=0.2)


def _send_payload(channel: Connection, payload: bytes, errors: list[str]) -> None:
    """Pipe writes cannot block the deadline supervisor while a child boots."""
    try:
        channel.send_bytes(payload)
    except (OSError, ValueError):
        errors.append('research_worker_failed')


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SpawnResearchRunner:
    def __init__(self, clock: Clock | None = None, *, max_seconds: float = MAX_SECONDS, diagnostic_fault: WorkerFault = WorkerFault.NONE):
        if (
            type(max_seconds) not in (int, float)
            or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= MAX_SECONDS
            or not isinstance(diagnostic_fault, WorkerFault)
        ):
            raise DomainError('validation_failed', 'research limit cannot exceed fifteen minutes')
        self.clock = clock if clock is not None else SystemClock()
        self.max_seconds, self.diagnostic_fault = float(max_seconds), diagnostic_fault
        self._lock = Lock()
        self._closed = Event()
        self.last_child_pid: int | None = None
        self.last_cleanup_verified = True
        self.last_child_ready = False

    def close(self) -> None:
        """Cancel this runner's sole owned job and queued admissions, never others."""
        self._closed.set()

    def run(
        self,
        strategy: StrategyRecord,
        spec: InstrumentSpec,
        calendar: TradingCalendar,
        bars: tuple[CompletedBar, ...],
        fees: FeeSchedule,
        *,
        deadline: datetime,
        source_profile: ProducerProfile | None = None,
    ) -> ResearchResult:
        if self._closed.is_set():
            raise DomainError('research_worker_failed', 'training runner is closed')
        aware(deadline)
        now = aware(self.clock.now())
        seconds = min(self.max_seconds, (deadline - now).total_seconds())
        if seconds <= 0:
            raise DomainError('research_timeout', 'training deadline expired before admission')
        started = monotonic()
        if not self._lock.acquire(timeout=seconds):
            raise DomainError('research_timeout', 'training worker queue deadline')
        try:
            if self._closed.is_set():
                raise DomainError('research_worker_failed', 'training runner closed while queued')
            return self._run(strategy, spec, calendar, bars, fees, deadline, source_profile, started + seconds)
        finally:
            self._lock.release()

    def _run(self, strategy, spec, calendar, bars, fees, deadline, source_profile, monotonic_deadline) -> ResearchResult:
        self.last_child_pid, self.last_cleanup_verified = None, True
        self.last_child_ready = False
        _initialize_types()
        job = ResearchJob(uuid4().hex, strategy, spec, calendar, bars, fees, source_profile)
        payload = dumps(job).encode('utf-8')
        if monotonic() >= monotonic_deadline or aware(self.clock.now()) >= deadline:
            raise DomainError('research_timeout', 'training deadline expired during admission')
        context = multiprocessing.get_context('spawn')
        channel, child_channel = context.Pipe(duplex=True)
        # Only a handle and fixed control enum enter spawn's bootstrap. Sending
        # the potentially large business packet as Process args would make
        # Process.start itself wait for child bootstrap and defeat short limits.
        absolute_deadline = (datetime.now(timezone.utc) + timedelta(seconds=max(0, monotonic_deadline - monotonic()))).isoformat()
        child = context.Process(target=_research_child, args=(child_channel, self.diagnostic_fault.value, absolute_deadline), name='MarkAutoTrainingV2')
        child.daemon = True
        self.last_child_pid, self.last_cleanup_verified = None, False
        started = False
        sender: Thread | None = None
        send_errors: list[str] = []
        # Cleanup has its own reserved slice INSIDE the original job limit.
        # It never extends the fifteen-minute research budget.
        cleanup_reserve = min(2.0, max(0.001, (monotonic_deadline - monotonic()) * 0.5))
        computation_deadline = monotonic_deadline - cleanup_reserve
        try:
            child.start()
            started = True
            self.last_child_pid = child.pid
            child_channel.close()
            sender = Thread(target=_send_payload, args=(channel, payload, send_errors), name='MarkAutoTrainingSender', daemon=True)
            sender.start()
            while True:
                if self._closed.is_set():
                    raise DomainError('research_worker_failed', 'owned training job canceled by engine shutdown')
                seconds = min(computation_deadline - monotonic(), (deadline - aware(self.clock.now())).total_seconds() - cleanup_reserve)
                if seconds <= 0:
                    raise DomainError('research_timeout', 'isolated training deadline exceeded')
                if send_errors:
                    raise DomainError('research_worker_failed', 'isolated training input transport failed')
                if channel.poll(min(0.05, seconds)):
                    try:
                        response = channel.recv_bytes(MAX_BYTES)
                    except (EOFError, OSError):
                        raise DomainError('research_worker_failed', 'isolated training process returned no valid bytes') from None
                    reply = loads(response.decode('utf-8'))
                    if isinstance(reply, ResearchStarted):
                        if reply.request_id != job.request_id or reply.worker_pid != child.pid or self.last_child_ready:
                            raise DomainError('research_worker_failed', 'training start identity mismatch')
                        self.last_child_ready = True
                        continue
                    if not isinstance(reply, ResearchReply) or reply.request_id != job.request_id or reply.worker_pid != child.pid:
                        raise DomainError('research_worker_failed', 'isolated training identity mismatch')
                    if reply.error_code:
                        raise DomainError(reply.error_code, 'isolated training did not complete')
                    # A valid reply is not permission to kill a child still
                    # doing ordinary interpreter/Windows handle teardown. Wait
                    # within this job's ORIGINAL budget, retaining cancellation
                    # and the reserved cleanup slice, rather than imposing a
                    # second arbitrary 500ms success deadline.
                    while child.is_alive():
                        if self._closed.is_set():
                            raise DomainError('research_worker_failed', 'training completion canceled by engine shutdown')
                        remaining = min(computation_deadline - monotonic(), (deadline - aware(self.clock.now())).total_seconds() - cleanup_reserve)
                        if remaining <= 0:
                            raise DomainError('research_timeout', 'training process completion exceeded original deadline')
                        child.join(timeout=min(0.05, remaining))
                    if child.exitcode != 0:
                        raise DomainError('research_worker_failed', 'isolated training completion was not clean')
                    if monotonic() >= monotonic_deadline or aware(self.clock.now()) >= deadline:
                        raise DomainError('research_timeout', 'training completion exceeded deadline')
                    if self._closed.is_set():
                        raise DomainError('research_worker_failed', 'training completion canceled by engine shutdown')
                    return self._validate_result(job, reply.result)
                if not child.is_alive() and not channel.poll(0):
                    raise DomainError('research_worker_failed', 'isolated training process exited without a result')
        except (OSError, RuntimeError) as exc:
            if isinstance(exc, DomainError):
                raise
            raise DomainError('research_worker_failed', 'isolated training could not start or communicate') from None
        finally:
            child_channel.close()
            if started:
                if child.is_alive():
                    child.terminate()
                remaining = max(0, min(monotonic_deadline - monotonic(), (deadline - aware(self.clock.now())).total_seconds()))
                child.join(timeout=min(remaining / 2, cleanup_reserve / 2))
                if child.is_alive():
                    child.kill()
                    remaining = max(0, min(monotonic_deadline - monotonic(), (deadline - aware(self.clock.now())).total_seconds()))
                    child.join(timeout=min(remaining, cleanup_reserve / 2))
                if sender is not None:
                    remaining = max(0, min(monotonic_deadline - monotonic(), (deadline - aware(self.clock.now())).total_seconds()))
                    sender.join(timeout=min(remaining, cleanup_reserve / 4))
                channel.close()
                if sender is not None and sender.is_alive():
                    remaining = max(0, min(monotonic_deadline - monotonic(), (deadline - aware(self.clock.now())).total_seconds()))
                    sender.join(timeout=min(remaining, cleanup_reserve / 4))
                self.last_cleanup_verified = not child.is_alive() and (sender is None or not sender.is_alive())
                if self.last_cleanup_verified:
                    child.close()
                else:
                    raise DomainError('research_worker_failed', 'owned training child cleanup could not be verified')
            else:
                channel.close()
                child.close()
                self.last_cleanup_verified = True

    @staticmethod
    def _validate_result(job: ResearchJob, result: ResearchResult | None) -> ResearchResult:
        if not isinstance(result, ResearchResult) or (result.strategy_id, result.version, result.partition) != (
            job.strategy.strategy_id,
            job.strategy.version,
            'TRAINING',
        ):
            raise DomainError('research_worker_failed', 'training result scope mismatch')
        if result.observations != len(job.bars) or any(
            not isinstance(value, Decimal) or not value.is_finite() for value in (result.net_pnl, result.costs, result.drawdown)
        ):
            raise DomainError('research_worker_failed', 'training result economics invalid')
        if any(
            type(value) is not str or len(value) != 64 or any(char not in '0123456789abcdef' for char in value)
            for value in (result.dataset_id, result.fingerprint)
        ):
            raise DomainError('research_worker_failed', 'training result digest invalid')
        if job.source_profile is not None and (result.producer_profile, result.source_digest) != (
            job.source_profile.profile_id,
            job.source_profile.source_digest,
        ):
            raise DomainError('research_worker_failed', 'training result producer profile mismatch')
        return result

"""Read-only query worker boundary: SDK waits never own the core writer lock.

Cached facts retain broker timestamps. Unknown, failed or aged queries raise a
typed error; neither zero balances nor empty positions are manufactured.
"""

from datetime import datetime
from decimal import Decimal
from threading import Lock
from time import monotonic
from typing import Callable

from quantlab.trading.application.context import AccountGateway
from quantlab.trading.application.events import validate_account_observation
from quantlab.trading.domain.models import AccountSnapshot, CapabilitySnapshot, Environment, OrderPlan, Quote
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import CommandReceipt, OrderEvent, RemoteSnapshot, SubmissionReceipt
from quantlab.trading.ports.interfaces import Clock


class ReadOnlyGatewayCache:
    def __init__(
        self, inner: AccountGateway, account_refs: tuple[str, ...], environment: Environment, clock: Clock, *, elapsed: Callable[[], float] = monotonic
    ):
        if (
            environment not in (Environment.BROKER_SIMULATION, Environment.LIVE)
            or type(account_refs) is not tuple
            or not 1 <= len(account_refs) <= 2
            or len(set(account_refs)) != len(account_refs)
        ):
            raise DomainError('capability_missing', 'bounded explicit broker query scope required')
        self.inner, self.account_refs, self.environment, self.clock = inner, account_refs, environment, clock
        self.lock = Lock()
        self.remote: dict[str, RemoteSnapshot] = {}
        self.capabilities: dict[str, CapabilitySnapshot] = {}
        self.report_log: dict[str, tuple[OrderEvent, ...]] = {ref: () for ref in account_refs}
        self.report_cursor = dict.fromkeys(account_refs, 0)
        self.report_floor = dict.fromkeys(account_refs, 0)
        self.account_errors = dict.fromkeys(account_refs, 'reconciliation_required')
        self.observed: dict[str, datetime] = {}
        self.quotes: dict[str, Quote] = {}
        self.quote_errors: dict[str, str] = {}
        self.next_account = 0
        self.elapsed = elapsed
        self.account_due = dict.fromkeys(account_refs, 0.0)
        self.account_failures = dict.fromkeys(account_refs, 0)
        self.quote_due: dict[str, float] = {}

    @property
    def subscriptions(self) -> dict[str, tuple[str, ...]]:
        return dict(getattr(self.inner, 'subscriptions', {}))

    def _known(self, account_ref: str) -> None:
        if account_ref not in self.account_refs:
            raise DomainError('capability_missing', 'account is outside query cache scope')
        if self.account_errors[account_ref]:
            raise DomainError(self.account_errors[account_ref], 'broker facts are not confirmed')
        remote = self.remote.get(account_ref)
        if remote is None:
            raise DomainError('reconciliation_required', 'broker account observation is missing')
        now = self.clock.now()
        validate_account_observation(account_ref, self.environment, now, remote)
        when = self.observed.get(account_ref)
        if when is None or not 0 <= (now - when).total_seconds() <= 30:
            raise DomainError('reconciliation_required', 'cached broker facts are stale')

    def snapshot(self, account_ref: str) -> AccountSnapshot:
        with self.lock:
            self._known(account_ref)
            return self.remote[account_ref].account

    def inspect(self, account_ref: str) -> CapabilitySnapshot:
        with self.lock:
            self._known(account_ref)
            return self.capabilities[account_ref]

    def refresh(self, account_ref: str) -> RemoteSnapshot:
        with self.lock:
            self._known(account_ref)
            return self.remote[account_ref]

    def events(self, account_ref: str, after_sequence: int = 0) -> tuple[OrderEvent, ...]:
        with self.lock:
            self._known(account_ref)
            if after_sequence < self.report_floor[account_ref]:
                raise DomainError('reconciliation_required', 'report cache prefix requires explicit snapshot reconciliation')
            return tuple(event for event in self.report_log[account_ref] if event.sequence > after_sequence)

    def latest(self, instrument_id: str) -> Quote | None:
        with self.lock:
            if instrument_id in self.quote_errors:
                raise DomainError(self.quote_errors[instrument_id], 'market query is not confirmed')
            return self.quotes.get(instrument_id)

    def submit(self, plan: OrderPlan, local_order_id: str) -> SubmissionReceipt:
        raise DomainError('capability_missing', 'read-only host cannot submit')

    def cancel(self, local_order_id: str) -> CommandReceipt:
        raise DomainError('capability_missing', 'read-only host cannot cancel')

    def amend(self, local_order_id: str, price: Decimal, quantity: int | None = None) -> CommandReceipt:
        raise DomainError('capability_missing', 'read-only host cannot amend')

    def _poll_account(self, account: str, cancelled: Callable[[], bool]) -> None:
        try:
            with self.lock:
                after = self.report_cursor[account]
            capability = self.inner.inspect(account)
            if cancelled():
                return
            reports = self.inner.events(account, after)
            if cancelled():
                return
            remote = self.inner.refresh(account)
            if (
                not isinstance(capability, CapabilitySnapshot)
                or not isinstance(remote, RemoteSnapshot)
                or type(reports) is not tuple
                or any(not isinstance(report, OrderEvent) for report in reports)
            ):
                raise DomainError('reconciliation_required', 'only normalized immutable port facts may be cached')
            if (
                capability.account_ref != account
                or capability.environment is not self.environment
                or remote.account.account_ref != account
                or remote.account.environment is not self.environment
            ):
                raise DomainError('reconciliation_required', 'cached query account or environment changed')
            validate_account_observation(account, self.environment, self.clock.now(), remote)
            if cancelled():
                return
            with self.lock:
                combined = list(self.report_log[account])
                known = set(combined)
                for report in reports:
                    # Exact duplicates may be retained by a port; different
                    # payloads with the same ID still reach the core's guard.
                    if report not in known:
                        combined.append(report)
                        known.add(report)
                if len(combined) > 10000:
                    dropped = combined[:-10000]
                    self.report_floor[account] = max(self.report_floor[account], max(report.sequence for report in dropped))
                    combined = combined[-10000:]
                self.report_log[account] = tuple(combined)
                self.report_cursor[account] = max((report.sequence for report in combined), default=after)
                self.remote[account], self.capabilities[account] = remote, capability
                self.observed[account] = self.clock.now()
                self.account_errors[account] = ''
                self.account_failures[account] = 0
                self.account_due[account] = self.elapsed() + 5
        except DomainError as exc:
            with self.lock:
                self.account_errors[account] = exc.code
                self._backoff(account, exc.code)
        except Exception:
            with self.lock:
                self.account_errors[account] = 'reconciliation_required'
                self._backoff(account, 'reconciliation_required')

    def _backoff(self, account: str, code: str) -> None:
        self.account_failures[account] += 1
        delay = 30 if code in ('rate_limited', 'capability_missing') else min(30, 2 ** min(self.account_failures[account], 5))
        self.account_due[account] = self.elapsed() + delay

    def poll(self, instrument_ids: tuple[str, ...], *, cancelled: Callable[[], bool]) -> None:
        """One account per turn, normalized calls outside any core writer lock.

        SDK methods with documented timeouts enforce their configured budgets.
        This worker cannot hard-cancel provider methods lacking timeout support.
        Its late results are discarded on shutdown, without touching a journal.
        Account refreshes use five-second cadence, quote requests one second;
        errors retain UNKNOWN facts and back off instead of hammering the API.
        """
        if cancelled():
            return
        account = self.account_refs[self.next_account]
        self.next_account = (self.next_account + 1) % len(self.account_refs)
        if self.elapsed() >= self.account_due[account]:
            self._poll_account(account, cancelled)
        latest = getattr(self.inner, 'latest', None)
        if latest is None or cancelled():
            return
        for instrument_id in instrument_ids:
            if cancelled():
                return
            if self.elapsed() < self.quote_due.get(instrument_id, 0):
                continue
            try:
                quote = latest(instrument_id)
                if quote is not None and not isinstance(quote, Quote):
                    raise DomainError('stale_quote', 'normalized quote required')
                if cancelled():
                    return
                with self.lock:
                    if quote is None:
                        self.quotes.pop(instrument_id, None)
                    else:
                        self.quotes[instrument_id] = quote
                    self.quote_errors.pop(instrument_id, None)
                    self.quote_due[instrument_id] = self.elapsed() + 1
            except DomainError as exc:
                with self.lock:
                    self.quote_errors[instrument_id] = exc.code
                    self.quote_due[instrument_id] = self.elapsed() + (30 if exc.code == 'rate_limited' else 5)
            except Exception:
                with self.lock:
                    self.quote_errors[instrument_id] = 'stale_quote'
                    self.quote_due[instrument_id] = self.elapsed() + 5

    def disconnect(self) -> None:
        disconnect = getattr(self.inner, 'disconnect', None)
        if disconnect is not None:
            disconnect()

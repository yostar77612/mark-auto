"""Real host entry: existing M1 cache, resolved gateway, owned refill and receipt."""

from datetime import datetime, timezone

from quantlab.trading.adapters.shioaji.minute_history import TMFMinuteHistorySession
from quantlab.trading.runtime.minute_receipt_store import MinuteReceiptStore
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.minute_receipt import MinuteResearchReceipt
from quantlab.trading.application.minute_research import validate_minute_request
from quantlab.trading.domain.validation import DomainError
from .minute_research import MinuteResearchService
from .minute_research_wait import MinuteResearchBudget
from .provenance import compute_profile
from .research_worker import SpawnResearchRunner


def _snapshot(bundle, strategy, settings, calendar):
    engine = bundle.engine
    if bundle.closing or bundle.resources_closed or engine is None:
        raise DomainError('capability_missing', 'active research host required')
    gateway = engine.gateways.get(strategy.form.account_ref)
    context = getattr(gateway, 'adapter', gateway)
    if context is None or not getattr(context, 'connected', False) or not hasattr(context, 'bindings'):
        raise DomainError('capability_missing', 'authenticated TMF gateway required')
    spec = engine.catalog.resolve(strategy.form.instrument_id)
    if spec.instrument_id not in context.bindings or context.bindings[spec.instrument_id].spec != spec:
        raise DomainError('instrument_unresolved', 'host catalogue and observed contract differ')
    sessions = validate_minute_request(strategy, spec, calendar, settings)
    evidence = settings.historical_contract
    if evidence is not None and evidence.sdk_code != context.bindings[spec.instrument_id].sdk_code:
        raise DomainError('instrument_unresolved', 'historical evidence contract code mismatch')
    owner = bundle.sinopac_connection
    stamp = None if owner is None else (owner.snapshot().generation, owner.shared)
    if owner is not None and owner.snapshot().phase != 'CONNECTED':
        raise DomainError('capability_missing', 'SinoPac history session unavailable')
    return engine, context, spec, engine.fees, sessions, context.client, stamp


def _guard(bundle, original, strategy, settings, calendar, budget):
    budget.check()
    current = _snapshot(bundle, strategy, settings, calendar)
    if current != original:
        raise DomainError('state_conflict', 'minute research host or contract changed')
    budget.check()


def run_minute_research(bundle, strategy, settings, *, calendar, deadline, cancel_event=None):
    """Synchronous research-only entry; callers may invoke on their owned worker.

    Historical applicability and full DAY calendar are explicit verified inputs.
    No observation timestamp is rewritten, and no automatic login is attempted.
    """
    budget = MinuteResearchBudget(deadline, cancel_event)
    with bundle.lock:
        if bundle.minute_research_active is not None:
            raise DomainError('state_conflict', 'one owned minute job per host')
        if bundle.minute_research_retiring is not None:
            if not bundle.minute_research_retiring.close(timeout=0):
                raise DomainError('capability_missing', 'previous minute history worker is still retiring')
            bundle.minute_research_retiring = None
        original = _snapshot(bundle, strategy, settings, calendar)
        runner = SpawnResearchRunner()
        bundle.minute_research_active = (budget.cancel, runner)
    engine, context, spec, fees, sessions, _, _ = original
    history = None
    try:
        history = HistorySync(
            bundle.kline_store,
            TMFMinuteHistorySession(context, calendar),
            now=context.clock.now,
            rate_limiter=bundle.market_history.reserve_query,
        )
        return _calculate_and_publish(bundle, original, strategy, settings, calendar, deadline, budget, history, runner)
    finally:
        if history is not None:
            history.watch_removed(spec.instrument_id, timeout=min(0.05, budget.remaining()))
            retired = history.close(timeout=min(0.05, budget.remaining()))
            if not retired:
                with bundle.lock:
                    bundle.minute_research_retiring = history
        runner.close()
        with bundle.lock:
            bundle.minute_research_active = None


def _calculate_and_publish(bundle, original, strategy, settings, calendar, deadline, budget, history, runner):
    engine, context, spec, fees, sessions, _, _ = original
    service = MinuteResearchService(bundle.kline_store, history, runner)
    profile = compute_profile()
    result = service.run_waiting(
        strategy,
        spec,
        calendar,
        fees,
        settings,
        now=context.clock.now(),
        deadline=deadline,
        source_profile=profile,
        budget=budget,
    )
    rows = tuple(row for row in bundle.kline_store.read(spec.instrument_id, sessions[0].opens_at, sessions[-1].closes_at) if row.session == 'DAY')
    receipt = MinuteResearchReceipt(result, strategy, spec, calendar, fees, profile, rows, context.clock.now())
    _publish(bundle, original, strategy, settings, calendar, budget, receipt)
    return receipt


def _publish(bundle, original, strategy, settings, calendar, budget, receipt):
    with bundle.lock:
        _guard(bundle, original, strategy, settings, calendar, budget)
        store = MinuteReceiptStore(bundle.launch.root / 'research' / 'minute-receipts.sqlite3', datetime.now(timezone.utc))
        try:
            store.append(receipt, datetime.now(timezone.utc), before_commit=lambda: _guard(bundle, original, strategy, settings, calendar, budget))
        finally:
            store.close()

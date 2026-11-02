"""Current-owner preflight facts collected only from existing trusted caches."""

from typing import TYPE_CHECKING

from quantlab.trading.application.manual_book import CAPACITY_SOURCE, diagnostic_passed
from quantlab.trading.application.preflight import PreflightFacts, engine_preflight_facts as engine_preflight_facts
from quantlab.trading.domain.models import Environment, OrderStatus
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import ManualAccountObservation

if TYPE_CHECKING:
    from .bootstrap import RuntimeBundle


def sinopac_preflight_facts(bundle: 'RuntimeBundle', account_ref: str) -> PreflightFacts:
    """Never infer key permission from login, signing or an attempted order.

    The existing TMF diagnostic proves key trading permission only after its
    known, unfilled cancellation in this SDK generation. Financial observations
    remain the manual runtime's normalized query cache; this collector neither
    queries a broker nor activates a certificate.
    """
    owner = bundle.sinopac_connection
    view = owner.snapshot()
    selected, shared = tuple(sorted(owner.selected)), owner.shared
    stamp = view.environment, view.generation, view.revision, selected, shared
    environment, engine, manual = bundle.launch.environment, bundle.engine, bundle.manual_runtime
    connected = (
        view.phase == 'CONNECTED'
        and view.environment is environment
        and owner.query_ready
        and shared is not None
        and not shared.callback_errors
        and not bundle.closing
        and not bundle.resources_closed
    )
    account = next((row for row in view.accounts if row.alias == account_ref and row.alias in selected), None)
    if engine is not None and account_ref in engine.gateways:
        base = engine_preflight_facts(engine, account_ref, quote_source='SHIOAJI')
        book_ready = any(book.account_ref == account_ref and book.source == CAPACITY_SOURCE for book in engine.state.manual_books)
        account_ready = account.signed if connected and account is not None and base.account_ready and book_ready else False
        permission = (
            False
            if account is None or account.signed is False
            else True
            if connected and account.signed is True and base.account_ready and diagnostic_passed(engine, view.generation)
            else None
        )
        observations = getattr(engine, 'manual_observations', {})
        uncertain = (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING)
        reconciled = bool(
            connected
            and base.reconciled
            and manual is not None
            and manual.stamp == (view.generation, view.revision, selected, shared)
            and set(observations) == set(engine.gateways)
            and all(
                isinstance(row, ManualAccountObservation)
                and row.account_ref == reference
                and row.environment is environment
                and 0 <= (engine.clock.now() - row.as_of).total_seconds() <= 30
                and not row.unmapped
                and not any(order.status in uncertain for order in row.orders)
                for reference, row in observations.items()
            )
        )
    else:
        base = PreflightFacts(None, None, None, None, None, None, None)
        account_ready, permission, reconciled = False, None, False
    ca = (True if view.certificate_status == 'READY' else None if view.certificate_status == 'UNKNOWN' else False) if environment is Environment.LIVE else None
    facts = PreflightFacts(
        bool(connected),
        account_ready,
        permission,
        ca,
        base.realtime if connected else False,
        bool(connected and base.service_open and not view.error_code and (manual is None or not manual.error)),
        reconciled,
    )
    current = owner.snapshot()
    if (
        stamp != (current.environment, current.generation, current.revision, tuple(sorted(owner.selected)), owner.shared)
        or bundle.sinopac_connection is not owner
        or bundle.engine is not engine
    ):
        raise DomainError('state_conflict', 'preflight belongs to an obsolete owner')
    return facts

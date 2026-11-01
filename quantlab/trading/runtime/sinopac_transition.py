"""Owned SDK transitions run outside UI/book locks; late candidates clean up."""

from time import monotonic

from quantlab.trading.adapters.shioaji.account_discovery import discover_accounts
from quantlab.trading.adapters.shioaji.market_session import MarketSession
from quantlab.trading.adapters.shioaji.shared_session import SharedSDKSession
from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.adapters.shioaji.sdk_loader import SdkUnavailable
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.sinopac_contracts import SinopacAccountView, SinopacReadiness
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError


def readiness(owner):
    connected = owner.session is not None and owner.session.connected
    selected = tuple(account for account in owner.accounts if account.alias in owner.selected)
    account_reason = (
        'not_connected'
        if not connected
        else 'accounts_unavailable'
        if not owner.accounts
        else 'ready'
        if owner.query_ready and selected
        else 'accounts_not_selected'
        if not selected
        else 'account_query_failed'
    )
    sim_reason = (
        'production_orders_disabled'
        if owner.configuration.environment is Environment.LIVE
        else 'accounts_not_selected'
        if not selected
        else 'account_not_signed'
        if any(account.signed is False for account in selected)
        else 'account_sign_unknown'
        if any(account.signed is None for account in selected)
        else 'account_query_failed'
        if not owner.query_ready
        else 'implementation_pending'
    )
    if owner.shared is not None and owner.shared.callback_errors:
        return (
            SinopacReadiness('market', 'UNKNOWN', 'callback_failed'),
            SinopacReadiness('accounts', 'UNKNOWN', 'callback_failed'),
            SinopacReadiness('simulation_orders', 'BLOCKED', 'callback_failed'),
            SinopacReadiness('production_orders', 'BLOCKED', 'production_orders_disabled'),
        )
    return (
        SinopacReadiness('market', 'READY' if connected else 'BLOCKED', 'ready' if connected else 'not_connected'),
        SinopacReadiness('accounts', 'READY' if account_reason == 'ready' else 'BLOCKED', account_reason),
        SinopacReadiness('simulation_orders', 'BLOCKED', sim_reason),
        SinopacReadiness('production_orders', 'BLOCKED', 'production_orders_disabled'),
    )


def account_views(owner):
    return tuple(
        SinopacAccountView(
            account.alias,
            account.label,
            account.market,
            account.signed,
            account.alias in owner.selected,
            True,
            'account_not_signed' if account.signed is False else 'account_sign_unknown' if account.signed is None else '',
        )
        for account in owner.accounts
    )


def dispose(owner):
    shared, session = owner.shared, owner.session
    try:
        owner.on_disconnected()
        if session is not None:
            session.disconnect()
    finally:
        if shared is not None:
            try:
                shared.close()
            except Exception:
                owner.cleanup_unconfirmed = True
                raise DomainError('outcome_unknown', 'native logout unconfirmed') from None
        owner.shared = owner.session = None
        owner.query_ready = False
        owner._resources.clear()


def select_accounts(owner, aliases, ticket):
    if type(aliases) is not tuple or len(set(aliases)) != len(aliases) or not set(aliases) <= {account.alias for account in owner.accounts}:
        raise DomainError('validation_failed', 'explicit discovered account selection required')
    for account in owner.accounts:
        if account.alias in aliases:
            if monotonic() >= owner.deadline:
                raise DomainError('outcome_unknown', 'account query deadline')
            owner.shared.facade.list_positions(account=account.native, unit='Common')
    with owner.lock:
        if owner.closed or ticket != owner.ticket or monotonic() >= owner.deadline:
            raise DomainError('outcome_unknown', 'late account selection')
        owner.preferences.save(owner.configuration, aliases)
        owner.selected = aliases
        owner.query_ready = bool(aliases)
        owner._resources.clear()


def accept_candidate(owner, candidate, market, accounts, ticket):
    with owner.lock:
        if owner.closed or ticket != owner.ticket or monotonic() >= owner.deadline:
            raise DomainError('outcome_unknown', 'late connection candidate')
        owner.shared, owner.session, owner.accounts = candidate, market, accounts
        owner.selected = tuple(alias for alias in owner.selected if alias in {account.alias for account in accounts})
    if owner.selected:
        select_accounts(owner, owner.selected, ticket)
    owner.preferences.save_accounts(accounts, owner.configuration.environment)
    owner.preferences.save(owner.configuration, owner.selected)
    owner.on_connected(market)
    with owner.lock:
        if owner.closed or ticket != owner.ticket or monotonic() >= owner.deadline:
            raise DomainError('outcome_unknown', 'connection superseded')
        owner.publish(phase='CONNECTED', accounts=account_views(owner), readiness=readiness(owner), error_code='')


def discard_candidate(owner, candidate, market):
    if owner.shared is candidate:
        try:
            owner.on_disconnected()
        except Exception:
            pass
        owner.shared = owner.session = None
    try:
        if market is not None:
            market.disconnect()
    except Exception:
        pass
    finally:
        try:
            candidate.close()
        except Exception:
            owner.cleanup_unconfirmed = True
    with owner.lock:
        owner.publish(readiness=readiness(owner))


def connect_candidate(owner, ticket):
    dispose(owner)  # An unconfirmed old logout must stop a new login.
    facade = owner.factory(owner.configuration.environment)
    if not isinstance(facade, ShioajiSDKFacade) or facade.environment is not owner.configuration.environment:
        raise DomainError('capability_missing', 'factory broker environment mismatch')
    candidate, market = SharedSDKSession(facade), None
    try:
        credentials = owner.secrets.broker_credentials(owner.configuration.key_ref)
        try:
            candidate.login(api_key=credentials.api_key, secret_key=credentials.secret_key)
        finally:
            del credentials
        accounts = discover_accounts(facade.list_accounts(), owner.configuration.environment)
        market = MarketSession(owner.settings, owner.secrets, facade._module, owner.clock, owner.directory)
        market.attach_authenticated(candidate.consumer('terminal'))
        accept_candidate(owner, candidate, market, accounts, ticket)
    except Exception:
        discard_candidate(owner, candidate, market)
        raise


def transition(owner, command, ticket):
    try:
        if command.action is UiAction.SAVE_AND_CONNECT_SINOPAC:
            connect_candidate(owner, ticket)
        elif command.action is UiAction.DISCONNECT_SINOPAC:
            dispose(owner)
            with owner.lock:
                owner.publish(phase='DISCONNECTED', readiness=readiness(owner), error_code='')
        elif command.action is UiAction.SELECT_SINOPAC_ACCOUNTS:
            select_accounts(owner, command.sinopac_accounts, ticket)
            with owner.lock:
                owner.publish(accounts=account_views(owner), readiness=readiness(owner), error_code='')
        else:
            from .sinopac_certificate import activate_certificate

            activate_certificate(owner, command.sinopac_settings, ticket)
    except Exception as error:
        public = (
            'logout_unconfirmed'
            if owner.cleanup_unconfirmed
            else 'market_sdk_missing'
            if isinstance(error, SdkUnavailable)
            else 'broker_permission_missing'
            if type(error).__name__ in ('AuthError', 'ShioajiPermissionError')
            else 'account_query_failed'
            if command.action is UiAction.SELECT_SINOPAC_ACCOUNTS
            else 'certificate_failed'
            if command.action is UiAction.ACTIVATE_SINOPAC_CA
            else 'broker_login_failed'
        )
        with owner.lock:
            if ticket == owner.ticket:
                if command.action is not UiAction.ACTIVATE_SINOPAC_CA:
                    owner.query_ready = False
                owner.publish(
                    phase='DISCONNECTED' if command.action in (UiAction.SAVE_AND_CONNECT_SINOPAC, UiAction.DISCONNECT_SINOPAC) else owner._view.phase,
                    error_code=public,
                    certificate_status='FAILED' if command.action is UiAction.ACTIVATE_SINOPAC_CA else owner._view.certificate_status,
                    readiness=readiness(owner),
                )
    finally:
        if owner.closed and owner.shared is not None:
            try:
                dispose(owner)
            except Exception:
                owner.cleanup_unconfirmed = True
        owner.done.set()

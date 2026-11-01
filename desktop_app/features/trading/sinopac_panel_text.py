"""Literal UI vocabulary for redacted connection DTOs; vendor text stays out."""

from desktop_app.strings.catalog import ui_text
from quantlab.trading.domain.models import Environment, Market


def reason_text(code):
    return {
        '': '',
        'ready': '',
        'not_connected': ui_text('m2.connection.connect_first'),
        'implementation_pending': ui_text('m2.connection.execution_pending'),
        'production_orders_disabled': ui_text('m2.connection.production_disabled'),
        'not_selected': ui_text('m2.connection.not_selected'),
        'accounts_not_selected': ui_text('m2.connection.not_selected'),
        'unsigned': ui_text('m2.connection.agreement_required'),
        'account_not_signed': ui_text('m2.connection.agreement_required'),
        'account_sign_unknown': ui_text('m2.connection.sign_unknown'),
        'account_query_unavailable': ui_text('m2.connection.account_unavailable'),
        'account_query_failed': ui_text('m2.connection.account_unavailable'),
        'permission_denied': ui_text('m2.connection.permission_denied'),
        'broker_permission_missing': ui_text('m2.connection.permission_denied'),
        'broker_login_failed': ui_text('m2.connection.login_failed'),
        'connection_timeout': ui_text('m2.connection.timeout'),
        'session_lost': ui_text('m2.connection.session_lost'),
        'logout_unconfirmed': ui_text('m2.connection.logout_unconfirmed'),
        'certificate_not_configured': ui_text('m2.connection.ca_not_configured'),
        'certificate_failed': ui_text('m2.connection.certificate_failed'),
        'outcome_unknown': ui_text('m2.connection.outcome_unknown'),
        'calendar_unavailable': ui_text('m2.connection.calendar_unavailable'),
        'state_conflict': ui_text('m2.connection.state_conflict'),
        'operation_failed': ui_text('m2.connection.operation_failed'),
        'journal_failed': ui_text('m2.connection.journal_failed'),
    }.get(code, ui_text('m2.connection.operation_failed'))


def phase_text(view):
    text = {
        'DISCONNECTED': ui_text('m2.connection.disconnected'),
        'CONNECTING': ui_text('m2.connection.pending'),
        'CONNECTED': ui_text('m2.connection.connected'),
        'DISCONNECTING': ui_text('m2.connection.disconnecting'),
    }[view.phase]
    if view.environment is not None:
        text += ' · ' + (ui_text('v2.broker_sim') if view.environment is Environment.BROKER_SIMULATION else ui_text('v2.live'))
    return text + (' · ' + reason_text(view.error_code) if view.error_code else '')


def certificate_text(status):
    return {
        'NOT_REQUIRED': ui_text('m2.connection.ca_not_required'),
        'NOT_CONFIGURED': ui_text('m2.connection.ca_not_configured'),
        'ACTIVATING': ui_text('m2.connection.ca_activating'),
        'READY': ui_text('m2.connection.ca_ready'),
        'FAILED': ui_text('m2.connection.ca_failed'),
        'UNKNOWN': ui_text('m2.connection.unknown'),
    }[status]


def readiness_text(item, *, reachable=True):
    caption = {
        'market': ui_text('m2.connection.market'),
        'accounts': ui_text('m2.connection.account_query'),
        'simulation_orders': ui_text('m2.connection.simulation'),
        'production_orders': ui_text('m2.connection.production'),
    }[item.code]
    state = item.state if reachable or item.code == 'production_orders' else 'UNKNOWN'
    status = {
        'READY': ui_text('m2.connection.ready'),
        'BLOCKED': ui_text('m2.connection.blocked'),
        'UNKNOWN': ui_text('m2.connection.unknown'),
        'NOT_REQUIRED': ui_text('m2.connection.not_required'),
    }[state]
    reason = item.reason if reachable or item.code == 'production_orders' else 'outcome_unknown'
    if item.code == 'production_orders':
        state, reason = 'BLOCKED', 'production_orders_disabled'
        status = ui_text('m2.connection.blocked')
    return ui_text('m2.connection.readiness_text').format(caption, status, reason_text(reason)).rstrip(' ·')


def account_text(item):
    market = ui_text('m2.connection.stock') if item.market is Market.STOCK else ui_text('m2.connection.futures')
    signed = (
        ui_text('m2.connection.signed')
        if item.signed is True
        else ui_text('m2.connection.unsigned')
        if item.signed is False
        else ui_text('m2.connection.signed_unknown')
    )
    return ui_text('m2.connection.account_text').format(market, item.label, signed)

"""Display names for Application state codes; no domain decisions."""

import re

from desktop_app.strings.catalog import ui_text


STATE_KEYS = {
    'LOCAL': 'v2.local',
    'BROKER_SIMULATION': 'v2.broker_sim',
    'LIVE': 'v2.live',
    'DISCONNECTED': 'v2.engine_disconnected',
    'CONNECTING': 'v2.engine_connecting',
    'UNVERIFIED': 'v2.context_unverified',
    'DRAFT': 'v2.state_draft',
    'RULE_VALID': 'v2.state_rule_valid',
    'RESEARCHED': 'v2.state_researched',
    'ACTIVE': 'v2.state_active',
    'RETIRED': 'v2.state_retired',
    'WAITING_RECONCILIATION': 'v2.engine_reconcile',
    'STOPPED': 'v2.engine_stopped',
    'RUNNING': 'v2.engine_running',
    'CLOSED': 'v2.engine_closed',
    'LOCAL_DAY_ONLY': 'v2.protect_day',
    'EXIT_BLOCKED': 'v2.protect_blocked',
    'PROTECTED_WHEN_ENGINE_RUNNING': 'v2.protect_running',
    'FRESH': 'v2.quote_fresh',
    'STALE': 'v2.quote_stale',
    'NO_DATA': 'v2.quote_none',
    'LOCAL_SYNTHETIC': 'v2.local_source',
    'MANAGED': 'v2.managed',
    'EXTERNAL': 'v2.external',
    'LOCAL_READY': 'v2.local_ready',
    'EXTERNAL_REQUIRED': 'v2.external_required',
    'CREATED': 'v2.order_created',
    'VALIDATED': 'v2.order_validated',
    'RESERVED': 'v2.order_reserved',
    'SUBMITTING': 'v2.order_submitting',
    'ACCEPTED': 'v2.order_accepted',
    'PARTIALLY_FILLED': 'v2.order_partial',
    'FILLED': 'v2.order_filled',
    'CANCEL_PENDING': 'v2.order_cancel_pending',
    'CANCELED': 'v2.order_canceled',
    'REJECTED': 'v2.order_rejected',
    'UNKNOWN': 'v2.order_unknown',
    'LOCAL_SYNTHETIC_TRAINING': 'v2.training_evidence',
    'CALENDAR_MISSING': 'v2.calendar_missing',
}
POLICY_KEYS = {'INTRADAY': 'v2.intraday', 'SWING': 'v2.swing', 'POSITION': 'v2.position', 'CUSTOM': 'v2.custom'}
EVENT_KEYS = {
    'startup_reconciliation_required': 'v2.event_startup',
    'strategy_version_created': 'v2.event_strategy',
    'strategy_rules_validated': 'v2.event_validated',
    'training_research_completed': 'v2.event_researched',
    'prior_deployment_retired': 'v2.event_retired',
    'local_deployment_activated': 'v2.event_activated',
    'exit_blocked': 'v2.event_exit_blocked',
    'reconciliation_complete': 'v2.event_reconciled',
    'reconciliation_unresolved': 'v2.event_reconcile_pending',
    'new_entries_stopped': 'v2.event_stopped',
    'entries_resumed_explicitly': 'v2.event_resumed',
    'position_transferred_explicitly': 'v2.event_transfer',
    'settings_changed': 'v2.event_settings',
    'view_context_changed': 'v2.event_context',
    'engine_shutdown_requested': 'v2.event_shutdown',
    'trading_day_advanced': 'v2.event_advanced',
    'portfolio_marked': 'v2.event_marked',
    'entry_cancel_requires_attention': 'v2.event_cancel_pending',
    'event_quarantine': 'v2.event_quarantine',
    'account_reconciled': 'v2.event_account_reconciled',
}


def state_label(code: str) -> str:
    return ui_text(STATE_KEYS[code]) if code in STATE_KEYS else code


def event_label(code: str) -> str:
    if code.startswith('broker_event_'):
        return ui_text('v2.event_order').format(state_label(code.removeprefix('broker_event_').upper()))
    return ui_text(EVENT_KEYS[code]) if code in EVENT_KEYS else ui_text('v2.event_generic')


def policy_label(code: str) -> str:
    match = re.fullmatch(r'(INTRADAY|SWING|POSITION|CUSTOM):(\d+)-(\d+)', code)
    if match:
        return ui_text('v2.policy_range').format(ui_text(POLICY_KEYS[match[1]]), match[2], match[3])
    return ui_text(POLICY_KEYS[code]) if code in POLICY_KEYS else code

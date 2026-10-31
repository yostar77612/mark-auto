"""Existing paper worker use cases; concrete dependencies arrive through ports."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from quantlab.core import StrategySpec, Instrument, ValidationError, content_hash


def paper_risk_limits():
    """The same fixed enforced limits supply both brokers and the read-only UI."""
    from quantlab.paper import RiskLimits

    return RiskLimits(1, 1, Decimal('1000'), 30)


def _paper(ports: UiOperationPorts, root):
    from quantlab.paper import PaperBroker

    policy = ports.repository.read_json(root / 'paper_policy.json')
    return PaperBroker(
        root / 'paper.sqlite3',
        instrument=Instrument(policy['contract_id']),
        costs=ports.repository.demo_config().costs,
        limits=paper_risk_limits(),
        risk_sessions=tuple(policy['risk_sessions']),
        margin_schedule=tuple(policy['margin_schedule']),
    )


def _prepare_paper_operation(ports: UiOperationPorts, payload, root):
    if 'policy' in payload:
        policy = payload['policy']
        existing = root / 'paper_policy.json'
        if ports.files.exists(existing) and ports.repository.read_json(existing) != policy:
            raise ValidationError(ports.text('ui.execute_ui_operation.paper_policy_locked'))
        if not ports.files.exists(existing):
            from quantlab.paper import PaperBroker

            if not isinstance(policy, dict) or set(policy) != {'contract_id', 'risk_sessions', 'margin_schedule'}:
                raise ValidationError(ports.text('ui.execute_ui_operation.paper_policy_fields'))
            with ports.files.TemporaryDirectory(prefix='policy-', dir=root) as staging:
                PaperBroker(
                    Path(staging) / 'validation.sqlite3',
                    instrument=Instrument(policy['contract_id']),
                    costs=ports.repository.demo_config().costs,
                    limits=paper_risk_limits(),
                    risk_sessions=tuple(policy['risk_sessions']),
                    margin_schedule=tuple(policy['margin_schedule']),
                )
            ports.repository.write_json(existing, policy)
    broker = _paper(ports, root)
    return broker


def _finish_paper_operation(ports: UiOperationPorts, root, broker, replay_state=None):
    state = broker.snapshot()
    journal = broker.journal_events()
    ports.repository.write_json(root / 'paper_snapshot.json', state)
    ports.repository.write_json(root / 'paper_journal_export.json', journal)
    if replay_state is not None:
        return {'replay': replay_state, 'account': state}
    return {'account': state, 'journal_tail': journal[-20:], 'journal_file': str(root / 'paper_journal_export.json')}


def _handle_ui_paper_cancel(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    if payload.get('action') == 'amend':
        from quantlab.paper_amend import execute as _execute_amend

        return _execute_amend(
            payload,
            root,
            prepare=lambda: _prepare_paper_operation(ports, payload, root),
            finish=lambda broker: _finish_paper_operation(ports, root, broker),
        )
    broker = _prepare_paper_operation(ports, payload, root)
    replay_state = None
    broker.cancel(payload['order_id'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
    return _finish_paper_operation(ports, root, broker, replay_state)


def _handle_ui_paper_cancel_all(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(ports, payload, root)
    now = datetime.fromisoformat(payload['now'].replace('Z', '+00:00'))
    targets = sorted((order_id for order_id, row in broker.snapshot()['orders'].items() if row['status'] not in ('filled', 'cancelled', 'rejected')))
    report = {'cancelled_order_ids': [], 'failed_order_ids': [], 'errors': {}}
    for order_id in targets:
        try:
            broker.cancel(order_id, now=now)
        except Exception as exc:
            report['failed_order_ids'].append(order_id)
            report['errors'][order_id] = ports.errors.exception_code(exc)
        else:
            report['cancelled_order_ids'].append(order_id)
    result = _finish_paper_operation(ports, root, broker)
    result['cancel_all_report'] = report
    return result


def _handle_ui_paper_kill(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(ports, payload, root)
    replay_state = None
    if 'manual_order_lock' in payload:
        broker.set_manual_order_lock(payload['manual_order_lock'])
    else:
        broker.set_kill_switch(True)
    return _finish_paper_operation(ports, root, broker, replay_state)


def _handle_ui_paper_reconcile(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(ports, payload, root)
    replay_state = None
    broker.reconcile(payload['snapshot'])
    if 'manual_order_lock' in payload:
        broker.set_manual_order_lock(payload['manual_order_lock'])
    return _finish_paper_operation(ports, root, broker, replay_state)


def _handle_ui_paper_replay(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(ports, payload, root)
    replay_state = None
    if payload.get('reconcile_confirmed') is not True:
        raise ValidationError(ports.text('ui.execute_ui_operation.replay_confirmation_required'))
    broker.reconcile(payload['snapshot'])
    if broker.snapshot().get('manual_order_lock', False):
        error = ValidationError(ports.text('paper.lock.rejected'))
        error.code = 'paper_manual_order_lock'
        raise error
    from quantlab.paper_replay import PaperReplay

    data = ports.inputs._dataset(root, payload)
    selection = ports.repository.load_selection(root / 'selection.json')
    binding = content_hash([data.manifest['data_hash'], selection['strategy_hash']])
    paths.require_replay_wal()
    replay = PaperReplay(
        root / 'replays' / (binding + '.sqlite3'),
        dataset=data,
        strategy=StrategySpec(**selection['strategy']),
        broker=broker,
        margin_schedule=broker._margin_schedule,
        storage_profile='wal_full',
    )
    if 'replay_action' in payload:
        import quantlab.replay_pacing as _replay_pacing

        try:
            replay_state = _replay_pacing.control(replay, payload['replay_action'])
            return _finish_paper_operation(ports, root, broker, replay_state)
        except BaseException:
            replay.stop()
            raise
    replay.start()
    cursor_before = replay.snapshot()['cursor']
    fills_before = len(broker.snapshot()['fills'])
    try:
        replay.step(max_bars=payload.get('max_bars', 100))
    finally:
        replay.stop()
    replay_state = replay.snapshot()
    replay_state['processed_bars'] = replay_state['cursor'] - cursor_before
    replay_state['new_fills'] = len(broker.snapshot()['fills']) - fills_before
    return _finish_paper_operation(ports, root, broker, replay_state)


def _handle_ui_paper_snapshot(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(ports, payload, root)
    replay_state = None
    return _finish_paper_operation(ports, root, broker, replay_state)


def _handle_ui_paper_submit(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    broker = _prepare_paper_operation(ports, payload, root)
    replay_state = None
    if payload.get('reconcile_confirmed') is not True:
        raise ValidationError(ports.text('ui.execute_ui_operation.snapshot_confirmation_required'))
    broker.reconcile(payload['snapshot'])
    selection = ports.repository.load_selection(root / 'selection.json')
    if payload['intent'].get('strategy_hash') != selection['strategy_hash']:
        raise ValidationError(ports.text('ui.execute_ui_operation.order_strategy_mismatch'))
    broker.set_kill_switch(False)
    broker.submit(payload['intent'], quote=payload['quote'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
    return _finish_paper_operation(ports, root, broker, replay_state)

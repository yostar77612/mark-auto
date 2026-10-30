"""Existing data worker use cases; concrete dependencies arrive through ports."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts
from pathlib import Path
from decimal import Decimal
from quantlab.core import ValidationError, content_hash, to_dict
from quantlab.research_core.application.ui_operations.market import dataset_market_series
from quantlab.research_core.application.paper_operations import _paper


def candidate_record(ports: UiOperationPorts, root, reference):
    from quantlab.research import validate_dsl

    state = ports.inputs.candidate_state(root, reference)
    if state.get('selection_hash') != content_hash(state.get('selected', [])):
        raise ValidationError(ports.text('ui.candidate_record.selection_hash_mismatch'))
    if state.get('campaign_id') != content_hash(state.get('binding')):
        raise ValidationError(ports.text('ui.candidate_record.version_hash_mismatch'))
    attempt = next((a for a in state.get('attempts', []) if a.get('attempt_id') == reference.get('attempt_id')), None)
    if not attempt or attempt.get('status') != 'evaluated':
        raise ValidationError(ports.text('ui.candidate_record.evaluation_required'))
    spec = validate_dsl(attempt.get('spec'))
    digest = content_hash(spec)
    if digest != attempt.get('strategy_hash') or digest != reference.get('strategy_hash'):
        raise ValidationError(ports.text('ui.candidate_record.strategy_hash_mismatch'))
    ranking = state['binding']['config']['ranking']
    selected = any((x.get('strategy_hash') == digest for x in state.get('selected', [])))
    qualified = selected and state.get('status') == 'completed'
    evaluations = {}
    for split in ('oos', 'holdout'):
        row = next((r for r in state.get('evaluations', {}).get(split, []) if r.get('strategy_hash') == digest), {})
        metrics = row.get('metrics', {})
        trades = metrics.get('trade_count', metrics.get('closed_trades', 0))
        passed = (
            row.get('status') == 'evaluated'
            and metrics.get('net_pnl') is not None
            and (Decimal(str(metrics['net_pnl'])) >= Decimal(str(ranking['minimum'])))
            and (trades >= ranking['min_trades'])
        )
        qualified = qualified and passed
        evaluations[split] = {'qualified': passed, 'evaluation': row}
    return (
        spec,
        {
            'reference': reference,
            'paper_qualified': bool(qualified),
            'evaluations': evaluations,
            'source_type': state.get('source_manifest', {}).get('source_type', 'unknown'),
            'source_data_hash': state.get('source_manifest', {}).get('data_hash'),
            'real_model_status': state.get('real_model_status', 'not_verified'),
            'note': ports.text('ui.candidate_record.synthetic_evidence_disclaimer'),
        },
    )


def _handle_ui_compare(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    if not payload.get('results'):
        raise ValidationError(ports.text('ui.execute_ui_operation.results_required'))
    return {'rows': ports.repository.comparison_rows([ports.repository.load_result(p) for p in payload['results']])}


def _handle_ui_demo(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    data = ports.repository.synthetic_dataset(payload.get('bars', 960))
    destination = root / ('synthetic-demo-dataset.json' if payload.get('synthetic_quick_start') is True else 'dataset.json')
    ports.repository.save_dataset(data, destination)
    return {'dataset': str(destination), 'source_type': 'synthetic', 'bars': len(data.bars)}


def _handle_ui_disable(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    selection = root / 'selection.json'
    if ports.files.exists(selection):
        archive = root / 'disabled_selections'
        ports.files.mkdir(archive, exist_ok=True)
        value = ports.repository.read_json(selection)
        ports.repository.write_json(archive / (content_hash(value) + '.json'), value)
        ports.files.unlink(selection)
    if ports.files.exists(root / 'paper_policy.json'):
        _paper(ports, root).set_kill_switch(True)
    return {'selection': 'disabled', 'scope': 'research_and_paper_only'}


def _handle_ui_import(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    from quantlab.data_gap_report import reject_invalid_import

    cal = ports.repository.read_json(Path(payload['calendar']))
    if payload['kind'] == 'validated_dataset':
        data = ports.repository.load_dataset(Path(payload['path']))
        reject_invalid_import(data, emit)
        dataset_market_series(ports, data, cal)
    else:
        data = ports.data_import.import_taifex(
            Path(payload['path']),
            kind=payload['kind'],
            calendar=ports.data_import.SessionCalendar(cal['sessions'], version=cal['version']),
            contract_id=payload.get('contract') or None,
            encoding=payload.get('encoding'),
        )
    reject_invalid_import(data, emit)
    ports.repository.save_dataset(data, root / 'dataset.json')
    ports.repository.write_json(root / 'dataset_calendar.json', cal)
    return {'dataset': str(root / 'dataset.json'), 'bars': len(data.bars), 'manifest': to_dict(data.manifest), 'quality': to_dict(data.quality)}


def _handle_ui_refresh(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    if payload.get('network_opt_in') is not True:
        raise ValidationError(ports.text('ui.execute_ui_operation.taifex_consent_required'))
    if 'auto_import' in payload:
        from quantlab.download_import import download_and_import

        return download_and_import(Path(paths.cache), root, payload, emit=emit)
    return ports.download.refresh(Path(paths.cache), days=payload.get('days', 1), kind=payload.get('format', 'csv'))


def _handle_ui_select(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    folder = Path(payload['result']).parent
    result = ports.repository.load_result(folder / 'result.json')
    reference = result.manifest.get('dataset_manifest', {}).get('desktop_candidate_reference')
    if reference:
        spec, provenance = candidate_record(ports, root, reference)
        if not provenance['paper_qualified']:
            raise ValidationError(ports.text('ui.execute_ui_operation.candidate_not_paper_eligible'))
        if content_hash(spec) != result.manifest.get('spec_hash'):
            raise ValidationError(ports.text('ui.execute_ui_operation.candidate_backtest_mismatch'))
    return ports.repository.save_selection(ports.repository.read_json(folder / 'strategy.json'), result, root / 'selection.json')

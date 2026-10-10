"""Typed desktop boundary for the frozen, offline walk-forward protocol.

No provider calls, paper qualification/selection or final-holdout evaluation.
Preview is read-only; a run revalidates every source/config binding before scoring.
"""
from pathlib import Path
import json
import re

from quantlab.core import ValidationError, canonical_json, content_hash, to_dict
from quantlab.walk_forward import (_validate_source, walk_forward_plan_from_dict,
    walk_forward_binding, planned_evaluations,
    run_walk_forward, read_walk_forward_state, reconcile_interrupted_walk_forward)


METRICS = ('net_pnl', 'trade_count', 'max_drawdown_pct', 'max_drawdown',
           'total_costs', 'realized_gross_pnl', 'unrealized_pnl', 'return', 'open_position')


def _folder(paths, reference):
    if type(reference) is not str or not re.fullmatch('[0-9a-f]{64}', reference):
        raise ValidationError('Walk-forward reference must be an immutable SHA-256 identity')
    state_root = Path(paths.state).resolve()
    base = (state_root / 'walk_forward').resolve()
    if not base.is_relative_to(state_root):
        raise ValidationError('Walk-forward state directory escapes the workspace')
    folder = base / reference
    if not folder.resolve().is_relative_to(base):
        raise ValidationError('Walk-forward reference escapes its state directory')
    return folder


def _binding(data, plan, registry):
    return walk_forward_binding(data, plan, registry)


def source_campaign_folder(paths, reference):
    if type(reference) is not str or not re.fullmatch('[0-9a-f]{64}', reference):
        raise ValidationError('Source campaign reference must be an immutable SHA-256 identity')
    root = Path(paths.state).resolve()
    base = (root / 'campaigns').resolve()
    folder = base / reference
    if not base.is_relative_to(root) or not folder.resolve().is_relative_to(base):
        raise ValidationError('Source campaign reference escapes the workspace')
    return folder


def _prepare_saved_plan(data, plan_payload, paths, saved_source, registry):
    from quantlab.desktop_runtime import validate_walk_forward_request
    from quantlab.saved_candidate_pool import admit_saved_campaign_pool, load_original_dataset
    chronology = validate_walk_forward_request(plan_payload, saved_source)
    # Validate the new data before indexing its first training timestamp.
    _validate_source(data, chronology)
    folder = source_campaign_folder(paths, saved_source['campaign_reference'])
    path = Path(saved_source['original_dataset']['path'])
    original = load_original_dataset(path)
    admitted = admit_saved_campaign_pool(source_campaign_dir=folder,
        source_campaign_ref=saved_source['campaign_reference'], original_dataset=original,
        original_dataset_ref=str(path), first_training_timestamp=data.bars[chronology.folds[0].train[0]].timestamp,
        authoritative_registry_path=registry)
    pool, admission = admitted.candidate_pool, to_dict(admitted.admission)
    bound = len(chronology.folds) * (2 * len(pool) + 1)
    if plan_payload['max_evaluations'] > bound:
        return None, {'admission_status': 'rejected', 'reason_code': 'evaluation_budget_exceeds_pool_bound',
            'candidate_count': len(pool), 'fold_count': len(chronology.folds),
            'evaluation_limit': plan_payload['max_evaluations'], 'planned_evaluations_upper_bound': bound,
            'pool_origin': 'saved_campaign_pool', 'pool_admission': admission,
            'candidate_pool': [to_dict(spec) for spec in pool], 'model_calls': 0}
    plan = walk_forward_plan_from_dict({**plan_payload,
        'candidate_pool': [to_dict(spec) for spec in pool], 'pool_admission': admission})
    return plan, None


def _range(data, bounds):
    start, end = bounds
    return {'start': start, 'end': end, 'start_time': data.bars[start].timestamp.isoformat(),
            'end_time': data.bars[end - 1].end.isoformat(), 'bars': end - start}


def preview_walk_forward(data, plan_payload, paths, saved_source=None):
    from desktop_ui import research_controls
    from quantlab.desktop_runtime import validate_walk_forward_request
    validate_walk_forward_request(plan_payload, saved_source)
    registry = research_controls(paths) / 'holdout-registry.sqlite3'
    if saved_source is None:
        plan = walk_forward_plan_from_dict(plan_payload)
    else:
        from quantlab.saved_candidate_pool import SavedCandidatePoolError
        try:
            plan, rejection = _prepare_saved_plan(data, plan_payload, paths, saved_source, registry)
        except SavedCandidatePoolError as exc:
            return {'admission_status': 'rejected', 'reason_code': exc.reason_code,
                'pool_origin': 'saved_campaign_pool', 'model_calls': 0}
        if rejection is not None: return rejection
    _validate_source(data, plan)
    binding = _binding(data, plan, registry)
    replay = plan.evidence_mode == 'historical_replay'
    return {'preview_identity': content_hash(binding), 'plan': to_dict(plan),
        'source_identity': binding['source_identity'], 'source_data_hash': binding['source_data_hash'],
        'source_type': data.manifest['source_type'], 'source_hashes': binding['source_hashes'],
        'registry_identity': binding['registry_identity'], 'bar_count': len(data.bars),
        'folds': [{'index': i, **{role: _range(data, getattr(fold, role)) for role in ('train', 'validation', 'oos')}} for i, fold in enumerate(plan.folds)],
        'final_holdout': _range(data, plan.final_holdout), 'final_holdout_status': 'excluded_not_evaluated',
        'candidate_pool': [to_dict(spec) for spec in plan.candidate_pool], 'ranking': to_dict(plan.ranking),
        'pool_origin': plan.pool_origin, 'pool_admission': to_dict(plan.pool_admission) if plan.pool_admission is not None else None,
        'candidate_count': len(plan.candidate_pool), 'admission_status': 'admitted',
        'evaluation_limit': plan.max_evaluations, 'planned_evaluations_upper_bound': planned_evaluations(plan),
        'runtime_seconds': plan.max_runtime_seconds, 'model_calls': 0,
        'evidence_mode': plan.evidence_mode, 'exposure_status': 'unverified' if replay else 'synthetic_not_market_evidence',
        'independent_oos': False, 'ranking_eligible': False, 'paper_eligible': False}


def _score(record):
    record = record or {}
    metrics = record.get('result', {}).get('metrics', {})
    return {'status': record.get('status', 'not_evaluated'),
            'metrics': {key: metrics[key] for key in METRICS if key in metrics}}


def compact_walk_forward(state, reference):
    """Bounded IPC projection, never the potentially 16-MiB journal payload."""
    if state['experiment_id'] != reference:
        raise ValidationError('Walk-forward journal reference does not match its binding')
    plan = state['binding']['plan']
    pool = plan['candidate_pool']
    folds = []
    for fold in state['folds']:
        selection = fold['selection']
        folds.append({'index': fold['index'], 'status': fold['status'],
            'winner': selection['spec']['strategy_id'] if selection else None,
            'winner_hash': selection['strategy_hash'] if selection else None,
            'winner_pool_index': selection['pool_index'] if selection else None,
            'candidates': [{'strategy_id': pool[c['pool_index']]['strategy_id'], 'family': pool[c['pool_index']]['family'],
                'pool_index': c['pool_index'], 'strategy_hash': c['strategy_hash'],
                'train': _score(c.get('train')), 'validation': _score(c.get('validation'))} for c in fold['candidates']],
            'oos': _score(fold.get('oos'))})
    return {'reference': reference, 'status': state['status'],
        'display_status': 'running_or_interrupted_no_stop_proof' if state['status'] == 'running' else state['status'],
        'source_identity': state['binding']['source_identity'],
        'source_type': state['source_manifest']['source_type'], 'ranking': plan['ranking'],
        'pool_origin': plan.get('pool_origin', 'exact_builtin_pool'),
        'pool_admission': plan.get('pool_admission'),
        'summary': state['summary'], 'folds': folds,
        'elapsed_seconds': state['elapsed_seconds'], 'journal': 'walk_forward/' + reference + '/walk_forward.sqlite3'}


def execute_walk_forward(operation, payload, paths, *, descendants_stopped=False):
    from desktop_ui import _dataset, research_controls
    if operation in ('ui_walk_forward_preview', 'ui_walk_forward_run'):
        required = {'plan'} if operation.endswith('_preview') else {'plan', 'preview_identity'}
        if 'saved_source' in payload:
            if not isinstance(payload.get('plan'), dict) or payload['plan'].get('pool_origin') != 'saved_campaign_pool':
                raise ValidationError('Built-in and saved pools cannot be mixed')
            required = required | {'saved_source'}
        if set(payload) != required:
            raise ValidationError('Unsupported walk-forward request fields')
        data = _dataset(Path(paths.state), {})
        preview = preview_walk_forward(data, payload['plan'], paths, payload.get('saved_source'))
        if operation.endswith('_preview'):
            return preview
        if preview.get('admission_status') == 'rejected':
            raise ValidationError('Saved pool admission changed or failed; preview again before starting')
        identity = preview['preview_identity']
        if payload['preview_identity'] != identity:
            raise ValidationError('Walk-forward source/config/pool changed; preview again before starting')
        output = _folder(paths, identity)
        # Reopening any journal is read-only. In particular, a stale running
        # journal cannot trigger the core's implicit interrupted reconciliation.
        if (output / 'walk_forward.sqlite3').exists():
            return compact_walk_forward(read_walk_forward_state(output), identity)
        source_options = {}
        if payload.get('saved_source') is not None:
            from quantlab.saved_candidate_pool import load_original_dataset
            source = payload['saved_source']
            source_options = {'source_campaign_dir': source_campaign_folder(paths, source['campaign_reference']),
                'original_dataset': load_original_dataset(Path(source['original_dataset']['path']))}
        state = run_walk_forward(data, plan=walk_forward_plan_from_dict(preview['plan']),
            output_dir=output, holdout_registry_path=research_controls(paths) / 'holdout-registry.sqlite3', **source_options)
        return compact_walk_forward(state, identity)
    if operation == 'ui_walk_forward_read':
        if set(payload) != {'reference'}:
            raise ValidationError('Unsupported walk-forward read fields')
        return compact_walk_forward(read_walk_forward_state(_folder(paths, payload['reference'])), payload['reference'])
    if operation == 'ui_walk_forward_reconcile':
        if set(payload) != {'reference', 'stopped_job_id'} or descendants_stopped is not True:
            raise ValidationError('Exact stopped walk-forward subtree proof required')
        folder = _folder(paths, payload['reference'])
        if not (folder / 'walk_forward.sqlite3').exists():
            # Cancellation before the worker created its journal has nothing to
            # reconcile. No evaluation or registry reservation is manufactured.
            return {'reference': payload['reference'], 'status': 'stopped_before_journal',
                    'display_status': 'stopped_before_journal'}
        return compact_walk_forward(reconcile_interrupted_walk_forward(output_dir=folder,
            descendants_stopped=True), payload['reference'])
    raise ValidationError('Unsupported walk-forward operation')


FAMILY_NAMES = {'trend': '均線趨勢', 'mean_reversion': '均值回歸', 'channel_breakout': '通道突破',
                'momentum': '動能', 'volatility_compression': '波動壓縮'}
PARAMETER_NAMES = {'fast': '快速均線根數', 'slow': '慢速均線根數', 'lookback': '回看根數',
    'entry_bps': '進場偏離基點', 'threshold_bps': '動能門檻基點', 'max_holding_bars': '最長持有根數',
    'max_range_bps': '最大區間基點', 'quantity': '口數', 'stop_ticks': '停損點數', 'target_ticks': '停利點數'}


ADMISSION_REASONS = {
    'source_duplicate_structure': '來源候選包含重複策略結構；整個候選池拒絕，不會靜默刪除或替換',
    'source_not_completed': '來源研究尚未正常完成（執行中或已中斷）',
    'source_producer_unsupported': '來源產生程式版本或必要來源雜湊尚未獲支援',
    'source_dataset_mismatch': '所選資料與原始研究的完整資料身分或切分不一致',
    'source_temporal_overlap': '原始資料的最晚事件結束時間未嚴格早於本次首折訓練',
    'source_journal_mismatch': '來源交易紀錄與匯出內容不一致',
    'source_invalid_evidence': '來源檔案、雜湊、結構或評估證據無法核對',
    'source_candidate_limit': '來源候選數量超過 15 個或單一家族超過 3 個',
    'source_no_evaluated_candidates': '來源研究沒有已完成有效評估的候選，不能建立固定池',
    'source_missing_evidence': '找不到或無法讀取明確選取的來源檔案',
    'source_provider_unsupported': '來源研究的模型供應商紀錄格式尚未獲支援',
    'source_manual_exchange_missing': '手動 AI 研究缺少已封存的交換套件與程式來源證據，無法安全核對',
    'source_provider_receipt_invalid': '來源模型的請求或回應憑證與已用嘗試不一致，拒絕載入',
    'source_provider_provenance_invalid': '來源模型程式版本、相依元件或描述紀錄無法通過核對',
    'source_provider_decimal_context_unsupported': '來源設定非零單價，但未保存可重現費用的小數計算環境；無法精確核對舊費用，拒絕載入',
    'source_resource_limit': '來源檔案、資料數量或數字超過核對上限',
    'source_registry_mismatch': '來源研究的不可逆登錄位置與目前共用登錄不一致，或缺少可核對的已消耗紀錄；拒絕開始，不會切換或重建登錄',
}


STATUS_LABELS = {
    'running': '執行中', 'training': '訓練中', 'selection_frozen': '贏家已鎖定',
    'running_or_interrupted_no_stop_proof': '執行中或已中斷，尚未確認停止',
    'completed': '已完成', 'completed_with_errors': '已完成，部分評估失敗',
    'evaluated': '已評估', 'not_evaluated': '未評估', 'failed': '評估失敗',
    'evaluation_failed': '評估失敗', 'timed_out': '已逾時', 'interrupted': '已中斷',
    'cancelled': '已取消', 'budget_exhausted': '評估額度或時間已用盡',
    'blocked_interrupted': '已中斷並封鎖重試', 'blocked_registry_busy': '共用登錄忙碌，已停止',
    'blocked_previously_consumed_range': '資料範圍先前已消耗，禁止評估',
    'no_eligible_candidate': '沒有通過全部門檻的候選', 'stopped_before_journal': '已在建立紀錄前停止',
    'not_verified': '尚未驗證', 'unverified': '尚未驗證',
    'synthetic_not_market_evidence': '合成資料，非市場證據',
    'synthetic_validation': '僅合成驗證', 'historical_replay': '歷史重播，資料暴露未驗證',
}


def status_label(value):
    """Display translation only; exact machine values stay in saved evidence."""
    return STATUS_LABELS.get(value, '尚無可確認紀錄，詳見進階')


def preview_text(preview, *, advanced=False):
    """Plain-language review by default; exact raw bindings are opt-in details."""
    p = preview
    if advanced:
        return '完整來源證據與設定（唯讀；原始模型狀態不會升級）\n' + json.dumps(json.loads(canonical_json(p)), ensure_ascii=False, indent=2)
    if p.get('admission_status') == 'rejected':
        if p.get('reason_code') == 'evaluation_budget_exceeds_pool_bound':
            return ('候選池已核對，評估額度需要您調整後重新預覽。\n'
                f"{p['fold_count']} 折 ×（2 × {p['candidate_count']} 個候選 + 1）= 最多 {p['planned_evaluations_upper_bound']} 次。\n"
                f"您填入 {p['evaluation_limit']} 次；請自行改為 1–{p['planned_evaluations_upper_bound']} 次，不會自動調整。\n"
                '沒有模型呼叫，沒有保留或消耗新範圍。')
        reason = ADMISSION_REASONS.get(p.get('reason_code'), '來源資料、結構或評估證據無法通過核對')
        return '來源研究未通過候選池准入：' + reason + '。\n沒有模型呼叫，沒有保留或消耗新範圍。'
    saved = p.get('pool_origin', 'exact_builtin_pool') == 'saved_campaign_pool'
    evidence = status_label(p['evidence_mode'])
    mode = '固定寬度' if p['plan']['mode'] == 'rolling' else '固定起點'
    lines = [f"{mode}訓練窗口 · {evidence} · {p['bar_count']} 根資料",
        ('已保存研究固定候選池' if saved else '五個精確內建規格') + f"：{len(p['candidate_pool'])} 個候選。",
        '重要：開始前即一次不可逆消耗全部計畫前推範圍；取消不退還，失敗／中斷不重試。',
        '最終保留集排除，未評估。非獨立 OOS、不可正式排名、無紙上資格；模型呼叫 0。',
        f"評估額度：您設定 {p['evaluation_limit']} 次；{len(p['folds'])} 折 ×（2 × {len(p['candidate_pool'])} 個候選 + 1）= 完整計畫至多 {p['planned_evaluations_upper_bound']} 次。",
        f"全實驗總秒數 {p['runtime_seconds']}；失敗／逾時／中斷也消耗額度。",
    ]
    if saved:
        provider = p['pool_admission'].get('provider_mode')
        label = {'fixture': '固定示範產生器', 'openai_compatible': '相容模型供應商', 'chatgpt_plan': 'ChatGPT 訂閱來源'}.get(provider, '已保存來源')
        lines.insert(2, '來源生成方式：' + label + '；來源模型狀態：' + status_label(p['pool_admission']['real_model_status']))
    lines.append('\n精確時序範圍：[起點, 終點)，UTC／明示時區')
    for fold in p['folds']:
        lines.append('第 ' + str(fold['index'] + 1) + ' 折')
        for role, label in (('train', '訓練'), ('validation', '驗證'), ('oos', '前推 OOS')):
            bounds = fold[role]
            lines.append(f"  {label}: [{bounds['start']}, {bounds['end']}) · {bounds['start_time']} → {bounds['end_time']}")
    b = p['final_holdout']
    lines.append(f"最終保留集 [{b['start']}, {b['end']}) · {b['start_time']} → {b['end_time']}：排除，未評估。")
    lines.extend([
        '歷史資料可能曾被模型或人接觸；時間早於本次訓練不代表未見資料。',
        '驗證門檻：淨損益 ≥ ' + str(p['ranking']['minimum']) + ' TWD；已平倉 lot ≥ ' + str(p['ranking']['min_trades']) + '；最大回撤比例 ≤ ' + str(p['ranking']['max_drawdown_pct']) + '（0.10 = 10%）。',
        '訓練僅描述；驗證通過全部門檻後，依淨損益選一個贏家；同分按固定池順序。',
        '每個切分獨立暖機、空倉起始。既有已消耗範圍仍封鎖；開始時由共用登錄原子核對。'
    ])
    if saved:
        admission = p['pool_admission']
        lines.extend(['來源模型狀態：' + status_label(admission['real_model_status']),
            '核對只證明本機來源紀錄一致，不代表真實模型推論或獲利已驗證。來源舊分數不參與本次排名。'])
        lines.append('\n全部來源嘗試（保留原順序）')
        for attempt in admission['attempts']:
            status = attempt['source_status']
            reason = '已評估並通過結構核對，納入固定池' if attempt['admitted'] else ({
                'rejected': '原研究未通過結構驗證，不納入',
                'generated': '原研究尚未評估，不納入',
                'validated': '原研究尚未完成評估，不納入',
                'failed': '原研究評估失敗，不納入',
                'error': '原研究評估失敗，不納入',
                'timed_out': '原研究評估逾時，不納入'}.get(status, '原研究未完成有效評估，不納入'))
            if attempt['reason'] == 'source_duplicate_rejected':
                reason = '與先前候選結構重複，原研究已拒絕且未重測；保留已用嘗試，不納入'
            lines.append(f"  第 {attempt['sequence']} 次 · {FAMILY_NAMES.get(attempt['family'], attempt['family'])}：{reason}")
    lines.append('\n固定候選（依來源順序）')
    for index, spec in enumerate(p['candidate_pool'], 1):
        params = '；'.join(PARAMETER_NAMES.get(k, k) + ' ' + str(v) for k, v in spec['parameters'].items())
        lines.append(f"{index}. {FAMILY_NAMES.get(spec['family'], spec['family'])} · {params}")
    config = p['plan']['backtest_config']; costs = config['costs']
    labels = {'commission_per_side': '單邊手續費', 'slippage_ticks': '滑價跳數', 'tax_rate': '交易稅率'}
    lines.append('\n明示費用：' + '；'.join(labels[k] + ' ' + str(costs[k]) for k in labels))
    lines.append('初始資金 ' + str(config['initial_cash']) + ' TWD；最大部位 ' + str(config['max_position']) + ' 口。')
    margins = [('原始保證金', config['initial_margin_per_contract']), ('維持保證金', config['maintenance_margin_per_contract'])]
    lines.append('每口' + '；'.join(label + '：' + (str(value) + ' TWD' if value is not None else '未設定') for label, value in margins) + '。')
    if config['cost_schedule'] or config['margin_schedule']:
        lines.append(f"另有 {len(config['cost_schedule'])} 筆費率及 {len(config['margin_schedule'])} 筆保證金異動，請展開進階核對各生效日期。")
    lines.append('完整來源證據、雜湊、登錄路徑及其餘政策設定可展開「進階」核對。')
    return '\n'.join(lines)


def result_rows(result):
    rows = []
    for fold in result.get('folds', []):
        for candidate in fold['candidates']:
            winner = ('第 ' + str(fold['winner_pool_index'] + 1) + ' 個') if fold.get('winner_pool_index') is not None else ('已選定，詳見進階' if fold['winner'] else '無')
            row = {'折次': fold['index'] + 1, '狀態': status_label(fold['status']), '贏家': winner,
                   '候選序號': candidate['pool_index'] + 1, '候選': FAMILY_NAMES.get(candidate.get('family'), '已保存候選')}
            for role, label in (('train', '訓練'), ('validation', '驗證')):
                score = candidate[role]; row[label + '狀態'] = status_label(score['status'])
                for key, caption in (('net_pnl', '淨損益 TWD'), ('trade_count', '已平倉 lot'), ('max_drawdown_pct', '最大回撤比例')):
                    row[label + caption] = score['metrics'].get(key)
            if candidate.get('strategy_hash') is not None and candidate['strategy_hash'] == fold.get('winner_hash'):
                row['前推狀態'] = status_label(fold['oos']['status'])
                names = {'net_pnl': '淨損益 TWD', 'trade_count': '已平倉 lot', 'max_drawdown_pct': '最大回撤比例',
                    'max_drawdown': '最大回撤 TWD', 'total_costs': '總費用 TWD', 'realized_gross_pnl': '已實現毛損益 TWD',
                    'unrealized_pnl': '未實現損益 TWD', 'return': '報酬率（比例）', 'open_position': '未平倉口數'}
                for key, value in fold['oos']['metrics'].items(): row['前推 ' + names[key]] = value
            rows.append(row)
        if not fold['candidates']:
            rows.append({'折次': fold['index'] + 1, '狀態': status_label(fold['status']), '贏家': '無'})
    return rows

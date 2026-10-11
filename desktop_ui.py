"""Native Traditional Chinese Qt workspace. No web server or live execution imports.

The GUI only schedules work. execute_ui_operation runs in the runtime's isolated
worker process; its inputs are data, never executable strategy source.
"""
from pathlib import Path
import json
from datetime import datetime
from decimal import Decimal

from quantlab.core import (Dataset, StrategySpec, Instrument, ValidationError, canonical_json,
                   content_hash, to_dict)
from quantlab.reporting import (read_json, write_json, load_dataset, save_dataset, synthetic_dataset,
                        demo_config, export_report, load_result, comparison_rows,
                        save_selection, load_selection, saved_analysis_entries)

UI_OPERATIONS = frozenset('ui_' + op for op in (
    'analysis_preview', 'analysis_run', 'analysis_read', 'analysis_reconcile',
    'walk_forward_preview', 'walk_forward_run', 'walk_forward_read', 'walk_forward_reconcile',
    'demo', 'import', 'refresh', 'market_refresh', 'chatgpt_auth', 'chatgpt_usage', 'chatgpt_reconcile', 'backtest', 'campaign', 'compare', 'select', 'disable',
    'paper_snapshot', 'paper_reconcile', 'paper_kill', 'paper_replay', 'paper_submit', 'paper_cancel',
    'backup_create', 'backup_restore'))


def research_controls(paths):
    """Irreversible budget/holdout ledgers must never be rolled back with user state."""
    state = Path(paths.state)
    legacy = list((state / 'provider_budgets').glob('*'))
    legacy.extend((state / 'campaigns').glob('.holdout_registry.sqlite3*'))
    if any(path.exists() and (not path.is_file() or path.stat().st_size > 0) for path in legacy):
        raise ValidationError('發現舊版工作區內的預算／保留集紀錄；為避免重設已用額度，研究已封鎖。請保留原始紀錄，需另外核對遷移，不會自動重設或刪除。')
    controls = Path(paths.controls)
    if controls.resolve().is_relative_to(state.resolve()):
        raise ValidationError('不可逆研究紀錄不得放在可還原狀態資料夾內')
    return controls


def provider_binding_options(options):
    # Preserve historical provider identities; these options cannot enable a removed provider.
    return {key: value for key, value in options.items()
            if key != 'network_opt_in' and not (options.get('mode') == 'local' and key == 'owner') and not (key == 'output_mode' and value == 'json_object')}


def campaign_generator(paths, options):
    """Only explicit deterministic fixtures use this non-subscription adapter."""
    from quantlab.research import FixtureGenerator
    if not isinstance(options, dict) or options != {'mode': 'fixture'}:
        raise ValidationError('模型研究僅支援官方 ChatGPT 訂閱；不提供本機模型或付費 API 備援')
    research_controls(paths)
    return FixtureGenerator()


def connection_event_from_payload(payload):
    from desktop_chatgpt_ui import ConnectionEvent
    if not isinstance(payload, dict): raise ValidationError('連線事件格式不符')
    value = dict(payload)
    value['registrations'] = tuple(tuple(row) for row in value.get('registrations', ()))
    value['models'] = tuple(value.get('models', ()))
    for key in ('model_labels', 'account_labels'):
        if key in value:
            value[key] = tuple(tuple(row) for row in value[key])
    return ConnectionEvent(**value)


def plan_provider(paths, data, config, options, *, for_usage=False):
    """Fixed bootstrap/control identity, never workspace-relative or random."""
    from desktop_chatgpt_auth import OAuthCredentialReference
    from desktop_chatgpt_provider import ChatGPTPlanProvider
    from desktop_chatgpt_ui import SubscriptionOptions
    from dataclasses import asdict
    allowed = {'mode','registration','model','max_calls','timeout_seconds','network_opt_in',
               'included_usage_policy_confirmed','paid_api_fallback','expected_binding'}
    if not isinstance(options, dict) or set(options)-allowed: raise ValidationError('不支援的訂閱設定欄位')
    raw = {key:value for key,value in options.items() if key != 'expected_binding'}
    if for_usage:
        if raw.get('network_opt_in') is not False or raw.get('included_usage_policy_confirmed') is not False:
            raise ValidationError('紀錄核對不可授權網路或推論')
        validation = {**raw, 'network_opt_in':True, 'included_usage_policy_confirmed':True}
    else:
        validation = raw
    parsed = SubscriptionOptions(**validation)
    public = {key:value for key,value in asdict(parsed).items() if key not in ('network_opt_in','included_usage_policy_confirmed')}
    import hashlib
    source_root = Path(__file__).parent
    source_files = ('desktop_chatgpt_auth.py','desktop_chatgpt_provider.py','quantlab/core.py',
                    'quantlab/backtest.py','quantlab/research.py','quantlab/strategies.py',
                    'desktop_chatgpt_dependency_manifest.json')
    sources = {name:hashlib.sha256((source_root/name).read_bytes()).hexdigest() for name in source_files}
    identity = content_hash({'data_hash':data.manifest['data_hash'], 'config':config,
                             'provider':public, 'implementation_sources':sources})
    if not for_usage and options.get('expected_binding') != identity:
        raise ValidationError('研究／模型／預算／來源已變更，請重新核對持久請求紀錄並明確同意')
    controls = research_controls(paths)
    reference = OAuthCredentialReference(str(getattr(paths,'bootstrap',None) or paths.root), parsed.registration)
    provider = ChatGPTPlanProvider(model=parsed.model, credential_reference=reference,
        budget_path=controls/('chatgpt-plan-'+identity+'.sqlite3'), campaign_id=identity,
        network_opt_in=not for_usage, included_usage_policy_confirmed=not for_usage,
        max_calls=parsed.max_calls, timeout_seconds=parsed.timeout_seconds)
    return provider, identity


def candidate_record(root, reference):
    """Resolve a persisted, hash-bound DSL candidate and independent evaluation gate."""
    from quantlab.research import validate_dsl
    campaigns = (Path(root) / 'campaigns').resolve()
    folder = str(reference.get('campaign_folder', ''))
    if len(folder) != 64 or any(c not in '0123456789abcdef' for c in folder):
        raise ValidationError('研究版本識別碼無效')
    path = campaigns / folder / 'campaign.json'
    if not path.resolve().is_relative_to(campaigns): raise ValidationError('研究版本路徑無效')
    state = read_json(path)
    # JSON is a review export; qualify only if it equals the authoritative journal.
    import sqlite3
    from contextlib import closing
    journal = path.with_name('campaign.sqlite3')
    if not journal.resolve().is_relative_to(campaigns) or not journal.is_file():
        raise ValidationError('找不到可核對的研究交易紀錄')
    with closing(sqlite3.connect(journal.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as database:
        row = database.execute('SELECT payload FROM state WHERE id=1').fetchone()
    if not row or canonical_json(json.loads(row[0])) != canonical_json(state):
        raise ValidationError('研究匯出與原始交易紀錄不符；拒絕候選資格判定')
    if state.get('selection_hash') != content_hash(state.get('selected', [])):
        raise ValidationError('研究選擇清單雜湊不符或尚未完成選擇')
    if state.get('campaign_id') != content_hash(state.get('binding')):
        raise ValidationError('研究版本內容雜湊不符')
    attempt = next((a for a in state.get('attempts', []) if a.get('attempt_id') == reference.get('attempt_id')), None)
    if not attempt or attempt.get('status') != 'evaluated': raise ValidationError('候選尚未通過結構驗證與評估')
    spec = validate_dsl(attempt.get('spec'))
    digest = content_hash(spec)
    if digest != attempt.get('strategy_hash') or digest != reference.get('strategy_hash'):
        raise ValidationError('候選策略版本雜湊不符')
    ranking = state['binding']['config']['ranking']
    selected = any(x.get('strategy_hash') == digest for x in state.get('selected', []))
    qualified = selected and state.get('status') == 'completed'
    evaluations = {}
    for split in ('oos', 'holdout'):
        row = next((r for r in state.get('evaluations', {}).get(split, []) if r.get('strategy_hash') == digest), {})
        metrics = row.get('metrics', {})
        trades = metrics.get('trade_count', metrics.get('closed_trades', 0))
        passed = (row.get('status') == 'evaluated' and metrics.get('net_pnl') is not None
                  and Decimal(str(metrics['net_pnl'])) >= Decimal(str(ranking['minimum']))
                  and trades >= ranking['min_trades'])
        qualified = qualified and passed
        evaluations[split] = {'qualified':passed, 'evaluation':row}
    return spec, {'reference':reference, 'paper_qualified':bool(qualified), 'evaluations':evaluations,
                  'source_type':state.get('source_manifest', {}).get('source_type', 'unknown'),
                  'source_data_hash':state.get('source_manifest', {}).get('data_hash'),
                  'real_model_status':state.get('real_model_status', 'not_verified'),
                  'note':'僅依預先宣告門檻檢查；合成與 Fixture 結果不是投資或真實模型績效驗證'}


def _root(paths):
    root = Path(paths.state)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dataset(root, payload):
    data = load_dataset(Path(payload.get('dataset') or root / 'dataset.json'))
    start, end = payload.get('start_date'), payload.get('end_date')
    if start or end:
        if start and end and start > end:
            raise ValidationError('開始日期不得晚於結束日期')
        bars = tuple(b for b in data.bars if (not start or b.trade_date >= start) and (not end or b.trade_date <= end))
        if not bars:
            raise ValidationError('選定日期沒有資料')
        manifest = {**data.manifest, 'parent_data_hash': data.manifest['data_hash'],
                    'data_hash': content_hash(bars), 'date_filter': {'start': start, 'end': end}}
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
        data = Dataset(bars, manifest, dict(data.quality))
    return data


def paper_risk_limits():
    """The same fixed enforced limits supply both brokers and the read-only UI."""
    from quantlab.paper import RiskLimits
    return RiskLimits(1, 1, Decimal('1000'), 30)


def _paper(root):
    from quantlab.paper import PaperBroker
    policy = read_json(root / 'paper_policy.json')
    return PaperBroker(root / 'paper.sqlite3', instrument=Instrument(policy['contract_id']),
                       costs=demo_config().costs, limits=paper_risk_limits(),
                       risk_sessions=tuple(policy['risk_sessions']), margin_schedule=tuple(policy['margin_schedule']))


def analysis_plan(paths, request, *, emit=None):
    from quantlab.desktop_runtime import validate_analysis_request
    from quantlab.research_analysis import build_analysis_packet, make_analysis_plan
    from desktop_chatgpt_provider import implementation_provenance
    validate_analysis_request(request)
    research_controls(paths)
    if emit: emit('progress',message='正在重新計算選定候選的訓練／驗證證據；不送出或評分 OOS／保留集。')
    from quantlab.saved_candidate_pool import load_original_dataset
    data=load_original_dataset(Path(request['original_dataset']['path']))
    packet=build_analysis_packet(source_campaign_dir=_root(paths)/'campaigns'/request['campaign_reference'],
        original_dataset=data,attempt_ids=request['attempt_ids'],task=request['task'],max_runtime_seconds=120)
    return make_analysis_plan(packet,model=request['model'],registration=request['registration'],
        provider_implementation=implementation_provenance(),timeout_seconds=request['timeout_seconds'])


def analysis_provider_for(paths, plan, *, authorized=False):
    from desktop_chatgpt_auth import OAuthCredentialReference
    from desktop_chatgpt_provider import analysis_provider
    reference=OAuthCredentialReference(str(getattr(paths,'bootstrap',None) or paths.root),plan['binding']['registration'])
    return analysis_provider(plan,reference,network_opt_in=authorized,included_usage_policy_confirmed=authorized)


ANALYSIS_NOTICE='本次重新計算的訓練／驗證結果；舊結果僅作來源索引，未驗證原始產生者。'
ANALYSIS_WARNING='未驗證的 AI 解讀／研究建議：敘述可能錯誤，風險安全性未驗證；不自動套用參數、不改選擇、不下單。'
ANALYSIS_CHECKPOINT_STATUS='中斷檢查點／尚未完成安全復原'
ANALYSIS_CHECKPOINT_NOTICE=(ANALYSIS_CHECKPOINT_STATUS+'\n'
    '僅發現分析狀態紀錄，缺少可讀取的結果匯出。紀錄內容、原始請求額度與作業停止狀態尚未核對；不可視為已完成結果。'
    '請保留原始檔案；安全復原另需原作業停止證明與原始紀錄核對。此處不復原、不重送、不重設額度。')
ANALYSIS_METRICS={'net_pnl':'淨損益','realized_gross_pnl':'已實現毛損益','unrealized_pnl':'未實現損益',
    'total_costs':'總成本','slippage_cost':'滑價成本','return':'報酬率','max_drawdown':'最大回撤',
    'max_drawdown_pct':'最大回撤比率','trade_count':'交易數','fill_count':'成交數','win_rate':'勝率',
    'profit_factor':'Profit Factor','sharpe':'Sharpe','sharpe_observations':'Sharpe觀測數',
    'sharpe_sample_count':'Sharpe樣本數','open_position':'未平倉數'}
ANALYSIS_KINDS={'market':'行情解讀','entry_exit':'進出場邏輯','backtest':'回測解讀','weakness':'弱點',
    'risk':'風險提醒','improvement':'研究改進方向','comparison':'候選比較'}


def analysis_preview_text(plan):
    from quantlab.research_analysis import validate_analysis_plan
    validate_analysis_plan(plan)
    binding=plan['binding'];context=binding['packet']['context'];training=context['training']
    lines=[ANALYSIS_NOTICE,ANALYSIS_WARNING,
        '僅傳送以下訓練 OHLC／指標及重新計算的 train／validation 摘要；不傳送 OOS／holdout。',
        '官方模型：'+binding['model']+'；最多一個不可退還的請求；網路期限 '+str(binding['timeout_seconds'])+' 秒。',
        '預覽識別：'+plan['analysis_id'],
        '訓練觀測：'+str(training['window_count'])+'／'+str(training['bar_count'])+' 根（僅末端有限視窗，非完整行情）']
    for row in context['strategies']:
        lines.append('候選 '+row['strategy_hash']+'；家族 '+row['spec']['family']+'；參數 '+canonical_json(row['spec']['parameters']))
    for row in context['evidence']:
        lines.append(('訓練' if row['split']=='train' else '驗證')+' · '+row['strategy_hash'][:16]+' · 本機數值：')
        lines.append('；'.join(ANALYSIS_METRICS.get(key,key)+'='+('不可用' if value is None else str(value)) for key,value in row['metrics'].items()))
    lines.append('完整送出內容可在下方進階證據中逐字核對；預覽本身不連網、不保留模型額度。')
    return '\n'.join(lines)


def analysis_record_text(record):
    # read_analysis/run_analysis already enforce record and evidence bindings.
    from quantlab.research_analysis import validate_analysis_plan, validate_analysis_response
    plan=validate_analysis_plan(record['plan']);context=plan['binding']['packet']['context']
    lines=[ANALYSIS_WARNING,ANALYSIS_NOTICE,'保存識別：'+plan['analysis_id'],'狀態：'+{'completed':'完成（不代表真帳戶已驗收）','blocked':'已封鎖，不重送','running':'中斷或完成未知，不重送'}.get(record['status'],'未知')]
    if record['status']!='completed':return '\n'.join(lines)
    response=validate_analysis_response(record['response'],context)
    evidence={row['evidence_id']:row for row in context['evidence']};training=context['training']
    for row in response['findings']:
        lines+=['',ANALYSIS_KINDS[row['kind']]+'：'+row['text'],'候選：'+', '.join(value[:16] for value in row['strategy_hashes'])]
        if 'signal_parameter' in row:lines.append('僅供另行研究的訊號參數：'+row['signal_parameter']+'（不套用）')
        for ref in row['evidence_refs']:
            if ref['evidence_id']==training['evidence_id']:
                lines.append('本機訓練視窗證據：'+ref['field']+'；'+str(training['window_count'])+' 根；完整數值見保存的送出證據。')
            else:
                local=evidence[ref['evidence_id']];value=local['metrics'][ref['field']]
                split=('訓練' if local['split']=='train' else '驗證')+'（'+local['split']+'）'
                lines.append('候選 '+local['strategy_hash'][:16]+' · 本機'+split+' '+ANALYSIS_METRICS.get(ref['field'],ref['field'])+'：'+('不可用' if value is None else str(value)))
    return '\n'.join(lines)


def execute_ui_operation(operation, payload, paths, *, emit=None, descendants_stopped=False):
    """Allowlisted process-worker adapter; no Qt objects are created here."""
    if operation not in UI_OPERATIONS:
        raise ValidationError('未知桌面作業')
    if operation == 'ui_campaign' and (not isinstance(payload.get('provider'), dict)
        or payload['provider'].get('mode') not in ('fixture', 'manual', 'chatgpt_plan')):
        raise ValidationError('不支援的模型研究來源；不提供本機模型或付費 API 備援')
    root = _root(paths)
    if operation.startswith('ui_analysis_'):
        from quantlab.research_analysis import read_analysis, run_analysis, reconcile_analysis, _read_analysis_journal
        from desktop_chatgpt_auth import OAuthCredentialReference
        from desktop_chatgpt_provider import read_account_status
        output=root/'analyses'
        if operation in ('ui_analysis_preview','ui_analysis_run'):
            allowed={'request'} if operation=='ui_analysis_preview' else {'request','expected_analysis_id','expected_plan_hash','user_confirmed','network_opt_in','included_usage_policy_confirmed'}
            if set(payload)!=allowed:raise ValidationError('分析請求欄位不符')
            if operation=='ui_analysis_run' and any(payload[key] is not True for key in ('user_confirmed','network_opt_in','included_usage_policy_confirmed')):
                raise ValidationError('請明確同意本次一個訂閱請求')
            plan=analysis_plan(paths,payload['request'],emit=emit)
            if operation=='ui_analysis_preview':
                provider=analysis_provider_for(paths,plan)
                reference=OAuthCredentialReference(str(getattr(paths,'bootstrap',None) or paths.root),plan['binding']['registration'])
                snapshot=provider.read_receipt_snapshot()
                account=read_account_status(reference,research_controls(paths))
                return {'analysis_id':plan['analysis_id'],'plan':plan,'receipt_snapshot':snapshot,'account_status':account}
            if payload['expected_analysis_id']!=plan['analysis_id'] or payload['expected_plan_hash']!=content_hash(plan):raise ValidationError('資料／來源／模型／期限已改變，請重新預覽並同意')
            if emit:emit('progress',message='證據已核對；正在執行唯一訂閱分析請求，取消不退還已保留次數。')
            result=run_analysis(output_root=output,plan=plan,provider=analysis_provider_for(paths,plan,authorized=True),
                expected_analysis_id=payload['expected_analysis_id'],user_confirmed=True)
            return {'analysis_id':plan['analysis_id'],**result}
        expected={'analysis_id'} if operation=='ui_analysis_read' else {'analysis_id','registration','stopped_job_id'}
        if set(payload)!=expected:raise ValidationError('保存分析請求欄位不符')
        if operation=='ui_analysis_reconcile' and descendants_stopped is not True:raise ValidationError('分析程序樹尚未停止，禁止核對')
        if operation=='ui_analysis_reconcile':
            record=_read_analysis_journal(output,payload['analysis_id'])
            if record['plan']['binding']['registration']!=payload['registration']:raise ValidationError('原始分析帳戶不符')
            record=reconcile_analysis(output_root=output,analysis_id=payload['analysis_id'],
                provider=analysis_provider_for(paths,record['plan']),descendants_stopped=True)
        else:
            record=read_analysis(output,payload['analysis_id'])
        return {'analysis_id':payload['analysis_id'],'record':record,'cache_hit':True}
    if operation.startswith('ui_walk_forward_'):
        from desktop_walk_forward import execute_walk_forward
        return execute_walk_forward(operation, payload, paths, descendants_stopped=descendants_stopped)
    if operation == 'ui_chatgpt_auth':
        from desktop_chatgpt_ui import ConnectionRequest, run_connection_request
        from dataclasses import asdict
        if set(payload) != {'request'} or not isinstance(payload['request'], dict): raise ValidationError('連線請求格式不符')
        request = ConnectionRequest(**payload['request'])
        def private_event(event):
            if emit is None: raise ValidationError('授權需要受管理程序與私人進度通道')
            emit('auth_progress', auth_event=asdict(event))
        if request.action in ('begin', 'first_sign_in', 'enable_plan') and emit is None: raise ValidationError('授權需要受管理程序')
        result = run_connection_request(request, bootstrap=str(getattr(paths,'bootstrap',None) or paths.root),
            emit=private_event, cancelled=lambda:False)
        if result.authorization_url is not None: raise ValidationError('授權網址不可進入結果紀錄')
        return {'auth_event':asdict(result)}
    if operation == 'ui_chatgpt_reconcile':
        from quantlab.research import reconcile_interrupted_campaign
        from quantlab.__main__ import config_from_json
        if descendants_stopped is not True: raise ValidationError('背景子程序尚未確認停止，禁止核對')
        if set(payload) != {'config','provider','binding','stopped_job_id'}: raise ValidationError('不支援的中斷核對欄位')
        data = _dataset(root,{})
        config = dict(payload['config']); config['backtest_config'] = config_from_json(config['backtest_config'])
        generator, identity = plan_provider(paths,data,config,payload['provider'],for_usage=True)
        if identity != payload['binding']: raise ValidationError('原始研究身分不符，維持未知封鎖')
        name = content_hash({'dataset':data.manifest['data_hash'],'config':config,
            'provider':provider_binding_options({'mode':'chatgpt_plan','binding':identity})})
        # This operation is dispatched only after JobManager's subtree proof.
        state = reconcile_interrupted_campaign(output_dir=root/'campaigns'/name,
            generator=generator,descendants_stopped=True)
        return {'binding':identity,'state':state['status']}
    if operation == 'ui_chatgpt_usage':
        from desktop_chatgpt_auth import OAuthCredentialReference
        from desktop_chatgpt_provider import read_account_status
        if set(payload)-{'registration','provider','config'}: raise ValidationError('不支援的請求紀錄核對欄位')
        reference = OAuthCredentialReference(str(getattr(paths,'bootstrap',None) or paths.root),payload['registration'])
        status = read_account_status(reference, research_controls(paths))
        result = {'registration':payload['registration'], 'account_status':status}
        if 'provider' in payload:
            from quantlab.__main__ import config_from_json
            data = _dataset(root, {})
            config = dict(payload['config']);config['backtest_config'] = config_from_json(config['backtest_config'])
            provider, identity = plan_provider(paths, data, config, payload['provider'], for_usage=True)
            if provider.credential_reference.registration != payload['registration']: raise ValidationError('紀錄與帳戶不符')
            receipts = provider.read_receipt_snapshot()['receipts']
            if len(receipts)>10000: raise ValidationError('請求紀錄超過顯示上限')
            result.update(receipts=[{'sequence':row['sequence'],'status':row['status']} for row in receipts], binding=identity,
                          account_status=read_account_status(reference,research_controls(paths)))
        return result
    if operation in ('ui_backup_create', 'ui_backup_restore'):
        from quantlab.desktop_runtime import BackupManager
        manager = BackupManager(paths)
        if operation == 'ui_backup_restore':
            manager.restore(Path(payload['path']))
            return {'restored': True, 'reconciliation_required': True}
        return {'backup': str(manager.create(Path(payload['path'])))}
    if operation == 'ui_market_refresh' and 'history_import' in payload:
        if payload.get('history_import') is not True or set(payload) != {'history_import','local_path','sessions','dated_policy_confirmed'}:
            raise ValidationError('本機歷史匯入請求欄位不符；不可混入網路或每日來源設定')
        from quantlab.market_history import import_history, session_from_dict
        if payload.get('dated_policy_confirmed') is not True:
            raise ValidationError('請先明確確認自行聲明的日期時段')
        records = payload.get('sessions')
        if not isinstance(records, list) or not 1 <= len(records) <= 128:
            raise ValidationError('請選擇 1 至 128 個明確時段')
        if emit is not None: emit('progress', message='正在匯入本機逐筆歷史；來源及日期時段未驗證，可取消。')
        result = import_history(Path(payload['local_path']), root / 'market_history',
                                sessions=tuple(session_from_dict(row) for row in records))
        return {'mode': 'local_unverified_history', 'cache_id': result.cache_id,
                'source_hash': result.source_hash, 'policy_hash': result.policy_hash,
                'counters': dict(result.counters), 'warnings': list(result.warnings),
                'contracts': len(result.series), 'bars': sum(len(x.bars) for x in result.series)}
    if operation == 'ui_market_refresh':
        from quantlab.market_providers import refresh_daily, import_daily, MAX_BYTES
        # File imports use the same fixed official schema and atomic cache path.
        local = payload.get('local_path')
        if not local and payload.get('network_opt_in') is not True:
            raise ValidationError('請先明確同意本次官方行情網路更新')
        providers = (payload.get('provider'),) if local else ('twse', 'taifex')
        outcomes = {}
        for provider in providers:
            if provider not in ('twse', 'taifex'): raise ValidationError('不支援的官方來源')
            try:
                kwargs = {}
                if local:
                    path = Path(local)
                    if path.stat().st_size > MAX_BYTES: raise ValidationError('官方資料檔案過大')
                    with path.open('rb') as stream: raw = stream.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES: raise ValidationError('官方資料檔案過大')
                    result = import_daily(provider, root / 'market_cache', raw, format=payload.get('format', 'json'))
                else:
                    result = refresh_daily(provider, root / 'market_cache', network_enabled=True, **kwargs)
                outcomes[provider] = {'stale': result.stale, 'error': result.error,
                    'contracts': len(result.series), 'bars': sum(len(x.bars) for x in result.series)}
            except Exception as exc:
                outcomes[provider] = {'stale': True, 'error': str(exc), 'contracts': None, 'bars': None}
        return {'providers': outcomes, 'mode': 'official_local_import' if local else 'official_explicit_refresh'}
    if operation == 'ui_demo':
        data = synthetic_dataset(payload.get('bars', 960))
        save_dataset(data, root / 'dataset.json')
        return {'dataset': str(root / 'dataset.json'), 'source_type': 'synthetic', 'bars': len(data.bars)}
    if operation == 'ui_import':
        from quantlab.data import SessionCalendar, import_taifex
        cal = read_json(Path(payload['calendar']))
        if payload['kind'] == 'validated_dataset':
            data = load_dataset(Path(payload['path']))
            dataset_market_series(data, cal)
        else:
            data = import_taifex(Path(payload['path']), kind=payload['kind'],
                                calendar=SessionCalendar(cal['sessions'], version=cal['version']),
                                contract_id=payload.get('contract') or None, encoding=payload.get('encoding'))
        save_dataset(data, root / 'dataset.json')
        write_json(root / 'dataset_calendar.json', cal)
        return {'dataset': str(root / 'dataset.json'), 'manifest': to_dict(data.manifest), 'quality': to_dict(data.quality)}
    if operation == 'ui_refresh':
        if payload.get('network_opt_in') is not True:
            raise ValidationError('需明確同意連線至臺灣期交所下載公開資料')
        from quantlab.downloads import refresh
        return refresh(Path(paths.cache), days=payload.get('days', 1), kind=payload.get('format', 'csv'))
    if operation == 'ui_backtest':
        from quantlab.strategies import builtin_strategies, validate_strategy
        from quantlab.backtest import run_backtest
        from quantlab.__main__ import config_from_json
        data = _dataset(root, payload)
        config = config_from_json(payload['config'])
        specs = list(builtin_strategies())
        provenance = None
        if payload.get('candidate'):
            if payload.get('batch'): raise ValidationError('生成候選不可與預設家族批次混用')
            spec, provenance = candidate_record(root, payload['candidate'])
            source_hash = data.manifest.get('parent_data_hash', data.manifest['data_hash'])
            if provenance['source_data_hash'] != source_hash: raise ValidationError('候選研究與目前資料來源不符；請切回原資料')
            specs = [spec]
        elif not payload.get('batch'):
            spec = next((s for s in specs if s.family == payload['family']), None)
            if spec is None:
                raise ValidationError('未知策略家族')
            spec = StrategySpec(spec.strategy_id, spec.family, payload.get('parameters', dict(spec.parameters)), dict(spec.rules))
            validate_strategy(spec)
            specs = [spec]
        if provenance:
            manifest = {**data.manifest, 'desktop_candidate_reference': provenance['reference']}
            manifest['manifest_hash'] = content_hash({k:v for k,v in manifest.items() if k not in ('imported_at','manifest_hash')})
            data = Dataset(data.bars, manifest, dict(data.quality))
        reports = []
        for spec in specs:
            result = run_backtest(data, spec, config)
            # Publish a complete immutable report folder, never a half-written result.
            import tempfile
            reports_root = root / 'reports'; reports_root.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.partial-', dir=reports_root) as staging:
                files = export_report(result, Path(staging))
                folder = Path(files['result']).parent
                write_json(folder / 'strategy.json', spec)
                if provenance: write_json(folder / 'candidate_provenance.json', provenance)
                destination = reports_root / files['result_hash']
                if destination.exists():
                    if content_hash(load_result(destination / 'result.json')) != files['result_hash'] or read_json(destination / 'strategy.json') != to_dict(spec):
                        raise ValidationError('已存在的報告不完整或不符合雜湊；原檔保留')
                else: folder.rename(destination)
                files = {key: str(destination / Path(value).name) if key != 'result_hash' else value for key, value in files.items()}
            reports.append(files)
        write_json(root / 'active_result.json', {'result_hash': reports[-1]['result_hash']})
        return {'reports': reports, 'source_type': data.manifest['source_type'], 'scope': 'research_only'}
    if operation == 'ui_campaign':
        from quantlab.research import FixtureGenerator, run_campaign, demo_campaign_config
        from quantlab.__main__ import config_from_json
        data = _dataset(root, payload)
        config = payload.get('config') or demo_campaign_config(data, demo_config())
        if isinstance(config.get('backtest_config'), dict):
            config['backtest_config'] = config_from_json(config['backtest_config'])
        options = payload['provider']
        if options.get('mode') == 'chatgpt_plan':
            generator, plan_identity = plan_provider(paths, data, config, options)
            options = {'mode':'chatgpt_plan','binding':plan_identity}
        elif options.get('mode') == 'manual':
            from quantlab.manual_exchange import export_request_file, import_response, import_response_file
            if payload.get('manual_export'):
                request = export_request_file(data, config, Path(payload['manual_export']))
                return {'manual_export': payload['manual_export'], 'request': request, 'mode': 'manual_unverified'}
            if options.get('response_path'):
                generator = import_response_file(data, config, Path(options['response_path']))
            else:
                generator = import_response(data, config, options.get('response_text', ''))
            generator.preflight(data, config)
            research_controls(paths)
            options = {'mode': 'manual', 'package': generator.model}
        else:
            generator = campaign_generator(paths, options)
        name = content_hash({'dataset': data.manifest['data_hash'], 'config': config, 'provider': provider_binding_options(options)})
        return run_campaign(data, config=config, generator=generator, output_dir=root / 'campaigns' / name,
                            holdout_registry_path=research_controls(paths) / 'holdout-registry.sqlite3')
    if operation == 'ui_compare':
        if not payload.get('results'): raise ValidationError('請至少選擇一個結果')
        return {'rows': comparison_rows([load_result(p) for p in payload['results']])}
    if operation == 'ui_select':
        folder = Path(payload['result']).parent
        result = load_result(folder / 'result.json')
        reference = result.manifest.get('dataset_manifest', {}).get('desktop_candidate_reference')
        if reference:
            spec, provenance = candidate_record(root, reference)
            if not provenance['paper_qualified']: raise ValidationError('生成候選尚未通過 OOS／保留集門檻；只允許研究，不可啟用紙上策略')
            if content_hash(spec) != result.manifest.get('spec_hash'): raise ValidationError('候選與回測策略不符')
        return save_selection(read_json(folder / 'strategy.json'), result, root / 'selection.json')
    if operation == 'ui_disable':
        selection = root / 'selection.json'
        if selection.exists():
            archive = root / 'disabled_selections'
            archive.mkdir(exist_ok=True)
            value = read_json(selection)
            write_json(archive / (content_hash(value) + '.json'), value)
            selection.unlink()
        if (root / 'paper_policy.json').exists():
            _paper(root).set_kill_switch(True)
        return {'selection': 'disabled', 'scope': 'research_and_paper_only'}
    if operation.startswith('ui_paper_'):
        # Explicit policy is required; never infer an official calendar from prices.
        if 'policy' in payload:
            policy = payload['policy']
            existing = root / 'paper_policy.json'
            if existing.exists() and read_json(existing) != policy:
                raise ValidationError('紙上帳戶政策已鎖定；請使用新工作區')
            if not existing.exists():
                from quantlab.paper import PaperBroker
                if not isinstance(policy, dict) or set(policy) != {'contract_id', 'risk_sessions', 'margin_schedule'}:
                    raise ValidationError('政策必須包含 contract_id、risk_sessions、margin_schedule')
                # Validate in a disposable journal first: invalid policy cannot poison startup.
                import tempfile
                with tempfile.TemporaryDirectory(prefix='policy-', dir=root) as staging:
                    PaperBroker(Path(staging) / 'validation.sqlite3', instrument=Instrument(policy['contract_id']),
                                costs=demo_config().costs, limits=paper_risk_limits(),
                                risk_sessions=tuple(policy['risk_sessions']), margin_schedule=tuple(policy['margin_schedule']))
                write_json(existing, policy)
        broker = _paper(root)
        if operation == 'ui_paper_reconcile':
            broker.reconcile(payload['snapshot'])
        elif operation == 'ui_paper_kill':
            broker.set_kill_switch(True)
        elif operation == 'ui_paper_submit':
            if payload.get('reconcile_confirmed') is not True:
                raise ValidationError('每次紙上執行前須明確確認參考快照')
            broker.reconcile(payload['snapshot'])
            selection = load_selection(root / 'selection.json')
            if payload['intent'].get('strategy_hash') != selection['strategy_hash']:
                raise ValidationError('委託與啟用策略雜湊不符')
            broker.set_kill_switch(False)
            broker.submit(payload['intent'], quote=payload['quote'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
        elif operation == 'ui_paper_cancel':
            broker.cancel(payload['order_id'], now=datetime.fromisoformat(payload['now'].replace('Z', '+00:00')))
        elif operation == 'ui_paper_replay':
            if payload.get('reconcile_confirmed') is not True:
                raise ValidationError('每次紙上重播前須明確確認參考快照')
            broker.reconcile(payload['snapshot'])
            from quantlab.paper_replay import PaperReplay
            data = _dataset(root, payload)
            selection = load_selection(root / 'selection.json')
            binding = content_hash([data.manifest['data_hash'], selection['strategy_hash']])
            paths.require_replay_wal()
            replay = PaperReplay(root / 'replays' / (binding + '.sqlite3'), dataset=data,
                                 strategy=StrategySpec(**selection['strategy']), broker=broker,
                                 margin_schedule=broker._margin_schedule, storage_profile="wal_full")
            replay.start()
            try:
                replay.step(max_bars=payload.get('max_bars', 100))
            finally:
                replay.stop()
            return {'replay': replay.snapshot(), 'account': broker.snapshot()}
        state = broker.snapshot()
        journal = broker.journal_events()
        write_json(root / 'paper_snapshot.json', state)
        write_json(root / 'paper_journal_export.json', journal)
        return {'account': state, 'journal_tail': journal[-20:], 'journal_file': str(root / 'paper_journal_export.json')}
    raise ValidationError('未實作作業')



def latest_market_observations(series):
    """Choose observed contract history, never infer a live or executable quote.

    Date/session ordering is explicit. Same-session sources without event times
    are not time-comparable: retain the first source (official daily cache).
    """
    chosen = {}
    session_order = {'night': 0, 'day': 1, 'combined': 2}
    for item in series:
        key = item.instrument.contract_id
        previous = chosen.get(key)
        if previous is None:
            chosen[key] = item
            continue
        latest, old = item.bars[-1], previous.bars[-1]
        rank = (latest.trade_date, session_order[latest.session])
        old_rank = (old.trade_date, session_order[old.session])
        if rank > old_rank or (rank == old_rank and latest.end is not None and old.end is not None and latest.end > old.end):
            chosen[key] = item
    return tuple(chosen.values())


def dataset_market_series(dataset, calendar_payload):
    """Adapt only validated one-minute official history with hash-bound calendar."""
    from quantlab.data import validate_dataset, SessionCalendar
    from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance, bar_key
    validate_dataset(dataset)
    manifest = dataset.manifest
    if manifest['source_type'] != 'official_local' or manifest.get('bar_granularity') != 'minute' or manifest.get('timeframe_minutes', 1) != 1:
        raise ValidationError('只接受明確的一分鐘官方歷史；不把合成或日資料轉成分鐘')
    calendar = SessionCalendar(calendar_payload['sessions'], version=calendar_payload['version'])
    if calendar.hash != manifest.get('calendar_hash'): raise ValidationError('交易日曆與研究資料雜湊不符')
    grouped = {}
    for bar in dataset.bars:
        instrument = InstrumentRef('TAIFEX', 'TMF', bar.contract_id, bar.contract_id.split(':')[-1])
        session = calendar.lookup(bar.timestamp, bar.contract_id)
        value = MarketBar(instrument, bar.trade_date, bar.session, bar.open, bar.high, bar.low, bar.close, bar.volume,
            interval='1m', timestamp=bar.timestamp, end=bar.end, session_open=session['open'], session_end=session['end'], source_id=bar.source_id)
        grouped.setdefault(instrument, []).append(value)
    result = []
    for instrument, bars in grouped.items():
        bars.sort(key=bar_key); dates = [b.trade_date for b in bars]
        provenance = SourceProvenance(manifest['source_url'], manifest['source_hash'],
            'TAIFEX 官方歷史；原始研究資料雜湊 ' + manifest['data_hash'],
            'https://www.taifex.com.tw', datetime.fromisoformat(manifest['imported_at'].replace('Z', '+00:00')),
            max(dates), min(dates), max(dates), mode='history', timestamp_basis='hash-bound explicit session calendar; one-minute source',
            warnings=tuple(str(x) for x in dataset.quality.get('warnings', ())))
        result.append(MarketSeries(instrument, tuple(bars), provenance))
    return tuple(result)

from PySide6.QtCore import Qt, QTimer, QPointF, QUrl
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF, QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QStackedWidget, QPushButton, QLineEdit, QPlainTextEdit, QComboBox,
    QSpinBox, QCheckBox, QProgressBar, QFileDialog, QFormLayout, QScrollArea,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QMessageBox, QApplication, QGroupBox)


class EquityPlot(QWidget):
    """Small native paint widget; no browser or extra plotting dependency."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = []
        self.setMinimumHeight(180)
        self.setAccessibleName('權益曲線，依時間排序')

    def set_values(self, rows):
        self.values = [float(row['equity']) for row in rows]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#172230'))
        painter.setPen(QColor('#dbe4ef'))
        if not self.values:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '尚無權益資料')
            return
        lo, hi = min(self.values), max(self.values)
        painter.drawText(8, 18, f'權益 TWD  最低 {lo:,.0f}  最高 {hi:,.0f} | 時間 →')
        points = QPolygonF([QPointF(16 + i * (self.width()-32) / max(1, len(self.values)-1),
                       self.height()-20-(v-lo) * (self.height()-55) / max(1, hi-lo)) for i, v in enumerate(self.values)])
        painter.setPen(QPen(QColor('#2563eb'), 2))
        painter.drawPolyline(points)


from desktop_market import MarketDashboard, MarketHistoryDialog
from desktop_forms import (StrategyForm, BacktestForm, CampaignForm, WalkForwardForm, PaperPolicyForm,
    PaperIntentForm, PaperQuoteForm, PaperSnapshotForm, ResultTable, SummaryCard, BacktestSummaryCard, BacktestFillsTable, CandidateSummaryCard)


class MainWindow(QMainWindow):
    def __init__(self, paths, jobs, settings=None, backups=None, guard=None):
        super().__init__()
        self.paths, self.jobs, self.settings, self.backups, self.guard = paths, jobs, settings, backups, guard
        self.root = _root(paths)
        self.actions = []
        self.last_operation = None
        self._ui_job_id = None
        self._wf_preview = None
        self._wf_request_key = None
        self._wf_launch = None
        self._wf_pending_reconcile = False
        self._wf_source_stamp = None
        self.active_candidate = None
        self._advanced_values = {}
        self._market_outcomes = {}
        self._campaign_data_hash = None
        self._chatgpt_job_request = None
        self._chatgpt_job_id = None
        self._plan_usage_binding = None
        self._subscription_campaign = False
        self._plan_launch = None
        self._pending_plan_reconcile = False
        self._pending_usage_refresh = False
        self._analysis_preview = None
        self._analysis_request_key = None
        self._analysis_launch = None
        self._analysis_running = False
        self._pending_analysis_reconcile = False
        self.setWindowTitle('TMF 量化研究桌面｜研究與紙上模擬')
        self.resize(1366, 768)
        self.setStyleSheet('''
            QMainWindow, QScrollArea, QStackedWidget { background: #101720; }
            QWidget { background: #101720; font-family: "Microsoft JhengHei UI", "Noto Sans CJK TC", sans-serif; font-size: 14px; color: #dbe4ef; }
            QLabel { padding: 3px 0; }
            QListWidget { background: #12243b; color: #e3edf9; border: none; border-radius: 9px; padding: 9px; }
            QListWidget::item { padding: 12px 8px; border-radius: 5px; }
            QListWidget::item:selected { background: #2865c4; color: white; }
            QPushButton { background: #2563ba; color: white; border: none; border-radius: 6px; padding: 9px 14px; min-height: 20px; }
            QPushButton:hover { background: #1b4f9b; }
            QPushButton:disabled { background: #243448; color: #9aabbc; }
            QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background: #172230; border: 1px solid #43566c; border-radius: 5px; padding: 7px; selection-background-color: #2563ba; }
            QCheckBox { padding: 7px 0; }
            QTableWidget { background:#172230; alternate-background-color:#1d2b3c; gridline-color:#354459; selection-background-color:#285f89; }
            QHeaderView::section { background:#243448; color:#e0e8f3; padding:6px; border:0; }
            QProgressBar { border: 1px solid #43566c; border-radius: 4px; background: #172230; text-align: center; }
            QProgressBar::chunk { background: #2563ba; }
        ''')
        body = QWidget(); outer = QVBoxLayout(body)
        banner = QLabel('研究／模擬交易｜實盤停用')
        banner.setWordWrap(True); banner.setStyleSheet('background:#30291d;color:#f1d38a;padding:10px')
        outer.addWidget(banner)
        horizontal = QHBoxLayout(); outer.addLayout(horizontal, 1)
        self.navigation = QListWidget(); self.navigation.setObjectName('navigation'); self.navigation.setMaximumWidth(180)
        self.stack = QStackedWidget(); horizontal.addWidget(self.navigation); horizontal.addWidget(self.stack, 1)
        self.status = QLabel('就緒'); self.status.setObjectName('status'); self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.notification = QLabel(''); self.notification.setObjectName('local_notification'); self.notification.setWordWrap(True); self.notification.hide(); outer.addWidget(self.notification)
        progress = QHBoxLayout(); self.progress = QProgressBar(); self.progress.setRange(0, 100)
        self.cancel_button = QPushButton('取消背景作業'); self.cancel_button.setObjectName('cancel_job')
        self.cancel_button.clicked.connect(self.cancel_job); self.cancel_button.setEnabled(False)
        progress.addWidget(self.progress); progress.addWidget(self.cancel_button); outer.addLayout(progress)
        self.setCentralWidget(body)
        self._dashboard(); self._data_page(); self._strategy_page(); self._backtest_page(); self._compare_page(); self._paper_page(); self._settings_page()
        self.chatgpt_panel.model.currentIndexChanged.connect(self._invalidate_analysis_preview)
        self.chatgpt_panel.timeout.valueChanged.connect(self._invalidate_analysis_preview)
        self.chatgpt_panel.account.currentIndexChanged.connect(self._invalidate_analysis_preview)
        self._connect_walk_forward_inputs()
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex); self.navigation.setCurrentRow(0)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll_jobs); self.timer.start(150)
        self._safe(self.refresh_views)
        self._safe(self.load_settings)
        self._busy(False)

    def _page(self, label):
        self.navigation.addItem(label)
        page = QWidget(); layout = QVBoxLayout(page)
        title = QLabel(label); title.setStyleSheet('font-size:22px;font-weight:600'); layout.addWidget(title)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page); self.stack.addWidget(scroll)
        return layout

    def _button(self, layout, text, name, callback):
        button = QPushButton(text); button.setObjectName(name); button.clicked.connect(lambda checked=False: self._safe(callback))
        layout.addWidget(button); self.actions.append(button)
        return button

    def _text(self, layout, label, value='', multiline=False):
        layout.addWidget(QLabel(label))
        field = QPlainTextEdit(value) if multiline else QLineEdit(value)
        if multiline: field.setMaximumHeight(150)
        layout.addWidget(field)
        return field

    def _advanced(self, layout, title='進階診斷 JSON（一般操作不需要）'):
        toggle = QCheckBox(title); layout.addWidget(toggle)
        box = QWidget(); inner = QVBoxLayout(box); inner.setContentsMargins(0,0,0,0)
        layout.addWidget(box); box.hide(); toggle.toggled.connect(box.setVisible)
        return inner

    def _payload(self, editor, build):
        text = editor.toPlainText()
        if text != self._advanced_values.get(editor, text):
            return json.loads(text)
        return build()

    def _remember(self, editor):
        self._advanced_values[editor] = editor.toPlainText()

    def _dashboard(self):
        self.navigation.addItem('市場總覽')
        self.market = MarketDashboard(); self.stack.addWidget(self.market)
        self.market.refresh_requested.connect(lambda: self._safe(self.refresh_market))
        self.market.preferences_changed.connect(lambda: self._safe(self.save_market_preferences))
        self.market.series_rendered.connect(lambda _: self._safe(self.bind_result_layers))
        # Compatibility diagnostics remain available on the data page, not the landing page.
        self.overview = QLabel(); self.data_card = QLabel()
        self.summary = QPlainTextEdit(); self.summary.setReadOnly(True)

    def refresh_market(self):
        if self.jobs.active: raise ValidationError('已有背景作業，請等待或取消')
        answer = QMessageBox.question(self, '更新官方唯讀資料',
            '本次連線 TWSE 與 TAIFEX 免費公開端點，下載歷史／盤後資料？不含即時行情、不使用交易帳密。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.start_job('ui_market_refresh', {'network_opt_in': True})

    def import_market_file(self):
        name, _ = QFileDialog.getOpenFileName(self, '選擇官方格式原始資料（本機檔案來源仍需自行核對）', '', 'JSON / CSV (*.json *.csv)')
        if name:
            provider, format_name = self.market_provider.currentData()
            self.start_job('ui_market_refresh', {'provider': provider, 'format': format_name, 'local_path': name})

    def import_market_history(self):
        if self.jobs.active: raise ValidationError('已有背景作業，請等待或取消')
        if getattr(self, '_closing', False):
            raise ValidationError('視窗正在關閉，不能啟動新匯入')
        existing = getattr(self, '_history_dialog', None)
        if existing is not None:
            existing.raise_(); existing.activateWindow(); return
        dialog = MarketHistoryDialog(self)
        self._history_dialog = dialog
        def accepted():
            if not getattr(self, '_closing', False):
                self._safe(lambda: self.start_job('ui_market_refresh', dialog.payload()))
        def finished(_):
            if self._history_dialog is dialog: self._history_dialog = None
            dialog.deleteLater()
        dialog.accepted.connect(accepted)
        dialog.finished.connect(finished)
        dialog.open()

    def save_market_preferences(self):
        if self.settings is None: return
        value = self.settings.load()
        value['market'] = self.market.preferences()
        geometry = self.geometry()
        value['window'] = {'x': self.x(), 'y': self.y(), 'width': geometry.width(), 'height': geometry.height()}
        self.settings.save(value)

    def _data_page(self):
        layout = self._page('資料匯入與更新')
        layout.addWidget(self.overview)
        self.market_provider = QComboBox(); self.market_provider.addItem('TWSE 加權指數官方格式 JSON', ('twse', 'json')); self.market_provider.addItem('TAIFEX 每日行情官方格式 JSON', ('taifex', 'json')); self.market_provider.addItem('TAIFEX 每日行情官方格式 CSV', ('taifex', 'csv')); layout.addWidget(self.market_provider)
        self._button(layout, '匯入官方唯讀行情（不變更研究資料）', 'import_market_file', self.import_market_file)
        self._button(layout, '匯入逐筆歷史 CSV / RPT（明確時段，唯讀）', 'import_market_history', self.import_market_history)
        self.import_path = self._text(layout, '本機 CSV / RPT / JSON 檔案')
        self._button(layout, '選擇資料檔案', 'browse_data', lambda: self._browse(self.import_path))
        self.calendar_path = self._text(layout, '版本化交易日曆 JSON（必填）')
        self._button(layout, '選擇交易日曆', 'browse_calendar', lambda: self._browse(self.calendar_path))
        self.import_kind = QComboBox(); self.import_kind.addItems(['validated_dataset', 'ticks', 'ticks_rpt', 'daily_json', 'synthetic_daily_json', 'synthetic_bars', 'synthetic_ticks', 'proxy_bars', 'proxy_ticks']); layout.addWidget(self.import_kind)
        self.contract = self._text(layout, '合約（可留空）', 'TAIFEX:TMF:202601')
        self._button(layout, '匯入並驗證資料', 'import_data', self.import_data)
        self.bars = QSpinBox(); self.bars.setRange(120, 10000); self.bars.setValue(960); layout.addWidget(self.bars)
        self._button(layout, '建立合成示範資料', 'create_demo', lambda: self.start_job('ui_demo', {'bars': self.bars.value()}))
        self.network_data = QCheckBox('同意本次連線至 TAIFEX 下載免費公開資料（不會自動匯入）'); layout.addWidget(self.network_data)
        self.days = QSpinBox(); self.days.setRange(1, 30); layout.addWidget(self.days)
        self._button(layout, '下載最近交易日資料', 'refresh_data', self.download_data)
        details = self._advanced(layout)
        self.data_detail = QPlainTextEdit(); self.data_detail.setReadOnly(True); details.addWidget(self.data_detail); details.addWidget(self.summary)

    def _strategy_page(self):
        from quantlab.strategies import builtin_strategies
        layout = self._page('AI 策略中心')
        self.chatgpt_sign_in_entry = self._button(layout, '使用 ChatGPT 帳戶登入', 'chatgpt_sign_in_entry', self.show_chatgpt_sign_in)
        layout.addWidget(QLabel('五種有限策略家族與受驗證參數；禁止任意 Python 策略程式。'))
        self.strategy_form = StrategyForm(); layout.addWidget(self.strategy_form)
        advanced = self._advanced(layout)
        self.family = QComboBox(); self.family.addItems([s.family for s in builtin_strategies()]); advanced.addWidget(self.family)
        self.parameters = self._text(advanced, '策略參數 JSON', '{}', True)
        self.strategy_detail = QPlainTextEdit(); self.strategy_detail.setReadOnly(True); advanced.addWidget(self.strategy_detail)
        self.family.currentIndexChanged.connect(self._family_changed); self._family_changed()
        self._walk_forward_section(layout)
        layout.addWidget(QLabel('離線 Fixture 生成器：固定候選與版本紀錄；不是已驗證的真實模型。'))
        self.strategy_form.family.currentIndexChanged.connect(lambda: self.family.setCurrentIndex(self.strategy_form.family.currentIndex()))
        self.campaign_form = CampaignForm(); layout.addWidget(self.campaign_form)
        self.campaign_config = self._text(advanced, '研究設定 JSON（空白使用明示示範切分）', '', True)
        self._remember(self.campaign_config)
        self.provider_mode = QComboBox(); self.provider_mode.addItem('官方 ChatGPT 訂閱（需自行授權；實際推論未驗證）', 'chatgpt_plan'); self.provider_mode.addItem('離線 Fixture（非真實 AI，需明確選取）', 'fixture'); self.provider_mode.addItem('手動 AI 交換（使用者自行傳送／貼回，未驗證）', 'manual'); layout.addWidget(self.provider_mode)
        manual = QWidget(); manual_layout = QVBoxLayout(manual); layout.addWidget(manual); manual.hide()
        self.provider_mode.currentIndexChanged.connect(lambda: manual.setVisible(self.provider_mode.currentData() == 'manual'))
        self.manual_path = self._text(manual_layout, '手動 AI 回應檔案（選檔或直接貼回回應；不自動連線）')
        self._button(manual_layout, '選取手動 AI 回應檔', 'browse_manual_response', lambda: self._browse(self.manual_path))
        self.manual_response = self._text(manual_layout, '貼回 AI 原始回應（不需手寫結構；勿含帳密）', '', True)
        self._button(manual_layout, '匯出手動 AI 請求與回應格式', 'export_manual_request', self.export_manual_request)
        self._button(layout, '核對本次訂閱研究請求紀錄（不連網）', 'chatgpt_campaign_usage', self.inspect_plan_usage)
        self._button(layout, '生成／重開研究與 OOS', 'run_campaign', self.run_campaign)
        self.candidate_choice = QComboBox(); self.candidate_choice.setObjectName('candidate_choice'); self.candidate_choice.currentIndexChanged.connect(self.inspect_candidate); layout.addWidget(self.candidate_choice)
        self.candidate_detail = QPlainTextEdit(); self.candidate_detail.setReadOnly(True); advanced.addWidget(self.candidate_detail)
        self.candidate_card = CandidateSummaryCard(); layout.addWidget(self.candidate_card)
        self.use_candidate_button = self._button(layout, '使用此不可變候選版本進行研究回測', 'use_candidate', self.use_candidate)
        self._button(layout, '改用內建家族與可編輯參數', 'use_builtin', self.use_builtin)
        self.history = QPlainTextEdit(); self.history.setReadOnly(True); advanced.addWidget(self.history)
        self.history_table = ResultTable(); layout.addWidget(self.history_table)
        layout.addWidget(QLabel('已保存樣本外／保留集評估（不回饋模型；沒有結果即未提供）'))
        self.evaluation_table = ResultTable(); layout.addWidget(self.evaluation_table)

    def _walk_forward_section(self, layout):
        section = QGroupBox('固定候選池 Walk-forward（技術驗證）')
        content = QVBoxLayout(section); layout.addWidget(section)
        self.walk_forward_form = WalkForwardForm(); content.addWidget(self.walk_forward_form)
        self.walk_forward_saved_controls = QWidget(); saved = QFormLayout(self.walk_forward_saved_controls)
        self.walk_forward_campaign = QComboBox(); self.walk_forward_campaign.setObjectName('walk_forward_campaign')
        self.walk_forward_campaign.addItem('請明確選取已保存研究（尚未核對）', None)
        saved.addRow('唯一來源研究', self.walk_forward_campaign)
        self.walk_forward_original = QLineEdit(); self.walk_forward_original.setReadOnly(True)
        self.walk_forward_original.setObjectName('walk_forward_original_dataset')
        self.walk_forward_original.setPlaceholderText('請選取該研究當時使用的完整原始資料檔')
        saved.addRow('完整原始資料', self.walk_forward_original)
        self._button(saved, '選取本機原始資料檔', 'pick_walk_forward_original', self.pick_walk_forward_original)
        notice = QLabel('必須保留當時完整資料，並核對全部候選來源。檔名或宣告日期相同不足以通過；不會從研究紀錄自動載入路徑。')
        notice.setWordWrap(True); saved.addRow(notice); content.addWidget(self.walk_forward_saved_controls)
        self.walk_forward_saved_controls.setEnabled(False)
        self._button(content, '預覽精確切分、風險門檻與一次性額度', 'preview_walk_forward', self.preview_walk_forward)
        self.walk_forward_preview = QPlainTextEdit(); self.walk_forward_preview.setReadOnly(True)
        self.walk_forward_preview.setObjectName('walk_forward_preview'); self.walk_forward_preview.setMinimumHeight(410)
        content.addWidget(self.walk_forward_preview)
        self.walk_forward_advanced_group = QGroupBox('進階：完整來源證據、雜湊與設定')
        self.walk_forward_advanced_group.setCheckable(True); self.walk_forward_advanced_group.setChecked(False)
        advanced = QVBoxLayout(self.walk_forward_advanced_group)
        self.walk_forward_advanced = QPlainTextEdit(); self.walk_forward_advanced.setReadOnly(True)
        self.walk_forward_advanced.setObjectName('walk_forward_advanced'); self.walk_forward_advanced.hide()
        advanced.addWidget(self.walk_forward_advanced)
        self.walk_forward_advanced_group.toggled.connect(self.walk_forward_advanced.setVisible)
        content.addWidget(self.walk_forward_advanced_group)
        self.walk_forward_consent = QCheckBox('我已核對預覽：所有前推 OOS 範圍在評分前不可逆消耗，取消仍保留消耗；最終保留集排除且不評估')
        self.walk_forward_consent.setObjectName('walk_forward_consent'); content.addWidget(self.walk_forward_consent)
        self.walk_forward_start = self._button(content, '執行／讀取同一計畫（不重試 OOS）', 'run_walk_forward', self.run_walk_forward)
        self.walk_forward_choice = QComboBox(); self.walk_forward_choice.setObjectName('walk_forward_choice'); content.addWidget(self.walk_forward_choice)
        self._button(content, '唯讀重開已保存 Walk-forward 結果', 'read_walk_forward', self.read_walk_forward)
        self.walk_forward_status = QLabel('尚未預覽。此區與 AI 研究歷史及紙上資格完全分開。')
        self.walk_forward_status.setWordWrap(True); content.addWidget(self.walk_forward_status)
        self.walk_forward_results = ResultTable(); content.addWidget(self.walk_forward_results)

    def _connect_walk_forward_inputs(self):
        for form in (self.walk_forward_form, self.backtest_form):
            for field in form.fields.values():
                signal = field.currentIndexChanged if isinstance(field, QComboBox) else field.textChanged
                signal.connect(self._invalidate_walk_forward_preview)
        self.walk_forward_form.fields['pool_origin'].currentIndexChanged.connect(self._walk_forward_origin_changed)
        self.walk_forward_campaign.currentIndexChanged.connect(self._invalidate_walk_forward_preview)
        self.walk_forward_original.textChanged.connect(self._invalidate_walk_forward_preview)
        self.backtest_form.expiries.table.itemChanged.connect(self._invalidate_walk_forward_preview)
        model = self.backtest_form.expiries.table.model()
        model.rowsInserted.connect(self._invalidate_walk_forward_preview)
        model.rowsRemoved.connect(self._invalidate_walk_forward_preview)
        self.config.textChanged.connect(self._invalidate_walk_forward_preview)

    def _walk_forward_origin_changed(self, *args):
        saved = self.walk_forward_form.fields['pool_origin'].currentData() == 'saved_campaign_pool'
        self.walk_forward_saved_controls.setEnabled(saved)
        self._invalidate_walk_forward_preview()

    def pick_walk_forward_original(self):
        name, _ = QFileDialog.getOpenFileName(self, '選取來源研究的完整原始資料（不會取代目前資料）', '', 'Quantlab 完整資料 (*.json)')
        if not name: return
        if '://' in name or name.startswith(('//', '\\\\')) or not Path(name).is_absolute():
            raise ValidationError('請使用明確的本機絕對檔案路徑')
        path = Path(name).resolve(strict=True)
        if not path.is_file(): raise ValidationError('請選取本機完整資料檔')
        self.walk_forward_original.setText(str(path))

    def _walk_forward_saved_source(self):
        if self.walk_forward_form.fields['pool_origin'].currentData() != 'saved_campaign_pool': return None
        reference = self.walk_forward_campaign.currentData()
        if not reference: raise ValidationError('請明確選取已保存的來源研究')
        path = self.walk_forward_original.text()
        if not path: raise ValidationError('請明確選取該研究完整的原始資料檔')
        return {'campaign_reference': reference, 'original_dataset': {'kind': 'local_dataset_file', 'path': path}}

    def _invalidate_walk_forward_preview(self, *args):
        self._wf_preview = None
        self.walk_forward_consent.setChecked(False)
        self.walk_forward_start.setEnabled(False)
        self.walk_forward_preview.setPlainText('來源或設定已變更，請重新預覽精確範圍。')
        self.walk_forward_status.setText('預覽已失效：來源或設定已變更，請重新預覽；目前不可開始。')
        self.walk_forward_advanced.clear()

    def _walk_forward_input_key(self):
        path = self.root / 'dataset.json'
        stat = path.stat()
        typed = self.backtest_form.build_payload()
        config = self._payload(self.config, lambda: typed['config'])
        plan = self.walk_forward_form.build_payload(config)
        # Worker checks full data/manifest and engine hashes again before running;
        # this cheap UI key only discards stale asynchronous preview responses.
        source = self._walk_forward_saved_source()
        inputs = {'plan': plan, 'source': [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]}
        if source is not None:
            from quantlab.desktop_runtime import validate_walk_forward_request
            validate_walk_forward_request(plan, source)
            from desktop_walk_forward import source_campaign_folder
            folder = source_campaign_folder(self.paths, source['campaign_reference'])
            files = (folder / 'campaign.json', folder / 'campaign.sqlite3', Path(source['original_dataset']['path']))
            inputs['saved_source'] = source
            inputs['saved_files'] = [[p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns] for p in files]
        return content_hash(inputs), plan

    def preview_walk_forward(self):
        self._invalidate_walk_forward_preview()
        self.walk_forward_results.set_rows([])
        key, plan = self._walk_forward_input_key()
        payload = {'plan': plan}
        source = self._walk_forward_saved_source()
        if source is not None: payload['saved_source'] = source
        self.start_job('ui_walk_forward_preview', payload)
        self._wf_request_key = key
        self.walk_forward_preview.setPlainText('正在核對來源、切分範圍與評估額度，請稍候。')
        self.walk_forward_status.setText('預覽核對中；尚未保留或消耗新範圍，目前不可開始。')

    def run_walk_forward(self):
        if self._wf_preview is None or not self.walk_forward_consent.isChecked():
            raise ValidationError('請先預覽並明確確認範圍與不可逆消耗')
        key, plan = self._walk_forward_input_key()
        if key != self._wf_request_key:
            self._invalidate_walk_forward_preview()
            raise ValidationError('來源或設定已變更，請重新預覽')
        identity = self._wf_preview['preview_identity']
        if (self.root / 'walk_forward' / identity / 'walk_forward.sqlite3').exists():
            self.start_job('ui_walk_forward_read', {'reference': identity})
            self.walk_forward_consent.setChecked(False)
            return
        payload = {'plan': plan, 'preview_identity': identity}
        source = self._walk_forward_saved_source()
        if source is not None: payload['saved_source'] = source
        job = self.start_job('ui_walk_forward_run', payload)
        self._wf_launch = {'reference': identity, 'stopped_job_id': job}
        self.walk_forward_consent.setChecked(False)

    def read_walk_forward(self):
        reference = self.walk_forward_choice.currentData()
        if not reference: raise ValidationError('尚無可重開的 Walk-forward 紀錄')
        self.start_job('ui_walk_forward_read', {'reference': reference})

    def _refresh_walk_forward_references(self):
        previous = self.walk_forward_choice.currentData()
        self.walk_forward_choice.clear()
        for path in sorted((self.root / 'walk_forward').glob('*/walk_forward.sqlite3')):
            name = path.parent.name
            if len(name) == 64 and all(c in '0123456789abcdef' for c in name):
                self.walk_forward_choice.addItem('識別碼 ' + name[:12], name)
        index = self.walk_forward_choice.findData(previous)
        if index >= 0: self.walk_forward_choice.setCurrentIndex(index)
        selected = self.walk_forward_campaign.currentData()
        self.walk_forward_campaign.blockSignals(True)
        self.walk_forward_campaign.clear(); self.walk_forward_campaign.addItem('請明確選取已保存研究（尚未核對）', None)
        for path in sorted((self.root / 'campaigns').glob('*/campaign.sqlite3')):
            name = path.parent.name
            if len(name) == 64 and all(c in '0123456789abcdef' for c in name):
                self.walk_forward_campaign.addItem('研究識別碼 ' + name[:12], name)
        index = self.walk_forward_campaign.findData(selected)
        self.walk_forward_campaign.setCurrentIndex(max(0, index))
        self.walk_forward_campaign.blockSignals(False)
        if selected != self.walk_forward_campaign.currentData(): self._invalidate_walk_forward_preview()

    def _walk_forward_event(self, event):
        operation = self.last_operation or ''
        if not operation.startswith('ui_walk_forward_'): return False
        kind = event.get('type')
        if kind == 'progress':
            self.status.setText('Walk-forward 背景作業進行中；無模型呼叫。')
            return True
        if kind not in ('result', 'error', 'cancelled'): return True
        self.record_event(operation, kind)
        if kind == 'result':
            result = event['result']
            if operation == 'ui_walk_forward_preview':
                try: current = self._walk_forward_input_key()[0]
                except (ValueError, OSError): current = None
                if current != self._wf_request_key:
                    self._invalidate_walk_forward_preview()
                    self.status.setText('預覽期間來源或設定已變更，請重新預覽。')
                    return True
                from desktop_walk_forward import preview_text
                self.walk_forward_preview.setPlainText(preview_text(result))
                self.walk_forward_advanced.setPlainText(preview_text(result, advanced=True))
                if result.get('admission_status') == 'rejected':
                    self._wf_preview = None
                    self.walk_forward_consent.setChecked(False)
                    self.walk_forward_start.setEnabled(False)
                    self.walk_forward_status.setText('預覽未通過：請核對上方原因；未保留或消耗新範圍，目前不可開始。')
                    self.status.setText('來源研究未通過候選池准入；請核對明示原因，未保留或消耗新範圍。')
                    return True
                self._wf_preview = result
                self.walk_forward_status.setText('預覽已就緒：請核對範圍、風險門檻與不可逆消耗，明確確認後才可開始；尚未保留或消耗新範圍。')
                self.status.setText('Walk-forward 預覽就緒；核對範圍、門檻與不可逆消耗後才可開始。')
            else:
                from desktop_walk_forward import result_rows, status_label, preview_text
                self.walk_forward_advanced.setPlainText(preview_text(result, advanced=True))
                summary = result.get('summary', {})
                self.walk_forward_results.set_rows(result_rows(result))
                self.walk_forward_status.setText(
                    '狀態：' + status_label(result.get('display_status', result['status'])) + ' · 證據：' + status_label(summary.get('evidence_mode')) +
                    ' · 暴露：' + status_label(summary.get('exposure_status')) +
                    f"\n全實驗預留額度 {summary.get('evaluations_reserved', 0)} / {summary.get('evaluation_limit', '未知')}；已評估前推折數 {summary.get('evaluated_oos_folds', 0)}。" +
                    '\n模型呼叫 0；最終保留集排除／未評估；非獨立 OOS、不可正式排名、無紙上資格。' +
                    ('\n來源模型狀態：' + status_label(result['pool_admission']['real_model_status']) if result.get('pool_admission') else '') +
                    '\n識別碼：' + str(result.get('reference', ''))[:12])
                self.status.setText('Walk-forward 紀錄已讀取；不會重送或重新評估已消耗 OOS。')
                self._refresh_walk_forward_references()
                if operation in ('ui_walk_forward_run', 'ui_walk_forward_reconcile'):
                    self._wf_launch = None
        else:
            if operation == 'ui_walk_forward_preview':
                self.walk_forward_status.setText('預覽未完成：已停止或失敗，請重新預覽；未保留或消耗新範圍，目前不可開始。')
            self.status.setText('Walk-forward 已停止或失敗；已消耗範圍不退還，不會自動重試。' + str(event.get('message', '')))
            if operation == 'ui_walk_forward_run': self._wf_pending_reconcile = self._wf_launch is not None
        return True

    def _backtest_page(self):
        layout = self._page('回測與結果')
        layout.addWidget(QLabel('使用「策略與版本」目前選定家族及參數。預設費率與保證金為合成假設。'))
        self.backtest_form = BacktestForm(); layout.addWidget(self.backtest_form)
        self.start_date = self.backtest_form.fields['start_date']; self.end_date = self.backtest_form.fields['end_date']
        advanced = self._advanced(layout)
        self.config = self._text(advanced, '費用／資金／保證金設定 JSON', canonical_json(demo_config()), True)
        self._remember(self.config)
        self.batch = QCheckBox('批次執行五個家族的預設參數'); layout.addWidget(self.batch)
        self.run_button = self._button(layout, '執行回測', 'run_backtest', self.run_backtest)
        self.result_choice = QComboBox(); self.result_choice.currentIndexChanged.connect(self.show_result); layout.addWidget(self.result_choice)
        self.plot = EquityPlot(); layout.addWidget(self.plot)
        self.result_detail = QPlainTextEdit(); self.result_detail.setReadOnly(True); advanced.addWidget(self.result_detail)
        self.result_card = BacktestSummaryCard(); layout.addWidget(self.result_card)
        self.fills_table = BacktestFillsTable(); layout.addWidget(self.fills_table)
        for kind, caption in (('signal', '市場圖表：顯示已驗證回測訊號'), ('fill', '市場圖表：顯示已驗證回測成交')):
            toggle = QCheckBox(caption); toggle.setChecked(True); layout.addWidget(toggle)
            toggle.toggled.connect(lambda value, layer=kind: self.market.chart.set_layer_visible(layer, value))

    def _compare_page(self):
        layout = self._page('比較與策略選擇')
        layout.addWidget(QLabel('勾選多個已保存結果進行比較。OOS／保留集詳細結果見策略研究紀錄。'))
        self.comparison_list = QListWidget(); self.comparison_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection); layout.addWidget(self.comparison_list)
        self._button(layout, '比較選取結果', 'compare_results', lambda: self.start_job('ui_compare', {'results': [i.data(Qt.ItemDataRole.UserRole) for i in self.comparison_list.selectedItems()]}))
        self.comparison = QPlainTextEdit(); self.comparison.setReadOnly(True); self._advanced(layout).addWidget(self.comparison)
        self.comparison_table = ResultTable(); layout.addWidget(self.comparison_table)
        self.select_button = self._button(layout, '啟用目前回測策略（僅研究／紙上）', 'select_strategy', self.select_strategy)
        self._button(layout, '停用策略並停止紙上新委託', 'disable_strategy', lambda: self.start_job('ui_disable', {}))
        self.selection_status = QLabel(); self.selection_status.setWordWrap(True); layout.addWidget(self.selection_status)
        self._analysis_section(layout)

    def _analysis_section(self, layout):
        title=QLabel('ChatGPT 已保存候選分析／比較（另行明確操作）');layout.addWidget(title)
        warning=QLabel(ANALYSIS_WARNING+'\n'+ANALYSIS_NOTICE);warning.setWordWrap(True);layout.addWidget(warning)
        self.analysis_candidates=QListWidget();self.analysis_candidates.setObjectName('analysis_candidates')
        self.analysis_candidates.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection);layout.addWidget(self.analysis_candidates)
        self.analysis_original=QLineEdit();self.analysis_original.setReadOnly(True);self.analysis_original.setObjectName('analysis_original_dataset')
        self.analysis_original.setPlaceholderText('必須明確選取來源研究當時的完整原始資料檔');layout.addWidget(self.analysis_original)
        self._button(layout,'選取分析的原始資料檔','pick_analysis_original',self.pick_analysis_original)
        self._button(layout,'預覽單一候選分析（不連網）','preview_candidate_analysis',lambda:self.preview_analysis('critique'))
        self._button(layout,'預覽同研究候選比較（不連網）','preview_candidate_comparison',lambda:self.preview_analysis('compare'))
        self.analysis_preview=QPlainTextEdit();self.analysis_preview.setReadOnly(True);self.analysis_preview.setObjectName('analysis_preview');layout.addWidget(self.analysis_preview)
        self.analysis_evidence=QPlainTextEdit();self.analysis_evidence.setReadOnly(True);self.analysis_evidence.setObjectName('analysis_evidence');self._advanced(layout).addWidget(self.analysis_evidence)
        self.analysis_consent=QCheckBox('我已核對預覽與送出證據；同意最多一個訂閱分析請求，取消／失敗不重送，不套用建議。')
        self.analysis_consent.setObjectName('analysis_one_call_consent');layout.addWidget(self.analysis_consent)
        note=QLabel('沿用設定頁的 ChatGPT 帳戶、官方模型、本次連線與 included-only 用量確認；不新增金鑰或供應商。')
        note.setWordWrap(True);layout.addWidget(note)
        self.analysis_start=self._button(layout,'明確送出已預覽分析／比較','run_candidate_analysis',self.run_analysis)
        self.analysis_start.setEnabled(False)
        self.analysis_saved=QComboBox();self.analysis_saved.setObjectName('analysis_saved');layout.addWidget(self.analysis_saved)
        self._analysis_checkpoint_ids=set()
        self.analysis_checkpoint_notice=QLabel();self.analysis_checkpoint_notice.setObjectName('analysis_checkpoint_notice')
        self.analysis_checkpoint_notice.setWordWrap(True);layout.addWidget(self.analysis_checkpoint_notice)
        self._button(layout,'唯讀重開已保存分析（不連網）','read_candidate_analysis',self.read_analysis)
        self.analysis_findings=QPlainTextEdit();self.analysis_findings.setReadOnly(True);self.analysis_findings.setObjectName('analysis_findings');layout.addWidget(self.analysis_findings)
        self.analysis_saved.currentIndexChanged.connect(self._analysis_saved_changed)
        self.analysis_candidates.itemSelectionChanged.connect(self._invalidate_analysis_preview)
        self.analysis_original.textChanged.connect(self._invalidate_analysis_preview)

    def _invalidate_analysis_preview(self, *args):
        self._analysis_preview=None;self._analysis_request_key=None
        if hasattr(self,'analysis_consent'):
            self.analysis_consent.setChecked(False);self.analysis_start.setEnabled(False)
            self.analysis_preview.clear();self.analysis_evidence.clear()

    def pick_analysis_original(self):
        name,_=QFileDialog.getOpenFileName(self,'選取來源研究的完整原始資料檔','','JSON (*.json)')
        if not name:return
        if '://' in name or name.startswith(('//',chr(92)*2)) or not Path(name).is_absolute():raise ValidationError('請選取本機絕對路徑')
        path=Path(name).resolve(strict=True)
        if not path.is_file():raise ValidationError('請選取原始資料檔')
        self.analysis_original.setText(str(path))

    def _analysis_request(self, task):
        from quantlab.desktop_runtime import validate_analysis_request
        refs=[item.data(Qt.ItemDataRole.UserRole) for item in self.analysis_candidates.selectedItems()]
        if not refs or len({ref['campaign_folder'] for ref in refs})!=1:raise ValidationError('請選取同一已保存研究的候選')
        c=self.chatgpt_controller;p=self.chatgpt_panel
        if c.busy or c.state!='plan_ready' or not c.active_registration or p.model.currentData() not in c.models:raise ValidationError('請先核對共享 ChatGPT 連線與官方模型')
        request={'campaign_reference':refs[0]['campaign_folder'],'original_dataset':{'kind':'local_dataset_file','path':self.analysis_original.text()},
            'attempt_ids':sorted(ref['attempt_id'] for ref in refs),'task':task,'registration':c.active_registration,
            'model':p.model.currentData(),'timeout_seconds':p.timeout.value()}
        validate_analysis_request(request);return request

    def preview_analysis(self, task):
        request=self._analysis_request(task)
        self._invalidate_analysis_preview();self._analysis_request_key=content_hash(request)
        self.start_job('ui_analysis_preview',{'request':request})

    def run_analysis(self):
        from desktop_chatgpt_ui import SubscriptionOptions
        preview=self._analysis_preview
        if preview is None or not self.analysis_consent.isChecked():raise ValidationError('請先核對分析預覽並同意唯一請求')
        plan=preview['plan'];request=self._analysis_request(plan['binding']['packet']['context']['task'])
        if content_hash(request)!=self._analysis_request_key:raise ValidationError('分析選擇已變更，請重新預覽')
        c=self.chatgpt_controller;p=self.chatgpt_panel
        if (not c.account_status_known or c.account_paused or c.account_pending
            or preview['receipt_snapshot']['receipts']):raise ValidationError('分析額度已使用或帳戶未知；只允許唯讀保存結果，不重送')
        if (not p.consent.isChecked() or not p.included_usage_only.isChecked()
            or p._included_usage_registration!=request['registration'] or p.account.currentData()!=request['registration']):
            raise ValidationError('請在共享連線區核對本次授權及 included-only 用量確認')
        SubscriptionOptions(request['registration'],request['model'],1,request['timeout_seconds'],network_opt_in=True,included_usage_policy_confirmed=True)
        payload={'request':request,'expected_analysis_id':plan['analysis_id'],'expected_plan_hash':content_hash(plan),'user_confirmed':True,
            'network_opt_in':True,'included_usage_policy_confirmed':True}
        self.analysis_consent.setChecked(False);p.consent.setChecked(False);p._reset_included_usage()
        job_id=self.start_job('ui_analysis_run',payload)
        self._analysis_launch={'analysis_id':plan['analysis_id'],'registration':request['registration'],'stopped_job_id':job_id}
        self._analysis_running=True;self._analysis_preview=None
        c.invalidate_campaign_usage();self._plan_usage_binding=None

    def read_analysis(self):
        reference=self.analysis_saved.currentData()
        if not reference:raise ValidationError('請先選取已保存分析')
        self._invalidate_analysis_preview()
        if reference in self._analysis_checkpoint_ids:
            self._analysis_saved_changed()
            return
        self.start_job('ui_analysis_read',{'analysis_id':reference})

    def _analysis_saved_changed(self, *args):
        self.analysis_checkpoint_notice.clear()
        if self.analysis_saved.currentData() in self._analysis_checkpoint_ids:
            self._invalidate_analysis_preview()
            self.analysis_findings.clear()
            self.analysis_checkpoint_notice.setText(ANALYSIS_CHECKPOINT_NOTICE)
            self.status.setText(ANALYSIS_CHECKPOINT_STATUS)
        elif self.status.text()==ANALYSIS_CHECKPOINT_STATUS:
            self.status.setText('請以唯讀重開載入所選分析；尚未核對結果。')

    def _analysis_event(self, event):
        if self.last_operation not in ('ui_analysis_preview','ui_analysis_run','ui_analysis_read','ui_analysis_reconcile'):return False
        kind=event.get('type')
        if kind=='progress':self.status.setText(str(event.get('message','分析作業進行中，可取消')));return True
        if kind not in ('result','error','failed','cancelled','canceled'):return True
        operation=self.last_operation
        self.record_event(operation,kind)
        if operation=='ui_analysis_run':
            self._analysis_running=False;self._pending_analysis_reconcile=self._analysis_launch is not None
            self.chatgpt_controller.account_status_known=False;self.chatgpt_controller.invalidate_campaign_usage()
            self._pending_usage_refresh=True
        if kind=='result':
            result=event['result']
            if operation=='ui_analysis_preview':
                plan=result['plan'];task=plan['binding']['packet']['context']['task']
                if content_hash(self._analysis_request(task))!=self._analysis_request_key:
                    self._invalidate_analysis_preview();self.status.setText('預覽期間選擇已變更，請重新核對。');return True
                if result['analysis_id']!=plan['analysis_id']:raise ValidationError('分析預覽識別不符')
                self._analysis_preview=result
                self.chatgpt_controller.set_account_status(plan['binding']['registration'],result['account_status'])
                self.analysis_preview.setPlainText(analysis_preview_text(plan))
                self.analysis_evidence.setPlainText(canonical_json(plan['binding']['packet']['context']))
                self.analysis_start.setEnabled(not result['receipt_snapshot']['receipts'])
                self.status.setText('分析證據已預覽；僅本機核對，尚未送出模型請求。')
            else:
                self._refresh_analysis_saved(preferred_reference=result['analysis_id'])
                if result['analysis_id'] in self._analysis_checkpoint_ids:return True
                if self.analysis_saved.currentData()!=result['analysis_id']:
                    self.analysis_findings.clear();self.analysis_evidence.clear()
                    self.status.setText('分析結果已回傳，但保存檔案目前無法安全列出；請保留原始紀錄，未載入結果。')
                    return True
                self.analysis_findings.setPlainText(analysis_record_text(result['record']))
                self.analysis_evidence.setPlainText(canonical_json(result['record']['plan']['binding']['packet']['context']))
                self.status.setText('已保存／唯讀載入 AI 解讀；不套用建議或改變策略。')
        else:
            self.analysis_consent.setChecked(False)
            self.status.setText('分析未完成，已保留未知／失敗紀錄，不會重送：'+str(event.get('message','已取消')))
        return True

    def _refresh_analysis_saved(self, *, preferred_reference=None):
        old=preferred_reference or self.analysis_saved.currentData();failed=False
        try:entries=saved_analysis_entries(self.root/'analyses')
        except (OSError, ValidationError):entries=();failed=True
        self._analysis_checkpoint_ids={name for name,checkpoint in entries if checkpoint}
        blocked=self.analysis_saved.blockSignals(True)
        try:
            self.analysis_saved.clear()
            for name,checkpoint in entries:
                label=ANALYSIS_CHECKPOINT_STATUS+' · '+name if checkpoint else name
                self.analysis_saved.addItem(label,name)
            index=self.analysis_saved.findData(old)
            if index>=0:self.analysis_saved.setCurrentIndex(index)
        finally:self.analysis_saved.blockSignals(blocked)
        self._analysis_saved_changed()
        if failed:
            self._invalidate_analysis_preview();self.analysis_findings.clear()
            self.analysis_checkpoint_notice.setText('無法安全列出已保存分析；資料夾無法讀取或路徑不安全。原始檔案未更動，未載入結果或進行復原。')

    def _paper_page(self):
        layout = self._page('紙上交易與復原')
        note = QLabel('沒有即時行情或真實券商。重新啟動後必須明確對帳。停止只禁止新委託，不會平倉。\n歷史重播採次棒成交；不支援盤中停損停利。預設示範費率與風控不代表真實條件。'); note.setWordWrap(True); layout.addWidget(note)
        limits = paper_risk_limits()
        self.paper_risk_summary = QLabel(
            f'固定風控（唯讀）：部位最多 {limits.max_position} 口、單筆最多 {limits.max_order_quantity} 口、'
            f'每日損失上限 {limits.max_daily_loss} TWD、報價最多 {limits.max_quote_age_seconds} 秒；'
            f'連續虧損上限 {limits.max_consecutive_losses} 次、{limits.window_seconds} 秒內最多 {limits.max_orders_per_window} 筆。'
            '停止新委託不會平倉。')
        self.paper_risk_summary.setObjectName('paper_fixed_risk_summary')
        self.paper_risk_summary.setWordWrap(True); layout.addWidget(self.paper_risk_summary)
        advanced = self._advanced(layout)
        self.policy_form = PaperPolicyForm(); layout.addWidget(self.policy_form)
        self.paper_policy = self._text(advanced, '鎖定政策 JSON（合約、交易時段、保證金版本；不可猜測）', '{}', True)
        self._remember(self.paper_policy)
        self._button(layout, '載入已核對的政策檔案', 'load_policy_file', lambda: self.load_form_file(self.policy_form, self.paper_policy))
        self._button(layout, '填入明示合成示範政策', 'demo_policy', self.demo_paper_policy)
        self._button(layout, '讀取／建立紙上帳戶', 'paper_snapshot', lambda: self.paper_job('snapshot'))
        self.snapshot_form = PaperSnapshotForm(); layout.addWidget(self.snapshot_form)
        self.snapshot = self._text(advanced, '外部紙上參考快照 JSON（初始空帳戶可使用下列示範）', canonical_json({'account_id':'paper-demo','cash':'1000000','positions':{},'orders':{},'fills':{}}), True)
        self.snapshot_form.from_payload(json.loads(self.snapshot.toPlainText())); self._remember(self.snapshot)
        self._button(layout, '載入外部完整參考快照', 'load_snapshot_file', lambda: self.load_form_file(self.snapshot_form, self.snapshot))
        self._button(layout, '明確對帳紙上帳戶', 'paper_reconcile', lambda: self.paper_job('reconcile', snapshot=self._payload(self.snapshot, self.snapshot_form.build_payload)))
        self.kill_button = self._button(layout, '緊急停止：禁止紙上新委託', 'paper_kill', self.kill_paper)
        self.replay_bars = QSpinBox(); self.replay_bars.setRange(1, 1000); self.replay_bars.setValue(100); layout.addWidget(self.replay_bars)
        self.paper_confirm = QCheckBox('我已核對上方參考快照，並同意本次重播／委託前對帳'); layout.addWidget(self.paper_confirm)
        self._button(layout, '重播選定策略一批歷史資料', 'paper_replay', lambda: self.paper_job('replay', max_bars=self.replay_bars.value()))
        self.intent_form = PaperIntentForm(); layout.addWidget(self.intent_form)
        self.quote_form = PaperQuoteForm(); layout.addWidget(self.quote_form)
        self.intent = self._text(advanced, '紙上委託意圖 JSON（需已啟用策略雜湊）', '{}', True)
        self.quote = self._text(advanced, '明示報價與風控條件 JSON', '{}', True)
        self._remember(self.intent); self._remember(self.quote)
        self.paper_time = self._text(layout, '紙上事件 UTC 時間', '2026-01-05T01:00:00Z')
        self._button(layout, '送出紙上委託', 'paper_submit', lambda: self.paper_job('submit', intent=self._payload(self.intent, self.intent_form.build_payload), quote=self._payload(self.quote, self.quote_form.build_payload), now=self.paper_time.text()))
        self.cancel_order = self._text(layout, '紙上委託 ID')
        self._button(layout, '取消紙上委託', 'paper_cancel', lambda: self.paper_job('cancel', order_id=self.cancel_order.text(), now=self.paper_time.text()))
        self.paper_detail = QPlainTextEdit(); self.paper_detail.setReadOnly(True); advanced.addWidget(self.paper_detail)
        self.paper_card = SummaryCard(); layout.addWidget(self.paper_card)

    def _settings_page(self):
        layout = self._page('設定與備份')
        layout.addWidget(QLabel('本機工作區：' + str(self.paths.root)))
        layout.addWidget(QLabel('資料與帳戶狀態：' + str(self.root)))
        layout.addWidget(QLabel('預算與保留集消耗紀錄不隨備份還原，也不因切換工作區重設。'))
        layout.addWidget(QLabel('日誌：' + str(self.paths.logs)))
        self.workspace_path = self._text(layout, '下次啟動的工作區（不搬移、不覆寫現有資料）', str(self.paths.root))
        self._button(layout, '設定下次啟動工作區', 'configure_workspace', self.configure_workspace)
        from desktop_chatgpt_ui import ChatGPTConnectionPanel, ConnectionController
        self.chatgpt_controller = ConnectionController(self)
        self.chatgpt_panel = ChatGPTConnectionPanel(self.chatgpt_controller); layout.addWidget(self.chatgpt_panel)
        self.chatgpt_controller.set_host_available(True)
        self.chatgpt_controller.quiesce_requested.connect(self._chatgpt_quiesce)
        self.chatgpt_controller.request_ready.connect(self._chatgpt_dispatch)
        self.chatgpt_controller.cancel_requested.connect(self._chatgpt_cancel)
        self.chatgpt_controller.browser_requested.connect(self._chatgpt_open_browser)
        self.persist_logs = QCheckBox('保存精簡本機作業日誌（不含金鑰、路徑、請求或回應）'); self.persist_logs.setChecked(True); layout.addWidget(self.persist_logs)
        self.local_notifications = QCheckBox('作業完成／失敗時顯示本機提示並提醒此視窗'); self.local_notifications.setChecked(True); layout.addWidget(self.local_notifications)
        self._button(layout, '儲存非敏感偏好', 'save_settings', self.save_settings)
        self.backup_path = self._text(layout, '備份封存檔案路徑（請選工作區與應用資料夾以外的位置）')
        self._button(layout, '建立本機備份', 'create_backup', lambda: self.backup(False))
        self.restore_confirm = QCheckBox('我確認還原會替換目前本機狀態，並會要求重新對帳'); layout.addWidget(self.restore_confirm)
        self._button(layout, '驗證並還原備份', 'restore_backup', lambda: self.backup(True))
        from desktop_automatic_backup import AutomaticBackupPanel
        self.automatic_backup_panel = AutomaticBackupPanel(self); layout.addWidget(self.automatic_backup_panel)
        from quantlab import __version__
        self.version_label = QLabel(f'目前版本 {__version__} · 未簽章預覽版；尚無已驗證的最新版本資訊。')
        self.version_label.setWordWrap(True); layout.addWidget(self.version_label)
        layout.addWidget(QLabel('更新不會自動下載或執行；請核對官方專案、SHA-256 與發行說明。'))
        self._button(layout, '開啟專案 Releases 頁面', 'open_releases', self.open_releases)
        self._button(layout, '讀取精簡本機日誌', 'read_logs', self.read_logs)
        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setPlaceholderText('本次工作階段的作業狀態。僅記錄作業名稱與結果類型，不記錄金鑰或供應商回應內容。'); layout.addWidget(self.log_view)
        layout.addStretch()

    def _safe(self, callback):
        try:
            return callback()
        except Exception as exc:
            self.status.setText('作業未完成（輸入驗證失敗）：' + str(exc))
            return None

    def _browse(self, target):
        name, _ = QFileDialog.getOpenFileName(self, '選取本機檔案')
        if name: target.setText(name)

    def load_form_file(self, form, editor):
        name, _ = QFileDialog.getOpenFileName(self, '載入已核對的完整資料檔', '', 'JSON (*.json)')
        if not name: return
        path = Path(name)
        if path.stat().st_size > 4 * 1024 * 1024: raise ValidationError('資料檔案過大')
        value = read_json(path)
        form.from_payload(value)
        editor.setPlainText(canonical_json(value)); self._remember(editor)
        self.paper_confirm.setChecked(False)
        self.status.setText('已載入參考資料；未對帳、未送出任何委託，請先核對。')

    def _family_changed(self):
        self.active_candidate = None
        if hasattr(self, 'candidate_choice'): (self.root / 'active_candidate.json').unlink(missing_ok=True)
        self.parameters.setReadOnly(False)
        from quantlab.strategies import builtin_strategies
        spec = builtin_strategies()[self.family.currentIndex()]
        self.parameters.setPlainText(canonical_json(spec.parameters)); self._remember(self.parameters)
        self.strategy_form.family.blockSignals(True)
        try: self.strategy_form.from_payload(to_dict(spec))
        finally: self.strategy_form.family.blockSignals(False)
        self.strategy_form.setEnabled(True)
        self.strategy_detail.setPlainText(canonical_json({'strategy': spec, 'sha256': content_hash(spec), 'scope': 'research_and_paper_only'}))

    def import_data(self):
        if not self.import_path.text().strip() or not self.calendar_path.text().strip():
            raise ValidationError('請選擇資料檔與交易日曆')
        self.start_job('ui_import', {'path': self.import_path.text(), 'calendar': self.calendar_path.text(), 'kind': self.import_kind.currentText(), 'contract': self.contract.text()})

    def download_data(self):
        if not self.network_data.isChecked(): raise ValidationError('請先勾選本次網路下載同意')
        self.start_job('ui_refresh', {'days':self.days.value(), 'network_opt_in':True})
        self.network_data.setChecked(False)

    def run_backtest(self):
        typed = self.backtest_form.build_payload()
        config = self._payload(self.config, lambda: typed['config'])
        spec = self.strategy_form.build_payload() if self.active_candidate is None else None
        parameters = self._payload(self.parameters, lambda: spec['parameters']) if spec else json.loads(self.parameters.toPlainText())
        self.start_job('ui_backtest', {'family': self.family.currentText(), 'parameters': parameters,
            'config': config, 'start_date': typed['start_date'], 'end_date': typed['end_date'],
            'batch': self.batch.isChecked(), 'candidate': self.active_candidate})

    def run_campaign(self):
        config = self._payload(self.campaign_config, lambda: self.campaign_form.build_payload(self.backtest_form.build_payload()['config']))
        options = {'mode':self.provider_mode.currentData()}
        if options['mode'] not in ('chatgpt_plan', 'fixture', 'manual'):
            raise ValidationError('不支援的模型研究來源；不提供本機模型或付費 API 備援')
        if options['mode'] == 'chatgpt_plan':
            from dataclasses import asdict
            options = asdict(self.chatgpt_panel.build_plan_options())
            options['expected_binding'] = self._plan_usage_binding
            from quantlab.__main__ import config_from_json
            checked = dict(config); checked['backtest_config'] = config_from_json(checked['backtest_config'])
            plan_provider(self.paths, _dataset(self.root, {}), checked, options)
        if options['mode'] == 'manual':
            options.update(response_path=self.manual_path.text().strip(), response_text=self.manual_response.toPlainText())
        subscription_campaign = options['mode'] == 'chatgpt_plan'
        launched_job = self.start_job('ui_campaign', {'config':config, 'provider':options})
        self._subscription_campaign = subscription_campaign
        if self._subscription_campaign:
            local_options = {**options,'network_opt_in':False,'included_usage_policy_confirmed':False}
            self._plan_launch = json.loads(canonical_json({'config':config,'provider':local_options,'binding':options['expected_binding'],'stopped_job_id':launched_job}))
            self.chatgpt_controller.invalidate_campaign_usage()

    def export_manual_request(self):
        config = self._payload(self.campaign_config, lambda: self.campaign_form.build_payload(self.backtest_form.build_payload()['config']))
        if config.get('max_improvements') != 0:
            raise ValidationError('手動 AI 交換請先將「每家族最多改良」設定為 0；不會暗中改變研究預算')
        name, _ = QFileDialog.getSaveFileName(self, '匯出手動 AI 請求（自行決定是否分享）', 'manual-ai-request.json', 'JSON (*.json)')
        if name:
            if Path(name).exists(): raise ValidationError('請使用新的檔名；手動 AI 請求不覆寫既有檔案')
            self.start_job('ui_campaign', {'config': config, 'provider': {'mode':'manual'}, 'manual_export': name})

    def select_strategy(self):
        path = self.result_choice.currentData()
        if not path: raise ValidationError('請先執行回測並選擇結果')
        self.start_job('ui_select', {'result':path})

    def demo_paper_policy(self):
        data = load_dataset(self.root / 'dataset.json')
        if data.manifest['source_type'] != 'synthetic': raise ValidationError('只有合成資料可以套用示範政策')
        sessions = []
        for day in sorted({b.trade_date for b in data.bars}):
            bars = [b for b in data.bars if b.trade_date == day]
            sessions.append({'open':bars[0].timestamp.isoformat(), 'end':bars[-1].end.isoformat(), 'trade_date':day, 'session':bars[0].session, 'contract_id':bars[0].contract_id, 'source':'explicit synthetic demonstration'})
        policy = {'contract_id':data.bars[0].contract_id,'risk_sessions':sessions,'margin_schedule':[{'effective_from':'2026-01-01','margin_per_contract':'100000','version':'synthetic-assumption-v1'}]}
        self.paper_policy.setPlainText(canonical_json(policy)); self.policy_form.from_payload(policy); self._remember(self.paper_policy)

    def paper_job(self, op, **payload):
        if op in ('submit', 'replay'):
            if not self.paper_confirm.isChecked(): raise ValidationError('請核對參考快照並明確勾選本次對帳同意')
            payload.update(snapshot=self._payload(self.snapshot, self.snapshot_form.build_payload), reconcile_confirmed=True)
        payload['policy'] = self._payload(self.paper_policy, self.policy_form.build_payload)
        self.start_job('ui_paper_' + op, payload)
        self.paper_confirm.setChecked(False)

    def kill_paper(self):
        self.freeze_paper('使用者要求緊急停止')
        self.status.setText('背景作業已停止；紙上新委託已凍結，重新執行前需明確對帳。')

    def show_chatgpt_sign_in(self):
        """One research entry to the existing official connection panel."""
        self.provider_mode.setCurrentIndex(self.provider_mode.findData('chatgpt_plan'))
        for index in range(self.stack.count()):
            page = self.stack.widget(index)
            if page.isAncestorOf(self.chatgpt_panel):
                self.navigation.setCurrentRow(index)
                self.chatgpt_panel.primary_sign_in.setFocus()
                # The panel is taller than one viewport: show its title and
                # consent disclosure, rather than centering a clipped widget.
                page.verticalScrollBar().setValue(self.chatgpt_panel.mapTo(page.widget(), self.chatgpt_panel.rect().topLeft()).y())
                page.horizontalScrollBar().setValue(0)
                self.status.setText('正在核對本機 ChatGPT 連線；官方登入會在系統瀏覽器開啟，授權由您決定。')
                self.chatgpt_panel.primary_sign_in.click()
                return
        raise ValidationError('找不到官方 ChatGPT 連線區')

    def _chatgpt_quiesce(self, request):
        try:
            self._quiesce_and_recover(preserve_primary_sign_in=True)
            self.poll_jobs()
            if self.jobs.active and self.last_operation == 'ui_analysis_reconcile':
                # The original analysis tree is joined, but its local evidence
                # reconciliation owns the slot. This auth request was never
                # dispatched: fail it explicitly rather than strand or queue it.
                self.chatgpt_panel.abandon_primary_sign_in()
                self.chatgpt_controller.worker_joined(request.request_id, joined=True, terminal_received=False)
                self.status.setText('分析停止紀錄正在本機核對；本次連線動作未執行，完成後請重新操作。')
                return
            self.chatgpt_controller.acknowledge_quiescence(request.request_id, joined=not self.jobs.active)
        except Exception:
            self.chatgpt_controller.acknowledge_quiescence(request.request_id, joined=False)

    def _chatgpt_dispatch(self, request):
        try:
            if self.jobs.active:
                self._quiesce_and_recover(preserve_primary_sign_in=True)
            self.poll_jobs()
            if self.jobs.active and self.last_operation == 'ui_analysis_reconcile':
                # Primary sign-in starts with local list (no quiesce signal).
                # It must not remain busy after reconciliation takes the slot.
                self.chatgpt_panel.abandon_primary_sign_in()
                self.chatgpt_controller.worker_joined(request.request_id, joined=True, terminal_received=False)
                self._chatgpt_job_request=None;self._chatgpt_job_id=None
                self.status.setText('分析停止紀錄正在本機核對；本次登入未執行，完成後請重新按登入。')
                return
            self._chatgpt_job_request = request
            self._chatgpt_job_id = self.start_job('ui_chatgpt_auth', {'request':request.payload()})
        except Exception:
            self.chatgpt_controller.worker_joined(request.request_id, joined=not self.jobs.active, terminal_received=False)
            self._chatgpt_job_request = None
            self.status.setText('連線背景作業無法啟動；請核對本機狀態。')

    def _chatgpt_cancel(self, request_id):
        self.chatgpt_panel.abandon_primary_sign_in()
        self._pending_usage_refresh = False
        if self.jobs.active: self.jobs.cancel()
        if self.jobs.active: return
        # Drain old packets before another operation may own the single manager.
        self.poll_jobs()
        self.chatgpt_controller.worker_joined(request_id, joined=True, terminal_received=False)
        self._chatgpt_job_request = None
        self._chatgpt_job_id = None
        self.chatgpt_panel.consent.setChecked(False)

    def _chatgpt_open_browser(self, url):
        if getattr(self, '_closing', False) or not self.chatgpt_controller.host_available:
            return
        from desktop_chatgpt_ui import official_authorization_url
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if not QDesktopServices.openUrl(QUrl(official_authorization_url(url))):
            self.status.setText('無法開啟官方授權頁面；請取消後再核對環境。')

    def _plan_usage_request(self):
        c = self.chatgpt_controller; panel = self.chatgpt_panel
        if c.state != 'plan_ready' or not c.active_registration or panel.model.currentData() not in c.models:
            raise ValidationError('請先明確核對連線與官方模型清單')
        options = {'mode':'chatgpt_plan','registration':c.active_registration,
            'model':panel.model.currentData(),'max_calls':panel.max_calls.value(),
            'timeout_seconds':panel.timeout.value(),'network_opt_in':False,
            'included_usage_policy_confirmed':False,'paid_api_fallback':False}
        config = self._payload(self.campaign_config, lambda: self.campaign_form.build_payload(self.backtest_form.build_payload()['config']))
        return {'registration':c.active_registration,'provider':options,'config':config}

    def _current_plan_binding(self):
        from quantlab.__main__ import config_from_json
        payload = self._plan_usage_request()
        config = dict(payload['config']); config['backtest_config'] = config_from_json(config['backtest_config'])
        return plan_provider(self.paths, _dataset(self.root, {}), config, payload['provider'], for_usage=True)[1]

    def inspect_plan_usage(self):
        self._invalidate_analysis_preview()
        if self.chatgpt_controller.busy: raise ValidationError('請先等待連線背景作業結束')
        payload = self._plan_usage_request()
        self.chatgpt_controller.invalidate_campaign_usage()
        self._plan_usage_binding = None
        self.start_job('ui_chatgpt_usage', payload)

    def _chatgpt_event(self, event):
        operation = self.last_operation
        if operation not in ('ui_chatgpt_auth','ui_chatgpt_usage','ui_chatgpt_reconcile'): return False
        kind = event.get('type')
        if operation == 'ui_chatgpt_reconcile':
            if kind in ('result','completed','success','error','failed','cancelled','canceled'):
                self.chatgpt_controller.account_status_known = False
                self.chatgpt_controller.invalidate_campaign_usage()
                self._pending_usage_refresh = True
                self.status.setText('中斷研究紀錄已核對；仍需明確檢查狀態。' if kind == 'result' else '中斷研究核對失敗；維持未知封鎖，請勿重送。')
            return True
        if operation == 'ui_chatgpt_auth':
            request = self._chatgpt_job_request
            if request is None: return True
            if self._chatgpt_job_id is not None and event.get('job_id') not in (None,self._chatgpt_job_id): return True
            if kind == 'auth_progress':
                self.chatgpt_controller.apply_event(connection_event_from_payload(event['auth_event']))
            elif kind in ('result','completed','success','error','failed','cancelled','canceled'):
                received = False
                if kind in ('result','completed','success'):
                    received = self.chatgpt_controller.apply_event(connection_event_from_payload(event['result']['auth_event']))
                joined = not self.jobs.active
                self.chatgpt_controller.worker_joined(request.request_id, joined=joined, terminal_received=received)
                if joined:
                    self._chatgpt_job_request = None; self._chatgpt_job_id = None
                    self._pending_usage_refresh = bool(received and self.chatgpt_controller.active_registration)
            return True
        if kind in ('result','completed','success'):
            result = event['result']; c = self.chatgpt_controller
            if result.get('registration') != c.active_registration: return True
            c.set_account_status(result['registration'],result['account_status'])
            if 'receipts' in result:
                if result.get('binding') != self._current_plan_binding():
                    c.invalidate_campaign_usage(); self._plan_usage_binding = None
                    self.status.setText('研究設定已變更，請重新核對請求紀錄。')
                else:
                    c.set_usage(result['registration'],result['receipts'],account_status=result['account_status'])
                    self._plan_usage_binding = result['binding']
                    self.status.setText('本次研究持久請求紀錄已核對；執行前仍需本次明確同意。')
        elif kind in ('error','failed','cancelled','canceled'):
            self.chatgpt_controller.account_status_known = False
            self.chatgpt_controller.invalidate_campaign_usage()
            self.status.setText('請求紀錄核對未完成；狀態未知，禁止自動重送。')
        return True

    def start_job(self, operation, payload):
        if operation not in ('ui_chatgpt_auth', 'ui_chatgpt_usage', 'ui_chatgpt_reconcile'):
            self.chatgpt_panel.abandon_primary_sign_in()
        if self.jobs.active: raise ValidationError('已有背景作業，請等待或取消')
        job_id = self.jobs.start(operation, payload)
        self.last_operation = operation
        self._ui_job_id = job_id
        self.status.setText('背景作業進行中；可切換頁面或取消。')
        self._busy(True)
        return job_id

    def _busy(self, active):
        for button in self.actions: button.setEnabled(not active)
        self.market.set_loading(active)
        self.kill_button.setEnabled(True)
        self.cancel_button.setEnabled(active)
        self.cancel_button.setVisible(active); self.progress.setVisible(active)
        self.progress.setRange(0, 0 if active else 100)
        if not active:
            self.progress.setValue(0)
            self.run_button.setEnabled(bool(getattr(self, '_dataset_ready', False)))
            self.use_candidate_button.setEnabled(bool(getattr(self, '_candidate_valid', False)))
            self.select_button.setEnabled(bool(getattr(self, '_selection_allowed', False)))
            self.walk_forward_start.setEnabled(self._wf_preview is not None)
            self.analysis_start.setEnabled(self._analysis_preview is not None and not self._analysis_preview['receipt_snapshot']['receipts'])

    def cancel_job(self):
        def cancel_and_recover():
            self.freeze_paper('使用者取消背景作業')
            self.status.setText('作業已停止；未完成還原已先復原，再凍結紙上執行。')
        self._safe(cancel_and_recover)

    def poll_jobs(self):
        try:
            for event in self.jobs.poll():
                if event.get('job_id') is not None and self._ui_job_id is not None and event['job_id'] != self._ui_job_id:
                    continue  # A joined old worker can never overwrite a newer view.
                self.automatic_backup_panel.handle_job_event(event)
                if self._walk_forward_event(event): continue
                if self._analysis_event(event): continue
                kind = event.get('type', '')
                if self._chatgpt_event(event): continue
                if self._subscription_campaign and kind in ('result','error','failed','cancelled'):
                    self.chatgpt_controller.invalidate_campaign_usage()
                    self.chatgpt_controller.account_status_known = False
                    self._pending_plan_reconcile = self._plan_launch is not None
                    self._pending_usage_refresh = True
                    self._subscription_campaign = False
                self.record_event(self.last_operation, kind)
                if kind in ('result', 'completed', 'success'):
                    result = event.get('result', {})
                    text = canonical_json(result)
                    self.summary.setPlainText(text)
                    if self.last_operation == 'ui_compare':
                        self.comparison.setPlainText(text); self.comparison_table.set_rows(result.get('rows', []))
                    if result.get('manual_export'):
                        self.status.setText('手動 AI 請求已匯出；由您決定是否傳送，程式未連線。')
                    if self.last_operation == 'ui_market_refresh': self._market_outcomes = result.get('providers', {})
                    if self.last_operation and self.last_operation.startswith('ui_paper_'):
                        self.paper_detail.setPlainText(text)
                        if 'account' in result: self._show_account(result['account'])
                    if self.last_operation == 'ui_backup_restore': self.freeze_paper('備份已還原，請重新核對帳戶')
                    self.status.setText('手動 AI 請求已匯出；程式未連線，請自行決定是否分享。' if result.get('manual_export') else '作業完成，結果已保存於本機。')
                    self.refresh_views()
                    if self.last_operation == 'ui_market_refresh' and any(v.get('error') for v in self._market_outcomes.values()):
                        self.status.setText('部分或全部官方來源更新失敗；仍保留最後有效快取，請查看來源提醒。')
                    self.notify_local('背景作業已結束。請核對來源、狀態與限制。')
                elif kind in ('error', 'failed'):
                    if self.last_operation == 'ui_backup_restore':
                        self.freeze_paper('還原未完成，請重新核對帳戶')
                    self.status.setText('作業失敗：' + str(event.get('message', event.get('error', '未知錯誤'))))
                    self.notify_local('背景作業失敗；請查看狀態並核對輸入。')
                elif kind in ('cancelled', 'canceled'):
                    self.freeze_paper('背景作業已取消')
                    self.status.setText('作業已取消；已完成的檔案保留，未完成部分不代表成功。')
                else:
                    self.status.setText(str(event.get('message', '背景作業進行中')))
            if not self.jobs.active:
                self._busy(False)
                if self._wf_pending_reconcile and self._wf_launch is not None:
                    self._wf_pending_reconcile = False
                    self.start_job('ui_walk_forward_reconcile', self._wf_launch)
                    return
                if self._pending_analysis_reconcile and self._analysis_launch is not None:
                    self._pending_analysis_reconcile=False
                    self.start_job('ui_analysis_reconcile',dict(self._analysis_launch))
                    return
                if getattr(self,'_close_after_reconcile',False):
                    self._close_after_reconcile = False
                    self.close()
                    return
                if self._pending_plan_reconcile and not self.chatgpt_controller.busy and not getattr(self,'_closing',False):
                    self._pending_plan_reconcile = False
                    self.start_job('ui_chatgpt_reconcile', self._plan_launch)
                if not self.jobs.active and self._pending_usage_refresh and not self.chatgpt_controller.busy and not getattr(self, '_closing', False):
                    self._pending_usage_refresh = False
                    reference = self.chatgpt_controller.active_registration
                    if reference: self.start_job('ui_chatgpt_usage', {'registration':reference})
                if not self.jobs.active and getattr(self, '_kill_pending', False):
                    self._kill_pending = False
                    self.paper_job('kill')
        except Exception as exc:
            self.status.setText('狀態讀取失敗：' + str(exc))

    def load_market_cache(self):
        from quantlab.market_providers import load_cached
        series, errors, quotes = {}, [], []
        self._market_data_bindings = {}
        self._market_research_series = {}
        for provider in ('twse', 'taifex'):
            try:
                loaded = load_cached(provider, self.root / 'market_cache')
                series.update({x.instrument.contract_id: x for x in loaded.series}); quotes.extend(loaded.series)
                outcome = self._market_outcomes.get(provider)
                if outcome and outcome.get('error'): errors.append(provider.upper() + '：更新失敗，保留最後有效快取')
            except ValueError:
                if (self.root / 'market_cache' / (provider + '.json')).exists(): errors.append(provider.upper() + '：快取驗證失敗，未採用該資料')
                if self._market_outcomes.get(provider, {}).get('error'):
                    errors.append(provider.upper() + '：更新失敗，尚無有效快取')
        dataset_path, calendar_path = self.root / 'dataset.json', self.root / 'dataset_calendar.json'
        if dataset_path.exists() and calendar_path.exists():
            try:
                dataset = load_dataset(dataset_path)
                for item in dataset_market_series(dataset, read_json(calendar_path)):
                    series[item.instrument.contract_id] = item
                    quotes.append(item)
                    self._market_data_bindings[item.instrument.contract_id] = dataset.manifest['data_hash']
                    self._market_research_series[item.instrument.contract_id] = item
            except (ValueError, KeyError, TypeError) as exc:
                errors.append('研究資料無法作為已驗證市場歷史：' + str(exc))
        try:
            from quantlab.market_history import list_history
            histories = list_history(self.root / 'market_history')
            # Keep immutable imports separate; newest received snapshot wins per
            # exact contract. Do not blend policies or minute/daily observations.
            incoming = [item for loaded in histories for item in loaded.series]
            for item in sorted(incoming, key=lambda item: (item.provenance.received_at, item.provenance.sha256)):
                series[item.instrument.contract_id] = item
        except (ValueError, OSError) as exc:
            errors.append('本機逐筆歷史快取驗證失敗：' + str(exc))
        self.market.set_quote_series(latest_market_observations(quotes), stale=True)
        self.market.set_market_series(tuple(series.values()), stale=True, error='；'.join(errors))
        selection = self.root / 'selection.json'
        strategy = '未啟用'
        if selection.exists():
            try: strategy = '已啟用研究／紙上版本 ' + load_selection(selection)['strategy_hash'][:16]
            except (ValueError, KeyError): strategy = '版本驗證失敗，不可使用'
        self.market.set_trading_status(strategy=strategy)
        if (self.root / 'paper.sqlite3').exists() and (self.root / 'paper_policy.json').exists():
            try: self._show_account(_paper(self.root).snapshot(), strategy=strategy)
            except Exception:
                self.market.set_trading_status(strategy=strategy, paper='帳戶讀取失敗，狀態未知', risk='請停止並核對紀錄')
                self.market.set_account_tables()

    def _show_account(self, account, strategy=None):
        values = {k: account.get(k) for k in ('account_id','cash','reconciliation_required','kill_switch')}
        if not account.get('account_id'): values['cash'] = None
        self.paper_card.set_values(values)
        positions = [{'contract_id': key, 'quantity': value} for key, value in account.get('positions', {}).items()]
        orders = []
        for key, value in account.get('orders', {}).items():
            row = {**value.get('intent', {}), **value, 'order_id': key}
            if 'quantity' in row and 'contract_id' in row: orders.append(row)
        fills = []
        for key, value in account.get('fills', {}).items():
            intent = account.get('orders', {}).get(value.get('order_id'), {}).get('intent', {})
            fills.append({**intent, **value, 'fill_id': key})
        self.market.set_account_tables(positions=positions, orders=orders, fills=fills)
        if strategy is None:
            selection = self.root / 'selection.json'
            strategy = ('已啟用研究／紙上版本 ' + load_selection(selection)['strategy_hash'][:16]) if selection.exists() else '未啟用'
        self.market.set_trading_status(strategy=strategy,
            paper=('帳戶 ' + str(account['account_id'])) if account.get('account_id') else '尚未完成初始對帳',
            risk='已停止新委託' if account.get('kill_switch') is True else ('需要對帳' if account.get('reconciliation_required') is True else '僅依已鎖定紙上政策；非實單' if account.get('kill_switch') is False and account.get('reconciliation_required') is False else '未知；請核對帳戶'))

    def refresh_views(self):
        self._refresh_walk_forward_references()
        self._refresh_analysis_saved()
        path = self.root / 'dataset.json'
        data = None
        if path.exists():
            try:
                data = load_dataset(path)
                self.overview.setText(f"資料來源：{data.manifest['source_type'].upper()} · {len(data.bars)} 根\n本機資料與紙上交易；實單：DISABLED；真實模型：NOT_VERIFIED")
                self.data_card.setText('資料來源\n\n' + data.manifest['source_type'].upper() + f' · {len(data.bars)} 根')
                self.data_detail.setPlainText(canonical_json({'manifest':data.manifest, 'quality':data.quality}))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.overview.setText('研究資料驗證失敗；原檔保留。' + str(exc))
        else:
            self.overview.setText('尚無資料。請先匯入本機資料或建立明示合成示範。')
        stamp = content_hash(to_dict(data.manifest)) if data is not None else None
        if stamp != self._wf_source_stamp:
            first_source = self._wf_source_stamp is None
            self._wf_source_stamp = stamp
            if data is not None and first_source:
                self.walk_forward_form.defaults_for_bars(len(data.bars))
            self._invalidate_walk_forward_preview()
        self._dataset_ready = data is not None
        self.load_market_cache()
        if data is not None and self._campaign_data_hash != data.manifest['data_hash']:
            from quantlab.research import demo_campaign_config
            self.campaign_form.from_payload(to_dict(demo_campaign_config(data, demo_config())))
            self._campaign_data_hash = data.manifest['data_hash']
        self.run_button.setEnabled(data is not None and not self.jobs.active)
        old = self.result_choice.currentData()
        active = self.root / 'active_result.json'
        if self.last_operation == 'ui_backtest' and active.exists():
            digest = read_json(active).get('result_hash', '')
            if len(digest) == 64 and all(c in '0123456789abcdef' for c in digest): old = str(self.root / 'reports' / digest / 'result.json')
        self.result_choice.blockSignals(True); self.result_choice.clear(); self.comparison_list.clear()
        for result_path in sorted((self.root / 'reports').glob('*/result.json')):
            label = result_path.parent.name
            self.result_choice.addItem(label, str(result_path))
            self.comparison_list.addItem(label); self.comparison_list.item(self.comparison_list.count()-1).setData(Qt.ItemDataRole.UserRole, str(result_path))
        index = self.result_choice.findData(old)
        if index >= 0: self.result_choice.setCurrentIndex(index)
        self.result_choice.blockSignals(False); self.show_result()
        selection = self.root / 'selection.json'
        self.selection_status.setText('已啟用研究／紙上版本：' + load_selection(selection)['strategy_hash'] + '\n實單固定停用；生成候選仍須通過獨立資格檢查。' if selection.exists() else '尚未啟用任何策略')
        policy = self.root / 'paper_policy.json'
        if policy.exists():
            policy_value = read_json(policy); self.paper_policy.setPlainText(canonical_json(policy_value))
            self.policy_form.from_payload(policy_value); self._remember(self.paper_policy)
        history = []
        for p in sorted((self.root / 'campaigns').glob('*/*.json'))[:100]:
            history.append({'file':str(p), 'content':read_json(p)})
        self.history.setPlainText(canonical_json(history) if history else '尚無研究版本或 OOS 結果')
        self.history_table.set_rows([{'family': a.get('family'), 'sequence': a.get('sequence'), 'status': a.get('status'), 'strategy_hash': a.get('strategy_hash')} for entry in history for a in entry['content'].get('attempts', [])])
        self.evaluation_table.set_rows([{'評估區段': split, 'status': row.get('status'), 'strategy_hash': row.get('strategy_hash'), **row.get('metrics', {})} for entry in history for split, rows in entry['content'].get('evaluations', {}).items() for row in rows])
        selected_analysis=[item.data(Qt.ItemDataRole.UserRole) for item in self.analysis_candidates.selectedItems()]
        self.analysis_candidates.blockSignals(True);self.analysis_candidates.clear()
        selected_ref = self.candidate_choice.currentData()
        self.candidate_choice.blockSignals(True); self.candidate_choice.clear()
        for entry in history:
            state = entry['content']
            if not isinstance(state, dict): continue
            for attempt in state.get('attempts', []):
                ref = {'campaign_folder':Path(entry['file']).parent.name, 'attempt_id':attempt.get('attempt_id'), 'strategy_hash':attempt.get('strategy_hash')}
                label = f"{state.get('campaign_id','')[:10]} · {attempt.get('family','?')} · v{attempt.get('sequence','?')} · {attempt.get('status','?')}"
                self.candidate_choice.addItem(label, ref)
                if attempt.get('status')=='evaluated' and Path(entry['file']).name=='campaign.json':
                    family=attempt.get('spec',{}).get('family',attempt.get('family','候選'))
                    family={'trend':'趨勢','mean_reversion':'均值回歸','breakout':'突破','momentum':'動能','volatility':'波動'}.get(family,family)
                    self.analysis_candidates.addItem(f"{state.get('campaign_id','')[:10]} · {family} · {str(attempt.get('strategy_hash',''))[:12]}（已評估）")
                    item=self.analysis_candidates.item(self.analysis_candidates.count()-1);item.setData(Qt.ItemDataRole.UserRole,ref)
                    item.setSelected(ref in selected_analysis)
        index = self.candidate_choice.findData(selected_ref)
        if index >= 0: self.candidate_choice.setCurrentIndex(index)
        self.candidate_choice.blockSignals(False); self.inspect_candidate()
        self.analysis_candidates.blockSignals(False)
        active_candidate = self.root / 'active_candidate.json'
        if self.active_candidate is None and active_candidate.exists():
            reference = read_json(active_candidate)
            index = self.candidate_choice.findData(reference)
            if index >= 0:
                self.candidate_choice.setCurrentIndex(index); self.use_candidate()

    def show_result(self, index=None):
        self.market.chart.set_reference_lines(())
        path = self.result_choice.currentData()
        self._selection_allowed = False
        if not path: self.plot.set_values([]); self.result_detail.setPlainText('尚無回測結果'); return
        try:
            result = load_result(path)
            self.plot.set_values(result.equity)
            self.result_card.set_values(dict(result.metrics))
            self.fills_table.set_rows([to_dict(x) for x in result.fills])
            self.bind_result_layers(result)
            self._selection_allowed = True
            reference = result.manifest.get('dataset_manifest', {}).get('desktop_candidate_reference')
            if reference:
                _, provenance = candidate_record(self.root, reference)
                self._selection_allowed = provenance['paper_qualified']
            self.select_button.setEnabled(self._selection_allowed and not self.jobs.active)
            self.result_detail.setPlainText(canonical_json({'metrics':result.metrics, 'warnings':result.warnings, 'manifest':result.manifest, 'fills':result.fills, 'rejects':result.rejects}))
        except Exception as exc: self.status.setText('結果驗證失敗：' + str(exc))

    def bind_result_layers(self, result=None):
        """Only exact source, strategy and chart identities may carry result layers."""
        from desktop_charts import ChartTrace, ChartMarker
        chart = self.market.chart
        bars = chart.bars
        old_overlays, old_panes, styles = dict(chart.overlays), dict(chart.panes), dict(chart.pane_styles)
        source, status = chart.source_label, chart.status_label
        chart.set_series(bars, source_label=source, status_label=status)
        chart.set_overlays(old_overlays, panes=old_panes, pane_styles=styles)
        path = self.result_choice.currentData() if hasattr(self, 'result_choice') else None
        if not bars or not path or not (self.root / 'dataset.json').exists(): return
        result = result or load_result(path)
        data = load_dataset(self.root / 'dataset.json')
        from quantlab.reporting import validate_result_payload
        try:
            # Use the report loader's authoritative full dataset/provenance binding.
            validate_result_payload(to_dict(result), dataset=data)
        except (ValidationError, KeyError, TypeError, ValueError):
            return
        # Require the exact adapted market source, not merely matching price/date.
        selected = self.market.contract_combo.currentData()
        item = self.market.selected_series()
        if item is None or self._market_data_bindings.get(selected) != data.manifest['data_hash']: return
        if item != self._market_research_series.get(selected): return
        trace = ChartTrace(selected, content_hash(bars), result.manifest['spec_hash'], '回測')
        markers = []
        from bisect import bisect_left, bisect_right
        timed = [(i,b) for i,b in enumerate(bars) if b.timestamp is not None and b.end is not None]
        starts, ends = [b.timestamp for _,b in timed], [b.end for _,b in timed]
        def event_index(timestamp, at_close):
            position = bisect_left(ends, timestamp) if at_close else bisect_right(starts, timestamp)-1
            if not 0 <= position < len(timed): return None
            i, bar = timed[position]
            return i if (bar.timestamp < timestamp <= bar.end if at_close else bar.timestamp <= timestamp < bar.end) else None
        for signal in result.signals:
            if signal.contract_id != selected: continue
            index = event_index(signal.timestamp, True)
            if index is not None:
                markers.append(ChartMarker(index, 'signal', '目標部位 ' + str(signal.target_position),
                    reason=signal.reason, timestamp=signal.timestamp, target_position=signal.target_position))
        for fill in result.fills:
            if fill.contract_id != selected: continue
            # Core timestamps are event availability; never infer intrabar execution time.
            index = event_index(fill.timestamp, fill.reason in ('stop', 'target'))
            if index is not None:
                markers.append(ChartMarker(index, 'fill', '買進' if fill.side == 'buy' else '賣出',
                    price=fill.price, quantity=fill.quantity, cost=fill.commission+fill.tax,
                    reason=fill.reason, timestamp=fill.timestamp))
        chart.set_series(bars, trace=trace, source_label=source, status_label=status + ' · 回測圖層（非市場交易紀錄）')
        chart.set_overlays(old_overlays, panes=old_panes, pane_styles=styles)
        chart.set_markers(markers, trace=trace)
        chart.set_reference_lines(self._result_snapshot_lines(result, bars, selected), trace=trace)

    @staticmethod
    def _result_snapshot_lines(result, bars, selected):
        """Read the final actual open-lot snapshot, never derive a fill from a signal.

        Range endpoints preserve the existing whole-position conservative policy:
        every original-entry lot can trigger; the most adverse triggered level
        wins (with existing gap handling). An average-price stop is not that rule.
        No line is projected back through historical candles or beyond this event.
        """
        from desktop_charts import ReferenceLine
        from decimal import Context, InvalidOperation, ROUND_HALF_EVEN, localcontext
        if not result.equity: return ()
        row = result.equity[-1]
        lots = result.metrics.get('open_lots', ())
        position = result.metrics.get('open_position')
        if not lots or type(position) is not int or not position: return ()
        if row.get('contract_id') != selected or row.get('position') != position: return ()
        def timestamp(value):
            return datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
        try:
            as_of = timestamp(row['timestamp'])
            indices = [i for i,bar in enumerate(bars) if bar.contract_id==selected and bar.end==as_of]
            if len(indices)!=1: return ()  # No nearest-time or date-only guess.
            side = 1 if position>0 else -1
            fills = {fill.fill_id: fill for fill in result.fills}
            if len(fills)!=len(result.fills) or any(fill.timestamp>as_of for fill in result.fills): return ()
            opening = {fid: fill for fid,fill in fills.items() if fill.reason in ('target_open','roll_open')}
            remaining = {fid: fill.quantity for fid,fill in opening.items()}
            exit_quantities = {}
            configuration = result.manifest['config']
            configured = {content_hash(event): event for event in configuration['settlement_events']}
            applied = {}
            available = {(timestamp(event['timestamp']),event['contract_id']) for event in result.equity}
            for settlement in result.metrics['settlements']:
                event = settlement['event']
                event_id = content_hash(event)
                if (event_id not in configured or settlement['event_id']!=event_id or event_id in applied
                        or settlement['kind']!=event.get('kind','daily')
                        or timestamp(event['timestamp'])>as_of
                        or (timestamp(event['timestamp']),event['contract_id']) not in available): return ()
                applied[event_id] = event
            with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
                # Reconcile full opening quantities against every closed FIFO match.
                # Several residual fragments may legitimately refer to one opening fill.
                for match in result.ledger:
                    fill = opening.get(match['entry_fill_id'])
                    quantity = match['quantity']
                    if (fill is None or type(quantity) is not int or quantity<=0
                            or match['contract_id']!=fill.contract_id
                            or match['side']!=('long' if fill.side=='buy' else 'short')
                            or Decimal(str(match['entry_price']))!=fill.price
                            or timestamp(match['entry_timestamp'])!=fill.timestamp
                            or not fill.timestamp<=timestamp(match['exit_timestamp'])<=as_of): return ()
                    exit_id = match['exit_fill_id']
                    if exit_id is not None:
                        exit_fill = fills.get(exit_id)
                        if (exit_fill is None or exit_id in opening or exit_fill.contract_id!=fill.contract_id
                                or exit_fill.side==fill.side or exit_fill.timestamp!=timestamp(match['exit_timestamp'])
                                or exit_fill.price!=Decimal(str(match['exit_price']))): return ()
                        exit_quantities[exit_id] = exit_quantities.get(exit_id,0)+quantity
                    else:
                        event = applied.get(match['exit_event_id'])
                        if (event is None or event.get('kind')!='final' or match['exit_event_type']!='final_settlement'
                                or event['contract_id']!=fill.contract_id
                                or timestamp(event['timestamp'])!=timestamp(match['exit_timestamp'])
                                or Decimal(str(event['price']))!=Decimal(str(match['exit_price']))): return ()
                    remaining[fill.fill_id] -= quantity
                    if remaining[fill.fill_id]<0: return ()
                if any(exit_quantities.get(fid,0)!=fill.quantity for fid,fill in fills.items() if fid not in opening): return ()
                expected = {fid: quantity for fid,quantity in remaining.items() if quantity}
                entries, bases, quantities, observed = [], [], [], {}
                for lot in lots:
                    quantity = lot['quantity']
                    entry, basis = Decimal(str(lot['price'])), Decimal(str(lot['basis_price']))
                    if type(quantity) is not int or quantity<=0 or lot['side']!=side or lot['contract_id']!=selected: return ()
                    if not entry.is_finite() or not basis.is_finite() or min(entry,basis)<=0: return ()
                    fill = opening.get(lot['fill_id'])
                    if (fill is None or fill.contract_id!=selected or fill.price!=entry
                            or fill.side!=('buy' if side>0 else 'sell') or quantity>fill.quantity
                            or timestamp(lot['timestamp'])!=fill.timestamp or fill.timestamp>as_of): return ()
                    observed[fill.fill_id] = observed.get(fill.fill_id,0)+quantity
                    expected_basis = entry
                    # Settlement at the opening timestamp belongs to the prior bar,
                    # before this next-open fill, so the boundary is strictly greater.
                    events = sorted((event for event in configured.values()
                                     if event['contract_id']==selected and fill.timestamp<timestamp(event['timestamp'])<=as_of),
                                    key=lambda event: timestamp(event['timestamp']))
                    for event in events:
                        if (content_hash(event) not in applied or event.get('kind','daily')!='daily'
                                or configuration['settlement_mode']!='daily_mtm'): return ()
                        expected_basis = Decimal(str(event['price']))
                    if basis!=expected_basis: return ()
                    entries.append(entry); bases.append(basis); quantities.append(quantity)
                if observed!=expected or sum(quantities)!=abs(position): return ()
                index = indices[0]
                lines = [ReferenceLine('成交均價（未含費用）',sum((p*q for p,q in zip(entries,quantities)),Decimal(0))/abs(position),index,as_of),
                         ReferenceLine('MTM 基準（非保證金）',sum((p*q for p,q in zip(bases,quantities)),Decimal(0))/abs(position),index,as_of)]
                if result.manifest.get('protective_scope')=='whole position at most adverse triggered original-entry lot level':
                    parameters = result.manifest['strategy']['parameters']
                    for key,label,direction in (('stop_ticks','停損門檻',-side),('target_ticks','停利門檻',side)):
                        if key not in parameters: continue
                        offset = parameters[key]
                        if type(offset) is not int or offset<=0: return ()
                        levels = [price+direction*offset for price in entries]
                        lower, upper = min(levels),max(levels)
                        lines.append(ReferenceLine(label+('下緣' if lower!=upper else ''),lower,index,as_of))
                        if lower!=upper: lines.append(ReferenceLine(label+'上緣',upper,index,as_of))
                return tuple(lines)
        except (KeyError, ValueError, TypeError, InvalidOperation):
            return ()  # Legacy/incomplete snapshots do not invent reference prices.

    def inspect_candidate(self, index=None):
        self._candidate_valid = False
        reference = self.candidate_choice.currentData()
        if not reference:
            self.candidate_detail.setPlainText('尚無生成候選。執行研究後可檢視每個版本與獨立 OOS／保留集結果。')
        else:
            try:
                spec, provenance = candidate_record(self.root, reference)
                self.candidate_detail.setPlainText(canonical_json({'strategy':spec, **provenance}))
                self.candidate_card.set_values({'策略': spec.strategy_id, '紙上資格': provenance['paper_qualified'], '樣本外與保留集': provenance['evaluations']})
                self._candidate_valid = True
            except Exception:
                self.candidate_detail.setPlainText('此候選尚未有效評估或雜湊不符；不可套用。完整拒絕／中斷原因見研究紀錄。')
        self.use_candidate_button.setEnabled(self._candidate_valid and not self.jobs.active)

    def use_candidate(self):
        reference = self.candidate_choice.currentData()
        spec, provenance = candidate_record(self.root, reference)
        self.family.setCurrentText(spec.family)
        self.active_candidate = reference
        write_json(self.root / 'active_candidate.json', reference)
        self.parameters.setPlainText(canonical_json(spec.parameters)); self.parameters.setReadOnly(True)
        self.strategy_detail.setPlainText(canonical_json({'strategy':spec, **provenance}))
        self.strategy_form.setEnabled(False)
        self.batch.setChecked(False)
        self.status.setText('已套用不可變生成版本；研究回測不等於通過樣本外驗證。')

    def use_builtin(self):
        self._family_changed()
        self.status.setText('已切回內建家族；參數可編輯。')

    def save_settings(self):
        if self.settings is None: raise ValidationError('設定儲存服務不可用')
        value = self.settings.load()
        # Preserve legacy provider settings as inert historical data. They are
        # never read into executable provider options or overwritten on save.
        value.update({'persist_logs':self.persist_logs.isChecked(),
                      'local_notifications':self.local_notifications.isChecked()})
        value['market'] = self.market.preferences()
        value['window'] = {'x': self.x(), 'y': self.y(), 'width': self.width(), 'height': self.height()}
        self.settings.save(value)
        self.jobs.logging_enabled = self.persist_logs.isChecked()
        self.chatgpt_panel.consent.setChecked(False)
        self.status.setText('已保存非敏感偏好；訂閱同意已重設。')

    def load_settings(self):
        if self.settings is None: return
        value = self.settings.load()
        self.persist_logs.setChecked(value.get('persist_logs', True) is True)
        self.jobs.logging_enabled = self.persist_logs.isChecked()
        self.local_notifications.setChecked(value.get('local_notifications', True) is True)
        try:
            if 'market' in value: self.market.restore_preferences(value['market'])
            size = value.get('window', {})
            x, y = int(size.get('x', self.x())), int(size.get('y', self.y()))
            available = [screen.availableGeometry() for screen in QApplication.screens()]
            screen = next((rect for rect in available if rect.contains(x, y)), self.screen().availableGeometry())
            self.resize(min(max(int(size.get('width', self.width())), 800), screen.width()), min(max(int(size.get('height', self.height())), 600), screen.height()))
            self.move(max(screen.left(), min(x, screen.right()-self.width()+1)), max(screen.top(), min(y, screen.bottom()-self.height()+1)))
        except (ValueError, TypeError, KeyError, OverflowError):
            self.status.setText('市場偏好無效；使用安全預設，原設定保留。')
        self.read_logs()

    def configure_workspace(self):
        self.chatgpt_panel.abandon_primary_sign_in()
        from quantlab.desktop_runtime import WorkspaceLocator
        if self.jobs.active: raise ValidationError('請先停止背景作業')
        self.chatgpt_panel.consent.setChecked(False)
        self._invalidate_analysis_preview()
        self.chatgpt_controller.invalidate_campaign_usage()
        self._plan_usage_binding = None
        root = WorkspaceLocator(getattr(self.paths, 'bootstrap', None) or self.paths.root).configure(Path(self.workspace_path.text().strip()))
        self.status.setText('下次啟動將使用：' + str(root) + '。請關閉後重新開啟；目前資料未搬移或覆寫。')

    def open_releases(self):
        # Verified repository Releases destination; never invent latest version or assets.
        if not QDesktopServices.openUrl(QUrl('https://github.com/yostar77612/mark-auto/releases')):
            raise ValidationError('無法開啟瀏覽器；專案 Releases 網址：https://github.com/yostar77612/mark-auto/releases')
        self.status.setText('已要求預設瀏覽器開啟專案 Releases；未下載或執行更新。')

    def notify_local(self, message):
        if self.local_notifications.isChecked():
            self.notification.setText(message); self.notification.setStyleSheet('background:#213b50;color:#e8f1ff;padding:10px;border-radius:6px')
            self.notification.show(); QApplication.alert(self, 1500)

    def record_event(self, operation, kind):
        from quantlab.desktop_runtime import RedactedEventLog
        # Runtime owns redacted persistence; UI never appends the same event twice.
        self.log_view.appendPlainText((operation if operation in UI_OPERATIONS else 'background') + ' · ' + (kind if kind in ('progress','result','error','cancelled') else 'status'))

    def read_logs(self):
        from quantlab.desktop_runtime import RedactedEventLog
        self.log_view.setPlainText('\n'.join(RedactedEventLog(self.paths.logs / 'desktop-events.jsonl').tail()))

    def backup(self, restore):
        self.chatgpt_panel.abandon_primary_sign_in()
        if self.backups is None: raise ValidationError('備份服務不可用')
        if not self.backup_path.text().strip(): raise ValidationError('請填寫備份路徑')
        if restore and not self.restore_confirm.isChecked(): raise ValidationError('請先確認還原取代本機狀態')
        if self.jobs.active: raise ValidationError('請先等待背景作業停止')
        self.start_job('ui_backup_restore' if restore else 'ui_backup_create', {'path':self.backup_path.text()})
        self.restore_confirm.setChecked(False)

    def _quiesce_and_recover(self, *, preserve_primary_sign_in=False):
        if not preserve_primary_sign_in:
            self.chatgpt_panel.abandon_primary_sign_in()
        # Never create state files until the writer has exited and pending swaps recover.
        if self.jobs.active: self.jobs.cancel()
        if self.jobs.active: raise ValidationError('背景程序尚未停止；禁止還原或寫入狀態')
        if self.backups is not None:
            self.backups.recover()
        else:
            from quantlab.desktop_runtime import BackupManager
            BackupManager(self.paths).recover()

    def freeze_paper(self, reason):
        self._quiesce_and_recover()
        self.chatgpt_panel.consent.setChecked(False)
        self._pending_usage_refresh = False
        if self._chatgpt_job_request:
            self.chatgpt_controller.worker_joined(self._chatgpt_job_request.request_id, joined=True, terminal_received=False)
            self._chatgpt_job_request = None
        self.chatgpt_controller.account_status_known = False
        self.chatgpt_controller.invalidate_campaign_usage()
        self.paper_confirm.setChecked(False)
        if self.guard is not None: self.guard.reconciliation_required = True
        write_json(self.root / 'desktop_safety.json', {'reconciliation_required':True, 'reason':str(reason)})
        if (self.root / 'paper_policy.json').exists():
            broker = _paper(self.root)
            broker.set_kill_switch(True)
        self.status.setText('紙上執行已凍結：' + str(reason) + '；每次執行需核對快照並明確對帳。')

    def closeEvent(self, event):
        self.chatgpt_panel.abandon_primary_sign_in()
        if self.jobs.active and QMessageBox.question(self, '背景作業尚未完成', '取消背景作業並關閉？', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            event.ignore(); return
        try:
            self._closing = True
            self.chatgpt_controller.set_host_available(False)
            self.chatgpt_panel.consent.setChecked(False)
            self.jobs.close()
            self._quiesce_and_recover()
            if (self.last_operation == 'ui_walk_forward_run' or self._wf_pending_reconcile) and self._wf_launch is not None:
                self._wf_pending_reconcile = False
                self.jobs.poll()
                self.start_job('ui_walk_forward_reconcile', self._wf_launch)
                self._close_after_reconcile = True
                event.ignore()
                return
            if (self._analysis_running or self._pending_analysis_reconcile) and self._analysis_launch is not None:
                self._analysis_running=False;self._pending_analysis_reconcile=False
                self.jobs.poll()
                self.start_job('ui_analysis_reconcile',dict(self._analysis_launch))
                self._close_after_reconcile=True
                event.ignore();return
            if (self._subscription_campaign or self._pending_plan_reconcile) and self._plan_launch is not None:
                self._subscription_campaign = False
                self._pending_plan_reconcile = False
                self.jobs.poll()  # joined old terminal packets cannot own the new worker
                self.start_job('ui_chatgpt_reconcile', self._plan_launch)
                self._close_after_reconcile = True
                event.ignore()
                return
            if self._chatgpt_job_request:
                self.chatgpt_controller.worker_joined(self._chatgpt_job_request.request_id, joined=True, terminal_received=False)
                self._chatgpt_job_request = None
            if self.guard is not None: self.guard.finish()
        except Exception:
            self._closing = False
            self.chatgpt_controller.set_host_available(True)
            event.ignore(); self.status.setText('關閉失敗，背景作業尚未確認停止。'); return
        self._safe(self.save_market_preferences)
        self.chatgpt_controller.set_host_available(False)
        self.timer.stop(); event.accept()


def create_window(paths, jobs, settings=None, backups=None, guard=None):
    return MainWindow(paths, jobs, settings, backups, guard)

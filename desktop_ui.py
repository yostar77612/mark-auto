"""Native Traditional Chinese Qt workspace. No web server or live execution imports.

The GUI only schedules work. execute_ui_operation runs in the runtime's isolated
worker process; its inputs are data, never executable strategy source.
"""
from pathlib import Path
import json
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass
from urllib.parse import urlsplit
import ipaddress

from quantlab.core import (Dataset, StrategySpec, Instrument, ValidationError, canonical_json,
                   content_hash, to_dict)
from quantlab.reporting import (read_json, write_json, load_dataset, save_dataset, synthetic_dataset,
                        demo_config, export_report, load_result, comparison_rows,
                        save_selection, load_selection)

UI_OPERATIONS = frozenset('ui_' + op for op in (
    'demo', 'import', 'refresh', 'market_refresh', 'chatgpt_auth', 'chatgpt_usage', 'chatgpt_reconcile', 'backtest', 'campaign', 'compare', 'select', 'disable',
    'paper_snapshot', 'paper_reconcile', 'paper_kill', 'paper_replay', 'paper_submit', 'paper_cancel',
    'backup_create', 'backup_restore'))


def validate_endpoint(endpoint):
    try:
        url = urlsplit(endpoint)
        loopback = url.hostname == 'localhost'
        if url.hostname and not loopback:
            try: loopback = ipaddress.ip_address(url.hostname).is_loopback
            except ValueError: pass
        if not url.hostname or url.username or url.password or '?' in endpoint or '#' in endpoint or any(c.isspace() for c in endpoint):
            raise ValueError()
        if url.scheme != 'https' and not (url.scheme == 'http' and loopback): raise ValueError()
        if url.port == 0: raise ValueError()
        return loopback
    except ValueError:
        raise ValidationError('模型端點不得包含帳密、查詢參數或片段；遠端必須 HTTPS，本機可使用 loopback HTTP') from None


@dataclass(frozen=True)
class DesktopCredentialTransport:
    """Pickle-safe root/name only; credentials resolve in isolated provider child."""
    root: str
    use_credential: bool = True

    def __call__(self, endpoint, request, timeout_seconds):
        from quantlab.provider import HTTPTransport
        from quantlab.desktop_runtime import DesktopCredentialReference
        resolver = DesktopCredentialReference(root=self.root, name='model_api_key') if self.use_credential else None
        return HTTPTransport(allow_network=True, credential_resolver=resolver)(endpoint, request, timeout_seconds)


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
    # Adding the optional output-mode selector must not reopen a legacy budget.
    return {key: value for key, value in options.items()
            if key != 'network_opt_in' and not (key == 'output_mode' and value == 'json_object')}


def campaign_generator(paths, options):
    from quantlab.research import FixtureGenerator, CompatibleProvider
    if options.get('mode', 'fixture') == 'fixture':
        research_controls(paths)
        return FixtureGenerator()
    if options.get('mode') != 'compatible' or options.get('network_opt_in') is not True:
        raise ValidationError('真實模型必須明確同意本次網路與可能費用')
    local = validate_endpoint(options['endpoint'])
    if not local and (Decimal(options['cost_per_token']) <= 0 or Decimal(options['max_spend']) <= 0):
        raise ValidationError('遠端模型必須填寫正數單位費率及最高費用；不得假設免費')
    if not local and options.get('use_credential') is not True:
        raise ValidationError('遠端模型必須使用 Windows 安全儲存金鑰')
    identity = content_hash(provider_binding_options(options))
    return CompatibleProvider(model=options['model'], endpoint=options['endpoint'],
        transport=DesktopCredentialTransport(str(getattr(paths, 'bootstrap', None) or paths.root), options.get('use_credential', True)),
        budget_path=research_controls(paths)/'provider_budgets'/(identity+'.sqlite3'), network_opt_in=True,
        max_calls=options['max_calls'], max_tokens=options['max_tokens'], max_spend=options['max_spend'],
        tokens_per_call=options['tokens_per_call'], cost_per_token=options['cost_per_token'], timeout_seconds=options['timeout_seconds'],
        output_mode=options.get('output_mode', 'json_object'))


def connection_event_from_payload(payload):
    from desktop_chatgpt_ui import ConnectionEvent
    if not isinstance(payload, dict): raise ValidationError('連線事件格式不符')
    value = dict(payload)
    value['registrations'] = tuple(tuple(row) for row in value.get('registrations', ()))
    value['models'] = tuple(value.get('models', ()))
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


def execute_ui_operation(operation, payload, paths, *, emit=None, descendants_stopped=False):
    """Allowlisted process-worker adapter; no Qt objects are created here."""
    if operation not in UI_OPERATIONS:
        raise ValidationError('未知桌面作業')
    root = _root(paths)
    if operation == 'ui_chatgpt_auth':
        from desktop_chatgpt_ui import ConnectionRequest, run_connection_request
        from dataclasses import asdict
        if set(payload) != {'request'} or not isinstance(payload['request'], dict): raise ValidationError('連線請求格式不符')
        request = ConnectionRequest(**payload['request'])
        def private_event(event):
            if emit is None: raise ValidationError('授權需要受管理程序與私人進度通道')
            emit('auth_progress', auth_event=asdict(event))
        if request.action == 'begin' and emit is None: raise ValidationError('授權需要受管理程序')
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
        options = payload.get('provider', {'mode':'fixture'})
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
            replay = PaperReplay(root / 'replays' / (binding + '.sqlite3'), dataset=data,
                                 strategy=StrategySpec(**selection['strategy']), broker=broker,
                                 margin_per_contract=Decimal('100000'), margin_version='synthetic-assumption-v1')
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


from desktop_market import MarketDashboard
from desktop_forms import (StrategyForm, BacktestForm, CampaignForm, PaperPolicyForm,
    PaperIntentForm, PaperQuoteForm, PaperSnapshotForm, ResultTable, SummaryCard)


class MainWindow(QMainWindow):
    def __init__(self, paths, jobs, settings=None, backups=None, guard=None):
        super().__init__()
        self.paths, self.jobs, self.settings, self.backups, self.guard = paths, jobs, settings, backups, guard
        self.root = _root(paths)
        self.actions = []
        self.last_operation = None
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
        layout = self._page('策略與版本')
        layout.addWidget(QLabel('五種有限策略家族與受驗證參數；禁止任意 Python 策略程式。'))
        self.strategy_form = StrategyForm(); layout.addWidget(self.strategy_form)
        advanced = self._advanced(layout)
        self.family = QComboBox(); self.family.addItems([s.family for s in builtin_strategies()]); advanced.addWidget(self.family)
        self.parameters = self._text(advanced, '策略參數 JSON', '{}', True)
        self.strategy_detail = QPlainTextEdit(); self.strategy_detail.setReadOnly(True); advanced.addWidget(self.strategy_detail)
        self.family.currentIndexChanged.connect(self._family_changed); self._family_changed()
        layout.addWidget(QLabel('離線 Fixture 生成器：固定候選與版本紀錄；不是已驗證的真實模型。'))
        self.strategy_form.family.currentIndexChanged.connect(lambda: self.family.setCurrentIndex(self.strategy_form.family.currentIndex()))
        self.campaign_form = CampaignForm(); layout.addWidget(self.campaign_form)
        self.campaign_config = self._text(advanced, '研究設定 JSON（空白使用明示示範切分）', '', True)
        self._remember(self.campaign_config)
        self.provider_mode = QComboBox(); self.provider_mode.addItem('離線 Fixture（預設，非真實 AI）', 'fixture'); self.provider_mode.addItem('相容模型 HTTP（需設定、逐次同意；驗證未完成）', 'compatible'); self.provider_mode.addItem('手動 AI 交換（使用者自行傳送／貼回，未驗證）', 'manual'); self.provider_mode.addItem('官方 ChatGPT 訂閱（需自行授權；實際推論未驗證）', 'chatgpt_plan'); layout.addWidget(self.provider_mode)
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
        self.candidate_card = SummaryCard(); layout.addWidget(self.candidate_card)
        self.use_candidate_button = self._button(layout, '使用此不可變候選版本進行研究回測', 'use_candidate', self.use_candidate)
        self._button(layout, '改用內建家族與可編輯參數', 'use_builtin', self.use_builtin)
        self.history = QPlainTextEdit(); self.history.setReadOnly(True); advanced.addWidget(self.history)
        self.history_table = ResultTable(); layout.addWidget(self.history_table)
        layout.addWidget(QLabel('已保存樣本外／保留集評估（不回饋模型；沒有結果即未提供）'))
        self.evaluation_table = ResultTable(); layout.addWidget(self.evaluation_table)

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
        self.result_card = SummaryCard(); layout.addWidget(self.result_card)
        self.fills_table = ResultTable(); layout.addWidget(self.fills_table)
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
        self.ai_endpoint = self._text(layout, '模型完整 chat/completions 端點（遠端 HTTPS / 本機 loopback HTTP）')
        self.ai_model = self._text(layout, '模型名稱')
        self.output_mode = QComboBox(); self.output_mode.addItem('一般 JSON DSL（相容模式）', 'json_object'); self.output_mode.addItem('JSON Schema：內建家族參數生成（服務須支援；不支援即失敗）', 'registry_json_schema')
        layout.addWidget(QLabel('模型輸出協定：結構化模式不代表新策略邏輯或績效保證')); layout.addWidget(self.output_mode)
        self.api_key = self._text(layout, 'API 金鑰（只存 Windows DPAPI；不寫入設定、日誌或備份）')
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password); self.api_key.setObjectName('api_key')
        self._button(layout, '儲存金鑰至 Windows 安全儲存庫', 'save_api_key', self.save_api_key)
        self.use_key = QCheckBox('使用 Windows 安全儲存金鑰（遠端必須；本機無驗證服務可取消）'); self.use_key.setChecked(True); layout.addWidget(self.use_key)
        self.max_calls = QSpinBox(); self.max_calls.setRange(1,100); self.max_calls.setValue(1); layout.addWidget(QLabel('最多呼叫次數（失敗仍保留預算）')); layout.addWidget(self.max_calls)
        self.max_tokens = QSpinBox(); self.max_tokens.setRange(1,1000000); self.max_tokens.setValue(20000); layout.addWidget(QLabel('總 token 保守預算（含輸入位元組上限）')); layout.addWidget(self.max_tokens)
        self.tokens_per_call = QSpinBox(); self.tokens_per_call.setRange(1,32768); self.tokens_per_call.setValue(2048); layout.addWidget(QLabel('每次最大輸出 tokens')); layout.addWidget(self.tokens_per_call)
        self.timeout_seconds = QSpinBox(); self.timeout_seconds.setRange(1,120); self.timeout_seconds.setValue(30); layout.addWidget(QLabel('單次逾時秒數')); layout.addWidget(self.timeout_seconds)
        self.max_spend = self._text(layout, '最高費用（USD；供應商實際帳單仍需自行核對）', '0')
        self.cost_per_token = self._text(layout, '保守每 token 費率（USD；遠端不可為零）', '0')
        self.ai_opt_in = QCheckBox('我同意下一次模型研究：傳送策略內容與訓練／驗證統計至上述端點，可能產生費用（不傳 OOS／保留集）'); layout.addWidget(self.ai_opt_in)
        self.ai_status = QLabel('外部真實模型：NOT_VERIFIED。預設 Fixture；只有明確選取相容模型並勾選逐次同意才可連線。預算不是供應商帳單保證。'); self.ai_status.setWordWrap(True); layout.addWidget(self.ai_status)
        self.persist_logs = QCheckBox('保存精簡本機作業日誌（不含金鑰、路徑、請求或回應）'); self.persist_logs.setChecked(True); layout.addWidget(self.persist_logs)
        self.local_notifications = QCheckBox('作業完成／失敗時顯示本機提示並提醒此視窗'); self.local_notifications.setChecked(True); layout.addWidget(self.local_notifications)
        self._button(layout, '儲存非敏感偏好', 'save_settings', self.save_settings)
        self.backup_path = self._text(layout, '備份封存檔案路徑（請選工作區與應用資料夾以外的位置）')
        self._button(layout, '建立本機備份', 'create_backup', lambda: self.backup(False))
        self.restore_confirm = QCheckBox('我確認還原會替換目前本機狀態，並會要求重新對帳'); layout.addWidget(self.restore_confirm)
        self._button(layout, '驗證並還原備份', 'restore_backup', lambda: self.backup(True))
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
        if options['mode'] == 'chatgpt_plan':
            from dataclasses import asdict
            options = asdict(self.chatgpt_panel.build_plan_options())
            options['expected_binding'] = self._plan_usage_binding
            from quantlab.__main__ import config_from_json
            checked = dict(config); checked['backtest_config'] = config_from_json(checked['backtest_config'])
            plan_provider(self.paths, _dataset(self.root, {}), checked, options)
        if options['mode'] == 'manual':
            options.update(response_path=self.manual_path.text().strip(), response_text=self.manual_response.toPlainText())
        if options['mode'] == 'compatible':
            options.update(endpoint=self.ai_endpoint.text().strip(), model=self.ai_model.text().strip(),
                network_opt_in=self.ai_opt_in.isChecked(), use_credential=self.use_key.isChecked(), output_mode=self.output_mode.currentData(),
                max_calls=self.max_calls.value(), max_tokens=self.max_tokens.value(),
                max_spend=self.max_spend.text().strip(), cost_per_token=self.cost_per_token.text().strip(),
                tokens_per_call=self.tokens_per_call.value(), timeout_seconds=self.timeout_seconds.value())
            if options['network_opt_in'] is not True: raise ValidationError('請至設定核對供應商、費率與預算，並勾選本次網路及費用同意')
            # Construction checks only; no HTTP or credential reads in the GUI.
            campaign_generator(self.paths, options)
        subscription_campaign = options['mode'] == 'chatgpt_plan'
        launched_job = self.start_job('ui_campaign', {'config':config, 'provider':options})
        self._subscription_campaign = subscription_campaign
        if self._subscription_campaign:
            local_options = {**options,'network_opt_in':False,'included_usage_policy_confirmed':False}
            self._plan_launch = json.loads(canonical_json({'config':config,'provider':local_options,'binding':options['expected_binding'],'stopped_job_id':launched_job}))
            self.chatgpt_controller.invalidate_campaign_usage()
        self.ai_opt_in.setChecked(False)

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

    def _chatgpt_quiesce(self, request):
        try:
            self._quiesce_and_recover()
            self.poll_jobs()
            self.chatgpt_controller.acknowledge_quiescence(request.request_id, joined=not self.jobs.active)
        except Exception:
            self.chatgpt_controller.acknowledge_quiescence(request.request_id, joined=False)

    def _chatgpt_dispatch(self, request):
        try:
            if self.jobs.active:
                self._quiesce_and_recover()
            self.poll_jobs()
            self._chatgpt_job_request = request
            self._chatgpt_job_id = self.start_job('ui_chatgpt_auth', {'request':request.payload()})
        except Exception:
            self.chatgpt_controller.worker_joined(request.request_id, joined=not self.jobs.active, terminal_received=False)
            self._chatgpt_job_request = None
            self.status.setText('連線背景作業無法啟動；請核對本機狀態。')

    def _chatgpt_cancel(self, request_id):
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
        from desktop_chatgpt_ui import official_authorization_url
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if not QDesktopServices.openUrl(QUrl(official_authorization_url(url))):
            self.status.setText('無法開啟官方授權頁面；請取消後再核對環境。')

    def _plan_usage_request(self):
        c = self.chatgpt_controller; panel = self.chatgpt_panel
        if c.state != 'plan_ready' or not c.active_registration or panel.model.currentText() not in c.models:
            raise ValidationError('請先明確核對連線與官方模型清單')
        options = {'mode':'chatgpt_plan','registration':c.active_registration,
            'model':panel.model.currentText(),'max_calls':panel.max_calls.value(),
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
        if self.jobs.active: raise ValidationError('已有背景作業，請等待或取消')
        job_id = self.jobs.start(operation, payload)
        self.last_operation = operation
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

    def cancel_job(self):
        def cancel_and_recover():
            self.freeze_paper('使用者取消背景作業')
            self.status.setText('作業已停止；未完成還原已先復原，再凍結紙上執行。')
        self._safe(cancel_and_recover)

    def poll_jobs(self):
        try:
            for event in self.jobs.poll():
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
            except (ValueError, KeyError, TypeError) as exc:
                errors.append('研究資料無法作為已驗證市場歷史：' + str(exc))
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
        selected_ref = self.candidate_choice.currentData()
        self.candidate_choice.blockSignals(True); self.candidate_choice.clear()
        for entry in history:
            state = entry['content']
            if not isinstance(state, dict): continue
            for attempt in state.get('attempts', []):
                ref = {'campaign_folder':Path(entry['file']).parent.name, 'attempt_id':attempt.get('attempt_id'), 'strategy_hash':attempt.get('strategy_hash')}
                label = f"{state.get('campaign_id','')[:10]} · {attempt.get('family','?')} · v{attempt.get('sequence','?')} · {attempt.get('status','?')}"
                self.candidate_choice.addItem(label, ref)
        index = self.candidate_choice.findData(selected_ref)
        if index >= 0: self.candidate_choice.setCurrentIndex(index)
        self.candidate_choice.blockSignals(False); self.inspect_candidate()
        active_candidate = self.root / 'active_candidate.json'
        if self.active_candidate is None and active_candidate.exists():
            reference = read_json(active_candidate)
            index = self.candidate_choice.findData(reference)
            if index >= 0:
                self.candidate_choice.setCurrentIndex(index); self.use_candidate()

    def show_result(self, index=None):
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
        if data.manifest['data_hash'] != result.manifest.get('data_hash'): return
        if content_hash(result.manifest.get('strategy')) != result.manifest.get('spec_hash'): return
        # Require the exact adapted market source, not merely matching price/date.
        selected = self.market.contract_combo.currentData()
        item = self.market.selected_series()
        if item is None or self._market_data_bindings.get(selected) != data.manifest['data_hash']: return
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
        endpoint = self.ai_endpoint.text().strip()
        if endpoint: validate_endpoint(endpoint)
        value = self.settings.load()
        value.update({'ai_endpoint':self.ai_endpoint.text().strip(), 'ai_model':self.ai_model.text().strip(), 'output_mode':self.output_mode.currentData(),
            'max_calls':self.max_calls.value(), 'max_tokens':self.max_tokens.value(), 'tokens_per_call':self.tokens_per_call.value(),
            'timeout_seconds':self.timeout_seconds.value(), 'max_spend':self.max_spend.text().strip(), 'cost_per_token':self.cost_per_token.text().strip(),
            'persist_logs':self.persist_logs.isChecked(), 'local_notifications':self.local_notifications.isChecked()})
        value['market'] = self.market.preferences()
        value['window'] = {'x': self.x(), 'y': self.y(), 'width': self.width(), 'height': self.height()}
        self.settings.save(value)
        self.jobs.logging_enabled = self.persist_logs.isChecked()
        self.ai_opt_in.setChecked(False)
        self.status.setText('已保存非敏感偏好；網路同意已重設，未在設定中保存金鑰。')

    def load_settings(self):
        if self.settings is None: return
        value = self.settings.load()
        endpoint = value.get('ai_endpoint', '')
        if endpoint: validate_endpoint(endpoint)
        self.ai_endpoint.setText(endpoint)
        self.ai_model.setText(value.get('ai_model', ''))
        mode = value.get('output_mode', 'json_object')
        index = self.output_mode.findData(mode)
        if index < 0: raise ValidationError('不支援的模型輸出協定；原設定保留')
        self.output_mode.setCurrentIndex(index)
        for key in ('max_calls', 'max_tokens', 'tokens_per_call', 'timeout_seconds'):
            if key in value: getattr(self, key).setValue(value[key])
        for key in ('max_spend', 'cost_per_token'):
            if key in value: getattr(self, key).setText(value[key])
        self.ai_opt_in.setChecked(False)
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
        from quantlab.desktop_runtime import WorkspaceLocator
        if self.jobs.active: raise ValidationError('請先停止背景作業')
        self.chatgpt_panel.consent.setChecked(False)
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

    def save_api_key(self):
        from quantlab.desktop_runtime import CredentialVault
        secret = self.api_key.text()
        try:
            CredentialVault(self.paths).save('model_api_key', secret)
            self.status.setText('金鑰已存至目前 Windows 使用者的安全儲存庫；不包含於備份。')
        finally:
            self.api_key.clear()
            del secret

    def backup(self, restore):
        if self.backups is None: raise ValidationError('備份服務不可用')
        if not self.backup_path.text().strip(): raise ValidationError('請填寫備份路徑')
        if restore and not self.restore_confirm.isChecked(): raise ValidationError('請先確認還原取代本機狀態')
        if self.jobs.active: raise ValidationError('請先等待背景作業停止')
        self.start_job('ui_backup_restore' if restore else 'ui_backup_create', {'path':self.backup_path.text()})
        self.restore_confirm.setChecked(False)

    def _quiesce_and_recover(self):
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
        if self.jobs.active and QMessageBox.question(self, '背景作業尚未完成', '取消背景作業並關閉？', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            event.ignore(); return
        try:
            self._closing = True
            self.chatgpt_panel.consent.setChecked(False)
            self.jobs.close()
            self._quiesce_and_recover()
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
            event.ignore(); self.status.setText('關閉失敗，背景作業尚未確認停止。'); return
        self._safe(self.save_market_preferences)
        self.timer.stop(); event.accept()


def create_window(paths, jobs, settings=None, backups=None, guard=None):
    return MainWindow(paths, jobs, settings, backups, guard)

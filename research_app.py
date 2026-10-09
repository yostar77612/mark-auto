"""Separate offline Streamlit workspace. Run: streamlit run research_app.py."""
from pathlib import Path
import json
import os
import sqlite3

import streamlit as st

from quantlab.core import canonical_json, content_hash, to_dict, ValidationError
from quantlab.reporting import (synthetic_dataset, demo_config, save_dataset, load_dataset,
                               load_result, export_report, comparison_rows, read_json, write_json, save_selection, load_selection)
from quantlab.__main__ import config_from_json


def guard(action):
    try:
        return action()
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, ArithmeticError, sqlite3.Error) as exc:
        st.error(str(exc))
        return None


def report_view(result):
    st.caption('Selected result SHA-256: ' + content_hash(result))
    st.info('Result source: ' + str(result.manifest.get('source_type', 'UNKNOWN')).upper() + ' | dataset hash: ' + str(result.manifest.get('data_hash', 'unavailable')))
    st.json(to_dict(result.metrics))
    for warning in result.warnings:
        st.warning(warning)
    if not result.fills:
        st.info('No fills. A no-trade result is not evidence of a profitable strategy.')
    if result.equity:
        st.line_chart([{'equity': float(row['equity'])} for row in result.equity])
        st.caption('Equity samples in chronological order; full UTC timestamps and trade dates below.')
        st.dataframe([dict(row) for row in result.equity], width='stretch')
    with st.expander('Ledger, fills, rejects and reproducibility manifest'):
        st.json({'ledger': to_dict(result)['ledger'], 'fills': to_dict(result)['fills'],
                 'rejects': to_dict(result)['rejects'], 'manifest': result.manifest})


def main():
    st.set_page_config(page_title='TMF Offline Research', layout='wide')
    st.title('TMF Offline Research & Paper')
    st.warning('OFFLINE RESEARCH / PAPER ONLY. Live trading is disabled. Synthetic data and fixture-generated candidates are demonstrations, not verified market data or real AI integration.')
    root = Path(st.sidebar.text_input('Local workspace directory', os.environ.get('QUANTLAB_WORKSPACE', '.quantlab'))).expanduser()
    st.sidebar.caption('All datasets, reports, campaign history and paper journal remain on this machine.')
    if guard(lambda: root.mkdir(parents=True, exist_ok=True)) is None and not root.is_dir():
        return
    data_path = root / 'dataset.json'
    dataset = guard(lambda: load_dataset(data_path)) if data_path.exists() else None
    if dataset:
        st.info('Data source: ' + str(dataset.manifest.get('source_type', 'UNKNOWN')).upper() + f' | {len(dataset.bars)} bars')
    else:
        st.info('No dataset loaded. Import local data or create an explicitly synthetic demonstration.')
    tabs = st.tabs(['Import & quality', 'Strategies & backtest', 'Campaign history', 'Compare & select', 'Paper & recovery'])
    with tabs[0]:
        st.subheader('Local data and provenance')
        count = st.number_input('Synthetic demonstration bars', 120, 10000, 960, 120)
        if st.button('Create synthetic dataset'):
            if guard(lambda: save_dataset(synthetic_dataset(int(count)), data_path)) is None and data_path.exists():
                st.rerun()
        st.caption('Import never downloads data. Supply a supported official file and explicit versioned session intervals. Synthetic schema fixtures are not official-source evidence.')
        local_file = st.text_input('Local CSV / RPT path')
        calendar_file = st.text_input('Session calendar JSON path')
        kind = st.selectbox('Import kind', ['ticks', 'ticks_rpt', 'daily_json', 'synthetic_daily_json', 'synthetic_bars', 'synthetic_ticks', 'synthetic_taifex_ticks', 'proxy_bars', 'proxy_ticks'])
        contract = st.text_input('Explicit contract (optional filter)', 'TAIFEX:TMF:202601')
        encoding = st.selectbox('Encoding', ['auto', 'utf-8-sig', 'big5'])
        if st.button('Import local data'):
            def do_import():
                from quantlab.data import SessionCalendar, import_taifex
                calendar_data = read_json(calendar_file)
                cal = SessionCalendar(calendar_data['sessions'], version=calendar_data['version'])
                imported = import_taifex(Path(local_file), kind=kind, calendar=cal,
                                         contract_id=contract or None, encoding=None if encoding == 'auto' else encoding)
                save_dataset(imported, data_path)
                return imported
            if guard(do_import):
                st.rerun()
        if dataset:
            st.json({'manifest': dataset.manifest, 'quality': dataset.quality})
            st.dataframe([to_dict(bar) for bar in dataset.bars[:200]], width='stretch')
    from quantlab.strategies import builtin_strategies
    from quantlab.backtest import run_backtest
    specs = builtin_strategies()
    with tabs[1]:
        st.subheader('Five causal strategy families')
        labels = {s.family: s for s in specs}
        family = st.selectbox('Strategy family', list(labels))
        spec = labels[family]
        st.json(to_dict(spec))
        st.caption('Next-bar execution; adverse slippage; conservative stop/target ambiguity. Default costs and margin below are explicit synthetic assumptions. Edit them for a justified research run.')
        config_text = st.text_area('Backtest configuration JSON', canonical_json(demo_config()), height=200)
        if st.button('Run backtest', disabled=dataset is None):
            def run():
                config = config_from_json(json.loads(config_text))
                result = run_backtest(dataset, spec, config)
                paths = export_report(result, root / 'reports')
                write_json(Path(paths['result']).parent / 'strategy.json', spec)
                write_json(root / 'active_result.json', {'result_hash': paths['result_hash']})
                return result
            if guard(run):
                st.success('Backtest persisted. Repeating the same run reuses its content-addressed report.')
        active = root / 'active_result.json'
        if active.exists():
            def active_result():
                digest = read_json(active)['result_hash']
                if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValidationError('Invalid persisted result hash')
                return load_result(root / 'reports' / digest / 'result.json')
            result = guard(active_result)
            if result:
                report_view(result)
                st.download_button('Download result JSON', canonical_json(result), file_name='quantlab-result.json', mime='application/json')
    with tabs[2]:
        st.subheader('Bounded offline fixture campaign')
        st.caption('FixtureGenerator is deterministic test infrastructure. Real model status: NOT_VERIFIED. OOS and final holdout are never generator feedback. Completed campaigns reopen without spending trials again.')
        campaign_name = st.text_input('Campaign directory name', 'fixture-demo')
        valid_name = bool(campaign_name) and campaign_name not in ('.', '..') and all(c.isalnum() or c in '-_' for c in campaign_name)
        campaign_dir = root / 'campaigns' / campaign_name if valid_name else None
        if not valid_name:
            st.error('Campaign name must contain only letters, numbers, hyphens or underscores.')
        if dataset and len(dataset.bars) >= 16:
            from quantlab.research import demo_campaign_config, FixtureGenerator, run_campaign
            cfg = demo_campaign_config(dataset, demo_config())
            cfg_text = st.text_area('Locked campaign configuration JSON', canonical_json(cfg), height=240)
            if st.button('Run / reopen campaign', disabled=not valid_name):
                def campaign():
                    config = json.loads(cfg_text)
                    config['backtest_config'] = config_from_json(config['backtest_config'])
                    return run_campaign(dataset, config=config, generator=FixtureGenerator(), output_dir=campaign_dir)
                if guard(campaign):
                    st.success('Campaign state persisted. Selection thresholds were locked before evaluation.')
        histories = sorted((root / 'campaigns').glob('*/campaign.json')) if (root / 'campaigns').exists() else []
        if histories:
            history = st.selectbox('Persisted campaign history', histories, format_func=lambda p: p.parent.name)
            saved = guard(lambda: read_json(history))
            if saved:
                st.json(saved)
        else:
            st.info('No persisted campaigns yet.')
    with tabs[3]:
        st.subheader('Compare runs and select an immutable strategy')
        paths = sorted((root / 'reports').glob('*/result.json')) if (root / 'reports').exists() else []
        results = []
        valid_paths = []
        for path in paths:
            result = guard(lambda p=path: load_result(p))
            if result:
                results.append(result)
                valid_paths.append(path)
        if results:
            st.dataframe(comparison_rows(results), width='stretch')
            choice = st.selectbox('Result to select', range(len(results)), format_func=lambda i: content_hash(results[i]))
            selected_path = valid_paths[choice].parent / 'strategy.json'
            if st.button('Select immutable strategy', disabled=not selected_path.exists()):
                def select():
                    selected = read_json(selected_path)
                    save_selection(selected, results[choice], root / 'selection.json')
                    return True
                if guard(select):
                    st.success('Strategy selected by immutable content hash. No trading was started.')
        else:
            st.info('Run a backtest to compare results.')
        if (root / 'selection.json').exists():
            st.json(guard(lambda: load_selection(root / 'selection.json')))
    with tabs[4]:
        paper_view(root, dataset)


@st.cache_resource
def paper_broker(journal_path, sessions_json, margins_json, contract_id):
    from quantlab.paper import PaperBroker, RiskLimits
    from quantlab.core import Instrument
    from decimal import Decimal
    return PaperBroker(Path(journal_path), instrument=Instrument(contract_id), costs=demo_config().costs,
                       limits=RiskLimits(1, 1, Decimal('1000'), 30),
                       risk_sessions=tuple(json.loads(sessions_json)), margin_schedule=tuple(json.loads(margins_json)))


def paper_view(root, dataset):
    st.subheader('Paper account and recovery')
    st.caption('Manual quote/event simulation; no streaming feed or automatic strategy execution. Paper simulation only. Start removes the kill switch after successful reconciliation; stop blocks new orders and does not liquidate. There is no real broker connection.')
    from quantlab.paper import PaperBroker, RiskLimits
    from quantlab.core import Instrument
    from decimal import Decimal
    if dataset is None or not dataset.bars:
        st.info('Load a dataset before configuring a paper account.')
        return
    policy_path = root / 'paper_policy.json'
    saved_policy = (guard(lambda: read_json(policy_path)) or {}) if policy_path.exists() else {}
    contract_id = st.text_input('Pinned paper contract', saved_policy.get('contract_id', dataset.bars[0].contract_id))
    synthetic_sessions = [{'open': f'2026-01-{day:02d}T00:45:00Z', 'end': f'2026-01-{day:02d}T04:45:00Z',
                           'trade_date': f'2026-01-{day:02d}', 'session': 'day', 'contract_id': 'TAIFEX:TMF:202601',
                           'source': 'Explicitly invented synthetic demonstration policy'} for day in range(5, 9)]
    st.caption('Paper policies below are pinned to this journal. Defaults are invented Jan 5–8 demo sessions and margin, not an official calendar. Changing a pinned policy requires a new workspace/journal.')
    sessions_json = st.text_area('Pinned paper session policy JSON', canonical_json(saved_policy.get('risk_sessions', synthetic_sessions if dataset.manifest['source_type'] == 'synthetic' else [])))
    margins_json = st.text_area('Pinned paper margin schedule JSON', canonical_json(saved_policy.get('margin_schedule', [{'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'synthetic-assumption-v1'}])))
    broker = guard(lambda: paper_broker(str((root / 'paper.sqlite3').resolve()), sessions_json, margins_json, contract_id))
    if broker is None:
        return
    guard(lambda: write_json(policy_path, {'contract_id': contract_id, 'risk_sessions': json.loads(sessions_json), 'margin_schedule': json.loads(margins_json)}))
    st.warning('Carried positions require a pinned session opening_reference with price, known_at and version for the new trading date. Without that daily-loss baseline, new intents remain blocked. These references must be supplied explicitly; they are not fetched from a live feed.')
    st.json({'instrument': to_dict(broker.instrument), 'costs': to_dict(broker.costs), 'risk_limits': to_dict(broker.limits)})
    st.json(broker.snapshot())
    if st.button('Stop paper / enable kill switch'):
        guard(lambda: broker.set_kill_switch(True))
        st.rerun()
    st.caption('The prefilled local snapshot is only a synthetic self-check, not independent real-broker reconciliation. Confirm an external paper reference before using it.')
    snapshot = broker.snapshot()
    initial = {'account_id': 'paper-demo', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}}
    reconcile_text = st.text_area('External paper snapshot for reconciliation JSON', canonical_json(snapshot if snapshot.get('account_id') else initial), height=200)
    if st.button('Reconcile paper state'):
        outcome = guard(lambda: broker.reconcile(json.loads(reconcile_text)))
        if outcome is not None:
            st.json(outcome)
    if st.button('Start paper / remove kill switch'):
        guard(lambda: broker.set_kill_switch(False))
        st.rerun()
    selection = (guard(lambda: load_selection(root / 'selection.json')) or {}) if (root / 'selection.json').exists() else {}
    st.subheader('Selected strategy → bounded market replay')
    st.caption('Historical replay uses closed-bar signals and next-bar market quotes, with explicitly synthetic fills, costs and margin. No real-time feed. Intrabar stop/target simulation is excluded from this paper replay.')
    if selection and dataset:
        from quantlab.paper_replay import PaperReplay
        from quantlab.core import StrategySpec
        replay_id = content_hash([dataset.manifest.get('data_hash'), selection['strategy_hash']])
        replay = guard(lambda: PaperReplay(root / 'replays' / (replay_id + '.sqlite3'), dataset=dataset,
                                           strategy=StrategySpec(**selection['strategy']), broker=broker,
                                           margin_per_contract=Decimal('100000'), margin_version='synthetic-assumption-v1'))
        if replay:
            batch = st.number_input('Maximum replay bars per action', 1, 1000, 100)
            if st.button('Start selected strategy replay'):
                if guard(replay.start):
                    st.success('Replay enabled. Advance a bounded batch below; no background or live feed starts.')
            if st.button('Advance replay batch'):
                outcome = guard(lambda: replay.step(max_bars=int(batch)))
                if outcome:
                    st.json(outcome)
            if st.button('Stop selected strategy replay'):
                guard(replay.stop)
            st.json(replay.snapshot())
    else:
        st.info('Load data and select a backtested immutable strategy to enable replay.')
    st.caption('Explicit paper intent and quote are required; reusing a client_order_id is idempotent only for an identical intent. UNKNOWN state blocks new orders.')
    selection = (guard(lambda: load_selection(root / 'selection.json')) or {}) if (root / 'selection.json').exists() else {}
    sample_intent = {'client_order_id': 'paper-demo-001', 'strategy_hash': selection.get('strategy_hash', 'select-a-strategy-first'),
                     'contract_id': contract_id, 'side': 'buy', 'quantity': 1, 'order_type': 'market', 'created_at': '2026-01-05T01:00:00Z'}
    sample_quote = {'account_id': 'paper-demo', 'contract_id': contract_id, 'timestamp': '2026-01-05T01:00:00Z',
                    'price': '20000', 'trade_date': '2026-01-05', 'session_open': '2026-01-05T00:45:00Z',
                    'session_end': '2026-01-05T04:45:00Z', 'margin_per_contract': '100000'}
    intent_text = st.text_area('Paper intent JSON', canonical_json(sample_intent))
    quote_text = st.text_area('Paper quote and account assumptions JSON', canonical_json(sample_quote))
    now_text = st.text_input('Paper event time (UTC ISO)', '2026-01-05T01:00:00Z')
    if st.button('Submit paper intent', disabled=not selection):
        from datetime import datetime
        outcome = guard(lambda: broker.submit(json.loads(intent_text), quote=json.loads(quote_text), now=datetime.fromisoformat(now_text.replace('Z', '+00:00'))))
        if outcome is not None:
            st.json(outcome)
    cancel_id = st.text_input('Paper order ID to cancel')
    if st.button('Cancel paper order'):
        from datetime import datetime
        outcome = guard(lambda: broker.cancel(cancel_id, now=datetime.fromisoformat(now_text.replace('Z', '+00:00'))))
        if outcome is not None:
            st.json(outcome)
    event_text = st.text_area('Paper recovery event JSON', '{}')
    if st.button('Apply recovery event'):
        outcome = guard(lambda: broker.apply_event(json.loads(event_text)))
        if outcome is not None:
            st.json(outcome)
    st.json(broker.snapshot())
    if hasattr(broker, 'journal_events'):
        with st.expander('Durable paper journal events'):
            st.json(broker.journal_events())


if __name__ == '__main__':
    main()

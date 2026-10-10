"""Offline synthetic corpus; no private/purchased data and no network calls."""
import copy
from contextlib import closing, contextmanager
import json
import multiprocessing
import time
import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from quantlab.core import Bar, Dataset, CostSpec, BacktestConfig, ValidationError, content_hash, to_dict
from quantlab.research import (FixtureGenerator, CompatibleProvider, validate_dsl,
                              run_campaign, demo_campaign_config)
from quantlab.strategies import builtin_strategies


def inputs():
    start = datetime(2026, 9, 1, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(240):
        price = Decimal(20000 + (i % 31) * 3)
        bars.append(Bar(start + timedelta(minutes=i), start + timedelta(minutes=i + 1),
                        '2026-09-01', 'day', 'TAIFEX:TMF:202609', price, price + 2, price - 2, price, 10))
    bars = tuple(bars)
    data = Dataset(bars, {'source_type': 'synthetic', 'validation_status': 'valid',
                         'data_hash': content_hash(bars), 'calendar_version': 'synthetic-v1'}, {'valid': True})
    costs = CostSpec(Decimal('0'), Decimal('0'), 0, 'none', '2026-01-01', 'synthetic-zero-cost')
    config = BacktestConfig(Decimal('100000'), costs, initial_margin_per_contract=Decimal('1000'),
                            margin_version='synthetic-margin')
    campaign = demo_campaign_config(data, config)
    if 'fork' in multiprocessing.get_all_start_methods():
        campaign['process_start_method'] = 'fork'
    return data, campaign


class Spy(FixtureGenerator):
    def __init__(self):
        self.contexts = []
    def generate(self, context):
        self.contexts.append(copy.deepcopy(context))
        return super().generate(context)


class InvalidGenerator(FixtureGenerator):
    def generate(self, context): return {'code': 'import os'}
    def improve(self, context): raise RuntimeError('private provider detail')


class RenamedDuplicateGenerator(FixtureGenerator):
    def improve(self, context):
        return self.generate(context)


def invalid_improvement_transport(endpoint, request, timeout):
    # Inert unit-test provider only; no network or real-model acceptance.
    context = json.loads(request['messages'][-1]['content'])
    payload = to_dict(builtin_strategies()[0]) if context['iteration'] == 0 else {'code': 'invalid DSL fixture'}
    return {'choices': [{'message': {'content': json.dumps(payload)}}]}


class HangingGenerator(FixtureGenerator):
    def generate(self, context):
        while True:
            time.sleep(1)


def hanging_backtest(*args):
    while True:
        time.sleep(1)


def oversized_worker():
    return {'text': 'x' * 32768}


def memory_hog():
    return {'size': len(bytearray(256 * 1024 * 1024))}


@contextmanager
def tracked_sqlite_connections(*, fail_open_name=None, fail_statement=None):
    """Retain handles so GC cannot conceal a missing explicit close."""
    opened = []
    original_connect = sqlite3.connect
    class TrackingConnection(sqlite3.Connection):
        closed_explicitly = False
        def close(self):
            self.closed_explicitly = True
            return super().close()
        def execute(self, statement, *args, **kwargs):
            if fail_statement and statement.startswith(fail_statement):
                raise sqlite3.OperationalError('inert connection failure fixture')
            return super().execute(statement, *args, **kwargs)
        def executemany(self, statement, *args, **kwargs):
            if fail_statement and statement.startswith(fail_statement):
                raise sqlite3.OperationalError('inert connection failure fixture')
            return super().executemany(statement, *args, **kwargs)
    def connect(path, *args, **kwargs):
        if fail_open_name and Path(path).name == fail_open_name:
            raise sqlite3.OperationalError('inert database-open failure fixture')
        connection = original_connect(path, *args, factory=TrackingConnection, **kwargs)
        opened.append(connection)
        return connection
    try:
        with patch('quantlab.research.sqlite3.connect', side_effect=connect):
            yield opened
    finally:
        # Cleanup after assertions, without letting GC make a broken test pass.
        for connection in opened:
            if not connection.closed_explicitly:
                connection.close()


class ResearchTests(unittest.TestCase):
    def test_production_prompt_explains_schema_without_candidate_answer(self):
        from quantlab.research import PROMPT, FAMILIES
        for key in ('strategy_id', 'family', 'parameters', 'rules', 'schema_version'):
            self.assertIn(key, PROMPT)
        for family in FAMILIES:
            self.assertIn(family + ':', PROMPT)
        self.assertIn('Choose parameter values yourself', PROMPT)
        self.assertNotIn('fixture_', PROMPT)
        self.assertNotIn('trend-v1', PROMPT)

    def test_candidate_fingerprint_normalizes_numbers_defaults_and_cosmetic_ids(self):
        from quantlab.research import candidate_fingerprint
        from decimal import localcontext
        first = {'strategy_id': 'first', 'family': 'mean_reversion',
                 'parameters': {'lookback': 20, 'entry_bps': '0123.4500'}, 'rules': {}}
        second = copy.deepcopy(first)
        second['strategy_id'] = 'renamed'
        second['parameters'].update(entry_bps='123.45', quantity=1)
        a, b = validate_dsl(first), validate_dsl(second)
        self.assertEqual(candidate_fingerprint(a), candidate_fingerprint(b))
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(candidate_fingerprint(a), candidate_fingerprint(b))
        second['parameters']['lookback'] = 21
        self.assertNotEqual(candidate_fingerprint(a), candidate_fingerprint(validate_dsl(second)))

    def test_duplicate_improvement_is_retained_but_not_retested(self):
        data, config = inputs()
        config.update(families=['trend'], max_trials=2, max_improvements=1)
        config['ranking']['minimum'] = '-1000000'
        with tempfile.TemporaryDirectory() as tmp:
            state = run_campaign(data, config=config, generator=RenamedDuplicateGenerator(), output_dir=Path(tmp)/'campaign')
        first, second = state['attempts']
        self.assertEqual(first['status'], 'evaluated')
        self.assertEqual(second['status'], 'rejected')
        self.assertNotEqual(first['output']['strategy_id'], second['output']['strategy_id'])
        self.assertEqual(first['candidate_fingerprint'], second['candidate_fingerprint'])
        self.assertEqual(second['duplicate_of'], first['attempt_id'])
        self.assertEqual(second['parent_id'], first['attempt_id'])
        self.assertEqual(second['metrics'], {})
        self.assertIn('duplicate_candidate_not_retested', second['warnings'])

    def test_distinct_improvement_receives_only_previous_training_feedback(self):
        data, config = inputs()
        config.update(families=['trend'], max_trials=2, max_improvements=1)
        config['ranking']['minimum'] = '-1000000'
        with tempfile.TemporaryDirectory() as tmp:
            state = run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=Path(tmp)/'campaign')
        first, second = state['attempts']
        self.assertEqual([first['status'], second['status']], ['evaluated', 'evaluated'])
        self.assertNotEqual(first['candidate_fingerprint'], second['candidate_fingerprint'])
        previous = second['generator_context']['previous']
        self.assertEqual(previous['output'], first['output'])
        self.assertEqual(set(previous['metrics']), {'train', 'validation'})
        self.assertEqual(previous['metrics']['validation'], first['metrics']['validation']['metrics'])
        self.assertNotIn('oos', second['generator_context'])
        self.assertNotIn('holdout', second['generator_context'])

    def test_invalid_improvement_consumes_real_provider_budget_without_fallback(self):
        data, config = inputs()
        config.update(families=['trend'], max_trials=2, max_improvements=1)
        config['ranking']['minimum'] = '-1000000'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'budget.db'
            provider = CompatibleProvider(model='unit-test-mock-not-real', endpoint='https://example.invalid/v1',
                transport=invalid_improvement_transport, budget_path=path, network_opt_in=True,
                max_calls=2, max_tokens=30000)
            state = run_campaign(data, config=config, generator=provider, output_dir=Path(tmp)/'campaign')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT calls FROM budget').fetchone()[0], 2)
        first, second = state['attempts']
        self.assertEqual([first['status'], second['status']], ['evaluated', 'rejected'])
        self.assertEqual(second['output'], {'code': 'invalid DSL fixture'})
        self.assertEqual(second['metrics'], {})
        self.assertEqual(len(state['provider_receipts']), 2)

    def test_provider_improve_marks_task_without_mutating_or_injecting_answers(self):
        requests = []
        def transport(endpoint, request, timeout):
            requests.append(request)
            return {'choices': [{'message': {'content': '{}'}}]}
        context = {'family': 'trend', 'iteration': 1, 'previous': {'metrics': {'train': {}, 'validation': {}}}}
        before = copy.deepcopy(context)
        with tempfile.TemporaryDirectory() as tmp:
            provider = CompatibleProvider(model='unit-test-mock', endpoint='https://example.invalid/v1',
                transport=transport, budget_path=Path(tmp)/'budget.db', network_opt_in=True,
                max_calls=1, max_tokens=20000, output_mode='registry_json_schema')
            provider.improve(context)
        sent = json.loads(requests[0]['messages'][-1]['content'])
        self.assertEqual(context, before)
        self.assertEqual(sent['task'], 'improve_previous_candidate')
        self.assertEqual(sent['previous'], before['previous'])
        self.assertIn('not just strategy_id', sent['improvement_instruction'])

    def test_registry_schema_is_closed_but_keeps_cross_field_validator(self):
        from quantlab.research import registry_json_schema, FAMILIES
        from quantlab.strategies import DEFAULTS
        for family in FAMILIES:
            schema = registry_json_schema(family)
            self.assertFalse(schema['additionalProperties'])
            self.assertEqual(schema['properties']['family']['const'], family)
            params = schema['properties']['parameters']
            self.assertFalse(params['additionalProperties'])
            self.assertEqual(set(params['required']), set(DEFAULTS[family]))
            self.assertTrue(all(v['type'] == 'integer' and v['minimum'] < v['maximum']
                                for v in params['properties'].values()))
            self.assertFalse(schema['properties']['rules']['additionalProperties'])
        with self.assertRaises(ValidationError): registry_json_schema('unknown')
        with self.assertRaises(ValidationError):
            validate_dsl({'strategy_id': 'unit-invalid', 'family': 'trend',
                          'parameters': {'fast': 20, 'slow': 10}, 'rules': {}})

    def test_structured_request_is_explicit_and_never_falls_back(self):
        requests = []
        def transport(endpoint, request, timeout):
            requests.append(request)
            raise ValidationError('unit-test unsupported schema response')
        with tempfile.TemporaryDirectory() as tmp:
            provider = CompatibleProvider(model='unit-test', endpoint='https://example.invalid/v1',
                transport=transport, budget_path=Path(tmp)/'budget.db', network_opt_in=True,
                max_calls=1, max_tokens=10000, output_mode='registry_json_schema')
            with self.assertRaises(ValidationError): provider.generate({'family': 'trend'})
            self.assertEqual(len(requests), 1)
            fmt = requests[0]['response_format']
            self.assertEqual(fmt['type'], 'json_schema')
            self.assertTrue(fmt['json_schema']['strict'])
            self.assertEqual(fmt['json_schema']['schema']['properties']['family']['const'], 'trend')
            with self.assertRaises(ValidationError): provider.generate({'family': 'trend'})
            self.assertEqual(len(requests), 1)

    def test_default_output_mode_preserves_existing_durable_budget_identity(self):
        def transport(*args):
            return {'choices': [{'message': {'content': '{}'}}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'budget.db'
            options = dict(model='unit-test', endpoint='https://example.invalid/v1',
                transport=transport, budget_path=path, network_opt_in=True,
                max_calls=1, max_tokens=10000)
            CompatibleProvider(**options).generate({})
            with closing(sqlite3.connect(path)) as db:
                binding = db.execute('SELECT binding FROM budget').fetchone()[0]
            legacy = {'model': 'unit-test', 'endpoint': 'https://example.invalid/v1',
                      'calls': 1, 'tokens': 10000, 'spend': '0', 'rate': '0',
                      'per_call': 2048, 'timeout': 30}
            self.assertEqual(binding, content_hash(legacy))
            with self.assertRaisesRegex(ValidationError, 'budget exhausted'):
                CompatibleProvider(**options, output_mode='json_object').generate({})
            with self.assertRaisesRegex(ValidationError, 'immutable'):
                CompatibleProvider(**options, output_mode='registry_json_schema').generate({'family': 'trend'})

    def test_parameter_contract_matches_each_registry_family(self):
        from quantlab.research import PARAMETER_CONTRACTS
        from quantlab.strategies import DEFAULTS
        self.assertEqual(set(PARAMETER_CONTRACTS), set(DEFAULTS))
        for family, defaults in DEFAULTS.items():
            self.assertEqual(set(PARAMETER_CONTRACTS[family]), set(defaults))
            self.assertTrue(all(isinstance(v, str) for v in PARAMETER_CONTRACTS[family].values()))

    def test_training_summary_uses_only_partitioned_training_bars(self):
        from quantlab.research import _campaign_config, training_summary
        data, config = inputs()
        splits = _campaign_config(data, config)
        summary = training_summary(splits['train'])
        self.assertEqual(summary['bar_count'], len(splits['train'].bars))
        self.assertEqual(summary['hash'], content_hash(splits['train'].bars))
        self.assertEqual(summary['last_close'], str(splits['train'].bars[-1].close))
        self.assertEqual(summary['total_volume'], sum(b.volume for b in splits['train'].bars))
        self.assertEqual(set(summary), {'bar_count', 'hash', 'first_close', 'last_close', 'high', 'low', 'total_volume'})
        self.assertNotEqual(summary['hash'], content_hash(data.bars))

    def test_provider_rejects_secret_endpoints_before_persistence(self):
        # Deliberately synthetic URL markers; never contact a provider.
        endpoints = [
            'https://fixture-user:synthetic-secret@example.invalid/v1',
            'https://fixture-user@example.invalid/v1',
            'https://@example.invalid/v1',
            'https://example.invalid/v1?key=synthetic-secret',
            'https://example.invalid/v1#synthetic-secret',
            'https://example.invalid/v1?',
            'https://example.invalid/v1#',
            'https:///v1',
            'https://example.invalid:bad/v1',
            'https://example.invalid:65536/v1',
            'https://example.invalid:0/v1',
            'https://[broken/v1',
            'https://example.invalid/\nsynthetic-secret',
            'https://example.invalid/\x00synthetic-secret',
            'https://example.invalid/\x7fsynthetic-secret',
        ]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'untouched' / 'provider.sqlite3'
                with patch('quantlab.research.canonical_json') as serialize:
                    with self.assertRaises(ValidationError) as caught:
                        CompatibleProvider(model='fixture', endpoint=endpoint,
                                           transport=lambda *args: self.fail('No transport call allowed'),
                                           budget_path=path)
                    serialize.assert_not_called()
                self.assertNotIn('synthetic-secret', str(caught.exception))
                self.assertFalse(path.parent.exists())

    def assert_connections_closed(self, connections):
        self.assertTrue(connections)
        self.assertTrue(all(db.closed_explicitly for db in connections))
        for db in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')

    def test_provider_connections_close_on_success_failure_and_budget_rejection(self):
        def success(*args):
            return {'choices': [{'message': {'content': json.dumps(to_dict(builtin_strategies()[0]))}}]}
        def failure(*args):
            raise RuntimeError('inert transport failure')
        for transport in (success, failure):
            with self.subTest(transport=transport.__name__), tempfile.TemporaryDirectory() as tmp:
                provider = CompatibleProvider(model='fixture', endpoint='https://example.invalid/v1',
                    transport=transport, budget_path=Path(tmp) / 'provider.db', network_opt_in=True,
                    max_calls=1, max_tokens=10000)
                with tracked_sqlite_connections() as connections:
                    if transport is success:
                        provider.generate({})
                    else:
                        with self.assertRaises(RuntimeError): provider.generate({})
                    with self.assertRaises(ValidationError): provider.generate({})
                    self.assertEqual(len(connections), 3)
                    self.assert_connections_closed(connections)
                with closing(sqlite3.connect(Path(tmp) / 'provider.db')) as db:
                    self.assertEqual(db.execute('SELECT calls FROM budget').fetchone()[0], 1)

    def test_holdout_connections_close_and_failed_reservation_rolls_back(self):
        from quantlab.research import _reserve_holdout
        data, _ = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            args = dict(registry_path=Path(tmp) / 'registry.db', campaign_id='fixture',
                        selection_hash='fixture-selection', output_dir=Path(tmp) / 'campaign')
            with tracked_sqlite_connections(fail_statement='INSERT INTO coverage') as connections:
                with self.assertRaises(sqlite3.OperationalError): _reserve_holdout(data, **args)
                self.assert_connections_closed(connections)
            with closing(sqlite3.connect(args['registry_path'])) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 0)
            with tracked_sqlite_connections() as connections:
                self.assertEqual(_reserve_holdout(data, **args)['status'], 'reserved_consumed')
                self.assertEqual(_reserve_holdout(data, **args)['status'], 'previously_consumed')
                self.assertEqual(len(connections), 2)
                self.assert_connections_closed(connections)

    def test_campaign_connections_close_including_initialization_failures(self):
        data, config = inputs(); config['max_trials'] = 1
        for failure in ('none', 'open_state', 'create_state', 'begin_lock'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                kwargs = {'fail_open_name': 'campaign.sqlite3'} if failure == 'open_state' else {}
                if failure == 'create_state': kwargs['fail_statement'] = 'CREATE TABLE IF NOT EXISTS state'
                if failure == 'begin_lock': kwargs['fail_statement'] = 'BEGIN EXCLUSIVE'
                with tracked_sqlite_connections(**kwargs) as connections:
                    with patch('quantlab.research._run_bounded', side_effect=ValidationError('inert candidate rejection')):
                        if failure == 'none':
                            run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'campaign')
                        else:
                            expected = ValidationError if failure == 'begin_lock' else sqlite3.OperationalError
                            with self.assertRaises(expected):
                                run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'campaign')
                    self.assert_connections_closed(connections)
                # Another caller can acquire the lock immediately after any exit.
                with closing(sqlite3.connect(Path(tmp) / 'campaign' / 'campaign.lock.sqlite3', timeout=0.1)) as db, db:
                    db.execute('BEGIN EXCLUSIVE')

    def test_all_families_validate(self):
        self.assertEqual(len(builtin_strategies()), 5)
        for spec in builtin_strategies():
            self.assertEqual(validate_dsl(to_dict(spec)), spec)

    def test_reject_corpus(self):
        base = to_dict(builtin_strategies()[0])
        bad = []
        for field, value in [('code', '__import__("os")'), ('url', 'https://bad'), ('path', '/etc/passwd')]:
            item = copy.deepcopy(base); item[field] = value; bad.append(item)
        for value in [float('nan'), float('inf'), -1, True, 'exec(1)']:
            item = copy.deepcopy(base); item['parameters']['fast'] = value; bad.append(item)
        for node in [{'op': 'eval', 'value': '1'}, {'op': 'field', 'name': 'close', 'lag': -1},
                     {'op': 'const', 'value': 'NaN'}, {'op': 'const', 'value': '__import__("os")'}]:
            item = copy.deepcopy(base); item['rules'] = {'long': node, 'short': node}; bad.append(item)
        item = copy.deepcopy(base); item['parameters']['risk_override'] = True; bad.append(item)
        item = copy.deepcopy(base); item['strategy_id'] = '../escape'; bad.append(item)
        item = copy.deepcopy(base); item['schema_version'] = True; bad.append(item)
        item = copy.deepcopy(base); item['rules'] = {'long': {'op': 'const', 'value': 1}, 'short': {'op': 'const', 'value': 0}}; bad.append(item)
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                validate_dsl(payload)

    def test_ast_depth_and_lag(self):
        node = {'op': 'gt', 'left': {'op': 'field', 'name': 'close', 'lag': 0}, 'right': {'op': 'const', 'value': '20000'}}
        payload = to_dict(builtin_strategies()[0]); payload['rules'] = {'long': node, 'short': {'op': 'not', 'arg': node}}
        validate_dsl(payload)
        for _ in range(20): node = {'op': 'not', 'arg': node}
        payload['rules']['long'] = node
        with self.assertRaises(ValidationError): validate_dsl(payload)

    def test_campaign_improves_freezes_and_restarts(self):
        data, config = inputs(); config['ranking']['minimum'] = '-100000'
        spy = Spy()
        with tempfile.TemporaryDirectory() as tmp:
            state = run_campaign(data, config=config, generator=spy, output_dir=Path(tmp) / 'campaign')
            self.assertEqual(len(state['attempts']), 15)
            self.assertTrue(all(a['status'] == 'evaluated' for a in state['attempts']), state['attempts'])
            self.assertEqual(len(state['selected']), 5)
            self.assertTrue(state['holdout_consumed'])
            self.assertEqual(state['selection_hash'], state['holdout_selection_hash'])
            self.assertEqual(state['real_model_status'], 'not_verified')
            self.assertTrue(all(a['parent_id'] for a in state['attempts'][5:]))
            before = len(spy.contexts)
            again = run_campaign(data, config=config, generator=spy, output_dir=Path(tmp) / 'campaign')
            self.assertEqual(state, again)
            self.assertEqual(len(spy.contexts), before)
            for context in [a['generator_context'] for a in state['attempts']]:
                text = json.dumps(context)
                self.assertNotIn('holdout', text); self.assertNotIn('oos', text)
                self.assertNotIn('bars', context)
            config['seed'] += 1
            with self.assertRaises(ValidationError): run_campaign(data, config=config, generator=spy, output_dir=Path(tmp) / 'campaign')

    def test_failed_trials_consume_budget(self):
        data, config = inputs(); config['max_trials'] = 7
        with tempfile.TemporaryDirectory() as tmp:
            state = run_campaign(data, config=config, generator=InvalidGenerator(), output_dir=Path(tmp) / 'campaign')
            self.assertEqual(len(state['attempts']), 7)
            self.assertEqual([a['status'] for a in state['attempts']], ['rejected'] * 5 + ['failed'] * 2)
            self.assertEqual(state['selected'], []); self.assertFalse(state['holdout_consumed'])
            self.assertNotIn('private provider detail', json.dumps(state))

    def test_splits_and_source_integrity(self):
        data, config = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            config['splits']['validation'][0] = 1
            with self.assertRaises(ValidationError): run_campaign(data, config=config, generator=Spy(), output_dir=Path(tmp) / 'campaign')
            data, config = inputs(); data = Dataset(data.bars, {**data.manifest, 'data_hash': 'forged'}, dict(data.quality))
            with self.assertRaises(ValidationError): run_campaign(data, config=config, generator=Spy(), output_dir=Path(tmp) / 'campaign')

    def test_reimport_wallclock_does_not_duplicate_trials(self):
        data, config = inputs(); config['max_trials'] = 1
        first = Dataset(data.bars, {**data.manifest, 'imported_at': '2026-10-09T00:00:00Z'}, dict(data.quality))
        later = Dataset(data.bars, {**data.manifest, 'imported_at': '2026-10-09T01:00:00Z'}, dict(data.quality))
        with tempfile.TemporaryDirectory() as tmp:
            state = run_campaign(first, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'campaign')
            again = run_campaign(later, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'campaign')
        self.assertEqual(state, again)
        self.assertEqual(state['source_manifest']['imported_at'], '2026-10-09T00:00:00Z')

    def test_new_name_and_changed_training_cannot_reset_holdout(self):
        data, config = inputs(); config['max_trials'] = 1
        config['ranking']['minimum'] = '-100000'
        changed = list(data.bars)
        b = changed[0]
        changed[0] = Bar(b.timestamp, b.end, b.trade_date, b.session, b.contract_id,
                         b.open + 1, b.high + 1, b.low + 1, b.close + 1, b.volume)
        changed = Dataset(tuple(changed), {**data.manifest, 'data_hash': content_hash(tuple(changed))}, dict(data.quality))
        with tempfile.TemporaryDirectory() as tmp:
            first = run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'first')
            self.assertTrue(first['evaluations']['holdout'])
            self.assertEqual(first, run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'first'))
            second = run_campaign(changed, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'renamed')
            self.assertEqual(second['status'], 'blocked_previously_consumed_holdout')
            self.assertEqual(second['holdout_status'], 'previously_consumed')
            self.assertEqual(second['evaluations']['holdout'], [])
            self.assertEqual(first['holdout_registry']['holdout_hash'], second['holdout_registry']['holdout_hash'])
            self.assertNotEqual(first['campaign_id'], second['campaign_id'])

    def test_shifted_indexes_and_overlap_are_already_seen(self):
        data, config = inputs(); config['max_trials'] = 1; config['ranking']['minimum'] = '-100000'
        b = data.bars[0]
        prefix = tuple(Bar(b.timestamp - timedelta(minutes=10-i), b.timestamp - timedelta(minutes=9-i),
                           b.trade_date, b.session, b.contract_id, b.open, b.high, b.low, b.close, b.volume)
                       for i in range(10))
        shifted_bars = prefix + data.bars
        shifted = Dataset(shifted_bars, {**data.manifest, 'data_hash': content_hash(shifted_bars)}, dict(data.quality))
        shifted_config = copy.deepcopy(config)
        shifted_config['splits'] = {k: [a+10, b+10] for k, (a, b) in config['splits'].items()}
        with tempfile.TemporaryDirectory() as tmp:
            run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'first')
            second = run_campaign(shifted, config=shifted_config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'shifted')
            self.assertEqual(second['holdout_status'], 'previously_consumed')
            overlap = copy.deepcopy(config); overlap['splits']['holdout'][0] += 1
            third = run_campaign(data, config=overlap, generator=FixtureGenerator(), output_dir=Path(tmp) / 'overlap')
            self.assertEqual(third['holdout_status'], 'previously_consumed')
            self.assertEqual(third['evaluations']['holdout'], [])

    def test_holdout_registry_reservation_is_atomic(self):
        from concurrent.futures import ThreadPoolExecutor
        from quantlab.research import _reserve_holdout
        data, _ = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            def reserve(index):
                return _reserve_holdout(data, registry_path=Path(tmp) / 'registry.db',
                    campaign_id=str(index), selection_hash=str(index), output_dir=Path(tmp) / str(index))
            with ThreadPoolExecutor(max_workers=2) as executor:
                rows = list(executor.map(reserve, [1, 2]))
            self.assertEqual(sorted(r['status'] for r in rows), ['previously_consumed', 'reserved_consumed'])
            with closing(sqlite3.connect(Path(tmp) / 'registry.db')) as db, db:
                self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 1)

    def test_no_winner_is_valid(self):
        data, config = inputs(); config['ranking']['minimum'] = '100000000'
        with tempfile.TemporaryDirectory() as tmp:
            state = run_campaign(data, config=config, generator=Spy(), output_dir=Path(tmp) / 'campaign')
            self.assertEqual(state['selected'], []); self.assertEqual(state['status'], 'completed')

    def test_provider_default_no_call_and_persistent_budget(self):
        calls = []
        def transport(endpoint, request, timeout):
            calls.append(request)
            return {'choices': [{'message': {'content': json.dumps(to_dict(builtin_strategies()[0]))}}]}
        with tempfile.TemporaryDirectory() as tmp:
            kw = dict(model='explicit-fixture-model', endpoint='https://example.invalid/v1', transport=transport,
                      budget_path=Path(tmp) / 'provider.sqlite3', max_calls=1, max_tokens=10000)
            provider = CompatibleProvider(**kw)
            with self.assertRaises(ValidationError): provider.generate({})
            self.assertFalse(calls)
            provider = CompatibleProvider(**kw, network_opt_in=True)
            validate_dsl(provider.generate({}))
            self.assertEqual(provider.real_model_status, 'not_verified')
            provider = CompatibleProvider(**kw, network_opt_in=True)
            with self.assertRaises(ValidationError): provider.generate({})
            self.assertEqual(len(calls), 1)

    def test_crash_consumes_trial(self):
        class Crashes(FixtureGenerator):
            def generate(self, context): raise KeyboardInterrupt()
        data, config = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            with patch('quantlab.research._run_bounded', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt): run_campaign(data, config=config, generator=Crashes(), output_dir=Path(tmp) / 'campaign')
            state = run_campaign(data, config=config, generator=Spy(), output_dir=Path(tmp) / 'campaign')
            self.assertEqual(state['status'], 'blocked_interrupted')
            self.assertEqual(state['attempts'][0]['status'], 'interrupted')

    def test_concurrent_campaign_is_rejected_without_trial(self):
        data, config = inputs(); spy = Spy()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'campaign').mkdir()
            lock = sqlite3.connect(Path(tmp) / 'campaign' / 'campaign.lock.sqlite3')
            lock.execute('BEGIN EXCLUSIVE')
            try:
                with self.assertRaises(ValidationError):
                    run_campaign(data, config=config, generator=spy, output_dir=Path(tmp) / 'campaign')
                self.assertEqual(spy.contexts, [])
            finally:
                lock.rollback(); lock.close()

    def test_hanging_generator_is_killed_and_budget_consumed(self):
        data, config = inputs(); config['max_runtime_seconds'] = 1
        config['process_start_method'] = 'spawn'
        before = {p.pid for p in multiprocessing.active_children()}
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            state = run_campaign(data, config=config, generator=HangingGenerator(), output_dir=Path(tmp) / 'campaign')
            self.assertLess(time.monotonic() - started, 4)
            self.assertEqual(state['attempts'][0]['status'], 'timed_out')
            self.assertEqual(state['status'], 'budget_exhausted')
            self.assertEqual(run_campaign(data, config=config, generator=HangingGenerator(), output_dir=Path(tmp) / 'campaign'), state)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)

    @unittest.skipUnless('fork' in multiprocessing.get_all_start_methods(), 'Patch inheritance uses POSIX fork; production default is spawn')
    def test_hanging_backtest_is_killed(self):
        data, config = inputs(); config['max_runtime_seconds'] = 1
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp, patch('quantlab.research.run_backtest', side_effect=hanging_backtest):
            state = run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'campaign')
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(state['attempts'][0]['status'], 'timed_out')
        self.assertEqual(state['status'], 'budget_exhausted')

    def test_worker_ipc_size_is_bounded(self):
        from quantlab.research import _run_bounded
        with self.assertRaises(ValidationError):
            _run_bounded(oversized_worker, (), deadline=time.monotonic() + 5,
                         config={'max_ipc_bytes': 16384})

    @unittest.skipUnless(sys.platform.startswith('linux'), 'RLIMIT_AS verification requires Linux')
    def test_worker_memory_limit_rejects_large_allocation(self):
        from quantlab.research import _run_bounded
        with self.assertRaisesRegex(RuntimeError, 'MemoryError'):
            _run_bounded(memory_hog, (), deadline=time.monotonic() + 5,
                         config={'worker_memory_mb': 128})

    def test_default_spawn_fixture_completes(self):
        data, config = inputs(); config.pop('process_start_method', None)
        config['max_trials'] = 1; config['max_improvements'] = 0
        with tempfile.TemporaryDirectory() as tmp:
            state = run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=Path(tmp) / 'campaign')
        self.assertEqual(state['attempts'][0]['status'], 'evaluated', state['attempts'])
        self.assertEqual(state['resource_enforcement']['runtime'], 'hard_subprocess_deadline')
        self.assertIn(state['resource_enforcement']['process_memory_isolation'], ['enforced_rlimit_as', 'unsupported_platform'])

    def test_provider_rejects_duplicate_and_nonfinite_json(self):
        for payload in ['{"family":"trend","family":"momentum"}', '{"value":NaN}']:
            with tempfile.TemporaryDirectory() as tmp:
                def transport(*args): return {'choices': [{'message': {'content': payload}}]}
                provider = CompatibleProvider(model='fixture', endpoint='https://example.invalid/v1',
                    transport=transport, budget_path=Path(tmp) / 'provider.db', network_opt_in=True,
                    max_calls=1, max_tokens=10000)
                with self.assertRaises(ValidationError): provider.generate({})

    def test_holdout_crash_cannot_be_reconsumed(self):
        from quantlab.research import _run_bounded as real
        data, config = inputs(); config['ranking']['minimum'] = '-100000'
        calls = []
        def interrupted(function, args, **kwargs):
            if function.__name__ == '_evaluate_split':
                name = args[0].manifest['research_split']['name']
                calls.append(name)
                if name == 'holdout': raise KeyboardInterrupt()
            return real(function, args, **kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            with patch('quantlab.research._run_bounded', side_effect=interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    run_campaign(data, config=config, generator=Spy(), output_dir=Path(tmp) / 'campaign')
            with patch('quantlab.research.run_backtest') as forbidden:
                state = run_campaign(data, config=config, generator=Spy(), output_dir=Path(tmp) / 'campaign')
                forbidden.assert_not_called()
            self.assertEqual(state['status'], 'blocked_consumed_holdout')
            self.assertTrue(state['holdout_consumed'])
            self.assertEqual(calls.count('holdout'), 1)

    def test_purge_and_resource_caps(self):
        from quantlab.research import _run_bounded as real
        data, config = inputs(); config['purge_bars'] = 3; config['max_trials'] = 1
        observed = []
        def inspect(function, args, **kwargs):
            if function.__name__ == '_evaluate_split':
                dataset = args[0]
                split = dataset.manifest['research_split']
                observed.append((split['name'], len(dataset.bars)))
                self.assertEqual(len(dataset.bars), split['end'] - split['start'] - 3)
                self.assertEqual(dataset.manifest['data_hash'], content_hash(dataset.bars))
            return real(function, args, **kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            with patch('quantlab.research._run_bounded', side_effect=inspect):
                result = run_campaign(data, config=config, generator=Spy(), output_dir=Path(tmp) / 'campaign')
            self.assertEqual(len(result['attempts']), 1)
            self.assertTrue(observed)
        config['max_bars'] = 10
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValidationError):
            run_campaign(data, config=config, generator=Spy(), output_dir=Path(tmp) / 'campaign')

    def test_runtime_exhaustion_no_generator_call(self):
        data, config = inputs(); config['max_runtime_seconds'] = 1
        spy = Spy()
        with tempfile.TemporaryDirectory() as tmp, patch('quantlab.research.time.monotonic', side_effect=range(100)):
            state = run_campaign(data, config=config, generator=spy, output_dir=Path(tmp) / 'campaign')
        self.assertEqual(state['status'], 'budget_exhausted')
        self.assertEqual(spy.contexts, [])

    def test_provider_failure_consumes_spend_and_retains_receipt(self):
        def failing(*args): raise RuntimeError('failure')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'provider.db'
            kwargs = dict(model='fixture', endpoint='https://example.invalid/v1', transport=failing,
                          budget_path=path, max_calls=1, max_tokens=10000,
                          max_spend='100', cost_per_token='0.01', network_opt_in=True)
            with self.assertRaises(RuntimeError): CompatibleProvider(**kwargs).generate({})
            with self.assertRaises(ValidationError): CompatibleProvider(**kwargs).generate({})
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('SELECT status FROM calls').fetchone()[0], 'failed_or_interrupted')
                self.assertGreater(Decimal(db.execute('SELECT spend FROM budget').fetchone()[0]), 0)

    def test_holdout_changes_do_not_change_selection_or_generator_feedback(self):
        data, config = inputs(); config['ranking']['minimum'] = '-100000'; config['max_improvements'] = 1
        modified = list(data.bars)
        for i in range(config['splits']['oos'][0], len(modified)):
            b = modified[i]
            modified[i] = Bar(b.timestamp, b.end, b.trade_date, b.session, b.contract_id,
                              b.open + 500, b.high + 500, b.low + 500, b.close + 500, b.volume)
        altered = Dataset(tuple(modified), {**data.manifest, 'data_hash': content_hash(tuple(modified))}, dict(data.quality))
        spies = [Spy(), Spy()]
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = run_campaign(data, config=config, generator=spies[0], output_dir=Path(a) / 'campaign')
            second = run_campaign(altered, config=config, generator=spies[1], output_dir=Path(b) / 'campaign')
        self.assertEqual([c['strategy_hash'] for c in first['selected']], [c['strategy_hash'] for c in second['selected']])
        # Split hashes must bind only the split, not an OOS-dependent parent hash.
        self.assertEqual([a['generator_context'] for a in first['attempts']], [a['generator_context'] for a in second['attempts']])


if __name__ == '__main__': unittest.main()

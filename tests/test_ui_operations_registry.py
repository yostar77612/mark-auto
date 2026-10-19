"""Dispatcher contracts and frozen pre-refactor offline results.

Golden normalisation is documented field by field below and in the fixture.
Synthetic data timestamps and hashes remain exact. Exceptions are recorded by
type/message too, so offline consent/proof failures are covered.
The inherited-permission mkdir shim avoids Windows sandbox's mode=0700 ACL
artifact; it changes no application logic or file contents.
"""

import ast
from contextlib import contextmanager
import importlib.util
import inspect
import json
import locale
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import desktop_ui as ui
from quantlab.core import ValidationError, content_hash, to_dict
from quantlab.desktop_runtime import AppPaths
from quantlab.reporting import demo_config, save_dataset, synthetic_dataset, write_json
from tests.test_market import TWSE
from tests.test_walk_forward import inputs, fake_worker


FIXTURES = Path(__file__).parent / 'fixtures'


def golden_observations():
    """B6: ignore only entry metadata; retain all recorded expected values."""
    observations = json.loads((FIXTURES / 'ui_operations_golden.json').read_text(encoding='utf-8'))['observations']
    return {name: {key: value for key, value in entry.items() if key not in {'source', 'review', 'precision'}} for name, entry in observations.items()}


@contextmanager
def old_module():
    """Load the committed pre-refactor source under a disposable module name."""
    # The pre-refactor desktop_ui.py (main at the end of P2-A3) is committed as a fixture so the live
    # old-vs-new comparison does not depend on git history (CI clones are shallow) or on HEAD.
    raw = (FIXTURES / 'desktop_ui_pre_registry.py.txt').read_bytes()
    with workspace() as paths:
        source_file = paths.root / 'old_desktop_ui.py'
        source_file.write_bytes(raw)
        name = '_ui_operations_before_refactor'
        spec = importlib.util.spec_from_file_location(name, source_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            # Source-hash lookups still refer to the unchanged dependency files
            # beside desktop_ui.py; only the loaded module's name is isolated.
            module.__file__ = ui.__file__
            yield module
        finally:
            sys.modules.pop(name, None)


def portable_paths(node):
    """Golden paths were recorded on Windows; CI also runs POSIX. Compare path separators neutrally."""
    if isinstance(node, dict):
        return {key: portable_paths(item) for key, item in node.items()}
    if isinstance(node, list):
        return [portable_paths(item) for item in node]
    if isinstance(node, str) and '<TEMP>' in node:
        return node.replace(chr(92), '/')
    return node


def normalise_observations(observations):
    """Only path-bound identities and measured wall-clock durations vary."""
    raw = json.dumps(observations, ensure_ascii=False, sort_keys=True)
    walk = observations['ui_walk_forward_preview'].get('result', {})
    if 'preview_identity' in walk:
        raw = raw.replace(walk['preview_identity'], '<WALK_ID>')
    replay = observations['ui_paper_replay'].get('result', {}).get('replay', {})
    if 'binding' in replay:
        # Replay order ids are hash([path-derived binding, bar index, leg]);
        # fills append ':fill'. Replace only identities matching that formula,
        # consistently in mapping keys, orders, fills and FIFO lot references.
        for index in range(replay['total_bars']):
            for leg in range(2):
                identity = content_hash([replay['binding'], index, leg])
                raw = raw.replace(identity, '<REPLAY_ORDER_{}_{}>'.format(index, leg))
        raw = raw.replace(replay['binding'], '<REPLAY_ID>')
    value = json.loads(raw)
    for name in ('ui_walk_forward_run', 'ui_walk_forward_read', 'ui_walk_forward_reconcile'):
        result = value[name].get('result', {})
        if 'elapsed_seconds' in result:
            result['elapsed_seconds'] = '<ELAPSED>'
    # Import wall time is metadata, excluded by production from manifest_hash.
    value['ui_import']['result']['manifest']['imported_at'] = '<IMPORTED_AT>'

    # Campaign/receipt elapsed_seconds are actual stopwatch measurements. No
    # other numeric field, deterministic bar timestamp, identity or hash is masked.
    def durations(node):
        if isinstance(node, dict):
            for key, item in node.items():
                if key == 'elapsed_seconds':
                    node[key] = '<ELAPSED>'
                else:
                    durations(item)
        elif isinstance(node, list):
            for item in node:
                durations(item)

    for name in ('campaign_fixture', 'campaign_subscription_fixture', 'ui_analysis_run', 'ui_analysis_read', 'ui_analysis_reconcile'):
        durations(value[name])
    return portable_paths(value)


@contextmanager
def workspace():
    """Fresh process profile and explicit paths; no host credential/ACL access."""
    mkdir = os.mkdir

    def inherited_mkdir(path, mode=0o777, *args, **kwargs):
        return mkdir(path, 0o777 if os.name == 'nt' else mode, *args, **kwargs)

    # Backtest/walk-forward manifests embed platform.python_version() and hash it into result/run/
    # reproducibility hashes; pin it so the recorded (Python 3.13.11) golden is host-independent.
    with patch('platform.python_version', return_value='3.13.11'), patch('os.mkdir', side_effect=inherited_mkdir):
        with tempfile.TemporaryDirectory(prefix='ui-registry-') as folder:
            root = Path(folder)
            profile = root / 'profile'
            local = profile / 'AppData' / 'Local'
            roaming = profile / 'AppData' / 'Roaming'
            for directory in (local, roaming):
                directory.mkdir(parents=True)
            environment = dict(
                USERPROFILE=str(profile),
                HOME=str(profile),
                LOCALAPPDATA=str(local),
                APPDATA=str(roaming),
                HOMEDRIVE=profile.drive,
                HOMEPATH=str(profile)[len(profile.drive) :],
                XDG_CONFIG_HOME=str(roaming),
                XDG_DATA_HOME=str(local),
                TZ='UTC',
                LANG='C',
                LC_ALL='C',
            )

            def prepare_empty_vault(vault):
                # Exercise real file lookup/locking/session logic, without the
                # host's token SID/DACL APIs (which differ in a sandbox).
                vault.directory.resolve().relative_to(root.resolve())
                vault.directory.mkdir(parents=True, exist_ok=True)

            previous_locale = locale.setlocale(locale.LC_ALL)
            try:
                locale.setlocale(locale.LC_ALL, 'C')
                with (
                    patch.dict(os.environ, environment),
                    patch('desktop_chatgpt_auth.DPAPIVault._prepare', prepare_empty_vault),
                    patch('quantlab.desktop_runtime.CredentialVault._crypt', side_effect=AssertionError('credential access forbidden')),
                    patch('desktop_chatgpt_auth.OfficialTransport.request', side_effect=AssertionError('offline fixtures only')),
                ):
                    yield AppPaths(root / 'workspace', root / 'bootstrap').ensure()
            finally:
                locale.setlocale(locale.LC_ALL, previous_locale)


def exercise(execute):
    """Real offline handlers, with the existing bounded-process scoring fixture."""
    with workspace() as paths, patch('socket.socket', side_effect=AssertionError('offline fixtures only')):
        observations = {}

        def call(name, payload, **kwargs):
            events = []
            operation = kwargs.pop('operation', name)
            try:
                result = execute(operation, payload, paths, emit=lambda kind, **data: events.append([kind, data]), **kwargs)
                value = {'result': to_dict(result), 'events': events}
            except Exception as exc:
                value = {'exception': type(exc).__name__, 'message': str(exc), 'events': events}
                result = None
            observations[name] = value
            return result

        call('ui_demo', {'bars': 240})
        reports = call('ui_backtest', {'config': to_dict(demo_config()), 'family': 'trend'})
        if reports:
            result = reports['reports'][0]['result']
            call('ui_compare', {'results': [result]})
            call('ui_select', {'result': result})
        policy = {
            'contract_id': 'TAIFEX:TMF:202601',
            'risk_sessions': [
                {'open': '2026-01-05T00:45:00Z', 'end': '2026-01-05T04:45:00Z', 'trade_date': '2026-01-05', 'session': 'day', 'source': 'synthetic fixture'}
            ],
            'margin_schedule': [{'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'synthetic-v1'}],
        }
        snapshot = {'account_id': 'fixture', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}}
        call('ui_paper_snapshot', {'policy': policy})
        call('ui_paper_reconcile', {'snapshot': snapshot})
        call('ui_paper_kill', {})
        selection = ui.read_json(paths.state / 'selection.json')
        now = '2026-01-05T00:46:00Z'
        call(
            'ui_paper_submit',
            {
                'reconcile_confirmed': True,
                'snapshot': snapshot,
                'intent': {
                    'client_order_id': 'offline-order',
                    'strategy_hash': selection['strategy_hash'],
                    'contract_id': policy['contract_id'],
                    'side': 'buy',
                    'quantity': 1,
                    'order_type': 'market',
                    'created_at': now,
                },
                'quote': {
                    'account_id': 'fixture',
                    'contract_id': policy['contract_id'],
                    'timestamp': now,
                    'price': '20000',
                    'trade_date': '2026-01-05',
                    'session_open': policy['risk_sessions'][0]['open'],
                    'session_end': policy['risk_sessions'][0]['end'],
                    'margin_per_contract': '100000',
                },
                'now': now,
            },
        )
        call('ui_paper_cancel', {'order_id': 'offline-order', 'now': now})
        call('ui_paper_replay', {'reconcile_confirmed': True, 'snapshot': ui.read_json(paths.state / 'paper_snapshot.json'), 'max_bars': 100})
        call('ui_disable', {})
        local = paths.root / 'official.json'
        local.write_bytes(TWSE)
        call('ui_market_refresh', {'local_path': str(local), 'provider': 'twse', 'format': 'json'})
        from desktop import _history_smoke_fixture

        _, history_payload = _history_smoke_fixture(paths.root)
        call('history_import', history_payload, operation='ui_market_refresh')
        calendar = paths.root / 'calendar.json'
        from tests.test_data import cal

        write_json(calendar, {'sessions': cal().sessions, 'version': 'synthetic-v1'})
        imported = paths.root / 'ticks.csv'
        imported.write_bytes((FIXTURES / 'data_synthetic_taifex.csv').read_bytes())
        call('ui_import', {'calendar': str(calendar), 'kind': 'synthetic_taifex_ticks', 'path': str(imported), 'encoding': 'utf-8'})
        call('ui_refresh', {'network_opt_in': False})
        from quantlab.research import demo_campaign_config

        config = demo_campaign_config(synthetic_dataset(240), demo_config())
        config['max_improvements'] = 0
        save_dataset(synthetic_dataset(240), paths.state / 'dataset.json')
        call('ui_campaign', {'config': config, 'provider': {'mode': 'manual'}, 'manual_export': str(paths.root / 'request.json')})
        with patch('quantlab.research._run_bounded', side_effect=lambda f, args, **kw: {'value': f(*args), 'memory_limit_enforced': False}):
            call('campaign_fixture', {'config': config, 'provider': {'mode': 'fixture'}}, operation='ui_campaign')
        call('ui_chatgpt_auth', {'request': {'request_id': 1, 'action': 'restore'}})
        call('ui_chatgpt_usage', {'registration': 'a' * 32})
        call('ui_chatgpt_reconcile', {})
        from tests.test_chatgpt_plan import MockTransport, SYNTHETIC_PROVENANCE

        options = dict(
            mode='chatgpt_plan',
            registration='b' * 32,
            model='fixture-model',
            max_calls=1,
            timeout_seconds=30,
            network_opt_in=False,
            included_usage_policy_confirmed=False,
            paid_api_fallback=False,
        )
        # Separate workspace and durable controls: the preceding campaign has
        # consumed its holdout once. Never reset or bypass that ledger.
        original_paths = paths
        paths = AppPaths(paths.root / 'subscription-workspace', paths.root / 'subscription-bootstrap').ensure()
        subscription_data = synthetic_dataset(241)
        save_dataset(subscription_data, paths.state / 'dataset.json')
        subscription_config = demo_campaign_config(subscription_data, demo_config())
        subscription_config.update(families=['trend'], max_trials=1, max_improvements=0)
        MockTransport.requests = []
        MockTransport.events = None
        with (
            patch('desktop_chatgpt_provider.implementation_provenance', return_value=SYNTHETIC_PROVENANCE),
            patch('desktop_chatgpt_provider.PlanHTTPTransport', MockTransport),
            patch('quantlab.research._run_bounded', side_effect=lambda f, args, **kw: {'value': f(*args), 'memory_limit_enforced': False}),
        ):
            _, binding = ui.plan_provider(paths, subscription_data, subscription_config, options, for_usage=True)
            call(
                'campaign_subscription_fixture',
                {
                    'config': to_dict(subscription_config),
                    'provider': {**options, 'network_opt_in': True, 'included_usage_policy_confirmed': True, 'expected_binding': binding},
                },
                operation='ui_campaign',
            )
            call(
                'ui_chatgpt_reconcile',
                {'config': to_dict(subscription_config), 'provider': options, 'binding': binding, 'stopped_job_id': 'offline'},
                descendants_stopped=True,
            )
        paths = original_paths
        from tests.test_research_analysis import source, PROVENANCE, AnalysisWire
        from tests.test_desktop_analysis import request_for

        data, state, folder = source(paths.state / 'campaigns')
        request = request_for(paths, data, state, folder)
        AnalysisWire.requests = []
        AnalysisWire.failure = AnalysisWire.mutate = None
        with (
            patch('quantlab.research_analysis._run_bounded', side_effect=lambda f, args, **kw: {'value': f(*args)}),
            patch('desktop_chatgpt_provider.implementation_provenance', return_value=PROVENANCE),
            patch('desktop_chatgpt_provider.PlanHTTPTransport', AnalysisWire),
        ):
            preview = call('ui_analysis_preview', {'request': request})
            if preview:
                call(
                    'ui_analysis_run',
                    {
                        'request': request,
                        'expected_analysis_id': preview['analysis_id'],
                        'expected_plan_hash': content_hash(preview['plan']),
                        'user_confirmed': True,
                        'network_opt_in': True,
                        'included_usage_policy_confirmed': True,
                    },
                )
                call('ui_analysis_read', {'analysis_id': preview['analysis_id']})
                call(
                    'ui_analysis_reconcile',
                    {'analysis_id': preview['analysis_id'], 'registration': 'a' * 32, 'stopped_job_id': 'offline'},
                    descendants_stopped=True,
                )
        data, plan = inputs(process_start_method='spawn')
        original_paths = paths
        paths = AppPaths(paths.root / 'walk-workspace', paths.root / 'walk-bootstrap').ensure()
        save_dataset(data, paths.state / 'dataset.json')
        preview = call('ui_walk_forward_preview', {'plan': to_dict(plan)})
        if preview:
            with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
                call('ui_walk_forward_run', {'plan': preview['plan'], 'preview_identity': preview['preview_identity']})
            call('ui_walk_forward_read', {'reference': preview['preview_identity']})
            call('ui_walk_forward_reconcile', {'reference': preview['preview_identity'], 'stopped_job_id': 'offline'}, descendants_stopped=True)
        paths = original_paths
        backup = paths.root.parent / 'offline.zip'
        call('ui_backup_create', {'path': str(backup)})
        call('ui_backup_restore', {'path': str(backup)})
        # The prefix includes both workspace and bootstrap, in native and JSON paths.
        raw = json.dumps(observations, ensure_ascii=False, sort_keys=True)
        # CI runners expose the same temp directory as a short (8.3) name and as the resolved long name;
        # replace every spelling of the temp prefix (native, resolved, forward-slash), longest first.
        prefix = paths.root.parent
        spellings = {str(prefix), str(prefix.resolve()), os.path.realpath(prefix)}
        spellings |= {value.replace(chr(92), '/') for value in spellings}
        for value in sorted(spellings, key=len, reverse=True):
            raw = raw.replace(json.dumps(value)[1:-1], '<TEMP>')
        return normalise_observations(json.loads(raw))


class RegistryTests(unittest.TestCase):
    def test_all_scenarios_ignore_host_profile_and_remembered_login(self):
        expected = portable_paths(golden_observations())
        original_environment = dict(os.environ)
        with old_module() as old, workspace() as host:
            from desktop_chatgpt_auth import DPAPIVault

            vault = DPAPIVault(str(host.bootstrap))
            vault.directory.mkdir(parents=True)
            sentinel = b'synthetic remembered login; never decrypt'
            host_environment = {key: os.environ[key] for key in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA')}
            original_read = Path.read_bytes

            def guarded_read(path):
                self.assertFalse(path.is_relative_to(host.root.parent), 'read simulated host profile or bootstrap')
                return original_read(path)

            for remembered in (False, True):
                if remembered:
                    vault.path.write_bytes(sentinel)
                    vault.host_marker.write_bytes(b'synthetic host marker')
                    # Cover profile-based discovery as well as explicit bootstrap.
                    profile_vault = Path(os.environ['LOCALAPPDATA']) / 'credentials' / 'accounts.dpapi'
                    profile_vault.parent.mkdir(parents=True)
                    profile_vault.write_bytes(sentinel)
                with self.subTest(remembered=remembered), patch.object(Path, 'read_bytes', guarded_read):
                    results = []
                    for execute in (old.execute_ui_operation, ui.execute_ui_operation):
                        results.append(exercise(execute))
                        self.assertEqual({key: os.environ[key] for key in host_environment}, host_environment)
                    self.assertEqual(results[1], results[0])
                    if sys.platform == 'win32':
                        # The golden (hashes of CRLF working-copy sources, Windows path spellings) was
                        # recorded on Windows; other platforms rely on the live old-vs-new equality above.
                        self.assertEqual(results[0], expected)
                if remembered:
                    self.assertEqual(vault.path.read_bytes(), sentinel)
                    self.assertEqual(profile_vault.read_bytes(), sentinel)
        self.assertEqual(dict(os.environ), original_environment)

    def test_registry_exact_allowlist_and_callable_handlers(self):
        self.assertEqual(set(ui._UI_OPERATION_HANDLERS), ui.UI_OPERATIONS)
        self.assertTrue(all(callable(handler) for handler in ui._UI_OPERATION_HANDLERS.values()))
        self.assertEqual(len(set(ui._UI_OPERATION_HANDLERS.values())), len(ui.UI_OPERATIONS))

    def test_dispatcher_and_handlers_at_most_sixty_lines(self):
        functions = [ui.execute_ui_operation, *ui._UI_OPERATION_HANDLERS.values()]
        for function in functions:
            with self.subTest(function=function.__name__):
                node = ast.parse(inspect.getsource(function)).body[0]
                self.assertLessEqual(node.end_lineno - node.lineno + 1, 60)

    def test_unknown_operations_fail_before_dispatch_or_workspace_access(self):
        expected = ui.ui_text('ui.execute_ui_operation.text_1')
        with patch.dict(ui._UI_OPERATION_HANDLERS, {'': unittest.mock.Mock(), 'ui_unknown': unittest.mock.Mock()}):
            with patch.object(ui, '_root', side_effect=AssertionError('workspace accessed')):
                for operation in ('', 'ui_unknown', 'backtest', 'demo', 'ui_analysis_unknown', None):
                    with self.subTest(operation=operation):
                        with self.assertRaises(ValidationError) as caught:
                            ui.execute_ui_operation(operation, {}, None)
                        self.assertEqual(str(caught.exception), expected)
            ui._UI_OPERATION_HANDLERS[''].assert_not_called()
            ui._UI_OPERATION_HANDLERS['ui_unknown'].assert_not_called()

    def test_operation_coverage_and_golden_parity(self):
        observed = exercise(ui.execute_ui_operation)
        # Explicit operation -> test callable coverage table, including guarded paths.
        coverage = {operation: self.test_operation_coverage_and_golden_parity for operation in observed if operation in ui.UI_OPERATIONS}
        self.assertEqual(set(coverage), ui.UI_OPERATIONS)
        self.assertTrue(all(callable(test) for test in coverage.values()))
        expected = json.loads((FIXTURES / 'ui_operations_golden.json').read_text(encoding='utf-8'))
        expected['observations'] = portable_paths(golden_observations())
        self.assertEqual(set(expected['offline_limits']), {'ui_refresh'})
        with old_module() as old:
            legacy = exercise(old.execute_ui_operation)
        self.assertEqual(set(observed), set(expected['observations']))
        for operation in observed:
            with self.subTest(operation=operation):
                self.assertEqual(observed[operation], legacy[operation])
                if sys.platform == 'win32':
                    self.assertEqual(legacy[operation], expected['observations'][operation])
                    self.assertEqual(observed[operation], expected['observations'][operation])
                if operation not in expected['offline_limits']:
                    self.assertIn('result', observed[operation], 'Offline operation must succeed')
        for name in ('campaign_fixture', 'campaign_subscription_fixture'):
            result = observed[name]['result']
            self.assertEqual(result['status'], 'completed')
            self.assertTrue(result['attempts'])
            self.assertTrue(all(row['status'] == 'evaluated' for row in result['attempts']))
        self.assertEqual(observed['ui_paper_submit']['result']['account']['orders']['offline-order']['status'], 'accepted')
        self.assertEqual(observed['ui_paper_cancel']['result']['account']['orders']['offline-order']['status'], 'cancel_pending')
        self.assertGreater(observed['ui_paper_replay']['result']['replay']['new_fills'], 0)
        self.assertEqual(observed['ui_walk_forward_run']['result']['status'], 'completed')
        self.assertEqual(observed['ui_analysis_run']['result']['record']['status'], 'completed')

    def test_public_names_unchanged(self):
        expected = json.loads((FIXTURES / 'desktop_ui_public_names.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(name for name in vars(ui) if not name.startswith('_')), expected)

"""Offline security regressions. Never import the legacy package or its dependencies.

Only audited AST-selected definitions execute with inert injected dependencies.
These are boundary tests, not legacy integration verification.
"""
import ast
import contextlib
import io
import logging
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def tree(path):
    return ast.parse((ROOT / path).read_text(encoding='utf-8'), filename=path)


def extract(path, names, globals_=None, class_name=None):
    nodes = tree(path).body
    if class_name:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == class_name).body
    selected = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names]
    assert len(selected) == len(names)
    namespace = dict(globals_ or {})
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] + selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), path, 'exec'), namespace)
    return namespace


class LegacySecurityTests(unittest.TestCase):
    def test_startup_disabled_before_imports(self):
        for path in ('trader/__init__.py', 'gui.py'):
            first = tree(path).body[0]
            self.assertIsInstance(first, ast.Raise)
        module = tree('run.py')
        imports = [n for n in module.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([n.module for n in imports], ['argparse'])
        reference = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == '_disabled_legacy_reference')
        self.assertIsInstance(reference.body[0], ast.Raise)

    def test_cli_help_and_execution_gate_without_services(self):
        from argparse import ArgumentParser
        from unittest.mock import patch
        main = extract('run.py', ['main'], {'ArgumentParser': ArgumentParser})['main']
        for args, code in [(['run.py', '--help'], 0), (['run.py'], 2), (['run.py', '--task', 'auto_trader'], 2)]:
            with patch('sys.argv', args), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, code)

    def test_no_tls_bypass(self):
        for path in ROOT.joinpath('trader').rglob('*.py'):
            source = path.read_text()
            self.assertNotIn('_create_unverified_context', source)
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Call):
                    self.assertFalse(any(k.arg == 'verify' and isinstance(k.value, ast.Constant) and k.value.value is False for k in node.keywords))

    def test_broker_default_is_inert_and_live_rejected(self):
        broker_sdk = Mock()
        ns = extract('trader/config.py', ['DisabledBroker', 'create_api'], {'sj': broker_sdk})
        broker = ns['create_api']()
        for value in (False, None, 0, 1, 'Simulation', 'Live'):
            with self.assertRaises(ValueError):
                ns['create_api'](value)
        for method in ('login', 'place_order', 'place_comboorder', 'activate_ca'):
            with self.assertRaises(RuntimeError):
                getattr(broker, method)
        self.assertEqual(broker_sdk.mock_calls, [])

    def test_no_broker_order_submission_calls_remain(self):
        for path in ROOT.joinpath('trader').rglob('*.py'):
            for n in ast.walk(ast.parse(path.read_text())):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'API':
                    self.assertNotIn(n.func.attr, ('place_order', 'place_comboorder'))

    def test_order_gate_rejects_before_accessing_content(self):
        for name in ('place_order', 'place_combo_order'):
            for value in (False, None, 0, 1, 'Simulation'):
                data = SimpleNamespace(Account=SimpleNamespace(Simulate=value))
                method = extract('trader/utils/orders.py', [name], {'TradeData': data}, class_name='OrderTool')[name]
                with self.assertRaises(RuntimeError):
                    method(None, None)

    def permission(self, chats, users, chat_id=-123, user_id=456):
        method = extract('trader/utils/bot.py', ['_check_permission'], {'WHITELIST': chats, 'USER_WHITELIST': users}, class_name='TelegramBot')['_check_permission']
        return method(None, SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), effective_user=SimpleNamespace(id=user_id), effective_message=Mock()))

    def test_telegram_requires_both_numeric_identities(self):
        self.assertTrue(self.permission({-123}, {456}))
        for chats, users in ((set(), {456}), ({-123}, set()), ({999}, {456}), ({-123}, {999})):
            self.assertFalse(self.permission(chats, users))
        for chat, user in ((None, 456), (-123, None), ('-123', 456), (-123, '456'), (True, True)):
            self.assertFalse(self.permission({-123, 1}, {456, 1}, chat, user))
        source = (ROOT / 'trader/utils/bot.py').read_text()
        self.assertNotIn('[TEXT MESSAGE]', source)
        self.assertNotIn('TELEGRAM_USER_WHITELIST', source)

    def test_telegram_invalid_allowlists_fail_closed(self):
        parse = extract('trader/utils/bot.py', ['_numeric_ids'])['_numeric_ids']
        self.assertEqual(parse({'account': '-123'}), {-123})
        self.assertEqual(parse(['456'], positive=True), {456})
        for values in (None, '', '456', [], [456, 'bad'], [True], ['0'], [' 456'], ['４５６'], [1.0]):
            self.assertFalse(parse(values, positive=True))
        self.assertFalse(parse([-123], positive=True))

    def test_telegram_every_control_handler_checks_permission_first(self):
        bot = next(n for n in tree('trader/utils/bot.py').body if isinstance(n, ast.ClassDef) and n.name == 'TelegramBot')
        handlers = [n for n in bot.body if isinstance(n, ast.AsyncFunctionDef) and (n.name.startswith('cmd_') or n.name == 'handle_text')]
        self.assertEqual(len(handlers), 8)
        for handler in handlers:
            self.assertIsInstance(handler.body[0], ast.If)
            self.assertIn('_check_permission(update)', ast.unparse(handler.body[0].test))
            self.assertIsInstance(handler.body[0].body[0], ast.Return)

    def test_telegram_invalid_configuration_prevents_startup(self):
        for chats, users in ((set(), {456}), ({-123}, set()), (set(), set())):
            method = extract('trader/utils/bot.py', ['__init__'], {'WHITELIST': chats, 'USER_WHITELIST': users, 'logging': logging}, class_name='TelegramBot')['__init__']
            fake = SimpleNamespace()
            with self.assertLogs(level='WARNING'):
                method(fake, 'account')
            self.assertIsNone(fake.app)

    def test_paths_reject_traversal_and_dot_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            fn = extract('trader/utils/runtime.py', ['_account_dir'], {'re': re, 'RUNTIME_ROOT': Path(directory)})['_account_dir']
            self.assertEqual(fn('account_1'), Path(directory) / 'account_1')
            for value in (None, '', '.', '..', '../escape', '/tmp/escape', 'a/b', 'a\\b', 'a..b', 'a.b', 'a'*65):
                with self.assertRaises(ValueError):
                    fn(value)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['account_1'])

    def test_untrusted_pickle_and_zip_ingress_disabled(self):
        for name in ('query', 'query_keys'):
            fn = extract('trader/utils/database/redis.py', [name], class_name='RedisTools')[name]
            with self.assertRaises(RuntimeError):
                fn(None, 'untrusted')
        source = (ROOT / 'trader/utils/file.py').read_text()
        self.assertNotIn('pd.read_pickle(', source)
        source = (ROOT / 'trader/utils/database/redis.py').read_text()
        self.assertNotIn('pickle.loads(', source)
        crawler_tree = tree('trader/utils/crawler.py')
        method = next(n for n in ast.walk(crawler_tree) if isinstance(n, ast.FunctionDef) and n.name == 'get_FuturesTickData')
        self.assertIsInstance(method.body[1], ast.Raise)
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ('get', 'extractall') for n in ast.walk(method)))

    def test_database_diagnostics_never_render_credentials(self):
        class SecretError(Exception):
            def __str__(self):
                raise AssertionError('Exception payload must never be rendered')
        method = extract('trader/utils/database/sql.py', ['__init__'], {'logging': logging, 'DBConfig': SimpleNamespace(ENGINE='mysql', HAS_DB=False)}, class_name='SQLDatabase')['__init__']
        fake = SimpleNamespace(connect=Mock(side_effect=SecretError('mysql://user:synthetic-secret@host/db')))
        with self.assertLogs(level='WARNING') as logs:
            method(fake)
        self.assertNotIn('synthetic-secret', '\n'.join(logs.output))
        for node in ast.walk(tree('trader/utils/database/sql.py')):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'logging':
                self.assertNotIn('sql_connect', ast.unparse(node))
                self.assertNotEqual(node.func.attr, 'exception')


if __name__ == '__main__':
    unittest.main()

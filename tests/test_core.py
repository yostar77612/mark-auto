import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
from quantlab.core import (Instrument, Bar, CostSpec, Fill, BacktestConfig, ValidationError,
                           canonical_json, content_hash, to_dict)


class CoreTests(unittest.TestCase):
    def test_canonical(self):
        x = {'b': D('10.00'), 'a': datetime(2026, 10, 8, tzinfo=timezone.utc)}
        self.assertEqual(canonical_json(x), '{"a":"2026-10-08T00:00:00Z","b":"10.00"}')
        self.assertEqual(content_hash(x), content_hash(dict(reversed(list(x.items())))))
        self.assertEqual(to_dict(Instrument('TAIFEX:TMF:202610'))['multiplier'], '10')
        for value in (D('NaN'), float('inf'), {1: 'bad'}, datetime(2026, 10, 8)):
            with self.assertRaises(ValidationError):
                canonical_json(value)

    def test_invalid_instrument(self):
        for value in ('TMF', 'TAIFEX:TMF:202613', 'TAIFEX:TX:202610'):
            with self.assertRaises(ValidationError):
                Instrument(value)
        with self.assertRaises(ValidationError):
            Instrument('TAIFEX:TMF:202610', multiplier=D('50'))

    def test_prices_and_timezone(self):
        start = datetime(2026, 10, 8, tzinfo=timezone.utc)
        args = [start, start + timedelta(minutes=1), '2026-10-08', 'day', 'TAIFEX:TMF:202610', D('20000'), D('20010'), D('19990'), D('20005'), 3]
        Bar(*args)
        for index, value in ((0, start.replace(tzinfo=None)), (5, D('20000.5')), (6, D('19999')), (9, True), (9, -1)):
            modified = list(args); modified[index] = value
            with self.assertRaises(ValidationError):
                Bar(*modified)

    def test_costs_mandatory(self):
        cost = CostSpec(D('15'), D('0.00002'), 1, 'none', '2024-07-29', 'test')
        BacktestConfig(D('100000'), cost)
        for args in ((D('-1'), D('0'), 0, 'none', '2024-07-29', 'x'),
                     (D('1'), D('0'), True, 'none', '2024-07-29', 'x'),
                     (D('1'), D('0'), 0, '', '2024-07-29', 'x')):
            with self.assertRaises(ValidationError):
                CostSpec(*args)
        with self.assertRaises(ValidationError):
            BacktestConfig(D('1000'), None)

    def test_fill_rejects_half_tick_and_boolean_quantity(self):
        args = ['f', 'o', datetime(2026, 10, 8, tzinfo=timezone.utc), 'TAIFEX:TMF:202610', 'buy', 1, D('20000'), D('15'), D('4')]
        Fill(*args)
        for index, value in ((5, True), (6, D('20000.5'))):
            modified = list(args); modified[index] = value
            with self.assertRaises(ValidationError):
                Fill(*modified)

    def test_import_has_no_broker_or_network_dependencies(self):
        import ast
        from pathlib import Path
        package = Path(__file__).parents[1] / 'quantlab'
        for filename in ('__init__.py', 'core.py', 'data.py'):
            tree = ast.parse((package / filename).read_text(encoding='utf-8'))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): imports.extend(n.name for n in node.names)
                elif isinstance(node, ast.ImportFrom): imports.append(node.module or '')
            self.assertFalse(any(i.split('.')[0] in ('trader', 'shioaji', 'requests', 'httpx', 'socket', 'urllib') for i in imports), filename)

    def test_nested_records_immutable_detached_and_copyable(self):
        import copy
        from quantlab.core import StrategySpec, Dataset, BacktestResult
        parameters = {'fast': 2, 'nested': [{'x': 1}]}
        spec = StrategySpec('id', 'trend', parameters, {})
        before = content_hash(spec)
        parameters['nested'][0]['x'] = 99
        parameters['fast'] = 3
        self.assertEqual(content_hash(spec), before)
        for action in (lambda: spec.parameters.update({'fast': 4}),
                       lambda: spec.parameters['nested'].append(2),
                       lambda: spec.parameters['nested'][0].__setitem__('x', 2)):
            with self.assertRaises(TypeError): action()
        self.assertEqual(content_hash(copy.deepcopy(spec)), before)
        exported = to_dict(spec); exported['parameters']['fast'] = 8
        self.assertEqual(spec.parameters['fast'], 2)
        dataset = Dataset((), {'nested': {'x': 1}}, {'errors': []})
        with self.assertRaises(TypeError): dataset.manifest['nested']['x'] = 2
        with self.assertRaises(TypeError): dataset.quality['errors'].append('bad')
        result = BacktestResult({}, (), (), ({'x': [1]},), (), {}, (), ())
        with self.assertRaises(TypeError): result.ledger[0]['x'].append(2)

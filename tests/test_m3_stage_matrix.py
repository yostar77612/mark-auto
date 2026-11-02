"""D6 intake matrix: no synthetic fixture is a production qualification."""

import unittest

from quantlab.trading.application.candidate_intake import _configuration
from quantlab.trading.domain.models import HoldingKind
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.build import synthetic_catalog
from tests.test_m3_candidate_intake import request


class MatrixTests(unittest.TestCase):
    def test_kind_instrument_interval_cross_product(self):
        class EmptyService:
            records = ()

        instruments = synthetic_catalog().instruments
        checked = 0
        for kind in HoldingKind:
            for spec in instruments:
                for interval in ('1m', '5m', '1d', '15m'):
                    req = request(holding_kind=kind, instrument_rule=spec.instrument_id, bar_interval=interval)
                    allowed = kind is HoldingKind.INTRADAY and ('TMF:' in spec.instrument_id) and interval in ('1m', '5m')
                    with self.subTest(kind=kind, instrument=spec.instrument_id, interval=interval):
                        if allowed:
                            _configuration(req, spec, EmptyService())
                        else:
                            with self.assertRaises(DomainError):
                                _configuration(req, spec, EmptyService())
                    checked += 1
        self.assertEqual(checked, len(HoldingKind) * len(instruments) * 4)


class ApplicationSafetyTests(unittest.TestCase):
    def test_owned_services_have_no_broker_or_ai_dependency(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for name in ('candidate_intake', 'signal_executor', 'signal_research', 'promotion_service', 'auto_strategy_views'):
            tree = ast.parse((root / 'quantlab/trading/application' / (name + '.py')).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn('assistant', node.module or '')
                    self.assertNotIn('adapters', node.module or '')
                    self.assertNotIn('runtime', node.module or '')
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, ('place_order', 'update_order', 'cancel_order', 'submit'))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertNotIn(node.name, ('approve_live', 'approve_live_intent'))

"""Adversarial dependency gate checks and immutable v1 producer compatibility."""

from hashlib import sha256
from pathlib import Path
import subprocess
import unittest

from tools.check_trading_architecture import check_source, scan

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '4095c3e9fdd2e91f1423d6d1bf76466834cdb417'
LOCKED = (
    'quantlab/research.py',
    'quantlab/provider.py',
    'quantlab/core.py',
    'quantlab/strategies.py',
    'quantlab/backtest.py',
    'quantlab/data.py',
    'desktop_chatgpt_auth.py',
    'desktop_chatgpt_provider.py',
    'quantlab/saved_candidate_pool.py',
    'tests/fixtures/lb_b10_legacy_journal.json',
)


class TradingArchitectureTests(unittest.TestCase):
    def test_new_live_domain_module_cannot_import_outer_layers(self) -> None:
        for source, target in (
            ('from ..application.performance import unrealized_liquidation', 'quantlab.trading.application.performance.unrealized_liquidation'),
            ('import PySide6', 'PySide6'),
            ('import shioaji', 'shioaji'),
        ):
            with self.subTest(source=source):
                findings = check_source(source, 'quantlab/trading/domain/live_bars.py')
                self.assertEqual(tuple((finding.rule, finding.target) for finding in findings), (('forbidden-dependency', target),))

    def test_repository_layers_have_no_forbidden_dependencies(self) -> None:
        self.assertEqual(scan(ROOT), ())

    def test_domain_rejects_ui_sdk_storage_and_application(self) -> None:
        for source in (
            'from PySide6.QtCore import QObject',
            'import shioaji',
            'import sqlite3',
            'from ..application.engine import TradingEngine',
            'from quantlab.trading import adapters',
            'from quantlab import paper',
            'import ctypes',
            'open("ledger.sqlite3", "rb")',
            'from pathlib import Path',
            'from ..runtime import build',
        ):
            with self.subTest(source=source):
                self.assertTrue(check_source(source, 'quantlab/trading/domain/subject.py'))

    def test_application_ports_and_adapter_boundaries(self) -> None:
        for path, source in (
            ('quantlab/trading/application/subject.py', 'from ..adapters.simulated import SimulatedBroker'),
            ('quantlab/trading/application/subject.py', 'from sqlite3 import connect'),
            ('quantlab/trading/ports/subject.py', 'from ..application import engine'),
            ('quantlab/trading/ports/subject.py', 'from ..runtime import build'),
            ('quantlab/trading/adapters/subject.py', 'from desktop_app.features.trading.window import TradingWindow'),
            ('quantlab/trading/adapters/subject.py', 'from ..application.engine import TradingEngine'),
        ):
            with self.subTest(path=path, source=source):
                self.assertTrue(check_source(source, path))

    def test_presentation_can_use_only_public_contracts_and_model_values(self) -> None:
        for source in (
            'import shioaji',
            'import sqlite3',
            'from quantlab.trading.domain.risk import RiskService',
            'from quantlab.trading.application.engine import TradingEngine',
            'from quantlab.trading.runtime import build',
            'from quantlab.trading.ports.storage import Journal',
        ):
            with self.subTest(source=source):
                self.assertTrue(check_source(source, 'desktop_app/features/trading/subject.py'))
        self.assertEqual(
            check_source(
                'from quantlab.trading.application.contracts import UiState\nfrom quantlab.trading.domain.models import Market\nfrom .widgets import label\nfrom PySide6.QtWidgets import QLabel',
                'desktop_app/features/trading/subject.py',
            ),
            (),
        )

    def test_dynamic_imports_aliases_and_known_getattr_cannot_hide_dependencies(self) -> None:
        for source in (
            'import importlib\nimportlib.import_module("quantlab.trading.adapters.simulated")',
            'from importlib import import_module as loader\nloader("quantlab.trading.application.engine")',
            'import importlib as il\nloader = il.import_module\nloader("sqlite3")',
            'import importlib\ngetattr(importlib, "import_module")("sqlite3")',
            '__import__("sqlite3")',
            'import builtins as b\nb.__import__("sqlite3")',
            'import importlib\nimportlib.import_module("quantlab." + "trading.adapters")',
            'import importlib\nimportlib.import_module("..adapters", __package__)',
            'import importlib\nimportlib.import_module(external_module_name)',
            'import quantlab\ngetattr(quantlab, "paper")',
        ):
            with self.subTest(source=source):
                self.assertTrue(check_source(source, 'quantlab/trading/domain/subject.py'))

    def test_relative_own_layer_type_checking_and_composition_are_explicit(self) -> None:
        self.assertEqual(check_source('from pathlib import Path\ndef location(path: Path) -> Path:\n    return path', 'quantlab/trading/ports/location.py'), ())
        self.assertTrue(check_source('from pathlib import Path\nPath("ledger").read_bytes()', 'quantlab/trading/ports/location.py'))
        self.assertEqual(
            check_source('from .models import Market\nfrom ..domain.validation import DomainError\nimport decimal', 'quantlab/trading/domain/subject.py'), ()
        )
        self.assertEqual(check_source('from .models import Market', 'quantlab/trading/domain/__init__.py'), ())
        self.assertTrue(check_source('from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import shioaji', 'quantlab/trading/domain/subject.py'))
        self.assertEqual(
            check_source(
                'from ..application.engine import TradingEngine\nfrom ..adapters.simulated import SimulatedBroker', 'quantlab/trading/runtime/build.py'
            ),
            (),
        )

    def test_v1_sources_profiles_and_frozen_journal_bytes_match_baseline_checkout(self) -> None:
        # Git applies the SAME platform checkout filters to the historical blob.
        # Windows CRLF checkouts are compared byte-for-byte to historical CRLF,
        # while canonical Git blob identity is independently checked below.
        for path in LOCKED:
            with self.subTest(path=path):
                baseline = subprocess.check_output(['git', 'cat-file', '--filters', f'{BASELINE}:{path}'], cwd=ROOT)
                current = (ROOT / path).read_bytes()
                self.assertEqual(sha256(current).digest(), sha256(baseline).digest())
                expected_blob = subprocess.check_output(['git', 'rev-parse', f'{BASELINE}:{path}'], cwd=ROOT).strip()
                current_blob = subprocess.check_output(['git', 'hash-object', '--stdin', '--path', path], input=current, cwd=ROOT).strip()
                self.assertEqual(current_blob, expected_blob)


if __name__ == '__main__':
    unittest.main()

"""Explicit optional import/version checks without a broker SDK client."""

import builtins
import importlib
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from quantlab.trading.adapters.shioaji import sdk_loader
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BROKER_SDK_VERSION


class SDKLoaderTests(unittest.TestCase):
    def test_importing_loader_does_not_import_sdk(self):
        original_import = builtins.__import__
        sdk_imports = []

        def inspect_import(name, *args, **kwargs):
            if name == 'shioaji' or name.startswith('shioaji.'):
                sdk_imports.append(name)
                raise AssertionError('SDK must remain unloaded on module import')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=inspect_import):
            importlib.reload(sdk_loader)
        self.assertEqual(sdk_imports, [])

    def test_explicit_load_requires_exact_version_without_constructing_client(self):
        module = ModuleType('shioaji')
        module.__version__ = BROKER_SDK_VERSION
        module.Shioaji = Mock(side_effect=AssertionError('no SDK client construction'))
        with patch.dict(sys.modules, {'shioaji': module}):
            self.assertIs(sdk_loader.load_pinned_sdk(), module)
        module.Shioaji.assert_not_called()

    def test_missing_sdk_is_a_sanitized_capability_error(self):
        with patch.dict(sys.modules, {'shioaji': None}), self.assertRaises(DomainError) as captured:
            sdk_loader.load_pinned_sdk()
        self.assertEqual(captured.exception.code, 'capability_missing')
        self.assertEqual(captured.exception.detail, 'optional pinned broker SDK is unavailable')

    def test_missing_wrong_or_non_string_version_is_rejected_without_client(self):
        module = ModuleType('shioaji')
        module.Shioaji = Mock(side_effect=AssertionError('no SDK client construction'))
        for version in (None, '1.7.8', '1.7.9+unreviewed', 1.79):
            with self.subTest(version=version):
                if version is not None:
                    module.__version__ = version
                elif hasattr(module, '__version__'):
                    del module.__version__
                with patch.dict(sys.modules, {'shioaji': module}), self.assertRaises(DomainError) as captured:
                    sdk_loader.load_pinned_sdk()
                self.assertEqual(captured.exception.code, 'capability_missing')
                self.assertEqual(captured.exception.detail, 'unsupported broker SDK version')
        module.Shioaji.assert_not_called()

    def test_repeated_explicit_load_does_not_cache_an_unverified_replacement(self):
        module = ModuleType('shioaji')
        module.__version__ = BROKER_SDK_VERSION
        with patch.dict(sys.modules, {'shioaji': module}):
            self.assertIs(sdk_loader.load_pinned_sdk(), module)
            module.__version__ = 'unreviewed'
            with self.assertRaises(DomainError):
                sdk_loader.load_pinned_sdk()

"""New M1 value boundaries never grant presentation storage or execution imports."""

import unittest

from tools.check_trading_architecture import check_source


class M1ArchitectureTests(unittest.TestCase):
    def test_named_m1_ui_value_contracts_are_allowed(self):
        for module in (
            'application.market_settings',
            'application.symbol_search',
            'application.alert_contracts',
            'domain.watch',
            'domain.alerts',
            'domain.validation',
        ):
            with self.subTest(module=module):
                self.assertEqual(check_source('import quantlab.trading.' + module, 'desktop_app/features/trading/m1_subject.py'), ())

    def test_ui_still_cannot_import_storage_sdk_or_execution(self):
        for module in (
            'shioaji',
            'sqlite3',
            'quantlab.trading.adapters.shioaji.market_session',
            'quantlab.trading.adapters.storage.kline_store',
            'quantlab.trading.runtime.market_terminal',
            'quantlab.trading.application.engine',
            'quantlab.trading.domain.risk',
            'quantlab.trading.application.alert_service',
            'quantlab.trading.application.market_terminal_service',
        ):
            with self.subTest(module=module):
                self.assertTrue(check_source('import ' + module, 'desktop_app/features/trading/m1_subject.py'))

    def test_new_application_and_domain_modules_cannot_hide_outer_dependencies(self):
        for path in (
            'quantlab/trading/application/symbol_search.py',
            'quantlab/trading/application/alert_contracts.py',
            'quantlab/trading/domain/watch.py',
            'quantlab/trading/domain/alerts.py',
        ):
            for source in ('import sqlite3', 'import shioaji', 'from quantlab.trading.runtime.market_terminal import attach_terminal'):
                with self.subTest(path=path, source=source):
                    self.assertTrue(check_source(source, path))


if __name__ == '__main__':
    unittest.main()

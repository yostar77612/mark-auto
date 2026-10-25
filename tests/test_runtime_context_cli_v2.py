"""Public launch routing remains explicit; these cases never start a GUI/SDK."""

from contextlib import redirect_stderr
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import desktop
from quantlab.trading.domain.models import Environment
from quantlab.trading.runtime.config import RuntimeLaunch


class RuntimeContextCliTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / 't' / 'cli-not-started'
        self.profile = self.root / 'profile.json'
        self.registry = self.root / 'contexts.json'

    def test_gui_routes_explicit_environment_account_profile_and_registry(self):
        with patch('trading_runtime.run_window', return_value=17) as launch:
            result = desktop.main(
                [
                    '--platform-v2',
                    '--trading-root',
                    str(self.root),
                    '--trading-environment',
                    'BROKER_SIMULATION',
                    '--trading-account',
                    'explicit-account',
                    '--trading-profile',
                    str(self.profile),
                    '--trading-contexts',
                    str(self.registry),
                ]
            )
        self.assertEqual(result, 17)
        launch.assert_called_once_with(
            self.root, environment=Environment.BROKER_SIMULATION, account_ref='explicit-account', profile_path=self.profile, contexts_path=self.registry
        )

    def test_engine_routes_typed_launch_and_gui_default_restores_saved_selection(self):
        with patch('quantlab.trading.runtime.server.serve', return_value=0) as serve:
            self.assertEqual(
                desktop.main(
                    [
                        '--trading-engine',
                        str(self.root),
                        '--trading-environment',
                        'LIVE',
                        '--trading-account',
                        'explicit-live',
                        '--trading-profile',
                        str(self.profile),
                    ]
                ),
                0,
            )
        serve.assert_called_once_with(self.root, launch=RuntimeLaunch(self.root, Environment.LIVE, self.profile, 'explicit-live'))
        with patch('trading_runtime.run_window', return_value=0) as launch:
            self.assertEqual(desktop.main(['--platform-v2', '--trading-root', str(self.root)]), 0)
        launch.assert_called_once_with(self.root, environment=None, account_ref=None, profile_path=None, contexts_path=None)

    def test_incomplete_ambiguous_or_legacy_mixed_context_arguments_are_rejected(self):
        variants = (
            ['--trading-environment', 'LIVE', '--trading-account', 'alias'],
            ['--platform-v2', '--trading-environment', 'LIVE'],
            ['--platform-v2', '--trading-profile', str(self.profile)],
            ['--platform-v2', '--trading-environment', 'LOCAL', '--trading-profile', str(self.profile)],
            ['--trading-engine', str(self.root), '--trading-contexts', str(self.registry)],
            ['--platform-v2', '--trading-contexts', 'relative.json'],
            ['--platform-v2', '--smoke-test', str(self.root / 'smoke.json')],
        )
        for args in variants:
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as rejected:
                desktop.parse_args(args)
            self.assertEqual(rejected.exception.code, 2)


if __name__ == '__main__':
    unittest.main()

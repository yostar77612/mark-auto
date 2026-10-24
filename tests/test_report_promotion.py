"""A transient directory rename must never replay the backtest computation."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from quantlab import backtest
from quantlab import runtime_support as io
from quantlab.core import to_dict
from quantlab.reporting import demo_config, save_dataset, synthetic_dataset
from tests.test_atomic_replace import denied


class ReportPromotionTests(unittest.TestCase):
    def test_transient_and_persistent_directory_denial_preserve_computation_and_activation(self):
        from desktop_ui import _handle_ui_backtest

        for persistent in (False, True):
            with self.subTest(persistent=persistent), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                save_dataset(synthetic_dataset(120), root / 'dataset.json')
                original_dataset = (root / 'dataset.json').read_bytes()
                (root / 'active_result.json').write_bytes(b'old active result reference')
                original_replace = io.os.replace
                attempts = []

                def replace(source, destination):
                    if Path(source).is_dir():
                        attempts.append((Path(source), Path(destination)))
                        if persistent or len(attempts) == 1:
                            raise denied()
                    return original_replace(source, destination)

                from quantlab.strategies import builtin_strategies

                spec = builtin_strategies()[0]
                payload = {'config': to_dict(demo_config()), 'family': spec.family, 'parameters': dict(spec.parameters)}
                with (
                    patch.object(io, 'sys', SimpleNamespace(platform='win32')),
                    patch.object(io.os, 'replace', side_effect=replace),
                    patch.object(io.time, 'sleep'),
                    patch.object(backtest, 'run_backtest', wraps=backtest.run_backtest) as compute,
                ):
                    if persistent:
                        with self.assertRaises(PermissionError):
                            _handle_ui_backtest(payload, None, root)
                        self.assertEqual((root / 'active_result.json').read_bytes(), b'old active result reference')
                        self.assertEqual(list((root / 'reports').iterdir()), [])
                    else:
                        result = _handle_ui_backtest(payload, None, root)
                        self.assertEqual(len(result['reports']), 1)
                        self.assertTrue(Path(result['reports'][0]['result']).exists())
                    compute.assert_called_once()
                self.assertEqual(len(attempts), 7 if persistent else 2)
                self.assertEqual(attempts, [attempts[0]] * len(attempts))
                self.assertEqual((root / 'dataset.json').read_bytes(), original_dataset)

import csv
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from quantlab.core import content_hash, ValidationError
from quantlab.reporting import (synthetic_dataset, demo_config, export_report, load_result,
                               load_dataset, save_dataset, read_json, write_json, comparison_rows)
from quantlab.strategies import builtin_strategies
from quantlab.backtest import run_backtest


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = synthetic_dataset()
        self.result = run_backtest(self.dataset, builtin_strategies()[0], demo_config())

    def test_dataset_and_result_roundtrip_and_repeated_export(self):
        path = self.root / 'dataset.json'
        save_dataset(self.dataset, path)
        self.assertEqual(content_hash(self.dataset), content_hash(load_dataset(path)))
        paths = export_report(self.result, self.root)
        self.assertEqual(content_hash(load_result(paths['result'])), content_hash(self.result))
        self.assertEqual(paths, export_report(self.result, self.root))
        self.assertEqual(len(list(self.root.glob('*/result.json'))), 1)
        self.assertEqual(comparison_rows([self.result])[0]['result_hash'], paths['result_hash'])

    def test_tampered_json_rejected(self):
        paths = export_report(self.result, self.root)
        envelope = read_json(paths['result'])
        envelope['payload']['metrics']['net_pnl'] = '99999999'
        write_json(paths['result'], envelope)
        with self.assertRaises(ValidationError):
            load_result(paths['result'])

    def test_text_formula_escape_and_untrusted_ids(self):
        malicious = replace(self.result.fills[0], reason='  =HYPERLINK("bad")', order_id='../../escape')
        result = replace(self.result, fills=(malicious,))
        paths = export_report(result, self.root)
        with open(paths['fills'], newline='') as file:
            row = next(csv.DictReader(file))
        self.assertTrue(row['reason'].startswith("'"))
        self.assertEqual(Path(paths['fills']).parent.parent, self.root)
        self.assertFalse((self.root.parent / 'escape').exists())

    def test_symlink_output_refused(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / content_hash(self.result)).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValidationError):
            export_report(self.result, self.root)

    def test_empty_comparison(self):
        self.assertEqual(comparison_rows([]), [])

    def test_immutable_selection_rejects_tamper_and_mismatch(self):
        from quantlab.core import to_dict
        from quantlab.reporting import save_selection, load_selection
        path = self.root / 'selection.json'
        saved = save_selection(to_dict(builtin_strategies()[0]), self.result, path)
        self.assertEqual(load_selection(path), saved)
        with self.assertRaises(ValidationError):
            save_selection(to_dict(builtin_strategies()[1]), self.result, path)
        saved['strategy_hash'] = '0' * 64
        write_json(path, saved)
        with self.assertRaises(ValidationError):
            load_selection(path)

    def test_recomputed_envelope_does_not_mask_internal_tamper(self):
        paths = export_report(self.result, self.root)
        envelope = read_json(paths['result'])
        envelope['payload']['metrics']['net_pnl'] = '999999999'
        envelope['sha256'] = content_hash(envelope['payload'])
        write_json(paths['result'], envelope)
        with self.assertRaisesRegex(ValidationError, 'Internal reproducibility'):
            load_result(paths['result'])

    def test_nested_config_binding_and_actual_dataset(self):
        paths = export_report(self.result, self.root)
        self.assertEqual(content_hash(load_result(paths['result'], dataset=self.dataset)), content_hash(self.result))
        with self.assertRaisesRegex(ValidationError, 'supplied dataset'):
            load_result(paths['result'], dataset=synthetic_dataset(241))
        envelope = read_json(paths['result'])
        payload = envelope['payload']
        payload['manifest']['config']['initial_cash'] = '999999999'
        unhashed = {**payload, 'manifest': {k: v for k, v in payload['manifest'].items() if k not in ('run_hash', 'reproducibility_hash')}}
        digest = content_hash(unhashed)
        payload['manifest'].update(run_hash=digest, reproducibility_hash=digest)
        envelope['sha256'] = content_hash(payload)
        write_json(paths['result'], envelope)
        with self.assertRaisesRegex(ValidationError, 'strategy/config hash'):
            load_result(paths['result'])

    def test_recomputed_dataset_envelope_rejects_stale_bar_binding(self):
        path = self.root / 'dataset.json'
        save_dataset(self.dataset, path)
        envelope = read_json(path)
        envelope['payload']['bars'][0]['volume'] = 999
        envelope['sha256'] = content_hash(envelope['payload'])
        write_json(path, envelope)
        with self.assertRaisesRegex(ValidationError, 'bar hash'):
            load_dataset(path)

"""Stock signal Bar IDs must never pass a futures data gate, nor reach an OOS reservation."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from unittest.mock import patch

from quantlab.core import Dataset, ValidationError, content_hash
from quantlab.data import validate_dataset
from quantlab.futures_gate import require_futures_dataset
from quantlab.reporting import load_dataset, save_dataset
from quantlab.research import FixtureGenerator, run_campaign
from quantlab.walk_forward import run_walk_forward
from tests import test_research, test_walk_forward

STOCK = 'TWSE:2330'


def as_stock(dataset, contract=STOCK):
    bars = tuple(replace(bar, contract_id=contract) for bar in dataset.bars)
    manifest = {**dataset.manifest, 'data_hash': content_hash(bars)}
    if 'source_hash' in manifest:
        manifest['source_hash'] = manifest['data_hash']
    if 'manifest_hash' in manifest:
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
    return Dataset(bars, manifest, dict(dataset.quality))


class FuturesGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_gate_rejects_every_stock_id_even_one_hidden_among_tmf_bars(self):
        data, _ = test_walk_forward.inputs()
        require_futures_dataset(data)
        for contract in ('TWSE:2330', 'TPEX:6488', 'TWSE:123456'):
            with self.subTest(contract=contract), self.assertRaises(ValidationError):
                require_futures_dataset(as_stock(data, contract))
        mixed = list(data.bars)
        mixed[100] = replace(mixed[100], contract_id=STOCK)
        with self.assertRaises(ValidationError):
            require_futures_dataset(Dataset(tuple(mixed), dict(data.manifest), dict(data.quality)))
        with self.assertRaises(ValidationError):
            require_futures_dataset('not a dataset')

    def test_handmade_quantlab_dataset_file_with_stock_ids_is_refused_on_load(self):
        data, _ = test_walk_forward.inputs()
        good, bad = self.root / 'good.json', self.root / 'bad.json'
        save_dataset(data, good)
        self.assertEqual(load_dataset(good).bars, data.bars)
        save_dataset(as_stock(data), bad)
        with self.assertRaises(ValidationError):
            load_dataset(bad)

    def test_walk_forward_refuses_stock_dataset_before_any_reservation(self):
        data, plan = test_walk_forward.inputs()
        registry = self.root / 'controls' / 'holdout.sqlite3'
        output = self.root / 'run'
        with self.assertRaises(ValidationError):
            run_walk_forward(as_stock(data), plan=plan, output_dir=output, holdout_registry_path=registry)
        self.assertFalse(registry.exists())
        self.assertFalse(registry.parent.exists())
        self.assertFalse(output.exists())

    def test_campaign_operation_refuses_stock_dataset_before_any_reservation(self):
        from types import SimpleNamespace

        from quantlab.research_core.application import research_operations

        data, config = test_research.inputs()
        controls = self.root / 'controls'
        ports = SimpleNamespace(inputs=SimpleNamespace(_dataset=lambda root, payload: as_stock(data), research_controls=lambda paths: controls))
        payload = {'config': config, 'provider': {'mode': 'fixture'}}
        with patch('quantlab.research.run_campaign') as campaign, self.assertRaisesRegex(ValidationError, 'TAIFEX:TMF'):
            research_operations._handle_ui_campaign(ports, payload, {}, self.root)
        campaign.assert_not_called()
        self.assertEqual(list(self.root.rglob('*')), [])

    def test_valid_tmf_campaign_still_starts(self):
        data, config = test_research.inputs()
        state = run_campaign(data, config=config, generator=FixtureGenerator(), output_dir=self.root / 'ok' / 'campaign')
        self.assertIn('status', state)

    def test_direct_validate_dataset_and_run_campaign_refuse_stock_ids(self):
        """Owner-approved G3 edit: the gates themselves (not only their callers) are TMF-only."""
        data, config = test_research.inputs()
        stock = as_stock(data)
        with self.assertRaises(ValidationError):
            validate_dataset(stock)
        output = self.root / 'direct' / 'campaign'
        with self.assertRaises(ValidationError):
            run_campaign(stock, config=config, generator=FixtureGenerator(), output_dir=output)
        self.assertFalse(output.exists())
        self.assertEqual(sorted(path.name for path in self.root.rglob('*.sqlite3')), [])


if __name__ == '__main__':
    unittest.main()

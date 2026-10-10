"""Frozen manual-exchange adversarial contract; synthetic data, no model calls."""
import copy
import json
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantlab.core import Dataset, ValidationError, to_dict
from quantlab.research import run_campaign
from quantlab.strategies import builtin_strategies
from tests.test_research import inputs
from quantlab.manual_exchange import export_request, export_request_file, import_response, import_response_file, MAX_BYTES


class ManualExchangeTests(unittest.TestCase):
    def setUp(self):
        self.data, self.config = inputs()
        self.config.update(max_improvements=0, max_trials=1, families=['trend'])
        self.config['ranking']['minimum'] = '-1000000'
        self.request = export_request(self.data, self.config)
        self.response = {k: self.request[k] for k in ('schema_version', 'request_id', 'data_hash', 'config_hash')}
        self.response['candidates'] = [{'family': 'trend', 'context_hash': self.request['families'][0]['context_hash'],
            'candidate': to_dict(builtin_strategies()[0])}]

    def load(self, value=None):
        return import_response(self.data, self.config, json.dumps(self.response if value is None else value))

    def test_training_only_and_versions(self):
        self.data = Dataset(self.data.bars, {**self.data.manifest, 'credential': 'SECRET_PATH_TOKEN'}, dict(self.data.quality))
        request = export_request(self.data, self.config)
        text = json.dumps(request)
        for forbidden in ('SECRET_PATH_TOKEN', '"holdout"', '"oos"', '"timestamp"', '"source_type"'):
            self.assertNotIn(forbidden, text)
        self.assertIn('prompt_version', request)
        self.assertIn('registry_version', request)
        self.assertIn('response_schema', request)

    def test_strict_parser_frozen_adversarial_matrix(self):
        good = json.dumps(self.response)
        invalid = [good.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1),
            ' ' * (MAX_BYTES + 1), '[' * 1000 + '0' + ']' * 1000,
            good.replace('"fast": 5', '"fast": NaN'), '{"x":NaN}', '{"x":1e999}',
            '```json\n' + good + '\n```']
        # Include an unconditional candidate nonfinite mutation, regardless of fixture parameters.
        bad = copy.deepcopy(self.response); bad['candidates'][0]['candidate']['parameters']['fast'] = float('inf')
        invalid.append(json.dumps(bad))
        for raw in invalid:
            if raw == good: continue
            with self.subTest(raw=raw[:70]), self.assertRaises(ValidationError):
                import_response(self.data, self.config, raw)

    def test_identity_family_context_extra_duplicate_and_code_rejected(self):
        for key in ('request_id', 'data_hash', 'config_hash'):
            bad = copy.deepcopy(self.response); bad[key] = '0' * 64
            with self.assertRaises(ValidationError): self.load(bad)
        for field, value in [('context_hash', '0' * 64), ('family', 'momentum'), ('code', 'print(1)')]:
            bad = copy.deepcopy(self.response); bad['candidates'][0][field] = value
            with self.assertRaises(ValidationError): self.load(bad)
        bad = copy.deepcopy(self.response); bad['candidates'] *= 2
        with self.assertRaises(ValidationError): self.load(bad)
        bad = copy.deepcopy(self.response); bad['candidates'][0]['candidate']['rules'] = {'code': '__import__("os")'}
        with self.assertRaises(ValidationError): self.load(bad)

    def test_sealed_pickle_exact_context_and_defensive_copy(self):
        generator = pickle.loads(pickle.dumps(self.load()))
        context = self.request['families'][0]['context']
        first = generator.generate(context); first['strategy_id'] = 'mutated'
        self.assertNotEqual(generator.generate(context)['strategy_id'], 'mutated')
        bad = copy.deepcopy(context); bad['seed'] += 1
        with self.assertRaises(ValidationError): generator.generate(bad)
        with self.assertRaises(ValidationError): generator.improve(context)
        with self.assertRaises((AttributeError, TypeError)): generator.model = 'changed'
        object.__setattr__(generator, '_package_json', b'{}')
        with self.assertRaises(ValidationError): generator.generate(context)

    def test_preflight_no_adaptation_or_insufficient_trials(self):
        generator = self.load()
        self.config['max_improvements'] = 1
        with self.assertRaises(ValidationError): export_request(self.data, self.config)
        with self.assertRaises(ValidationError): generator.preflight(self.data, self.config)
        self.config.update(max_improvements=0, families=['trend', 'momentum'])
        with self.assertRaises(ValidationError): export_request(self.data, self.config)

    def test_file_roundtrip_and_stale_source_or_config(self):
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / 'request.json'
            response_path = Path(directory) / 'response.json'
            request = export_request_file(self.data, self.config, request_path)
            self.assertEqual(json.loads(request_path.read_text()), request)
            response_path.write_text(json.dumps(self.response))
            generator = import_response_file(self.data, self.config, response_path)
            generator.preflight(self.data, self.config)
            changed = copy.deepcopy(self.config); changed['seed'] += 1
            with self.assertRaises(ValidationError): generator.preflight(self.data, changed)
            with patch('quantlab.manual_exchange._source_hash', return_value='0' * 64):
                with self.assertRaises(ValidationError): generator.generate(request['families'][0]['context'])
            response_path.write_bytes(b'x' * (MAX_BYTES + 1))
            with self.assertRaises(ValidationError): import_response_file(self.data, self.config, response_path)

    def test_export_never_overwrites_existing_file_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / 'controls.sqlite3'
            existing.write_bytes(b'authoritative controls')
            with self.assertRaises(ValidationError): export_request_file(self.data, self.config, existing)
            self.assertEqual(existing.read_bytes(), b'authoritative controls')
            link = root / 'export.json'
            try: link.symlink_to(existing)
            except (OSError, NotImplementedError): self.skipTest('Symlink creation unavailable')
            with self.assertRaises(ValidationError): export_request_file(self.data, self.config, link)
            self.assertTrue(link.is_symlink())
            self.assertEqual(existing.read_bytes(), b'authoritative controls')
            real = root / 'real'; real.mkdir()
            linked_dir = root / 'linked'; linked_dir.symlink_to(real, target_is_directory=True)
            with self.assertRaises(ValidationError): export_request_file(self.data, self.config, linked_dir / 'new.json')
            self.assertFalse((real / 'new.json').exists())

    def test_export_failure_leaves_no_partial_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'new.json'
            with patch('quantlab.manual_exchange.os.fsync', side_effect=OSError('synthetic disk failure')):
                with self.assertRaises(ValidationError): export_request_file(self.data, self.config, target)
            self.assertFalse(target.exists())

    def test_all_families_sealed_and_schema_integer_only(self):
        from quantlab.research import FAMILIES
        self.config.update(families=list(FAMILIES), max_trials=len(FAMILIES))
        request = export_request(self.data, self.config)
        response = {k: request[k] for k in ('schema_version', 'request_id', 'data_hash', 'config_hash')}
        response['candidates'] = []
        for expected in request['families']:
            candidate = to_dict(next(s for s in builtin_strategies() if s.family == expected['family']))
            candidate['parameters'] = {k: int(v) for k, v in candidate['parameters'].items()}
            response['candidates'].append({'family': expected['family'], 'context_hash': expected['context_hash'], 'candidate': candidate})
        generator = import_response(self.data, self.config, json.dumps(response))
        for expected in request['families']:
            self.assertEqual(generator.generate(expected['context'])['family'], expected['family'])
        response['candidates'][1]['candidate']['parameters']['entry_bps'] = '10'
        with self.assertRaises(ValidationError): import_response(self.data, self.config, json.dumps(response))

    def test_synthetic_campaign_uses_shared_irreversible_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); registry = root / 'controls.sqlite3'
            first = run_campaign(self.data, config=self.config, generator=self.load(), output_dir=root/'a', holdout_registry_path=registry)
            self.assertEqual(first['attempts'][0]['status'], 'evaluated')
            self.assertEqual(first['holdout_status'], 'reserved_consumed')
            self.assertEqual(first['real_model_status'], 'not_verified')
            self.response['candidates'][0]['candidate']['parameters']['fast'] = 3
            other = self.load()
            with self.assertRaises(ValidationError):
                run_campaign(self.data, config=self.config, generator=other, output_dir=root/'a', holdout_registry_path=registry)
            second = run_campaign(self.data, config=self.config, generator=other, output_dir=root/'b', holdout_registry_path=registry)
            self.assertEqual(second['status'], 'blocked_previously_consumed_holdout')
            self.assertEqual(second['evaluations'], {'oos': [], 'holdout': []})
            self.assertNotEqual(first['binding']['provider']['model'], second['binding']['provider']['model'])
            # A changed partition with an overlapping, nonidentical final interval
            # is still rejected by the same authoritative registry.
            self.config['splits']['oos'][1] += 1
            self.config['splits']['holdout'][0] += 1
            request = export_request(self.data, self.config)
            for key in ('request_id', 'data_hash', 'config_hash'):
                self.response[key] = request[key]
            self.response['candidates'][0]['context_hash'] = request['families'][0]['context_hash']
            third = run_campaign(self.data, config=self.config, generator=self.load(), output_dir=root/'c', holdout_registry_path=registry)
            self.assertEqual(third['status'], 'blocked_previously_consumed_holdout')
            self.assertEqual(third['evaluations'], {'oos': [], 'holdout': []})

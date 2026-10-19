"""Cheap offline metadata inventory and pre-B6 value preservation checks."""

import copy
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import list_unverified_goldens as inventory
from tools.run_test_group import core_shard_for_module


FIXTURES = Path(__file__).parent / 'fixtures'
# Canonical JSON digests from git show 17b5b1b:tests/fixtures/<name>,
# established with a full deep-equality check stripping only B6 entry metadata.
BASELINE = {
    'engine_golden.json': 'dc25575a34ab7847bdf64cf6ea13dd439e2afe471a07076dc57f864ed14f94a9',
    'ui_operations_golden.json': '64c1b4bdf86e7479477cf15f272f00d3b37fa0357c45f23d57d3a8766475c8bb',
}


class GoldenMetadataTests(unittest.TestCase):
    def test_fixture_metadata_counts_and_original_values(self):
        expected_counts = {}
        for name, collection in inventory.FIXTURES.items():
            with (FIXTURES / name).open(encoding='utf-8') as stream:
                document = json.load(stream)
            entries = list(document[collection].values()) if collection == 'observations' else document[collection]
            expected_counts[name] = 0
            for entry in entries:
                self.assertIn(entry['source'], {'hand-computed', 'existing-behaviour', 'cross-checked', 'derived'})
                self.assertIn(entry['review'], {'unreviewed', 'reviewed', 'independently-verified'})
                self.assertEqual(entry['precision'], 'Decimal-exact' if collection == 'cases' else 'exact after documented normalisations; Decimal-exact money')
                if collection == 'cases':
                    self.assertEqual(entry['source'], 'hand-computed')
                if entry['review'] != 'independently-verified' or entry['source'] not in ('hand-computed', 'cross-checked'):
                    expected_counts[name] += 1
                for key in ('source', 'review', 'precision'):
                    del entry[key]
            canonical = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), BASELINE[name])
        report = inventory.count_unverified(FIXTURES)
        self.assertEqual(report, {'fixtures': expected_counts, 'total': sum(expected_counts.values())})
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(inventory.main(['--json']), 0)
        self.assertEqual(json.loads(output.getvalue()), report)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(inventory.main([]), 0)
        for name, count in expected_counts.items():
            self.assertIn(f'{name}: {count} unverified', output.getvalue())
        self.assertIn(f'Total: {sum(expected_counts.values())} unverified', output.getvalue())
        self.assertEqual(core_shard_for_module('test_golden_metadata'), 'remaining')

    def test_count_requires_both_independent_source_and_review(self):
        entries = [
            {'source': source, 'review': review, 'precision': 'Decimal-exact'}
            for source in ('hand-computed', 'existing-behaviour', 'cross-checked', 'derived')
            for review in ('unreviewed', 'reviewed', 'independently-verified')
        ]
        document = {'cases': entries}
        with (
            patch.dict(inventory.FIXTURES, {'synthetic.json': 'cases'}, clear=True),
            patch.object(Path, 'open', return_value=io.StringIO(json.dumps(document))),
        ):
            report = inventory.count_unverified(FIXTURES)
        expected = sum(e['source'] in ('existing-behaviour', 'derived') or e['review'] != 'independently-verified' for e in entries)
        self.assertEqual(report, {'fixtures': {'synthetic.json': expected}, 'total': expected})

    def test_invalid_or_missing_metadata_is_rejected(self):
        valid = {'source': 'derived', 'review': 'unreviewed', 'precision': 'Decimal-exact'}
        for field in ('source', 'review', 'precision'):
            for value in (None, 'unsupported', 0.001):
                entry = copy.copy(valid)
                if value is None:
                    del entry[field]
                else:
                    entry[field] = value
                with (
                    self.subTest(field=field, value=value),
                    patch.dict(inventory.FIXTURES, {'synthetic.json': 'cases'}, clear=True),
                    patch.object(Path, 'open', return_value=io.StringIO(json.dumps({'cases': [entry]}))),
                ):
                    with self.assertRaisesRegex(ValueError, field):
                        inventory.count_unverified(FIXTURES)

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
# Re-pinned after B3: the 23 analysis hash leaves changed only because quantlab/indicators.py source bytes are bound into them
# (see docs/analysis/b3_golden_changes.md); verified leaf-by-leaf against origin/main with metadata stripped.
# Re-pinned after A4: the only change is the added files['source'] observation of the ui_backtest export.
BASELINE = {
    'engine_golden.json': 'dc25575a34ab7847bdf64cf6ea13dd439e2afe471a07076dc57f864ed14f94a9',
    # B2/B4 regenerated only the walk-forward oos_statistics_text observations (statistics and Welch decay lines).
    # R1 (PR #76 approved) refreshed only provider/research source and derived SHA-256 values after the
    # approved desktop_chatgpt_provider.py and quantlab/research.py edits; operation results are unchanged.
    # R2 (PR #83 approved) refreshed only 5 provider-derived SHA-256 values after the approved
    # desktop_chatgpt_provider.py edit; every non-digest observation is unchanged.
    # Headerless-stream fix (owner approved 2026-10-23) refreshed the same 5 provider-derived digests.
    # Completed-items compatibility: exactly 9 digest leaves (5 identities); no other fixture leaf changed.
    # Windows long-path storage: exactly 49 source/derived-digest leaves; other observations retained.
    'ui_operations_golden.json': '76028f3e7dab0de0bf62f8cea05097d2160374a0e7e7bd754c2bca4b967c2fa2',
}


class GoldenMetadataTests(unittest.TestCase):
    def _restore_reviewed_atomic_provenance(self, document):
        # Keep the pre-change digest as an independent whole-corpus guard.
        # Only the 26 owner-approved, formula-verified source/derived hashes
        # may differ, with the complete new corpus independently pinned too.
        canonical = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), '56133b5b080c8d355816dd02e7b220c9731d7aeb873005c312919df6022aab54')
        changes = json.loads((FIXTURES / 'ui_operations_atomic_provenance_delta.json').read_text(encoding='utf-8'))
        self.assertEqual(len(changes), 26)
        self.assertEqual(len({tuple(row['path']) for row in changes}), 26)
        for row in changes:
            self.assertEqual(set(row), {'path', 'old', 'new'})
            self.assertRegex(row['old'], r'^[a-f0-9]{64}$')
            self.assertRegex(row['new'], r'^[a-f0-9]{64}$')
            self.assertNotEqual(row['old'], row['new'])
            self.assertIn(
                row['path'][-1],
                {
                    'attempt_id',
                    'campaign_id',
                    'holdout_selection_hash',
                    'selection_hash',
                    'binding',
                    'research.py',
                    'saved_candidate_pool.py',
                    'walk_forward.py',
                },
            )
            node = document['observations']
            for key in row['path'][:-1]:
                node = node[key]
            self.assertEqual(node[row['path'][-1]], row['new'])
            node[row['path'][-1]] = row['old']

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
            if collection == 'observations':
                # A2 adds one separately asserted operation; retain the original-value digest.
                self.assertIn('cancel_all_report', document[collection]['ui_paper_cancel_all']['result'])
                del document[collection]['ui_paper_cancel_all']
                self.assertIn(document[collection]['ui_capital_scenario']['result']['status'], ('completed', 'rejected'))
                del document[collection]['ui_capital_scenario']
                self.assertEqual(document[collection]['ui_idea_research']['result']['status'], 'search_unavailable')
                self.assertEqual(document[collection]['ui_idea_adopt']['exception'], 'ValidationError')
                del document[collection]['ui_idea_research']
                del document[collection]['ui_idea_adopt']
                self._restore_reviewed_atomic_provenance(document)
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

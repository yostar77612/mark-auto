"""Synthetic E1 contract tests, not proof of a production summary producer."""

from dataclasses import fields, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from quantlab.trading.domain.signal_strategy import CandidateEvidence, CandidateSummary
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.candidate_catalog import ResearchWorkspaceCandidateCatalog
from quantlab.trading.runtime.v1_signal_source import canonical_spec_json, spec_fingerprint


def evidence(**changes):
    spec = canonical_spec_json(json.dumps({'strategy_id': 'fixture', 'family': 'trend', 'parameters': {'fast': 2, 'slow': 5}, 'rules': {}}))
    row = CandidateEvidence(
        candidate_ref='fixture:candidate',
        campaign_ref='fixture:campaign',
        candidate_fingerprint=spec_fingerprint(spec),
        verdict='statistical_edge',
        oos_consumed=True,
        sample_count=40,
        completed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        dataset_family='fixture-family',
        dataset_interval='1d',
        signal_spec_json=spec,
    )
    return replace(row, **changes)


class CandidateCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)

    def catalog(self, rows):
        return ResearchWorkspaceCandidateCatalog(self.workspace, read_validated_summaries=lambda path: rows)

    def unavailable(self, call):
        with self.assertRaises(DomainError) as caught:
            call()
        self.assertEqual(caught.exception.code, 'candidate_unavailable')
        self.assertEqual(str(caught.exception), 'candidate_unavailable')
        self.assertIsNone(caught.exception.__cause__)

    def test_default_reader_is_explicitly_unavailable_not_legacy_admission(self):
        # Neither a legacy-looking export nor an invented E1 sidecar is trusted.
        for name in ('campaign.json', 'walk_forward.json', 'candidate-evidence.json'):
            (self.workspace / name).write_text('{"verdict":"statistical_edge"}', encoding='utf-8')
        catalog = ResearchWorkspaceCandidateCatalog(self.workspace)
        with patch.object(Path, 'open', side_effect=AssertionError('must not read research contents')):
            self.unavailable(catalog.passed)
            self.unavailable(lambda: catalog.resolve('fixture:candidate'))

    def test_synthetic_host_summary_projects_only_fixed_fields(self):
        row = evidence()
        reader = Mock(return_value=(row,))
        catalog = ResearchWorkspaceCandidateCatalog(self.workspace, read_validated_summaries=reader)
        self.assertEqual(catalog.passed(), (CandidateSummary(row.candidate_ref, row.verdict, row.completed_at, row.dataset_interval),))
        self.assertEqual(catalog.resolve(row.candidate_ref), row)
        self.assertEqual(reader.call_args.args, (self.workspace,))
        self.assertEqual(
            {field.name for field in fields(CandidateEvidence)},
            {
                'candidate_ref',
                'campaign_ref',
                'candidate_fingerprint',
                'verdict',
                'oos_consumed',
                'sample_count',
                'completed_at',
                'dataset_family',
                'dataset_interval',
                'signal_spec_json',
            },
        )

    def test_empty_validated_summary_list_is_empty_but_missing_reference_unavailable(self):
        catalog = self.catalog(())
        self.assertEqual(catalog.passed(), ())
        self.unavailable(lambda: catalog.resolve('missing'))

    def test_unqualified_facts_are_not_listed_and_remain_available_for_application_gate(self):
        rows = (evidence(verdict='insufficient'), evidence(candidate_ref='not-consumed', oos_consumed=False))
        catalog = self.catalog(rows)
        self.assertEqual(catalog.passed(), ())
        self.assertEqual(catalog.resolve('not-consumed'), rows[1])

    def test_fingerprint_tampering_rejected_before_any_projection(self):
        for changes in ({'candidate_fingerprint': 'mismatch'}, {'signal_spec_json': evidence().signal_spec_json.replace('"fast":2', '"fast":3')}):
            with self.subTest(changes=changes):
                catalog = self.catalog((evidence(**changes),))
                self.unavailable(catalog.passed)
                self.unavailable(lambda: catalog.resolve('fixture:candidate'))

    def test_duplicate_reference_and_noncanonical_or_invalid_specs_fail_closed(self):
        row = evidence()
        for rows in ((row, row), (evidence(signal_spec_json=' ' + row.signal_spec_json),), (evidence(signal_spec_json='{"rules":{"op":"exec"}}'),)):
            with self.subTest(rows=rows):
                self.unavailable(self.catalog(rows).passed)

    def test_raw_or_mutable_reader_payload_cannot_cross_summary_boundary(self):
        for rows in ([evidence()], ({'oos': 'synthetic-forbidden-field'},), (object(),), None):
            with self.subTest(rows=rows):
                self.unavailable(self.catalog(rows).passed)

    def test_missing_workspace_never_invokes_reader_or_creates_directory(self):
        missing = self.workspace / 'missing'
        reader = Mock()
        catalog = ResearchWorkspaceCandidateCatalog(missing, read_validated_summaries=reader)
        self.unavailable(catalog.passed)
        reader.assert_not_called()
        self.assertFalse(missing.exists())

    def test_lock_prevents_read_without_acquiring_or_removing_it(self):
        lock = self.workspace / 'desktop.lock'
        lock.write_bytes(b'fixture-lock')
        reader = Mock()
        catalog = ResearchWorkspaceCandidateCatalog(self.workspace, read_validated_summaries=reader)
        self.unavailable(catalog.passed)
        reader.assert_not_called()
        self.assertEqual(lock.read_bytes(), b'fixture-lock')

    def test_lock_appearing_during_read_discards_summary(self):
        def reader(path):
            (path / 'desktop.lock').write_bytes(b'fixture-racing-writer')
            return (evidence(),)

        catalog = ResearchWorkspaceCandidateCatalog(self.workspace, read_validated_summaries=reader)
        self.unavailable(catalog.passed)

    def test_reader_io_schema_and_sqlite_failures_are_redacted(self):
        for error in (
            OSError('private path'),
            sqlite3.OperationalError('database is locked'),
            ValueError('private research payload'),
            DomainError('other', 'private detail'),
        ):
            with self.subTest(error=type(error).__name__):
                reader = Mock(side_effect=error)
                catalog = ResearchWorkspaceCandidateCatalog(self.workspace, read_validated_summaries=reader)
                self.unavailable(catalog.passed)

    def test_catalog_does_not_write_read_raw_files_or_acquire_locks(self):
        row = evidence()
        catalog = self.catalog((row,))
        with (
            patch.object(Path, 'open', side_effect=AssertionError('no file contents')),
            patch('sqlite3.connect', side_effect=AssertionError('no journal access')),
        ):
            self.assertEqual(catalog.resolve(row.candidate_ref), row)
            self.assertEqual(len(catalog.passed()), 1)
        self.assertEqual(list(self.workspace.iterdir()), [])


if __name__ == '__main__':
    unittest.main()

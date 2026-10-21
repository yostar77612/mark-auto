from contextlib import contextmanager
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

from quantlab.backtest import run_backtest
from quantlab.core import ValidationError, content_hash, to_dict
from quantlab.reporting import demo_config, export_report, load_result, synthetic_dataset
from quantlab.strategies import builtin_strategies


@contextmanager
def report_directory():
    root = Path(tempfile.gettempdir()).resolve() / ('a4-' + uuid.uuid4().hex)
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root)


class ReportSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = synthetic_dataset()
        cls.result = run_backtest(cls.dataset, builtin_strategies()[0], demo_config())

    def test_fixed_source_bytes_for_validated_dataset_manifests(self):
        # Independent literal expectations also pin LF line endings on Windows.
        texts = {
            'synthetic': '\u8cc7\u6599\u4f86\u6e90\uff1a\u5408\u6210\u793a\u7bc4\uff08synthetic\uff09\u3002\u4e0d\u662f\u5be6\u969b\u884c\u60c5\u6216\u6210\u4ea4\uff0c\u6578\u5b57\u4e0d\u4ee3\u8868\u7372\u5229\u80fd\u529b\u3002\n',
            'proxy': '\u8cc7\u6599\u4f86\u6e90\uff1a\u4ee3\u7406\u8cc7\u6599\uff08proxy\uff09\u3002\u50c5\u4f9b\u7814\u7a76\u53c3\u8003\uff0c\u4e0d\u7b49\u540c\u5b98\u65b9\u884c\u60c5\u6216\u5be6\u969b\u6210\u4ea4\uff0c\u6578\u5b57\u4e0d\u4ee3\u8868\u7372\u5229\u80fd\u529b\u3002\n',
            'official_local': '\u8cc7\u6599\u4f86\u6e90\uff1a\u672c\u6a5f\u5b98\u65b9\u8cc7\u6599\uff08official_local\uff09\u3002\u884c\u60c5\u4f86\u6e90\u70ba\u672c\u6a5f\u532f\u5165\u7684\u5b98\u65b9\u8cc7\u6599\uff1b\u56de\u6e2c\u6210\u4ea4\u70ba\u6a21\u64ec\uff0c\u6578\u5b57\u4e0d\u4ee3\u8868\u7372\u5229\u80fd\u529b\u3002\n',
        }
        for source_type, expected in texts.items():
            with self.subTest(source_type=source_type), report_directory() as root:
                manifest = {**self.dataset.manifest, 'source_type': source_type}
                manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('manifest_hash', 'imported_at')})
                dataset = replace(self.dataset, manifest=manifest)
                config = replace(demo_config(), instrument_expiries={'TAIFEX:TMF:202601': '2026-01-21'})
                result = run_backtest(dataset, builtin_strategies()[0], config)
                digest = content_hash(result)
                files = export_report(result, root)
                source = root / digest / 'SOURCE.txt'
                self.assertEqual(files['source'], str(source))
                self.assertEqual(source.read_bytes(), expected.encode('utf-8'))
                self.assertEqual(content_hash(load_result(files['result'], dataset=dataset)), digest)
                self.assertEqual(export_report(result, root), files)
                self.assertEqual(source.read_bytes(), expected.encode('utf-8'))
                self.assertEqual(content_hash(result), digest)
                self.assertEqual(
                    {p.name for p in source.parent.iterdir()},
                    {
                        'result.json',
                        'manifest.json',
                        'ledger.json',
                        'metrics.json',
                        'fills.csv',
                        'equity.csv',
                        'SOURCE.txt',
                    },
                )
                self.assertNotIn(expected[0], '=+-@')
                self.assertNotIn(str(root), expected)
                self.assertNotIn('2026', expected)

    def test_nested_type_wins_but_loader_still_rejects_mismatched_binding(self):
        result = replace(self.result, manifest={**self.result.manifest, 'source_type': 'proxy'})
        with report_directory() as root:
            files = export_report(result, root)
            self.assertIn(b'synthetic', Path(files['source']).read_bytes())
            self.assertNotIn(b'proxy', Path(files['source']).read_bytes())
            with self.assertRaises(ValidationError):
                load_result(files['result'])

    def test_unknown_types_reject_before_any_write_and_preserve_previous_export(self):
        with report_directory() as root:
            export_report(self.result, root)
            before = {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
            listing = set(root.rglob('*'))
            invalid = ['real', '', None, 3, True, [], {}]
            manifests = [{**self.result.manifest['dataset_manifest'], 'source_type': value} for value in invalid]
            manifests += [{k: v for k, v in self.result.manifest['dataset_manifest'].items() if k != 'source_type'}, None]
            for manifest in manifests:
                with self.subTest(manifest=manifest):
                    result = replace(self.result, manifest={**self.result.manifest, 'dataset_manifest': manifest})
                    with self.assertRaises(ValidationError):
                        export_report(result, root)
                    self.assertEqual(set(root.rglob('*')), listing)
                    self.assertFalse((root / content_hash(result)).exists())
                    self.assertEqual({p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}, before)
                    missing_root = root / 'not-created'
                    with self.assertRaises(ValidationError):
                        export_report(result, missing_root)
                    self.assertFalse(missing_root.exists())

    def test_source_symlink_refused_before_export_writes(self):
        # Mock only the filesystem predicate: portable without symlink privileges.
        with report_directory() as root:
            files = export_report(self.result, root)
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (root / files['result_hash']).iterdir()}
            original = Path.is_symlink
            with patch.object(Path, 'is_symlink', lambda p: p.name == 'SOURCE.txt' or original(p)):
                with self.assertRaises(ValidationError):
                    export_report(self.result, root)
            self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (root / files['result_hash']).iterdir()}, before)

    def test_source_atomic_replace_failure_cleans_temporary_file(self):
        with report_directory() as root:
            files = export_report(self.result, root)
            source = Path(files['source'])
            before = source.read_bytes(), source.stat().st_mtime_ns
            original = os.replace

            def fail_source(src, dst):
                if Path(dst).name == 'SOURCE.txt':
                    raise OSError('write failed')
                return original(src, dst)

            with patch('quantlab.reporting.os.replace', side_effect=fail_source):
                with self.assertRaises(OSError):
                    export_report(self.result, root)
            self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), before)
            self.assertEqual(len(list(source.parent.iterdir())), 7)

    def test_main_1c65154_bytes_and_digest_unchanged(self):
        # Recorded from git archive 1c65154, before changing reporting.py.
        expected = {
            'result': '45525b920c8762c59dac2d0352bcea0c27f540e905252448829b0bddc966d4cf',
            'manifest': '72464bfcbe90de076a467b0414cd4465af4d0e7d7294254065ddf51b44fff26c',
            'ledger': '747a7ccb42e7713c1b52bec99189d062bf473eca89cb8384a79780dcb2504cb0',
            'metrics': '83fe25a7c078293ddcc93687e01643c97c52e105d0dd3184a620b34ebf496ee2',
            'fills': '2e7b62a49380f92c108ef8b9c38dd1a24d1a2fe1cec24d63c8b5d5c127ce1738',
            'equity': 'd273316ea4948ba814e4b83975bbf8b2635672c0704bcefffc3df219b925cb4f',
        }
        # The existing JSON writer uses native newlines; CSV always uses CRLF.
        # These LF hashes pin the same baseline JSON bytes on POSIX checkouts.
        if os.linesep == '\n':
            expected.update(
                result='e00b94917e5668ecef2f45d9b377cfbb3fedd264268590e7f6ba31f54a4e1b59',
                manifest='85ea2aa4ee8b805ec66ab761e6b1f1d04aa01c6c27930382c16c6197ab5df5ab',
                ledger='1162b39cb387635a39747752d429647f864754ce6e226b4f0a9c441d079a7a50',
                metrics='2fef8e23340df420d76530df285ec35b523681ec479821e4ba16193a13e4f5b2',
            )
        digest = 'f02a7f8a08fb7ade12ac4d65c74cd1bfb5581636f5735d05f0ad462fe1ae767b'
        # Pin environment metadata from main's fixture so interpreter versions
        # and checkout line endings cannot change this export compatibility test.
        manifest = {
            **self.result.manifest,
            'python_version': '3.13.11',
            'source_hashes': {
                'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e',
            },
        }
        manifest['engine_hash'] = content_hash(manifest['source_hashes'])
        payload = to_dict(replace(self.result, manifest=manifest))
        payload['manifest'] = {k: v for k, v in payload['manifest'].items() if k not in ('run_hash', 'reproducibility_hash')}
        run_hash = content_hash(payload)
        manifest.update(run_hash=run_hash, reproducibility_hash=run_hash)
        result = replace(self.result, manifest=manifest)
        with report_directory() as root:
            files = export_report(result, root)
            self.assertEqual(content_hash(load_result(files['result'], dataset=self.dataset)), digest)
            self.assertEqual(files['result_hash'], digest)
            self.assertEqual(set(files), {*expected, 'source', 'result_hash'})
            for name, sha in expected.items():
                path = root / digest / (name + ('.csv' if name in ('fills', 'equity') else '.json'))
                self.assertEqual(files[name], str(path))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), sha)

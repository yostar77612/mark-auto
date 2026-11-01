"""Every written product version equals quantlab.__version__ (set them with tools/bump_version.py)."""

from pathlib import Path
import json
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

import quantlab
from quantlab.build_info import build_commit

ROOT = Path(__file__).resolve().parents[1]
BUMP = runpy.run_path(str(ROOT / 'tools/bump_version.py'))


class VersionConsistencyTests(unittest.TestCase):
    def test_every_location_matches_the_single_source(self):
        found = list(BUMP['versions']())
        self.assertEqual({name for name, _ in found}, {name for name, _ in BUMP['LOCATIONS']})
        for name, version in found:
            with self.subTest(name=name):
                self.assertEqual(version, quantlab.__version__)

    def test_build_reads_version_from_the_single_source(self):
        build = (ROOT / 'packaging/build.ps1').read_text(encoding='utf-8')
        self.assertIn("param([string]$Version = ''", build)
        self.assertIn('quantlab/__init__.py', build)
        self.assertIn('build/build-info.json', build)
        self.assertIn("(str(root / 'build/build-info.json'), '.')", (ROOT / 'packaging/markauto.spec').read_text(encoding='utf-8'))


class BuildCommitTests(unittest.TestCase):
    def test_source_run_has_no_commit(self):
        with patch.object(sys, '_MEIPASS', None, create=True):
            self.assertEqual(build_commit(), '')

    def test_frozen_build_reports_short_commit(self):
        with tempfile.TemporaryDirectory() as bundle:
            (Path(bundle) / 'build-info.json').write_text(json.dumps({'version': '0.3.0', 'commit': '73157ed' + '0' * 33}), encoding='utf-8')
            with patch.object(sys, '_MEIPASS', bundle, create=True):
                self.assertEqual(build_commit(), '73157ed')

    def test_frozen_build_without_info_has_no_commit(self):
        with tempfile.TemporaryDirectory() as bundle, patch.object(sys, '_MEIPASS', bundle, create=True):
            self.assertEqual(build_commit(), '')


if __name__ == '__main__':
    unittest.main()

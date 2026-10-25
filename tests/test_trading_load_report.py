"""Load evidence is atomic under actual rename failures, never a partial pass."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quantlab import runtime_support
from tools.trading_load_report import write_report


class LoadEvidenceTests(unittest.TestCase):
    def test_transient_sharing_contention_keeps_one_complete_report(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'load.json'
            target.write_text('{"status":"RUNNING","acknowledged":100}', encoding='utf-8')
            original = runtime_support.os.replace
            attempts = []

            def replace(source, destination):
                attempts.append(Path(source).read_bytes())
                if len(attempts) == 1:
                    self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['status'], 'RUNNING')
                    error = PermissionError('injected sharing violation')
                    error.winerror = 5
                    raise error
                return original(source, destination)

            final = {'status': 'PASS', 'acknowledged': 180000, 'acceptance_30_minutes': True}
            with patch.object(runtime_support.sys, 'platform', 'win32'), patch.object(runtime_support.os, 'replace', side_effect=replace):
                write_report(target, final)
            self.assertEqual(json.loads(target.read_text(encoding='utf-8')), final)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0], attempts[1])
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_persistent_write_denial_cannot_publish_pass_or_destroy_previous_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'load.json'
            previous = b'{"status":"RUNNING","acceptance_30_minutes":false}'
            target.write_bytes(previous)
            with patch.object(runtime_support.os, 'replace', side_effect=PermissionError('injected permanent denial')):
                with self.assertRaises(PermissionError):
                    write_report(target, {'status': 'PASS', 'acceptance_30_minutes': True})
            self.assertEqual(target.read_bytes(), previous)
            self.assertEqual(list(Path(directory).iterdir()), [target])

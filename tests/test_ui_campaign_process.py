"""Behavior and fault proof for the developer web-host campaign boundary."""

from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import research_campaign as campaign
from quantlab.reporting import synthetic_dataset, demo_config
from quantlab.research import demo_campaign_config
from tests.test_desktop_smoke_terminal import process_can_run

_REAL_POPEN = subprocess.Popen


class WebCampaignProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.reap_retained)
        self.root = Path(self.tmp.name)
        self.dataset = synthetic_dataset(120)
        self.campaign_options = demo_campaign_config(self.dataset, demo_config())
        self.processes = []
        self.inputs = []

    def reap_retained(self):
        for inputs, process, tree in list(campaign._RETAINED):
            if tree is not None:
                tree.stop_and_join()
                tree.close()
            elif sys.platform != 'win32':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            process.wait(timeout=6)
            owned = Path(inputs.name).resolve()
            self.assertEqual(owned.parent, Path(tempfile.gettempdir()).resolve())
            self.assertTrue(owned.name.startswith('web-campaign-'))
            inputs.cleanup()
            campaign._RETAINED.remove((inputs, process, tree))

    def backend(self, code):
        def launch(command, **kwargs):
            self.inputs.append(Path(command[4]).parent)
            process = _REAL_POPEN([command[0], '-c', code], **kwargs)
            self.processes.append(process)
            return process

        return launch

    def test_invalid_budget_cannot_start_a_worker_or_create_campaign(self):
        with patch.object(campaign.subprocess, 'Popen', side_effect=AssertionError('Must reject before launch')):
            for value in (None, True, 0, -1, 7201, float('nan'), '300'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    campaign.run_fixture_campaign(self.dataset, dict(self.campaign_options, max_runtime_seconds=value), self.root / 'campaign')
        self.assertFalse((self.root / 'campaign').exists())

    def test_missing_admission_cannot_import_or_execute_campaign(self):
        result = subprocess.run(
            [sys.executable, '-c', campaign._BOOTSTRAP, 'campaign', str(self.root / 'missing-dataset')],
            input=b'',
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, b'')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_nonzero_worker_is_joined_and_never_publishes_success(self):
        code = 'import sys; sys.stdin.buffer.read(1); raise SystemExit(7)'
        with patch.object(campaign.subprocess, 'Popen', side_effect=self.backend(code)):
            with self.assertRaises(RuntimeError):
                campaign.run_fixture_campaign(self.dataset, self.campaign_options, self.root / 'campaign')
        self.assertEqual(self.processes[0].returncode, 7)
        self.assertFalse(self.inputs[0].exists())
        self.assertFalse((self.root / 'campaign/campaign.json').exists())
        self.assertEqual(campaign._RETAINED, [])

    def test_timeout_stops_owned_parent_and_descendant_without_budget_extension(self):
        pidfile = self.root / 'descendant.pid'
        code = (
            'import sys,time,subprocess; from pathlib import Path; sys.stdin.buffer.read(1); '
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
            f'Path({str(pidfile)!r}).write_text(str(child.pid)); time.sleep(60)'
        )
        started = time.monotonic()
        with patch.object(campaign.subprocess, 'Popen', side_effect=self.backend(code)):
            with self.assertRaises(TimeoutError):
                campaign.run_fixture_campaign(self.dataset, dict(self.campaign_options, max_runtime_seconds=2), self.root / 'campaign')
        self.assertLess(time.monotonic() - started, 10)
        self.assertIsNotNone(self.processes[0].returncode)
        self.assertFalse(process_can_run(int(pidfile.read_text())))
        self.assertFalse(self.inputs[0].exists())
        self.assertEqual(campaign._RETAINED, [])

    def test_unverified_stop_retains_inputs_and_refuses_new_work(self):
        stop = (
            patch('quantlab.desktop_runtime._WindowsProcessTree.stop_and_join', side_effect=RuntimeError('Unverified owned stop'))
            if sys.platform == 'win32'
            else patch.object(campaign.os, 'killpg', side_effect=PermissionError('Unverified owned stop'))
        )
        code = 'import sys; sys.stdin.buffer.read(1); raise SystemExit(7)'
        with patch.object(campaign.subprocess, 'Popen', side_effect=self.backend(code)), stop:
            with self.assertRaisesRegex((RuntimeError, PermissionError), 'Unverified owned stop'):
                campaign.run_fixture_campaign(self.dataset, self.campaign_options, self.root / 'campaign')
        self.assertEqual(len(campaign._RETAINED), 1)
        self.assertTrue(self.inputs[0].is_dir())
        with patch.object(campaign.subprocess, 'Popen', side_effect=AssertionError('Must remain blocked')):
            with self.assertRaisesRegex(RuntimeError, 'unverified'):
                campaign.run_fixture_campaign(self.dataset, self.campaign_options, self.root / 'other')


if __name__ == '__main__':
    unittest.main()

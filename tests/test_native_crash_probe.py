"""The CI crash probe names the faulting native module without swallowing the crash."""

import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows vectored exception handler')
class NativeCrashProbeTests(unittest.TestCase):
    def test_access_violation_reports_module_offset_and_still_crashes(self):
        code = 'import ctypes\nfrom tools.native_crash_probe import install\ninstall()\ninstall()\nctypes.string_at(16)\n'
        result = subprocess.run(
            [sys.executable, '-X', 'faulthandler', '-c', code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, 'PYTHONPATH': str(ROOT)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('native access violation #1: read at _ctypes.pyd+0x', result.stderr)
        self.assertIn('accessing address 0x10', result.stderr)
        self.assertIn('  stack ', result.stderr)
        self.assertNotIn('native access violation #2', result.stderr)
        # faulthandler still runs after the probe.
        self.assertIn('Windows fatal exception: access violation', result.stderr)


if __name__ == '__main__':
    unittest.main()

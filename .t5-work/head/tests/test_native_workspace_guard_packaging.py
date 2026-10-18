"""Static contracts for the separately executed Windows old-EXE refusal proof."""
import json
from pathlib import Path
import re
import unittest

from quantlab.desktop_runtime import _workspace_format

ROOT = Path(__file__).resolve().parents[1]


class NativeWorkspaceGuardPackagingTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'packaging/test_update_recovery.ps1').read_text()
        self.proof = self.source.split('function Assert-ReleasedWorkspaceGuard', 1)[1].split('\nPreserve-OwnedLifecycleSettings', 1)[0]

    def test_fixture_uses_current_strict_guard_without_real_sqlite(self):
        marker = json.loads(re.search(r"\$marker = '([^']+)'", self.proof).group(1))
        self.assertEqual(_workspace_format(marker), marker)
        self.assertIn('sqlite_replay', marker)
        self.assertIn('must remain unopened:', self.proof)
        self.assertIn('unchanged_files=$before.Count', self.proof)

    def test_exact_release_bounded_process_and_expected_refusal(self):
        for required in ("$BaselineVersion -ne '0.2.1'", '2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8',
                         'WaitForExit(30000)', 'taskkill.exe /PID $p.Id /T /F',
                         '$p.ExitCode -ne 1', "$evidence.market_smoke.error_type -ne 'RuntimeSafetyError'",
                         '@($evidence.steps).Count -ne 0'):
            self.assertIn(required, self.proof)
        self.assertIn("throw 'Required 0.2.1 native guard proof has an unexpected baseline source commit'", self.proof)
        self.assertNotIn('Run-Setup', self.proof)
        self.assertNotIn('Invoke-WebRequest', self.proof)

    def test_pointer_cleanup_requires_exclusive_creation_and_unchanged_hash(self):
        self.assertIn('[IO.FileMode]::CreateNew', self.proof)
        self.assertIn('$pointerCreated = $true', self.proof)
        self.assertIn('Assert-NoReparsePath $pointer', self.proof)
        self.assertIn('.Hash -ne $pointerDigest', self.proof)
        self.assertIn('[IO.File]::Delete($pointer)', self.proof)
        self.assertNotIn('Remove-Item', self.proof)

    def test_existing_lifecycle_still_runs_around_extra_proof(self):
        call = self.source.index('$workspaceGuardEvidence = Assert-ReleasedWorkspaceGuard $oldExe')
        self.assertLess(self.source.index("Smoke $oldExe $BaselineVersion 'baseline-existing-settings-smoke'"), call)
        self.assertGreater(self.source.index("Smoke $oldExe $BaselineVersion 'interrupted-before-activation'"), call)
        self.assertGreater(self.source.index("Smoke $newExe $Version 'recovered-smoke'"), call)
        self.assertIn('released_workspace_guard=$workspaceGuardEvidence', self.source)
        self.assertIn('no old-EXE backup-restore command-line entrypoint', self.proof)

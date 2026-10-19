"""Fast offline developer bootstrap contracts; never download or provision Python."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import install_sqlite_runtime as installer

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/dev_setup.ps1'
POWERSHELL = shutil.which('powershell.exe') or shutil.which('pwsh')


class DevSetupTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket', 'socket.create_connection', 'tools.install_sqlite_runtime.urllib.request.urlopen'):
            guard = patch(target, side_effect=AssertionError('Network forbidden in dev setup tests'))
            guard.start()
            self.addCleanup(guard.stop)

    @unittest.skipUnless(POWERSHELL, 'No powershell.exe or pwsh; PowerShell AST parse requires a host')
    def test_powershell_ast_and_no_write_preview(self):
        # One host startup for AST validation and both previews. No install branch runs.
        script = str(SCRIPT).replace("'", "''")
        command = (
            "$ErrorActionPreference='Stop'; $tokens=$null; $errors=$null; "
            "[void][System.Management.Automation.Language.Parser]::ParseFile("
            "'" + script + "', [ref]$tokens, [ref]$errors); "
            "if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }; "
            "& '" + script + "' -DryRun -Python 'must-not-execute'; "
            "& '" + script + "' -WhatIf -Python 'must-not-execute'"
        )
        # Cwd-independent, including the preview; no Python or network available to it.
        result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', command], cwd=ROOT.parent, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('Plan: pip install --require-hashes'), 2)

    def test_static_windows_trust_and_project_paths(self):
        source = SCRIPT.read_text(encoding='utf-8-sig')
        lower = source.lower()
        for forbidden in ('localappdata', '-skipcertificatecheck', '-insecure', 'servercertificatevalidationcallback', 'trustallcerts', '&&'):
            self.assertNotIn(forbidden, lower)
        self.assertNotRegex(lower, r'invoke-webrequest[^\n]*\|\s*(iex|invoke-expression)')
        for required in (
            '$PSScriptRoot',
            'Set-StrictMode',
            "$ErrorActionPreference = 'Stop'",
            'SupportsShouldProcess',
            '$WhatIfPreference',
            '$DryRun',
            'Net.HttpWebRequest',
            '$request.AllowAutoRedirect = $false',
            'archive SHA256 + SHA3-256',
            'extracted DLL content SHA256',
            "'--archive'",
            "'.runtime-sqlite'",
            "'.venv'",
            'Assert-ProjectPath',
            "'--require-hashes'",
            'requirements-desktop.lock',
            'python desktop.py',
        ):
            self.assertIn(required, source)
        self.assertLess(source.index('if ($DryRun -or $WhatIfPreference)'), source.index('New-Item'))
        self.assertIn('$creatingRuntime = $true', source)
        self.assertIn('Remove-Item -LiteralPath $runtime', source)

    def test_local_artifact_all_hash_failures_precede_install(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('sqlite3.dll', b'offline fixture DLL')
        data = output.getvalue()
        pin = {
            'sha256': hashlib.sha256(data).hexdigest(),
            'sha3_256': hashlib.sha3_256(data).hexdigest(),
            'dll_sha256': hashlib.sha256(b'offline fixture DLL').hexdigest(),
        }
        # Separate temporary files avoid Windows sandbox directory ACL creation.
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as stream:
            stream.write(data)
            artifact = Path(stream.name)
        manifest = artifact.with_suffix('.json')
        destination = artifact.with_suffix('.private')
        report = artifact.with_suffix('.report.json')
        try:
            # Exercise the actual provision path on both Linux and Windows without copying.
            with (
                patch.object(installer, 'MANIFEST', manifest),
                patch.object(installer.sys, 'platform', 'win32'),
                patch.object(installer.sys, 'prefix', installer.sys.base_prefix),
                patch.object(installer.platform, 'machine', return_value='AMD64'),
                patch.object(installer.shutil, 'copytree') as copy,
            ):
                for key, message in (('sha256', 'sha256 mismatch'), ('sha3_256', 'sha3_256 mismatch'), ('dll_sha256', 'DLL content mismatch')):
                    with self.subTest(check=key):
                        manifest.write_text(json.dumps({'windows_x64': {**pin, key: '0' * 64}}), encoding='utf-8')
                        with self.assertRaisesRegex(RuntimeError, message):
                            installer.provision(destination, report, archive_path=artifact)
                        self.assertFalse(destination.exists())
                        self.assertFalse(report.exists())
                        copy.assert_not_called()
            accepted = installer.download(pin, artifact)
            self.assertEqual(installer.windows_dll(accepted, pin), b'offline fixture DLL')
            self.assertFalse(destination.exists())
        finally:
            artifact.unlink()
            manifest.unlink(missing_ok=True)

    def test_local_archive_cli_is_optional_and_forwarded(self):
        with patch.object(installer, 'provision') as provision:
            with patch('sys.argv', ['install_sqlite_runtime.py', '--destination', 'private', '--report', 'report.json']):
                installer.main()
            provision.assert_called_once_with(Path('private'), Path('report.json'), False, None)
            provision.reset_mock()
            with patch('sys.argv', ['install_sqlite_runtime.py', '--destination', 'private', '--report', 'report.json', '--archive', 'local.zip']):
                installer.main()
            provision.assert_called_once_with(Path('private'), Path('report.json'), False, Path('local.zip'))

    def test_generated_paths_are_gitignored(self):
        paths = ['.venv/Scripts/python.exe', '.runtime-sqlite/python.exe', 'build/dev-setup-downloads/fixture/sqlite.zip']
        result = subprocess.run(
            ['git', 'check-ignore', '--no-index', '--stdin', '-z'], cwd=ROOT, input='\0'.join(paths) + '\0', capture_output=True, text=True, timeout=2
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(result.stdout.rstrip('\0').split('\0')), set(paths))


if __name__ == '__main__':
    unittest.main()

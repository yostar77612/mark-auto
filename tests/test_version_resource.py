"""Version metadata is deterministic project identity, never proof of signing."""
import ast
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = runpy.run_path(str(ROOT / 'packaging/version_resource.py'))


class VersionResourceTests(unittest.TestCase):
    def test_valid_versions_have_four_bounded_numeric_parts(self):
        self.assertEqual(RESOURCE['version_tuple']('0.2.2'), (0, 2, 2, 0))
        self.assertEqual(RESOURCE['version_tuple']('65535.65535.65535'),
                         (65535, 65535, 65535, 0))

    def test_rejects_injection_unicode_overflow_and_noncanonical_versions(self):
        for value in ('', '1.2', '1.2.3.4', '1.2.3-beta', '-1.2.3', '01.2.3',
                      '1.2.65536', '999999999.1.1', '١.٢.٣', '1.2.3\n',
                      "1.2.3');__import__('os')", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RESOURCE['render_version_resource'](value)

    def test_resource_has_expected_strings_fixed_versions_and_translation(self):
        source = RESOURCE['render_version_resource']('0.2.2')
        tree = ast.parse(source, mode='eval')
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        strings = {ast.literal_eval(call.args[0]): ast.literal_eval(call.args[1])
                   for call in calls if isinstance(call.func, ast.Name)
                   and call.func.id == 'StringStruct'}
        self.assertEqual(strings, {
            'CompanyName': 'Mark Auto contributors', 'FileDescription': 'MarkAuto',
            'FileVersion': '0.2.2', 'InternalName': 'MarkAuto',
            'OriginalFilename': 'MarkAuto.exe', 'ProductName': 'MarkAuto',
            'ProductVersion': '0.2.2'})
        fixed = next(call for call in calls if call.func.id == 'FixedFileInfo')
        fields = {entry.arg: ast.literal_eval(entry.value) for entry in fixed.keywords}
        self.assertEqual(fields['filevers'], (0, 2, 2, 0))
        self.assertEqual(fields['prodvers'], (0, 2, 2, 0))
        self.assertEqual(fields['fileType'], 1)
        self.assertIn("StringTable('040904B0'", source)
        self.assertIn("VarStruct('Translation', [1033, 1200])", source)
        self.assertEqual(source, RESOURCE['render_version_resource']('0.2.2'))

    def test_cli_writes_resource_and_rejects_invalid_before_touching_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'build' / 'version.txt'
            main = RESOURCE['main']
            self.assertEqual(main(['--version', '0.2.2', '--output', str(output)]), 0)
            before = output.read_bytes()
            with self.assertRaises(ValueError):
                main(['--version', '65536.0.0', '--output', str(output)])
            self.assertEqual(output.read_bytes(), before)

    def test_build_generates_before_freeze_then_checks_actual_version_before_inventory(self):
        build = (ROOT / 'packaging/build.ps1').read_text()
        self.assertLess(build.index('packaging/version_resource.py'), build.index('-m PyInstaller'))
        self.assertLess(build.index('-m PyInstaller'), build.index('[System.Diagnostics.FileVersionInfo]'))
        self.assertLess(build.index('[System.Diagnostics.FileVersionInfo]'), build.index('packaging/payload_inventory.py'))
        for field in ('FileVersion', 'ProductVersion', 'ProductName', 'CompanyName',
                      'OriginalFilename', 'InternalName', 'FilePrivatePart', 'ProductPrivatePart'):
            self.assertIn('$nativeVersion.' + field, build)
        self.assertIn('signature_verified = $false', build)
        # Lower installer fixture deliberately wraps the same candidate payload.
        self.assertEqual(build.count('packaging/version_resource.py'), 1)
        self.assertEqual(build.count('-m PyInstaller'), 1)
        self.assertIn("'/DAppVersion=0.0.0'", build)
        self.assertIn('"/DAppVersion=$Version"', build)

    def test_spec_adds_only_project_resource_and_preserves_sqlite_hooks(self):
        spec = (ROOT / 'packaging/markauto.spec').read_text()
        self.assertIn("version=str(root / 'build/markauto-version.txt')", spec)
        self.assertEqual(spec.count('version='), 1)
        self.assertIn("runtime_hooks=[str(root / 'packaging/sqlite_runtime_hook.py')]", spec)
        self.assertIn('verify_binaries(analysis.binaries', spec)


if __name__ == '__main__':
    unittest.main()

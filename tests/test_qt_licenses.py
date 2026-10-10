"""Offline checks for Qt notice inputs, exact module scope and frozen-payload audit."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import subprocess
import zipfile
import io
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('qt_licenses', ROOT / 'packaging/qt_licenses.py')
qt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qt)


class QtLicenseTests(unittest.TestCase):
    def test_exact_licenses_and_versioned_source_pins(self):
        notices = qt.reviewed_notice_bytes(ROOT / 'packaging/qt_notices')
        self.assertIn(b'GNU GENERAL PUBLIC LICENSE', notices['GPL-3.0-only.txt'])
        self.assertIn(b'17. Interpretation of Sections 15 and 16.', notices['GPL-3.0-only.txt'])
        self.assertIn(b'GNU LESSER GENERAL PUBLIC LICENSE', notices['LGPL-3.0-only.txt'])
        self.assertIn(b'4. Combined Works.', notices['LGPL-3.0-only.txt'])
        manifest = json.loads(notices['manifest.json'])
        self.assertEqual(set(manifest['qt_modules']), qt.MODULES)
        self.assertEqual(set(manifest['qt_plugins']), qt.PLUGINS)
        self.assertEqual(manifest['qt_version'], '.'.join(map(str, qt.QT_VERSION)))
        sources = runpy.run_path(str(ROOT / 'packaging/fetch_sources.py'))['SOURCES']
        self.assertEqual([(s['url'], s['sha256']) for s in manifest['source_archives']], sources)
        for item in manifest['source_archives']:
            self.assertIn('/6.12.0/', item['url']) if item['component'].startswith('QtBase') else self.assertIn('-6.12.0', item['url'])
            self.assertEqual(item['version'], '6.12.0')
        self.assertIn('packaging/qt_notices/*', (ROOT / 'packaging/build_manifest.py').read_text())

    def test_autocrlf_checkout_preserves_all_pinned_qt_assets(self):
        resource = Path('packaging/qt_notices')
        expected = {resource / p.name: p.read_bytes() for p in (ROOT / resource).iterdir()}
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary).resolve()
            (checkout / '.gitattributes').write_bytes((ROOT / '.gitattributes').read_bytes())
            for name, raw in expected.items():
                target = checkout / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            control = checkout / 'ordinary.py'
            control.write_bytes(b'# ordinary source\npass\n')
            def git(*args):
                return subprocess.run(['git', '-C', str(checkout), *args], check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git('init', '--quiet')
            git('-c', 'core.autocrlf=false', 'add', '--', '.gitattributes', 'ordinary.py',
                *(name.as_posix() for name in expected))
            for name in [*expected, Path('ordinary.py')]:
                (checkout / name).unlink()
            git('-c', 'core.autocrlf=true', 'checkout-index', '--all', '--force')
            self.assertEqual(control.read_bytes(), b'# ordinary source\r\npass\r\n')
            for name, raw in expected.items():
                self.assertEqual((checkout / name).read_bytes(), raw, name)
            qt.reviewed_notice_bytes(checkout / resource)

    def test_native_texts_are_complete_pinned_data_with_component_mapping(self):
        notices = qt.reviewed_notice_bytes(ROOT / 'packaging/qt_notices')
        with zipfile.ZipFile(io.BytesIO(notices['QT-NATIVE-NOTICES.zip'])) as archive:
            native = json.loads(archive.read('manifest.json'))
            components = {row['id']: row for row in native['components']}
            self.assertTrue({'pcre2', 'harfbuzz-ng', 'freetype', 'tika-mimetypes', 'psl-data',
                             'masm', 'libjpeg-turbo', 'libpng', 'libtiff', 'libwebp',
                             'mesa-llvmpipe', 'llvm-3.6.2', 'openssl-3.5.9'} <= set(components))
            self.assertNotIn('yoga', components)
            self.assertNotIn('pixman', components)
            for row in native['sources']:
                raw = archive.read(row['archive_file'])
                self.assertEqual(len(raw), row['bytes'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'])
            for row in native['components']:
                self.assertTrue(row['license_files'])
                for name in row['license_files']:
                    self.assertTrue(archive.read(name))
            text_hashes = [hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist() if n.startswith('texts/')]
            self.assertEqual(len(text_hashes), len(set(text_hashes)))
            self.assertNotIn('openssl-3.5.5', components)
            self.assertTrue(all(name.endswith(('.txt', '.json')) for name in archive.namelist()))

    def copied_notices(self, temp):
        target = Path(temp) / 'qt'
        shutil.copytree(ROOT / 'packaging/qt_notices', target)
        return target

    def test_missing_changed_extra_and_self_consistent_tampering_fail(self):
        for kind in ('missing', 'changed', 'extra', 'manifest', 'self-consistent'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                target = self.copied_notices(temp)
                file = target / 'GPL-3.0-only.txt'
                if kind == 'missing':
                    file.unlink()
                elif kind == 'extra':
                    (target / 'extra.txt').write_text('unreviewed')
                elif kind == 'manifest':
                    (target / 'manifest.json').write_text('{}')
                else:
                    file.write_bytes(b'Not a complete GPL text')
                    if kind == 'self-consistent':
                        manifest = json.loads((target / 'manifest.json').read_text())
                        manifest['files'][file.name]['sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
                        manifest['files'][file.name]['bytes'] = file.stat().st_size
                        (target / 'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(RuntimeError):
                    qt.reviewed_notice_bytes(target)

    def test_source_symlink_and_simulated_junction_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            target = self.copied_notices(temp)
            file = target / 'GPL-3.0-only.txt'
            outside = Path(temp) / 'outside'
            file.rename(outside)
            file.symlink_to(outside)
            with self.assertRaisesRegex(RuntimeError, 'link or reparse'):
                qt.reviewed_notice_bytes(target)
        with tempfile.TemporaryDirectory() as temp:
            target = self.copied_notices(temp)
            original = Path.lstat
            def lstat(path, *args, **kwargs):
                if path == target:
                    return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=0x400)
                return original(path, *args, **kwargs)
            with patch.object(Path, 'lstat', lstat), self.assertRaisesRegex(RuntimeError, 'link or reparse'):
                qt.reviewed_notice_bytes(target)

    def test_destination_symlink_preserves_target(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'target'
            target.mkdir()
            sentinel = Path(temp) / 'sentinel'
            sentinel.write_bytes(b'unchanged')
            (target / 'GPL-3.0-only.txt').symlink_to(sentinel)
            with self.assertRaisesRegex(RuntimeError, 'link or reparse'):
                qt.copy_notice_bytes({'GPL-3.0-only.txt': b'changed'}, target)
            self.assertEqual(sentinel.read_bytes(), b'unchanged')

    def test_filter_removes_only_unused_components_and_preserves_native_input(self):
        removed = [
            'libssl-3-x64.dll', 'libcrypto-3-x64.dll',
            'PySide6/plugins/tls/qopensslbackend.dll',
            'PySide6/Qt6VirtualKeyboard.dll',
            'PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll',
            'PySide6/qml/QtQuick/VirtualKeyboard/qmldir',
            'PySide6/resources/qtvirtualkeyboard.rcc',
            'PySide6/translations/qtvirtualkeyboard_zh_TW.qm',
            'resources/qtvirtualkeyboard.rcc', 'translations/qtvirtualkeyboard_zh_TW.qm',
            'PySide6/Qt6Pdf.dll', 'PySide6/Qt6PdfWidgets.dll',
            'PySide6/plugins/imageformats/qpdf.dll',
            'PySide6/translations/qtpdf_zh_TW.qm',
        ]
        retained = sorted(qt.REQUIRED) + ['reports/export.csv', 'licenses/other/NOTICE.txt']
        entries = [(name, 'inert-source', 'BINARY') for name in removed + retained]
        actual = qt.filter_payload_toc(entries)
        self.assertEqual([entry[0] for entry in actual], retained)
        self.assertIn('pyside6/plugins/platforms/qwindows.dll', retained)
        qt.audit_paths(retained)

    def test_unknown_module_binding_plugin_and_resource_fail_closed(self):
        for name in ('PySide6/Qt6Charts.dll', 'PySide6/Qt6Graphs.dll',
                     'PySide6/QtCharts.pyd', 'PySide6/plugins/new/unknown.dll',
                     'PySide6/qml/Unreviewed/qmldir', 'PySide6/resources/new.rcc',
                     'PySide6/Qt6VirtualKeyboard.dll', 'PySide6/Qt6Pdf.dll',
                     'libssl-3-x64.dll', 'libcrypto-3-x64.dll',
                     'PySide6/plugins/tls/qopensslbackend.dll'):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                qt.audit_paths(sorted(qt.REQUIRED) + [name])
        for name in ('../PySide6/Qt6Core.dll', 'C:/PySide6/Qt6Core.dll', '/PySide6/Qt6Core.dll'):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                qt.audit_paths([name], require_core=False)
        with self.assertRaisesRegex(RuntimeError, 'native Windows input'):
            qt.audit_paths(sorted(qt.REQUIRED - {'pyside6/plugins/platforms/qwindows.dll'}))

    def fixture_payload(self, temp):
        root = Path(temp) / 'MarkAuto'
        for relative in qt.REQUIRED:
            file = root / '_internal' / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'inert PE fixture; parser mocked')
        qt.copy_notice_bytes(qt.reviewed_notice_bytes(ROOT / 'packaging/qt_notices'), root / '_internal/licenses/qt')
        return root

    def test_actual_payload_audit_reports_limited_static_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture_payload(temp)
            with patch.object(qt, 'pe_version', return_value=(6, 12, 0, 0)), \
                    patch.object(qt, 'NATIVE_REQUIRED', frozenset()):
                result = qt.audit_payload(root)
            self.assertEqual(result['status'], 'PASS')
            self.assertFalse(result['virtual_keyboard_present'])
            self.assertFalse(result['qt_pdf_present'])
            self.assertEqual(len(result['binary_sha256']), 3)
            self.assertIn('NOT TESTED', result['native_ime_behavior'])
            self.assertIn('not full third-party legal clearance', result['scope'])

    def test_actual_payload_mismatch_and_missing_notice_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture_payload(temp)
            with patch.object(qt, 'pe_version', return_value=(6, 11, 0, 0)), self.assertRaisesRegex(RuntimeError, 'source version'):
                qt.audit_payload(root)
            (root / '_internal/licenses/qt/GPL-3.0-only.txt').unlink()
            with self.assertRaisesRegex(RuntimeError, 'missing or unreviewed'):
                qt.audit_payload(root)

    def test_missing_retained_python_https_pair_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture_payload(temp)
            with patch.object(qt, 'pe_version', return_value=(6, 12, 0, 0)):
                with self.assertRaisesRegex(RuntimeError, 'Python HTTPS libraries'):
                    qt.audit_payload(root)
        manifest = json.loads(qt.reviewed_notice_bytes(ROOT / 'packaging/qt_notices')['manifest.json'])
        for name in ('libssl-3.dll', 'libcrypto-3.dll'):
            self.assertEqual(manifest['native_binaries'][name]['version'], [3, 5, 9, 0])
        self.assertNotIn('libssl-3-x64.dll', manifest['native_binaries'])

    def test_actual_native_dependency_hash_change_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture_payload(temp)
            (root / '_internal/libssl-3.dll').write_bytes(b'unreviewed native library')
            with patch.object(qt, 'pe_version', return_value=(6, 12, 0, 0)):
                with self.assertRaisesRegex(RuntimeError, 'Unreviewed native'):
                    qt.audit_payload(root)

    def test_payload_directory_symlink_fails_before_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture_payload(temp)
            outside = Path(temp) / 'outside'
            outside.mkdir()
            (root / '_internal/linked-directory').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, 'link or reparse'):
                qt.audit_payload(root)

    def test_build_runs_actual_payload_audit_after_freezer_before_installer(self):
        build = (ROOT / 'packaging/build.ps1').read_text()
        self.assertLess(build.index('-m PyInstaller'), build.index('packaging/qt_licenses.py'))
        self.assertLess(build.index('packaging/qt_licenses.py'), build.index('ISCC.exe'))
        self.assertIn('qt-license-audit.json', build)
        spec = (ROOT / 'packaging/markauto.spec').read_text()
        self.assertIn("analysis.binaries = qt_licenses['filter_payload_toc'](analysis.binaries)", spec)
        self.assertIn("analysis.datas = qt_licenses['filter_payload_toc'](analysis.datas)", spec)


if __name__ == '__main__':
    unittest.main()

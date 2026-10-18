"""Offline P0-15/16 dependency archive and application artwork contracts."""
import ast
import hashlib
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QWidget

import desktop_icon
from tools.make_icon import SIZES, make_icon

ROOT = Path(__file__).resolve().parents[1]


class ApplicationIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ico_header_contains_all_required_sizes_and_valid_images(self):
        data = (ROOT / 'packaging/markauto.ico').read_bytes()
        self.assertEqual(struct.unpack_from('<HHH', data), (0, 1, 7))
        sizes = []
        for index in range(7):
            width, height, colors, reserved, planes, bits, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + index * 16)
            sizes.append(width or 256)
            self.assertEqual(width, height)
            self.assertEqual((colors, reserved, planes, bits), (0, 0, 1, 32))
            self.assertGreaterEqual(offset, 118)
            self.assertLessEqual(offset + length, len(data))
            self.assertTrue(data[offset:offset + length].startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(tuple(sizes), (16, 24, 32, 48, 64, 128, 256))
        self.assertEqual(tuple(sizes), SIZES)
        self.assertEqual(make_icon(), data)

    def test_real_icon_and_missing_development_file_fallback_are_non_null(self):
        icon = desktop_icon.application_icon(self.app)
        self.assertFalse(icon.isNull())
        self.assertEqual({s.width() for s in icon.availableSizes()}, set(SIZES))
        for size in SIZES:
            self.assertFalse(icon.pixmap(QSize(size, size)).isNull())
        with patch.object(desktop_icon, '__file__', str(ROOT / 'absent-artwork/desktop_icon.py')):
            fallback = desktop_icon.application_icon(self.app)
        self.assertFalse(fallback.isNull())
        previous = self.app.windowIcon()
        window = QWidget()
        try:
            self.app.setWindowIcon(icon)
            window.setWindowIcon(icon)
            self.assertFalse(self.app.windowIcon().isNull())
            self.assertFalse(window.windowIcon().isNull())
        finally:
            window.close()
            self.app.setWindowIcon(previous)

    def test_start_paths_apply_icon_and_freezer_installer_reference_same_artwork(self):
        for name in ('desktop.py', 'desktop_ui.py'):
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8-sig'))
            self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                                and node.func.attr == 'setWindowIcon' for node in ast.walk(tree)), name)
        spec = (ROOT / 'packaging/markauto.spec').read_text()
        self.assertIn("icon=str(root / 'packaging/markauto.ico')", spec)
        self.assertIn("(str(root / 'packaging/markauto.ico'), 'packaging')", spec)
        installer = (ROOT / 'packaging/markauto.iss').read_text(encoding='utf-8-sig')
        self.assertIn('SetupIconFile=markauto.ico', installer)
        self.assertIn(r'UninstallDisplayIcon={code:PayloadDir}\_internal\packaging\markauto.ico', installer)
        harness = (ROOT / 'packaging/test_installer.ps1').read_text()
        self.assertIn("if ($number -eq $Version)", harness)
        self.assertIn(r"'_internal\packaging\markauto.ico'", harness)
        self.assertIn('Installed application icon differs from build input', harness)

    def test_legacy_dependencies_are_archived_byte_identically_and_never_installed(self):
        self.assertFalse((ROOT / 'requirements.txt').exists())
        archived = ROOT / 'archives/legacy_autotrading/requirements.txt'
        # Git may check out text as CRLF on Windows or LF on Linux CI.
        canonical = archived.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         '6b7bc80e0d50e3633ad0087f40b55d7d1ff62fb346ac688fc7cb0519fafda9d7')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertNotIn('pip install -r requirements.txt', readme)
        self.assertIn('requirements-desktop.lock', readme)
        self.assertIn('packaging/build.ps1', readme)
        workflow = (ROOT / '.github/workflows/quantlab.yml').read_text()
        self.assertIn('archives/legacy_autotrading/requirements.txt is outside this audit', workflow)
        for lock in ('requirements-ui.lock', 'requirements-qt-ci.lock'):
            self.assertIn('requirements: ' + lock, workflow)
        self.assertIn('pip-audit', workflow)


if __name__ == '__main__':
    unittest.main()

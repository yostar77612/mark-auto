"""Failure-injection coverage for the offline quality/security gate."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.quality_gate import main, python_findings, scan, secret_findings


class QualityGateTests(unittest.TestCase):
    def test_secret_signatures_are_detected_without_value_disclosure(self):
        tokens = ["ghp_" + "a" * 36, "AKIA" + "A" * 16,
                  "xoxb-" + "a" * 30, "123456789:" + "a" * 35,
                  "-----BEGIN " + "PRIVATE KEY-----",
                  "sk-proj-" + "a" * 48, "sk-svcacct-" + "b" * 48,
                  "AIza" + "c" * 35]
        for token in tokens:
            with self.subTest(kind=token[:4]):
                findings = secret_findings("token = '" + token + "'", "fixture")
                self.assertTrue(findings)
                self.assertNotIn(token, "\n".join(findings))

    def test_ordinary_placeholders_do_not_trigger(self):
        self.assertEqual(secret_findings("API_KEY = 'your-api-key'\nTOKEN = ''", "fixture"), [])

    def test_invalid_syntax_is_redacted(self):
        secret = "ghp_" + "a" * 36
        findings = python_findings("'" + secret, "fixture.py")
        self.assertTrue(findings)
        self.assertNotIn(secret, str(findings))

    def test_compile_does_not_execute_or_import_legacy(self):
        self.assertEqual(python_findings("import trader\nraise RuntimeError('do not run')", "legacy.py"), [])
        self.assertTrue(python_findings("return 1", "invalid.py"))

    def test_research_boundary_rejects_imports_and_dynamic_execution(self):
        for source in ("import trader", "from shioaji import API", "import pickle",
                       "import subprocess", "eval('1')", "builtins.exec('1')"):
            self.assertTrue(python_findings(source, "quantlab/new.py", research=True))
        self.assertEqual(python_findings("import json", "quantlab/new.py", research=True), [])

    def test_desktop_boundary_allows_qt_but_rejects_legacy(self):
        self.assertEqual(python_findings("from PySide6.QtWidgets import QWidget",
                                       "desktop_ui.py", desktop=True), [])
        for source in ("import trader", "import shioaji", "eval('1')"):
            self.assertTrue(python_findings(source, "desktop_ui.py", desktop=True))

    def test_all_desktop_components_enforce_existing_execution_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("desktop_ui.py", "desktop_charts.py", "desktop_forms.py", "desktop_market.py",
                         "desktop_chatgpt_auth.py", "desktop_chatgpt_provider.py", "desktop_chatgpt_ui.py"):
                (root / name).write_text("import trader\n", encoding="utf-8")
                with patch("tools.quality_gate.git", return_value=(name+"\0").encode()):
                    self.assertTrue(scan(root), name)
                (root / name).write_text("from PySide6.QtWidgets import QWidget\n", encoding="utf-8")
                with patch("tools.quality_gate.git", return_value=(name+"\0").encode()):
                    self.assertEqual(scan(root), [], name)

    def test_research_dependencies_are_standard_library_only(self):
        for source in ("import PySide6", "from streamlit import title", "import requests"):
            self.assertTrue(python_findings(source, "quantlab/new.py", research=True))
        for source in ("from .core import Dataset", "from quantlab.core import Dataset", "import sqlite3"):
            self.assertEqual(python_findings(source, "quantlab/new.py", research=True), [])

    def test_desktop_runtime_bridge_is_narrow(self):
        source = "from desktop_ui import execute_ui_operation"
        self.assertEqual(python_findings(source, "quantlab/desktop_runtime.py", research=True), [])
        self.assertTrue(python_findings(source, "quantlab/core.py", research=True))
        self.assertTrue(python_findings("import PySide6", "quantlab/desktop_runtime.py", research=True))

    def test_cli_exits_nonzero_on_detection(self):
        secret = "ghp_" + "a" * 36
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(["git", "-C", directory, *args], check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git("init")
            (root / "bad.py").write_text("TOKEN = '" + secret + "'", encoding="utf-8")
            git("add", "bad.py")
            output = io.StringIO()
            with patch.object(sys, "argv", ["gate", "--root", directory]), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 1)
            self.assertNotIn(secret, output.getvalue())
            # Historical deletion must not hide the credential.
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
            (root / "bad.py").write_text("TOKEN = ''", encoding="utf-8")
            git("add", "bad.py")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "remove fixture")
            self.assertEqual(scan(root), [])
            findings = scan(root, history=True)
            self.assertTrue(any("history" in finding for finding in findings))
            self.assertNotIn(secret, str(findings))

    def test_non_utf8_python_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.py").write_bytes(b"# encoding: latin-1\nname = '\xff'\n")
            with patch("tools.quality_gate.git", return_value=b"bad.py\0"):
                self.assertEqual(scan(root), ["bad.py: Python source must be UTF-8"])

    def test_shallow_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("tools.quality_gate.git", side_effect=[b"", b"true\n"]):
                self.assertIn("history: full checkout required", scan(Path(directory), history=True))

    def test_git_failure_is_closed_and_redacted(self):
        output = io.StringIO()
        with patch("tools.quality_gate.scan", side_effect=OSError("secret error")), \
                patch.object(sys, "argv", ["gate"]), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertNotIn("secret error", output.getvalue())


if __name__ == "__main__":
    unittest.main()

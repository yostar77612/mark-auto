"""Cheap synthetic coverage for the formatting guard; no Ruff or git process."""

import contextlib
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.verify_format_equivalence import base_blobs, equivalent, verify


class FormatEquivalenceTests(unittest.TestCase):
    def test_reformat_preserves_ast(self):
        self.assertTrue(equivalent(b"\xef\xbb\xbfx = {'a': 1, 'b': 2}\r\n", b'x = {\n    "a": 1,\n    "b": 2,\n}\n'))

    def test_semantic_change_fails(self):
        self.assertFalse(equivalent(b"x = 1\n", b"x = 2\n"))

    def test_docstring_change_fails(self):
        self.assertFalse(equivalent(b'"""original"""\n', b'"""changed"""\n'))

    def test_batch_preserves_blob_boundaries_and_missing_sources(self):
        response = b"abc blob 6\nx = 1\n\nHEAD:new.py missing\n"
        with patch("tools.verify_format_equivalence.subprocess.run", return_value=SimpleNamespace(stdout=response)) as run:
            self.assertEqual(base_blobs(Path("."), "HEAD", ["old.py", "new.py"]), {"old.py": b"x = 1\n", "new.py": None})
        self.assertEqual(run.call_count, 1)

    def test_locked_and_outside_allowlist_changes_fail(self):
        for filename in ("quantlab/core.py", "unexpected.txt"):
            with (
                self.subTest(filename=filename),
                patch("tools.verify_format_equivalence.git", side_effect=[filename.encode() + b"\0", b""]),
                patch("tools.verify_format_equivalence.base_blobs", return_value={}),
                patch.object(Path, "exists", return_value=False),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(verify(Path(".")), 1)
                self.assertIn(filename + ": forbidden change", output.getvalue())


if __name__ == "__main__":
    unittest.main()

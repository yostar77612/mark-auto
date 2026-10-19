"""Cheap static Ruff/CI contracts: no subprocesses, network or Ruff execution."""

import ast
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RuffConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]
        cls.workflow = (ROOT / ".github/workflows/quantlab.yml").read_text(encoding="utf-8")

    def job(self, name):
        match = re.search(r"(?ms)^  " + re.escape(name) + r":\n.*?(?=^  [a-z][a-z0-9_-]*:\n|\Z)", self.workflow)
        self.assertIsNotNone(match, name)
        return match.group(0)

    def test_exact_g3_exclusions_derived_from_producer_hash_keys(self):
        tree = ast.parse((ROOT / "quantlab/saved_candidate_pool.py").read_text(encoding="utf-8-sig"))
        pinned = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        and key.value.endswith(".py")
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                        and re.fullmatch(r"[0-9a-f]{64}", value.value)
                    ):
                        pinned.add(key.value if key.value.startswith("desktop_") else "quantlab/" + key.value)
        self.assertEqual(len(pinned), 8)
        self.assertEqual(set(self.config["exclude"]), pinned)
        self.assertEqual(len(self.config["exclude"]), 8)

    def test_format_and_fix_policy(self):
        self.assertIs(self.config["force-exclude"], True)
        self.assertIs(self.config["fix"], False)
        self.assertEqual(self.config["target-version"], "py311")
        self.assertEqual(self.config["line-length"], 160)
        self.assertEqual(self.config["format"]["line-ending"], "lf")
        self.assertTrue({"E9", "F"} <= set(self.config["lint"]["select"]))
        self.assertFalse(self.config["lint"].get("ignore", []))

    def test_frozen_local_and_generated_paths_are_also_excluded(self):
        required = {
            "quantlab/saved_candidate_pool.py",
            "archives",
            ".claude",
            "AGENTS.md",
            "CLAUDE.md",
            ".tmp*",
            ".t*-work",
            "build",
            "dist",
            ".venv",
            ".runtime-sqlite",
            ".git",
            ".gitnexus",
            "tests/fixtures",
        }
        self.assertTrue(required <= set(self.config["extend-exclude"]))

    def test_hash_lock_is_pinned_and_well_formed(self):
        source = (ROOT / "requirements-ruff.lock").read_text(encoding="utf-8")
        lines = [line.strip() for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        records = " ".join(line.removesuffix("\\").strip() for line in lines)
        tokens = records.split()
        self.assertGreater(len(tokens), 1)
        self.assertEqual(tokens[0], "ruff==0.16.10")
        for token in tokens[1:]:
            self.assertRegex(token, r"^--hash=sha256:[0-9a-f]{64}$")
        self.assertEqual(len(tokens[1:]), len(set(tokens[1:])))

    def test_workflow_uses_only_hash_locked_ruff_installation(self):
        job = self.job("ruff")
        self.assertIn("runs-on: ubuntu-latest", job)
        self.assertIn("timeout-minutes: 3", job)
        self.assertIn("python-version: '3.11'", job)
        self.assertIn("python -m pip install --require-hashes -r requirements-ruff.lock", job)
        self.assertIn("- run: ruff check .", job)
        self.assertIn("- run: ruff format --check .", job)
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            for line in workflow.read_text(encoding="utf-8").splitlines():
                if re.search(r"\bpip\b.*\binstall\b.*\bruff\b", line):
                    self.assertIn("--require-hashes", line)
                    self.assertIn("-r requirements-ruff.lock", line)
                    self.assertNotRegex(line, r"\binstall\s+ruff(?:\s|[=<>!~]|$)")
        for action in ("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"):
            self.assertIn(action, job)

    def test_aggregate_audit_and_publication_require_ruff(self):
        aggregate = self.job("core-coverage")
        self.assertIn("needs: [offline, ruff]", aggregate)
        self.assertIn("sys.exit(0 if '${{ needs.ruff.result }}' == 'success' else 1)", aggregate)
        self.assertNotIn("continue-on-error", aggregate)
        security = self.job("security")
        self.assertIn("profile: ruff", security)
        self.assertIn("requirements: requirements-ruff.lock", security)
        self.assertIn("--target audit-runtime --require-hashes -r requirements-ruff.lock", security)
        self.assertIn("pip_audit --path audit-runtime", security)
        self.assertIn("--strict", security)
        tree = ast.parse((ROOT / "packaging/wait_for_gates.py").read_text(encoding="utf-8"))
        required = next(
            node.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "REQUIRED_JOBS" for t in node.targets)
        )
        self.assertTrue({"Ruff lint and format", "Dependency audit (ruff)"} <= ast.literal_eval(required.args[0]))

    def test_lf_attributes_cover_python_and_lock_only(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.py text eol=lf", attributes)
        self.assertIn("requirements-ruff.lock text eol=lf", attributes)


if __name__ == "__main__":
    unittest.main()

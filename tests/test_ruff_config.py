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
        # Producer keys are historical identities, independent of current paths.
        moved = {
            'assistant_domain_init.py': 'quantlab/assistant/domain/__init__.py',
            'assistant_ports_init.py': 'quantlab/assistant/ports/__init__.py',
            'research_domain_init.py': 'quantlab/research_core/domain/__init__.py',
            'desktop_chatgpt_auth.py': 'quantlab/assistant/adapters/chatgpt/auth.py',
            'desktop_chatgpt_provider.py': 'quantlab/assistant/adapters/chatgpt/provider.py',
            'chatgpt_vault.py': 'quantlab/assistant/adapters/chatgpt/vault.py',
            'chatgpt_identity.py': 'quantlab/assistant/adapters/chatgpt/identity.py',
            'chatgpt_loopback.py': 'quantlab/assistant/adapters/chatgpt/loopback.py',
            'chatgpt_account_summary.py': 'quantlab/assistant/adapters/chatgpt/account_summary.py',
            'chatgpt_account_paths.py': 'quantlab/assistant/adapters/chatgpt/account_paths.py',
            'chatgpt_response_stream.py': 'quantlab/assistant/adapters/chatgpt/response_stream.py',
            'chatgpt_transport.py': 'quantlab/assistant/adapters/chatgpt/transport.py',
            'chatgpt_provenance.py': 'quantlab/assistant/adapters/chatgpt/provenance.py',
            'chatgpt_account_store.py': 'quantlab/assistant/adapters/chatgpt/account_store.py',
            'chatgpt_resolution_audit.py': 'quantlab/assistant/adapters/chatgpt/resolution_audit.py',
            'chatgpt_unknown_reconciliation.py': 'quantlab/assistant/adapters/chatgpt/unknown_reconciliation.py',
            'chatgpt_finished_reconciliation.py': 'quantlab/assistant/adapters/chatgpt/finished_reconciliation.py',
            'chatgpt_campaign_receipts.py': 'quantlab/assistant/adapters/chatgpt/campaign_receipts.py',
            'assistant_auth_protocol.py': 'quantlab/assistant/domain/auth_protocol.py',
            'assistant_auth_tokens.py': 'quantlab/assistant/domain/auth_tokens.py',
            'assistant_plan_protocol.py': 'quantlab/assistant/domain/plan_protocol.py',
            'assistant_source_components.py': 'quantlab/assistant/domain/source_components.py',
            'assistant_auth_ports.py': 'quantlab/assistant/ports/auth.py',
            'research_receipts.py': 'quantlab/research_core/domain/receipts.py',
        }
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
                        pinned.add(moved.get(key.value, "quantlab/" + key.value))
        self.assertEqual(len(pinned), 30)
        self.assertEqual(
            pinned,
            {
                'quantlab/strategies.py',
                'quantlab/backtest.py',
                'quantlab/research.py',
                'quantlab/assistant/adapters/chatgpt/vault.py',
                'quantlab/assistant/domain/source_components.py',
                'quantlab/assistant/ports/auth.py',
                'quantlab/assistant/domain/plan_protocol.py',
                'quantlab/assistant/adapters/chatgpt/auth.py',
                'quantlab/assistant/adapters/chatgpt/unknown_reconciliation.py',
                'quantlab/assistant/domain/auth_tokens.py',
                'quantlab/assistant/ports/__init__.py',
                'quantlab/assistant/adapters/chatgpt/account_summary.py',
                'quantlab/provider.py',
                'quantlab/assistant/adapters/chatgpt/account_paths.py',
                'quantlab/assistant/adapters/chatgpt/transport.py',
                'quantlab/assistant/adapters/chatgpt/finished_reconciliation.py',
                'quantlab/assistant/adapters/chatgpt/identity.py',
                'quantlab/assistant/adapters/chatgpt/provenance.py',
                'quantlab/assistant/adapters/chatgpt/provider.py',
                'quantlab/data.py',
                'quantlab/assistant/domain/__init__.py',
                'quantlab/assistant/adapters/chatgpt/campaign_receipts.py',
                'quantlab/assistant/domain/auth_protocol.py',
                'quantlab/assistant/adapters/chatgpt/response_stream.py',
                'quantlab/core.py',
                'quantlab/research_core/domain/receipts.py',
                'quantlab/research_core/domain/__init__.py',
                'quantlab/assistant/adapters/chatgpt/account_store.py',
                'quantlab/assistant/adapters/chatgpt/resolution_audit.py',
                'quantlab/assistant/adapters/chatgpt/loopback.py',
            },
        )
        for path in pinned:
            self.assertTrue((ROOT / path).is_file(), path)
        self.assertEqual(set(self.config["exclude"]), pinned)
        self.assertEqual(len(self.config["exclude"]), 30)

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
        self.assertIn("needs: [changes, offline, ruff]", aggregate)
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

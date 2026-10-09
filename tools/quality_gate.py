"""Offline static gate; never imports application or legacy modules.

Scans tracked files for high-confidence credential signatures, compiles Python
without executing it, and enforces the research import boundary. This is not a
complete secret detector or a security audit of the disabled legacy dependency set.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import subprocess
import sys


SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "openai-key": re.compile(r"\bsk-(?:proj|svcacct)-[A-Za-z0-9_-]{40,}\b"),
    "google-api-key": re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "telegram-token": re.compile(r"\b[0-9]{8,12}:[A-Za-z0-9_-]{35}\b"),
}
BANNED_IMPORTS = {"trader", "shioaji", "pickle", "subprocess"}
BANNED_CALLS = {"eval", "exec", "compile", "__import__"}


def secret_findings(source: str, label: str) -> list[str]:
    """Only locations and rule names leave this function, never matched values."""
    return [f"{label}:{source.count(chr(10), 0, match.start()) + 1}: {name}"
            for name, pattern in SECRET_PATTERNS.items()
            for match in pattern.finditer(source)]


def python_findings(source: str, label: str, research: bool = False,
                    desktop: bool = False) -> list[str]:
    try:
        tree = ast.parse(source, filename=label)
        compile(tree, label, "exec")
    except (SyntaxError, ValueError, TypeError):
        # SyntaxError text can contain a credential literal; do not print it.
        return [f"{label}: invalid Python syntax"]
    findings = []
    if research or desktop:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [item.name.split(".")[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "").split(".")[0]]
            else:
                modules = []
            if research and modules and not (isinstance(node, ast.ImportFrom) and node.level):
                # The isolated desktop worker lazily dispatches to our root GUI
                # module. It is first-party, not a third-party research dependency.
                first_party = {"quantlab"}
                if label == "quantlab/desktop_runtime.py":
                    first_party.add("desktop_ui")
                if set(modules) - sys.stdlib_module_names - first_party:
                    findings.append(f"{label}:{node.lineno}: research dependency must be standard library")
            if BANNED_IMPORTS.intersection(modules):
                findings.append(f"{label}:{node.lineno}: forbidden research import")
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else "")
                if name in BANNED_CALLS:
                    findings.append(f"{label}:{node.lineno}: dynamic execution")
    return findings


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def scan(root: Path, history: bool = False) -> list[str]:
    findings = []
    names = git(root, "ls-files", "-z").decode("utf-8").split("\0")
    for name in filter(None, names):
        path = root / name
        if not path.is_file():
            findings.append(f"{name}: tracked file missing")
            continue
        raw = path.read_bytes()
        # Binary assets are out of scope; Python must always be explicit UTF-8.
        if b"\0" in raw and path.suffix != ".py":
            continue
        try:
            source = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            if path.suffix == ".py":
                findings.append(f"{name}: Python source must be UTF-8")
            continue
        findings.extend(secret_findings(source, name))
        if path.suffix == ".py":
            findings.extend(python_findings(source, name, name.startswith("quantlab/"),
                                            desktop=name == "desktop_ui.py"))
    if history:
        if git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
            findings.append("history: full checkout required")
        else:
            # Scan added text across all fetched refs, including removed secrets.
            patch = git(root, "log", "--all", "--format=", "--no-ext-diff", "--unified=0", "-p")
            added = "\n".join(line[1:] for line in patch.decode("utf-8", errors="replace").splitlines()
                              if line.startswith("+") and not line.startswith("+++"))
            findings.extend(secret_findings(added, "history (added-line index)"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    try:
        findings = scan(args.root, args.history)
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
        print("Static gate could not complete; fail closed (details redacted).")
        return 1
    for finding in findings:
        print(finding)
    print(f"Static gate: {len(findings)} finding(s). Credential values are never printed.")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())

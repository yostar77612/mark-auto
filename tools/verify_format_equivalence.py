"""Verify a formatting worktree against a git ref without importing product code."""

import argparse
import ast
from fnmatch import fnmatchcase
import io
import json
from pathlib import Path
import subprocess

LOCKED = frozenset(
    {
        "quantlab/research.py",
        "quantlab/provider.py",
        "quantlab/core.py",
        "quantlab/strategies.py",
        "quantlab/backtest.py",
        "quantlab/data.py",
        "desktop_chatgpt_auth.py",
        "desktop_chatgpt_provider.py",
        "quantlab/saved_candidate_pool.py",
    }
)


def equivalent(before: bytes, after: bytes) -> bool:
    """Compare syntax trees, including string constants but excluding locations."""
    return ast.dump(ast.parse(before.decode("utf-8-sig")), include_attributes=False) == ast.dump(ast.parse(after.decode("utf-8-sig")), include_attributes=False)


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def base_blobs(root: Path, base: str, names: list[str]) -> dict[str, bytes | None]:
    """Read all base blobs in one process to keep a repository-wide check cheap."""
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="".join(f"{base}:{name}\n" for name in names).encode("utf-8"),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stream = io.BytesIO(result.stdout)
    blobs = {}
    for name in names:
        header = stream.readline().rstrip(b"\n")
        if header.endswith(b" missing"):
            blobs[name] = None
        else:
            size = int(header.rsplit(b" ", 1)[1])
            blobs[name] = stream.read(size)
            if stream.read(1) != b"\n":
                raise ValueError("Invalid git batch response")
    return blobs


def verify(root: Path, base: str = "HEAD") -> int:
    """Check tracked changes and new project Python; ignore unrelated local files."""
    names = set(filter(None, git(root, "diff", "--name-only", "-z", base, "--").decode("utf-8").split("\0")))
    # User-local inputs are deliberately outside the project change inventory.
    local = (".claude", "AGENTS.md", "CLAUDE.md", ".tmp*", ".t*-work", "build")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
    names.update(name for name in untracked if name and not any(fnmatchcase(name.split("/")[0], pattern) for pattern in local))
    manifest = root / "docs/analysis/t13_golden_changes.json"
    allowed = set(json.loads(manifest.read_text(encoding="utf-8-sig")).get("files", [])) if manifest.exists() else set()
    checked = 0
    errors = []
    blobs = base_blobs(root, base, sorted(name for name in names if name.endswith(".py") and name not in LOCKED))
    for name in sorted(names):
        if name in LOCKED or (not name.endswith(".py") and name not in allowed):
            errors.append(f"{name}: forbidden change")
            continue
        if not name.endswith(".py"):
            continue
        try:
            after = (root / name).read_bytes()
            if blobs[name] is None:
                if name not in {"tools/verify_format_equivalence.py", "tests/test_format_equivalence.py"}:
                    raise ValueError("no base source")
                ast.parse(after.decode("utf-8-sig"))
                print(f"{name}: new source parsed (no base blob)")
                continue
            checked += 1
            print(name)
            if not equivalent(blobs[name], after):
                errors.append(f"{name}: AST mismatch")
        except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
            errors.append(f"{name}: {type(exc).__name__}")
    for error in errors:
        print(error)
    print(f"{checked} files checked, {len(errors)} mismatches")
    return int(bool(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", nargs="?", default="HEAD")
    args = parser.parse_args()
    return verify(Path(__file__).resolve().parents[1], args.base)


if __name__ == "__main__":
    raise SystemExit(main())

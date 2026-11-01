"""Print the test modules a change needs, as one ready-to-run unittest command (work rule R8).

The changed-file list comes from ``git diff`` against the merge base with ``--base``
(default ``origin/main``, including uncommitted and untracked files) or from ``--files``.
A test module is selected when it, or anything it imports, changed. Imports are resolved
with the layer gate's module index, including local/conditional imports and the parent
package initializers they execute. Test files also reach code by string: dotted module names
(``patch('pkg.mod.name')``) and repository file paths (source/fixture/doc pins) count
as dependencies. The string catalog (``desktop_app/strings``) is treated as data: it reaches
only the tests that import it, plus the static string pins, never every UI module. Static rules add the baseline-pinning modules for strings, inventory,
styles and page services, and escalate to the full suite for packaging, installer,
workflow, G3 locked files and layer rules.

A passing selection never replaces CI, which always runs the full suite.
"""

from __future__ import annotations

import argparse
import ast
from collections import deque
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_layers import module_index, resolve_target
from tools.check_trading_architecture import _module, _relative
from tools.quality_gate import git

ROOT = Path(__file__).resolve().parents[1]
FULL_COMMAND = 'python -m unittest discover -s tests'
STRINGS_PREFIX = 'desktop_app/strings/'
TEST_FILE = re.compile(r'^tests/(test_[^/]+)\.py$')
DOTTED = re.compile(r'^[A-Za-z_]\w*(\.\w+)+$')
GENERIC_NAMES = frozenset({'README.md', '__init__.py', 'LICENSE', '.gitignore', 'CONTRIBUTING.md'})
LAYER_FILES = frozenset({'tools/layer_map.json', 'tools/layer_allowlist.json', 'tools/layer_relocations.json', 'tools/check_layers.py'})
WORKFLOW_FILES = frozenset({'pyproject.toml', '.gitattributes', 'tools/ci_changes.py', 'tools/run_test_group.py', 'tools/ui_test_gate.py'})
PRESERVED_BYTE_FOR_BYTE = 'quantlab/saved_candidate_pool.py'
STRING_PINS = (
    'test_desktop_catalog_split',
    'test_desktop_text_aliases',
    'test_desktop_strings',
    'test_catalog_placeholders',
    'test_no_hardcoded_ui_text',
    'test_glossary_terms',
)
INVENTORY_PINS = ('test_layer_gate', 'test_repo_layout', 'test_import_graph', 'test_docs_layering')
STYLE_PINS = ('test_b4_appearance', 'test_no_inline_stylesheet', 'test_desktop_theme')
SERVICE_PINS = ('test_page_services_r1', 'test_download_auto_import_contracts')
DOC_PINS = ('test_docs_layering', 'test_repo_layout')


def changed_files(root: Path, base: str) -> dict[str, str]:
    """Path -> A/M/D versus the merge base, including uncommitted and untracked files."""
    fork = git(root, 'merge-base', base, 'HEAD').decode().strip()
    fields = git(root, 'diff', '--name-status', '--no-renames', '-z', fork).decode('utf-8').split('\0')
    result = {path: status[0] for status, path in zip(fields[0::2], fields[1::2])}
    for path in filter(None, git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode('utf-8').split('\0')):
        result[path] = 'A'
    return result


def g3_locked(root: Path) -> frozenset[str]:
    text = (root / 'docs/CONTRIBUTING.md').read_text(encoding='utf-8')
    section = text.split('G3 locked file set', 1)[1].split('The owner approved', 1)[0]
    return frozenset(re.findall(r'^- `([^`]+\.py)`$', section, re.M)) | {PRESERVED_BYTE_FOR_BYTE}


def source_paths(root: Path) -> tuple[str, ...]:
    names = git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '*.py').decode('utf-8').split('\0')
    return tuple(name for name in names if name and not name.startswith('archives/') and (root / name).is_file())


class Graph:
    """Forward dependency edges from imports plus module-name and file-path strings."""

    def __init__(self, root: Path):
        self.root = root
        self.paths = source_paths(root)
        self.files = frozenset(git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').decode('utf-8').split('\0')) - {''}
        self.modules = module_index(self.paths)
        self.texts = {path: (root / path).read_bytes().decode('utf-8-sig') for path in self.paths}
        self.edges = {path: self._dependencies(path) for path in self.paths}
        self.dependents: dict[str, set[str]] = {}
        for path, targets in self.edges.items():
            for target in targets:
                self.dependents.setdefault(target, set()).add(path)

    def _file_for(self, name: str) -> list[str]:
        """The module's file plus the parent package initializers an import executes."""
        target, path = resolve_target(name, self.modules)
        if path is None:
            return []
        parts = target.split('.')
        found = [self.modules.get('.'.join(parts[:n])) for n in range(1, len(parts) + 1)]
        return [item for item in found if item and not item.endswith('/')]

    def _imported_names(self, tree: ast.AST, path: str) -> set[str]:
        _, package = _module(path)
        is_test = path.startswith('tests/')
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _relative('.' * node.level + (node.module or ''), package)
                if base is not None:
                    names.add(base)
                    names.update(base + '.' + alias.name for alias in node.names if alias.name != '*')
            elif is_test and isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in self.files:
                    names.add('file:' + node.value)
                elif DOTTED.match(node.value) and node.value.split('.')[0] in self.modules:
                    names.add(node.value)
        return names

    def _dependencies(self, path: str) -> set[str]:
        targets = set()
        for name in self._imported_names(ast.parse(self.texts[path], filename=path), path):
            if name.startswith('file:'):
                targets.add(name[5:])
            else:
                targets.update(self._file_for(name))
        targets.discard(path)
        return targets

    def affected(self, seeds: dict[str, str]) -> dict[str, str]:
        """Every file that transitively depends on a seed -> the seed that reaches it."""
        reached = dict(seeds)
        queue = deque(seeds)
        while queue:
            current = queue.popleft()
            data_only = current.startswith(STRINGS_PREFIX)
            for dependent in self.dependents.get(current, ()):
                # String catalog files are data: they reach only the tests that import them, not every UI module.
                if dependent not in reached and not (data_only and not dependent.startswith('tests/')):
                    reached[dependent] = reached[current]
                    queue.append(dependent)
        return reached

    def referencing(self, target: str, dotted: str | None) -> list[str]:
        """Python files naming a non-importable or deleted target by path, module name or unique data-file name."""
        name = Path(target).name
        unique = name not in GENERIC_NAMES and not name.endswith('.py') and sum(Path(f).name == name for f in self.files) <= 1
        needles = [target] + ([name] if unique else []) + ([dotted] if dotted else [])
        return [path for path, text in self.texts.items() if any(needle in text for needle in needles)]


def static_selection(changes: dict[str, str], root: Path) -> tuple[list[str], dict[str, str]]:
    """Reasons that force the full suite, and extra baseline-pinning modules with reasons."""
    locked, full, extra = g3_locked(root), [], {}

    def pin(reason: str, modules: tuple[str, ...]) -> None:
        for module in modules:
            extra.setdefault(module, reason)

    for path, status in sorted(changes.items()):
        if path.startswith(('packaging/', '.github/workflows/', 'requirements')) or path.endswith(('.spec', '.iss')) or path in WORKFLOW_FILES:
            full.append(f'{path}: packaging/installer/workflow input')
        elif path in locked:
            full.append(f'{path}: G3 locked file')
        elif path in LAYER_FILES:
            full.append(f'{path}: layer rules')
        if path.startswith(STRINGS_PREFIX):
            pin(f'{path}: string catalog change', STRING_PINS)
        registered = path.endswith('.py') and status in 'AD' and not path.startswith(('tests/', 'archives/'))
        if registered or path == 'docs/analysis/08_REFACTOR_INVENTORY.md':
            pin(f'{path}: file registration', INVENTORY_PINS)
        if path.startswith('desktop_app/shell/theme') or 'stylesheet' in path:
            pin(f'{path}: stylesheet change', STYLE_PINS)
        if path.startswith('desktop_app/shell/') or (path.startswith('tests/') and path.endswith('.py')):
            pin(f'{path}: page service observers and their line pins', SERVICE_PINS)
        if path.endswith('.md') or path.startswith('docs/'):
            pin(f'{path}: documentation', DOC_PINS)
    return full, extra


def select(changes: dict[str, str], root: Path) -> tuple[list[str], dict[str, str]]:
    """(full-suite reasons, module -> reason)."""
    full, extra = static_selection(changes, root)
    if full:
        return full, {}
    graph = Graph(root)
    live = {path: path for path, status in changes.items() if status != 'D' and path in graph.edges}
    modules = {}
    for path, seed in graph.affected(live).items():
        match = TEST_FILE.match(path)
        if match:
            modules[match[1]] = 'itself changed' if path == seed else f'depends on {seed}'
    for path, status in changes.items():
        if path not in graph.edges or status == 'D':
            dotted = _module(path)[0] if path.endswith('.py') else None
            for reader in graph.referencing(path, dotted):
                match = TEST_FILE.match(reader)
                if match:
                    modules.setdefault(match[1], f'references {path}')
    existing = {name for name in graph.texts if TEST_FILE.match(name)}
    for module, reason in extra.items():
        if f'tests/{module}.py' in existing:
            modules.setdefault(module, reason)
    return [], modules


def command(modules: list[str], discover: bool) -> str:
    if discover:
        return ' && '.join(f'python -m unittest discover -s tests -p {name}.py' for name in modules)
    return 'python -m unittest ' + ' '.join(f'tests.{name}' for name in modules)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--base', default='origin/main', help='diff against the merge base with this ref (default origin/main)')
    parser.add_argument('--files', nargs='+', help='use this changed-file list instead of git diff (existing files count as modified, missing as deleted)')
    parser.add_argument('--discover', action='store_true', help='emit one discovery command per module (CONTRIBUTING form) instead of dotted names')
    parser.add_argument('--list', action='store_true', help='print one module per line instead of a command')
    parser.add_argument('-q', '--quiet', action='store_true', help='do not print the reasons on stderr')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    changes = {path: 'M' if (root / path).exists() else 'D' for path in args.files} if args.files else changed_files(root, args.base)
    full, modules = select(changes, root)
    if not args.quiet:
        for reason in full or []:
            print(f'full suite: {reason}', file=sys.stderr)
        for module, reason in sorted(modules.items()):
            print(f'{module}: {reason}', file=sys.stderr)
    if full:
        print(FULL_COMMAND)
    elif not modules:
        print('# no affected test modules (CI still runs the full suite)')
    elif args.list:
        print('\n'.join(sorted(modules)))
    else:
        print(command(sorted(modules), args.discover))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

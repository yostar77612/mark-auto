"""AST layer gate for v2, including relative imports and known dynamic loaders.

Runtime is the explicit composition root. This gate complements the existing
research/credential gate; it does not replace or relax any v1 prohibition.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import sys

PREFIX = 'quantlab.trading.'
IO_MODULES = frozenset(
    ('sqlite3', 'dbm', 'shelve', 'ctypes', 'subprocess', 'multiprocessing', 'socket', 'urllib', 'http', 'tkinter', 'webbrowser', 'os', 'pathlib')
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    target: str


def _within(target: str, prefix: str) -> bool:
    return target == prefix or target.startswith(prefix + '.')


def _layer(path: str) -> str:
    normalized = path.replace('\\', '/')
    if normalized.startswith('desktop_app/features/trading/'):
        return 'presentation'
    if normalized.startswith('quantlab/trading/'):
        parts = normalized.split('/')
        return parts[2] if len(parts) > 3 else 'package'
    return 'outside'


def _module(path: str) -> tuple[str, str]:
    parts = list(Path(path.replace('\\', '/')).with_suffix('').parts)
    is_package = parts[-1] == '__init__'
    if is_package:
        parts.pop()
    name = '.'.join(parts)
    return name, name if is_package else '.'.join(parts[:-1])


def _relative(target: str, package: str) -> str | None:
    dots = len(target) - len(target.lstrip('.'))
    if not dots:
        return target
    parts = package.split('.')
    if dots > len(parts):
        return None
    suffix = target[dots:]
    return '.'.join(parts[: len(parts) - dots + 1] + ([suffix] if suffix else []))


def _allowed(layer: str, target: str) -> bool:
    if layer in ('outside', 'runtime'):
        return True
    root = target.split('.')[0]
    if layer == 'presentation':
        return (
            root in sys.stdlib_module_names
            and root not in IO_MODULES
            or root == 'PySide6'
            or _within(target, 'desktop_app.strings.catalog')
            or _within(target, 'desktop_app.features.trading')
            or _within(target, PREFIX + 'application.contracts')
            or _within(target, PREFIX + 'domain.models')
        )
    if root in sys.stdlib_module_names:
        if layer == 'ports' and target == 'pathlib.Path':
            return True  # immutable location value in the storage protocol
        return layer == 'adapters' or root not in IO_MODULES
    if layer == 'package':
        return target.startswith(PREFIX)
    layers = {
        'domain': ('domain',),
        'ports': ('domain', 'ports'),
        'application': ('domain', 'ports', 'application'),
        'adapters': ('domain', 'ports', 'adapters'),
    }
    if any(_within(target, PREFIX + item) for item in layers.get(layer, ())):
        return True
    return layer in ('application', 'adapters') and _within(target, 'quantlab.errors')


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        return left + right if left is not None and right is not None else None
    return None


def check_source(source: str, path: str) -> tuple[Finding, ...]:
    """Check one source without importing it or executing dynamic expressions."""
    layer = _layer(path)
    if layer == 'outside':
        return ()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return (Finding(path, exc.lineno or 1, 'invalid-syntax', ''),)
    _, package = _module(path)
    aliases: dict[str, str] = {}
    findings: list[Finding] = []
    # Independently enforce the one owner-authorized lazy SDK import. This does
    # not allow SDK dependencies elsewhere in adapters or the shared layers.
    sdk_loader_body = {
        id(node)
        for function in tree.body
        if path == 'quantlab/trading/adapters/shioaji/sdk_loader.py' and isinstance(function, ast.FunctionDef) and function.name == 'load_pinned_sdk'
        for statement in function.body
        for node in ast.walk(statement)
    }
    sdk_parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)} if sdk_loader_body else {}

    def target(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return aliases.get(
                node.id,
                node.id if node.id in ('__import__', 'getattr', 'eval', 'exec', 'compile', 'open', 'vars', 'locals', 'globals', 'setattr', 'delattr') else None,
            )
        if isinstance(node, ast.Attribute):
            base = target(node.value)
            return base + '.' + node.attr if base else None
        if isinstance(node, ast.Call) and target(node.func) in ('getattr', 'builtins.getattr') and len(node.args) >= 2:
            base, attribute = target(node.args[0]), _literal(node.args[1])
            return base + '.' + attribute if base and attribute is not None else None
        return None

    def record(node: ast.AST, name: str | None, rule: str = 'forbidden-dependency') -> None:
        if id(node) in sdk_loader_body and (
            isinstance(node, ast.Import)
            and name == 'shioaji'
            and all(item.name == 'shioaji' for item in node.names)
            or isinstance(node, ast.Call)
            and name == 'shioaji.__version__'
            and target(node.func) in ('getattr', 'builtins.getattr')
            or isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and name == 'shioaji.__version__'
        ):
            return
        if name is None or not _allowed(layer, name):
            findings.append(Finding(path, node.lineno, rule, name or '<unresolved>'))

    # Lexical imports and simple aliases also cover imports inside functions and
    # TYPE_CHECKING blocks. Shadowing does not excuse a forbidden dependency.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
                record(node, item.name)
        elif isinstance(node, ast.ImportFrom):
            base = _relative('.' * node.level + (node.module or ''), package)
            for item in node.names:
                name = base + '.' + item.name if base and item.name != '*' else base
                aliases[item.asname or item.name] = name or '<unresolved>'
                record(node, name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = target(node.value) if node.value is not None else None
            names = node.targets if isinstance(node, ast.Assign) else (node.target,)
            if value:
                for name in names:
                    if isinstance(name, ast.Name):
                        aliases[name.id] = value
    for node in ast.walk(tree):
        if path == 'quantlab/trading/adapters/shioaji/sdk_loader.py' and isinstance(node, ast.Name) and target(node) == 'shioaji':
            parent = sdk_parents.get(id(node))
            metadata_read = (
                isinstance(parent, ast.Attribute)
                and parent.value is node
                and parent.attr == '__version__'
                and isinstance(parent.ctx, ast.Load)
                or isinstance(parent, ast.Call)
                and target(parent.func) in ('getattr', 'builtins.getattr')
                and len(parent.args) >= 2
                and parent.args[0] is node
                and _literal(parent.args[1]) == '__version__'
            )
            explicit_return = isinstance(parent, ast.Return) and parent.value is node
            if id(node) not in sdk_loader_body or not (metadata_read or explicit_return):
                findings.append(Finding(path, node.lineno, 'sdk-loader-module-escape', 'shioaji'))
        if path == 'quantlab/trading/adapters/shioaji/sdk_loader.py' and isinstance(node, ast.Attribute):
            name = target(node)
            if name is not None and name.startswith('shioaji.'):
                record(node, name, 'sdk-loader-metadata-only')
        if not isinstance(node, ast.Call):
            continue
        call = target(node.func)
        if path == 'quantlab/trading/adapters/shioaji/sdk_loader.py':
            if call in (
                'vars',
                'locals',
                'globals',
                'setattr',
                'delattr',
                'builtins.vars',
                'builtins.locals',
                'builtins.globals',
                'builtins.setattr',
                'builtins.delattr',
            ):
                findings.append(Finding(path, node.lineno, 'sdk-loader-reflection', call))
            elif call is not None and call.startswith('shioaji.'):
                record(node, call, 'sdk-loader-call-forbidden')
        if call in ('importlib.import_module', '__import__', 'builtins.__import__'):
            if layer == 'runtime':
                continue  # explicit composition scope; credential gate remains active
            if not node.args:
                record(node, None, 'dynamic-import-unresolved')
                continue
            literal = _literal(node.args[0])
            if literal is None:
                record(node, None, 'dynamic-import-unresolved')
                continue
            dynamic_package = package
            if len(node.args) > 1:
                dynamic_package = _literal(node.args[1]) or (package if isinstance(node.args[1], ast.Name) and node.args[1].id == '__package__' else '')
            for keyword in node.keywords:
                if keyword.arg == 'package':
                    dynamic_package = _literal(keyword.value) or (package if isinstance(keyword.value, ast.Name) and keyword.value.id == '__package__' else '')
            resolved = _relative(literal, dynamic_package) if literal.startswith('.') and dynamic_package else literal if not literal.startswith('.') else None
            record(node, resolved)
        elif call in ('eval', 'exec', 'compile', 'builtins.eval', 'builtins.exec', 'builtins.compile') and layer != 'runtime':
            findings.append(Finding(path, node.lineno, 'dynamic-execution', call))
        elif call in ('open', 'builtins.open', 'io.open') and layer in ('domain', 'ports', 'application', 'presentation'):
            findings.append(Finding(path, node.lineno, 'direct-filesystem-io', call))
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in ('read_text', 'read_bytes', 'write_text', 'write_bytes', 'mkdir', 'unlink', 'rmdir', 'iterdir', 'glob', 'rglob')
            and layer in ('domain', 'ports', 'application', 'presentation')
        ):
            findings.append(Finding(path, node.lineno, 'direct-filesystem-io', node.func.attr))
        elif call in ('getattr', 'builtins.getattr') and len(node.args) >= 2:
            base, attribute = target(node.args[0]), _literal(node.args[1])
            if base is not None and (base.startswith(('quantlab', 'desktop', 'PySide6', 'shioaji')) or base in IO_MODULES):
                record(node, base + '.' + attribute if attribute is not None else None, 'dynamic-dependency')
    unique = {(item.path, item.line, item.rule, item.target): item for item in findings}
    return tuple(unique[key] for key in sorted(unique))


def scan(root: Path) -> tuple[Finding, ...]:
    findings = []
    for scope in ('quantlab/trading', 'desktop_app/features/trading'):
        directory = root / scope
        if not directory.is_dir():
            findings.append(Finding(scope, 0, 'required-scope-missing', scope))
            continue
        for path in sorted(directory.rglob('*.py')):
            findings.extend(check_source(path.read_text(encoding='utf-8-sig'), path.relative_to(root).as_posix()))
    return tuple(findings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    findings = scan(args.root.resolve())
    for item in findings:
        print(f'{item.path}:{item.line}: {item.rule}: {item.target}')
    print(f'Trading v2 architecture: {len(findings)} violation(s)')
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())

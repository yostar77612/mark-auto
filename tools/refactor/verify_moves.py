"""Independent AST and frozen-literal verification of the mechanical desktop move."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path
import subprocess


def qualified(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = qualified(node.value)
        return base + '.' + node.attr if base else None
    return None


class Canonical(ast.NodeTransformer):
    def __init__(self, moves, rewrite, old, future=False):
        self.reverse = {new: old for old, new in moves.items()}
        self.modules = {rewrite.module(new): rewrite.module(old) for old, new in moves.items()}
        self.rewrite = rewrite
        self.old = old
        self.moves = moves
        self.future = future
        path = moves.get(old, old) if future else old
        self.package = rewrite.module(path) if path.endswith('/__init__.py') else rewrite.module(path).rpartition('.')[0]

    def original_name(self, name):
        for new, old in sorted(self.modules.items(), key=lambda item: len(item[0]), reverse=True):
            if name == new or name.startswith(new + '.'):
                return old + name[len(new) :]
        return name

    def visit_Import(self, node):
        return [
            ast.Import(names=[ast.alias(name=self.original_name(alias.name), asname=alias.asname or self.original_name(alias.name).split('.')[0])])
            for alias in node.names
        ]

    def visit_ImportFrom(self, node):
        base = node.module or ''
        if node.level:
            parts = self.package.split('.')
            base = '.'.join(parts[: len(parts) - node.level + 1] + ([base] if base else []))
        result = []
        for alias in node.names:
            parent, _, name = self.original_name(base + '.' + alias.name).rpartition('.')
            result.append(ast.ImportFrom(module=parent, names=[ast.alias(name=name, asname=(alias.asname or alias.name) if name != '*' else None)], level=0))
        return result

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(self.rewrite.strings(node.value, self.reverse, physical=True)), node)
        return node

    def visit_Attribute(self, node):
        name = qualified(node)
        if name:
            for new, old in sorted(self.modules.items(), key=lambda item: len(item[0]), reverse=True):
                if name == new or name.startswith(new + '.'):
                    return ast.copy_location(ast.parse(old + name[len(new) :], mode='eval').body, node)
        return self.generic_visit(node)

    def visit_Subscript(self, node):
        # Physical-file selection preserves the original logical key lookup.
        if isinstance(node.value, ast.Dict) and isinstance(node.slice, ast.Name) and node.slice.id == 'name':
            keys = [item.value for item in node.value.keys if isinstance(item, ast.Constant)]
            values = [item.value for item in node.value.values if isinstance(item, ast.Constant)]
            if keys == ['desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'] and values == ['auth.py', 'provider.py']:
                return ast.copy_location(ast.Name(id='name', ctx=ast.Load()), node)
        if self.old in ('desktop_icon.py', 'desktop_ui.py') and ast.unparse(node).endswith('.parents[2]'):
            value = node.value
            return ast.copy_location(ast.Attribute(value=value.value, attr='parent', ctx=ast.Load()), node)
        return self.generic_visit(node)

    def visit_Call(self, node):
        # A dotted __import__ without fromlist returns the top-level package.
        # Only this exact adapter preserves the former single-module return value.
        if (
            self.future
            and isinstance(node.func, ast.Name)
            and node.func.id == '__import__'
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in self.modules
        ):
            if (
                len(node.args) == 1
                and len(node.keywords) == 1
                and node.keywords[0].arg == 'fromlist'
                and isinstance(node.keywords[0].value, ast.List)
                and len(node.keywords[0].value.elts) == 1
                and isinstance(node.keywords[0].value.elts[0], ast.Constant)
                and node.keywords[0].value.elts[0].value == '__name__'
            ):
                return ast.Call(func=ast.Name(id='__import__', ctx=ast.Load()), args=[ast.Constant(self.modules[node.args[0].value])], keywords=[])
            return node
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'get' and isinstance(node.func.value, ast.Dict):
            keys = [item.value for item in node.func.value.keys if isinstance(item, ast.Constant)]
            values = [item.value for item in node.func.value.values if isinstance(item, ast.Constant)]
            wanted_keys = ['desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py', 'desktop_chatgpt_dependency_manifest.json']
            wanted_values = [self.moves.get(name, 'quantlab/assistant/adapters/chatgpt/' + name) for name in wanted_keys]
            arguments = len(node.args) == 2 and all(isinstance(item, ast.Name) and item.id == 'name' for item in node.args)
            if self.old == 'desktop_ui.py' and keys == wanted_keys and values == wanted_values and arguments and not node.keywords:
                return node.args[1]
        return self.generic_visit(node)


def signature(source, old, moves, rewrite, future=False):
    tree = Canonical(moves, rewrite, old, future).visit(ast.parse(source))
    return ast.dump(tree, include_attributes=False)


def frozen_literals(source):
    tree = ast.parse(source)
    return {
        node.targets[0].id: ast.get_source_segment(source, node)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == 'freeze'
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--base', help='Reviewed PR-B base; omit for in-memory preparation verification')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('move_script', Path(__file__).with_name('move_desktop_app.py'))
    rewrite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rewrite)
    root = args.root.resolve()
    moves = rewrite.read_mapping(root)
    if args.base:
        originals = {old: subprocess.check_output(['git', '-C', str(root), 'show', args.base + ':' + old]).decode('utf-8') for old in moves}
        outputs = {new: (root / new).read_bytes().decode('utf-8') for new in moves.values()}
        pool = 'quantlab/saved_candidate_pool.py'
        originals[pool] = subprocess.check_output(['git', '-C', str(root), 'show', args.base + ':' + pool]).decode('utf-8')
        outputs[pool] = (root / pool).read_bytes().decode('utf-8')
    else:
        originals, outputs = rewrite.prepare(root, moves)
    differences = [old for old, new in moves.items() if signature(originals[old], old, moves, rewrite) != signature(outputs[new], old, moves, rewrite, True)]
    baseline = signature('import socket\nx=1', 'sample.py', {}, rewrite)
    controls = ['x=1', 'import json\nx=1', 'import socket as other\nx=1']
    if any(signature(source, 'sample.py', {}, rewrite) == baseline for source in controls):
        raise ValueError('Import removal/replacement/alias negative control failed')
    if signature('import socket\nimport json\nx=1', 'sample.py', {}, rewrite) == signature('import json\nimport socket\nx=1', 'sample.py', {}, rewrite):
        raise ValueError('Import reordering was hidden')
    keys = ['desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py', 'desktop_chatgpt_dependency_manifest.json']
    physical = {name: moves.get(name, 'quantlab/assistant/adapters/chatgpt/' + name) for name in keys}
    good = 'x = source_root / ' + repr(physical) + '.get(name, name)'
    before_lookup = signature('x = source_root / name', 'desktop_ui.py', moves, rewrite)
    if signature(good, 'desktop_ui.py', moves, rewrite, True) != before_lookup:
        raise ValueError('Reviewed physical lookup failed equivalence')
    physical[keys[0]] = 'wrong/auth.py'
    wrong = 'x = source_root / ' + repr(physical) + '.get(name, name)'
    if signature(wrong, 'desktop_ui.py', moves, rewrite, True) == before_lookup:
        raise ValueError('Wrong physical lookup escaped verification')
    module_before = signature("x = __import__('desktop_smoke')", 'sample.py', moves, rewrite)
    correct_import = "x = __import__('desktop_app.smoke', fromlist=['__name__'])"
    if signature(correct_import, 'sample.py', moves, rewrite, True) != module_before:
        raise ValueError('Exact dotted module-return adapter failed')
    wrong_imports = [
        "x = __import__('desktop_app.smoke')",
        "x = __import__('desktop_app.smoke', fromlist=['*'])",
        "x = __import__('desktop_app.shell.pages', fromlist=['__name__'])",
    ]
    if any(signature(code, 'sample.py', moves, rewrite, True) == module_before for code in wrong_imports):
        raise ValueError('Wrong or missing dotted fromlist escaped verification')
    pool = 'quantlab/saved_candidate_pool.py'
    before, after = frozen_literals(originals[pool]), frozen_literals(outputs[pool])
    # Git blobs and checkout CRLF are different evidence domains. Raw checkout
    # preservation is checked by the independently captured raw-byte manifest.
    changed_literals = [
        name
        for name, value in before.items()
        if (after.get(name, '').replace('\r\n', '\n') if args.base else after.get(name)) != (value.replace('\r\n', '\n') if args.base else value)
    ]
    print(
        json.dumps(
            {
                'compared_moved_modules': len(moves),
                'ast_differences': differences,
                'historical_profiles': len(before),
                'changed_historical_profile_literals': changed_literals,
                'literal_comparison': 'git_blob_with_approved_eol' if args.base else 'actual_checkout_characters_and_eol',
            },
            indent=2,
        )
    )
    return int(bool(differences or changed_literals))


if __name__ == '__main__':
    raise SystemExit(main())

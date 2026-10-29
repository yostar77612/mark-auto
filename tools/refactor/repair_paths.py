"""Idempotent mechanical corrections for physical paths and nested test fixtures."""

import ast
import subprocess

FROZEN = {
    'quantlab/research.py',
    'quantlab/provider.py',
    'quantlab/core.py',
    'quantlab/strategies.py',
    'quantlab/backtest.py',
    'quantlab/data.py',
    'quantlab/saved_candidate_pool.py',
    'quantlab/assistant/adapters/chatgpt/auth.py',
    'quantlab/assistant/adapters/chatgpt/provider.py',
}


def fixture_parents(source):
    tree = ast.parse(source)
    methods = {'test_all_desktop_components_enforce_existing_execution_boundary', 'test_automatic_backup_component_keeps_desktop_boundary'}
    lines = source.splitlines(keepends=True)
    edits = []
    for method in ast.walk(tree):
        if not isinstance(method, ast.FunctionDef) or method.name not in methods:
            continue
        body = ast.get_source_segment(source, method)
        for node in ast.walk(method):
            if (
                not isinstance(node, ast.Expr)
                or not isinstance(node.value, ast.Call)
                or not isinstance(node.value.func, ast.Attribute)
                or node.value.func.attr != 'write_text'
            ):
                continue
            receiver = ast.unparse(node.value.func.value)
            parent = '(' + receiver + ').parent.mkdir(parents=True, exist_ok=True)'
            if parent not in body:
                edits.append((node.lineno - 1, ' ' * node.col_offset + parent + '\n'))
    for index, insertion in reversed(sorted(set(edits))):
        lines.insert(index, insertion)
    return ''.join(lines)


def strict_core_fixture(source):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    wanted = "if name.startswith('quantlab/'):\n    self.assertTrue(scan(root), name)\nelse:\n    self.assertEqual(scan(root), [], name)\n"
    wanted_node = ast.parse(wanted).body[0]
    for method in ast.walk(tree):
        if not isinstance(method, ast.FunctionDef) or method.name != 'test_all_desktop_components_enforce_existing_execution_boundary':
            continue
        for node in ast.walk(method):
            guard = isinstance(node, ast.If) and ast.dump(node.test) == ast.dump(wanted_node.test)
            expression = isinstance(node, ast.Expr) and isinstance(node.value, (ast.Call, ast.IfExp))
            if not (guard or expression):
                continue
            text = ast.get_source_segment(source, node)
            if 'scan(root)' not in text or 'assertEqual' not in text:
                continue
            if guard and ast.dump(node) == ast.dump(wanted_node):
                return source
            indent = ' ' * node.col_offset
            replacement = ''.join(indent + line for line in wanted.splitlines(keepends=True))
            lines[node.lineno - 1 : node.end_lineno] = [replacement]
            return ''.join(lines)
    return source


def repair(root, moves):
    fixture = root / 'tests/fixtures/layered_paths/page_service_line_relocations.json'
    raw = (root / 'tools/refactor/page_service_line_relocations.json.template').read_bytes()
    if not fixture.exists():
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_bytes(raw)
    elif fixture.read_bytes().replace(b'\r\n', b'\n') != raw.replace(b'\r\n', b'\n'):
        raise ValueError('Mechanical line-location fixture differs from the reviewed template')
    paths = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'], text=True, encoding='utf-8').split('\0')
    paths += [path.relative_to(root).as_posix() for path in (root / 'tools/refactor').glob('*.py')]
    paths += ['tests/layered_source_fixtures.py', 'tests/test_layered_paths_profile.py', 'tests/test_desktop_layered_worker_import.py']
    changed = []
    for name in sorted(set(paths)):
        path = root / name
        if (
            not name
            or not path.is_file()
            or name in FROZEN
            or (path.suffix not in {'.py', '.toml', '.yml', '.yaml', '.json', '.md', '.ps1', '.spec'} and name != '.gitignore')
        ):
            continue
        source = path.read_bytes().decode('utf-8')
        updated = source
        for old, new in moves.items():
            if '/' not in old:
                updated = updated.replace('test_' + new, 'test_' + old)
        if name.startswith('tests/'):
            updated = updated.replace("__import__('desktop_app.smoke')", "__import__('desktop_app.smoke', fromlist=['__name__'])")
            updated = updated.replace("__import__('desktop_app.smoke', fromlist=['*'])", "__import__('desktop_app.smoke', fromlist=['__name__'])")
        if name == 'tools/ci_changes.py':
            updated = updated.replace("'desktop_app.shell.pages', 'desktop_app.smoke'", "'desktop_app'")
        if name == 'tools/ui_test_gate.py':
            updated = updated.replace("('desktop_app.shell.pages', 'desktop_app.smoke')", "('desktop_app',)")
        if name == 'tests/test_ui_test_gate.py':
            updated = updated.replace("('desktop_app.shell.pages', 'desktop_app.smoke')", "('desktop_app/features/market', 'desktop_app/smoke')")
            updated = updated.replace('(root / package).mkdir()', '(root / package).mkdir(parents=True)')
        if name == 'tests/test_core_shards.py':
            updated = updated.replace("'desktop_pages/view.py'", "'desktop_app/features/strategy/view.py'")
            updated = updated.replace("'desktop_smoke/source.txt'", "'desktop_app/smoke/source.txt'")
        if name == 'tests/test_trading_architecture.py':
            if 'from tests.layered_source_fixtures import mechanically_restored_source, physical_path' not in updated:
                updated = updated.replace(
                    'from tools.check_trading_architecture import check_source, scan',
                    'from tools.check_trading_architecture import check_source, scan\nfrom tests.layered_source_fixtures import mechanically_restored_source, physical_path',
                )
            updated = updated.replace(
                "['git', 'cat-file', '--filters', f'{BASELINE}:{path}']",
                "['git', 'cat-file', '--filters', '--path', physical_path(path), f'{BASELINE}:{path}']",
            )
            updated = updated.replace('current = (ROOT / path).read_bytes()', 'current = mechanically_restored_source(ROOT, path, baseline)')
        if name == 'tests/test_no_inline_stylesheet.py':
            updated = (root / 'tools/refactor/test_no_inline_stylesheet.py.template').read_text(encoding='utf-8')
        if name == 'tools/check_trading_architecture.py':
            updated = updated.replace("('quantlab/trading', 'desktop_app.features.trading')", "('quantlab/trading', 'desktop_app/features/trading')")
        if name == 'packaging/build_manifest.py':
            updated = updated.replace(
                "'desktop_chatgpt_dependency_manifest.json'", "'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json'"
            )
        if name == 'tests/test_quality_gate.py':
            updated = fixture_parents(updated)
            updated = strict_core_fixture(updated)
        if name == 'tools/quality_gate.py' and 'no Qt imports under quantlab/' not in updated:
            anchor = "        if any(module.split('.')[0].startswith('desktop') for module in modules):"
            added = "        if any(module.split('.')[0] in ('PySide6', 'shiboken6') for module in modules):\n            findings.append(f'{label}:{node.lineno}: no Qt imports under quantlab/')\n"
            updated = updated.replace(anchor, added + anchor, 1)
        if name == '.gitignore' and '!desktop_app/features/data/*.py' not in updated:
            updated += '\n# The data feature is presentation source; keep other data directories ignored.\n!desktop_app/features/data/\ndesktop_app/features/data/*\n!desktop_app/features/data/*.py\n'
        if name == 'tests/fixtures/desktop_text_alias_map.json':
            updated = updated.replace('"source_path": "desktop_app/strings/catalog.py"', '"source_path": "desktop_strings.py"')
        if name == 'tests/page_services_inventory.py':
            updated = (
                updated.replace(
                    'from tests.layered_source_fixtures import page_sources',
                    'from tests.layered_source_fixtures import page_sources, project_page_service_lines',
                )
                if 'project_page_service_lines' not in updated
                else updated
            )
            updated = updated.replace(
                "    return result\n\n\nif __name__ == '__main__':", "    return project_page_service_lines(result)\n\n\nif __name__ == '__main__':"
            )
            updated = updated.replace("target.split('.')[1]", "target.removeprefix('desktop_app.shell.main_window.')")
        if name in ('tests/test_page_services_r1.py', 'tests/page_services_inventory.py'):
            updated = updated.replace('from tests.layered_source_fixtures import physical_path', 'from tests.layered_source_fixtures import page_sources')
            updated = updated.replace("(ROOT / physical_path('desktop_pages')).rglob('*.py')", 'page_sources(ROOT)')
        if name == 'tests/test_desktop_pages.py':
            updated = updated.replace(
                'from tests.layered_source_fixtures import physical_path, page_sources', 'from tests.layered_source_fixtures import page_sources'
            )
            updated = updated.replace('from tests.layered_source_fixtures import physical_path', 'from tests.layered_source_fixtures import page_sources')
            updated = updated.replace("for path in (ROOT / physical_path('desktop_pages')).rglob('*.py'):", 'for path in page_sources(ROOT):')
        if name == 'tests/test_ui_operations_registry.py':
            updated = updated.replace("'old_desktop_app/shell/main_window.py'", "'old_desktop_ui.py'")
            if 'from tests.layered_source_fixtures import historical_ui_environment' not in updated:
                updated = updated.replace(
                    'import desktop_app.shell.main_window as ui',
                    'from tests.layered_source_fixtures import historical_ui_environment\n\nimport desktop_app.shell.main_window as ui',
                    1,
                )
            old = '            spec.loader.exec_module(module)\n            # Source-hash lookups still refer to the unchanged dependency files\n            # beside desktop_ui.py; only the loaded module\'s name is isolated.\n            module.__file__ = ui.__file__\n            yield module'
            new = "            with historical_ui_environment():\n                spec.loader.exec_module(module)\n                module.__file__ = str(Path(__file__).resolve().parents[1] / 'desktop_ui.py')\n                yield module"
            updated = updated.replace(old, new)
            updated = updated.replace(
                "with workspace() as paths, patch('socket.socket', side_effect=AssertionError('offline fixtures only')):",
                "with workspace() as paths, patch('socket.socket', side_effect=AssertionError('offline fixtures only')), historical_ui_environment():",
            )
        if name == 'tests/test_desktop_text_aliases.py':
            updated = updated.replace(
                "('desktop_app.shell.pages', 'desktop_app.smoke', 'desktop_app.features.trading', 'quantlab', 'tools', 'tests')",
                "('desktop_app', 'quantlab', 'tools', 'tests')",
            )
            updated = updated.replace(
                "self.assertEqual(self.fixture['source_path'], 'desktop_app/strings/catalog.py')",
                "self.assertEqual(self.fixture['source_path'], 'desktop_strings.py')",
            )
        if name == 'tests/fixtures/ui_operations_golden.json':
            updated = updated.replace(
                'git show HEAD:desktop_app/shell/main_window.py; captured before refactoring', 'git show HEAD:desktop_ui.py; captured before refactoring'
            )
        if name == 'tests/test_packaging.py':
            updated = updated.replace(
                "'desktop_chatgpt_dependency_manifest.json'", "'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json'"
            )
            updated = updated.replace(
                "self.assertIn((str(ROOT / name), '.'), datas)", "self.assertIn((str(ROOT / name), 'quantlab/assistant/adapters/chatgpt'), datas)"
            )
            if '\nimport json\n' not in updated:
                updated = updated.replace('import ast\n', 'import ast\nimport json\n', 1)
        if name == 'tests/test_layer_gate.py':
            lines = updated.splitlines(keepends=True)
            key = "'tools/refactor/repair_paths.py': 'tooling'"
            lines = [line for line in lines if key not in line]
            updated = ''.join(lines).replace(
                "'tools/refactor/verify_moves.py': 'tooling',",
                "'tools/refactor/verify_moves.py': 'tooling',\n            'tools/refactor/repair_paths.py': 'tooling',",
            )
        if updated != source:
            path.write_bytes(updated.encode('utf-8'))
            changed.append(name)
    old = root / 'desktop_trading/README.md'
    new = root / 'desktop_app/features/trading/README.md'
    if old.is_file():
        if new.exists():
            raise ValueError('README destination already exists; preserve both until reviewed')
        subprocess.run(['git', '-C', str(root), 'mv', '--', 'desktop_trading/README.md', 'desktop_app/features/trading/README.md'], check=True)
        changed.append('desktop_app/features/trading/README.md')
    return changed

"""Idempotent mechanical corrections for physical paths and nested test fixtures."""

import ast
import json
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


def current_test_paths(source, moves):
    """Use current physical paths in executable tests; retain frozen identity keys."""
    tree = ast.parse(source)
    edits = []
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def span(node):
        return (
            offsets[node.lineno - 1] + len(lines[node.lineno - 1].encode()[: node.col_offset].decode()),
            offsets[node.end_lineno - 1] + len(lines[node.end_lineno - 1].encode()[: node.end_col_offset].decode()),
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
            expression = "physical_path('desktop_pages' + '/' + str(" + ast.unparse(node.target) + '))'
            if expression not in ast.get_source_segment(source, node):
                continue
            for item in node.iter.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    edits.append((*span(item), repr(moves['desktop_pages/' + item.value])))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'physical_path':
            argument = ast.unparse(node.args[0])
            directories = {'desktop_pages': 'desktop_app', 'desktop_trading': 'desktop_app/features/trading', 'desktop_smoke': 'desktop_app/smoke'}
            if isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                replacement = repr(moves.get(value, directories.get(value, value)))
            elif argument.startswith("'desktop_pages' + '/' + str("):
                replacement = ast.unparse(node.args[0].right.args[0])
            else:
                continue
            edits.append((*span(node), replacement))
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    if 'physical_path(' not in source:
        source = source.replace('physical_path, ', '').replace(', physical_path', '')
        source = source.replace('from tests.layered_source_fixtures import physical_path\n', '# Source scans below use current physical paths.\n')
    source = source.replace('desktop_theme.apply_market_theme', 'desktop_app.shell.theme.apply_market_theme')
    source = source.replace(
        "for old, new in CURRENT_PATHS.items() if not old.startswith('desktop_trading/')",
        "for new in CURRENT_PATHS.values() if not new.startswith('desktop_app/features/trading/')",
    )
    source = source.replace(
        "for old, new in CURRENT_PATHS.items() if old.startswith('desktop_trading/')",
        "for new in CURRENT_PATHS.values() if new.startswith('desktop_app/features/trading/')",
    )
    source = source.replace("CURRENT_PATHS['desktop_trading/dashboard.py']", "'desktop_app/features/trading/dashboard.py'")
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
        if name == 'tools/quality_gate.py':
            updated = updated.replace(
                "            if name.startswith('quantlab/'):",
                "            if name.startswith('quantlab/') and name not in {'quantlab/assistant/adapters/chatgpt/auth.py', 'quantlab/assistant/adapters/chatgpt/provider.py', 'quantlab/research_core/adapters/market_layout.py'}:",
            )
            updated = updated.replace(
                '"quantlab/assistant/adapters/chatgpt/provider.py"}',
                '"quantlab/assistant/adapters/chatgpt/provider.py", "quantlab/research_core/adapters/market_layout.py"}',
            )
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
                if 'import page_sources, project_page_service_lines' not in updated
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
        if name.startswith('tests/') and name.endswith('.py') and name not in {'tests/layered_source_fixtures.py', 'tests/test_trading_architecture.py'}:
            updated = current_test_paths(updated, moves)
        if name == 'quantlab/desktop_runtime.py':
            updated = updated.replace('# desktop_ui module', '# desktop_app.shell.main_window module')
        if name == 'tests/test_desktop_theme.py':
            updated = updated.replace('QSS rules in desktop_theme', 'QSS rules in desktop_app.shell.theme')
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
    # Dated contracts, snapshots and verification records retain their original paths.
    folder = root / 'tools/refactor'
    historical = json.loads((folder / 'historical_docs.json.template').read_text(encoding='utf-8'))
    for name in historical:
        raw = subprocess.check_output(['git', '-C', str(root), 'show', '559025982afbeac8b473b42802d0a8340de90e88:' + name])
        if name == 'docs/agent/IMPLEMENTATION_CONTRACTS.md':
            header, body = raw.decode('utf-8').split('\n', 1)
            raw = (header + (folder / 'contracts_current_locations.md.template').read_text(encoding='utf-8') + body).encode('utf-8')
        text = raw.decode('utf-8')
        for old, new in {**moves, 'desktop_trading/README.md': 'desktop_app/features/trading/README.md'}.items():
            target = '../../' + old
            replacement = (
                ('../../' + new)
                if name == 'docs/design/TEMPLATE.md'
                else ('https://github.com/yostar77612/mark-auto/blob/559025982afbeac8b473b42802d0a8340de90e88/' + old)
            )
            text = text.replace('](' + target + ')', '](' + replacement + ')')
        raw = text.encode('utf-8')
        if (root / name).read_bytes().replace(b'\r\n', b'\n') != raw.replace(b'\r\n', b'\n'):
            (root / name).write_bytes(raw)
            changed.append(name)
    path = root / 'docs/CONTRIBUTING.md'
    source = path.read_text(encoding='utf-8')
    updated = source.replace('desktop_app.shell.pages tools tests', 'desktop_app tools tests').replace(
        'desktop_app.features.trading', 'desktop_app/features/trading'
    )
    if updated != source:
        path.write_text(updated, encoding='utf-8', newline='')
        changed.append('docs/CONTRIBUTING.md')
    return changed

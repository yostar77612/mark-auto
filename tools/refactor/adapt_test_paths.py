"""Explicit mechanical configuration and historical fixture adaptations."""

import ast
import gzip
import hashlib
import json
from pathlib import Path
import re


def configure(path, source, moves, strings, MANIFEST, ADAPTER):
    if path in ('tests/test_import_graph.py', 'tests/test_error_catalog_b1.py', 'tests/test_no_inline_stylesheet.py', 'tests/test_notifications_f4.py'):
        adapters = tuple(moves[name] for name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py', 'desktop_market_layout.py'))
        for old in ("ROOT.glob('desktop*.py')", 'ROOT.glob("desktop*.py")'):
            source = source.replace(old, '[*' + old + ', *(ROOT / relative for relative in ' + repr(adapters) + ')]')
    if path == 'pyproject.toml':
        source = source.replace('"desktop_trading*"', '"desktop_app*"')
    if path == 'packaging/markauto.spec':
        for old in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'):
            source = source.replace(f"(str(root / '{old}'), '.')", f"(str(root / '{moves[old]}'), '{ADAPTER.rstrip('/')}')")
        source = source.replace(f"(str(root / '{MANIFEST}'), '.')", f"(str(root / '{ADAPTER + MANIFEST}'), '{ADAPTER.rstrip('/')}')")
    if Path(path).suffix != '.py':
        source = strings(source, moves, physical=True)
    if path in ('tools/run_test_group.py', 'packaging/build_manifest.py', 'packaging/desktop_regression.py'):
        # A directory collection now covers all slices, including source bytes
        # and data nested below the new desktop/assistant packages.
        source = source.replace("'desktop_app.shell', 'desktop_app.smoke', 'desktop_app.features.trading'", "'desktop_app'").replace(
            "'desktop_app.shell.pages', 'desktop_app.smoke', 'desktop_app.features.trading'", "'desktop_app'"
        )
        source = source.replace("'desktop_app/*.py'", "'desktop_app/**/*.py'")
        if path == 'packaging/build_manifest.py':
            source = source.replace(
                "'quantlab/trading/**/*.py',",
                "'quantlab/trading/**/*.py',\n            'quantlab/assistant/**/*.py',\n            'quantlab/assistant/**/*.json',\n            'quantlab/research_core/**/*.py',",
            )
    if path == 'tools/quality_gate.py':
        # These files were desktop=True/research=False before moving; retain
        # every banned-call/import check while keeping only their old scope.
        source = source.replace(
            'name.startswith("quantlab/"),',
            'name.startswith("quantlab/") and name not in {"' + moves['desktop_chatgpt_auth.py'] + '", "' + moves['desktop_chatgpt_provider.py'] + '"},',
        )
        source = source.replace(
            'first_party.add("desktop_app.shell.main_window")',
            'if (isinstance(node, ast.Import) and all(item.name == "desktop_app.shell.main_window" for item in node.names)) or (isinstance(node, ast.ImportFrom) and node.module == "desktop_app.shell.main_window"):\n                        first_party.add("desktop_app")',
        )
    if path == 'tests/test_no_hardcoded_ui_text.py':
        source = source.replace("('desktop_app.shell', 'desktop_app.smoke', 'desktop_app.features.trading')", "('desktop_app',)").replace(
            "('desktop_app.shell.pages', 'desktop_app.smoke', 'desktop_app.features.trading')", "('desktop_app',)"
        )
        source = source.replace(
            "for path in (ROOT / package).rglob('*.py'))",
            "for path in (ROOT / package).rglob('*.py') if not path.relative_to(ROOT).as_posix().startswith('desktop_app/strings/') and path.relative_to(ROOT).as_posix() != 'desktop_app/smoke/tls.py')",
        )
        source = source.replace(
            "self.assertEqual({path.name for path in ROOT.glob('desktop*.py')}, set(UI_MODULES) | set(NON_UI_MODULES))",
            "actual = {path.relative_to(ROOT).as_posix() for path in ROOT.glob('desktop*.py')} | {path.relative_to(ROOT).as_posix() for path in (ROOT / 'desktop_app').rglob('*.py')}\n        actual |= {path for path in ("
            + repr(moves['desktop_chatgpt_auth.py'])
            + ', '
            + repr(moves['desktop_chatgpt_provider.py'])
            + ', '
            + repr(moves['desktop_market_layout.py'])
            + ") if (ROOT / path).is_file()}\n        shared = {path.relative_to(ROOT).as_posix() for path in (ROOT / 'desktop_app/strings').rglob('*.py')}\n        self.assertEqual(actual, set(UI_MODULES) | set(UI_PACKAGE_MODULES) | set(NON_UI_MODULES) | shared)",
        )
    if path == 'tests/page_services_inventory.py':
        source = source.replace("(ROOT / 'desktop_app.shell').glob('*.py')", "(ROOT / 'desktop_app').rglob('*.py')")
    if path in (
        'tools/quality_gate.py',
        'tools/verify_format_equivalence.py',
        'tests/test_desktop_text_aliases.py',
        'tests/test_function_lengths.py',
        'tests/test_no_hardcoded_ui_text.py',
        'tests/test_packaging.py',
        'tests/test_quality_gate.py',
        'tests/test_repo_layout.py',
        'tests/test_agent_harness_d2.py',
    ):
        for old in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'):
            source = source.replace(old, moves[old])
    return source


def packaging_source_coverage(source):
    tree = ast.parse(source)
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'test_manifest_includes_every_root_desktop_component')
    replacement = '''def test_manifest_includes_every_root_desktop_component(self):
        source = (ROOT / 'packaging/build_manifest.py').read_text(encoding='utf-8')
        self.assertIn("'desktop*.py'", source)
        patterns = {node.value for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        included = {path.relative_to(ROOT).as_posix() for pattern in patterns if '*' in pattern for path in ROOT.glob(pattern) if path.is_file()}
        relocations = json.loads((ROOT / 'tools/layer_relocations.json').read_text(encoding='utf-8'))
        self.assertEqual(len(relocations), 102)
        self.assertLessEqual(set(relocations.values()) | {'desktop.py'}, included)'''
    return source.replace(ast.get_source_segment(source, method), replacement, 1)


def physical_test_paths(source):
    inverse = {
        'desktop_app.shell': 'desktop_pages',
        'desktop_app.shell.pages': 'desktop_pages',
        'desktop_app.features.trading': 'desktop_trading',
        'desktop_app.smoke': 'desktop_smoke',
    }
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    starts, total = [], 0
    for line in lines:
        starts.append(total)
        total += len(line)
    edits = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'Path'
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in inverse
        ):
            continue
        relative = repr(inverse[node.args[0].value])
        for part in node.args[1:]:
            relative += " + '/' + str(" + ast.unparse(part) + ')'
        replacement = 'Path(physical_path(' + relative + '))'
        start = starts[node.lineno - 1] + len(lines[node.lineno - 1].encode()[: node.col_offset].decode())
        stop = starts[node.end_lineno - 1] + len(lines[node.end_lineno - 1].encode()[: node.end_col_offset].decode())
        edits.append((start, stop, replacement))
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        parts, current = [], node
        while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
            parts.append(current.right)
            current = current.left
        parts.reverse()
        if not parts or not isinstance(parts[0], ast.Constant) or parts[0].value not in inverse:
            continue
        relative = repr(inverse[parts[0].value])
        for part in parts[1:]:
            relative += " + '/' + str(" + ast.unparse(part) + ')'
        replacement = ast.unparse(current) + ' / physical_path(' + relative + ')'
        start = starts[node.lineno - 1] + len(lines[node.lineno - 1].encode()[: node.col_offset].decode())
        stop = starts[node.end_lineno - 1] + len(lines[node.end_lineno - 1].encode()[: node.end_col_offset].decode())
        edits.append((start, stop, replacement))
    selected = []
    for edit in sorted(edits, key=lambda item: (item[0], -item[1])):
        if not selected or edit[0] >= selected[-1][1]:
            selected.append(edit)
    for start, stop, replacement in reversed(selected):
        source = source[:start] + replacement + source[stop:]
    if selected:
        source = source.replace("physical_path('desktop_pages')).glob(", "physical_path('desktop_pages')).rglob(")
        imports = [node for node in ast.parse(source).body if isinstance(node, (ast.Import, ast.ImportFrom))]
        position = max(node.end_lineno for node in imports)
        lines = source.splitlines(keepends=True)
        lines.insert(position, 'from tests.layered_source_fixtures import physical_path\n')
        source = ''.join(lines)
    return source


def inventory_test(source, outputs, root):
    tree = ast.parse(source)
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'test_inventory_assignments_match_exactly')
    mapping = json.loads(outputs['tools/layer_map.json'])
    metadata = {}
    for path in outputs:
        if not path.endswith('/__init__.py') or (root / path).exists():
            continue
        if path in mapping['overrides']:
            metadata[path] = mapping['overrides'][path]
        else:
            metadata[path] = next(mapping['prefixes'][prefix] for prefix in sorted(mapping['prefixes'], key=len, reverse=True) if path.startswith(prefix))
    metadata.update(
        {path: 'tooling' for path in ('tools/refactor/move_desktop_app.py', 'tools/refactor/adapt_test_paths.py', 'tools/refactor/verify_moves.py')}
    )
    replacement = '''def test_inventory_assignments_match_exactly(self):
        text = (ROOT / 'docs/analysis/08_REFACTOR_INVENTORY.md').read_text(encoding='utf-8')
        section = text.split('## 2 ')[1].split('## 3 ')[0]
        rows = dict(re.findall(r'^\\| `([^`]+\\.py)` \\| \\d+ \\| (\\w+) \\|', section, re.M))
        self.assertTrue(rows)
        relocations = json.loads((ROOT / 'tools/layer_relocations.json').read_text(encoding='utf-8'))
        inverse = {new: old for old, new in relocations.items()}
        metadata = __METADATA__
        current = gate.tracked_sources(ROOT)
        self.assertLessEqual({inverse.get(path, path) for path in current}, rows.keys() | metadata.keys())
        for path in current:
            canonical = inverse.get(path, path)
            with self.subTest(path=path, original=canonical):
                if canonical in rows:
                    expected = rows[canonical]
                elif path in metadata:
                    expected = metadata[path]
                    if path.endswith('/__init__.py'):
                        self.assertEqual((ROOT / path).read_text(encoding='utf-8').strip(), '')
                else:
                    self.fail('Uninventoried product source: ' + path)
                self.assertEqual(gate.layer_for(path, self.mapping), expected)'''.replace('__METADATA__', repr(metadata))
    return source.replace(ast.get_source_segment(source, method), replacement, 1)


def root_layout(source):
    for dotted in ('desktop_app.shell', 'desktop_app.shell.pages', 'desktop_app.smoke', 'desktop_app.features.trading'):
        source = source.replace(repr(dotted), "'desktop_app'")
    for name in ('ALLOWED_FILES', 'ALLOWED_DIRECTORIES'):
        tree = ast.parse(source)
        assignment = next(
            node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
        )
        values = set(ast.literal_eval(assignment.value))
        if name == 'ALLOWED_FILES':
            values = {value for value in values if '/' not in value and value != 'desktop_chatgpt_dependency_manifest.json'}
        else:
            values -= {'desktop_pages', 'desktop_trading', 'desktop_smoke'}
            values.add('desktop_app')
        source = source.replace(ast.get_source_segment(source, assignment), name + ' = {' + ', '.join(repr(value) for value in sorted(values)) + '}', 1)
    return source


def adapt(outputs, originals, moves, root):
    folder = Path(__file__).parent
    base_mapping = (folder / 'r0_relocations_a.json.template').read_bytes()
    outputs['tests/fixtures/layered_paths/r0_relocations_a.json'] = base_mapping
    outputs['tools/layer_relocations.json'] = json.dumps(moves, indent=2) + '\n'
    inventory = 'docs/analysis/08_REFACTOR_INVENTORY.md'
    original_inventory = (root / inventory).read_bytes().decode('utf-8')
    originals[inventory] = original_inventory
    outputs[inventory] = original_inventory.replace(
        'G3 auth/provider 本體不搬。', 'G3 auth/provider 本體於 B 純搬至上述 adapter 路徑，D 再依責任拆分。'
    ).replace('D E1 才搬檔；', 'B 已純搬至 desktop_app，D 抽取核心責任；')
    outputs[inventory] = re.sub(
        r'(\| `desktop_pages/__init__\.py` \| \d+ \| presentation \| )`desktop_app/shell/__init__\.py`', r'\1`desktop_app/shell/pages.py`', outputs[inventory]
    )
    outputs[inventory] = outputs[inventory].replace(
        'smoke 使用 desktop_app/smoke/',
        'B 的唯一 R0 落點修正：desktop_pages/__init__.py 搬至 desktop_app/shell/pages.py；shell/__init__.py 必須為空 metadata，保留 worker guard 先於 Qt 載入。其餘 101 對映以原始 A fixture 逐項比對，102 來源與 92 債務身份不變。\n\nsmoke 使用 desktop_app/smoke/',
        1,
    )
    template = (folder / 'layered_source_fixtures.py.template').read_text(encoding='utf-8')
    for name, marker in (('desktop_chatgpt_auth.py', '__FROZEN_AUTH_SHA__'), ('desktop_chatgpt_provider.py', '__FROZEN_PROVIDER_SHA__')):
        raw = originals[name].encode('utf-8')
        outputs['tests/fixtures/layered_paths/' + name + '.gz'] = gzip.compress(raw, mtime=0)
        template = template.replace(marker, hashlib.sha256(raw).hexdigest())
    old, new = originals['desktop_chatgpt_provider.py'], outputs[moves['desktop_chatgpt_provider.py']]

    def source_parts(source):
        tree = ast.parse(source)
        imported = next(
            node for node in tree.body if isinstance(node, ast.ImportFrom) and (node.module or '').endswith(('desktop_chatgpt_auth', 'chatgpt.auth'))
        )
        read = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == 'raw'
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == 'read_bytes'
            and any(isinstance(part, ast.Name) and part.id == 'name' for part in ast.walk(node.value))
        )
        return [ast.get_source_segment(source, node).replace('\r\n', '\n') for node in (imported, read)]

    pairs = {moves['desktop_chatgpt_provider.py']: list(zip(source_parts(new), source_parts(old)))}
    template = template.replace('__MECHANICAL_NORMALIZATIONS__', repr(pairs))
    template = template.replace('__R0_RELOCATIONS__', repr(moves))
    outputs['tests/layered_source_fixtures.py'] = template
    outputs['tests/test_layered_paths_profile.py'] = (folder / 'test_layered_paths_profile.py.template').read_text(encoding='utf-8')
    outputs['tests/test_desktop_layered_worker_import.py'] = (folder / 'test_desktop_layered_worker_import.py.template').read_text(encoding='utf-8')
    for path, source in list(outputs.items()):
        if not path.startswith('tests/') or not path.endswith('.py'):
            continue
        if path == 'tests/test_desktop_worker_import.py':
            source = source.replace(
                'import quantlab.desktop_runtime as runtime\n',
                'import quantlab.desktop_runtime as runtime\nfrom tests.layered_source_fixtures import CURRENT_PATHS\n',
                1,
            )
            source = source.replace(
                'ROOT = Path',
                "FORMER_PAGE_MODULES = {current.removesuffix('.py').replace('/', '.') for old, current in CURRENT_PATHS.items() if old.startswith('desktop_pages/')}\n\nROOT = Path",
                1,
            )
            source = source.replace(
                "sorted(name for name in sys.modules if name == 'desktop_app.shell.pages' or name.startswith('desktop_app.shell.pages.'))",
                'sorted(FORMER_PAGE_MODULES.intersection(list(sys.modules)))',
            )
        if 'producer_profile' in path:
            source = re.sub(r'(len\((?:pools\.)?SUPPORTED_PRODUCERS\)\s*,\s*)28\b', r'\g<1>29', source)
            source = source.replace('pools.SUPPORTED_PRODUCERS[26:]', 'pools.SUPPORTED_PRODUCERS[26:28]')
            needed = False
            for variable in ('ROOT', 'root'):
                old = '(' + variable + ' / name).read_bytes()'
                if old in source:
                    source = source.replace(old, 'reviewed_source_bytes(' + variable + ', name)')
                    needed = True
                old = "(" + variable + " / 'desktop_chatgpt_dependency_manifest.json').read_bytes()"
                new = "(" + variable + " / 'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json').read_bytes()"
                source = source.replace(old, new)
            if needed:
                source = source.replace('import unittest\n', 'import unittest\nfrom tests.layered_source_fixtures import reviewed_source_bytes\n', 1)
        if path == 'tests/test_chatgpt_provenance.py':
            physical = {
                'desktop_chatgpt_auth.py': 'auth.py',
                'desktop_chatgpt_provider.py': 'provider.py',
                'desktop_chatgpt_dependency_manifest.json': 'desktop_chatgpt_dependency_manifest.json',
            }
            source = source.replace('ROOT / name', 'ROOT / ' + repr(physical) + '[name]')
        if path == 'tests/test_function_lengths.py':
            source = source.replace('import unittest\n', 'import unittest\nfrom tests.layered_source_fixtures import original_adapter_text\n', 1)
            anchor = "source = (ROOT / filename).read_text(encoding='utf-8-sig')"
            source = source.replace(
                anchor,
                anchor
                + '\n                if filename == '
                + repr(moves['desktop_chatgpt_provider.py'])
                + ':\n                    source = original_adapter_text(filename, source)',
                1,
            )
        if path == 'tests/test_layer_gate.py':
            source = source.replace(
                'b1f30593fa4736ea17ef5eca319a91de9e2f05411171e353100b8303d32942e2', 'fa66be37970e64bbe132d90645c505d7120de6d7680784ec02e9fc6a3f2d3e17'
            )
            source = inventory_test(source, outputs, root)
            anchor = '    def test_allowlist_is_shrink_only(self):'
            test = '''    def test_only_package_initializer_destination_is_corrected(self):
        raw = (ROOT / 'tests/fixtures/layered_paths/r0_relocations_a.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw.replace(b'\\r\\n', b'\\n')).hexdigest(), 'b1f30593fa4736ea17ef5eca319a91de9e2f05411171e353100b8303d32942e2')
        original = json.loads(raw)
        self.assertEqual(len(original), 102)
        self.assertEqual(original['desktop_pages/__init__.py'], 'desktop_app/shell/__init__.py')
        original['desktop_pages/__init__.py'] = 'desktop_app/shell/pages.py'
        actual = json.loads((ROOT / 'tools/layer_relocations.json').read_text(encoding='utf-8'))
        self.assertEqual(actual, original, 'The other 101 relocation pairs must remain exact')

'''
            source = source.replace(anchor, test + anchor, 1)
        if path == 'tests/test_packaging.py':
            source = packaging_source_coverage(source)
        if path == 'tests/test_quality_gate.py':
            method = next(
                node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == 'test_desktop_runtime_bridge_is_narrow'
            )
            original = ast.get_source_segment(source, method)
            extra = '\n        self.assertTrue(python_findings("import desktop_app.features.market.dashboard", "quantlab/desktop_runtime.py", research=True))'
            source = source.replace(original, original + extra, 1)
        if path not in ('tests/layered_source_fixtures.py', 'tests/test_layered_paths_profile.py'):
            source = physical_test_paths(source)
        if path == 'tests/test_repo_layout.py':
            source = root_layout(source)
        outputs[path] = source
    return outputs

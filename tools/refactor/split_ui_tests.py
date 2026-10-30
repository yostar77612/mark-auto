"""Update source-scanner paths after the literal and chart-stage extractions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    path = ROOT / 'tests/test_ui_operations_registry.py'
    source = path.read_text(encoding='utf-8')
    source = source.replace(
        '        source_file.write_bytes(raw)',
        '''        from tools.refactor.split_ui_references import rewrite_source

        owners = json.loads((FIXTURES.parents[1] / 'tools/refactor/split_ui_owners.json').read_text(encoding='utf-8'))
        legacy_owners = {name.replace('desktop_app.components.forms.', 'desktop_forms.').replace('desktop_app.components.charts.', 'desktop_charts.'): owner for name, owner in owners.items()}
        projected, _ = rewrite_source(raw.decode('utf-8'), 'desktop_ui.py', legacy_owners, set())
        source_file.write_text(projected, encoding='utf-8')''',
    )
    path.write_text(source, encoding='utf-8', newline='\n')

    path = ROOT / 'tests/test_desktop_text_aliases.py'
    source = path.read_text(encoding='utf-8')
    source = source.replace(
        "assert len(call.args) == 1 and not call.keywords and isinstance(call.args[0], ast.Dict)\n        block = ast.literal_eval(call.args[0])",
        "assert len(call.args) == 1 and not call.keywords and isinstance(call.args[0], ast.Subscript)\n"
        "        assert isinstance(call.args[0].value, ast.Name) and call.args[0].value.id == '_ZH_TW_CHUNKS'\n"
        "        phase = ast.literal_eval(call.args[0].slice)\n"
        "        block = strings._ZH_TW_CHUNKS[phase]",
    )
    anchor = '            for node in ast.walk(tree):\n                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in allowed_nodes:'
    replacement = '''            if name.startswith('desktop_app/strings/aliases/'):
                for statement in tree.body:
                    if not isinstance(statement, ast.Assign) or not any(isinstance(t, ast.Name) and t.id == 'ENTRIES' for t in statement.targets):
                        continue
                    for row in statement.value.elts:
                        order, key, value = row.elts
                        self.assertEqual(strings.TEXT_ALIASES[ast.literal_eval(key)], ast.literal_eval(value))
                        allowed_nodes.add(id(key))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in allowed_nodes:'''
    if replacement not in source:
        assert anchor in source
        source = source.replace(anchor, replacement)
    path.write_text(source, encoding='utf-8', newline='\n')

    for name in ('test_chart_memory_f6.py', 'test_chart_popout_c10.py'):
        path = ROOT / 'tests' / name
        source = path.read_text(encoding='utf-8')
        source = source.replace('.chart._zoom(', '.chart.interaction._zoom(').replace('.chart._pan(', '.chart.interaction._pan(')
        path.write_text(source, encoding='utf-8', newline='\n')

    old = "'desktop_app.features.market.dashboard', 'desktop_app.components.charts', 'desktop_app.components.forms'"
    new = (
        "'desktop_app.features.market.dashboard', 'desktop_app.components.charts', 'desktop_app.features.strategy.forms', 'desktop_app.features.research.forms'"
    )
    for name in ('desktop_app/smoke/__init__.py', 'tests/test_desktop_market_smoke.py'):
        path = ROOT / name
        source = path.read_text(encoding='utf-8').replace(old, new)
        source = source.replace("sys.modules['desktop_app.components.forms'] = None", "sys.modules['desktop_app.features.strategy.forms'] = None")
        path.write_text(source, encoding='utf-8', newline='\n')

    path = ROOT / 'tests/test_r7_characterization.py'
    source = path.read_text(encoding='utf-8')
    source = source.replace('capture, mount_capture, snapshot_cases\n', 'capture, mount_capture, snapshot_cases, public_names\n')
    while ', public_names, public_names' in source:
        source = source.replace(', public_names, public_names', ', public_names')
    source = source.replace(
        "        self.assertEqual(self.actual['public'], BASE['public'])",
        '''        expected = json.loads(json.dumps(BASE['public']))
        chart = expected['desktop_app/components/charts.py']
        moved_imports = {'ChartMarker', 'ChartTrace', 'ReferenceLine', 'Decimal', 'QPolygonF', 'ZoneInfo', 'dataclass', 'datetime', 're', 'timedelta'}
        chart[0] = sorted((set(chart[0]) - moved_imports) | {'ChartInteraction'})
        annotation_classes = {name: value for name, value in chart[1].items() if name != 'CandlestickChart'}
        chart[1] = {'CandlestickChart': chart[1]['CandlestickChart']}
        self.assertEqual(self.actual['public'], expected)
        annotations = public_names((ROOT / 'desktop_app/components/chart_annotations.py').read_text(encoding='utf-8'))
        self.assertEqual(annotations[1], annotation_classes)''',
    )
    path.write_text(source, encoding='utf-8', newline='\n')

    # Keep every R7 stage check on the helpers' new concrete owners.
    path = ROOT / 'tests/test_r7_function_lengths.py'
    source = path.read_text(encoding='utf-8')
    old = "        for path in TARGETS:\n            tree = ast.parse((ROOT / path).read_text(encoding='utf-8-sig'))\n            added = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name not in BASE['functions'][path]]"
    new = """        stages = dict.fromkeys(TARGETS)
        stages.update(dict.fromkeys(('desktop_app/components/chart_geometry.py', 'desktop_app/components/chart_paint.py', 'desktop_app/components/chart_paint_footer.py')))
        for path in stages:
            tree = ast.parse((ROOT / path).read_text(encoding='utf-8-sig'))
            baseline = BASE['functions'].get(path, BASE['functions']['desktop_app/components/charts.py'])
            added = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name not in baseline]"""
    source = source.replace(old, new)
    source = source.replace(
        "        tree = ast.parse((ROOT / 'desktop_app/components/charts.py').read_text(encoding='utf-8-sig'))\n        for node in tree.body:",
        "        paths = ('charts.py', 'chart_geometry.py', 'chart_paint.py', 'chart_paint_footer.py')\n"
        "        nodes = [node for path in paths for node in ast.parse((ROOT / 'desktop_app/components' / path).read_text(encoding='utf-8-sig')).body]\n"
        "        for node in nodes:",
    )
    path.write_text(source, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()

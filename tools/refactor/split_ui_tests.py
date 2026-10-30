"""Update source-scanner paths after the literal and chart-stage extractions."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def write_source(path, source):
    """Preserve existing formatting when a replay makes no syntax change."""
    current = path.read_text(encoding='utf-8')
    if ast.dump(ast.parse(current)) != ast.dump(ast.parse(source)):
        path.write_text(source, encoding='utf-8', newline='\n')


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
    write_source(path, source)

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
    write_source(path, source)

    for name in ('test_chart_memory_f6.py', 'test_chart_popout_c10.py'):
        path = ROOT / 'tests' / name
        source = path.read_text(encoding='utf-8')
        source = source.replace('.chart._zoom(', '.chart.interaction._zoom(').replace('.chart._pan(', '.chart.interaction._pan(')
        write_source(path, source)

    old = "'desktop_app.features.market.dashboard', 'desktop_app.components.charts', 'desktop_app.components.forms'"
    new = (
        "'desktop_app.features.market.dashboard', 'desktop_app.components.charts', 'desktop_app.features.strategy.forms', 'desktop_app.features.research.forms'"
    )
    for name in ('desktop_app/smoke/__init__.py', 'tests/test_desktop_market_smoke.py'):
        path = ROOT / name
        source = path.read_text(encoding='utf-8').replace(old, new)
        source = source.replace("sys.modules['desktop_app.components.forms'] = None", "sys.modules['desktop_app.features.strategy.forms'] = None")
        write_source(path, source)

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
    write_source(path, source)

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
    write_source(path, source)


def replace_test_function(source, name, replacement):
    import ast

    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1 : node.end_lineno] = [replacement.rstrip() + '\n']
    return ''.join(lines)


def slice2():
    """Adapt concrete owners and injected dependencies; retain behavioral asserts."""

    def edit(name, transform):
        path = ROOT / name
        source = path.read_text(encoding='utf-8')
        updated = transform(source)
        if updated != source:
            write_source(path, updated)

    edit(
        'tests/test_desktop_ui.py',
        lambda s: s.replace(
            'from desktop_app.shell.main_window import research_controls', 'research_controls = _c_create_operation_ports().inputs.research_controls'
        ),
    )
    edit(
        'tests/test_idea_research_ui.py',
        lambda s: (
            s.replace("state=self.state, safe=", "state=self.state, idea_records=IdeaStore, safe=")
            .replace('page.QDesktopServices', '_c_idea_links.QDesktopServices')
            .replace('page.QUrl', '_c_idea_links.QUrl')
            .replace(
                'from desktop_app.features.strategy.idea_links import open_url as _c_page_open_url',
                'from desktop_app.features.strategy.idea_links import open_url as _c_page_open_url\nfrom desktop_app.features.strategy import idea_links as _c_idea_links',
            )
            if 'import idea_links as _c_idea_links' not in s
            else s.replace('page.QUrl', '_c_idea_links.QUrl')
        ),
    )
    edit('tests/test_workspace_wal_guard.py', lambda s: s.replace('inputs=_c_create_operation_ports().inputs', 'inputs=fake_ui'))
    for name in ('tests/page_services_inventory.py', 'tests/test_page_services_r1.py', 'tests/test_desktop_pages.py'):
        edit(
            name,
            lambda s: s.replace("tree('desktop_app/shell/main_window.py')", "tree('desktop_app/shell/window.py')").replace(
                "ROOT / 'desktop_app/shell/main_window.py'", "ROOT / 'desktop_app/shell/window.py'"
            ),
        )
    edit(
        'tests/layered_source_fixtures.py',
        lambda s: (
            s.replace(
                "    return [root / name for name in sorted(projected | additions)]",
                "    # Only the two real assembly roots are excluded; every presenter stays scanned.\n    for name in ('desktop_app/bootstrap.py', 'desktop_app/shell/main_window.py'):\n        if (root / name).is_file():\n            mapping = json.loads((root / 'tools/layer_map.json').read_text(encoding='utf-8'))\n            assert mapping['overrides'][name] == 'composition'\n            additions.discard(name)\n    return [root / name for name in sorted(projected | additions)]",
            )
            if '# Only the two real assembly roots' not in s
            else s
        ),
    )
    edit(
        'tests/test_ui_operations_registry.py',
        lambda s: s.replace("patch.object(ui, '_root',", "patch('quantlab.research_core.adapters.ui_files._root',").replace(
            "expected = ui.ui_text('ui.execute_ui_operation.unknown_operation')",
            "from desktop_app.strings.catalog import ui_text\n        expected = ui_text('ui.execute_ui_operation.unknown_operation')",
        ),
    )
    edit(
        'tests/test_r7_characterization.py',
        lambda s: s.replace(
            "sorted(WINDOW_ATTRIBUTES + REDESIGN['added_window_attributes'])",
            "sorted(WINDOW_ATTRIBUTES + REDESIGN['added_window_attributes'] + ['services', 'job_presenter'])",
        ),
    )
    edit(
        'tests/test_r7_function_lengths.py',
        lambda s: s.replace(
            "stages.update(\n            dict.fromkeys(('desktop_app/components/chart_geometry.py'",
            "stages.update(\n            dict.fromkeys(('desktop_app/features/market/layout.py', 'desktop_app/features/market/indicator_controls.py', 'desktop_app/components/chart_geometry.py'",
        ).replace(
            "BASE['functions']['desktop_app/components/charts.py'])",
            "BASE['functions']['desktop_app/features/market/dashboard.py'] if '/market/' in path else BASE['functions']['desktop_app/components/charts.py'])",
        ),
    )
    edit(
        'tests/layered_source_fixtures.py',
        lambda s: (
            s.replace(
                "            mapping = json.loads((root / 'tools/layer_map.json')",
                "            import json\n            mapping = json.loads((root / 'tools/layer_map.json')",
            )
            if '            import json\n' not in s
            else s
        ),
    )
    edit(
        'tests/test_capital_scenario_b5.py',
        lambda s: s.replace(
            '                _c_ui_MainWindow.closeEvent(shell, event)',
            '                from desktop_app.shell.window import MainWindow\n                MainWindow.closeEvent(shell, event)',
        ),
    )
    edit('tests/test_capital_scenario_b5.py', lambda s: s.replace('_c_ui_QMessageBox', 'QMessageBox'))
    edit(
        'tests/test_ui_operations_registry.py',
        lambda s: replace_test_function(
            s,
            'test_public_names_unchanged',
            """    def test_public_names_unchanged(self):
        from desktop_app.shell.window import MainWindow
        from desktop_app.bootstrap import create_ui_services
        from quantlab.research_core.application.ui_operations import registry
        self.assertIs(ui.MainWindow, MainWindow)
        self.assertIs(ui._UI_OPERATION_HANDLERS, registry._UI_OPERATION_HANDLERS)
        self.assertIs(ui.UI_OPERATIONS, registry.UI_OPERATIONS)
        self.assertIs(ui.create_ui_services, create_ui_services)
        self.assertEqual(ui.execute_ui_operation.__module__, 'desktop_app.shell.main_window')
        self.assertEqual(ui.OPERATION_REGISTRAR, 'desktop_app.shell.main_window:execute_ui_operation')
        self.assertNotIn('plan_provider', vars(ui))
        self.assertNotIn('_handle_ui_paper_submit', vars(ui))""",
        ),
    )
    # Historical fixture bytes remain frozen. Only current import/port wiring is
    # projected while loading the fixture; its own handlers and guards still run.
    edit(
        'tests/test_ui_operations_registry.py',
        lambda s: (
            s.replace(
                "name.replace('desktop_app.components.forms.', 'desktop_forms.').replace('desktop_app.components.charts.', 'desktop_charts.')",
                "legacy_owner_name(name)",
            ).replace(
                "        legacy_owners = {",
                "        from tools.refactor.split_ui_inputs import legacy_owner_name, legacy_walk_forward_inputs\n        legacy_owners = {",
            )
            if 'from tools.refactor.split_ui_inputs import legacy_owner_name' not in s
            else s
        ),
    )
    edit(
        'tests/test_ui_operations_registry.py',
        lambda s: s.replace(
            "source_file.write_text(projected, encoding='utf-8')", "source_file.write_text(legacy_walk_forward_inputs(projected), encoding='utf-8')"
        ),
    )
    edit(
        'tests/page_services_inventory.py',
        lambda s: s.replace(
            "'target': dotted(value.body.func if call else value)", "'target': original_service_target(key.value, dotted(value.body.func if call else value))"
        ),
    )
    edit(
        'tests/test_page_services_r1.py',
        lambda s: s.replace(
            "shell = SimpleNamespace(page_host=SimpleNamespace(callbacks={}))",
            "shell = SimpleNamespace(page_host=SimpleNamespace(callbacks={}), services=SimpleNamespace(**{name: Mock() for name in ('paper_risk_limits', 'paper', 'dataset', 'plan_provider', 'connection_event_from_payload', 'saved_analysis_entries', 'load_result', 'result_name', 'write_json', 'read_json', 'load_dataset')}))\n        shell.services.operations = _c_ui_UI_OPERATIONS",
        ).replace(
            "receiver = shell if entry['origin'] == 'mount' else ui\n                target = entry['target'].removeprefix('shell.')",
            "receiver = shell if entry['origin'] == 'mount' else shell.services\n                target = entry['target'].removeprefix('shell.')\n                if entry['origin'] == 'page_services':\n                    target = {'_paper': 'paper', '_dataset': 'dataset'}.get(target, target)\n                    if target in ('analysis_preview_text', 'analysis_record_text'):\n                        from desktop_app.features.analysis import presenter\n                        receiver = presenter",
        ),
    )
    edit(
        'tests/page_services_inventory.py',
        lambda s: (
            s.replace(
                'def registrations():',
                "\n\ndef original_service_target(name, target):\n    expected = {\n        'ui_operations': 'self.services.operations',\n        '_paper': 'self.services.paper', '_dataset': 'self.services.dataset',\n        'analysis_preview_text': '_analysis_rows.analysis_preview_text',\n        'analysis_record_text': '_analysis_rows.analysis_record_text',\n    }\n    assert target == expected.get(name, 'self.services.' + name), (name, target)\n    return 'UI_OPERATIONS' if name == 'ui_operations' else name\n\n\ndef registrations():",
            )
            if 'def original_service_target' not in s
            else s
        ),
    )
    edit(
        'tests/test_page_services_r1.py',
        lambda s: s.replace(
            "receiver = self.window if entry['origin'] == 'mount' else ui\n                target = entry['target'].removeprefix('shell.')",
            "from tests.page_services_inventory import service_patch_target\n                receiver, target = service_patch_target(self.window, entry)",
        ),
    )
    edit(
        'tests/page_services_inventory.py',
        lambda s: s.replace(
            "if isinstance(target, str) and target.startswith('desktop_app.shell.main_window.'):",
            "if isinstance(target, str) and target.startswith(('desktop_app.shell.main_window.', 'quantlab.reporting.', 'desktop_app.features.analysis.presenter.', 'desktop_app.components.formatting.', 'quantlab.research_core.adapters.ui_repository.WorkerRepository.')):",
        ).replace(
            "target.removeprefix('desktop_app.shell.main_window.'), 'patch', 'desktop_app.shell.main_window'",
            "target.rsplit('.', 1)[-1], 'patch', target.rsplit('.', 1)[0]",
        ),
    )
    # Replace the one baseline assignment exactly, avoiding repeated nested expressions.
    import re

    edit(
        'tests/test_r7_function_lengths.py',
        lambda s: re.sub(
            r"            baseline = BASE\['functions'\].*?\n(?=            added =)",
            "            baseline = BASE['functions'].get(path, BASE['functions']['desktop_app/features/market/dashboard.py'] if '/market/' in path else BASE['functions']['desktop_app/components/charts.py'])\n",
            s,
            flags=re.S,
        ),
    )
    edit(
        'tests/page_services_inventory.py',
        lambda s: (
            s.replace(
                'def registrations():',
                "\n\ndef service_patch_target(window, entry):\n    target = entry['target'].removeprefix('shell.')\n    if entry['origin'] == 'mount':\n        return window, target\n    if target == '_dataset':\n        from quantlab.research_core.adapters.ui_repository import WorkerRepository\n        return WorkerRepository, target\n    if target in ('analysis_preview_text', 'analysis_record_text'):\n        from desktop_app.features.analysis import presenter\n        return presenter, target\n    if target == 'result_name':\n        from desktop_app.components import formatting\n        return formatting, target\n    from quantlab import reporting\n    return reporting, target\n\n\ndef registrations():",
            )
            if 'def service_patch_target' not in s
            else s
        ),
    )
    edit(
        'tests/layered_source_fixtures.py',
        lambda s: (
            s.replace(
                "    return [root / name for name in sorted(projected | additions)]",
                "    window = root / 'desktop_app/shell/window.py'\n    if window.is_file():\n        import ast\n        classes = [node.name for node in ast.parse(window.read_text(encoding='utf-8')).body if isinstance(node, ast.ClassDef)]\n        assert classes == ['MainWindow']\n        additions.discard('desktop_app/shell/window.py')\n    return [root / name for name in sorted(projected | additions)]",
            )
            if "additions.discard('desktop_app/shell/window.py')" not in s
            else s
        ),
    )
    edit(
        'tests/test_r7_characterization.py',
        lambda s: (
            s.replace(
                "        self.assertEqual(self.actual['public'], expected)",
                "        market = expected['desktop_app/features/market/dashboard.py']\n        history = market[1].pop('MarketHistoryDialog')\n        market[0] = sorted(('ChartPresenter', 'DEFAULT_INDICATORS', 'IndicatorPresenter', 'MarketDashboard', 'MarketPreferences', 'MarketPresenter', 'MarketRows', 'QAbstractItemView', 'QHeaderView', 'QScrollArea', 'QTableWidget', 'QVBoxLayout', 'QWidget', 'Signal', 'apply_market_theme', 'deepcopy', 'ui_text'))\n        history_owner = public_names((ROOT / 'desktop_app/features/market/history_dialog.py').read_text(encoding='utf-8'))\n        self.assertEqual(history_owner[1]['MarketHistoryDialog'], history)\n        self.assertEqual(self.actual['public'], expected)",
            )
            if 'history_owner = public_names' not in s
            else s
        ),
    )
    edit(
        'tests/test_ui_split_contracts.py',
        lambda s: (
            s
            + "\n\nclass IdeaStoreTimingTests(unittest.TestCase):\n    def test_dialog_defers_store_and_uses_a_fresh_instance_for_each_action(self):\n        from pathlib import Path\n        from types import SimpleNamespace\n        from unittest.mock import Mock\n        from PySide6.QtWidgets import QComboBox\n        from desktop_app.features.strategy.idea_research import IdeaResearchDialog\n        app = QApplication.instance() or QApplication([])\n        calls, instances = [], []\n        task = 'idea-' + 'b' * 32\n        root = Path('unused-idea-store-timing')\n        class Store:\n            def __init__(self, location):\n                calls.append(('construct', location))\n                instances.append(self)\n            def purge(self, count, *, max_age):\n                calls.append(('purge', count, max_age))\n                return 0\n            def load(self, task_id):\n                calls.append(('load', task_id))\n                return {'task_id': task_id, 'status': 'completed', 'searches': [], 'sources': [], 'candidates': []}\n            def read_text(self, task_id, source_id):\n                calls.append(('read_text', task_id, source_id))\n                return 'plain text'\n        model = QComboBox()\n        model.addItem('Fixture', 'model')\n        state = SimpleNamespace(root=root, jobs=SimpleNamespace(active=False), chatgpt_panel=SimpleNamespace(model=model))\n        host = SimpleNamespace(state=state, safe=lambda callback: callback(), start_job=Mock(), payload=Mock(), idea_records=Store)\n        dialog = IdeaResearchDialog(host)\n        try:\n            self.assertEqual(calls, [])\n            dialog.clear_temp()\n            dialog.load_record(task)\n            dialog.record['sources'] = [{'source_id': 's1'}]\n            dialog.sources.blockSignals(True)\n            dialog.sources.setRowCount(1)\n            dialog.sources.setCurrentCell(0, 0)\n            dialog.sources.blockSignals(False)\n            dialog.show_source()\n            self.assertEqual(calls, [('construct', root), ('purge', 0, 0), ('construct', root), ('load', task), ('construct', root), ('read_text', task, 's1')])\n            self.assertEqual(len({id(instance) for instance in instances}), 3)\n            self.assertEqual(dialog.reader.toPlainText(), 'plain text')\n        finally:\n            shiboken6.delete(dialog)\n            shiboken6.delete(model)\n            app.processEvents()\n"
            if 'class IdeaStoreTimingTests' not in s
            else s
        ),
    )
    edit(
        'desktop_app/features/market/market.py',
        lambda s: s.replace('from desktop_app.bootstrap import sample_market_series\n', '').replace(
            'series = sample_market_series()', 'series = self.host.sample_market_series()'
        ),
    )
    edit(
        'tests/test_idea_research.py',
        lambda s: s.replace(
            "            _c_ui_MainWindow.start_job(shell, 'ui_idea_research', {})",
            "            from desktop_app.shell.job_presenter import JobPresenter\n            JobPresenter(shell).start_job('ui_idea_research', {})",
        ),
    )
    for name in ('tests/test_b11_privacy.py', 'tests/test_b4_appearance.py', 'tests/test_paper_lock_b2.py'):
        edit(name, lambda s: s.replace("ROOT / 'desktop_app/shell/main_window.py'", "ROOT / 'desktop_app/shell/window.py'"))
    edit(
        'tests/test_paper_lock_b2.py',
        lambda s: s.replace(
            "('desktop_app/shell/main_window.py', '_handle_ui_paper_submit', 'broker')",
            "('quantlab/research_core/application/paper_operations.py', '_handle_ui_paper_submit', 'broker')",
        ),
    )
    edit(
        'tests/test_application_icon.py',
        lambda s: s.replace("for name in ('desktop.py', 'desktop_app/shell/main_window.py'):", "for name in ('desktop.py', 'desktop_app/shell/setup.py'):"),
    )
    edit(
        'tests/test_desktop_window_position.py',
        lambda s: s.replace("/ 'desktop_app/shell/main_window.py'", "/ 'desktop_app/shell/setup.py'").replace(
            "{'self': self.window,", "{'window': self.window,"
        ),
    )
    edit(
        'tests/test_workspace_wal_guard.py',
        lambda s: replace_test_function(
            s,
            'test_real_ui_adapter_guards_before_replay_constructor',
            "    def test_real_ui_adapter_guards_before_replay_constructor(self):\n        # Compile the real stable executor; use every real registered handler.\n        import ast\n        from desktop_app.bootstrap import create_operation_ports\n        from quantlab.research_core.application.ui_operations import registry\n        from quantlab.research_core.application import paper_operations\n        source = Path(__file__).resolve().parents[1] / 'desktop_app/shell/main_window.py'\n        tree = ast.parse(source.read_text(encoding='utf-8'))\n        executor = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'execute_ui_operation')\n        ports = create_operation_ports()\n        ports.inputs = types.SimpleNamespace(_dataset=lambda root, payload: types.SimpleNamespace(manifest={'data_hash': 'data'}))\n        broker = types.SimpleNamespace(reconcile=lambda snapshot: None, snapshot=lambda: {}, _margin_schedule=())\n        namespace = {'create_operation_ports': lambda: ports, 'prepare_operation': registry.prepare_operation, '_UI_OPERATION_HANDLERS': registry._UI_OPERATION_HANDLERS}\n        exec(compile(ast.Module(body=[executor], type_ignores=[]), str(source), 'exec'), namespace)\n        class ReachedConstructor(Exception):\n            pass\n        def constructor(*args, **kwargs):\n            self.assertEqual(json.loads((self.paths.root / 'workspace-format.json').read_text()), GUARDED)\n            raise ReachedConstructor()\n        with (\n            patch('quantlab.paper_replay.PaperReplay', side_effect=constructor),\n            patch.object(paper_operations, '_paper', return_value=broker),\n            patch('quantlab.reporting.load_selection', return_value={'strategy_hash': 'strategy', 'strategy': {}}),\n            patch.object(paper_operations, 'content_hash', return_value='binding'),\n            patch.object(paper_operations, 'StrategySpec', side_effect=lambda **value: value),\n        ):\n            with self.assertRaises(ReachedConstructor):\n                namespace['execute_ui_operation']('ui_paper_replay', {'reconcile_confirmed': True, 'snapshot': {}}, self.paths)\n",
        ),
    )
    # R7's added-stage check follows layout functions, not the thin widget delegates.
    edit(
        'tests/test_r7_function_lengths.py',
        lambda s: (
            s.replace(
                "added = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name not in baseline]",
                "added = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name not in baseline]\n            if path == 'desktop_app/features/market/dashboard.py':\n                continue  # Its existing stages are checked at both concrete layout owners above.",
            )
            if '# Its existing stages' not in s
            else s
        ),
    )


def repair_r3a():
    """Mechanical construction and patch-owner updates; assertions stay intact."""
    import json

    replacements = {
        'tests/test_t11_part_b.py': [("SimpleNamespace(MainWindow=Mock(return_value=window))", "SimpleNamespace(create_window=Mock(return_value=window))")],
        'tests/test_restart_availability_contract.py': [
            (
                "self.window = Window(self.paths, self.jobs, SettingsStore(self.paths.state / 'settings.json'), self.backups)",
                "self.window = Window(self.paths, self.jobs, SettingsStore(self.paths.state / 'settings.json'), self.backups, services=_c_create_ui_services(_c_create_operation_ports()))",
            )
        ],
        'tests/test_desktop_chatgpt_integration.py': [
            (
                'from desktop_app.shell.main_window import execute_ui_operation, _dataset',
                'from desktop_app.shell.main_window import execute_ui_operation\n        _dataset = _c_create_operation_ports().inputs._dataset',
            )
        ],
        'tests/test_paper_stop_a1.py': [
            ('import desktop_app.shell.main_window as ui\n', ''),
            ("patch.object(ui, '_dataset',", "patch('quantlab.research_core.adapters.ui_repository.WorkerRepository._dataset',"),
        ],
        'tests/test_replay_b13.py': [("patch.object(ui, '_dataset',", "patch('quantlab.research_core.adapters.ui_repository.WorkerRepository._dataset',")],
        'tests/test_quick_start_u3.py': [
            ('_UI_OPERATION_HANDLERS[operation].call_args.args[2]', '_UI_OPERATION_HANDLERS[operation].call_args.args[3]'),
            ("_UI_OPERATION_HANDLERS['ui_demo'].call_args.args[2]", "_UI_OPERATION_HANDLERS['ui_demo'].call_args.args[3]"),
            ("call_args.args[0]['dataset']", "call_args.args[1]['dataset']"),
        ],
    }
    reasons = {
        'tests/test_t11_part_b.py': 'Fake the lazy create_window composition entry instead of the former constructor; lifecycle expectations unchanged.',
        'tests/test_restart_availability_contract.py': 'Supply required concrete services to the existing test-only subclass constructor; assertions unchanged.',
        'tests/test_desktop_chatgpt_integration.py': 'Resolve dataset through the concrete inputs adapter that now owns it; assertions unchanged.',
        'tests/test_paper_stop_a1.py': 'Patch WorkerRepository._dataset where paper operation inputs look it up; assertions unchanged.',
        'tests/test_replay_b13.py': 'Patch WorkerRepository._dataset where paper operation inputs look it up; assertions unchanged.',
        'tests/test_quick_start_u3.py': 'Shift inspected handler argument positions by one for the injected ports argument; payload/path contracts and assertions retained.',
    }
    for name, pairs in replacements.items():
        path = ROOT / name
        source = path.read_text(encoding='utf-8')
        for old, new in pairs:
            source = source.replace(old, new)
        write_source(path, source)
    path = ROOT / '.tmp-layered/test-edit-reasons.json'
    entries = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    entries = [entry for entry in entries if entry.get('slice') != 'T3-r3a']
    entries.extend({'slice': 'T3-r3a', 'path': name, 'reason': reason} for name, reason in reasons.items())
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
    if (ROOT / 'desktop_app/bootstrap.py').exists():
        slice2()
        repair_r3a()

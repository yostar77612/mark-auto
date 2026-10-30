"""Prepare the market view/presenters and the genuine pure session model."""

from __future__ import annotations

# Historical pass: never overwrite the applied split or its subsequent repairs.
from pathlib import Path as _AppliedPath

if __name__ == '__main__' and (_AppliedPath(__file__).resolve().parents[2] / 'desktop_app/features/market/rows.py').is_file():
    print('split_ui_market.py: already applied')
    raise SystemExit(0)


import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path

from tools.refactor.split_ui_modules import names_defined, used_imports
from tools.refactor.split_ui_modules import read_source


PREFIX = 'desktop_app/features/market/'
GROUPS = {
    'presenter': (
        'set_market_series',
        'set_quote_series',
        'selected_series',
        'set_loading',
        '_fill_contracts',
        '_filter_catalog',
        '_render_watch',
        '_add_watch',
        '_remove_watch',
        '_move_watch',
        '_watch_selected',
        '_contract_changed',
        '_timeframe_changed',
    ),
    'preferences': ('preferences', '_prepare_chart_memory', 'restore_preferences'),
    'indicator_presenter': (
        '_indicators_changed',
        '_restore_indicator_controls',
        '_apply_indicators',
        'refresh_annotations',
        '_annotation_preferences_changed',
    ),
    'rows': ('_render_cards', 'set_trading_status', 'set_account_tables'),
    'chart_presenter': ('_render_chart',),
}
CLASS_NAMES = {
    'preferences': 'MarketPreferences',
    'presenter': 'MarketPresenter',
    'indicator_presenter': 'IndicatorPresenter',
    'rows': 'MarketRows',
    'chart_presenter': 'ChartPresenter',
}
FIELDS = {
    'preferences': 'preference_presenter',
    'presenter': 'presenter',
    'indicator_presenter': 'indicator_presenter',
    'rows': 'rows',
    'chart_presenter': 'chart_presenter',
}
GLOBAL_GROUPS = {
    'rows': ('_identity', '_friendly_contract', '_friendly_source', '_label', '_named', '_series_source'),
    'indicator_presenter': ('DEFAULT_INDICATORS',),
    'layout': (
        '_build_market_header',
        '_build_market_cards',
        '_build_market_diagnostics',
        '_build_market_empty_actions',
        '_build_market_watchlist',
        '_build_market_chart',
    ),
    'detail_layout': (
        '_build_market_trading_status',
        '_build_market_indicators',
        '_build_market_panel_toggle',
        '_build_market_tables',
        '_build_market_workspace',
    ),
}
SESSION_NAMES = {
    'MAX_BARS',
    'MAX_SESSIONS',
    'PRODUCT_SOURCES',
    'UTC',
    'TAIPEI',
    '_fail',
    '_stamp',
    'MarketSession',
    '_session_dict',
    'session_from_dict',
    '_sessions',
}


def expr(text):
    return ast.parse(text, mode='eval').body


class ViewMethods(ast.NodeTransformer):
    def __init__(self, own):
        self.own = own

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == 'self':
            if node.attr not in self.own:
                node.value = expr('self.view')
            return node
        return self.generic_visit(node)

    def visit_Name(self, node):
        if node.id == 'self' and isinstance(node.ctx, ast.Load):
            return expr('self.view')
        return node


def forwarding(method, field):
    result = deepcopy(method)
    if any(isinstance(decorator, ast.Name) and decorator.id == 'property' for decorator in method.decorator_list):
        result.body = [ast.Return(value=expr('self.' + field + '.' + method.name))]
        return result
    args = [ast.Name(id=argument.arg, ctx=ast.Load()) for argument in method.args.args[1:]]
    if method.args.vararg:
        args.append(ast.Starred(value=ast.Name(id=method.args.vararg.arg, ctx=ast.Load()), ctx=ast.Load()))
    keywords = [ast.keyword(arg=argument.arg, value=ast.Name(id=argument.arg, ctx=ast.Load())) for argument in method.args.kwonlyargs]
    if method.args.kwarg:
        keywords.append(ast.keyword(arg=None, value=ast.Name(id=method.args.kwarg.arg, ctx=ast.Load())))
    result.body = [ast.Return(value=ast.Call(func=expr('self.' + field + '.' + method.name), args=args, keywords=keywords))]
    return result


def output_module(nodes, imports, own_names, global_owners):
    loads = {node.id for parent in nodes for node in ast.walk(parent) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    statements = used_imports(imports, loads)
    groups = {}
    for name in sorted(loads & global_owners.keys() - set(own_names)):
        groups.setdefault(global_owners[name], []).append(name)
    statements += ['from ' + path.removesuffix('.py').replace('/', '.') + ' import ' + ', '.join(names) for path, names in sorted(groups.items())]
    return '\n'.join(statements) + '\n\n' + '\n\n'.join(ast.unparse(ast.fix_missing_locations(node)) for node in nodes) + '\n'


def market_outputs(source):
    tree = ast.parse(source)
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    globals_ = {name: node for node in tree.body for name in names_defined(node)}
    dashboard = deepcopy(globals_['MarketDashboard'])
    class_owners = {CLASS_NAMES[group]: PREFIX + group + '.py' for group in GROUPS}
    global_owners = {name: PREFIX + group + '.py' for group, names in GLOBAL_GROUPS.items() for name in names}
    global_owners.update(class_owners)
    classes = {}
    methods = {node.name: node for node in dashboard.body if isinstance(node, ast.FunctionDef)}
    for group, names in GROUPS.items():
        controller = ast.parse('class ' + CLASS_NAMES[group] + ':\n    def __init__(self, view):\n        self.view = view\n').body[0]
        controller.body.extend(ViewMethods(set()).visit(deepcopy(methods[name])) for name in names)
        classes[group] = controller
    moved = {name: group for group, names in GROUPS.items() for name in names}
    for index, node in enumerate(dashboard.body):
        if isinstance(node, ast.FunctionDef) and node.name in moved:
            dashboard.body[index] = forwarding(node, FIELDS[moved[node.name]])
        elif isinstance(node, ast.FunctionDef) and node.name == '__init__':
            assignments = ast.parse('\n'.join('self.' + FIELDS[group] + ' = ' + CLASS_NAMES[group] + '(self)' for group in GROUPS)).body
            node.body[1:1] = assignments
    outputs = {PREFIX + 'dashboard.py': output_module([dashboard], imports, ('sample_market_series', 'MarketDashboard'), global_owners)}
    outputs[PREFIX + 'dashboard.py'] = 'from quantlab.market import MarketValidationError as MarketValidationError\n' + outputs[PREFIX + 'dashboard.py']
    for group, names in GLOBAL_GROUPS.items():
        nodes = [deepcopy(globals_[name]) for name in names]
        if group in classes:
            nodes.append(classes[group])
        outputs[PREFIX + group + '.py'] = output_module(nodes, imports, (*names, CLASS_NAMES.get(group, '')), global_owners)
    for group in set(GROUPS) - GLOBAL_GROUPS.keys():
        outputs[PREFIX + group + '.py'] = output_module([classes[group]], imports, (CLASS_NAMES[group],), global_owners)
    dialog = deepcopy(globals_['MarketHistoryDialog'])

    class SessionImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == 'quantlab.market_history' and all(alias.name in SESSION_NAMES for alias in node.names):
                node.module = 'quantlab.research_core.domain.market_sessions'
            return node

    dialog = SessionImports().visit(dialog)
    outputs[PREFIX + 'history_dialog.py'] = output_module([dialog], imports, ('MarketHistoryDialog',), global_owners)
    return outputs


def session_outputs(source):
    tree = ast.parse(source)
    nodes = [deepcopy(node) for node in tree.body if set(names_defined(node)) & SESSION_NAMES]
    imports = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            node = deepcopy(node)
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                node.module, node.level = 'quantlab.' + node.module, 0
            imports.append(node)
    domain = output_module(nodes, imports, SESSION_NAMES, {})
    # UI-only validation retains a pure model; PR E2 owns the history adapter.
    return {'quantlab/research_core/domain/market_sessions.py': domain}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    root, output = args.source_root.resolve(), args.output_root.resolve()
    if root == output:
        parser.error('Preparation must not overwrite product sources')
    outputs = market_outputs(read_source(root, 'desktop_market.py'))
    outputs.update(session_outputs((root / 'quantlab/market_history.py').read_text(encoding='utf-8-sig')))
    report = {}
    for name, source in outputs.items():
        ast.parse(source, feature_version=(3, 11))
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8', newline='\n')
        report[name] = len(source.splitlines())
    (output / 'market-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()

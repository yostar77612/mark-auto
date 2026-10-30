"""Prepare AST-preserving PR C module extractions without applying them.

Outputs are a review fixture, not a complete refactor: the report deliberately
retains unresolved layer debts for the implementation step to resolve via ports.
Every existing definition has exactly one concrete owner, with no re-exports.
"""

from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from collections import defaultdict
import json
from pathlib import Path


FORMS = {
    'desktop_app/components/forms.py': ('_Form', '_Rows'),
    'desktop_app/components/form_values.py': ('number', 'required', 'utc'),
    'desktop_app/features/backtest/forms.py': ('BacktestForm',),
    'desktop_app/features/strategy/forms.py': ('FAMILY_LABELS', 'PARAM_LABELS', 'StrategyForm'),
    'desktop_app/features/research/forms.py': ('CampaignForm',),
    'desktop_app/features/walk_forward/forms.py': ('WalkForwardForm',),
    'desktop_app/features/paper/forms.py': ('PaperIntentForm', 'PaperQuoteForm', 'PaperSnapshotForm', 'PaperActionForm'),
    'desktop_app/features/paper/policy_form.py': ('PaperPolicyForm',),
    'desktop_app/components/result_tables.py': ('RESULT_LABELS', 'readable', 'ResultTable', 'SummaryCard'),
    'desktop_app/features/backtest/summary.py': (
        '_REPORT_TEXT',
        '_report_text',
        '_report_number',
        'backtest_summary_text',
        'BacktestSummaryCard',
        '_FILL_REASONS',
        'BacktestFillsTable',
    ),
    'desktop_app/features/strategy/summary.py': ('_CANDIDATE_EVALUATION_LABELS', 'candidate_summary_text', 'CandidateSummaryCard'),
}
CHARTS = {
    'desktop_app/components/chart_footer.py': ('_display_time', '_footer_items'),
    'desktop_app/components/chart_annotations.py': ('ChartTrace', '_number', '_validate_chart_bar', 'ChartMarker', 'ReferenceLine', '_ChartAnnotationMixin'),
    'desktop_app/components/charts.py': ('_paint_drawings', 'CandlestickChart'),
    'desktop_app/components/chart_geometry.py': ('_prepare_chart_geometry',),
    'desktop_app/components/chart_paint.py': ('_paint_chart_bars', '_paint_chart_references', '_paint_chart_markers_and_panes'),
    'desktop_app/components/chart_paint_footer.py': ('_paint_chart_footer',),
    'desktop_app/components/chart_interaction.py': ('ChartInteraction',),
}


def dotted(path):
    return path.removesuffix('.py').replace('/', '.').removesuffix('.__init__')


def names_defined(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return tuple(target.id for target in targets if isinstance(target, ast.Name))
    return ()


def original_fragment(source, node):
    first = min([node.lineno] + [decorator.lineno for decorator in getattr(node, 'decorator_list', ())])
    return ''.join(source.splitlines(keepends=True)[first - 1 : node.end_lineno]).rstrip() + '\n'


def used_imports(imports, names):
    statements = []
    for node in imports:
        kept = [item for item in node.names if (item.asname or (item.name.split('.')[0] if isinstance(node, ast.Import) else item.name)) in names]
        if kept:
            result = ast.Import(names=kept) if isinstance(node, ast.Import) else ast.ImportFrom(module=node.module, names=kept, level=node.level)
            statements.append(ast.unparse(result))
    return statements


def normalize_imports(text, relocations):
    """Mirror B's already-declared module paths in a legacy-source prep fixture."""
    modules = {dotted(old): dotted(new) for old, new in relocations.items()}
    tree = ast.parse(text)
    lines = text.encode('utf-8').splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rewritten = []
            for alias in node.names:
                target = modules.get(alias.name, alias.name)
                rewritten.append(ast.alias(name=target, asname=alias.asname or alias.name if target != alias.name else alias.asname))
            changed = ast.Import(names=rewritten)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            target = modules.get(node.module, node.module)
            if target == 'quantlab.__main__' and all(alias.name == 'config_from_json' for alias in node.names):
                target = 'quantlab.configuration'
            changed = ast.ImportFrom(module=target, names=node.names, level=0)
        else:
            continue
        if ast.dump(node, include_attributes=False) != ast.dump(changed, include_attributes=False):
            edits.append((offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset, ast.unparse(changed)))
    raw = text.encode('utf-8')
    for start, end, replacement in sorted(edits, reverse=True):
        raw = raw[:start] + replacement.encode('utf-8') + raw[end:]
    return raw.decode('utf-8')


def chart_interaction(source):
    """Give pointer/keyboard viewport behavior a composed, testable owner."""
    tree = ast.parse(source)
    chart = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'CandlestickChart')
    names = {'_pan', '_zoom', 'wheelEvent', 'mousePressEvent', 'mouseMoveEvent', 'leaveEvent', 'keyPressEvent'}

    class ViewReferences(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'self' and node.attr not in ('_pan', '_zoom'):
                node.value = ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr='view', ctx=ast.Load())
                return node
            return self.generic_visit(node)

        def visit_Expr(self, node):
            call = node.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'keyPressEvent':
                owner = call.func.value
                if isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name) and owner.func.id == 'super':
                    return ast.Return(value=ast.Constant(False))
            return self.generic_visit(node)

    moved, edits = [], []
    for method in chart.body:
        if not isinstance(method, ast.FunctionDef) or method.name not in names:
            continue
        prepared = ViewReferences().visit(deepcopy(method))
        if method.name == 'keyPressEvent':
            prepared.body.append(ast.Return(value=ast.Constant(True)))
        moved.append(ast.unparse(ast.fix_missing_locations(prepared)))
        if method.name in ('_pan', '_zoom'):
            replacement = ''
        elif method.name == 'keyPressEvent':
            replacement = (
                '    def keyPressEvent(self, event):\n        if not self.interaction.keyPressEvent(event):\n            super().keyPressEvent(event)\n'
            )
        else:
            replacement = f'    def {method.name}(self, event):\n        self.interaction.{method.name}(event)\n'
        edits.append((method.lineno, method.end_lineno, replacement))
    if len(moved) != len(names):
        raise ValueError('Chart interaction source no longer matches its reviewed boundary')
    lines = source.splitlines(keepends=True)
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start - 1 : end] = [replacement]
    source = ''.join(lines)
    initialization = '        self._drag = None\n'
    if source.count(initialization) != 1:
        raise ValueError('Expected the remaining constructor drag initialization')
    source = source.replace(initialization, initialization + '        self._marker_index = {}\n        self.interaction = ChartInteraction(self)\n', 1)
    body = '\n\n'.join('    ' + method.replace('\n', '\n    ') for method in moved)
    source += (
        '\n\nclass ChartInteraction:\n    """Viewport interactions; the Qt view retains data and painting."""\n\n    def __init__(self, view):\n        self.view = view\n\n'
        + body
        + '\n'
    )
    return source


def prepare_module(root, source_path, ownership, destination, relocations):
    actual_source = root / relocations.get(source_path, source_path)
    if not actual_source.exists():
        actual_source = root / source_path
    original = actual_source.read_text(encoding='utf-8-sig')
    source = normalize_imports(original, relocations)
    if source_path == 'desktop_forms.py':
        # Backtest UI defaults are data construction, not report storage. Keep
        # exactly the reporting demo's values without importing its IO adapter.
        source = source.replace('from quantlab.reporting import demo_config', 'from quantlab.core import BacktestConfig, CostSpec')
        source = source.replace(
            "to_dict(demo_config())",
            """to_dict(BacktestConfig(
            Decimal('1000000'),
            CostSpec(Decimal('20'), Decimal('0.00002'), 1, 'half_up_twd', '2026-01-01', 'synthetic-assumption-v1'),
            initial_margin_per_contract=Decimal('100000'),
            margin_version='synthetic-assumption-v1',
            maintenance_margin_per_contract=Decimal('80000'),
        ))""",
        )
    if source_path == 'desktop_charts.py':
        source = chart_interaction(source)
        # Drawing projection stays with its existing storage-domain dependency;
        # the bar renderer receives the painter callback, avoiding an import cycle.
        source = source.replace(
            '_paint_chart_bars(self, p, text, start, end, visible, r, low, high, x, y, step)',
            '_paint_chart_bars(self, p, text, start, end, visible, r, low, high, x, y, step, paint_drawings)',
        )
        source = source.replace('step, paint_drawings)\n', 'step, _paint_drawings)\n')
        source = source.replace('    _paint_drawings(p, self.drawings, self.bars, r, x, y)', '    paint_drawings(p, self.drawings, self.bars, r, x, y)')
    tree = ast.parse(source)
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    definitions = {name: node for node in tree.body for name in names_defined(node)}
    owners = {name: path for path, names in ownership.items() for name in names}
    if set(definitions) != set(owners):
        raise ValueError({'unassigned': sorted(set(definitions) - set(owners)), 'missing': sorted(set(owners) - set(definitions))})
    nodes_by_path = defaultdict(list)
    for node in tree.body:
        names = names_defined(node)
        if names:
            paths = {owners[name] for name in names}
            if len(paths) != 1:
                raise ValueError('A single definition cannot have more than one owner')
            nodes_by_path[paths.pop()].append(node)
    report = []
    for path, nodes in nodes_by_path.items():
        body = '\n\n'.join(original_fragment(source, node) for node in nodes)
        references = {node.id for node in ast.walk(ast.parse(body)) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        dependencies = defaultdict(set)
        for name in references & owners.keys():
            if owners[name] != path:
                dependencies[dotted(owners[name])].add(name)
        statements = used_imports(imports, references)
        statements += [f'from {module} import ' + ', '.join(sorted(names)) for module, names in sorted(dependencies.items())]
        text = '"""' + path.removesuffix('.py').replace('/', ' ') + ' responsibilities."""\n\n' + '\n'.join(statements) + '\n\n\n' + body
        extracted = ast.parse(text, feature_version=(3, 11))
        by_name = {name: node for node in extracted.body for name in names_defined(node)}
        for name in ownership[path]:
            if ast.dump(by_name[name], include_attributes=False) != ast.dump(definitions[name], include_attributes=False):
                raise AssertionError(f'Extraction changed {name}')
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')
        report.append({'path': path, 'lines': len(text.splitlines()), 'definitions': list(ownership[path]), 'imports': statements})
    return report, {dotted(relocations.get(source_path, source_path)) + '.' + name: dotted(owner) + '.' + name for name, owner in owners.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    root, destination = args.source_root.resolve(), args.output_root.resolve()
    if root == destination:
        parser.error('Preparation must not overwrite a product worktree')
    relocations = json.loads((root / 'tools/layer_relocations.json').read_text(encoding='utf-8'))
    report, symbol_owners = [], {}
    for path, ownership in (('desktop_forms.py', FORMS), ('desktop_charts.py', CHARTS)):
        result, symbols = prepare_module(root, path, ownership, destination, relocations)
        report.extend(result)
        symbol_owners.update(symbols)
    (destination / 'module-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (destination / 'symbol-owners.json').write_text(json.dumps(symbol_owners, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps([{'path': item['path'], 'lines': item['lines']} for item in report], ensure_ascii=False))


if __name__ == '__main__':
    main()

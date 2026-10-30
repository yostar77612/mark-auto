"""Prepare the idea dialog around actual presenters and an injected record port."""

from __future__ import annotations

# Historical pass: never overwrite the applied split or its subsequent repairs.
from pathlib import Path as _AppliedPath

if __name__ == '__main__' and (_AppliedPath(__file__).resolve().parents[2] / 'desktop_app/features/strategy/idea_presenter.py').is_file():
    print('split_ui_idea.py: already applied')
    raise SystemExit(0)


import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path

from tools.refactor.split_ui_market import ViewMethods, forwarding
from tools.refactor.split_ui_modules import names_defined, used_imports
from tools.refactor.split_ui_modules import read_source


BASE = 'desktop_app/features/strategy/'
GROUPS = {
    'idea_presenter': (
        'discovery_mode',
        '_choose',
        '_set_fallback',
        'busy',
        'refresh_controls',
        '_identity',
        '_consent',
        '_reset_consent',
        'start',
        'retry',
        'cancel',
        'clear_temp',
        'adopt',
        'apply',
        '_upsert',
        'load_record',
        'job_ended',
    ),
    'idea_rows': ('render_searches', '_origin', '_row_url', 'render_sources', 'show_source', 'render_candidates', 'show_candidate', 'render_status'),
}
CLASS_NAMES = {'idea_presenter': 'IdeaPresenter', 'idea_rows': 'IdeaRows'}
FIELDS = {'idea_presenter': 'presenter', 'idea_rows': 'rows'}
LABELS = ('FAMILY_TEXT', 'TIMEFRAME_TEXT', 'DISCOVERY_TEXT', 'STATE_TEXT', 'STATUS_TEXT', 'STOP_TEXT', 'COLUMN_TEXT', 'FAMILIES', 'STATES', 'COLUMNS')


class RecordPort(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        if node.module == 'quantlab.idea_research' and all(alias.name == 'IdeaStore' for alias in node.names):
            return None
        return node

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == 'IdeaStore':
            return ast.parse('self.records()', mode='eval').body
        return self.generic_visit(node)


def module(nodes, imports, owners, own):
    loads = {node.id for parent in nodes for node in ast.walk(parent) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    statements = used_imports(imports, loads)
    grouped = {}
    for name in sorted(loads & owners.keys() - set(own)):
        grouped.setdefault(owners[name], []).append(name)
    statements += ['from ' + path.removesuffix('.py').replace('/', '.') + ' import ' + ', '.join(names) for path, names in sorted(grouped.items())]
    return '\n'.join(statements) + '\n\n' + '\n\n'.join(ast.unparse(ast.fix_missing_locations(node)) for node in nodes) + '\n'


def layout_sections(layout):
    body = layout.body
    starts = {}
    markers = {
        'filters': 'form = QFormLayout()',
        'discovery': 'self.discovery = QButtonGroup(self)',
        'consent': 'self.model_summary = QLabel()',
        'actions': 'actions = QHBoxLayout()',
        'sources': "source_layout.addWidget(QLabel(ui_text('idea.sources')))",
        'candidates': "results.addWidget(QLabel(ui_text('idea.candidates')))",
    }
    for key, marker in markers.items():
        wanted = ast.dump(ast.parse(marker).body[0], include_attributes=False)
        starts[key] = next(index for index, node in enumerate(body) if ast.dump(node, include_attributes=False) == wanted)
    blocks = (
        ('_build_idea_workspaces', ('self',), body[: starts['filters']], 'layout, conditions, results, source_layout'),
        ('_build_idea_filters', ('self', 'conditions'), body[starts['filters'] : starts['discovery']], 'form'),
        ('_build_idea_discovery', ('self', 'form'), body[starts['discovery'] : starts['consent']], None),
        ('_build_idea_consent', ('self', 'conditions'), body[starts['consent'] : starts['actions']], None),
        ('_build_idea_actions', ('self', 'layout', 'conditions', 'source_layout'), body[starts['actions'] : starts['sources']], None),
        ('_build_idea_sources', ('self', 'source_layout'), body[starts['sources'] : starts['candidates']], None),
        ('_build_idea_candidates', ('self', 'results'), body[starts['candidates'] : -1], None),
    )
    functions = []
    for name, parameters, statements, returned in blocks:
        function = ast.parse('def ' + name + '(' + ', '.join(parameters) + '):\n    pass\n').body[0]
        function.body = deepcopy(statements)
        if returned is not None:
            function.body.extend(ast.parse('return ' + returned).body)
        functions.append(function)
    layout.body = ast.parse('''layout, conditions, results, source_layout = _build_idea_workspaces(self)
form = _build_idea_filters(self, conditions)
_build_idea_discovery(self, form)
_build_idea_consent(self, conditions)
_build_idea_actions(self, layout, conditions, source_layout)
_build_idea_sources(self, source_layout)
_build_idea_candidates(self, results)
self.refresh_controls()
''').body
    flattened = [statement for function in functions for statement in function.body if not isinstance(statement, ast.Return)] + [body[-1]]
    if [ast.dump(node, include_attributes=False) for node in flattened] != [ast.dump(node, include_attributes=False) for node in body]:
        raise AssertionError('Layout extraction changed an original construction statement or its order')
    return functions + [layout]


def idea_outputs(source):
    tree = ast.parse(source)
    imports = [deepcopy(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    for node in imports:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            node.module, node.level = 'desktop_pages.' + node.module, 0
    globals_ = {name: node for node in tree.body for name in names_defined(node)}
    owners = {name: BASE + 'idea_labels.py' for name in LABELS}
    owners.update({'open_url': BASE + 'idea_links.py', '_plain': BASE + 'idea_rows.py'})
    owners.update({value: BASE + key + '.py' for key, value in CLASS_NAMES.items()})
    owners['IdeaRecords'] = 'quantlab/research_core/ports/idea_records.py'
    imports.append(ast.ImportFrom(module='typing', names=[ast.alias(name='Callable')], level=0))
    dialog = deepcopy(globals_['IdeaResearchDialog'])
    methods = {node.name: node for node in dialog.body if isinstance(node, ast.FunctionDef)}
    controllers = {}
    for group, names in GROUPS.items():
        controller = ast.parse('class ' + CLASS_NAMES[group] + ':\n    def __init__(self, view):\n        self.view = view\n').body[0]
        for name in names:
            method = RecordPort().visit(deepcopy(methods[name]))
            controller.body.append(ViewMethods(set()).visit(method))
        controllers[group] = controller
    moved = {name: group for group, names in GROUPS.items() for name in names}
    constructor = methods['__init__']
    layout = deepcopy(constructor)
    layout.name = 'configure_idea_dialog'
    layout.args.args = [ast.arg(arg='self')]
    layout.args.defaults = []
    layout.body = deepcopy(constructor.body[4:])
    # Widget setup remains concrete UI; the controller stores no widget copies.
    constructor.body = ast.parse(
        'super().__init__(parent)\nself.host = host\nself.state = host.state\nself.record = None\nself.records: Callable[[], IdeaRecords] = lambda: host.idea_records(self.state.root)\nself.presenter = IdeaPresenter(self)\nself.rows = IdeaRows(self)\nconfigure_idea_dialog(self)'
    ).body
    owners['configure_idea_dialog'] = BASE + 'idea_layout.py'
    for index, node in enumerate(dialog.body):
        if isinstance(node, ast.FunctionDef) and node.name in moved:
            dialog.body[index] = forwarding(node, FIELDS[moved[node.name]])
    output = {
        BASE + 'idea_research.py': module([dialog], imports, owners, ('IdeaResearchDialog',)),
        BASE + 'idea_layout.py': module(layout_sections(layout), imports, owners, ('configure_idea_dialog',)),
        BASE + 'idea_labels.py': module([deepcopy(globals_[name]) for name in LABELS], imports, owners, LABELS),
        BASE + 'idea_links.py': module([deepcopy(globals_['open_url'])], imports, owners, ('open_url',)),
        BASE + 'idea_events.py': module([deepcopy(globals_['dialog_for']), deepcopy(globals_['event'])], imports, owners, ('dialog_for', 'event')),
    }
    for group, controller in controllers.items():
        nodes = ([deepcopy(globals_['_plain'])] if group == 'idea_rows' else []) + [controller]
        output[BASE + group + '.py'] = module(nodes, imports, owners, (CLASS_NAMES[group], '_plain'))
    output['quantlab/research_core/ports/idea_records.py'] = '''"""Read and purge capabilities used by the idea presentation."""
from typing import Protocol

class IdeaRecords(Protocol):
    def load(self, task_id: str) -> dict: ...
    def read_text(self, task_id: str, source_id: str) -> str: ...
    def purge(self, max_tasks: int, *, max_age: int) -> int: ...
'''
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    root, output = args.source_root.resolve(), args.output_root.resolve()
    if root == output:
        parser.error('Preparation cannot overwrite product sources')
    outputs = idea_outputs(read_source(root, 'desktop_pages/idea_research.py'))
    report = {}
    for name, source in outputs.items():
        ast.parse(source, feature_version=(3, 11))
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8', newline='\n')
        report[name] = len(source.splitlines())
    (output / 'idea-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()

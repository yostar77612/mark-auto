"""Compose the real window around prepared application ports in a fixture tree."""

from __future__ import annotations


import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path

from tools.refactor.split_ui_modules import used_imports
from tools.refactor.split_ui_modules import read_source


SERVICES = {
    '_root': 'state_root',
    'UI_OPERATIONS': 'operations',
    'paper_risk_limits': 'paper_risk_limits',
    '_paper': 'paper',
    '_dataset': 'dataset',
    'candidate_record': 'candidate_record',
    'plan_provider': 'plan_provider',
    'connection_event_from_payload': 'connection_event_from_payload',
    'dataset_market_series': 'dataset_market_series',
    'latest_market_observations': 'latest_market_observations',
    'saved_analysis_entries': 'saved_analysis_entries',
    'load_result': 'load_result',
    'result_name': 'result_name',
    'write_json': 'write_json',
    'read_json': 'read_json',
    'load_dataset': 'load_dataset',
    'require_operation': 'require_operation',
}
PRESENTER = {'start_job', 'cancel_job', 'poll_jobs', '_quiesce_and_recover', '_busy', 'notify_local', '_notification_link'}


def expr(text):
    return ast.parse(text, mode='eval').body


class ServiceReferences(ast.NodeTransformer):
    def __init__(self, receiver):
        self.receiver = receiver

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in SERVICES:
            return expr(self.receiver + '.' + SERVICES[node.id])
        return node

    def visit_ImportFrom(self, node):
        if node.module == 'quantlab.analysis_recovery' and all(alias.name == 'require_operation' for alias in node.names):
            return None
        return node


class ViewReferences(ast.NodeTransformer):
    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == 'self' and node.attr not in PRESENTER:
            node.value = expr('self.view')
            return node
        return self.generic_visit(node)


def imports_for(nodes, imports):
    names = {node.id for parent in nodes for node in ast.walk(parent) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    return '\n'.join(used_imports(imports, names))


def flatten_imports(tree):
    imports = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
        elif isinstance(node, ast.If):
            imports.extend(child for child in (*node.body, *node.orelse) if isinstance(child, (ast.Import, ast.ImportFrom)))
    return imports


def emit(nodes, imports, extra=''):
    return imports_for(nodes, imports) + '\n' + extra + '\n\n' + '\n\n'.join(ast.unparse(ast.fix_missing_locations(node)) for node in nodes) + '\n'


def setup_sections(setup):
    original = setup.body
    chrome = next(index for index, node in enumerate(original) if isinstance(node, ast.Expr) and ast.unparse(node.value).startswith('window.setWindowTitle('))
    state = next(
        index for index, node in enumerate(original) if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == 'window.page_state._section_toggles'
    )
    host = next(index for index, node in enumerate(original) if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == 'window.page_host')
    mount = next(index for index, node in enumerate(original) if isinstance(node, ast.Expr) and ast.unparse(node.value) == 'mount_pages(window)')
    blocks = (
        ('_initialize_window_state', ('window', 'paths', 'jobs', 'settings', 'backups', 'guard'), original[:chrome]),
        ('_build_window_chrome', ('window',), original[chrome:state]),
        ('_wire_page_host', ('window',), original[state:mount]),
        ('_mount_window_pages', ('window',), original[mount:]),
    )
    functions = []
    for name, parameters, statements in blocks:
        function = ast.parse('def ' + name + '(' + ', '.join(parameters) + '):\n    pass\n').body[0]
        function.body = deepcopy(statements)
        functions.append(function)
    flattened = [node for function in functions for node in function.body]
    if [ast.dump(node, include_attributes=False) for node in flattened] != [ast.dump(node, include_attributes=False) for node in original]:
        raise AssertionError('Window setup extraction changed construction statements or order')
    create_host = ast.parse('def _create_page_host(window):\n    pass\n').body[0]
    create_host.body = [ast.Return(value=deepcopy(original[host].value))]
    for function in functions:
        for node in function.body:
            if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == 'window.page_host':
                node.value = expr('_create_page_host(window)')
    setup.body = ast.parse('''_initialize_window_state(window, paths, jobs, settings, backups, guard)
_build_window_chrome(window)
_wire_page_host(window)
_mount_window_pages(window)
''').body
    return [*functions, create_host, setup]


def poll_sections(presenter):
    """Separate event projection, terminal presentation and idle continuation."""
    poll = next(node for node in presenter.body if isinstance(node, ast.FunctionDef) and node.name == 'poll_jobs')
    attempt = poll.body[0]
    initial, loop, idle = attempt.body
    assert isinstance(attempt, ast.Try) and isinstance(loop, ast.For) and isinstance(idle, ast.If)
    outcome = ast.parse('def _project_job_outcome(self, kind, event):\n    pass\n').body[0]
    outcome.body = [deepcopy(loop.body[-1])]
    event = ast.parse('def _project_job_event(self, event, recovery_changed):\n    pass\n').body[0]
    event.body = deepcopy(loop.body[:-1]) + ast.parse('self._project_job_outcome(kind, event)\nreturn recovery_changed').body

    class EventContinuation(ast.NodeTransformer):
        def visit_Continue(self, node):
            return ast.Return(value=ast.Name(id='recovery_changed', ctx=ast.Load()))

    event = EventContinuation().visit(event)
    continuation = ast.parse('def _continue_after_jobs(self, recovery_changed):\n    pass\n').body[0]
    continuation.body = deepcopy(idle.body)
    loop.body = ast.parse('recovery_changed = self._project_job_event(event, recovery_changed)').body
    idle.body = ast.parse('self._continue_after_jobs(recovery_changed)').body
    attempt.body = [initial, loop, idle]
    presenter.body.extend((event, outcome, continuation))


def shell_outputs(source):
    tree = ast.parse(source)
    imports = flatten_imports(tree)
    window = deepcopy(next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MainWindow'))
    constructor = deepcopy(next(node for node in window.body if isinstance(node, ast.FunctionDef) and node.name == '__init__'))
    setup = deepcopy(constructor)
    setup.name = 'configure_window'
    setup.body = setup.body[1:]
    setup.args.args[0].arg = 'window'

    class WindowName(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == 'self':
                node.id = 'window'
            return node

    setup = WindowName().visit(setup)
    setup = ServiceReferences('window.services').visit(setup)
    for node in ast.walk(setup):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'PageHost':
            node.keywords.append(ast.keyword(arg='idea_records', value=expr('window.services.idea_records')))
    for node in list(imports):
        if isinstance(node, ast.ImportFrom) and node.module == 'desktop_app.shell.pages':
            moved_names = [alias for alias in node.names if alias.name in ('PageHost', 'PageState')]
            if moved_names:
                node.names = [alias for alias in node.names if alias not in moved_names]
                imports.append(ast.ImportFrom(module='desktop_app.shell.host', names=moved_names, level=0))
    support = deepcopy(next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_install_window_support'))
    constructor.args.kwonlyargs.append(ast.arg(arg='services'))
    constructor.args.kw_defaults.append(None)
    constructor.body = ast.parse(
        'super().__init__()\nself.services = services\nself.job_presenter = JobPresenter(self)\nconfigure_window(self, paths, jobs, settings, backups, guard)'
    ).body
    moved = []
    for index, method in enumerate(window.body):
        if not isinstance(method, ast.FunctionDef):
            continue
        if method.name == '__init__':
            window.body[index] = constructor
        elif method.name in PRESENTER:
            controller_method = deepcopy(method)
            if method.name == '_quiesce_and_recover':
                start = next(
                    index
                    for index, node in enumerate(controller_method.body)
                    if isinstance(node, ast.ImportFrom) and node.module == 'quantlab.analysis_recovery'
                )
                controller_method.body = controller_method.body[:start] + ast.parse('return self.services.recover_state(self.paths, self.backups)').body
            from tools.refactor.split_ui_market import ViewMethods

            controller_method = ViewMethods(set()).visit(controller_method)
            controller_method = ServiceReferences('self.view.services').visit(controller_method)
            moved.append(controller_method)
            from tools.refactor.split_ui_market import forwarding

            window.body[index] = forwarding(method, 'job_presenter')
    window = ServiceReferences('self.services').visit(window)

    class AnalysisRows(ast.NodeTransformer):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load) and node.id in ('analysis_preview_text', 'analysis_record_text'):
                return expr('_analysis_rows.' + node.id)
            return node

    window = AnalysisRows().visit(window)
    presenter = ast.parse('class JobPresenter:\n    def __init__(self, view):\n        self.view = view\n').body[0]
    presenter.body.extend(moved)
    poll_sections(presenter)
    row_names = {'ANALYSIS_NOTICE', 'ANALYSIS_WARNING', 'ANALYSIS_CHECKPOINT_STATUS', 'ANALYSIS_CHECKPOINT_NOTICE', 'ANALYSIS_METRICS', 'ANALYSIS_KINDS'}
    rows = [
        deepcopy(node)
        for node in tree.body
        if (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in row_names for target in node.targets))
        or (isinstance(node, ast.FunctionDef) and node.name in ('analysis_preview_text', 'analysis_record_text'))
    ]
    return {
        'desktop_app/shell/main_window.py': emit(
            [window],
            imports,
            'from desktop_app.shell.setup import configure_window\nfrom desktop_app.shell.job_presenter import JobPresenter\nfrom desktop_app.features.analysis import rows as _analysis_rows',
        ),
        'desktop_app/shell/setup.py': emit([support, *setup_sections(setup)], imports),
        'desktop_app/shell/job_presenter.py': emit([presenter], imports),
        'desktop_app/features/analysis/rows.py': emit(rows, imports),
    }


FACTORY = '''
def create_idea_records(root):
    from quantlab.idea_research import IdeaStore
    return IdeaStore(root)

def create_ui_services(ports):
    import desktop_app.components.formatting as formatting
    from desktop_app.shell.services import UiServices
    from quantlab.research_core.application.ui_operations.registry import UI_OPERATIONS
    from quantlab.research_core.application.ui_operations import paper, assistant, data, market, lifecycle
    return UiServices(
        idea_records=create_idea_records,
        state_root=ports.files._root,
        operations=UI_OPERATIONS,
        paper_risk_limits=lambda *args, **kwargs: paper.paper_risk_limits(*args, **kwargs),
        paper=lambda *args, **kwargs: paper._paper(ports, *args, **kwargs),
        dataset=lambda *args, **kwargs: ports.inputs._dataset(*args, **kwargs),
        candidate_record=lambda *args, **kwargs: data.candidate_record(ports, *args, **kwargs),
        plan_provider=lambda *args, **kwargs: assistant.plan_provider(ports, *args, **kwargs),
        connection_event_from_payload=lambda *args, **kwargs: assistant.connection_event_from_payload(ports, *args, **kwargs),
        dataset_market_series=lambda *args, **kwargs: market.dataset_market_series(ports, *args, **kwargs),
        latest_market_observations=lambda *args, **kwargs: market.latest_market_observations(*args, **kwargs),
        saved_analysis_entries=lambda *args, **kwargs: ports.repository.saved_analysis_entries(*args, **kwargs),
        load_result=lambda *args, **kwargs: ports.repository.load_result(*args, **kwargs),
        result_name=lambda *args, **kwargs: formatting.result_name(*args, **kwargs),
        write_json=lambda *args, **kwargs: ports.repository.write_json(*args, **kwargs),
        read_json=lambda *args, **kwargs: ports.repository.read_json(*args, **kwargs),
        load_dataset=lambda *args, **kwargs: ports.repository.load_dataset(*args, **kwargs),
        require_operation=lambda *args, **kwargs: ports.recovery.require_operation(*args, **kwargs),
        recover_state=lambda *args, **kwargs: lifecycle.recover_state(ports, *args, **kwargs),
    )

def register_operations():
    from quantlab.desktop_runtime import register_operation_executor, register_operation_executor_factory
    register_operation_executor(execute_ui_operation)
    register_operation_executor_factory('desktop_app.bootstrap:execute_ui_operation')

def create_window(paths, jobs, settings=None, backups=None, guard=None, *, window_type=None):
    if _worker_import:
        raise RuntimeError('GUI construction is unavailable in an operation worker')
    register_operations()
    from desktop_app.shell.main_window import MainWindow
    services = create_ui_services(create_operation_ports())
    factory = MainWindow if window_type is None else window_type
    return factory(paths, jobs, settings, backups, guard, services=services)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    root, output = args.source_root.resolve(), args.output_root.resolve()
    if root == output:
        parser.error('Preparation cannot overwrite product sources')
    outputs = shell_outputs(read_source(root, 'desktop_ui.py'))
    fields = sorted(set(SERVICES.values()) | {'recover_state', 'idea_records'})
    outputs['desktop_app/shell/services.py'] = (
        '"""Explicit late-call services supplied to the desktop presentation."""\nfrom dataclasses import dataclass\nfrom typing import Any, Callable\n\n@dataclass(frozen=True)\nclass UiServices:\n'
        + ''.join('    ' + name + (': frozenset[str]\n' if name == 'operations' else ': Callable[..., Any]\n') for name in fields)
    )
    host_tree = ast.parse(read_source(root, 'desktop_pages/host.py'))
    host = next(node for node in host_tree.body if isinstance(node, ast.ClassDef) and node.name == 'PageHost')
    host.body.append(ast.AnnAssign(target=ast.Name(id='idea_records', ctx=ast.Store()), annotation=ast.Name(id='Callable', ctx=ast.Load()), simple=1))
    outputs['desktop_app/shell/host.py'] = ast.unparse(ast.fix_missing_locations(host_tree)) + '\n'
    bootstrap = output / 'desktop_app/bootstrap.py'
    initial_bootstrap = bootstrap.read_text(encoding='utf-8')
    bootstrap_tree = ast.parse(initial_bootstrap)
    first_value = next(node for node in bootstrap_tree.body if not isinstance(node, (ast.Import, ast.ImportFrom, ast.Expr)))
    lines = initial_bootstrap.splitlines(keepends=True)
    lines.insert(
        first_value.lineno - 1, 'from quantlab.desktop_runtime import _is_worker_registrar_import\n\n_worker_import = _is_worker_registrar_import()\n\n'
    )
    outputs['desktop_app/bootstrap.py'] = ''.join(lines) + '\n\n' + FACTORY
    report = {}
    for name, source in outputs.items():
        ast.parse(source, feature_version=(3, 11))
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8', newline='\n')
        report[name] = len(source.splitlines())
    (output / 'shell-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()

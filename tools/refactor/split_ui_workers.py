"""Prototype the worker use cases with explicit ports and real IO adapters.

Preparation writes only a separate fixture tree. No product source is modified.
Concrete existing service modules satisfy small structural Protocols; application
functions only name those interfaces, while bootstrap supplies implementations.
"""

from __future__ import annotations


import argparse
import ast
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path

from tools.refactor.split_ui_modules import read_source


BASE = 'quantlab/research_core/application/ui_operations/'
GROUPS = {
    'binding_policy': ('provider_binding_options',),
    'research': ('campaign_generator', '_handle_ui_backtest', '_handle_ui_campaign'),
    'assistant': ('connection_event_from_payload', 'plan_provider', '_handle_ui_chatgpt_auth', '_handle_ui_chatgpt_reconcile', '_handle_ui_chatgpt_usage'),
    'analysis': (
        'analysis_plan',
        'analysis_provider_for',
        '_handle_ui_analysis_preview',
        '_handle_ui_analysis_read',
        '_handle_ui_analysis_reconcile',
        '_handle_ui_analysis_run',
    ),
    'paper': (
        'paper_risk_limits',
        '_paper',
        '_prepare_paper_operation',
        '_finish_paper_operation',
        '_handle_ui_paper_cancel',
        '_handle_ui_paper_cancel_all',
        '_handle_ui_paper_kill',
        '_handle_ui_paper_reconcile',
        '_handle_ui_paper_replay',
        '_handle_ui_paper_snapshot',
        '_handle_ui_paper_submit',
    ),
    'data': ('candidate_record', '_handle_ui_compare', '_handle_ui_demo', '_handle_ui_disable', '_handle_ui_import', '_handle_ui_refresh', '_handle_ui_select'),
    'idea': ('_handle_ui_idea_research', '_handle_ui_idea_adopt'),
    'market': ('_handle_ui_market_refresh', 'latest_market_observations', 'dataset_market_series'),
    'backup': ('_handle_ui_backup_create', '_handle_ui_backup_restore'),
    'derived': (
        '_handle_ui_capital_scenario',
        '_handle_ui_walk_forward_preview',
        '_handle_ui_walk_forward_read',
        '_handle_ui_walk_forward_reconcile',
        '_handle_ui_walk_forward_run',
    ),
}
PORT_MODULES = {
    'quantlab.reporting': 'repository',
    'quantlab.assistant.adapters.chatgpt.auth': 'auth',
    'quantlab.assistant.adapters.chatgpt.provider': 'subscription',
    'desktop_app.features.assistant.connection': 'connection',
    'quantlab.analysis_recovery': 'recovery',
    'quantlab.manual_exchange': 'manual',
    'quantlab.data': 'data_import',
    'quantlab.market_history': 'history',
    'quantlab.market_providers': 'market',
    'quantlab.downloads': 'download',
    'quantlab.desktop_errors': 'errors',
    'quantlab.desktop_feedback': 'feedback',
    'desktop_app.features.capital_scenario.worker': 'capital',
    'desktop_app.features.walk_forward.presenter': 'walk_forward',
}
SPECIAL_NAMES = {
    'ui_text': 'ports.text',
    'research_controls': 'ports.inputs.research_controls',
    '_dataset': 'ports.inputs._dataset',
    '_root': 'ports.files._root',
    '_promote_report': 'ports.files._promote_report',
    '_idea_event_caller': 'ports.idea_stream',
}
PURE_FUNCTIONS = {'provider_binding_options', 'paper_risk_limits', 'latest_market_observations'}


def expression(text):
    return ast.parse(text, mode='eval').body


def import_bindings(nodes):
    result = {}
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                result[alias.asname or alias.name] = (node.module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result[alias.asname or alias.name.split('.')[0]] = (alias.name, None)
    return result


def remove_unused_imports(function):
    names = {node.id for node in ast.walk(function) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}

    class Filter(ast.NodeTransformer):
        def visit_Import(self, node):
            node.names = [alias for alias in node.names if (alias.asname or alias.name.split('.')[0]) in names]
            return node if node.names else None

        def visit_ImportFrom(self, node):
            node.names = [alias for alias in node.names if (alias.asname or alias.name) in names]
            return node if node.names else None

    return Filter().visit(function)


class PortReferences(ast.NodeTransformer):
    def __init__(self, bindings, owned):
        self.bindings, self.owned = bindings, owned

    def visit_ImportFrom(self, node):
        if node.module == 'quantlab.__main__' and all(alias.name == 'config_from_json' for alias in node.names):
            node.module = 'quantlab.configuration'
        return None if node.module in PORT_MODULES or node.module == 'desktop_app.components.formatting' else node

    def visit_Import(self, node):
        node.names = [alias for alias in node.names if alias.name not in PORT_MODULES and alias.name != 'tempfile']
        return node if node.names else None

    def visit_Name(self, node):
        if not isinstance(node.ctx, ast.Load):
            return node
        if node.id in SPECIAL_NAMES:
            return ast.copy_location(expression(SPECIAL_NAMES[node.id]), node)
        if node.id in self.bindings:
            module, name = self.bindings[node.id]
            if module in PORT_MODULES:
                target = 'ports.' + PORT_MODULES[module] + ('.' + name if name else '')
                return ast.copy_location(expression(target), node)
            if module == 'tempfile':
                return ast.copy_location(expression('ports.files'), node)
            if module == 'quantlab.desktop_runtime' and name == 'BackupManager':
                return ast.copy_location(expression('ports.backups.BackupManager'), node)
        return node

    def visit_Call(self, node):
        original_function = node.func
        self.generic_visit(node)
        if isinstance(original_function, ast.Name) and original_function.id in self.owned:
            node.args.insert(0, ast.Name(id='ports', ctx=ast.Load()))
        if isinstance(node.func, ast.Attribute) and ast.unparse(node.func) == 'ports.walk_forward.execute_walk_forward':
            node.keywords.append(ast.keyword(arg='inputs', value=expression('ports.inputs')))
        if isinstance(node.func, ast.Attribute) and node.func.attr in ('mkdir', 'exists', 'unlink', 'is_dir', 'is_symlink'):
            target = node.func.value
            node.func = expression('ports.files.' + node.func.attr)
            node.args.insert(0, target)
        return node


def patch_io(function):
    if function.name == 'candidate_record':
        start = next(index for index, node in enumerate(function.body) if isinstance(node, ast.If) and "state.get('selection_hash')" in ast.unparse(node.test))
        imports = [node for node in function.body[:start] if isinstance(node, ast.ImportFrom) and node.module == 'quantlab.research']
        function.body = imports + ast.parse('state = ports.inputs.candidate_state(root, reference)').body + function.body[start:]
    elif function.name == 'plan_provider':
        start = next(
            index
            for index, node in enumerate(function.body)
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'source_root' for target in node.targets)
        )
        end = next(
            index
            for index, node in enumerate(function.body)
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'sources' for target in node.targets)
        )
        function.body[start : end + 1] = ast.parse('sources = ports.inputs.implementation_sources()').body
    elif function.name == '_handle_ui_market_refresh':

        class LocalSource(ast.NodeTransformer):
            def visit_If(self, node):
                self.generic_visit(node)
                if isinstance(node.test, ast.Name) and node.test.id == 'local' and node.body and isinstance(node.body[0], ast.Assign):
                    if ast.unparse(node.body[0]).startswith('path = Path(local)'):
                        call = ast.parse(
                            "raw = ports.files.official_source(Path(local), MAX_BYTES, ui_text('ui.execute_ui_operation.official_file_too_large'))"
                        ).body
                        node.body = call + [node.body[-1]]
                return node

        function = LocalSource().visit(function)
    return function


def transform_function(function, global_imports, owned):
    function = patch_io(deepcopy(function))
    bindings = {**global_imports, **import_bindings(ast.walk(function))}
    if function.name not in PURE_FUNCTIONS:
        function.args.args.insert(0, ast.arg(arg='ports', annotation=ast.Name(id='UiOperationPorts', ctx=ast.Load())))
    function = PortReferences(bindings, set(owned) - PURE_FUNCTIONS).visit(function)
    if function.name in PURE_FUNCTIONS and any(isinstance(node, ast.Name) and node.id == 'ports' for node in ast.walk(function)):
        raise ValueError('A pure helper unexpectedly acquired a port dependency')
    if function.name == '_handle_ui_analysis_preview':
        function.body = [
            node
            for node in function.body
            if not isinstance(node, ast.Assign) or not any(isinstance(target, ast.Name) and target.id == 'output' for target in node.targets)
        ]
    return remove_unused_imports(ast.fix_missing_locations(function))


def generated_imports(nodes, global_nodes, owners, own_path):
    references = {node.id for parent in nodes for node in ast.walk(parent) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    statements = ['from quantlab.research_core.ports.ui_operations import UiOperationPorts'] if 'UiOperationPorts' in references else []
    for node in global_nodes:
        aliases = [alias for alias in node.names if (alias.asname or (alias.name.split('.')[0] if isinstance(node, ast.Import) else alias.name)) in references]
        if aliases:
            statement = ast.Import(names=aliases) if isinstance(node, ast.Import) else ast.ImportFrom(module=node.module, names=aliases, level=node.level)
            statements.append(ast.unparse(statement))
    groups = defaultdict(list)
    for name in references & owners.keys():
        if owners[name] != own_path:
            groups[owners[name]].append(name)
    statements += ['from ' + path.removesuffix('.py').replace('/', '.') + ' import ' + ', '.join(sorted(names)) for path, names in sorted(groups.items())]
    return '\n'.join(statements)


def repository_source(root, ui_source):
    presentation = ast.parse(read_source(root, 'desktop_presentation.py'))
    originals = {node.name: node for node in ast.parse(ui_source).body if isinstance(node, ast.FunctionDef)}
    source_method = ast.parse('def implementation_sources(self):\n    source_root = self.source_root\n').body[0]
    source_method.body.extend(
        deepcopy(node)
        for node in originals['plan_provider'].body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in ('source_files', 'sources') for target in node.targets)
    )
    source_method.body.append(ast.Return(value=ast.Name(id='sources', ctx=ast.Load())))
    prefix = deepcopy(originals['candidate_record'])
    stop = next(index for index, node in enumerate(prefix.body) if isinstance(node, ast.If) and "state.get('selection_hash')" in ast.unparse(node.test))
    prefix.body = prefix.body[:stop] + [ast.Return(value=ast.Name(id='state', ctx=ast.Load()))]
    prefix.body = [node for node in prefix.body if not isinstance(node, ast.ImportFrom) or node.module != 'quantlab.research']
    prefix.name = 'candidate_state'
    functions = [deepcopy(node) for node in presentation.body if isinstance(node, ast.FunctionDef) and node.name in ('research_controls', '_dataset')]
    functions.append(prefix)

    class Messages(ast.NodeTransformer):
        def visit_Name(self, node):
            return expression('self.text') if isinstance(node.ctx, ast.Load) and node.id == 'ui_text' else node

    methods = [ast.unparse(ast.fix_missing_locations(source_method))]
    for function in functions:
        function.args.args.insert(0, ast.arg(arg='self'))
        function = Messages().visit(function)
        methods.append(ast.unparse(ast.fix_missing_locations(function)))
    imports = "from pathlib import Path\nimport json\nimport hashlib\nfrom quantlab.core import Dataset, ValidationError, content_hash, canonical_json\nfrom quantlab.reporting import read_json, load_dataset\nfrom quantlab.windows_paths import canonical_path as _canonical_path, native_path as _native_path, sqlite_uri as _sqlite_uri\n"
    body = '\n\n'.join('    ' + method.replace('\n', '\n    ') for method in methods)
    return (
        '"""Filesystem boundaries used by the desktop research use cases."""\n\n'
        + imports
        + '\n\nclass WorkerRepository:\n    def __init__(self, text, source_root):\n        self.text = text\n        self.source_root = source_root\n\n'
        + body
        + '\n'
    )


FILES_SOURCE = '''"""Owned filesystem metadata, bounded reads and temporary publication."""
from pathlib import Path
from tempfile import TemporaryDirectory
from quantlab.core import ValidationError

__all__ = ('TemporaryDirectory', '_root', 'mkdir', 'exists', 'unlink', 'is_dir', 'is_symlink', '_promote_report', 'official_source')

def _root(paths):
    root = Path(paths.state)
    root.mkdir(parents=True, exist_ok=True)
    return root

def mkdir(path, *args, **kwargs):
    return path.mkdir(*args, **kwargs)

def exists(path):
    return path.exists()

def unlink(path):
    return path.unlink()

def is_dir(path):
    return path.is_dir()

def is_symlink(path):
    return path.is_symlink()

def _promote_report(folder, destination):
    from quantlab.runtime_support import replace_file
    return replace_file(folder, destination)

def official_source(path, limit, message):
    if path.stat().st_size > limit:
        raise ValidationError(message)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValidationError(message)
    return raw
'''


def ports_source(outputs):
    used = defaultdict(set)
    for source in outputs.values():
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == 'ports'
            ):
                used[node.value.attr].add(node.attr)
    text = '"""Only the capabilities exercised by existing desktop worker use cases."""\nfrom typing import Any, Callable, Protocol\n\n'
    for group, names in sorted(used.items()):
        text += '\nclass ' + group.title().replace('_', '') + 'Port(Protocol):\n'
        text += ''.join('    ' + name + ': Any\n' for name in sorted(names))
    text += '\nclass UiOperationPorts(Protocol):\n    text: Callable[[str], str]\n    idea_stream: Callable[..., Any]\n'
    text += ''.join('    ' + group + ': ' + group.title().replace('_', '') + 'Port\n' for group in sorted(used))
    return text, used


def lifecycle_source(tree, global_nodes, bindings, owners):
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MainWindow')
    original = next(node for node in window.body if isinstance(node, ast.FunctionDef) and node.name == '_quiesce_and_recover')
    start = next(index for index, node in enumerate(original.body) if isinstance(node, ast.ImportFrom) and node.module == 'quantlab.analysis_recovery')
    function = ast.parse('def recover_state(paths, backups):\n    pass\n').body[0]
    function.body = deepcopy(original.body[start:])

    class Arguments(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'self' and node.attr in ('paths', 'backups'):
                return ast.Name(id=node.attr, ctx=node.ctx)
            return self.generic_visit(node)

    function = Arguments().visit(function)
    function = transform_function(function, bindings, owners)
    path = BASE + 'lifecycle.py'
    return generated_imports([function], global_nodes, owners, path) + '\n\n' + ast.unparse(ast.fix_missing_locations(function)) + '\n'


def bootstrap_source(used):
    text = '"""Concrete bindings and dispatcher selection for desktop worker operations."""\nfrom pathlib import Path\nfrom desktop_app.strings.catalog import ui_text\nfrom quantlab.research_core.adapters.ui_repository import WorkerRepository\nfrom quantlab.research_core.adapters import ui_files\nfrom quantlab.research_core.adapters.ui_idea_stream import _idea_event_caller\nfrom quantlab.research_core.application.ui_operations.registry import _UI_OPERATION_HANDLERS, prepare_operation\n\n'
    text += 'class DesktopOperationPorts:\n    def __init__(self, text, source_root):\n        self.text = text\n        self.inputs = WorkerRepository(text, source_root)\n        self.files = ui_files\n        self.idea_stream = _idea_event_caller\n'
    modules = {value: key for key, value in PORT_MODULES.items()}
    modules['backups'] = 'quantlab.desktop_runtime'
    modules['walk_forward'] = 'desktop_app.features.walk_forward.presenter'
    for name in sorted(set(used) - {'inputs', 'files'}):
        text += f'\n    @property\n    def {name}(self):\n        import {modules[name]} as implementation\n        return implementation\n'
    text += '\n\ndef create_operation_ports():\n    return DesktopOperationPorts(ui_text, Path(__file__).resolve().parents[1])\n\n'
    text += 'def execute_ui_operation(operation, payload, paths, *, emit=None, descendants_stopped=False):\n    ports = create_operation_ports()\n    payload, root = prepare_operation(ports, operation, payload, paths)\n    return _UI_OPERATION_HANDLERS[operation](ports, payload, paths, root, emit=emit, descendants_stopped=descendants_stopped)\n'
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    root, output = args.source_root.resolve(), args.output_root.resolve()
    if root == output:
        parser.error('Prototype output must be a separate fixture')
    source = read_source(root, 'desktop_ui.py')
    tree = ast.parse(source)
    globals_ = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    bindings = import_bindings(globals_)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    owners = {name: BASE + group + '.py' for group, names in GROUPS.items() for name in names}
    transformed = {name: transform_function(functions[name], bindings, owners) for name in owners}
    outputs = {}
    for group, names in GROUPS.items():
        path = BASE + group + '.py'
        nodes = [transformed[name] for name in names]
        outputs[path] = (
            '"""Existing '
            + group
            + ' worker use cases; concrete dependencies arrive through ports."""\n\n'
            + generated_imports(nodes, globals_, owners, path)
            + '\n\n'
            + '\n\n'.join(ast.unparse(node) for node in nodes)
            + '\n'
        )
    outputs[BASE + 'lifecycle.py'] = lifecycle_source(tree, globals_, bindings, owners)
    ui_operations = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'UI_OPERATIONS' for target in node.targets)
    )
    handlers = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == '_UI_OPERATION_HANDLERS' for target in node.targets)
    )
    admission = transform_function(functions['execute_ui_operation'], bindings, owners)
    admission.name = 'prepare_operation'
    admission.body[-1] = ast.Return(value=ast.Tuple(elts=[ast.Name(id='payload', ctx=ast.Load()), ast.Name(id='root', ctx=ast.Load())], ctx=ast.Load()))
    registry_imports = generated_imports([handlers, admission], globals_, owners, BASE + 'registry.py')
    outputs[BASE + 'registry.py'] = (
        '"""Fixed operation names and admission rules."""\n'
        + registry_imports
        + '\n\n'
        + ast.unparse(ui_operations)
        + '\n\n'
        + ast.unparse(handlers)
        + '\n\n'
        + ast.unparse(ast.fix_missing_locations(admission))
        + '\n'
    )
    ports, used = ports_source(outputs)
    outputs['quantlab/research_core/ports/ui_operations.py'] = ports
    outputs['quantlab/research_core/adapters/ui_repository.py'] = repository_source(root, source)
    outputs['quantlab/research_core/adapters/ui_files.py'] = FILES_SOURCE
    stream = ast.unparse(functions['_idea_event_caller'])
    outputs['quantlab/research_core/adapters/ui_idea_stream.py'] = '"""Bounded subscription event-stream adapter."""\n\n' + stream + '\n'
    outputs['desktop_app/bootstrap.py'] = bootstrap_source(used)
    for name, text in outputs.items():
        ast.parse(text, feature_version=(3, 11))
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    report = {name: len(text.splitlines()) for name, text in outputs.items()}
    print(json.dumps({'worker_report': report}))
    print(json.dumps(report))


if __name__ == '__main__':
    main()

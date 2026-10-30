"""Apply slice 2 from an explicit pre-split source snapshot.

Extends the slice 1 generators and owner map. No GitNexus or git mutations.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.refactor import split_ui_workers as workers, split_ui_shell as shell
from tools.refactor import split_ui_market as market, split_ui_idea as idea, split_ui_inputs as inputs
from tools.refactor.split_ui_modules import dotted, names_defined


def write_outputs(root, outputs):
    for name, source in outputs.items():
        ast.parse(source, feature_version=(3, 11))
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8', newline='\n')


def worker_outputs(base, root):
    # Reuse the reviewed worker generator, with the current B paths.
    before = sys.argv
    sys.argv = ['split_ui_workers', '--source-root', str(base), '--output-root', str(root)]
    try:
        workers.main()
    finally:
        sys.argv = before
    source = (base / 'desktop_app/shell/main_window.py').read_text(encoding='utf-8')
    return source


def shell_outputs(source, root):
    outputs = shell.shell_outputs(source)
    window_tree = ast.parse(outputs['desktop_app/shell/main_window.py'])
    window = next(node for node in window_tree.body if isinstance(node, ast.ClassDef))
    navigation = []
    for method in window.body:
        if isinstance(method, ast.FunctionDef) and method.name in ('_mount_market', '_mount_page', '_navigate_selected_page'):
            navigation.append(ast.parse(ast.unparse(method)).body[0])
            args = ', '.join(argument.arg for argument in method.args.args)
            method.body = ast.parse('return _navigation.' + method.name + '(' + args + ')').body
    imports = [node for node in window_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    outputs['desktop_app/shell/navigation.py'] = shell.emit(navigation, imports)
    window_tree.body.insert(0, ast.parse('from desktop_app.shell import navigation as _navigation').body[0])
    outputs['desktop_app/shell/main_window.py'] = ast.unparse(ast.fix_missing_locations(window_tree)) + '\n'
    # The native view has no composition dependency. The historical registrar
    # stays a real composition entry, so spawn's public identity never changes.
    outputs['desktop_app/shell/window.py'] = outputs.pop('desktop_app/shell/main_window.py')
    outputs['desktop_app/features/analysis/presenter.py'] = outputs.pop('desktop_app/features/analysis/rows.py')
    outputs['desktop_app/shell/window.py'] = outputs['desktop_app/shell/window.py'].replace('analysis import rows as', 'analysis import presenter as')
    factory = ast.parse(shell.FACTORY)
    functions = [node for node in factory.body if isinstance(node, ast.FunctionDef) and node.name in ('create_idea_records', 'create_ui_services')]
    bootstrap_path = root / 'desktop_app/bootstrap.py'
    bootstrap = ast.parse(bootstrap_path.read_text(encoding='utf-8'))
    dispatcher = next(node for node in bootstrap.body if isinstance(node, ast.FunctionDef) and node.name == 'execute_ui_operation')
    bootstrap.body.remove(dispatcher)
    bootstrap.body = [
        node for node in bootstrap.body if not isinstance(node, ast.ImportFrom) or node.module != 'quantlab.research_core.application.ui_operations.registry'
    ]
    bootstrap.body.extend(functions)
    service_factory = next(node for node in bootstrap.body if isinstance(node, ast.FunctionDef) and node.name == 'create_ui_services')
    service_factory.body[-1].value.keywords.append(ast.keyword(arg='sample_market_series', value=ast.Name(id='sample_market_series', ctx=ast.Load())))
    outputs['desktop_app/bootstrap.py'] = ast.unparse(ast.fix_missing_locations(bootstrap)) + '\n'
    entry = '''"""Native shell composition and stable, Qt-free spawned-worker registrar."""
from quantlab.desktop_runtime import (
    _is_worker_registrar_import,
    register_operation_executor,
    register_operation_executor_factory,
)
from desktop_app.bootstrap import create_operation_ports, create_ui_services
from quantlab.research_core.application.ui_operations.registry import UI_OPERATIONS, _UI_OPERATION_HANDLERS, prepare_operation

_worker_import = _is_worker_registrar_import()
'''
    entry += '\n\n' + ast.unparse(dispatcher) + '\n\n'
    entry += '''OPERATION_REGISTRAR = 'desktop_app.shell.main_window:execute_ui_operation'
register_operation_executor(execute_ui_operation)
register_operation_executor_factory(OPERATION_REGISTRAR)

if not _worker_import:
    from PySide6.QtWidgets import QMainWindow
    from desktop_app.shell.window import MainWindow


def create_window(paths, jobs, settings=None, backups=None, guard=None):
    if _worker_import:
        raise RuntimeError('GUI construction is unavailable in an operation worker')
    services = create_ui_services(create_operation_ports())
    return MainWindow(paths, jobs, settings, backups, guard, services=services)
'''
    outputs['desktop_app/shell/main_window.py'] = entry
    fields = sorted(set(shell.SERVICES.values()) | {'recover_state', 'idea_records', 'sample_market_series'})
    outputs['desktop_app/shell/services.py'] = (
        '"""Late-call services supplied by composition to desktop presentation."""\nfrom dataclasses import dataclass\nfrom typing import Any, Callable\n\n@dataclass(frozen=True)\nclass UiServices:\n'
        + ''.join('    ' + name + (': frozenset[str]\n' if name == 'operations' else ': Callable[..., Any]\n') for name in fields)
    )
    # Composition supplies a factory, never an eager store or shared instance.
    return outputs


def capture_base(root, reference):
    """Recreate generator inputs from the fixed pre-slice commit, read-only git."""
    import subprocess

    base = root / '.tmp-layered' / ('slice2-source-' + reference)
    names = (
        'desktop_app/shell/main_window.py',
        'desktop_app/shell/host.py',
        'desktop_app/features/market/dashboard.py',
        'desktop_app/features/strategy/idea_research.py',
        'desktop_app/components/formatting.py',
        'desktop_app/features/walk_forward/presenter.py',
        'quantlab/market_history.py',
        'tools/layer_relocations.json',
    )
    for name in names:
        raw = subprocess.check_output(['git', 'show', reference + ':' + name], cwd=root)
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--source-ref', default='19f0962')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    base = args.source_root.resolve() if args.source_root else capture_base(root, args.source_ref)
    source = worker_outputs(base, root)
    outputs = shell_outputs(source, root)
    outputs.update(market.market_outputs((base / 'desktop_app/features/market/dashboard.py').read_text(encoding='utf-8')))
    outputs.update(market.session_outputs((base / 'quantlab/market_history.py').read_text(encoding='utf-8')))
    outputs.update(idea.idea_outputs((base / 'desktop_app/features/strategy/idea_research.py').read_text(encoding='utf-8')))
    outputs['desktop_app/components/formatting.py'] = inputs.formatting_output((base / 'desktop_app/components/formatting.py').read_text(encoding='utf-8'))
    outputs['desktop_app/features/walk_forward/presenter.py'] = inputs.walk_forward_output(
        (base / 'desktop_app/features/walk_forward/presenter.py').read_text(encoding='utf-8')
    )
    host = ast.parse((base / 'desktop_app/shell/host.py').read_text(encoding='utf-8'))
    cls = next(node for node in host.body if isinstance(node, ast.ClassDef) and node.name == 'PageHost')
    cls.body.append(ast.parse('sample_market_series: Callable').body[0])
    cls.body.append(ast.AnnAssign(target=ast.Name(id='idea_records', ctx=ast.Store()), annotation=ast.Name(id='Callable', ctx=ast.Load()), simple=1))
    outputs['desktop_app/shell/setup.py'] = outputs['desktop_app/shell/setup.py'].replace(
        'idea_records=window.services.idea_records', 'idea_records=window.services.idea_records, sample_market_series=window.services.sample_market_series'
    )
    outputs['desktop_app/shell/host.py'] = ast.unparse(ast.fix_missing_locations(host)) + '\n'
    sample = next(
        node
        for node in ast.parse((base / 'desktop_app/features/market/dashboard.py').read_text(encoding='utf-8')).body
        if isinstance(node, ast.FunctionDef) and node.name == 'sample_market_series'
    )
    sample.body.insert(0, ast.parse('from quantlab.market import MarketSeries').body[0])
    outputs['desktop_app/bootstrap.py'] += '\n\n' + ast.unparse(sample) + '\n'
    # Naming follows inventory section 10; scripts own all physical references.
    moves = {
        'desktop_app/features/market/presenter.py': 'desktop_app/features/market/watchlist_presenter.py',
        'desktop_app/features/market/detail_layout.py': 'desktop_app/features/market/indicator_controls.py',
    }
    outputs = {moves.get(name, name): text for name, text in outputs.items()}
    replacements = {dotted(old): dotted(new) for old, new in moves.items()}
    for name in outputs:
        for old, new in replacements.items():
            outputs[name] = outputs[name].replace(old, new)
    app_moves = {workers.BASE + group + '.py': 'quantlab/research_core/application/' + group + '_operations.py' for group in ('analysis', 'research', 'paper')}
    for old, new in app_moves.items():
        outputs[new] = (root / old).read_text(encoding='utf-8')
        (root / old).unlink()
    for name in outputs:
        for old, new in app_moves.items():
            outputs[name] = outputs[name].replace(dotted(old), dotted(new))
        outputs[name] = outputs[name].replace(
            'from quantlab.research_core.application.ui_operations import paper, assistant, data, market, lifecycle',
            'from quantlab.research_core.application import paper_operations as paper\n    from quantlab.research_core.application.ui_operations import assistant, data, market, lifecycle',
        )
    registry_path = root / (workers.BASE + 'registry.py')
    registry = registry_path.read_text(encoding='utf-8')
    for old, new in app_moves.items():
        registry = registry.replace(dotted(old), dotted(new))
    outputs[workers.BASE + 'registry.py'] = registry
    write_outputs(root, outputs)
    # Exact composition files; the widget remains presentation in window.py.
    mapping_path = root / 'tools/layer_map.json'
    mapping = json.loads(mapping_path.read_text(encoding='utf-8'))
    mapping['prefixes'].update(
        {'quantlab/research_core/application/': 'application', 'quantlab/research_core/ports/': 'application', 'quantlab/research_core/domain/': 'domain'}
    )
    mapping['overrides'].update({'desktop_app/bootstrap.py': 'composition', 'desktop_app/shell/main_window.py': 'composition'})
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    allowlist_path = root / 'tools/layer_allowlist.json'
    debts = json.loads(allowlist_path.read_text(encoding='utf-8'))
    debts = [
        row
        for row in debts
        if row['path'] not in ('desktop_ui.py', 'desktop_presentation.py')
        and not (row['path'] == 'desktop_market.py' and row['target'] in ('quantlab.market_history', 'quantlab.reporting'))
    ]
    allowlist_path.write_text(json.dumps(debts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Extend the single owner table used by the slice 1 reference pipeline.
    owners_path = root / 'tools/refactor/split_ui_owners.json'
    owners = json.loads(owners_path.read_text(encoding='utf-8'))
    previous = {
        name: dotted(name)
        for name in (
            'desktop_app/shell/main_window.py',
            'desktop_app/features/market/dashboard.py',
            'desktop_app/features/strategy/idea_research.py',
            'desktop_app/components/formatting.py',
        )
    }
    originals = {name: {symbol for node in ast.parse((base / name).read_text(encoding='utf-8')).body for symbol in names_defined(node)} for name in previous}
    for name, text in outputs.items():
        for node in ast.parse(text).body:
            for symbol in names_defined(node):
                for old, module in previous.items():
                    if symbol in originals[old]:
                        owners[module + '.' + symbol] = dotted(name) + '.' + symbol
    for group, names in workers.GROUPS.items():
        for name in names:
            old_path = workers.BASE + group + '.py'
            new_owner = dotted(app_moves.get(old_path, old_path)) + '.' + name
            owners['desktop_app.shell.main_window.' + name] = new_owner
            if old_path in app_moves:
                owners[dotted(old_path) + '.' + name] = new_owner
    owners['desktop_app.shell.main_window._root'] = 'quantlab.research_core.adapters.ui_files._root'
    owners['desktop_app.shell.main_window._idea_event_caller'] = 'quantlab.research_core.adapters.ui_idea_stream._idea_event_caller'
    owners['desktop_app.features.market.dashboard.indicators'] = 'desktop_app.features.market.indicator_presenter.indicators'
    for symbol in (
        'read_json',
        'write_json',
        'load_dataset',
        'load_result',
        'demo_config',
        'save_dataset',
        'synthetic_dataset',
        'saved_analysis_entries',
        'load_selection',
    ):
        owners['desktop_app.shell.main_window.' + symbol] = 'quantlab.reporting.' + symbol
    for symbol, module in {
        'ui_text': 'desktop_app.strings.catalog',
        'result_name': 'desktop_app.components.formatting',
        'QMessageBox': 'PySide6.QtWidgets',
        'QFileDialog': 'PySide6.QtWidgets',
        'QTimer': 'PySide6.QtCore',
    }.items():
        owners['desktop_app.shell.main_window.' + symbol] = module + '.' + symbol
    for symbol, module in {'QDesktopServices': 'PySide6.QtGui', 'QUrl': 'PySide6.QtCore'}.items():
        owners['desktop_app.features.strategy.idea_research.' + symbol] = module + '.' + symbol
    owners_path.write_text(json.dumps(owners, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'outputs': len(outputs)}))


if __name__ == '__main__':
    main()

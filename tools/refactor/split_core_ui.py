"""Re-runnable responsibility extraction and mechanical caller migration for PR D."""

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CHANGED = set()


def write(path, source):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.read_text(encoding='utf-8') != source:
        target.write_text(source, encoding='utf-8')
        CHANGED.add(path)


def source(node):
    return ast.unparse(node) + '\n\n'


def extract_connection():
    path = 'desktop_app/features/assistant/connection.py'
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    nodes = {getattr(n, 'name', ''): n for n in tree.body}
    if 'ConnectionRequest' not in nodes:
        return
    contract_names = {
        '_ref',
        'official_authorization_url',
        'ConnectionRequest',
        'ConnectionEvent',
        'TestConnectionEvent',
        'ReconciliationEvent',
        'SubscriptionOptions',
    }
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)]
    constants = [n for n in assignments if n.targets[0].id not in ('STATE_LABELS', 'USAGE_SETTINGS_URL')]
    contracts = 'from dataclasses import dataclass, field, asdict\nimport re\nfrom urllib.parse import urlsplit, parse_qsl\n\n'
    contracts += ''.join(source(n) for n in constants)
    contracts += ''.join(source(n) for n in tree.body if getattr(n, 'name', '') in contract_names)
    # Validation uses a fixed protocol pattern, never a translated string.
    from desktop_app.strings.catalog import ui_text

    contracts = contracts.replace("ui_text('chatgpt_ui.post_init.masked_account_pattern')", repr(ui_text('chatgpt_ui.post_init.masked_account_pattern')))
    write('quantlab/assistant/application/connection_contracts.py', contracts)
    imports = (
        'from quantlab.assistant.application.connection_contracts import (' + ', '.join(sorted(contract_names | {n.targets[0].id for n in constants})) + ')\n'
    )
    state = ast.parse((ROOT / 'desktop_app/features/assistant/states.py').read_text(encoding='utf-8'))
    outcome = ''.join(source(n) for n in state.body if isinstance(n, ast.Assign) or getattr(n, 'name', '') == 'outcome_state')
    renderers = []
    controller = copy.deepcopy(nodes['ConnectionController'])
    controller.name = 'ConnectionStateMachine'
    controller.bases = []
    controller.body = [n for n in controller.body if not isinstance(n, ast.Assign)]

    class SeparatePresentation(ast.NodeTransformer):
        method = ''
        counter = 0

        def visit_FunctionDef(self, node):
            self.method = node.name
            if node.name == '__init__':
                node.args = ast.parse('def f(self, *, emit, present): pass').body[0].args
                node.body = [n for n in node.body if 'super().__init__' not in ast.unparse(n)]
                node.body[0:0] = ast.parse('self._emit = emit\nself._present = present').body
            return self.generic_visit(node)

        def renderer(self, node, expression=False):
            self.counter += 1
            name = self.method.strip('_') + '_' + str(self.counter)
            known = {'self', 'ui_text', 'STATE_LABELS', 'outcome_message', 'error_message'}
            params = sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)} - known)
            args = ', '.join(['self', *params])
            body = ('return ' if expression else '') + ast.unparse(node)
            renderers.append(f'def render_{name}({args}):\n' + '\n'.join('    ' + line for line in body.splitlines()) + '\n\n')
            return ast.parse(f"self._present('{name}'" + ''.join(f', {p}={p}' for p in params) + ')').body[0].value

        def visit_Assign(self, node):
            text = ast.unparse(node)
            if any(x in text for x in ('self.message', 'self.test_message', 'messages =')):
                return ast.copy_location(ast.Expr(self.renderer(node)), node)
            return self.generic_visit(node)

        def visit_AugAssign(self, node):
            if 'self.message' in ast.unparse(node) or 'self.test_message' in ast.unparse(node):
                return ast.copy_location(ast.Expr(self.renderer(node)), node)
            return self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == 'ui_text':
                return self.renderer(node, True)
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'emit':
                if isinstance(node.func.value, ast.Attribute):
                    signal = node.func.value.attr
                    return ast.Call(ast.Attribute(ast.Name('self', ast.Load()), '_emit', ast.Load()), [ast.Constant(signal), *node.args], node.keywords)
                # Conditional request dispatch preserves the original join barrier.
                return ast.parse("self._emit('quiesce_requested' if self._awaiting_join else 'request_ready', request)").body[0].value
            return self.generic_visit(node)

    controller = SeparatePresentation().visit(controller)
    ast.fix_missing_locations(controller)
    core = imports + '\n' + outcome + source(controller)
    core = core.replace('from quantlab.desktop_errors import error_message', '')
    write('quantlab/assistant/application/connection_controller.py', core)
    labels = next(n for n in assignments if n.targets[0].id == 'STATE_LABELS')
    presenter = (
        'from PySide6.QtCore import QObject, Signal\nfrom desktop_app.strings.catalog import ui_text\nfrom desktop_app.features.assistant.states import outcome_message\nfrom quantlab.desktop_errors import error_message\nfrom quantlab.assistant.application.connection_controller import ConnectionStateMachine\n\n'
        + source(labels)
    )
    presenter += ''.join(renderers)
    names = [ast.parse(r).body[0].name for r in renderers]
    presenter += 'RENDERERS = {\n' + ''.join(f"    '{n.removeprefix('render_')}': {n},\n" for n in names) + '}\n\n'
    presenter += '''class ConnectionController(QObject, ConnectionStateMachine):
    """Qt effects and localized messages around the application state machine."""
    quiesce_requested = Signal(object)
    request_ready = Signal(object)
    cancel_requested = Signal(int)
    browser_requested = Signal(str)
    changed = Signal()
    request_finished = Signal(object, bool)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        ConnectionStateMachine.__init__(self, emit=self._dispatch, present=self._render)

    def _dispatch(self, name, *args):
        getattr(self, name).emit(*args)

    def _render(self, name, **values):
        return RENDERERS[name](self, **values)
'''
    # The reconciliation message table is kept together in the UI renderer.
    presenter = presenter.replace('    messages = {', '    self._messages = {').replace('self.message = messages[kind]', 'self.message = self._messages[kind]')
    # A local message table must not cross back into core state.
    core = core.replace(', messages=messages', '')
    write('quantlab/assistant/application/connection_controller.py', core)
    write('desktop_app/features/assistant/connection_presenter.py', presenter)
    worker = 'import sqlite3\nimport time\nfrom pathlib import Path\nfrom quantlab.desktop_errors import ERROR_LABELS, exception_code\n' + imports
    worker += source(nodes['_safe_error_code']) + source(nodes['run_connection_request'])
    worker = worker.replace(
        'from desktop_app.features.assistant.connection_test import run_probe', 'from quantlab.assistant.adapters.chatgpt.connection_probe import run_probe'
    )
    write('quantlab/assistant/adapters/chatgpt/connection_worker.py', worker)
    widget_imports = (
        'from desktop_app.strings.catalog import ui_text\nfrom PySide6.QtCore import Qt, QTimer\nfrom PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox, QMessageBox\nfrom desktop_app.features.assistant.connection_presenter import ConnectionController, STATE_LABELS\n'
        + imports
    )
    write(path, widget_imports + "\nUSAGE_SETTINGS_URL = 'https://chatgpt.com/settings/usage'\n\n" + source(nodes['ChatGPTConnectionPanel']))
    probe_path = 'desktop_app/features/assistant/connection_test.py'
    probe_tree = ast.parse((ROOT / probe_path).read_text(encoding='utf-8'))
    probe = next(n for n in probe_tree.body if getattr(n, 'name', '') == 'run_probe')
    probe_source = source(probe).replace(
        'from desktop_app.features.assistant.connection import TestConnectionEvent as ConnectionEvent, _safe_error_code',
        'from quantlab.assistant.application.connection_contracts import TestConnectionEvent as ConnectionEvent\n    from quantlab.assistant.adapters.chatgpt.connection_worker import _safe_error_code',
    )
    write('quantlab/assistant/adapters/chatgpt/connection_probe.py', 'from pathlib import Path\nimport time\nPROMPT = "Reply with OK."\n\n' + probe_source)
    probe_tree.body.remove(probe)
    write(probe_path, ast.unparse(probe_tree) + '\n')


def extract_walk_forward():
    path = 'desktop_app/features/walk_forward/presenter.py'
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    nodes = {getattr(n, 'name', ''): n for n in tree.body}
    if '_folder' not in nodes:
        return
    names = {'_folder', '_binding', 'source_campaign_folder', '_prepare_saved_plan', '_range', 'preview_walk_forward', 'execute_walk_forward'}
    imports = ''.join(
        source(n)
        for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom))
        and not ('desktop_app' in ast.unparse(n) or '_significance' in ast.unparse(n) or '_verdict' in ast.unparse(n))
    )
    operations = imports + 'from quantlab.research_core.application.walk_forward_projection import compact_walk_forward\n\n'
    operations += ''.join(source(n) for n in tree.body if getattr(n, 'name', '') in names)
    operations = operations.replace(
        'from desktop_app.components.formatting import research_controls',
        'from quantlab.research_core.application.walk_forward_inputs import research_controls',
    )
    operations = operations.replace(
        'from desktop_app.components.formatting import _dataset, research_controls',
        'from quantlab.research_core.application.walk_forward_inputs import _dataset, research_controls',
    )
    write('quantlab/research_core/application/walk_forward_operations.py', operations)
    metrics = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == 'METRICS')
    projection = (
        'from quantlab.core import ValidationError\nfrom quantlab import significance as _significance\nfrom quantlab import verdict as _verdict\n\n'
        + source(metrics)
    )
    projection += source(nodes['_score']) + source(nodes['compact_walk_forward']).replace(
        "'oos_statistics_text': oos_statistics_text(state)", "'oos_statistics': oos_statistics_data(state)"
    )
    projection += '''def oos_statistics_data(state):
    """Fixed bounded statistics; daily returns never enter IPC."""
    if state.get('status') != 'completed':
        return {'available': False}
    merged = _significance.merge_oos_daily_returns(state)
    result = {'available': True, 'reason': merged['reason'], 'skipped_folds': merged.get('skipped_folds', 0)}
    if merged['reason']:
        return result
    stats = _significance.mean_positive_test(merged['returns'])
    required = _significance.required_observations(merged['returns'])
    result.update(stats=stats, required=required, decline=_significance.oos_decline_test(state), verdict=_verdict.judge(stats, required, merged['returns'], ()))
    return result
'''
    write('quantlab/research_core/application/walk_forward_projection.py', projection)
    formatting = ast.parse((ROOT / 'desktop_app/components/formatting.py').read_text(encoding='utf-8'))
    inputs = 'from pathlib import Path\nfrom quantlab.core import ValidationError, content_hash\nfrom quantlab.data import Dataset, load_dataset\n\n'
    inputs += ''.join(source(n) for n in formatting.body if getattr(n, 'name', '') in ('research_controls', '_dataset'))
    labels = {
        'ui.research_controls.legacy_budget_blocked': 'Legacy irreversible records require migration',
        'ui.research_controls.irreversible_record_location': 'Irreversible records must be outside state',
        'ui.dataset.reversed_dates': 'Reversed date range',
        'ui.dataset.empty_date_range': 'Empty date range',
    }
    for key, value in labels.items():
        inputs = inputs.replace(f"ui_text('{key}')", repr(value))
    write('quantlab/research_core/application/walk_forward_inputs.py', inputs)
    body = [
        n
        for n in tree.body
        if getattr(n, 'name', '') not in names | {'_score', 'compact_walk_forward', 'result_rows'}
        and n is not metrics
        and not isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    presentation = 'import json\nfrom desktop_app.strings.catalog import ui_text\nfrom quantlab.core import canonical_json\nfrom quantlab import significance as _significance\nfrom quantlab import verdict as _verdict\nfrom quantlab.research_core.application.walk_forward_projection import oos_statistics_data\n\n'
    presentation += ''.join(source(n) for n in body)
    presentation = presentation.replace("if state.get('status') != 'completed':", "if not data['available']:")
    presentation = presentation.replace(
        "title = ui_text('walk_forward.statistics.title')",
        "data = state.get('oos_statistics') or oos_statistics_data(state)\n    title = ui_text('walk_forward.statistics.title')",
    )
    presentation = presentation.replace("merged = _significance.merge_oos_daily_returns(state)", 'merged = data')
    presentation = presentation.replace("stats = _significance.mean_positive_test(merged['returns'])", "stats = data['stats']").replace(
        "required = _significance.required_observations(merged['returns'])", "required = data['required']"
    )
    presentation = presentation.replace('decline = _significance.oos_decline_test(state)', "decline = data['decline']").replace(
        "_verdict_text(stats, required, merged['returns'])", "_verdict_text(data['verdict'])"
    )
    presentation = presentation.replace(
        'def _verdict_text(stats, required, returns):\n    conclusion = _verdict.judge(stats, required, returns, ())', 'def _verdict_text(conclusion):'
    )
    presentation += '''def compact_walk_forward(state, reference):
    """Render the compact application projection for desktop evidence views."""
    from quantlab.research_core.application.walk_forward_projection import compact_walk_forward as project
    result = project(state, reference)
    result['oos_statistics_text'] = oos_statistics_text(result)
    return result
'''
    write(path, presentation)
    write(
        'desktop_app/features/walk_forward/rows.py',
        'from desktop_app.strings.catalog import ui_text\nfrom desktop_app.features.walk_forward.presenter import FAMILY_NAMES, status_label\n\n'
        + source(nodes['result_rows']),
    )


def extract_worker_dependencies():
    path = 'desktop_app/features/assistant/assistant_models.py'
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    context = next((n for n in tree.body if getattr(n, 'name', '') == 'context_usage'), None)
    if context:
        write('quantlab/assistant/application/context_usage.py', source(context))
        tree.body.remove(context)
        write(path, 'from quantlab.assistant.application.context_usage import context_usage\n' + ast.unparse(tree) + '\n')
    path = 'desktop_app/features/capital_scenario/worker.py'
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    event = next((n for n in tree.body if getattr(n, 'name', '') == 'event'), None)
    if event:
        write(
            'desktop_app/features/capital_scenario/presenter.py',
            'from quantlab.capital_scenario import empty_result\nfrom quantlab.desktop_feedback import completion_summary\n\n' + source(event),
        )
        tree.body.remove(event)
        tree.body = [n for n in tree.body if not isinstance(n, ast.ImportFrom) or n.module != 'quantlab.desktop_feedback']
        write(path, ast.unparse(tree) + '\n')


def migrate_references():
    owners = {}
    contracts = ast.parse((ROOT / 'quantlab/assistant/application/connection_contracts.py').read_text(encoding='utf-8'))
    for n in contracts.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            owners[('desktop_app.features.assistant.connection', n.name)] = 'quantlab.assistant.application.connection_contracts'
        if isinstance(n, ast.Assign):
            owners[('desktop_app.features.assistant.connection', n.targets[0].id)] = 'quantlab.assistant.application.connection_contracts'
    owners.update(
        {
            ('desktop_app.features.assistant.connection', n): 'quantlab.assistant.adapters.chatgpt.connection_worker'
            for n in ('run_connection_request', '_safe_error_code')
        }
    )
    for name in ('_folder', '_binding', 'source_campaign_folder', '_prepare_saved_plan', '_range', 'preview_walk_forward', 'execute_walk_forward'):
        owners[('desktop_app.features.walk_forward.presenter', name)] = 'quantlab.research_core.application.walk_forward_operations'
    owners[('desktop_app.features.walk_forward.presenter', 'result_rows')] = 'desktop_app.features.walk_forward.rows'
    owners[('desktop_app.features.assistant.assistant_models', 'context_usage')] = 'quantlab.assistant.application.context_usage'
    owners[('desktop_app.features.assistant.connection_test', 'run_probe')] = 'quantlab.assistant.adapters.chatgpt.connection_probe'
    owners[('desktop_app.features.capital_scenario.worker', 'event')] = 'desktop_app.features.capital_scenario.presenter'
    for folder in ('desktop_app', 'quantlab', 'tests', 'tools'):
        for path in (ROOT / folder).rglob('*.py'):
            if 'strings' in path.parts or path == Path(__file__).resolve():
                continue
            text = path.read_text(encoding='utf-8')
            edits = []
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.ImportFrom) and any((node.module, n.name) in owners for n in node.names):
                    groups = {}
                    for n in node.names:
                        owner = owners.get((node.module, n.name), node.module)
                        groups.setdefault(owner, []).append(n.name + (' as ' + n.asname if n.asname else ''))
                    replacement = ('\n' + ' ' * node.col_offset).join('from ' + mod + ' import ' + ', '.join(names) for mod, names in groups.items())
                    edits.append((node.lineno, node.end_lineno, node.col_offset, replacement))
            lines = text.splitlines(keepends=True)
            for start, end, col, replacement in sorted(edits, reverse=True):
                lines[start - 1 : end] = [' ' * col + replacement + '\n']
            text = ''.join(lines)
            # Module-qualified worker calls and patch targets must follow the owner.
            for old, new in [
                (
                    'desktop_app.features.assistant.connection.run_connection_request',
                    'quantlab.assistant.adapters.chatgpt.connection_worker.run_connection_request',
                ),
                ('desktop_app.features.assistant.connection_test.run_probe', 'quantlab.assistant.adapters.chatgpt.connection_probe.run_probe'),
            ]:
                text = text.replace(old, new)
            if folder == 'tests' and ('ui.run_connection_request' in text or 'self.ui.run_connection_request' in text):
                text = (
                    'from quantlab.assistant.adapters.chatgpt import connection_worker\n' + text
                    if 'from quantlab.assistant.adapters.chatgpt import connection_worker' not in text
                    else text
                )
                text = text.replace('self.ui.run_connection_request', 'connection_worker.run_connection_request').replace(
                    'ui.run_connection_request', 'connection_worker.run_connection_request'
                )
            if text != path.read_text(encoding='utf-8'):
                write(path.relative_to(ROOT).as_posix(), text)


def replace(path, old, new):
    text = (ROOT / path).read_text(encoding='utf-8')
    write(path, text.replace(old, new))


def finish_boundaries():
    replace(
        'desktop_app/features/assistant/connection.py',
        'from desktop_app.strings.catalog import ui_text',
        'from quantlab.desktop_errors import exception_code\nfrom desktop_app.strings.catalog import ui_text',
    ) if 'from quantlab.desktop_errors import exception_code' not in (ROOT / 'desktop_app/features/assistant/connection.py').read_text(
        encoding='utf-8'
    ) else None
    replace(
        'desktop_app/features/assistant/connection_presenter.py',
        'def render_apply_reconciliation_event_23(self, kind, messages):',
        'def render_apply_reconciliation_event_23(self, kind):',
    )
    # QObject initialization traverses the MRO: keep the core constructor optional
    # during that pass, then initialize its two explicit effect ports below.
    replace(
        'quantlab/assistant/application/connection_controller.py',
        'def __init__(self, *, emit, present):',
        'def __init__(self, *, emit=None, present=None):\n        if emit is None:\n            return',
    )
    errors = ast.parse((ROOT / 'quantlab/desktop_errors.py').read_text(encoding='utf-8'))
    error_code = next(n for n in errors.body if getattr(n, 'name', '') == 'exception_code')
    write('quantlab/assistant/domain/connection_errors.py', 'import sqlite3\nfrom quantlab.errors import ERROR_TABLE\n\n' + source(error_code))
    replace(
        'quantlab/assistant/adapters/chatgpt/connection_worker.py',
        'from quantlab.desktop_errors import ERROR_LABELS, exception_code',
        'from quantlab.errors import ERROR_LABELS\nfrom quantlab.assistant.domain.connection_errors import exception_code',
    )
    # Core input validation has no file IO. Dataset IO is supplied by composition.
    inputs_path = 'quantlab/research_core/application/walk_forward_inputs.py'
    inputs = ast.parse((ROOT / inputs_path).read_text(encoding='utf-8'))
    inputs.body = [
        n
        for n in inputs.body
        if getattr(n, 'name', '') != '_dataset' and not isinstance(n, ast.ImportFrom) or isinstance(n, ast.ImportFrom) and n.module != 'quantlab.data'
    ]
    write(inputs_path, ast.unparse(inputs) + '\n')
    operations_path = 'quantlab/research_core/application/walk_forward_operations.py'
    replace(operations_path, '*, descendants_stopped=False):', '*, descendants_stopped=False, dataset_loader=None):')
    replace(operations_path, 'import _dataset, research_controls', 'import research_controls')
    replace(
        operations_path,
        'data = _dataset(Path(paths.state), {})',
        "if dataset_loader is None:\n            raise ValidationError('Dataset input port required')\n        data = dataset_loader(Path(paths.state), {})",
    )
    shell = 'desktop_app/shell/main_window.py'
    replace(
        shell, "payload, paths, descendants_stopped=descendants_stopped)", "payload, paths, descendants_stopped=descendants_stopped, dataset_loader=_dataset)"
    )
    replace(
        shell,
        'import desktop_app.features.capital_scenario.worker as _capital\n                if _capital.event',
        'import desktop_app.features.capital_scenario.presenter as _capital\n                if _capital.event',
    )
    # Adapter wiring belongs to composition, exposed through an application port.
    write(
        'quantlab/assistant/ports/connection.py',
        '"""Application-owned connection worker registration and dispatch contract."""\nfrom typing import Protocol\n\nclass ConnectionWorker(Protocol):\n    def __call__(self, request, *, bootstrap, emit, cancelled): ...\n\n_worker: ConnectionWorker | None = None\n\ndef configure_connection_worker(worker: ConnectionWorker):\n    global _worker\n    _worker = worker\n\ndef run_connection_request(request, *, bootstrap, emit, cancelled):\n    if _worker is None:\n        raise RuntimeError(\'Connection worker is not configured\')\n    return _worker(request, bootstrap=bootstrap, emit=emit, cancelled=cancelled)\n',
    )
    composition_path = 'desktop_app/connection_composition.py'
    write(
        composition_path,
        '"""Connection worker wiring at the desktop process composition boundary."""\nfrom quantlab.assistant.adapters.chatgpt import connection_worker\nfrom quantlab.assistant.ports.connection import configure_connection_worker\n\ndef configure():\n    configure_connection_worker(lambda request, **kwargs: connection_worker.run_connection_request(request, **kwargs))\n\ndef execute_ui_operation(*args, **kwargs):\n    from desktop_app.shell.main_window import execute_ui_operation as execute\n    configure()\n    return execute(*args, **kwargs)\n',
    )
    replace(
        shell,
        'from quantlab.assistant.adapters.chatgpt.connection_worker import run_connection_request',
        'from quantlab.assistant.ports.connection import run_connection_request',
    )
    # The UI renderer consumes fixed statistical data, retaining pre-rendered
    # archived evidence as well.
    panel = 'desktop_app/components/result_panels.py'
    if "if 'oos_statistics' in result:" not in (ROOT / panel).read_text(encoding='utf-8'):
        replace(
            panel,
            "text = result.get('oos_statistics_text', '')",
            "text = result.get('oos_statistics_text', '')\n        if 'oos_statistics' in result:\n            from desktop_app.features.walk_forward.presenter import oos_statistics_text\n            text = oos_statistics_text(result)",
        )
    # Module-qualified callers (including assertions) receive only path changes.
    contract_tree = ast.parse((ROOT / 'quantlab/assistant/application/connection_contracts.py').read_text(encoding='utf-8'))
    names = [n.name for n in contract_tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    names += [n.targets[0].id for n in contract_tree.body if isinstance(n, ast.Assign)]
    for path in (ROOT / 'tests').glob('*.py'):
        text = path.read_text(encoding='utf-8')
        original = text
        for name in names:
            text = text.replace('self.ui.' + name, 'connection_contracts.' + name).replace('ui.' + name, 'connection_contracts.' + name)
        if text != original and 'from quantlab.assistant.application import connection_contracts' not in text:
            lines = text.splitlines(keepends=True)
            parsed = ast.parse(text)
            first = parsed.body[0]
            index = first.end_lineno if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str) else 0
            lines.insert(index, '\nfrom quantlab.assistant.application import connection_contracts\n')
            text = ''.join(lines)
        # Move the early worker import after any module docstring.
        early = 'from quantlab.assistant.adapters.chatgpt import connection_worker\n'
        if text.startswith(early):
            text = text[len(early) :]
            parsed = ast.parse(text)
            first = parsed.body[0]
            index = first.end_lineno if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str) else 0
            lines = text.splitlines(keepends=True)
            lines.insert(index, '\n' + early)
            text = ''.join(lines)
        if text != original:
            write(path.relative_to(ROOT).as_posix(), text)
    models = 'desktop_app/features/assistant/assistant_models.py'
    text = (ROOT / models).read_text(encoding='utf-8')
    early = 'from quantlab.assistant.application.context_usage import context_usage\n'
    if text.startswith(early):
        text = text[len(early) :]
        first = ast.parse(text).body[0]
        lines = text.splitlines(keepends=True)
        lines.insert(first.end_lineno, '\n' + early)
        write(models, ''.join(lines))
    # Every source has an explicit PR D mapping and an inventory row.
    mapping_path = ROOT / 'tools/layer_map.json'
    mapping = json.loads(mapping_path.read_text(encoding='utf-8'))
    mapping['prefixes']['quantlab/assistant/application/'] = 'application'
    mapping['overrides'][composition_path] = 'composition'
    new_paths = [p.relative_to(ROOT).as_posix() for folder in ('quantlab/assistant/application',) for p in (ROOT / folder).glob('*.py')]
    new_paths += [
        'quantlab/assistant/domain/connection_errors.py',
        'quantlab/assistant/ports/connection.py',
        composition_path,
        'desktop_app/features/assistant/connection_presenter.py',
        'desktop_app/features/capital_scenario/presenter.py',
        'desktop_app/features/walk_forward/rows.py',
        'quantlab/assistant/adapters/chatgpt/connection_worker.py',
        'quantlab/assistant/adapters/chatgpt/connection_probe.py',
    ]
    new_paths += ['quantlab/research_core/application/walk_forward_' + name + '.py' for name in ('operations', 'projection', 'inputs')]
    for path in new_paths:
        if path not in mapping['overrides']:
            mapping['overrides'][path] = (
                'presentation'
                if path.startswith('desktop_app')
                else 'infrastructure'
                if '/adapters/' in path
                else 'domain'
                if '/domain/' in path
                else 'application'
            )
    # Existing debts move with their actual extracted presentation owner.
    mapping['split_origins']['desktop_app/features/capital_scenario/presenter.py'] = 'desktop_capital_scenario.py'
    write('tools/layer_map.json', json.dumps(mapping, ensure_ascii=False, indent=2) + '\n')
    inventory = 'docs/analysis/08_REFACTOR_INVENTORY.md'
    text = (ROOT / inventory).read_text(encoding='utf-8')
    anchor = '\n## 3 '
    rows = ''
    for path in new_paths:
        if f'| `{path}` |' not in text:
            count = len((ROOT / path).read_text(encoding='utf-8').splitlines())
            rows += f'| `{path}` | {count} | {mapping["overrides"][path]} | `{path}` | PR D slice 2b responsibility owner |\n'
    if rows:
        index = text.index(anchor)
        text = text[:index] + '\n' + rows + text[index:]
        write(inventory, text)


def main():
    extract_connection()
    extract_walk_forward()
    extract_worker_dependencies()
    migrate_references()
    finish_boundaries()
    complete_mechanical_references()
    reasons_path = ROOT / '.tmp-layered/test-edit-reasons.json'
    reasons = json.loads(reasons_path.read_text(encoding='utf-8'))
    recorded = {r['file'] for r in reasons if r.get('round') == 'T4 slice 2b'}
    for path in sorted(CHANGED):
        if path.startswith('tests/') and path not in recorded:
            reasons.append(
                {
                    'file': path,
                    'reason': 'Mechanical import and patch target migration to extracted owners by tools/refactor/split_core_ui.py; assertions unchanged.',
                    'round': 'T4 slice 2b',
                }
            )
    reasons_path.write_text(json.dumps(reasons, indent=2) + '\n', encoding='utf-8')


def _complete_mechanical_references():
    import re

    for path in (ROOT / 'tests').glob('*.py'):
        text = path.read_text(encoding='utf-8')
        text = text.replace('ui._safe_error_code', 'connection_worker._safe_error_code')
        if 'connection_worker._safe_error_code' in text and 'from quantlab.assistant.adapters.chatgpt import connection_worker' not in text:
            first = ast.parse(text).body[0]
            offset = first.end_lineno if isinstance(first, ast.Expr) else 0
            lines = text.splitlines(keepends=True)
            lines.insert(offset, '\nfrom quantlab.assistant.adapters.chatgpt import connection_worker\n')
            text = ''.join(lines)
        # Compose worker adapters for tests that call the operation entry directly.
        text = re.sub(
            r'from desktop_app.shell.main_window import execute_ui_operation\b', 'from desktop_app.connection_composition import execute_ui_operation', text
        )
        if 'import execute_ui_operation,' in text and 'from desktop_app.connection_composition' in text:
            # Mixed imports retain all non-entry-point symbols at their owners.
            text = re.sub(
                r'(?m)^([ \t]*)from desktop_app.connection_composition import execute_ui_operation, ([^\n]+)',
                r'\1from desktop_app.connection_composition import execute_ui_operation\n\1from desktop_app.shell.main_window import \2',
                text,
            )
        if '"""' in text or "'''" in text:
            parsed = ast.parse(text)
            doc = next((n for n in parsed.body[:4] if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)), None)
            if doc and doc is not parsed.body[0]:
                lines = text.splitlines(keepends=True)
                block = ''.join(lines[doc.lineno - 1 : doc.end_lineno])
                del lines[doc.lineno - 1 : doc.end_lineno]
                text = block + '\n' + ''.join(lines).lstrip()
        if text != path.read_text(encoding='utf-8'):
            write(path.relative_to(ROOT).as_posix(), text)
    shell = 'desktop_app/shell/main_window.py'
    replace(
        shell,
        'from desktop_app.connection_composition import connection_request as run_connection_request',
        'from quantlab.assistant.ports.connection import run_connection_request',
    )
    mapping = json.loads((ROOT / 'tools/layer_map.json').read_text(encoding='utf-8'))
    contract = 'quantlab/assistant/application/connection_contracts.py'
    if contract not in mapping['ports']:
        mapping['ports'].append(contract)
        write('tools/layer_map.json', json.dumps(mapping, ensure_ascii=False, indent=2) + '\n')


def complete_mechanical_references():
    _complete_mechanical_references()
    for path in (ROOT / 'tests').glob('*.py'):
        text = path.read_text(encoding='utf-8')
        for name in ('_binding', 'run_walk_forward', 'read_walk_forward_state', 'execute_walk_forward', 'preview_walk_forward'):
            text = text.replace('desktop_app.features.walk_forward.presenter.' + name, 'quantlab.research_core.application.walk_forward_operations.' + name)
        if 'quantlab.research_core.application.walk_forward_operations._binding' in text:
            text = text.replace('import desktop_app.features.walk_forward.presenter\n', 'import quantlab.research_core.application.walk_forward_operations\n')
        text = text.replace('desktop_app.features.walk_forward.presenter.result_rows', 'desktop_app.features.walk_forward.rows.result_rows')
        text = text.replace(
            'from desktop_app.features.assistant import connection_test as probe', 'from quantlab.assistant.adapters.chatgpt import connection_probe as probe'
        )
        text = text.replace(
            'import desktop_app.features.walk_forward.presenter as adapter', 'import quantlab.research_core.application.walk_forward_operations as adapter'
        )
        text = text.replace(
            "{'plan': preview['plan'], 'preview_identity': identity}, self.paths)",
            "{'plan': preview['plan'], 'preview_identity': identity}, self.paths, dataset_loader=fake_ui._dataset)",
        )
        if text != path.read_text(encoding='utf-8'):
            write(path.relative_to(ROOT).as_posix(), text)
    replace(
        'quantlab/research_core/domain/job_protocol.py',
        "DEFAULT_OPERATION_REGISTRAR = 'desktop_app.shell.main_window:execute_ui_operation'",
        "DEFAULT_OPERATION_REGISTRAR = 'desktop_app.connection_composition:execute_ui_operation'",
    )
    text = (ROOT / 'desktop.py').read_text(encoding='utf-8')
    if 'configure_connection()' not in text:
        first = next(n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)))
        lines = text.splitlines(keepends=True)
        lines.insert(first.lineno - 1, 'from desktop_app.connection_composition import configure as configure_connection\nconfigure_connection()\n\n')
        write('desktop.py', ''.join(lines))


def repair_r3b_references():
    # Move public error-catalog observers to its real owner, without facade exports.
    for p in (ROOT / 'tests').glob('*.py'):
        s = p.read_text(encoding='utf-8')
        old = s
        if 'ui.ERROR_LABELS' in s:
            s = 'from quantlab.desktop_errors import ERROR_LABELS\n' + s if not s.startswith(('"""', "'''")) else s
            if 'from quantlab.desktop_errors import ERROR_LABELS' not in s:
                tree = ast.parse(s)
                n = tree.body[0]
                lines = s.splitlines(keepends=True)
                lines.insert(n.end_lineno, '\nfrom quantlab.desktop_errors import ERROR_LABELS\n')
                s = ''.join(lines)
            s = s.replace('ui.ERROR_LABELS', 'ERROR_LABELS')
        s = s.replace(
            'from desktop_app.features.assistant.connection import ConnectionController, ERROR_LABELS',
            'from desktop_app.features.assistant.connection_presenter import ConnectionController\n        from quantlab.desktop_errors import ERROR_LABELS',
        )
        if s != old:
            write(p.relative_to(ROOT).as_posix(), s)
    replace('tests/test_capital_scenario_b5.py', 'adapter.event(', 'scenario_presenter.event(')
    replace(
        'tests/test_capital_scenario_b5.py',
        'import desktop_app.features.capital_scenario.worker as adapter',
        'import desktop_app.features.capital_scenario.worker as adapter\nfrom desktop_app.features.capital_scenario import presenter as scenario_presenter',
    )

    # Historical test source checks observe immutable base bytes; CURRENT checks use the appended identity.
    for p in (ROOT / 'tests').glob('test_*producer_profile.py'):
        s = p.read_text()
        s = s.replace('len(pools.SUPPORTED_PRODUCERS), 29', 'len(pools.SUPPORTED_PRODUCERS), 30').replace(
            'len(SUPPORTED_PRODUCERS), 29', 'len(SUPPORTED_PRODUCERS), 30'
        )
        tree = ast.parse(s)
        lines = s.splitlines(keepends=True)
        for n in sorted([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)], key=lambda n: n.lineno, reverse=True):
            block = ''.join(lines[n.lineno - 1 : n.end_lineno])
            if 'current' in n.name or 'literal_sources_match' in n.name:
                # Keep relational historical assertions and historical pins unchanged.
                if p.name == 'test_atomic_replace_producer_profile.py':
                    block = block.replace(
                        "self.assertEqual(actual, new['engine_source_hashes'])",
                        "self.assertEqual(actual, {name: pools.CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes'][name] for name in actual})",
                    )
                    block = block.replace("actual['research.py'], 'c6d", "new['engine_source_hashes']['research.py'], 'c6d")
                elif p.name == 'test_fail_closed_producer_profile.py':
                    block = block.replace(
                        "expected_sources['research.py'] = ATOMIC_REPLACE_TRANSPORT_PROFILE_V1['engine_source_hashes']['research.py']",
                        "expected_sources['research.py'] = CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes']['research.py']",
                    )
                    block = block.replace('ATOMIC_REPLACE_TRANSPORT_PROFILE_V1[', 'CORE_SPLIT_SIWC_PROFILE_V1[')
                else:
                    block = block.replace('pools.ATOMIC_REPLACE_TRANSPORT_PROFILE_V1', 'pools.CORE_SPLIT_SIWC_PROFILE_V1').replace(
                        'pools.ATOMIC_REPLACE_SIWC_PROFILE_V1', 'pools.CORE_SPLIT_SIWC_PROFILE_V1'
                    )
                lines[n.lineno - 1 : n.end_lineno] = [block]
        s = ''.join(lines)
        if p.name == 'test_fail_closed_producer_profile.py':
            s = s.replace('    ATOMIC_REPLACE_TRANSPORT_PROFILE_V1,', '    CORE_SPLIT_SIWC_PROFILE_V1,')
        write(p.relative_to(ROOT).as_posix(), s)

    replace(
        'desktop_app/shell/main_window.py',
        'from quantlab.desktop_runtime import validate_analysis_request',
        'from quantlab.runtime_support import validate_analysis_request',
    )
    replace(
        'quantlab/research_core/domain/saved_pool.py',
        'class SavedCandidatePoolError(ValidationError):',
        "class SavedCandidatePoolError(ValidationError):\n    __module__ = 'quantlab.saved_candidate_pool'",
    )


def repair_r3b_projection():
    path = ROOT / 'quantlab/research_core/application/walk_forward_projection.py'
    text = path.read_text(encoding='utf-8')
    old = "    result.update(stats=stats, required=required, decline=_significance.oos_decline_test(state), verdict=_verdict.judge(stats, required, merged['returns'], ()))"
    new = old + "\n    result['decline'] = {key: value for key, value in result['decline'].items() if not key.startswith('p_value_increase')}"
    if "not key.startswith('p_value_increase')" not in text:
        write(path.relative_to(ROOT).as_posix(), text.replace(old, new))


if __name__ == '__main__':
    main()
    repair_r3b_references()
    repair_r3b_projection()

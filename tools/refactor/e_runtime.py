"""Idempotent E3 runtime extraction and mechanical consumer rewrites."""

import ast
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OLD = 'quantlab.desktop_runtime'
PREFIX = 'quantlab.research_core.'
GROUPS = {
    'adapters.workspace_store': [
        'WORKSPACE_FORMAT',
        'REPLAY_REQUIREMENT',
        'WALK_FORWARD_REQUIREMENT',
        'GUARDED_BACKUP_VERSION',
        'MAX_BACKUP',
        'MAX_FILES',
        '_workspace_format',
        '_marker_stream',
        '_write_workspace_format',
        'AppPaths',
        'WorkspaceLocator',
    ],
    'adapters.settings_store': ['SettingsStore'],
    'adapters.state_json': ['STATE_VERSION', 'MAX_JSON', '_json_bytes', '_read_json'],
    'adapters.runtime_safety': ['_verify_replay_runtime', 'RuntimeGuard'],
    'adapters.event_log': ['RedactedEventLog'],
    'application.job_manager': ['JobManager'],
    'domain.job_protocol': ['OPERATIONS', 'UI_OPERATIONS', 'ANALYSIS_OPERATIONS', 'WALK_FORWARD_OPERATIONS'],
}
OWNERS = {name: PREFIX + mod for mod, names in GROUPS.items() for name in names}
HEADERS = {
    'adapters.workspace_store': '''import ctypes
import os
from pathlib import Path
import stat
import sys
import tempfile
from dataclasses import dataclass
from quantlab.windows_paths import canonical_path, native_path
from quantlab.runtime_support import atomic_write, _sync_directory
from quantlab.shared.runtime_errors import RuntimeSafetyError
from .state_json import STATE_VERSION, _json_bytes, _read_json
from .settings_store import SettingsStore
from .runtime_safety import _verify_replay_runtime
''',
    'adapters.settings_store': '''from pathlib import Path
from quantlab.runtime_support import atomic_write
from quantlab.shared.runtime_errors import RuntimeSafetyError
from .state_json import STATE_VERSION, _json_bytes, _read_json
''',
    'adapters.state_json': '''import json
from quantlab.windows_paths import native_path
from quantlab.shared.runtime_errors import RuntimeSafetyError
''',
    'adapters.runtime_safety': '''import os
import time
from quantlab import __version__
from quantlab.runtime_support import atomic_write
from quantlab.shared.runtime_errors import RuntimeSafetyError
from .state_json import _json_bytes
''',
    'adapters.event_log': '''import json
import os
from pathlib import Path
import time
from quantlab.shared.runtime_errors import RuntimeSafetyError
from quantlab.research_core.domain.job_protocol import OPERATIONS
from .state_json import _json_bytes
''',
    'application.job_manager': '''import time
import uuid
from quantlab.shared.runtime_errors import RuntimeSafetyError
from quantlab.research_core.ports.jobs import JobProcessPort, JobStoragePort, JobEventLogPort
from quantlab.research_core.domain.job_protocol import OPERATIONS, UI_OPERATIONS, ANALYSIS_OPERATIONS, WALK_FORWARD_OPERATIONS
''',
}


def write(path, source):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding='utf-8') != source:
        path.write_text(source, encoding='utf-8', newline='\n')


def definitions(source):
    result = {}
    lines = source.splitlines(keepends=True)
    for node in ast.parse(source).body:
        name = getattr(node, 'name', None)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name:
            start = min([node.lineno] + [d.lineno for d in getattr(node, 'decorator_list', [])])
            result[name] = ''.join(lines[start - 1 : node.end_lineno])
    return result


def extract():
    path = 'quantlab/desktop_runtime.py'
    source = (ROOT / path).read_text(encoding='utf-8')
    defs = definitions(source)
    if 'AppPaths' not in defs:
        return
    for module, header in HEADERS.items():
        body = '\n\n'.join(defs[n] for n in GROUPS[module])
        if module == 'adapters.event_log':
            body = body.replace(
                'def __init__(self, path):\n        self.path = Path(path)',
                'def __init__(self, path, *, error_codes):\n        self.path = Path(path)\n        self.error_codes = error_codes',
            )
            body = body.replace('from .desktop_errors import ERROR_TABLE', 'ERROR_TABLE = self.error_codes')
        if module == 'application.job_manager':
            body = adapt_manager(body)
        write(
            module.replace('.', '/').join(['quantlab/research_core/', '.py']),
            '"""Runtime responsibility extracted with safety ordering preserved."""\n\nfrom __future__ import annotations\n\n' + header + '\n\n' + body,
        )
    credentials = defs['CredentialVault'] + '\n\n' + defs['DesktopCredentialReference']
    credentials = credentials.replace(
        'return CredentialVault(AppPaths(Path(self.root))).load(self.name)',
        'from quantlab.research_core.adapters.workspace_store import AppPaths\n\n        return CredentialVault(AppPaths(Path(self.root))).load(self.name)',
    )
    write(
        path,
        '"""Desktop DPAPI credential boundary; secrets resolve only in the HTTP child."""\n\nfrom __future__ import annotations\n\nimport ctypes\nfrom pathlib import Path\nimport re\nimport sys\nfrom dataclasses import dataclass\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\nfrom .runtime_support import (\n    WindowsAppMutex as WindowsAppMutex,\n    WINDOWS_APP_MUTEX as WINDOWS_APP_MUTEX,\n    atomic_write,\n)\n\n\n'
        + credentials,
    )


def adapt_manager(body):
    tree = ast.parse(body)
    methods = {n.name: ast.get_source_segment(body, n) for n in tree.body[0].body if isinstance(n, ast.FunctionDef)}
    owner = '\n\n'.join('    ' + methods[n] for n in ('_walk_forward_owner_path', '_claim_walk_forward', '_check_walk_forward_owner'))
    owner = owner.replace('self.paths', 'self.paths').replace('self.storage_port.check_regular_path', 'self.check_regular_path')
    write(
        'quantlab/research_core/adapters/walk_forward_owner.py',
        '"""Durable original-writer ownership evidence; never grants recovery alone."""\n\nimport os\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\nfrom .state_json import _json_bytes, _read_json\n\n\nclass WalkForwardOwner:\n    def __init__(self, paths, check_regular_path):\n        self.paths = paths\n        self.check_regular_path = check_regular_path\n\n'
        + owner
        + '\n',
    )
    for name, args in [
        ('_walk_forward_owner_path', 'reference'),
        ('_claim_walk_forward', 'reference, job_id'),
        ('_check_walk_forward_owner', 'job_id, reference'),
    ]:
        body = body.replace(methods[name], f'def {name}(self, {args}):\n        return self.storage_port.{name}(self.paths, {args})')
    body = body.replace(
        'process_port: JobProcessPort | None = None, storage_port: JobStoragePort | None = None',
        'process_port: JobProcessPort, storage_port: JobStoragePort, event_log: JobEventLogPort',
    )
    body = body.replace(
        'self.process_port, self.storage_port = _job_ports(process_port, storage_port)', 'self.process_port, self.storage_port = process_port, storage_port'
    )
    body = body.replace("self.event_log = RedactedEventLog(paths.logs / 'desktop-events.jsonl')", 'self.event_log = event_log')
    body = body.replace('from .errors import ERROR_TABLE', 'from quantlab.errors import ERROR_TABLE').replace(
        'from .analysis_recovery import require_operation', 'from quantlab.analysis_recovery import require_operation'
    )
    body = body.replace('_json_bytes(payload)', 'self.storage_port.validate_payload(payload)')
    body = body.replace(
        "        # Characterization callers may construct the lifecycle with __new__.\n        if not hasattr(self, 'process_port'):\n            self.process_port, self.storage_port = _job_ports(None, None)\n",
        '',
    )
    body = body.replace(
        '        # Defer the adapter until this operation runs in its owning process.\n        from quantlab.research_core.adapters.job_process import DesktopJobProcess\n\n        port = getattr(self, \'process_port\', None) or DesktopJobProcess()',
        '        port = self.process_port',
    )
    return body


def rewrite_imports(source):
    # Also rewrite imports in embedded smoke programs and migration templates.
    pattern = r'(?m)( *)(from (?:quantlab\.desktop_runtime|\.desktop_runtime) import )(\([^)]*\)|[^;\n]+)'

    def replace(match):
        indent, _, names = match.groups()
        groups = {}
        for item in names.strip('() \n').replace('\n', ' ').split(','):
            item = item.strip()
            if not item:
                continue
            name = item.split()[0]
            groups.setdefault(OWNERS.get(name, OLD), []).append(item)
        return ('\n' + indent).join('from ' + mod + ' import ' + ', '.join(items) for mod, items in groups.items()).join([indent, ''])

    return re.sub(pattern, replace, source)


def rewrite_attributes(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(a.asname or a.name for a in node.names if a.name == OLD)
        elif isinstance(node, ast.ImportFrom) and node.module == 'quantlab':
            aliases.update(a.asname or a.name for a in node.names if a.name == 'desktop_runtime')
    extra = set()
    for alias in aliases:
        for name, owner in OWNERS.items():
            old = alias + '.' + name
            if re.search(r'\b' + re.escape(old) + r'\b', source):
                source = re.sub(r'\b' + re.escape(old) + r'\b', name, source)
                extra.add('from ' + owner + ' import ' + name)
    if extra:
        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
        offset = 0
        for node in tree.body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                or isinstance(node, ast.ImportFrom)
                and node.module == '__future__'
            ):
                offset = node.end_lineno
            else:
                break
        lines[offset:offset] = [line + '\n' for line in sorted(extra)]
        source = ''.join(lines)
    return source


def consumers():
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    for path in paths:
        if (
            not path.endswith(('.py', '.spec'))
            or not (ROOT / path).exists()
            or path.startswith('tools/refactor/')
            and path != 'tools/refactor/split_ui_oracles.py'
        ):
            continue
        source = (ROOT / path).read_text(encoding='utf-8-sig')
        source = rewrite_attributes(rewrite_imports(source))
        for name, owner in OWNERS.items():
            source = source.replace(OLD + '.' + name, owner + '.' + name)
        # Concrete construction is composed; the class stays available for class-level patches.
        if path != 'desktop_app/research_bootstrap.py' and path.startswith(('desktop', 'tests/', 'tools/')):
            source, count = re.subn(r'(?<![\w.])JobManager\(', 'create_job_manager(', source)
            source, logs = re.subn(r'(?<![\w.])RedactedEventLog\(', 'create_event_log(', source)
            imports = []
            if count:
                imports.append('create_job_manager')
            if logs:
                imports.append('create_event_log')
            if imports:
                # Keep generated programs self-contained by putting imports beside their class imports.
                for name in imports:
                    class_name = 'JobManager' if name == 'create_job_manager' else 'RedactedEventLog'
                    source = re.sub(
                        r'(?m)^( *)from ([\w.]+) import ([^\n]*\b' + class_name + r'\b[^\n]*)$',
                        lambda m: m[0] + '\n' + m[1] + 'from desktop_app.research_bootstrap import ' + name,
                        source,
                    )
        write(path, source)


def embedded_programs(source):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or 'from quantlab.desktop_runtime import ' not in node.value:
            continue
        try:
            ast.parse(node.value)
        except SyntaxError:
            continue
        new = rewrite_imports(node.value)
        for cls, factory in [('JobManager', 'create_job_manager'), ('RedactedEventLog', 'create_event_log')]:
            new, count = re.subn(r'(?<![\w.])' + cls + r'\(', factory + '(', new)
            if count:
                new = 'from desktop_app.research_bootstrap import ' + factory + '\n' + new
        if new != node.value:
            start = offsets[node.lineno - 1] + node.col_offset
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            edits.append((start, end, repr(new)))
    for start, end, new in sorted(edits, reverse=True):
        source = source[:start] + new + source[end:]
    return source


def repair_references():
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    for path in paths:
        if not path.endswith('.py') or path.startswith('tools/refactor/') or not (ROOT / path).is_file():
            continue
        source = embedded_programs((ROOT / path).read_text(encoding='utf-8'))
        replacements = {
            OLD + '.os.replace': 'quantlab.runtime_support.os.replace',
            OLD + '.os.killpg': PREFIX + 'adapters.job_process.os.killpg',
            OLD + '.os.setsid': PREFIX + 'adapters.job_worker.os.setsid',
            OLD + '.os.fsync': PREFIX + 'adapters.workspace_store.os.fsync',
            OLD + '.time.': PREFIX + 'application.job_manager.time.',
            OLD + '.tempfile.': PREFIX + 'adapters.workspace_store.tempfile.',
            PREFIX + 'adapters.runtime_safety._verify_replay_runtime': PREFIX + 'adapters.workspace_store._verify_replay_runtime',
            'desktop_runtime.uuid': 'job_manager.uuid',
            'desktop_runtime.time': 'job_manager.time',
            'runtime.os,': 'job_worker.os,',
            'desktop_app.research_bootstrap import ResearchSession': 'desktop_app.research_session import ResearchSession',
            'desktop_app.research_bootstrap import UnifiedResearch': 'desktop_app.research_session import UnifiedResearch',
            'desktop_app.research_bootstrap import EmbeddedSettings': 'desktop_app.research_session import EmbeddedSettings',
            'desktop_app.research_bootstrap import ResearchUnavailable': 'desktop_app.research_session import ResearchUnavailable',
            "'quantlab/desktop_runtime.py': 'JobManager.start'": "'quantlab/research_core/application/job_manager.py': 'JobManager.start'",
        }
        if path.endswith(('test_log_table.py', 'test_settings_sections.py')):
            replacements[OLD + '.time.'] = PREFIX + 'adapters.event_log.time.'
        for old, new in replacements.items():
            source = source.replace(old, new)
        if path.endswith('test_t11_part_c.py'):
            if 'manager.storage_port = WorkspaceJobStorage()' not in source:
                source = source.replace(
                    '            manager._log = Mock()',
                    '            manager._log = Mock()\n            manager.process_port = job_process.DesktopJobProcess()\n            manager.storage_port = WorkspaceJobStorage()',
                )
            if 'from quantlab.research_core.application import job_manager' not in source:
                anchor = 'from quantlab.research_core.application.job_manager import JobManager'
                source = source.replace(
                    anchor,
                    'from quantlab.research_core.application import job_manager\nfrom quantlab.research_core.adapters.workspace_backup import WorkspaceJobStorage\n'
                    + anchor,
                )
        if 'job_worker.os,' in source and 'import job_worker' not in source:
            source = 'from quantlab.research_core.adapters import job_worker\n' + source
        if path in ('tests/test_product_ai_boundary.py', 'tests/test_desktop_saved_candidate_pool.py'):
            anchor = "            'quantlab/desktop_runtime.py',"
            extra = ''.join("\n            'quantlab/research_core/" + module.replace('.', '/') + ".py'," for module in HEADERS)
            extra += "\n            'quantlab/research_core/adapters/walk_forward_owner.py',"
            if "'quantlab/research_core/adapters/state_json.py'," not in source:
                source = source.replace(anchor, anchor + extra)
        if path in ('tests/layered_source_fixtures.py', 'tests/test_no_hardcoded_ui_text.py'):
            source = source.replace('desktop_app/research_bootstrap.py', 'desktop_app/research_session.py')
        if path == 'tests/test_layer_gate.py' and "'quantlab/research_core/adapters/state_json.py':" not in source:
            anchor = "                'desktop_app/features/capital_scenario/presenter.py': 'desktop_capital_scenario.py',"
            extra = ''.join(
                "\n                'quantlab/research_core/" + module.replace('.', '/') + ".py': 'quantlab/desktop_runtime.py'," for module in HEADERS
            )
            extra += "\n                'quantlab/research_core/adapters/walk_forward_owner.py': 'quantlab/desktop_runtime.py',"
            source = source.replace(anchor, anchor + extra)
        source = worker_calls(source)
        source = source.replace(
            '**kwargs, storage_port=WorkspaceJobStorage()', "**dict(kwargs, storage_port=kwargs.get('storage_port') or WorkspaceJobStorage())"
        )
        write(path, source)


def worker_calls(source):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    needed = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
        if (
            name not in ('_job_worker', '_original_job_worker', 'ORIGINAL_WORKER')
            or any(k.arg == 'storage_port' for k in node.keywords)
            or 'storage_port=' in ast.get_source_segment(source, node)
        ):
            continue
        # Direct worker invocations in tooling/fixtures use the same default storage port.
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        edits.append((end - 1, ', storage_port=WorkspaceJobStorage()'))
        needed = True
    for offset, text in sorted(edits, reverse=True):
        # Multiline calls already have a trailing comma.
        before = source[:offset].rstrip()
        if before.endswith(','):
            text = text[1:]
        source = source[:offset] + text + source[offset:]
    if needed:
        # Spawn wrappers accept the injected port; their direct call constructs the identical adapter.
        tree = ast.parse(source)
        lines = source.splitlines(keepends=True)
        for node in sorted(ast.walk(tree), key=lambda n: getattr(n, 'lineno', 0), reverse=True):
            if isinstance(node, ast.FunctionDef) and node.args.vararg and node.args.kwarg is None:
                segment = ast.get_source_segment(source, node)
                if not any(name in segment for name in ('_job_worker(', 'ORIGINAL_WORKER(')):
                    continue
                first = node.lineno - 1
                last = node.body[0].lineno - 1
                header = ''.join(lines[first:last])
                position = header.rfind(')')
                header = header[:position] + ', **runtime_options' + header[position:]
                lines[first:last] = [header]
        source = ''.join(lines)
        tree = ast.parse(source)
        offset = 0
        if ast.get_docstring(tree):
            offset = tree.body[0].end_lineno
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == '__future__':
                offset = node.end_lineno
        lines = source.splitlines(keepends=True)
        lines[offset:offset] = ['from quantlab.research_core.adapters.workspace_backup import WorkspaceJobStorage\n']
        source = ''.join(lines)
    return source


if __name__ == '__main__':
    extract()
    consumers()
    repair_references()

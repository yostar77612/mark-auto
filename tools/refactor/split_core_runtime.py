"""Re-runnable AST/text extraction for T4 runtime and saved-pool ownership."""

import ast
import json
import re
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[2]
OWNERS = {}


def write(path, source):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding='utf-8', newline='\n')


def extract(path, groups, headers):
    raw = (ROOT / path).read_bytes()
    text = raw.decode('utf-8')
    lines = text.splitlines(keepends=True)
    nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
    cuts = []
    for target, names in groups.items():
        bodies = []
        for name in names:
            OWNERS[(path[:-3].replace('/', '.'), name)] = target[:-3].replace('/', '.')
            if name not in nodes:
                continue
            node = nodes[name]
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            body = ''.join(lines[start : node.end_lineno])
            body = body.replace('from .', 'from quantlab.')
            bodies.append(body)
            cuts.append((start, node.end_lineno))
        if bodies:
            write(target, headers[target] + '\n\n' + '\n\n\n'.join(bodies) + '\n')
    for start, end in sorted(cuts, reverse=True):
        lines[start:end] = []
    if cuts:
        # Preserve every untouched literal byte, including historical CRLFs.
        (ROOT / path).write_bytes(''.join(lines).encode('utf-8'))


def saved_pool():
    base = 'quantlab/research_core/'
    domain = base + 'domain/saved_pool.py'
    source = base + 'adapters/saved_pool_source.py'
    validation = base + 'application/saved_pool_validation.py'
    attempts = base + 'application/saved_pool_attempts.py'
    common = '''"""Saved campaign evidence; no provider calls or credential access."""
from __future__ import annotations
import json
import math
import os
import re
import sqlite3
import stat
import time
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path, PurePosixPath, PureWindowsPath
from functools import wraps
from urllib.parse import urlsplit
from quantlab.core import Bar, Dataset, StrategySpec, ValidationError, canonical_json, content_hash, freeze, to_dict, validate_utc
from quantlab.data import parse_timestamp, validate_dataset
from quantlab.windows_paths import canonical_path, native_path, sqlite_uri
from quantlab.research import _campaign_config, _dataset_identity, _keys, _unique_keys, candidate_fingerprint, validate_dsl, PARAMETER_CONTRACTS, training_summary
'''
    shared = 'from quantlab.research_core.domain.saved_pool import SavedCandidatePool, SavedCandidatePoolError, _hash, _fail, _safe_boundary, MAX_AUDIT_BYTES, MAX_SOURCE_BARS\n'
    groups = {
        domain: ['SavedCandidatePool', 'SavedCandidatePoolError', '_hash', '_fail', '_safe_boundary'],
        source: [
            '_json_load',
            '_read_file',
            '_audit_tree',
            '_validate_original_dataset',
            'load_original_dataset',
            '_prepare_bounded_read',
            '_read_campaign',
            '_lexical_registry_path',
            '_validate_source_registry',
        ],
        validation: [
            '_check_result',
            '_validate_provider',
            'validate_admission_snapshot',
            '_matches_chatgpt_implementation',
            '_validate_chatgpt_provider',
            '_saved_pool_snapshot',
        ],
        attempts: ['_compatible_request', '_validate_legacy_receipts', '_admit_source_attempt', '_collect_source_attempts', '_validate_source_selection'],
    }
    headers = {
        domain: common + 'from quantlab.errors import fail, saved_candidate_reason\nMAX_AUDIT_BYTES = 32 * 1024 * 1024\nMAX_SOURCE_BARS = 100000\n',
        source: common + shared,
        validation: common + shared,
        attempts: common + shared + 'from quantlab.research_core.application.saved_pool_validation import _check_result\n',
    }
    extract('quantlab/saved_candidate_pool.py', groups, headers)
    p = ROOT / validation
    s = p.read_text(encoding='utf-8').replace(
        'def validate_admission_snapshot(snapshot, pool):', 'def validate_admission_snapshot(snapshot, pool, *, profiles, audited_producer):'
    )
    s = s.replace('SUPPORTED_PRODUCERS', 'profiles').replace("AUDITED_PRODUCER['protocol']", "audited_producer['protocol']")
    write(validation, s)
    p = ROOT / 'quantlab/saved_candidate_pool.py'
    raw = p.read_bytes()
    if b'from quantlab.research_core.domain.saved_pool import' not in raw:
        imports = (
            shared
            + 'from quantlab.research_core.adapters.saved_pool_source import _validate_original_dataset, _read_campaign, _validate_source_registry\nfrom quantlab.research_core.application.saved_pool_validation import _validate_provider, _matches_chatgpt_implementation, _validate_chatgpt_provider, _saved_pool_snapshot\nfrom quantlab.research_core.application.saved_pool_attempts import _collect_source_attempts, _validate_legacy_receipts, _validate_source_selection\n'
        )
        raw = raw.replace(b'MAX_AUDIT_BYTES = 32 * 1024 * 1024', imports.encode() + b'\nMAX_AUDIT_BYTES = 32 * 1024 * 1024', 1)
        p.write_bytes(raw)


def runtime():
    base = 'quantlab/research_core/'
    worker = base + 'adapters/job_worker.py'
    process = base + 'adapters/job_process.py'
    backup = base + 'adapters/workspace_backup.py'
    requests = base + 'application/job_requests.py'
    protocol = base + 'domain/job_protocol.py'
    p = ROOT / 'quantlab/desktop_runtime.py'
    text = p.read_text(encoding='utf-8')
    if 'class BackupManager:' not in text:
        return
    constants = text[text.index('UI_OPERATIONS =') : text.index('def _validate_idea_research_payload')]
    default = "DEFAULT_OPERATION_REGISTRAR = 'desktop_app.shell.main_window:execute_ui_operation'\n"
    write(protocol, '"""Bounded desktop operation grammar and IPC constants."""\n' + default + 'MAX_JSON = 1024 * 1024\n\n' + constants)
    common = '''"""Desktop job implementation extracted without changing safety control flow."""
from __future__ import annotations
import ctypes
import hashlib
import importlib
import json
import multiprocessing as mp
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from quantlab import __version__
from quantlab.windows_paths import canonical_path, native_path
from quantlab.job_stages import normalize_stage, stage_from_traceback
from quantlab.shared.runtime_errors import RuntimeSafetyError
from quantlab.runtime_support import atomic_write, _sync_directory, _durable_replace, validate_analysis_request
from quantlab.research_core.domain.job_protocol import DEFAULT_OPERATION_REGISTRAR, MAX_JSON, UI_OPERATIONS, OPERATIONS, ANALYSIS_OPERATIONS, WALK_FORWARD_OPERATIONS
'''
    registry = text[text.index('_executor_registry =') : text.index('def register_operation_executor(')]
    groups = {
        backup: ['BackupManager'],
        worker: [
            '_OperationExecutorRegistry',
            'register_operation_executor',
            '_operation_executor',
            'register_operation_executor_factory',
            '_worker_operation_executor',
            '_is_worker_registrar_import',
            '_worker_recovery_guard',
            '_job_worker',
        ],
        process: ['_WindowsProcessTree'],
        requests: ['_validate_idea_research_payload', 'validate_walk_forward_request'],
    }
    headers = {
        backup: common
        + 'from quantlab.desktop_runtime import SettingsStore, _read_json, _json_bytes, _workspace_format, _write_workspace_format, _verify_replay_runtime, WORKSPACE_FORMAT, GUARDED_BACKUP_VERSION, STATE_VERSION, MAX_BACKUP, MAX_FILES\n',
        worker: common + 'from quantlab.desktop_runtime import AppPaths, _json_bytes\n',
        process: common + 'from quantlab.research_core.adapters import job_worker\n',
        requests: common,
    }
    extract('quantlab/desktop_runtime.py', groups, headers)
    s = (ROOT / worker).read_text(encoding='utf-8')
    position = s.index('def register_operation_executor(')
    write(worker, s[:position] + registry + '\n' + s[position:])
    s = p.read_text(encoding='utf-8').replace(registry, '').replace(constants, '').replace(default, '')
    manager = next(n for n in ast.parse(s).body if isinstance(n, ast.ClassDef) and n.name == 'JobManager')
    lines = s.splitlines(keepends=True)
    methods = {n.name: n for n in manager.body if isinstance(n, ast.FunctionDef)}
    requests_body, process_body = [], []
    remove = []
    for name in ('_prepare_walk_forward_job', '_prepare_analysis_job', '_prepare_other_job', '_launch_job_process', '_join_descendants'):
        n = methods[name]
        body = textwrap.dedent(''.join(lines[n.lineno - 1 : n.end_lineno])).replace('from .', 'from quantlab.')
        if name.startswith('_prepare'):
            requests_body.append(body)
        else:
            process_body.append(
                body.replace('_executor_registrar', 'job_worker._executor_registrar').replace('target=_job_worker', 'target=job_worker._job_worker')
            )
        remove.append((n.lineno - 1, n.end_lineno))
    for start, end in sorted(remove, reverse=True):
        lines[start:end] = []
    s = ''.join(lines)
    for name in ('_prepare_walk_forward_job', '_prepare_analysis_job', '_prepare_other_job'):
        s = s.replace('self.' + name + '(operation, payload)', 'job_requests.' + name + '(self, operation, payload)')
    s = s.replace('self._launch_job_process(', 'self.process_port.launch(self, ').replace(
        'self._join_descendants(', 'self.process_port.join_descendants(self, '
    )
    s = s.replace(
        'def __init__(self, paths):\n        self.paths = paths.ensure()',
        'def __init__(self, paths, *, process_port=None, storage_port=None):\n        self.process_port, self.storage_port = _job_ports(process_port, storage_port)\n        self.paths = paths.ensure()',
    )
    head, tail = s.split('class JobManager:', 1)
    s = head + 'class JobManager:' + tail.replace('BackupManager._check_regular_path(', 'self.storage_port.check_regular_path(')
    s = s.replace(
        'BackupManager(self.paths).recover()', 'self.storage_port.recover(self.paths)'
    )  # .replace('BackupManager(self.paths).recover()', 'self.storage_port.recover(self.paths)')
    # Physical termination belongs to the process port; cancellation proof stays here.
    start = s.index('        proc = self.process\n', s.index('    def cancel(self):'))
    end = s.index('        if self._requires_tree_quiescence:\n            self.process_port.join_descendants', start)
    termination = s[start:end]
    s = s[:start] + '        proc = self.process\n        self.process_port.stop(self)\n' + s[end:]
    imports = 'from quantlab.research_core.application import job_requests\nfrom quantlab.research_core.domain.job_protocol import OPERATIONS, UI_OPERATIONS, ANALYSIS_OPERATIONS, WALK_FORWARD_OPERATIONS\n\n\ndef _job_ports(process_port, storage_port):\n    # Composition for legacy direct construction; JobManager uses only ports.\n    from quantlab.research_core.adapters.job_process import DesktopJobProcess\n    from quantlab.research_core.adapters.workspace_backup import WorkspaceJobStorage\n    return process_port or DesktopJobProcess(), storage_port or WorkspaceJobStorage()\n\n'
    s = s.replace('STATE_VERSION = 1', imports + '\nSTATE_VERSION = 1', 1)
    write('quantlab/desktop_runtime.py', s)
    with (ROOT / requests).open('a', encoding='utf-8', newline='\n') as f:
        f.write('\n\n' + '\n\n\n'.join(requests_body) + '\n')
    with (ROOT / process).open('a', encoding='utf-8', newline='\n') as f:
        f.write(
            '\n\n'
            + '\n\n\n'.join(process_body)
            + '\n\n\ndef _stop(self):\n'
            + textwrap.indent(textwrap.dedent(termination), '    ')
            + '\n\nclass DesktopJobProcess:\n    launch = staticmethod(_launch_job_process)\n    join_descendants = staticmethod(_join_descendants)\n    stop = staticmethod(_stop)\n'
        )
    with (ROOT / backup).open('a', encoding='utf-8', newline='\n') as f:
        f.write(
            '\n\nclass WorkspaceJobStorage:\n    check_regular_path = staticmethod(BackupManager._check_regular_path)\n\n    @staticmethod\n    def recover(paths):\n        return BackupManager(paths).recover()\n'
        )
    write(
        base + 'ports/jobs.py',
        '''"""Process and storage boundaries used by desktop lifecycle coordination."""
from typing import Protocol

class JobProcessPort(Protocol):
    def launch(self, manager, operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request): ...
    def join_descendants(self, manager, pid): ...
    def stop(self, manager): ...

class JobStoragePort(Protocol):
    def check_regular_path(self, path): ...
    def recover(self, paths): ...
''',
    )
    for folder in ('application', 'ports', 'adapters'):
        path = base + folder + '/__init__.py'
        if not (ROOT / path).exists():
            write(path, '"""Research core ' + folder + '."""\n')


def references():
    for module, original in (
        ('adapters.workspace_backup', 'quantlab.desktop_runtime'),
        ('adapters.job_worker', 'quantlab.desktop_runtime'),
        ('adapters.job_process', 'quantlab.desktop_runtime'),
        ('application.job_requests', 'quantlab.desktop_runtime'),
    ):
        target = 'quantlab.research_core.' + module
        for node in ast.parse((ROOT / (target.replace('.', '/') + '.py')).read_text(encoding='utf-8')).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                OWNERS[(original, node.name)] = target
    reasons = ROOT / '.tmp-layered/test-edit-reasons.json'
    history = json.loads(reasons.read_text(encoding='utf-8-sig')) if reasons.exists() else []
    for path in ROOT.rglob('*.py'):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(('.git/', '.tmp', 'tools/refactor/', 'quantlab/saved_candidate_pool.py', 'quantlab/research_core/')):
            continue
        s = path.read_text(encoding='utf-8-sig')
        old = s
        lines = s.splitlines(keepends=True)
        changes = []
        for n in ast.walk(ast.parse(s)):
            if not isinstance(n, ast.ImportFrom):
                continue
            module = n.module
            if n.level and rel.startswith('quantlab/'):
                module = 'quantlab.' + (module or '')
            groups = {}
            for item in n.names:
                owner = OWNERS.get((module, item.name), module)
                groups.setdefault(owner, []).append(item.name + (' as ' + item.asname if item.asname else ''))
            if set(groups) == {module}:
                continue
            changes.append(
                (
                    n.lineno - 1,
                    n.end_lineno,
                    ''.join(' ' * n.col_offset + 'from ' + owner + ' import ' + ', '.join(names) + '\n' for owner, names in groups.items()),
                )
            )
        for start, end, replacement in sorted(changes, reverse=True):
            lines[start:end] = [replacement]
        s = ''.join(lines)
        for (owner, name), target in OWNERS.items():
            s = s.replace(owner + '.' + name, target + '.' + name)
        # Module-qualified runtime/pool references retain their spelling and point to real owners.
        tree = ast.parse(s)
        additions = set()
        swaps = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                for item in n.names:
                    if item.name in ('desktop_runtime', 'saved_candidate_pool'):
                        swaps[item.asname or item.name] = 'quantlab.' + item.name
            elif isinstance(n, ast.Import):
                for item in n.names:
                    if item.name in ('quantlab.desktop_runtime', 'quantlab.saved_candidate_pool') and item.asname:
                        swaps[item.asname] = item.name
        for alias, owner in swaps.items():
            for (old_owner, name), target in OWNERS.items():
                if old_owner == owner and alias + '.' + name in s:
                    token = target.rsplit('.', 1)[1]
                    additions.add('from ' + target.rsplit('.', 1)[0] + ' import ' + token)
                    s = s.replace(alias + '.' + name, token + '.' + name)
        if additions:
            # Insert after all future imports.
            tree = ast.parse(s)
            offset = max([n.end_lineno for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == '__future__'] or [0])
            if (
                not offset
                and tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ):
                offset = tree.body[0].end_lineno
            lines = s.splitlines(keepends=True)
            lines[offset:offset] = ['\n' + '\n'.join(sorted(additions)) + '\n']
            s = ''.join(lines)
        if s != old:
            write(rel, s)
            if rel.startswith('tests/') or rel.endswith('_test.py'):
                history.append({'file': rel, 'reason': 'Slice 2a scripted import/patch-target ownership update; assertions unchanged.'})
    reasons.write_text(json.dumps(history, indent=2) + '\n', encoding='utf-8')


def finalize_patch_targets():
    r = ROOT
    for p in r.joinpath('tests').rglob('*.py'):
        if p.name == 'test_layer_gate.py':
            continue
        s = p.read_text(encoding='utf-8-sig')
        old = s
        s = s.replace('quantlab.desktop_runtime.mp.', 'quantlab.research_core.adapters.job_process.mp.')
        s = s.replace('quantlab.desktop_runtime._durable_replace', 'quantlab.research_core.adapters.workspace_backup._durable_replace')
        s = s.replace('quantlab.saved_candidate_pool.os.open', 'quantlab.research_core.adapters.saved_pool_source.os.open')
        if p.name == 'test_saved_candidate_pool.py':
            s = s.replace('quantlab.saved_candidate_pool.content_hash', 'quantlab.research_core.adapters.saved_pool_source.content_hash')
        if p.name == 'test_desktop_saved_candidate_pool.py':
            s = s.replace(
                "patch('quantlab.desktop_runtime.Path', PureWindowsPath)", "patch('quantlab.research_core.application.job_requests.Path', PureWindowsPath)"
            )
        imports = set()
        for alias in ('desktop_runtime', 'runtime'):
            if alias + '.mp' in s:
                s = s.replace(alias + '.mp', 'job_process.mp')
                imports.add('job_process')
            for name in (
                '_job_worker',
                '_worker_recovery_guard',
                '_worker_operation_executor',
                '_is_worker_registrar_import',
                '_operation_executor',
                '_executor_registry',
                '_executor_registrar',
            ):
                if f"patch.object({alias}, '{name}'," in s:
                    s = s.replace(f"patch.object({alias}, '{name}',", f"patch('quantlab.research_core.adapters.job_worker.{name}',")
                if alias + '.' + name in s:
                    s = s.replace(alias + '.' + name, 'job_worker.' + name)
                    imports.add('job_worker')
            if f"patch.object({alias}, '_WindowsProcessTree'" in s:
                s = s.replace(f"patch.object({alias}, '_WindowsProcessTree'", "patch.object(job_process, '_WindowsProcessTree'")
                imports.add('job_process')
        if imports:
            tree = ast.parse(s)
            pos = max([n.end_lineno for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == '__future__'] or [0])
            if (
                not pos
                and tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ):
                pos = tree.body[0].end_lineno
            ls = s.splitlines(keepends=True)
            ls[pos:pos] = ['\nfrom quantlab.research_core.adapters import ' + ', '.join(sorted(imports)) + '\n']
            s = ''.join(ls)
            # Embedded subprocess programs have their own import scope.
            for line in ('from quantlab import desktop_runtime as runtime', 'import quantlab.desktop_runtime as runtime'):
                s = s.replace(line + '\n', line + '\nfrom quantlab.research_core.adapters import ' + ', '.join(sorted(imports)) + '\n')
        if s != old:
            p.write_text(s, encoding='utf-8', newline='\n')


def finish_ipc_and_workspace_checks():
    path = ROOT / 'quantlab/desktop_runtime.py'
    source = path.read_text(encoding='utf-8')
    lines = source.splitlines(keepends=True)
    edits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef):
            continue
        if any(isinstance(item, ast.Name) and item.id == 'BackupManager' for item in ast.walk(node)):
            if not any(isinstance(item, ast.ImportFrom) and item.module == 'quantlab.research_core.adapters.workspace_backup' for item in ast.walk(node)):
                position = node.body[0].lineno - 1
                if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                    position = node.body[0].end_lineno
                edits.append((position, ' ' * (node.col_offset + 4) + 'from quantlab.research_core.adapters.workspace_backup import BackupManager\n'))
    for position, value in sorted(edits, reverse=True):
        lines[position:position] = [value]
    source = ''.join(lines)
    drain = next((node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == 'drain'), None)
    if drain is not None:
        lines = source.splitlines(keepends=True)
        body = textwrap.dedent(''.join(lines[drain.lineno - 1 : drain.end_lineno])).replace('def drain():', 'def _drain(self, events):')
        lines[drain.lineno - 1 : drain.end_lineno] = []
        source = ''.join(lines).replace('            drain()', '            self.process_port.drain(self, events)')
        process = ROOT / 'quantlab/research_core/adapters/job_process.py'
        content = process.read_text(encoding='utf-8')
        content = content.replace('import ctypes', 'import ctypes\nimport json\nfrom quantlab.research_core.domain.job_protocol import MAX_JSON', 1)
        process.write_text(content + '\n\n' + body + '\nDesktopJobProcess.drain = staticmethod(_drain)\n', encoding='utf-8', newline='\n')
    path.write_text(source, encoding='utf-8', newline='\n')


def explicit_snapshot_profiles():
    for path in (ROOT / 'tests').rglob('*.py'):
        source = path.read_text(encoding='utf-8-sig')
        lines = source.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        edits = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'validate_admission_snapshot' and not node.keywords:
                edits.append(offsets[node.end_lineno - 1] + node.end_col_offset - 1)
        if not edits:
            continue
        for end in sorted(edits, reverse=True):
            source = source[:end] + ', profiles=pool_profiles.SUPPORTED_PRODUCERS, audited_producer=pool_profiles.AUDITED_PRODUCER' + source[end:]
        tree = ast.parse(source)
        offset = max([node.end_lineno for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == '__future__'] or [0])
        if (
            not offset
            and tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            offset = tree.body[0].end_lineno
        lines = source.splitlines(keepends=True)
        lines[offset:offset] = ['\nfrom quantlab import saved_candidate_pool as pool_profiles\n']
        path.write_text(''.join(lines), encoding='utf-8', newline='\n')


def repair_r3a():
    """Restore lifecycle ownership and mechanically relocate reference lookups."""
    path = ROOT / 'quantlab/desktop_runtime.py'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'^from quantlab.research_core.application import job_requests\n', '', source, flags=re.MULTILINE)
    source = re.sub(
        r'^from quantlab.research_core.ports.jobs import JobProcessPort, JobStoragePort',
        'from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from quantlab.research_core.ports.jobs import JobProcessPort, JobStoragePort',
        source,
        flags=re.MULTILINE,
    )
    source = source.replace(
        'job_requests._prepare_walk_forward_job(\n                self, operation, payload\n            )', 'self._prepare_walk_forward_job(operation, payload)'
    )
    for name in ('_prepare_walk_forward_job', '_prepare_analysis_job', '_prepare_other_job'):
        source = source.replace('job_requests.' + name + '(self, operation, payload)', 'self.' + name + '(operation, payload)')
        source = source.replace('return self.' + name + '(operation, payload)', 'return job_requests.' + name + '(self, operation, payload)')
    source = source.replace('self.process_port.launch(self, ', 'self._launch_job_process(')
    source = source.replace('self.process_port.join_descendants(self, ', 'self._join_descendants(')
    source = source.replace('return self._launch_job_process(', 'return self.process_port.launch(self, ')
    source = source.replace('return self._join_descendants(pid)', 'return self.process_port.join_descendants(self, pid)')
    source = source.replace(
        '    def _join_descendants(self, pid):\n        return self.process_port.join_descendants(self, pid)',
        "    def _join_descendants(self, pid):\n        from quantlab.research_core.adapters.job_process import DesktopJobProcess\n\n        port = getattr(self, 'process_port', None) or DesktopJobProcess()\n        return port.join_descendants(self, pid)",
    )
    if '    def _prepare_other_job(' not in source:
        methods = ''
        for name in ('_prepare_walk_forward_job', '_prepare_analysis_job', '_prepare_other_job'):
            methods += (
                f'    def {name}(self, operation, payload):\n'
                '        from quantlab.research_core.application import job_requests\n\n'
                f'        return job_requests.{name}(self, operation, payload)\n\n'
            )
        methods += '''    def _launch_job_process(self, operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request):
        # Characterization callers may construct the lifecycle with __new__.
        if not hasattr(self, 'process_port'):
            self.process_port, self.storage_port = _job_ports(None, None)
        return self.process_port.launch(self, operation, payload, job_id, reconciliation_admitted, helper_nonce, approved_analysis_plan, request)

    def _join_descendants(self, pid):
        from quantlab.research_core.adapters.job_process import DesktopJobProcess

        port = getattr(self, 'process_port', None) or DesktopJobProcess()
        return port.join_descendants(self, pid)

'''
        source = source.replace('    def start(self, operation, payload):', methods + '    def start(self, operation, payload):')
    write('quantlab/desktop_runtime.py', source)

    owners = {
        '_WindowsProcessTree': 'quantlab.research_core.adapters.job_process',
        '_durable_replace': 'quantlab.runtime_support',
        'validate_analysis_request': 'quantlab.runtime_support',
        'BackupManager': 'quantlab.research_core.adapters.workspace_backup',
        '_job_worker': 'quantlab.research_core.adapters.job_worker',
        '_worker_operation_executor': 'quantlab.research_core.adapters.job_worker',
        '_worker_recovery_guard': 'quantlab.research_core.adapters.job_worker',
        '_is_worker_registrar_import': 'quantlab.research_core.adapters.job_worker',
    }
    reasons = ROOT / '.tmp-layered/test-edit-reasons.json'
    history = json.loads(reasons.read_text(encoding='utf-8-sig'))
    # Match single-line imports inside embedded subprocess programs as well.
    pattern = re.compile(r'from quantlab\.desktop_runtime import ([A-Za-z_][\w]*(?: as \w+)?(?:, [A-Za-z_]\w*(?: as \w+)?)*)')

    def relocate(match):
        groups = {}
        for item in match.group(1).split(', '):
            owner = owners.get(item.split(' as ')[0], 'quantlab.desktop_runtime')
            groups.setdefault(owner, []).append(item)
        return '; '.join('from ' + owner + ' import ' + ', '.join(names) for owner, names in groups.items())

    paths = list((ROOT / 'tests').rglob('*.py')) + list((ROOT / 'tools').glob('*.py'))
    paths.append(ROOT / 'tests/fixtures/desktop_ui_pre_registry.py.txt')
    # Only owned product modules; cross-PR imports are reported for the controller.
    paths.append(ROOT / 'desktop_app/features/compare/compare.py')
    for path in paths:
        source = path.read_text(encoding='utf-8-sig')
        old = source
        source = pattern.sub(relocate, source)
        if path.relative_to(ROOT).as_posix() == 'desktop_app/features/compare/compare.py':
            source = source.replace(
                'from quantlab.runtime_support import validate_analysis_request',
                'from quantlab.research_core.application.job_requests import validate_analysis_request',
            )
        if path.name == 'test_t11_boundaries.py':
            source = source.replace('runtime.importlib', 'job_worker.importlib')
            source = source.replace('runtime.validate_analysis_request', 'job_requests.validate_analysis_request')
            source = source.replace("patch.object(runtime, 'AppPaths'", "patch.object(job_worker, 'AppPaths'")
            if 'from quantlab.research_core.application import job_requests' not in source:
                source = source.replace(
                    'from quantlab.research_core.adapters import job_worker',
                    'from quantlab.research_core.application import job_requests\nfrom quantlab.research_core.adapters import job_worker',
                )
        if path.name == 'test_quality_gate.py':
            source = source.replace(
                'source = "from desktop_app.connection_composition import execute_ui_operation"',
                'source = "from desktop_app.shell.main_window import execute_ui_operation"',
            )
        if path.name == 'test_t11_part_b.py':
            source = source.replace(
                "SavedCandidatePoolError.__module__, 'quantlab.saved_candidate_pool'",
                "SavedCandidatePoolError.__module__, 'quantlab.research_core.domain.saved_pool'",
            )
        if path.name == 'test_agent_harness_d2.py':
            source = source.replace('quantlab/assistant/adapters/chatgpt/auth.py::DPAPIVault', 'quantlab/assistant/adapters/chatgpt/vault.py::DPAPIVault')
        if path.name == 'test_import_graph.py':
            for name in ('_job_worker', '_worker_recovery_guard'):
                source = source.replace(f"(runtime, '{name}')", f"(importlib.import_module('quantlab.research_core.adapters.job_worker'), '{name}')")
        if path.parent.name == 'tools' and 'sys.path.insert(0, str(ROOT))' in source:
            import_line = 'from quantlab.research_core.adapters import job_worker\n'
            if import_line in source and source.index(import_line) < source.index('sys.path.insert(0, str(ROOT))'):
                source = source.replace(import_line, '')
                source = source.replace('sys.path.insert(0, str(ROOT))\n', 'sys.path.insert(0, str(ROOT))\n' + import_line, 1)
        if path.name == 'bench_worker_latency.py':
            source = re.sub(r'^from quantlab.research_core.adapters import job_worker\n', '', source, flags=re.MULTILINE)
            if '    from quantlab.research_core.adapters import job_worker' not in source:
                source = source.replace(
                    '    entered = time.perf_counter()\n',
                    '    from quantlab.research_core.adapters import job_worker\n\n    entered = time.perf_counter()\n',
                    1,
                )
                source = source.replace(
                    '    import quantlab.desktop_runtime as runtime\n',
                    '    import quantlab.desktop_runtime as runtime\n    from quantlab.research_core.adapters import job_worker\n',
                    1,
                )
            source = source.replace("patch.object(runtime, '_job_worker'", "patch.object(job_worker, '_job_worker'")
        if source != old:
            rel = path.relative_to(ROOT).as_posix()
            write(rel, source)
            if rel.startswith('tests/'):
                item = {
                    'file': rel,
                    'slice': 'T4-r3a',
                    'reason': 'Mechanical import, patch lookup or symbol-owner path update; all assertions retained. Quality-gate synthetic import restored to its base spelling.',
                }
                if item not in history:
                    history.append(item)
    document = ROOT / 'docs/AGENT_HARNESS_THREAT_MODEL.md'
    document.write_text(
        document.read_text(encoding='utf-8').replace(
            'quantlab/assistant/adapters/chatgpt/auth.py::DPAPIVault', 'quantlab/assistant/adapters/chatgpt/vault.py::DPAPIVault'
        ),
        encoding='utf-8',
        newline='\n',
    )
    reasons.write_text(json.dumps(history, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    saved_pool()
    runtime()
    finish_ipc_and_workspace_checks()
    references()
    finalize_patch_targets()
    explicit_snapshot_profiles()
    repair_r3a()

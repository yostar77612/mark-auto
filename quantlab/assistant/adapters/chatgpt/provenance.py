"""Provenance responsibility; original guards and ordering preserved."""

from __future__ import annotations

from pathlib import Path
from quantlab.assistant.domain.plan_protocol import PlanError
from quantlab.assistant.domain.plan_protocol import _fail
from quantlab.assistant.domain.plan_protocol import _json
import hashlib
import importlib.metadata
import platform
import re
import sys
from quantlab.assistant.domain.source_components import SOURCE_COMPONENTS


def _dependency_manifest():
    """Strict build inputs shared by admission and the CI-only hash installer."""
    root = Path(__file__).parent
    raw = (root / 'desktop_chatgpt_dependency_manifest.json').read_bytes()
    if not 1 <= len(raw) <= 16384:
        _fail('invalid_dependency_manifest')
    manifest = _json(raw)
    targets = {'windows-cp311-amd64', 'windows-cp312-amd64', 'windows-cp313-amd64', 'linux-cp311-x86_64', 'linux-cp312-x86_64'}
    if (
        set(manifest) != {'version', 'targets'}
        or type(manifest['version']) is not int
        or manifest['version'] != 1
        or type(manifest['targets']) is not dict
        or set(manifest['targets']) != targets
    ):
        _fail('invalid_dependency_manifest')
    expected = {'PyJWT': '2.15.1', 'cryptography': '50.0.2', 'cffi': '2.1.1', 'pycparser': '3.11'}
    for entry in manifest['targets'].values():
        if type(entry) is not dict or set(entry) != {'dependencies'} or type(entry['dependencies']) is not list or len(entry['dependencies']) != 4:
            _fail('invalid_dependency_manifest')
        seen = set()
        for item in entry['dependencies']:
            if type(item) is not dict or set(item) != {'distribution', 'version', 'wheel_sha256'}:
                _fail('invalid_dependency_manifest')
            name = item['distribution']
            if type(name) is not str or name not in expected or name in seen or item['version'] != expected[name]:
                _fail('invalid_dependency_manifest')
            if type(item['wheel_sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', item['wheel_sha256']):
                _fail('invalid_dependency_manifest')
            seen.add(name)
    return raw, manifest, expected


def _dependency_target():
    """Only declared 64-bit CPython runtimes; never infer other wheel targets."""
    if platform.python_implementation() != 'CPython' or sys.maxsize <= 2**32 or platform.machine().lower() not in ('amd64', 'x86_64'):
        _fail('unsupported_dependency_target')
    version = sys.version_info[:2]
    if sys.platform == 'win32' and version in ((3, 11), (3, 12), (3, 13)):
        return f'windows-cp{version[0]}{version[1]}-amd64'
    if sys.platform == 'linux' and version in ((3, 11), (3, 12)):
        return f'linux-cp{version[0]}{version[1]}-x86_64'
    _fail('unsupported_dependency_target')


def implementation_provenance():
    """Exact shipped source/build-manifest hashes; invoked only at admission.

    Wheel digests are hash-locked build evidence, not a runtime audit of every
    installed distribution byte. Missing source, metadata or manifest blocks.
    """
    try:
        root = Path(__file__).parent
        sources = {}
        for name, path in SOURCE_COMPONENTS:
            raw = (root.parents[3] / path).read_bytes()
            if not (0 if path.endswith('/__init__.py') else 1) <= len(raw) <= 1048576:
                _fail('invalid_packaged_source')
            sources[name] = hashlib.sha256(raw).hexdigest()
        raw, manifest, expected = _dependency_manifest()
        target = _dependency_target()
        observed = {name: importlib.metadata.version(name) for name in expected}
        if observed != expected:
            _fail('dependency_version_mismatch')
        return {
            'source_sha256': sources,
            'dependency_versions': observed,
            'dependency_manifest_sha256': hashlib.sha256(raw).hexdigest(),
            'dependency_target': target,
            'dependency_artifact_evidence': 'hash_locked_build_manifest',
        }
    except PlanError:
        raise
    except Exception:
        raise PlanError('implementation_provenance_unavailable') from None

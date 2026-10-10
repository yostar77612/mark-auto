"""Source/manifest fixtures plus pinned native dependency admission, no network."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import unittest
from unittest.mock import patch
import desktop_chatgpt_provider as p

VERSIONS={'PyJWT':'2.15.1','cryptography':'50.0.2','cffi':'2.1.1','pycparser':'3.11'}
ROOT=Path(p.__file__).parent

class ProvenanceStructureTests(unittest.TestCase):
    """Metadata/platform mocks are explicit synthetic fixtures, not native proof."""
    def setUp(self):
        patches=[patch.object(p.importlib.metadata,'version',side_effect=lambda name:VERSIONS[name]),
                 patch.object(p.sys,'platform','linux'),patch.object(p.sys,'version_info',(3,12,0)),
                 patch.object(p.platform,'machine',return_value='x86_64'),
                 patch.object(p.platform,'python_implementation',return_value='CPython')]
        for mock in patches:mock.start();self.addCleanup(mock.stop)

    def test_exact_sources_and_manifest(self):
        descriptor=p.implementation_provenance()
        for name,digest in descriptor['source_sha256'].items():
            assert digest==hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        assert descriptor['dependency_manifest_sha256']==hashlib.sha256((ROOT/'desktop_chatgpt_dependency_manifest.json').read_bytes()).hexdigest()
        assert str(ROOT) not in json.dumps(descriptor)

    def test_mutation_and_missing_files(self):
        baseline=p.implementation_provenance();original=Path.read_bytes
        for name in ('desktop_chatgpt_auth.py','desktop_chatgpt_provider.py','desktop_chatgpt_dependency_manifest.json'):
            with self.subTest(name=name):
                def altered(path):return original(path)+b'\n' if path==ROOT/name else original(path)
                with patch.object(Path,'read_bytes',altered):
                    changed=p.implementation_provenance()
                    if name.endswith('.py'):assert changed['source_sha256'][name]!=baseline['source_sha256'][name]
                    else:assert changed['dependency_manifest_sha256']!=baseline['dependency_manifest_sha256']
                def missing(path):
                    if path==ROOT/name:raise FileNotFoundError('synthetic private path')
                    return original(path)
                with patch.object(Path,'read_bytes',missing):
                    with self.assertRaises(p.PlanError) as caught:p.implementation_provenance()
                    assert 'private' not in str(caught.exception)

    def test_installed_mismatch_and_malformed_manifest(self):
        with patch.object(p.importlib.metadata,'version',return_value='0.0.0'):
            with self.assertRaises(p.PlanError):p.implementation_provenance()
        original=Path.read_bytes
        with patch.object(Path,'read_bytes',lambda path:b'{"version":1,"targets":{}}' if path.name=='desktop_chatgpt_dependency_manifest.json' else original(path)):
            with self.assertRaises(p.PlanError):p.implementation_provenance()

    def test_target_selection_and_unknown_target(self):
        with patch.object(p.sys,'platform','win32'),patch.object(p.sys,'version_info',(3,13,16)),patch.object(p.platform,'machine',return_value='AMD64'):
            assert p.implementation_provenance()['dependency_target']=='windows-cp313-amd64'
        with patch.object(p.platform,'machine',return_value='arm64'):
            with self.assertRaises(p.PlanError):p.implementation_provenance()

class NativePinnedProvenanceTests(unittest.TestCase):
    """Desktop-full Windows and explicitly required profiles must never skip."""
    @classmethod
    def setUpClass(cls):
        required=os.environ.get('MARKAUTO_REQUIRE_DESKTOP_AUTH_TESTS')=='1'
        try:observed={name:importlib.metadata.version(name) for name in VERSIONS}
        except importlib.metadata.PackageNotFoundError:
            if required:raise AssertionError('Pinned desktop authentication dependencies are mandatory in this profile')
            raise unittest.SkipTest('Optional stdlib-only profile; pinned desktop dependencies not installed')
        if observed!=VERSIONS:raise AssertionError('Installed desktop dependencies do not match exact locked versions')
        supported=(sys.platform=='win32' and sys.version_info[:2]==(3,13)) or (sys.platform=='linux' and sys.version_info[:2]==(3,12))
        if not supported:
            if required:raise AssertionError('Desktop provenance target is unsupported')
            raise unittest.SkipTest('Optional profile is outside declared native test targets')

    def test_real_installed_versions_and_shipped_provenance(self):
        descriptor=p.implementation_provenance()
        assert descriptor['dependency_versions']==VERSIONS
        assert descriptor['dependency_target'] in ('windows-cp313-amd64','linux-cp312-x86_64')
        assert set(descriptor['source_sha256'])=={'desktop_chatgpt_auth.py','desktop_chatgpt_provider.py'}

class NativeProfileBoundaryTests(unittest.TestCase):
    def test_required_profile_missing_dependencies_fails(self):
        with patch.dict(os.environ,{'MARKAUTO_REQUIRE_DESKTOP_AUTH_TESTS':'1'}),patch.object(importlib.metadata,'version',side_effect=importlib.metadata.PackageNotFoundError('fixture')):
            with self.assertRaises(AssertionError):NativePinnedProvenanceTests.setUpClass()

    def test_windows_stdlib_profile_can_skip_missing_optional_dependencies(self):
        with patch.dict(os.environ,{'MARKAUTO_REQUIRE_DESKTOP_AUTH_TESTS':'0'}),patch.object(sys,'platform','win32'),patch.object(sys,'version_info',(3,11,0)),patch.object(importlib.metadata,'version',side_effect=importlib.metadata.PackageNotFoundError('fixture')):
            with self.assertRaises(unittest.SkipTest):NativePinnedProvenanceTests.setUpClass()

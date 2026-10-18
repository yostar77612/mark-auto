"""Source/manifest fixtures plus pinned native dependency admission, no network."""
import copy
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
TARGETS={'windows-cp311-amd64','windows-cp312-amd64','windows-cp313-amd64',
         'linux-cp311-x86_64','linux-cp312-x86_64'}

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

    def test_all_declared_native_targets_and_reject_unknown_platforms(self):
        for system,versions in (('win32',(11,12,13)),('linux',(11,12))):
            for minor in versions:
                for machine in ('AMD64','x86_64'):
                    with self.subTest(system=system,minor=minor,machine=machine):
                        with patch.object(p.sys,'platform',system),patch.object(p.sys,'version_info',(3,minor,0)),patch.object(p.platform,'machine',return_value=machine):
                            target=p.implementation_provenance()['dependency_target']
                            expected=f"{'windows' if system=='win32' else 'linux'}-cp3{minor}-{'amd64' if system=='win32' else 'x86_64'}"
                            self.assertEqual(target,expected)
        for system,version,machine,implementation,bits in (
            ('darwin',(3,12,0),'x86_64','CPython',2**63-1),
            ('linux',(3,13,0),'x86_64','CPython',2**63-1),
            ('win32',(3,14,0),'AMD64','CPython',2**63-1),
            ('linux',(3,10,0),'x86_64','CPython',2**63-1),
            ('linux',(3,12,0),'aarch64','CPython',2**63-1),
            ('linux',(3,12,0),'x86_64','PyPy',2**63-1),
            ('win32',(3,12,0),'AMD64','CPython',2**31-1)):
            with self.subTest(system=system,version=version,machine=machine,implementation=implementation,bits=bits):
                with patch.object(p.sys,'platform',system),patch.object(p.sys,'version_info',version),patch.object(p.platform,'machine',return_value=machine),patch.object(p.platform,'python_implementation',return_value=implementation),patch.object(p.sys,'maxsize',bits):
                    with self.assertRaises(p.PlanError) as caught:p.implementation_provenance()
                    self.assertEqual(caught.exception.code,'unsupported_dependency_target')

    def test_manifest_guards_apply_to_every_target(self):
        original=Path.read_bytes
        baseline=json.loads((ROOT/'desktop_chatgpt_dependency_manifest.json').read_text())
        mutations=[]
        for version in (True,0,2,'1'):
            item=copy.deepcopy(baseline);item['version']=version;mutations.append(item)
        item=copy.deepcopy(baseline);item['extra']=1;mutations.append(item)
        item=copy.deepcopy(baseline);item['targets']['linux-cp313-x86_64']=copy.deepcopy(item['targets']['linux-cp312-x86_64']);mutations.append(item)
        for target in TARGETS:
            item=copy.deepcopy(baseline);del item['targets'][target];mutations.append(item)
            for field,value in (('distribution','unknown'),('version','0.0.0'),('wheel_sha256','A'*64),('wheel_sha256','0'*63),('wheel_sha256',None)):
                item=copy.deepcopy(baseline);item['targets'][target]['dependencies'][0][field]=value;mutations.append(item)
            item=copy.deepcopy(baseline);item['targets'][target]['dependencies'][1]=copy.deepcopy(item['targets'][target]['dependencies'][0]);mutations.append(item)
            item=copy.deepcopy(baseline);item['targets'][target]['dependencies'].pop();mutations.append(item)
            item=copy.deepcopy(baseline);item['targets'][target]['dependencies'][0]['extra']=1;mutations.append(item)
        for index,item in enumerate(mutations):
            with self.subTest(index=index):
                raw=json.dumps(item).encode()
                with patch.object(Path,'read_bytes',lambda path:raw if path.name=='desktop_chatgpt_dependency_manifest.json' else original(path)):
                    with self.assertRaises(p.PlanError) as caught:p.implementation_provenance()
                    self.assertEqual(caught.exception.code,'invalid_dependency_manifest')

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
        supported=(platform.python_implementation()=='CPython' and sys.maxsize>2**32
                   and platform.machine().lower() in ('amd64','x86_64')
                   and ((sys.platform=='win32' and sys.version_info[:2] in ((3,11),(3,12),(3,13)))
                        or (sys.platform=='linux' and sys.version_info[:2] in ((3,11),(3,12)))))
        if not supported:
            if required:raise AssertionError('Desktop provenance target is unsupported')
            raise unittest.SkipTest('Optional profile is outside declared native test targets')

    def test_real_installed_versions_and_shipped_provenance(self):
        descriptor=p.implementation_provenance()
        assert descriptor['dependency_versions']==VERSIONS
        assert descriptor['dependency_target'] in TARGETS
        assert set(descriptor['source_sha256'])=={'desktop_chatgpt_auth.py','desktop_chatgpt_provider.py'}

class NativeProfileBoundaryTests(unittest.TestCase):
    def test_required_profile_missing_dependencies_fails(self):
        with patch.dict(os.environ,{'MARKAUTO_REQUIRE_DESKTOP_AUTH_TESTS':'1'}),patch.object(importlib.metadata,'version',side_effect=importlib.metadata.PackageNotFoundError('fixture')):
            with self.assertRaises(AssertionError):NativePinnedProvenanceTests.setUpClass()

    def test_windows_stdlib_profile_can_skip_missing_optional_dependencies(self):
        with patch.dict(os.environ,{'MARKAUTO_REQUIRE_DESKTOP_AUTH_TESTS':'0'}),patch.object(sys,'platform','win32'),patch.object(sys,'version_info',(3,11,0)),patch.object(importlib.metadata,'version',side_effect=importlib.metadata.PackageNotFoundError('fixture')):
            with self.assertRaises(unittest.SkipTest):NativePinnedProvenanceTests.setUpClass()

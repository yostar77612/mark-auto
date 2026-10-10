"""Offline negatives for the fixed-hash, non-extracting collector integration."""
from pathlib import Path
import hashlib
import io
import json
import os
import runpy
import shutil
import stat
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
VERSIONS={'PyJWT':'2.15.1','cryptography':'50.0.2','cffi':'2.1.1','pycparser':'3.11'}
EXPECTED_SHA='cbf2c6123cd25e53b33e766fb27bea9c9b4d8d174deb5ae54519d07f62dc9b24'


def changed_zip(path,change):
    with zipfile.ZipFile(path) as source:
        items={n:source.read(n) for n in source.namelist()}
    change(items)
    # Recompute the manifest's file hashes: a self-consistent changed input
    # still cannot replace the separately reviewed archive pin.
    if 'notices-manifest.json' in items:
        manifest=json.loads(items['notices-manifest.json'])
        manifest['files']={n:hashlib.sha256(raw).hexdigest() for n,raw in items.items() if n!='notices-manifest.json'}
        manifest['status']='complete';manifest['unresolved']=[]
        items['notices-manifest.json']=json.dumps(manifest).encode()
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as target:
        for n,raw in items.items():target.writestr(n,raw)


class ZipCollectorTests(unittest.TestCase):
    def run_collector(self,mutate=None,versions=None,reparse=None,inventory=False):
        with tempfile.TemporaryDirectory() as temporary:
            temp=Path(temporary);source=temp/'packaging/third_party/chatgpt-auth-native-notices.zip'
            source.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/'packaging/third_party/chatgpt-auth-native-notices.zip',source)
            (temp/'LICENSE.txt').write_text('Fixture Python license')
            (temp/'outside-sentinel').write_text('unchanged')
            dependencies=[]
            if inventory:
                license_file=temp/'fixture-license.txt';license_file.write_text('Existing dependency notice')
                dependencies=[SimpleNamespace(metadata={'Name':'FixtureDependency'},
                    files=['LICENSE.txt'], locate_file=lambda relative:license_file)]
            if mutate:mutate(temp,source)
            old=os.getcwd();os.chdir(temp)
            original_lstat=Path.lstat
            def lstat(path,*args,**kwargs):
                if reparse and path.absolute()==reparse(temp,source).absolute():
                    return SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_file_attributes=0x400)
                return original_lstat(path,*args,**kwargs)
            try:
                with patch('importlib.metadata.distributions',return_value=dependencies),patch('importlib.metadata.version',side_effect=(versions or VERSIONS).__getitem__),patch('sys.base_prefix',str(temp)),patch.object(Path,'lstat',lstat),patch.object(zipfile.ZipFile,'extract',side_effect=AssertionError('Archive extraction forbidden')),patch.object(zipfile.ZipFile,'extractall',side_effect=AssertionError('Archive extraction forbidden')):
                    namespace=runpy.run_path(str(ROOT/'packaging/collect_licenses.py'))
                target=temp/'build/licenses/chatgpt-auth-native-notices.zip'
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),EXPECTED_SHA)
                expected={'PYTHON-LICENSE.txt','chatgpt-auth-native-notices.zip'}
                if inventory:
                    expected.add('FixtureDependency')
                    self.assertEqual((target.parent/'FixtureDependency/LICENSE.txt').read_text(), 'Existing dependency notice')
                self.assertEqual(set(p.name for p in target.parent.iterdir()),expected)
                self.assertEqual(namespace['AUTH_DEPENDENCY_VERSIONS'],VERSIONS)
            finally:
                os.chdir(old)
                self.assertEqual((temp/'outside-sentinel').read_text(),'unchanged')

    def test_exact_archive_copied_unextracted(self):self.run_collector()
    def test_existing_distribution_license_inventory_retained(self):self.run_collector(inventory=True)
    def test_missing_source_fails(self):
        with self.assertRaisesRegex(RuntimeError,'missing'):
            self.run_collector(lambda t,s:s.unlink())
    def test_wrong_hash_fails(self):
        with self.assertRaisesRegex(RuntimeError,'checksum'):
            self.run_collector(lambda t,s:s.write_bytes(s.read_bytes()[:-1]+b'x'))
    def test_partial_bundle_fails(self):
        with self.assertRaisesRegex(RuntimeError,'checksum'):
            self.run_collector(lambda t,s:changed_zip(s,lambda items:items.clear()))
    def test_oversize_source_fails(self):
        with self.assertRaisesRegex(RuntimeError,'bounded regular'):
            self.run_collector(lambda t,s:s.write_bytes(b'x'*(2*1024*1024+1)))
    def test_directory_source_fails(self):
        def mutate(t,s):s.unlink();s.mkdir()
        with self.assertRaisesRegex(RuntimeError,'bounded regular'):self.run_collector(mutate)
    @unittest.skipUnless(hasattr(os,'mkfifo'),'FIFO requires POSIX')
    def test_special_source_fails_without_opening(self):
        def mutate(t,s):s.unlink();os.mkfifo(s)
        with self.assertRaisesRegex(RuntimeError,'bounded regular'):self.run_collector(mutate)
    def test_dependency_version_mismatch_fails(self):
        with self.assertRaisesRegex(RuntimeError,'version mismatch'):
            self.run_collector(versions=VERSIONS|{'cryptography':'50.0.1'})
    def test_missing_license_with_consistent_manifest_fails(self):
        def mutate(t,s):changed_zip(s,lambda items:items.pop('syn-2.0.119/LICENSE-MIT'))
        with self.assertRaisesRegex(RuntimeError,'checksum'):self.run_collector(mutate)
    def test_omitted_component_with_consistent_manifest_fails(self):
        def omit(items):
            for name in list(items):
                if name.startswith('unicode-ident-1.0.24/'):del items[name]
            sbom_name='cryptography-50.0.2/sboms/cryptography-rust.cyclonedx.json'
            sbom=json.loads(items[sbom_name])
            sbom['components']=[c for c in sbom['components'] if c['name']!='unicode-ident']
            items[sbom_name]=json.dumps(sbom).encode()
        with self.assertRaisesRegex(RuntimeError,'checksum'):
            self.run_collector(lambda t,s:changed_zip(s,omit))
    def test_extra_unlisted_file_fails(self):
        def add(items):items['extra-file.txt']=b'not reviewed'
        with self.assertRaisesRegex(RuntimeError,'checksum'):
            self.run_collector(lambda t,s:changed_zip(s,add))
    def test_windows_unsafe_member_paths_fail_without_extraction(self):
        for member in ('C:/escape.txt','C:escape.txt','//server/share/x','../escape','safe/../escape',
                       'safe\\escape','safe/stream:ads','CON','nul.txt','COM1.log','file.','file ',
                       'safe/./escape','safe//escape'):
            with self.subTest(member=member),self.assertRaisesRegex(RuntimeError,'checksum'):
                self.run_collector(lambda t,s:changed_zip(s,lambda items:items.__setitem__(member,b'not reviewed')))
    def test_source_file_symlink_fails(self):
        def mutate(t,s):
            actual=t/'actual.zip';s.rename(actual);s.symlink_to(actual)
        with self.assertRaisesRegex(RuntimeError,'link or reparse'):self.run_collector(mutate)
    def test_source_parent_symlink_fails(self):
        def mutate(t,s):
            actual=t/'actual-parent';s.parent.rename(actual);s.parent.symlink_to(actual,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,'link or reparse'):self.run_collector(mutate)
    def test_dangling_source_parent_fails(self):
        def mutate(t,s):
            shutil.rmtree(s.parent);s.parent.symlink_to(t/'missing',target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,'link or reparse'):self.run_collector(mutate)
    def test_source_parent_junction_attributes_fails(self):
        with self.assertRaisesRegex(RuntimeError,'link or reparse'):
            self.run_collector(reparse=lambda t,s:s.parent)
    def test_source_file_reparse_attributes_fails(self):
        with self.assertRaisesRegex(RuntimeError,'link or reparse'):
            self.run_collector(reparse=lambda t,s:s)
    def test_destination_parent_symlink_fails(self):
        def mutate(t,s):
            outside=t/'outside';outside.mkdir();(t/'build').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,'link or reparse'):self.run_collector(mutate)
    def test_destination_ancestry_junction_attributes_fails(self):
        with self.assertRaisesRegex(RuntimeError,'link or reparse'):
            self.run_collector(reparse=lambda t,s:t/'build')
    def test_destination_file_symlink_fails_preserves_target(self):
        def mutate(t,s):
            dest=t/'build/licenses';dest.mkdir(parents=True)
            (dest/'chatgpt-auth-native-notices.zip').symlink_to(t/'outside-sentinel')
        with self.assertRaisesRegex(RuntimeError,'link or reparse'):self.run_collector(mutate)
    def test_destination_file_directory_fails(self):
        def mutate(t,s):(t/'build/licenses/chatgpt-auth-native-notices.zip').mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError,'destination must be a regular file'):self.run_collector(mutate)

if __name__=='__main__':unittest.main()

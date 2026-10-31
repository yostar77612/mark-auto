"""Exact reviewed mechanical-path profile; no credential or model operation."""

from quantlab.research_core.domain import saved_pool


import copy
import hashlib
import io
from pathlib import Path
import platform
import sys
import unittest

from quantlab import saved_candidate_pool as pools
from quantlab.core import content_hash, to_dict
from tests.core_split_source_fixtures import layered_source_bytes

ROOT = Path(__file__).resolve().parents[1]
PROFILE = pools.LAYERED_PATHS_SIWC_PROFILE_V1
SOURCES = {
    'desktop_chatgpt_auth.py': 'quantlab/assistant/adapters/chatgpt/auth.py',
    'desktop_chatgpt_provider.py': 'quantlab/assistant/adapters/chatgpt/provider.py',
}


def binding(index=0):
    item = to_dict(PROFILE['chatgpt_plan_implementations'][index])
    descriptor = {key: value for key, value in item.items() if key != 'dependency_targets'}
    descriptor['dependency_target'] = item['dependency_targets'][0]
    return {
        'engine_source_hashes': to_dict(PROFILE['engine_source_hashes']),
        'prompt_template_hash': PROFILE['prompt_template_hash'],
        'provider': {'mode': 'chatgpt_plan', 'descriptor': descriptor},
    }


class LayeredPathsProfileTests(unittest.TestCase):
    def test_historical_pool_adapter_rejects_unrelated_source_drift(self):
        from tests.layered_source_fixtures import original_pool_text

        source = (ROOT / 'quantlab/saved_candidate_pool.py').read_text(encoding='utf-8')
        restored = original_pool_text(source)
        self.assertEqual(content_hash(restored), 'a98cf010989dbba963c5b5236553db94bcd809a298b3c94494307bc9f80e2b4f')
        for changed in (
            source + '\nUNREVIEWED_CHANGE = True\n',
            source.replace('SUPPORTED_PRODUCERS = (', 'UNREVIEWED_CHANGE = True\nSUPPORTED_PRODUCERS = (', 1),
        ):
            with self.subTest(changed=changed[-100:]), self.assertRaises(ValueError):
                original_pool_text(changed)

    def test_only_new_protocol_and_reviewed_source_tuple_change(self):
        previous = pools.ATOMIC_REPLACE_SIWC_PROFILE_V1
        restored = to_dict(PROFILE)
        self.assertEqual(PROFILE['protocol'], 'mark_auto_0_2_2_campaign_layered_paths_siwc_v1')
        restored['protocol'] = previous['protocol']
        for current, old in zip(restored['chatgpt_plan_implementations'], previous['chatgpt_plan_implementations']):
            current['source_sha256'] = to_dict(old['source_sha256'])
        self.assertEqual(restored, previous)
        self.assertIs(pools.SUPPORTED_PRODUCERS[-2], PROFILE)
        self.assertEqual(len(pools.SUPPORTED_PRODUCERS), 30)

    def test_exact_current_lf_crlf_sources_and_original_manifest(self):
        for index, implementation in enumerate(PROFILE['chatgpt_plan_implementations']):
            for name, path in SOURCES.items():
                raw = layered_source_bytes(path).replace(b'\r\n', b'\n')
                raw = raw.replace(b'\n', b'\r\n') if index else raw
                self.assertEqual(hashlib.sha256(raw).hexdigest(), implementation['source_sha256'][name])
            raw = (ROOT / 'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json').read_bytes().replace(b'\r\n', b'\n')
            raw = raw.replace(b'\n', b'\r\n') if index else raw
            self.assertEqual(hashlib.sha256(raw).hexdigest(), implementation['dependency_manifest_sha256'])
            for target in implementation['dependency_targets']:
                value = binding(index)
                value['provider']['descriptor']['dependency_target'] = target
                self.assertIs(pools._select_producer(value), PROFILE)

    def test_current_engine_text_identity_is_newline_independent(self):
        for name, expected in PROFILE['engine_source_hashes'].items():
            raw = layered_source_bytes('quantlab/' + name).replace(b'\r\n', b'\n')
            for source in (raw, raw.replace(b'\n', b'\r\n')):
                with io.TextIOWrapper(io.BytesIO(source), encoding='utf-8') as stream:
                    self.assertEqual(content_hash(stream.read()), expected, name)

    def test_actual_raw_sources_select_only_the_exact_host_target(self):
        value = binding()
        descriptor = value['provider']['descriptor']
        manifest = (ROOT / 'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json').read_bytes()
        eol = b'\r\n' if b'\r\n' in manifest else b'\n'
        descriptor['source_sha256'] = {name: hashlib.sha256(layered_source_bytes(path).replace(b'\n', eol)).hexdigest() for name, path in SOURCES.items()}
        descriptor['dependency_manifest_sha256'] = hashlib.sha256(
            (ROOT / 'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json').read_bytes()
        ).hexdigest()
        version = f'cp{sys.version_info.major}{sys.version_info.minor}'
        machine = platform.machine().lower()
        target = f'windows-{version}-amd64' if sys.platform == 'win32' and machine in ('amd64', 'x86_64') else f'{sys.platform}-{version}-{machine}'
        descriptor['dependency_target'] = target
        supported = {target for variant in PROFILE['chatgpt_plan_implementations'] for target in variant['dependency_targets']}
        if target in supported:
            self.assertIs(pools._select_producer(value), PROFILE)
        else:
            with self.assertRaises(saved_pool.SavedCandidatePoolError):
                pools._select_producer(value)

    def test_original_g3_checkout_and_linux_crlf_restrictions_remain(self):
        attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        for path in SOURCES.values():
            self.assertIn(path + ' !eol', attributes)
        for target in ('linux-cp311-x86_64', 'linux-cp312-x86_64'):
            value = binding(1)
            value['provider']['descriptor']['dependency_target'] = target
            with self.assertRaises(saved_pool.SavedCandidatePoolError):
                pools._select_producer(value)

    def test_unknown_tampered_mixed_and_unsupported_tuples_fail_closed(self):
        for index in (0, 1):
            value = binding(index)
            variants = []
            for key in SOURCES:
                changed = copy.deepcopy(value)
                changed['provider']['descriptor']['source_sha256'][key] = 'f' * 64
                variants.append(changed)
            for target in ('windows-cp314-amd64', 'linux-cp313-x86_64'):
                changed = copy.deepcopy(value)
                changed['provider']['descriptor']['dependency_target'] = target
                variants.append(changed)
            changed = copy.deepcopy(value)
            changed['provider']['descriptor']['dependency_manifest_sha256'] = 'f' * 64
            variants.append(changed)
            changed = copy.deepcopy(value)
            changed['provider']['descriptor']['source_sha256']['desktop_chatgpt_provider.py'] = to_dict(PROFILE['chatgpt_plan_implementations'][1 - index])[
                'source_sha256'
            ]['desktop_chatgpt_provider.py']
            variants.append(changed)
            for changed in variants:
                with self.subTest(index=index, descriptor=changed['provider']['descriptor']):
                    with self.assertRaises(saved_pool.SavedCandidatePoolError):
                        pools._select_producer(changed)
        with self.assertRaises(TypeError):
            PROFILE['chatgpt_plan_implementations'][0]['source_sha256']['desktop_chatgpt_provider.py'] = 'f' * 64

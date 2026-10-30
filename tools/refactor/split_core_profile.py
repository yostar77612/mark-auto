"""Emit the single new D-slice producer literal and pinned historical fixtures.

Run after source review/formatting, never at product runtime. Historical profile
assignments are checked against the base Git object before and after insertion.
"""

import ast
import gzip
import hashlib
import json
from pathlib import Path
import pprint
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

NAME = 'CORE_SPLIT_SIWC_PROFILE_V1'
PROTOCOL = 'mark_auto_0_2_2_campaign_core_split_siwc_v1'


def profiles(source):
    lines = source.splitlines(keepends=True)
    return {
        node.targets[0].id: b''.join(lines[node.lineno - 1 : node.end_lineno])
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'freeze'
    }


def emit():
    from quantlab.assistant.domain.source_components import SOURCE_COMPONENTS
    from quantlab.core import content_hash, to_dict
    from quantlab import saved_candidate_pool as pools

    path = ROOT / 'quantlab/saved_candidate_pool.py'
    raw = path.read_bytes()
    baseline = subprocess.check_output(
        ['git', 'cat-file', '--filters', '--path', 'quantlab/saved_candidate_pool.py', '6b78239:quantlab/saved_candidate_pool.py'], cwd=ROOT
    )
    historical = profiles(baseline)
    for name, block in historical.items():
        assert profiles(raw)[name] == block, name
    profile = to_dict(pools.LAYERED_PATHS_SIWC_PROFILE_V1)
    profile['protocol'] = PROTOCOL
    profile['provider_modes'] = ['fixture', 'openai_compatible', 'chatgpt_plan']
    engine = (*profile['engine_source_hashes'], 'research_core/domain/receipts.py')
    profile['engine_source_hashes'] = {name: content_hash((ROOT / 'quantlab' / name).read_text(encoding='utf-8')) for name in engine}
    for index, implementation in enumerate(profile['chatgpt_plan_implementations']):
        sources = {}
        for key, filename in SOURCE_COMPONENTS:
            body = (ROOT / filename).read_bytes().replace(b'\r\n', b'\n')
            if index and key in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'):
                body = body.replace(b'\n', b'\r\n')
            sources[key] = hashlib.sha256(body).hexdigest()
        implementation['source_sha256'] = sources
    assignment = (NAME + ' = freeze(' + pprint.pformat(profile, sort_dicts=False, width=120) + ')\n\n').encode()
    if NAME.encode() + b' = freeze(' in raw:
        start = raw.index(NAME.encode() + b' = freeze(')
        stop = raw.index(b'SUPPORTED_PRODUCERS = (', start)
        raw = raw[:start] + assignment + raw[stop:]
    else:
        raw = raw.replace(b'SUPPORTED_PRODUCERS = (', assignment + b'SUPPORTED_PRODUCERS = (', 1)
        raw = raw.replace(
            b'ATOMIC_REPLACE_SIWC_PROFILE_V1, LAYERED_PATHS_SIWC_PROFILE_V1)',
            b'ATOMIC_REPLACE_SIWC_PROFILE_V1, LAYERED_PATHS_SIWC_PROFILE_V1, ' + NAME.encode() + b')',
            1,
        )
    for name, block in historical.items():
        assert profiles(raw)[name] == block, name
    path.write_bytes(raw)
    historical_sources = {
        filename: subprocess.check_output(['git', 'show', '6b78239:' + filename], cwd=ROOT).decode('utf-8')
        for filename in (
            'quantlab/assistant/adapters/chatgpt/auth.py',
            'quantlab/assistant/adapters/chatgpt/provider.py',
            'quantlab/research.py',
            'quantlab/saved_candidate_pool.py',
        )
    }
    fixture = json.dumps(historical_sources, ensure_ascii=False, sort_keys=True).encode()
    target = ROOT / 'tests/fixtures/core_split_sources.json.gz'
    target.write_bytes(gzip.compress(fixture, mtime=0))
    pins = {
        'profile_hash': content_hash(profile),
        'fixture_sha256': hashlib.sha256(fixture).hexdigest(),
        'current_text_sha256': {
            filename: hashlib.sha256((ROOT / filename).read_text(encoding='utf-8').encode()).hexdigest() for filename in historical_sources
        },
        'historical_profiles': {name: hashlib.sha256(block).hexdigest() for name, block in historical.items()},
    }
    # The pin file is test data, never runtime authority.
    (ROOT / 'tests/fixtures/core_split_pins.json').write_text(json.dumps(pins, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(pins, indent=2))


if __name__ == '__main__':
    emit()

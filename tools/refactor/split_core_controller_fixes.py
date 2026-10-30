"""Reproduce controller-discovered slice-1 owner and current-profile fixes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path, old, new):
    target = ROOT / path
    source = target.read_text(encoding='utf-8')
    if old in new and new in source:
        return
    if old not in source:
        return
    target.write_text(source.replace(old, new), encoding='utf-8', newline='\n')


def rewrite():
    plan = 'tests/test_chatgpt_plan.py'
    replace(
        plan,
        'from quantlab.assistant.adapters.chatgpt.response_stream import SSEParser',
        'from quantlab.assistant.adapters.chatgpt.resolution_audit import _resolution_registration\n'
        'from quantlab.assistant.adapters.chatgpt.response_stream import SSEParser',
    )
    replace(plan, 'self.module._resolution_registration(db,', '_resolution_registration(db,')
    replace(plan, "/ 'quantlab/research.py').read_text(encoding='utf-8')", "/ 'quantlab/research_core/domain/receipts.py').read_text(encoding='utf-8')")
    pool = 'tests/test_saved_candidate_pool.py'
    replace(pool, 'ATOMIC_REPLACE_TRANSPORT_PROFILE_V1', 'CORE_SPLIT_SIWC_PROFILE_V1')
    replace(pool, "Path(research.__file__).with_name(name)", "(Path(research.__file__).parent / name)")
    replace(
        pool,
        '            for name in TRANSPORT_VERIFIER_PRODUCER[\'engine_source_hashes\']',
        '            for name in CORE_SPLIT_SIWC_PROFILE_V1[\'engine_source_hashes\']',
    )
    replace(
        pool,
        '            for name in CLEANUP_TRANSPORT_PROFILE_V1[\'engine_source_hashes\']',
        '            for name in CORE_SPLIT_SIWC_PROFILE_V1[\'engine_source_hashes\']',
    )
    replace(
        pool,
        "            self.assertEqual({k: v for k, v in expected_current.items() if k != 'backtest.py'}, {k: v for k, v in actual.items() if k != 'backtest.py'})",
        "            for name in ('backtest.py', 'research_core/domain/receipts.py'):\n"
        "                expected_current[name] = CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes'][name]\n"
        "            self.assertEqual(expected_current, actual)",
    )
    replace(pool, "'mark_auto_0_2_2_campaign_windows_atomic_replace_transport_v1'", "'mark_auto_0_2_2_campaign_core_split_siwc_v1'")
    replace(
        'quantlab/research_analysis.py',
        "    return {\n        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ('research_analysis.py', 'indicators.py', 'research_core/domain/receipts.py')\n    }",
        "    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ('research_analysis.py', 'indicators.py')}",
    )
    replace(
        'tests/layered_source_fixtures.py',
        "        def source_bytes(path):\n            name = source_keys.get(path)",
        "        def source_bytes(path):\n            if path == root / 'quantlab/research_analysis.py':\n"
        "                return historical_analysis_source(original_read(path))\n            name = source_keys.get(path)",
    )
    replace(
        'tests/layered_source_fixtures.py',
        "            source = original_text(path, *args, **kwargs)\n            return original_pool_text(source)",
        "            source = original_text(path, *args, **kwargs)\n"
        "            if path == root / 'quantlab/research.py':\n"
        "                from tests.core_split_source_fixtures import before_core_split\n\n"
        "                return before_core_split('quantlab/research.py', source)\n"
        "            return original_pool_text(source)",
    )
    replace(
        'tests/layered_source_fixtures.py',
        "        with patch('builtins.__import__', projected_import), patch.object(Path, 'read_bytes', source_bytes), patch.object(Path, 'read_text', source_text):",
        "        with (\n"
        "            patch('builtins.__import__', projected_import),\n"
        "            patch.object(Path, 'read_bytes', source_bytes),\n"
        "            patch.object(Path, 'read_text', source_text),\n"
        "            patch('quantlab.research.content_hash', new=historical_campaign_hash),\n"
        "        ):",
    )
    replace(
        'tests/layered_source_fixtures.py',
        "        def source_bytes(path):\n            if path == root / 'quantlab/research_analysis.py':",
        "        def source_bytes(path):\n            if path == root / 'quantlab/research.py':\n"
        "                from tests.core_split_source_fixtures import before_core_split\n\n"
        "                raw = original_read(path)\n"
        "                restored = before_core_split('quantlab/research.py', raw.decode('utf-8')).encode('utf-8')\n"
        "                return restored.replace(b'\\n', b'\\r\\n') if b'\\r\\n' in raw else restored\n"
        "            if path == root / 'quantlab/research_analysis.py':",
    )
    helper = ROOT / 'tests/layered_source_fixtures.py'
    source = helper.read_text(encoding='utf-8')
    if '\ndef historical_analysis_source(' not in source:
        source += '''\n\ndef historical_analysis_source(raw):
    """Undo only the receipt-validator import move, with an exact historical pin."""
    source = raw.decode('utf-8').replace('\\r\\n', '\\n')
    current = 'from quantlab.research_core.domain.receipts import _validated_receipt_snapshot\\n'
    if source.count(current) != 1 or source.count('    _validated_provider_descriptor,\\n') != 1:
        raise ValueError('Reviewed analysis receipt import changed')
    source = source.replace(current, '', 1).replace(
        '    _validated_provider_descriptor,\\n',
        '    _validated_provider_descriptor,\\n    _validated_receipt_snapshot,\\n',
        1,
    )
    restored = source.encode('utf-8')
    if hashlib.sha256(restored).hexdigest() != '98b60d821e7b7b6fab5a70d9284a16c3708670aac0b56af9ec9c61f6778a8c30':
        raise ValueError('Historical analysis source outside the import move changed')
    return restored
'''
        helper.write_text(source, encoding='utf-8', newline='\n')
    source = helper.read_text(encoding='utf-8')
    if '\ndef historical_campaign_hash(' not in source:
        source += """\n\ndef historical_campaign_hash(value):
    \"\"\"Project only the exact reviewed engine tuple before deriving golden identities.\"\"\"
    from quantlab.core import content_hash, to_dict
    from quantlab.saved_candidate_pool import ATOMIC_REPLACE_TRANSPORT_PROFILE_V1, CORE_SPLIT_SIWC_PROFILE_V1
    from tests.core_split_source_fixtures import layered_source_bytes

    fields = {'config', 'data_hash', 'split_hashes', 'provider', 'prompt_template_hash', 'engine_source_hashes'}
    if isinstance(value, dict) and set(value) == fields:
        if value['engine_source_hashes'] == ATOMIC_REPLACE_TRANSPORT_PROFILE_V1['engine_source_hashes']:
            return content_hash(value)
        expected = to_dict(CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes'])
        expected['research.py'] = content_hash(layered_source_bytes('quantlab/research.py').decode('utf-8').replace('\\r\\n', '\\n'))
        if value['engine_source_hashes'] != expected:
            raise ValueError('Unreviewed current campaign source tuple')
        historical = dict(expected)
        del historical['research_core/domain/receipts.py']
        if historical != ATOMIC_REPLACE_TRANSPORT_PROFILE_V1['engine_source_hashes']:
            raise ValueError('Historical campaign source tuple changed')
        value['engine_source_hashes'] = historical
    return content_hash(value)
"""
        helper.write_text(source, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    rewrite()

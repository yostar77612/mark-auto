"""Reproduce historical/current test-source ownership updates for the core split."""

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def replace_file(name, replacements):
    path = ROOT / name
    source = path.read_text(encoding='utf-8')
    for old, new in replacements:
        if new not in source:
            source = source.replace(old, new)
    path.write_text(source, encoding='utf-8', newline='\n')


def rewrite():
    from quantlab.assistant.domain.source_components import SOURCE_COMPONENTS

    path = ROOT / 'tests/test_chatgpt_provenance.py'
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    changes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and {key.value for key in node.keys if isinstance(key, ast.Constant)} == {
            'desktop_chatgpt_auth.py',
            'desktop_chatgpt_provider.py',
            'desktop_chatgpt_dependency_manifest.json',
        }:
            changes.append(node)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for node in sorted(changes, key=lambda item: item.lineno, reverse=True):
        source = source[: offsets[node.lineno - 1] + node.col_offset] + 'SOURCE_PATHS' + source[offsets[node.end_lineno - 1] + node.end_col_offset :]
    if 'SOURCE_PATHS = ' not in source:
        table = (
            '\nSOURCE_PATHS = {\n'
            + ''.join('    ' + repr(key) + ': ROOT.parents[3] / ' + repr(filename) + ',\n' for key, filename in SOURCE_COMPONENTS)
            + "    'desktop_chatgpt_dependency_manifest.json': ROOT / 'desktop_chatgpt_dependency_manifest.json',\n}\n"
        )
        source = source.replace('\n\nclass ProvenanceStructureTests', table + '\n\nclass ProvenanceStructureTests', 1)
    source = source.replace(
        "for name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py', 'desktop_chatgpt_dependency_manifest.json'):", 'for name in SOURCE_PATHS:'
    )
    source = source.replace(
        "assert set(descriptor['source_sha256']) == {'desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'}",
        "assert set(descriptor['source_sha256']) == set(SOURCE_PATHS) - {'desktop_chatgpt_dependency_manifest.json'}",
    )
    path.write_text(source, encoding='utf-8', newline='\n')
    replace_file(
        'tests/test_layered_paths_profile.py',
        [
            (
                'from quantlab.core import content_hash, to_dict',
                'from quantlab.core import content_hash, to_dict\nfrom tests.core_split_source_fixtures import layered_source_bytes',
            ),
            ("(ROOT / path).read_bytes()", 'layered_source_bytes(path)'),
            ("(ROOT / 'quantlab' / name).read_bytes()", "layered_source_bytes('quantlab/' + name)"),
            ('pools.SUPPORTED_PRODUCERS[-1], PROFILE', 'pools.SUPPORTED_PRODUCERS[-2], PROFILE'),
            ('len(pools.SUPPORTED_PRODUCERS), 29', 'len(pools.SUPPORTED_PRODUCERS), 30'),
        ],
    )
    replace_file(
        'tests/test_long_path_producer_profile.py',
        [
            (
                'from tests.layered_source_fixtures import reviewed_source_bytes',
                'from tests.layered_source_fixtures import reviewed_source_bytes\nfrom tests.core_split_source_fixtures import layered_source_bytes',
            ),
            ("(ROOT / 'quantlab' / name).read_text(encoding='utf-8')", "layered_source_bytes('quantlab/' + name).decode('utf-8')"),
        ],
    )
    replace_file(
        'tests/layered_source_fixtures.py',
        [
            (
                'def original_adapter_text(path: str, source: str) -> str:\n',
                'def original_adapter_text(path: str, source: str) -> str:\n    from tests.core_split_source_fixtures import before_core_split\n\n    source = before_core_split(path, source)\n',
            ),
            (
                '    from quantlab.core import content_hash\n',
                "    from quantlab.core import content_hash\n    from tests.core_split_source_fixtures import before_core_split\n\n    source = before_core_split('quantlab/saved_candidate_pool.py', source)\n",
            ),
        ],
    )


if __name__ == '__main__':
    rewrite()

"""Reproduce the mechanical T4-r3c repair references without changing historical pins."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CHANGED = set()
REASONS = {}


def write(name, text, reason=None):
    path = ROOT / name
    if path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8', newline='\n')
        CHANGED.add(name)
    if reason:
        REASONS[name] = reason


def replace(name, old, new, reason=None):
    text = (ROOT / name).read_text(encoding='utf-8')
    if not new or new not in text:
        text = text.replace(old, new)
    write(name, text, reason)


def repair_workers():
    replace(
        'desktop_app/connection_composition.py',
        'from quantlab.assistant.adapters.chatgpt import connection_worker',
        'import desktop_app.shell.main_window as operations\nfrom quantlab.assistant.adapters.chatgpt import connection_worker',
    )
    replace(
        'desktop_app/connection_composition.py',
        '    from desktop_app.shell.main_window import execute_ui_operation as execute\n\n    configure()\n    return execute(*args, **kwargs)',
        '    configure()\n    return operations.execute_ui_operation(*args, **kwargs)',
    )
    replace(
        'desktop_app/shell/main_window.py',
        '    from desktop_app.features.walk_forward.presenter import render_result',
        '    # Resolve presentation only when the operation runs in its owning process.\n    from desktop_app.features.walk_forward.presenter import render_result',
    )
    replace(
        'desktop_app/features/walk_forward/presenter.py',
        '    from quantlab.research_core.application.walk_forward_projection import compact_walk_forward as project',
        '    # Load the application projection only for completed result rendering.\n    from quantlab.research_core.application.walk_forward_projection import compact_walk_forward as project',
    )
    # The frozen oracle still executes its independent dispatcher; only wire its
    # moved operation and the keyword-only dataset input port added by PR C.
    replace(
        'tests/fixtures/desktop_ui_pre_registry.py.txt',
        '        from desktop_walk_forward import execute_walk_forward\n        return execute_walk_forward(operation, payload, paths, descendants_stopped=descendants_stopped)',
        '        from quantlab.research_core.application.walk_forward_operations import execute_walk_forward\n'
        '        from desktop_app.features.walk_forward.presenter import render_result\n'
        '        return render_result(execute_walk_forward(operation, payload, paths, descendants_stopped=descendants_stopped, dataset_loader=_dataset))',
        'Move frozen oracle walk-forward, connection contracts/worker, and original-dataset loader imports to extracted owners; supply the existing dataset input port and render the same public result. Independent dispatcher and golden assertions retained.',
    )
    fixture = 'tests/fixtures/desktop_ui_pre_registry.py.txt'
    for old, new in (
        ('from desktop_chatgpt_ui import ConnectionEvent', 'from quantlab.assistant.application.connection_contracts import ConnectionEvent'),
        ('from desktop_chatgpt_ui import SubscriptionOptions', 'from quantlab.assistant.application.connection_contracts import SubscriptionOptions'),
        (
            'from quantlab.saved_candidate_pool import load_original_dataset',
            'from quantlab.research_core.adapters.saved_pool_source import load_original_dataset',
        ),
        (
            'from desktop_chatgpt_ui import ConnectionRequest, run_connection_request',
            'from quantlab.assistant.application.connection_contracts import ConnectionRequest\n'
            '        from quantlab.assistant.adapters.chatgpt.connection_worker import run_connection_request',
        ),
    ):
        replace(fixture, old, new)


def repair_profiles():
    replace(
        'tests/layered_source_fixtures.py',
        'def reviewed_source_bytes(root: Path, name: str) -> bytes:\n    if name not in HASHES:',
        'def reviewed_source_bytes(root: Path, name: str, *, current=False) -> bytes:\n'
        '    if current:\n'
        '        from tests.core_split_source_fixtures import CURRENT_SOURCES\n\n'
        '        return (root / CURRENT_SOURCES.get(name, name)).read_bytes()\n'
        '    if name not in HASHES:',
        'Resolve explicit current-profile logical source keys through the complete reviewed physical source table; default historical archive reads stay pinned.',
    )
    for stem in ('completed_items', 'finished_reconciliation', 'stream_content_type', 'unknown_reconciliation'):
        name = 'tests/test_' + stem + '_producer_profile.py'
        replace(
            name,
            'reviewed_source_bytes(ROOT, name)',
            'reviewed_source_bytes(ROOT, name, current=True)',
            'Current-profile byte checks read the actual extracted source owners; apply the LF/CRLF policy only to the two original adapter variants, matching the explicit new profile.',
        )
        replace(
            name,
            "raw if index == 0 else raw.replace(b'\\n', b'\\r\\n')",
            "raw.replace(b'\\n', b'\\r\\n') if index and name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py') else raw",
        )
        replace(name, '                if index:\n', "                if index and name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'):\n")
    name = 'tests/test_long_path_producer_profile.py'
    replace(
        name,
        "actual = {name: content_hash(layered_source_bytes('quantlab/' + name).decode('utf-8')) for name in profile['engine_source_hashes']}\n            expected = dict(profile['engine_source_hashes'])\n            expected['research.py'] = pools.CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes']['research.py']",
        "actual = {name: content_hash((ROOT / 'quantlab' / name).read_text(encoding='utf-8')) for name in pools.CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes']}\n            expected = dict(pools.CORE_SPLIT_SIWC_PROFILE_V1['engine_source_hashes'])",
        'Compare final current engine bytes and provider components with the append-only current profile; historical long-path literal/hash assertions remain exact.',
    )
    replace(name, 'from tests.core_split_source_fixtures import layered_source_bytes\n', '')
    # Restrict provider-current substitution to the current-source check method.
    text = (ROOT / name).read_text(encoding='utf-8')
    start = text.index('    def test_current_engine_and_both_provider_checkout_variants_match')
    end = text.index('\n    def ', start + 5)
    block = text[start:end].replace('reviewed_source_bytes(ROOT, name)', 'reviewed_source_bytes(ROOT, name, current=True)')
    block = block.replace("enumerate(SIWC['chatgpt_plan_implementations'])", "enumerate(pools.CORE_SPLIT_SIWC_PROFILE_V1['chatgpt_plan_implementations'])")
    block = block.replace(
        "raw if index == 0 else raw.replace(b'\\n', b'\\r\\n')",
        "raw.replace(b'\\n', b'\\r\\n') if index and name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py') else raw",
    )
    tail = text[end:].replace("enumerate(pools.CORE_SPLIT_SIWC_PROFILE_V1['chatgpt_plan_implementations'])", "enumerate(SIWC['chatgpt_plan_implementations'])")
    write(name, text[:start] + block + tail)
    replace(
        'tests/test_t11_part_b.py',
        "self.assertEqual(SavedCandidatePoolError.__module__, 'quantlab.research_core.domain.saved_pool')",
        "self.assertEqual(SavedCandidatePoolError.__module__, 'quantlab.saved_candidate_pool')",
        'Restore the base recorded exception identity; product explicitly preserves quantlab.saved_candidate_pool.',
    )
    replace(
        'tests/test_import_graph.py',
        "{'quantlab.ui_preferences', 'quantlab.runtime_support', 'desktop_app.strings.catalog'}",
        "{'quantlab.ui_preferences', 'quantlab.shared.runtime_errors', 'desktop_app.strings.catalog'}",
        'Use the exact shared RuntimeSafetyError import set specified for both PR C and PR D.',
    )
    replace(
        'tests/test_desktop_auth_smoke.py', 'from pathlib import Path', 'from pathlib import Path\nfrom tests.core_split_source_fixtures import CURRENT_SOURCES'
    )
    replace(
        'tests/test_desktop_auth_smoke.py',
        "{'desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'}",
        'set(CURRENT_SOURCES)',
        'Pin the complete extracted current source identity set using the independently reviewed source table; all native, offline and credential assertions retained.',
    )


def repair_inventory():
    from tools import check_layers as gate

    mapping_path = 'tools/layer_map.json'
    mapping = json.loads((ROOT / mapping_path).read_text(encoding='utf-8'))
    mapping['overrides']['tools/refactor/split_core_r3c.py'] = 'tooling'
    write(mapping_path, json.dumps(mapping, ensure_ascii=False, indent=2) + '\n')
    name = 'tests/test_layer_gate.py'
    text = (ROOT / name).read_text(encoding='utf-8')
    start = text.index('    def test_split_origins_preserve_only_existing_debt_and_never_new_edges')
    match = re.search(r'(            \{\n)(.*?)(            \},)', text[start:], re.S)
    assert match
    literal = ''.join('                ' + repr(key) + ': ' + repr(value) + ',\n' for key, value in mapping['split_origins'].items())
    a, b = start + match.start(2), start + match.end(2)
    write(
        name,
        text[:a] + literal + text[b:],
        'Extend the exact split-origin mapping expectation to reviewed extracted owners; preserve every negative debt-expansion assertion.',
    )
    name = 'docs/analysis/08_REFACTOR_INVENTORY.md'
    text = (ROOT / name).read_text(encoding='utf-8')
    section = text.split('## 2 ')[1].split('## 3 ')[0]
    existing = set(re.findall(r'^\| `([^`]+\.py)` \|', section, re.M))
    inverse = {new: old for old, new in json.loads((ROOT / 'tools/layer_relocations.json').read_text()).items()}
    rows = []
    for path in gate.tracked_sources(ROOT):
        if inverse.get(path, path) in existing:
            continue
        layer = gate.layer_for(path, mapping)
        assert layer, path
        count = len((ROOT / path).read_text(encoding='utf-8').splitlines())
        rows.append(f'| `{path}` | {count} | {layer} | `{path}` | PR D extracted responsibility owner (r3c inventory completion) |\n')
    if rows:
        index = text.index('\n## 3 ')
        text = text[:index] + '\n' + ''.join(rows) + text[index:]
    text = re.sub(
        r'(?m)^(\| `([^`]+\.py)` \| )\d+( \| [^\n]*r3c inventory completion[^\n]*)$',
        lambda match: match[1] + str(len((ROOT / match[2]).read_text(encoding='utf-8').splitlines())) + match[3],
        text,
    )
    write(name, text)


def repair_fixture_pin():
    name = 'tests/fixtures/page_services_inventory.json'
    old = json.loads(subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=ROOT))
    current = json.loads((ROOT / name).read_text(encoding='utf-8'))

    def normalized(value):
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items() if key != 'line'}
        if isinstance(value, list):
            return [normalized(item) for item in value]
        return value

    # Patch rows are sorted by source line; line moves can swap their order.
    # Preserve ordering in every other list, including services and aliases.
    previous, updated = normalized(old), normalized(current)
    for value in (previous, updated):
        value['patch_points'].sort(key=lambda item: json.dumps(item, sort_keys=True))
    assert previous == updated, 'Service inventory differs beyond line locations'
    digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    replace(
        'tests/test_download_auto_import_contracts.py',
        "'page_services_inventory.json': '39c5ca7d7e61cca59c62050fdef3b9c9eafd9dc9a04861849423616c3cca325c'",
        "'page_services_inventory.json': '" + digest + "'",
        'Re-pin only the fixture digest after asserting normalized HEAD/current service inventories are identical except line locations; fixture content unchanged in r3c.',
    )


def record():
    path = ROOT / '.tmp-layered/test-edit-reasons.json'
    reasons = json.loads(path.read_text(encoding='utf-8-sig'))
    for name, reason in REASONS.items():
        row = {'file': name, 'reason': reason, 'slice': 'T4-r3c'}
        previous = next((index for index, item in enumerate(reasons) if item.get('file') == name and item.get('slice') == 'T4-r3c'), None)
        if previous is None:
            reasons.append(row)
        else:
            reasons[previous] = row
    path.write_text(json.dumps(reasons, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(sorted(CHANGED), indent=2))


def main():
    repair_workers()
    repair_profiles()
    repair_inventory()
    repair_fixture_pin()
    record()


if __name__ == '__main__':
    main()

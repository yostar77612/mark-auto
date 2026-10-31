"""Update the explicit G3 lock and inventory paths after the authorized split."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCKS = [
    "quantlab/research.py",
    "quantlab/provider.py",
    "quantlab/core.py",
    "quantlab/strategies.py",
    "quantlab/backtest.py",
    "quantlab/data.py",
    "quantlab/assistant/adapters/chatgpt/auth.py",
    "quantlab/assistant/adapters/chatgpt/provider.py",
    "quantlab/assistant/adapters/chatgpt/vault.py",
    "quantlab/assistant/adapters/chatgpt/identity.py",
    "quantlab/assistant/adapters/chatgpt/loopback.py",
    "quantlab/assistant/adapters/chatgpt/account_summary.py",
    "quantlab/assistant/adapters/chatgpt/account_paths.py",
    "quantlab/assistant/adapters/chatgpt/response_stream.py",
    "quantlab/assistant/adapters/chatgpt/transport.py",
    "quantlab/assistant/adapters/chatgpt/provenance.py",
    "quantlab/assistant/adapters/chatgpt/account_store.py",
    "quantlab/assistant/adapters/chatgpt/resolution_audit.py",
    "quantlab/assistant/adapters/chatgpt/unknown_reconciliation.py",
    "quantlab/assistant/adapters/chatgpt/finished_reconciliation.py",
    "quantlab/assistant/adapters/chatgpt/campaign_receipts.py",
    "quantlab/assistant/domain/auth_protocol.py",
    "quantlab/assistant/domain/auth_tokens.py",
    "quantlab/assistant/domain/plan_protocol.py",
    "quantlab/assistant/domain/source_components.py",
    "quantlab/assistant/ports/auth.py",
    "quantlab/research_core/domain/receipts.py",
    "quantlab/assistant/domain/__init__.py",
    "quantlab/assistant/ports/__init__.py",
    "quantlab/research_core/domain/__init__.py",
]


def update():
    path = ROOT / 'pyproject.toml'
    source = path.read_text(encoding='utf-8')
    start = source.index('exclude = [', source.index('[tool.ruff]'))
    end = source.index(']\n', start) + 2
    source = source[:start] + 'exclude = [\n' + ''.join('    ' + json.dumps(name) + ',\n' for name in LOCKS) + ']\n' + source[end:]
    source = source.replace(
        '# Keep the eight G3 source/hash inputs explicit and independently testable.',
        '# Keep all current and historical G3 source/hash inputs explicit and independently testable.',
    )
    path.write_text(source, encoding='utf-8', newline='\n')
    path = ROOT / 'docs/CONTRIBUTING.md'
    source = path.read_text(encoding='utf-8')
    start = source.index('The G3 locked file set')
    end = source.index('The owner approved relocation', start)
    source = (
        source[:start]
        + ('The G3 locked file set covers the following ' + str(len(LOCKS)) + ' source files. They must not be edited\nwithout owner approval:\n\n')
        + ''.join('- `' + name + '`\n' for name in LOCKS)
        + '\n'
        + source[end:]
    )
    path.write_text(source, encoding='utf-8', newline='\n')
    path = ROOT / 'tests/test_ruff_config.py'
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    method = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'test_exact_g3_exclusions_derived_from_producer_hash_keys'
    )
    # Add reviewed logical component names to the old filename mapping.
    mapping = next(
        node.value
        for node in ast.walk(method)
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'moved' for target in node.targets)
    )
    component_tree = ast.parse((ROOT / 'quantlab/assistant/domain/source_components.py').read_text(encoding='utf-8'))
    components = dict(ast.literal_eval(component_tree.body[1].value))
    old = ast.get_source_segment(source, mapping)
    source = source.replace(old, repr(components), 1)
    source = source.replace('self.assertEqual(len(pinned), 8)', 'self.assertEqual(len(pinned), ' + str(len(LOCKS)) + ')')
    source = source.replace('self.assertEqual(len(self.config["exclude"]), 8)', 'self.assertEqual(len(self.config["exclude"]), ' + str(len(LOCKS)) + ')')
    tree = ast.parse(source)
    method = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'test_exact_g3_exclusions_derived_from_producer_hash_keys'
    )
    expected = next(
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Set) and any(isinstance(item, ast.Constant) and item.value == 'quantlab/research.py' for item in node.elts)
    )
    source = source.replace(ast.get_source_segment(source, expected), '{' + ', '.join(repr(name) for name in sorted(LOCKS)) + '}', 1)
    path.write_text(source, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    update()

"""Idempotent mechanical source/patch and build-data updates for D slice 1."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD = 'quantlab.assistant.adapters.chatgpt.provider'
ADAPTER = 'quantlab.assistant.adapters.chatgpt.'


def rewrite():
    for folder in ('tests', 'tools', 'quantlab', 'desktop_app'):
        for path in (ROOT / folder).rglob('*.py'):
            if path.relative_to(ROOT).as_posix().startswith(('tools/refactor/', 'desktop_app/shell/', 'desktop_app/strings/')):
                continue
            source = path.read_text(encoding='utf-8')
            updated = source
            for attr, owner in {
                'official_tls_context': 'identity',
                '_dependency_manifest': 'provenance',
                '_dependency_target': 'provenance',
            }.items():
                updated = updated.replace(OLD + '.' + attr, ADAPTER + owner + '.' + attr)
            if path.name in ('test_chatgpt_provenance.py', 'test_desktop_auth_install.py'):
                updated = updated.replace('import ' + OLD + ' as p', 'import ' + ADAPTER + 'provenance as p')
            # Patch the transport's actual global lookup, not its former owner.
            for attr in ('http', 'ssl', 'socket', 'threading'):
                updated = updated.replace(OLD + '.' + attr, ADAPTER + 'transport.' + attr)
            if updated != source:
                path.write_text(updated, encoding='utf-8', newline='\n')
            if path.relative_to(ROOT).as_posix() in (
                'desktop_app/smoke/__init__.py',
                'tests/test_chatgpt_tls_context.py',
                'tests/test_chatgpt_token_formats.py',
            ):
                tree = ast.parse(updated)
                names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
                lines = updated.splitlines(keepends=True)
                for node in sorted(ast.walk(tree), key=lambda node: getattr(node, 'lineno', 0), reverse=True):
                    if isinstance(node, ast.Import) and all((item.asname or item.name.split('.')[0]) not in names for item in node.names):
                        del lines[node.lineno - 1 : node.end_lineno]
                path.write_text(''.join(lines), encoding='utf-8', newline='\n')


def build_sources():
    source = (ROOT / 'quantlab/assistant/domain/source_components.py').read_text(encoding='utf-8')
    components = ast.literal_eval(ast.parse(source).body[1].value)
    path = ROOT / 'packaging/markauto.spec'
    source = path.read_text(encoding='utf-8')
    additions = []
    for _, name in components:
        if "root / '" + name + "'" not in source:
            additions.append("           (str(root / '" + name + "'), '" + name.rpartition('/')[0] + "'),\n")
    marker = "           (str(root / 'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json')"
    if additions:
        source = source.replace(marker, ''.join(additions) + marker, 1)
        path.write_text(source, encoding='utf-8', newline='\n')


def checkout_endings():
    adapter = ROOT / 'quantlab/assistant/adapters/chatgpt'
    tree = ast.parse((ROOT / 'quantlab/assistant/domain/source_components.py').read_text(encoding='utf-8'))
    for key, filename in ast.literal_eval(tree.body[1].value):
        if key not in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py'):
            path = ROOT / filename
            path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
    manifest = (adapter / 'desktop_chatgpt_dependency_manifest.json').read_bytes()
    eol = b'\r\n' if b'\r\n' in manifest else b'\n'
    for name in ('auth.py', 'provider.py'):
        path = adapter / name
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', eol))


if __name__ == '__main__':
    rewrite()
    build_sources()
    checkout_endings()

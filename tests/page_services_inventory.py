"""AST-only R1 inventory; run as a module to regenerate the reviewed fixture."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/page_services_inventory.json'


def tree(path):
    return ast.parse((ROOT / path).read_text(encoding='utf-8-sig'), feature_version=(3, 11))


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + '.' + node.attr
    return ''


def callback_reads(path):
    result = []
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Call) and dotted(node.func) == 'HostMethod':
            result.append((node.args[0].value, 'HostMethod'))
        if isinstance(node, ast.Subscript) and dotted(node.value).endswith('.callbacks'):
            if isinstance(node.ctx, ast.Load) and isinstance(node.slice, ast.Constant):
                result.append((node.slice.value, 'callbacks'))
    return sorted(set(result))


def registrations():
    result = []
    for node in ast.walk(tree('desktop_pages/mount.py')):
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if isinstance(target, ast.Subscript) and dotted(target.value) == 'host.callbacks':
            result.append({'name': target.slice.value, 'target': dotted(node.value.body.func), 'origin': 'mount', 'variadic': True})
    method = next(n for n in ast.walk(tree('desktop_ui.py')) if isinstance(n, ast.FunctionDef) and n.name == 'page_services')
    services = next(n.value for n in method.body if isinstance(n, ast.Return))
    for key, value in zip(services.keys, services.values):
        call = isinstance(value, ast.Lambda)
        result.append({'name': key.value, 'target': dotted(value.body.func if call else value), 'origin': 'page_services', 'variadic': call})
    return result


def aliases_and_copies():
    aliases, copies = [], []
    for node in ast.walk(tree('desktop_pages/mount.py')):
        if not isinstance(node, ast.Assign):
            continue
        left, right = dotted(node.targets[0]), dotted(node.value)
        if left.startswith('shell.') and right.startswith('shell.'):
            parts = right.split('.')
            aliases.append({'name': left.split('.')[1], 'page': parts[1], 'attribute': '.'.join(parts[2:])})
        if left.startswith('host.state.') and right.startswith('shell.'):
            copies.append({'name': left.split('.')[2], 'source': right})
    owners = {a['name']: a['page'] for a in aliases}
    # These controls are created through SharedStateBindings, without a shell
    # alias assignment; ownership follows compare.py / settings_layout.py.
    owners.update(chatgpt_panel='settings_page', chatgpt_controller='settings_page', select_button='compare_page')
    for copy in copies:
        copy['page'] = owners.get(copy['source'].split('.')[1], 'shell')
    return aliases, copies


def patch_points(names, module_targets):
    """Include literal patches, setattr, and assignments, retaining receiver evidence.

    Attribute assignments are conservative: page/helper receivers with a matching
    name are included too. Dynamic loop names are expanded from their literal
    loop iterable; the receiver expression is retained for review.
    """
    result = []
    for path in sorted((ROOT / 'tests').glob('*.py')):
        if path.name == 'page_services_inventory.py':
            continue
        relative = path.relative_to(ROOT).as_posix()
        parsed = tree(relative)
        parents = {child: parent for parent in ast.walk(parsed) for child in ast.iter_child_nodes(parent)}

        def add(node, name, kind, receiver):
            if name in names or name in module_targets:
                result.append({'file': relative, 'line': node.lineno, 'name': name, 'kind': kind, 'receiver': receiver})

        def expanded(node, expression):
            if isinstance(expression, ast.Constant):
                return [expression.value]
            scope = node
            while scope in parents:
                scope = parents[scope]
                if isinstance(scope, ast.For) and dotted(scope.target) == dotted(expression):
                    return sorted({n.value for n in ast.walk(scope.iter) if isinstance(n, ast.Constant) and isinstance(n.value, str)})
            return []

        for node in ast.walk(parsed):
            if isinstance(node, ast.Call):
                func = dotted(node.func)
                if func.endswith('patch.object') and len(node.args) >= 2:
                    receiver, name = node.args[:2]
                    for value in expanded(node, name):
                        add(node, value, 'patch.object', dotted(receiver))
                elif func.endswith('patch') and node.args and isinstance(node.args[0], ast.Constant):
                    target = node.args[0].value
                    if isinstance(target, str) and target.startswith('desktop_ui.'):
                        add(node, target.split('.')[1], 'patch', 'desktop_ui')
                elif func == 'setattr' and len(node.args) >= 2:
                    for value in expanded(node, node.args[1]):
                        add(node, value, 'setattr', dotted(node.args[0]))
                elif func.endswith('patch.dict') and node.args and dotted(node.args[0]).endswith('.callbacks'):
                    for keyword in node.keywords:
                        add(node, keyword.arg, 'patch.dict', dotted(node.args[0]))
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    if isinstance(target, ast.Attribute):
                        add(node, target.attr, 'assignment', dotted(target.value))
                    elif isinstance(target, ast.Subscript) and dotted(target.value).endswith('.callbacks') and isinstance(target.slice, ast.Constant):
                        add(node, target.slice.value, 'callback assignment', dotted(target.value))
    return sorted(result, key=lambda p: (p['file'], p['line'], p['name'], p['kind']))


def inventory():
    services = registrations()
    aliases, copies = aliases_and_copies()
    consumers = {}
    for path in sorted((ROOT / 'desktop_pages').glob('*.py')):
        relative = path.relative_to(ROOT).as_posix()
        for name, kind in callback_reads(relative):
            consumers.setdefault(name, []).append({'module': relative, 'kind': kind})
    patches = patch_points({s['name'] for s in services} | {a['name'] for a in aliases}, {s['target'] for s in services if s['origin'] == 'page_services'})
    patched = {p['name'] for p in patches}
    for service in services:
        service['consumers'] = consumers.get(service['name'], [])
        service['patch_sensitive'] = service['name'] in patched or service['target'] in patched
    for alias in aliases:
        alias['patch_sensitive'] = alias['name'] in patched
    return {'services': services, 'aliases': aliases, 'state_copies': copies, 'patch_points': patches}


def reviewed_inventory(base, delta):
    """Apply exact additive test-observer changes without replacing the historical fixture."""
    result = json.loads(json.dumps(base))
    assert delta['services'] == delta['state_copies'] == {'removed': [], 'added': []}
    before, after = delta['aliases']['removed'], delta['aliases']['added']
    assert len(before) == len(after) == 2
    for old, new in zip(before, after):
        assert old['count'] == new['count'] == 1
        assert old['row']['patch_sensitive'] is False and new['row']['patch_sensitive'] is True
        assert {k: v for k, v in old['row'].items() if k != 'patch_sensitive'} == {k: v for k, v in new['row'].items() if k != 'patch_sensitive'}
        result['aliases'][result['aliases'].index(old['row'])] = new['row']
    for item in delta['patch_points']['removed']:
        for _ in range(item['count']):
            result['patch_points'].remove(item['row'])
    for item in delta['patch_points']['added']:
        result['patch_points'].extend([item['row']] * item['count'])
    result['patch_points'].sort(key=lambda p: (p['file'], p['line'], p['name'], p['kind']))
    return result


if __name__ == '__main__':
    FIXTURE.write_text(json.dumps(inventory(), indent=2) + '\n', encoding='utf-8')

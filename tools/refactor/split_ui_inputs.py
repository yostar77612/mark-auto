"""Remove real IO from formatting and inject its true boundary into walk-forward."""

from __future__ import annotations

# Historical pass: never overwrite the applied split or its subsequent repairs.
from pathlib import Path as _AppliedPath

if __name__ == '__main__' and (_AppliedPath(__file__).resolve().parents[2] / 'desktop_app/shell/window.py').is_file():
    print('split_ui_inputs.py: already applied')
    raise SystemExit(0)


import argparse
import ast
import json
from pathlib import Path

from tools.refactor.split_ui_modules import read_source
from tools.refactor.split_ui_modules import used_imports, original_fragment


def formatting_output(source):
    tree = ast.parse(source)
    removed = {'research_controls', '_dataset'}
    nodes = [
        node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom)) and not (isinstance(node, ast.FunctionDef) and node.name in removed)
    ]
    names = {node.id for parent in nodes for node in ast.walk(parent) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    imports = used_imports([node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))], names)
    # Preserve each actual display definition exactly; no IO compatibility export.
    doc = nodes.pop(0) if isinstance(nodes[0], ast.Expr) and isinstance(nodes[0].value, ast.Constant) and isinstance(nodes[0].value.value, str) else None
    return (
        (original_fragment(source, doc) + '\n' if doc is not None else '')
        + '\n'.join(imports)
        + '\n\n'
        + '\n\n'.join(original_fragment(source, node) for node in nodes)
        + '\n'
    )


def walk_forward_output(source):
    """Make only the agreed mandatory keyword-port edits in D's old source."""
    source = source.replace(
        'def preview_walk_forward(data, plan_payload, paths, saved_source=None):',
        'def preview_walk_forward(data, plan_payload, paths, saved_source=None, *, inputs):',
    )
    source = source.replace(
        'def execute_walk_forward(operation, payload, paths, *, descendants_stopped=False):',
        'def execute_walk_forward(operation, payload, paths, *, descendants_stopped=False, inputs):',
    )
    source = source.replace('    from desktop_app.components.formatting import research_controls\n', '')
    source = source.replace('    from desktop_app.components.formatting import _dataset, research_controls\n', '')
    source = source.replace('research_controls(paths)', 'inputs.research_controls(paths)').replace(
        '_dataset(Path(paths.state), {})', 'inputs._dataset(Path(paths.state), {})'
    )
    source = source.replace(
        "preview_walk_forward(data, payload['plan'], paths, payload.get('saved_source'))",
        "preview_walk_forward(data, payload['plan'], paths, payload.get('saved_source'), inputs=inputs)",
    )
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    root, output = args.source_root.resolve(), args.output_root.resolve()
    if root == output:
        parser.error('Preparation cannot overwrite product sources')
    outputs = {
        'desktop_app/components/formatting.py': formatting_output(read_source(root, 'desktop_presentation.py')),
        'desktop_app/features/walk_forward/presenter.py': walk_forward_output(read_source(root, 'desktop_walk_forward.py')),
    }
    for name, source in outputs.items():
        ast.parse(source)
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8', newline='\n')
    print(
        json.dumps(
            {
                'real_original_io_definitions_removed': ['research_controls', '_dataset'],
                'required_input_port_added_to': ['preview_walk_forward', 'execute_walk_forward'],
            }
        )
    )


if __name__ == '__main__':
    main()


def legacy_owner_name(name):
    """Project only module selectors in the immutable pre-registry oracle."""
    from tools.refactor.split_ui_modules import dotted

    mapping = json.loads((Path(__file__).resolve().parents[2] / 'tools/layer_relocations.json').read_text(encoding='utf-8'))
    for old, new in sorted(mapping.items(), key=lambda item: len(item[1]), reverse=True):
        current = dotted(new)
        if name.startswith(current + '.'):
            return dotted(old) + name[len(current) :]
    return name


def legacy_walk_forward_inputs(source):
    """Supply the required port to historical calls, retaining all fixture code."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'execute_walk_forward']
    for call in sorted(calls, key=lambda node: node.lineno, reverse=True):
        call.keywords.append(ast.keyword(arg='inputs', value=ast.parse('_layered_inputs', mode='eval').body))
        # The fixture call is a single returned statement.
        statement = ' ' * (call.col_offset - len('return ')) + 'return ' + ast.unparse(ast.fix_missing_locations(call)) + '\n'
        lines[call.lineno - 1 : call.end_lineno] = [statement]
    # Its own research_controls and _dataset remain the golden implementations.
    return 'from desktop_app.bootstrap import create_operation_ports as _create_ports\n_layered_inputs = _create_ports().inputs\n' + ''.join(lines)

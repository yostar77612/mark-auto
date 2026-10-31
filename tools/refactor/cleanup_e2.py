"""Replay T5-E2's mechanical private-call and archive-reference updates."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path, old, new):
    target = ROOT / path
    source = target.read_text(encoding='utf-8')
    if old == 'import unittest\n' and new in source:
        return
    if old in source:
        target.write_text(source.replace(old, new), encoding='utf-8', newline='\n')


def cleanup():
    replace('desktop_app/components/result_widgets.py', "key.endswith(('_id', '_hash')) and value is not None", "key.endswith(('_id', '_hash'))")
    replace('desktop_app/components/charts.py', "getattr(self, '_marker_index', {})", 'self._marker_index')
    replace('desktop_app/components/chart_geometry.py', "getattr(self, '_marker_index', {})", 'self._marker_index')
    replace('desktop_app/components/chart_geometry.py', 'def _prepare_chart_geometry(self, p, fm,', 'def _prepare_chart_geometry(self, fm,')
    replace('desktop_app/components/charts.py', '_prepare_chart_geometry(self, p, fm,', '_prepare_chart_geometry(self, fm,')
    path = 'quantlab/research_core/application/paper_operations.py'
    replace(
        path,
        'def _prepare_paper_operation(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):',
        'def _prepare_paper_operation(ports: UiOperationPorts, payload, root):',
    )
    replace(path, '_prepare_paper_operation(ports, payload, paths, root)', '_prepare_paper_operation(ports, payload, root)')
    # These are the split owners of the inventoried desktop_ui AppPaths uses.
    for path in (
        'quantlab/research_core/application/ui_operations/idea.py',
        'quantlab/research_core/application/ui_operations/assistant.py',
        'quantlab/research_core/application/analysis_operations.py',
    ):
        replace(path, "getattr(paths, 'bootstrap', None) or paths.root", 'paths.bootstrap or paths.root')


def references():
    for path in ('tests/test_docs_layering.py',):
        replace(path, ", ROOT / 'archives/legacy_autotrading/README.md'", '')
    replace('.gitignore', 'archives/legacy_autotrading/trader/scripts/*\n!archives/legacy_autotrading/trader/scripts/README.md\n', '')
    replace(
        '.github/workflows/quantlab.yml',
        'archives/legacy_autotrading/requirements.txt is outside this audit',
        'Historical legacy dependencies (removed in PR E) are outside this audit',
    )
    replace(
        'tests/test_application_icon.py', "archived = ROOT / 'archives/legacy_autotrading/requirements.txt'", "archived = historical_bytes('requirements.txt')"
    )
    replace('tests/test_application_icon.py', "canonical = archived.read_bytes().replace", 'canonical = archived.replace')
    replace(
        'tests/test_application_icon.py',
        'archives/legacy_autotrading/requirements.txt is outside this audit',
        'Historical legacy dependencies (removed in PR E) are outside this audit',
    )
    replace('tests/test_packaging.py', "(ROOT / 'archives/legacy_autotrading/requirements.txt').read_text()", "historical_text('requirements.txt')")
    for path, name in (('tests/test_application_icon.py', 'historical_bytes'), ('tests/test_packaging.py', 'historical_text')):
        replace(path, 'import unittest\n', f'import unittest\n\nfrom legacy_history import {name}\n')
    path = 'tests/test_legacy_security.py'
    replace(path, 'import unittest\n', 'import unittest\n\nfrom legacy_history import historical_text, historical_python_paths\n')
    replace(path, "(ROOT / path).read_text(encoding='utf-8')", 'historical_text(path)')
    for name in ('bot', 'file', 'database/redis'):
        replace(
            path,
            f"(ROOT / 'archives/legacy_autotrading/trader/utils/{name}.py').read_text(encoding='utf-8')",
            f"historical_text('archives/legacy_autotrading/trader/utils/{name}.py')",
        )
    replace(path, "ROOT.joinpath('archives/legacy_autotrading/trader').rglob('*.py')", 'historical_python_paths()')
    replace(path, "path.read_text(encoding='utf-8')", 'historical_text(path)')


if __name__ == '__main__':
    cleanup()
    references()

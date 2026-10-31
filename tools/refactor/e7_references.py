"""Replay the exact T5-E7 owner-reference and fixture-interface corrections."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDITS = {
    '.github/workflows/quantlab.yml': [
        ('from desktop import _auth_smoke_dependencies', 'from desktop_app.smoke.auth import _auth_smoke_dependencies'),
    ],
    'desktop.py': [
        (
            'import sys\n\nfrom desktop_app.smoke.fixtures import _SmokeSettingsView',
            'import sys\nimport desktop_app.smoke  # Static package edge for the frozen entry point.\nfrom desktop_app.smoke.fixtures import _SmokeSettingsView',
        ),
    ],
    'tools/refactor/split_ui_inputs.py': [
        (
            '    tree = ast.parse(source)\n    lines = source.splitlines(keepends=True)\n    calls =',
            "    # The immutable oracle keeps its history call; compose its relocated storage port.\n    source = source.replace(\n        'from quantlab.market_history import import_history, session_from_dict',\n        'from desktop_app.research_bootstrap import create_history_service\\n'\n        '        _history_service = create_history_service()\\n'\n        '        import_history, session_from_dict = _history_service.import_history, _history_service.session_from_dict',\n    )\n    tree = ast.parse(source)\n    lines = source.splitlines(keepends=True)\n    calls =",
        )
    ],
    'tests/test_restart_availability_contract.py': [
        ('from quantlab.research_core.adapters.workspace_backup import WorkspaceJobStorage\n', ''),
        ("return _job_worker(*args, **dict(kwargs, storage_port=kwargs.get('storage_port') or WorkspaceJobStorage()))", 'return _job_worker(*args, **kwargs)'),
    ],
    'tests/test_import_graph.py': [
        (
            "sorted((ROOT / 'quantlab').glob('*.py'))",
            "sorted((ROOT / 'quantlab').glob('*.py'))\n        + sorted((ROOT / 'quantlab/research_core').rglob('*.py'))\n        + sorted((ROOT / 'quantlab/shared').rglob('*.py'))",
        ),
    ],
    'tests/page_services_inventory.py': [
        ('    import hashlib\n', '    # Hash only the reviewed relocation table when projecting its observer identities.\n    import hashlib\n'),
    ],
    'tests/test_desktop_ui.py': [
        (
            '        self.window.jobs = SlowErrorExit()\n',
            '        self.window.jobs = SlowErrorExit()\n        self.window.jobs.event_log = original.event_log\n',
        ),
    ],
}


def main():
    for name, edits in EDITS.items():
        path = ROOT / name
        source = path.read_text(encoding='utf-8-sig')
        for old, new in edits:
            if new and new in source:
                continue
            if not new and old not in source:
                continue
            assert old in source, name
            source = source.replace(old, new)
        path.write_text(source, encoding='utf-8')
    print(f'{len(EDITS)} exact T5-E7 reference files verified')


if __name__ == '__main__':
    main()

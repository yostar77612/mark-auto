"""Pinned historical adapter source bytes; current sources have separate tests."""

import gzip
import hashlib
from pathlib import Path

HASHES = {
    'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
    'desktop_chatgpt_provider.py': 'f17a71953af43bc6e9a0239bcd74bf1ed3da74bbd826153f9d76f70bc1023899',
}
NORMALIZATIONS = {
    'quantlab/assistant/adapters/chatgpt/provider.py': [
        (
            'from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference, official_tls_context',
            'from desktop_chatgpt_auth import OAuthCredentialReference, official_tls_context',
        ),
        ("raw=(root/{'desktop_chatgpt_auth.py':'auth.py','desktop_chatgpt_provider.py':'provider.py'}[name]).read_bytes()", 'raw=(root/name).read_bytes()'),
    ]
}
CURRENT_PATHS = {
    'desktop_accessibility.py': 'desktop_app/shell/accessibility.py',
    'desktop_automatic_backup.py': 'desktop_app/features/settings/automatic_backup.py',
    'desktop_capital_scenario.py': 'desktop_app/features/capital_scenario/worker.py',
    'desktop_chart_memory.py': 'desktop_app/features/market/chart_memory.py',
    'desktop_chart_popout.py': 'desktop_app/features/market/chart_popout.py',
    'desktop_charts.py': 'desktop_app/components/charts.py',
    'desktop_chatgpt_auth.py': 'quantlab/assistant/adapters/chatgpt/auth.py',
    'desktop_chatgpt_provider.py': 'quantlab/assistant/adapters/chatgpt/provider.py',
    'desktop_chatgpt_states.py': 'desktop_app/features/assistant/states.py',
    'desktop_chatgpt_ui.py': 'desktop_app/features/assistant/connection.py',
    'desktop_expiry_inputs.py': 'desktop_app/components/expiry_inputs.py',
    'desktop_forms.py': 'desktop_app/components/forms.py',
    'desktop_help.py': 'desktop_app/components/help.py',
    'desktop_icon.py': 'desktop_app/components/icon.py',
    'desktop_market.py': 'desktop_app/features/market/dashboard.py',
    'desktop_market_layout.py': 'quantlab/research_core/adapters/market_layout.py',
    'desktop_market_workspace.py': 'desktop_app/features/market/workspace.py',
    'desktop_order_lines.py': 'desktop_app/features/paper/order_lines.py',
    'desktop_pages/__init__.py': 'desktop_app/shell/pages.py',
    'desktop_pages/app_header.py': 'desktop_app/shell/app_header.py',
    'desktop_pages/assistant.py': 'desktop_app/features/assistant/assistant.py',
    'desktop_pages/assistant_completion.py': 'desktop_app/features/assistant/assistant_completion.py',
    'desktop_pages/assistant_details.py': 'desktop_app/features/assistant/assistant_details.py',
    'desktop_pages/assistant_manifest.py': 'desktop_app/features/assistant/assistant_manifest.py',
    'desktop_pages/assistant_models.py': 'desktop_app/features/assistant/assistant_models.py',
    'desktop_pages/assistant_permissions.py': 'desktop_app/features/assistant/assistant_permissions.py',
    'desktop_pages/assistant_runtime.py': 'desktop_app/features/assistant/worker.py',
    'desktop_pages/async_status.py': 'desktop_app/components/async_status.py',
    'desktop_pages/backtest.py': 'desktop_app/features/backtest/backtest.py',
    'desktop_pages/backtest_summary_card.py': 'desktop_app/features/backtest/backtest_summary_card.py',
    'desktop_pages/backup_inspection.py': 'desktop_app/features/settings/backup_inspection.py',
    'desktop_pages/bindings.py': 'desktop_app/shell/bindings.py',
    'desktop_pages/chatgpt_reconciliation.py': 'desktop_app/features/assistant/chatgpt_reconciliation.py',
    'desktop_pages/command_palette.py': 'desktop_app/components/command_palette.py',
    'desktop_pages/compare.py': 'desktop_app/features/compare/compare.py',
    'desktop_pages/compare_equity.py': 'desktop_app/features/compare/compare_equity.py',
    'desktop_pages/compare_table.py': 'desktop_app/features/compare/compare_table.py',
    'desktop_pages/connection_test.py': 'desktop_app/features/assistant/connection_test.py',
    'desktop_pages/data.py': 'desktop_app/features/data/data.py',
    'desktop_pages/data_gaps.py': 'desktop_app/features/data/data_gaps.py',
    'desktop_pages/design.py': 'desktop_app/components/design.py',
    'desktop_pages/diagnostics.py': 'desktop_app/features/settings/diagnostics.py',
    'desktop_pages/download_import.py': 'desktop_app/features/data/download_import.py',
    'desktop_pages/equity.py': 'desktop_app/components/equity.py',
    'desktop_pages/error_guidance.py': 'desktop_app/components/error_guidance.py',
    'desktop_pages/host.py': 'desktop_app/shell/host.py',
    'desktop_pages/idea_research.py': 'desktop_app/features/strategy/idea_research.py',
    'desktop_pages/job_progress.py': 'desktop_app/components/job_progress.py',
    'desktop_pages/log_table.py': 'desktop_app/features/settings/log_table.py',
    'desktop_pages/maintenance.py': 'desktop_app/features/settings/maintenance.py',
    'desktop_pages/market.py': 'desktop_app/features/market/market.py',
    'desktop_pages/mount.py': 'desktop_app/shell/mount.py',
    'desktop_pages/notification_log.py': 'desktop_app/shell/notification_log.py',
    'desktop_pages/notifications.py': 'desktop_app/shell/notifications.py',
    'desktop_pages/onboarding.py': 'desktop_app/shell/onboarding.py',
    'desktop_pages/palette_commands.py': 'desktop_app/shell/palette_commands.py',
    'desktop_pages/paper.py': 'desktop_app/features/paper/paper.py',
    'desktop_pages/paper_layout.py': 'desktop_app/features/paper/paper_layout.py',
    'desktop_pages/paper_readiness.py': 'desktop_app/features/paper/paper_readiness.py',
    'desktop_pages/paper_tabs.py': 'desktop_app/features/paper/paper_tabs.py',
    'desktop_pages/preferences.py': 'desktop_app/features/settings/preferences.py',
    'desktop_pages/quick_start.py': 'desktop_app/features/onboarding/quick_start.py',
    'desktop_pages/quick_start_chain.py': 'desktop_app/features/onboarding/quick_start_chain.py',
    'desktop_pages/redesign_strategy_layout.py': 'desktop_app/features/strategy/redesign_strategy_layout.py',
    'desktop_pages/replay_controls.py': 'desktop_app/features/paper/replay_controls.py',
    'desktop_pages/result_layers.py': 'desktop_app/components/result_layers.py',
    'desktop_pages/result_panels.py': 'desktop_app/components/result_panels.py',
    'desktop_pages/result_widgets.py': 'desktop_app/components/result_widgets.py',
    'desktop_pages/settings.py': 'desktop_app/features/settings/settings.py',
    'desktop_pages/settings_layout.py': 'desktop_app/features/settings/settings_layout.py',
    'desktop_pages/shortcuts.py': 'desktop_app/shell/shortcuts.py',
    'desktop_pages/strategy.py': 'desktop_app/features/strategy/strategy.py',
    'desktop_pages/strategy_tabs.py': 'desktop_app/features/strategy/strategy_tabs.py',
    'desktop_pages/views.py': 'desktop_app/shell/views.py',
    'desktop_pages/wf_wizard.py': 'desktop_app/features/walk_forward/wf_wizard.py',
    'desktop_pages/widgets.py': 'desktop_app/components/widgets.py',
    'desktop_presentation.py': 'desktop_app/components/formatting.py',
    'desktop_privacy.py': 'desktop_app/components/privacy.py',
    'desktop_recovery_smoke.py': 'desktop_app/smoke/recovery.py',
    'desktop_research_runtime.py': 'desktop_app/research_bootstrap.py',
    'desktop_smoke/__init__.py': 'desktop_app/smoke/__init__.py',
    'desktop_strings.py': 'desktop_app/strings/catalog.py',
    'desktop_theme.py': 'desktop_app/shell/theme.py',
    'desktop_timeinput.py': 'desktop_app/components/timeinput.py',
    'desktop_tls_smoke.py': 'desktop_app/smoke/tls.py',
    'desktop_trading/__init__.py': 'desktop_app/features/trading/__init__.py',
    'desktop_trading/broker_panel.py': 'desktop_app/features/trading/broker_panel.py',
    'desktop_trading/dashboard.py': 'desktop_app/features/trading/dashboard.py',
    'desktop_trading/dashboard_rows.py': 'desktop_app/features/trading/dashboard_rows.py',
    'desktop_trading/labels.py': 'desktop_app/features/trading/labels.py',
    'desktop_trading/market_watch.py': 'desktop_app/features/trading/market_watch.py',
    'desktop_trading/market_watch_rows.py': 'desktop_app/features/trading/market_watch_rows.py',
    'desktop_trading/reconciliation_rows.py': 'desktop_app/features/trading/reconciliation_rows.py',
    'desktop_trading/rendering.py': 'desktop_app/features/trading/rendering.py',
    'desktop_trading/research_panel.py': 'desktop_app/features/trading/research_panel.py',
    'desktop_trading/widgets.py': 'desktop_app/features/trading/widgets.py',
    'desktop_trading/window.py': 'desktop_app/features/trading/window.py',
    'desktop_trading/wizard.py': 'desktop_app/features/trading/wizard.py',
    'desktop_trading/workspaces.py': 'desktop_app/features/trading/workspaces.py',
    'desktop_ui.py': 'desktop_app/shell/main_window.py',
    'desktop_ui_polish.py': 'desktop_app/shell/polish.py',
    'desktop_walk_forward.py': 'desktop_app/features/walk_forward/presenter.py',
}


def physical_path(relative: str) -> str:
    return CURRENT_PATHS.get(relative, relative)


def reviewed_source_bytes(root: Path, name: str) -> bytes:
    if name not in HASHES:
        return (root / name).read_bytes()
    path = Path(__file__).resolve().parent / 'fixtures' / 'layered_paths' / (name + '.gz')
    raw = gzip.decompress(path.read_bytes())
    if hashlib.sha256(raw).hexdigest() != HASHES[name]:
        raise ValueError('Historical adapter source fixture changed')
    return raw


def original_adapter_text(path: str, source: str) -> str:
    for current, original in NORMALIZATIONS[path]:
        if source.count(current) != 1:
            raise ValueError('Reviewed mechanical source rewrite changed')
        source = source.replace(current, original, 1)
    return source


def page_sources(root: Path):
    """Original page ownership projected to current paths, plus new desktop sources."""
    moved = set(CURRENT_PATHS.values())
    projected = {new for old, new in CURRENT_PATHS.items() if old.startswith('desktop_pages/')}
    additions = {path.relative_to(root).as_posix() for path in (root / 'desktop_app').rglob('*.py')} - moved
    # Only the two real assembly roots are excluded; every presenter stays scanned.
    for name in ('desktop_app/bootstrap.py', 'desktop_app/shell/main_window.py'):
        if (root / name).is_file():
            import json

            mapping = json.loads((root / 'tools/layer_map.json').read_text(encoding='utf-8'))
            assert mapping['overrides'][name] == 'composition'
            additions.discard(name)
    window = root / 'desktop_app/shell/window.py'
    if window.is_file():
        import ast

        classes = [node.name for node in ast.parse(window.read_text(encoding='utf-8')).body if isinstance(node, ast.ClassDef)]
        assert classes == ['MainWindow']
        additions.discard('desktop_app/shell/window.py')
    return [root / name for name in sorted(projected | additions)]


def historical_ui_environment():
    """Preserve committed golden source identities while resolving their old imports.

    This context is used only by the historical registry comparison. Runtime
    provenance separately reads and verifies the actual relocated raw sources.
    No original fixture bytes, source hashes or producer profiles are changed.
    """
    import builtins
    from contextlib import contextmanager, nullcontext
    import importlib
    from unittest.mock import patch

    if getattr(Path.read_text, '_layered_historical_projection', False):
        return nullcontext()

    @contextmanager
    def environment():
        root = Path(__file__).resolve().parents[1]
        modules = {
            old.removesuffix('.py').replace('/', '.').removesuffix('.__init__'): new.removesuffix('.py').replace('/', '.').removesuffix('.__init__')
            for old, new in CURRENT_PATHS.items()
        }
        source_keys = {root / name: name for name in HASHES}
        source_keys.update({root / CURRENT_PATHS[name]: name for name in HASHES})
        original_import, original_read, original_text = builtins.__import__, Path.read_bytes, Path.read_text

        def projected_import(name, globals=None, locals=None, fromlist=(), level=0):
            if not level and name in modules:
                if not fromlist and '.' in name:
                    raise ValueError('Historical dotted import binding requires explicit review')
                return importlib.import_module(modules[name])
            return original_import(name, globals, locals, fromlist, level)

        def source_bytes(path):
            name = source_keys.get(path)
            if name is not None:
                return reviewed_source_bytes(root, name)
            if path == root / 'desktop_chatgpt_dependency_manifest.json':
                return original_read(root / 'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json')
            return original_read(path)

        def source_text(path, *args, **kwargs):
            source = original_text(path, *args, **kwargs)
            return original_pool_text(source) if path == root / 'quantlab/saved_candidate_pool.py' else source

        source_text._layered_historical_projection = True
        with patch('builtins.__import__', projected_import), patch.object(Path, 'read_bytes', source_bytes), patch.object(Path, 'read_text', source_text):
            yield

    return environment()


def original_pool_text(source: str) -> str:
    """Undo only the reviewed additional producer literal and exact tuple entry."""
    import ast
    from quantlab.core import content_hash

    marker = '\n# Reviewed mechanical-path producer; all earlier literal blocks remain exact.\n'
    tail = 'ATOMIC_REPLACE_TRANSPORT_PROFILE_V1, ATOMIC_REPLACE_SIWC_PROFILE_V1, LAYERED_PATHS_SIWC_PROFILE_V1)'
    if source.count(marker) != 1 or source.count(tail) != 1:
        raise ValueError('Reviewed producer insertion changed')
    start = source.index(marker)
    stop = source.index('SUPPORTED_PRODUCERS = (', start)
    block = ast.parse(source[start:stop]).body
    if (
        len(block) != 1
        or not isinstance(block[0], ast.Assign)
        or not isinstance(block[0].targets[0], ast.Name)
        or block[0].targets[0].id != 'LAYERED_PATHS_SIWC_PROFILE_V1'
    ):
        raise ValueError('Unexpected source in the reviewed producer insertion')
    inserted = ast.get_source_segment(source[start:stop], block[0])
    if hashlib.sha256(inserted.encode('utf-8')).hexdigest() != '1bd303b3dacfa0c6abab813b238863dd6561ae5a8b92610d10cef021b4782ac7':
        raise ValueError('Exact reviewed new producer literal changed')
    restored = source[:start] + source[stop:]
    restored = restored.replace(tail, 'ATOMIC_REPLACE_TRANSPORT_PROFILE_V1, ATOMIC_REPLACE_SIWC_PROFILE_V1)', 1)
    if content_hash(restored) != 'a98cf010989dbba963c5b5236553db94bcd809a298b3c94494307bc9f80e2b4f':
        raise ValueError('Historical saved-pool source outside the added literal changed')
    return restored


def project_page_service_lines(result):
    """Apply only the pinned line-location delta to all original patch identities."""
    import json

    path = Path(__file__).parent / 'fixtures/layered_paths/page_service_line_relocations.json'
    table = json.loads(path.read_text(encoding='utf-8'))
    canonical = json.dumps(table, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if hashlib.sha256(canonical).hexdigest() != '04890b66fff9e9090edeb92541bb13f0a084c1e70d8d572da28d3cfdab86b859':
        raise ValueError('Reviewed mechanical line-location table changed')
    if len(result['patch_points']) != table['patch_points']:
        raise ValueError('Historical patch inventory size changed')
    rows = {tuple(sorted(row['original'].items())): row['current_line'] for row in table['line_relocations']}
    used = set()
    for point in result['patch_points']:
        key = tuple(sorted(point.items()))
        if key in rows:
            used.add(key)
            point['line'] = rows[key]
    if used != rows.keys():
        raise ValueError('A historical patch identity was removed or changed')
    result['patch_points'].sort(key=lambda point: (point['file'], point['line'], point['name'], point['kind']))
    return _project_slice2_service_refs(result)


def mechanically_restored_source(root: Path, logical: str, baseline: bytes) -> bytes:
    """Read actual current bytes and undo only the reviewed B mechanical adapters."""
    current = (root / physical_path(logical)).read_bytes()
    if logical == 'desktop_chatgpt_provider.py':
        return original_adapter_text(physical_path(logical), current.decode('utf-8')).encode('utf-8')
    if logical == 'quantlab/saved_candidate_pool.py':
        text = original_pool_text(current.decode('utf-8').replace('\r\n', '\n'))
        canonical = baseline.replace(b'\r\n', b'\n')
        eol = b'\r\n' if b'\r\n' in baseline else b'\n'
        if b'\r' in canonical or canonical.replace(b'\n', eol) != baseline:
            raise ValueError('Unknown historical checkout line-ending policy')
        return text.encode('utf-8').replace(b'\n', eol)
    return current


_SLICE2_PATCH_SHA = '00143849c2fd1ff59147d2f790fdbe09b8db4cc2bf8da5aed8a2c2245a8d9c22'


def _project_slice2_service_refs(result):
    """Project reviewed observer locations; every historical observer is retained."""
    import json

    path = Path(__file__).parent / 'fixtures/layered_paths/slice2_service_relocations.json'
    table = json.loads(path.read_text(encoding='utf-8'))
    canonical = json.dumps(table, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if hashlib.sha256(canonical).hexdigest() != _SLICE2_PATCH_SHA:
        raise ValueError('Reviewed slice 2 observer table changed')
    assert len(result['patch_points']) == table['original_observers'] == 174
    service = next(row for row in result['services'] if row['name'] == '_paper')
    assert service['patch_sensitive'] is False
    service['patch_sensitive'] = True
    for row in table['relocations']:
        original, current = row['original'], row['current']
        assert (original['file'], original['name']) == (current['file'], current['name'])
        index = result['patch_points'].index(original)
        result['patch_points'][index] = dict(current)
    additions = table['newly_discovered_existing_observers']
    assert [(point['file'], point['name'], point['receiver']) for point in additions] == [
        ('tests/test_compare_equity_f2.py', 'load_result', 'quantlab.reporting'),
        ('tests/test_workspace_wal_guard.py', '_paper', 'paper_operations'),
    ]
    result['patch_points'].extend(additions)
    result['patch_points'].sort(key=lambda point: (point['file'], point['line'], point['name'], point['kind']))
    return result

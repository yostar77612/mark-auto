"""Filesystem boundaries used by the desktop research use cases."""

from pathlib import Path
import json
import hashlib
from quantlab.core import Dataset, ValidationError, content_hash, canonical_json
from quantlab.reporting import read_json, load_dataset
from quantlab.windows_paths import canonical_path as _canonical_path, native_path as _native_path, sqlite_uri as _sqlite_uri


class WorkerRepository:
    def __init__(self, text, source_root):
        self.text = text
        self.source_root = source_root

    def implementation_sources(self):
        source_root = self.source_root
        source_files = (
            'desktop_chatgpt_auth.py',
            'desktop_chatgpt_provider.py',
            'quantlab/core.py',
            'quantlab/backtest.py',
            'quantlab/research.py',
            'quantlab/strategies.py',
            'desktop_chatgpt_dependency_manifest.json',
        )
        sources = {
            name: hashlib.sha256(
                (
                    source_root
                    / {
                        'desktop_chatgpt_auth.py': 'quantlab/assistant/adapters/chatgpt/auth.py',
                        'desktop_chatgpt_provider.py': 'quantlab/assistant/adapters/chatgpt/provider.py',
                        'desktop_chatgpt_dependency_manifest.json': 'quantlab/assistant/adapters/chatgpt/desktop_chatgpt_dependency_manifest.json',
                    }.get(name, name)
                ).read_bytes()
            ).hexdigest()
            for name in source_files
        }
        return sources

    def research_controls(self, paths):
        """Irreversible budget/holdout ledgers must never be rolled back with user state."""
        state = Path(paths.state)
        legacy = list((state / 'provider_budgets').glob('*'))
        legacy.extend((state / 'campaigns').glob('.holdout_registry.sqlite3*'))
        if any((path.exists() and (not path.is_file() or path.stat().st_size > 0) for path in legacy)):
            raise ValidationError(self.text('ui.research_controls.legacy_budget_blocked'))
        controls = Path(paths.controls)
        if controls.resolve().is_relative_to(state.resolve()):
            raise ValidationError(self.text('ui.research_controls.irreversible_record_location'))
        return controls

    def _dataset(self, root, payload):
        data = load_dataset(Path(payload.get('dataset') or root / 'dataset.json'))
        start, end = (payload.get('start_date'), payload.get('end_date'))
        if start or end:
            if start and end and (start > end):
                raise ValidationError(self.text('ui.dataset.reversed_dates'))
            bars = tuple((b for b in data.bars if (not start or b.trade_date >= start) and (not end or b.trade_date <= end)))
            if not bars:
                raise ValidationError(self.text('ui.dataset.empty_date_range'))
            manifest = {
                **data.manifest,
                'parent_data_hash': data.manifest['data_hash'],
                'data_hash': content_hash(bars),
                'date_filter': {'start': start, 'end': end},
            }
            manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
            data = Dataset(bars, manifest, dict(data.quality))
        return data

    def candidate_state(self, root, reference):
        """Resolve a persisted, hash-bound DSL candidate and independent evaluation gate."""
        campaigns = _native_path(Path(root) / 'campaigns').resolve()
        folder = str(reference.get('campaign_folder', ''))
        if len(folder) != 64 or any((c not in '0123456789abcdef' for c in folder)):
            raise ValidationError(self.text('ui.candidate_record.invalid_version_id'))
        path = _native_path(campaigns / folder / 'campaign.json')
        if not _canonical_path(path.resolve()).is_relative_to(_canonical_path(campaigns)):
            raise ValidationError(self.text('ui.candidate_record.invalid_version_path'))
        state = read_json(path)
        import sqlite3
        from contextlib import closing

        journal = path.with_name('campaign.sqlite3')
        if not _canonical_path(journal.resolve()).is_relative_to(_canonical_path(campaigns)) or not journal.is_file():
            raise ValidationError(self.text('ui.candidate_record.transaction_missing'))
        with closing(sqlite3.connect(_sqlite_uri(journal.resolve()) + '?mode=ro', uri=True, timeout=1)) as database:
            row = database.execute('SELECT payload FROM state WHERE id=1').fetchone()
        if not row or canonical_json(json.loads(row[0])) != canonical_json(state):
            raise ValidationError(self.text('ui.candidate_record.export_transaction_mismatch'))
        return state

"""Existing market worker use cases; concrete dependencies arrive through ports."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts
from pathlib import Path
from datetime import datetime
from quantlab.core import ValidationError


def _handle_ui_market_refresh(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    if 'history_import' in payload:
        if payload.get('history_import') is not True or set(payload) != {'history_import', 'local_path', 'sessions', 'dated_policy_confirmed'}:
            raise ValidationError(ports.text('ui.execute_ui_operation.invalid_history_import_fields'))
        if payload.get('dated_policy_confirmed') is not True:
            raise ValidationError(ports.text('ui.execute_ui_operation.session_confirmation_required'))
        records = payload.get('sessions')
        if not isinstance(records, list) or not 1 <= len(records) <= 128:
            raise ValidationError(ports.text('ui.execute_ui_operation.session_count_limit'))
        if emit is not None:
            emit('progress', message=ports.text('ui.execute_ui_operation.importing_local_history'))
        result = ports.history.import_history(
            Path(payload['local_path']), root / 'market_history', sessions=tuple((ports.history.session_from_dict(row) for row in records))
        )
        return {
            'mode': 'local_unverified_history',
            'cache_id': result.cache_id,
            'source_hash': result.source_hash,
            'policy_hash': result.policy_hash,
            'counters': dict(result.counters),
            'warnings': list(result.warnings),
            'contracts': len(result.series),
            'bars': sum((len(x.bars) for x in result.series)),
        }
    local = payload.get('local_path')
    if not local and payload.get('network_opt_in') is not True:
        raise ValidationError(ports.text('ui.execute_ui_operation.market_consent_required'))
    providers = (payload.get('provider'),) if local else ('twse', 'taifex')
    outcomes = {}
    for provider in providers:
        if provider not in ('twse', 'taifex'):
            raise ValidationError(ports.text('ui.execute_ui_operation.unsupported_official_source'))
        try:
            kwargs = {}
            if local:
                raw = ports.files.official_source(Path(local), ports.market.MAX_BYTES, ports.text('ui.execute_ui_operation.official_file_too_large'))
                result = ports.market.import_daily(provider, root / 'market_cache', raw, format=payload.get('format', 'json'))
            else:
                result = ports.market.refresh_daily(provider, root / 'market_cache', network_enabled=True, **kwargs)
            outcomes[provider] = {
                'stale': result.stale,
                'error': result.error,
                'contracts': len(result.series),
                'bars': sum((len(x.bars) for x in result.series)),
            }
        except Exception as exc:
            outcomes[provider] = {'stale': True, 'error': ports.errors.exception_code(exc), 'contracts': None, 'bars': None}
    return {'providers': outcomes, 'mode': 'official_local_import' if local else 'official_explicit_refresh'}


def latest_market_observations(series):
    """Choose observed contract history, never infer a live or executable quote.

    Date/session ordering is explicit. Same-session sources without event times
    are not time-comparable: retain the first source (official daily cache).
    """
    chosen = {}
    session_order = {'night': 0, 'day': 1, 'combined': 2}
    for item in series:
        key = item.instrument.contract_id
        previous = chosen.get(key)
        if previous is None:
            chosen[key] = item
            continue
        latest, old = (item.bars[-1], previous.bars[-1])
        rank = (latest.trade_date, session_order[latest.session])
        old_rank = (old.trade_date, session_order[old.session])
        if rank > old_rank or (rank == old_rank and latest.end is not None and (old.end is not None) and (latest.end > old.end)):
            chosen[key] = item
    return tuple(chosen.values())


def dataset_market_series(ports: UiOperationPorts, dataset, calendar_payload):
    """Adapt only validated one-minute official history with hash-bound calendar."""
    from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance, bar_key

    ports.data_import.validate_dataset(dataset)
    manifest = dataset.manifest
    if manifest['source_type'] != 'official_local' or manifest.get('bar_granularity') != 'minute' or manifest.get('timeframe_minutes', 1) != 1:
        raise ValidationError(ports.text('ui.dataset_market_series.minute_history_required'))
    calendar = ports.data_import.SessionCalendar(calendar_payload['sessions'], version=calendar_payload['version'])
    if calendar.hash != manifest.get('calendar_hash'):
        raise ValidationError(ports.text('ui.dataset_market_series.calendar_hash_mismatch'))
    grouped = {}
    for bar in dataset.bars:
        instrument = InstrumentRef('TAIFEX', 'TMF', bar.contract_id, bar.contract_id.split(':')[-1])
        session = calendar.lookup(bar.timestamp, bar.contract_id)
        value = MarketBar(
            instrument,
            bar.trade_date,
            bar.session,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            interval='1m',
            timestamp=bar.timestamp,
            end=bar.end,
            session_open=session['open'],
            session_end=session['end'],
            source_id=bar.source_id,
        )
        grouped.setdefault(instrument, []).append(value)
    result = []
    for instrument, bars in grouped.items():
        bars.sort(key=bar_key)
        dates = [b.trade_date for b in bars]
        provenance = SourceProvenance(
            manifest['source_url'],
            manifest['source_hash'],
            ports.text('ui.dataset_market_series.taifex_source_hash').format(manifest['data_hash']),
            'https://www.taifex.com.tw',
            datetime.fromisoformat(manifest['imported_at'].replace('Z', '+00:00')),
            max(dates),
            min(dates),
            max(dates),
            mode='history',
            timestamp_basis='hash-bound explicit session calendar; one-minute source',
            warnings=tuple((str(x) for x in dataset.quality.get('warnings', ()))),
        )
        result.append(MarketSeries(instrument, tuple(bars), provenance))
    return tuple(result)

"""Versioned, prospective single-candidate E1 contract, owned by the host.

A fresh registry or a source label is never proof that historical data was unseen.
Only a plan committed before every planned observation can be evaluated here.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import hashlib
from pathlib import Path
import re

from quantlab.configuration import config_from_json
from quantlab.core import BacktestConfig, canonical_json, content_hash, to_dict, validate_contract
from quantlab.data import SessionCalendar
from quantlab.strict_json import loads
from quantlab.trading.domain.validation import DomainError, identity
from quantlab.trading.domain.automatic_calendar import TMF_OPEN, TMF_CLOSE, TMF_EXPIRY_CLOSE
from quantlab.trading.runtime.v1_signal_source import canonical_spec_json, spec_fingerprint, validated_spec
from quantlab.value_bounds import _bounded_value
from quantlab.verdict import LEVELS

PROTOCOL = 'm3-prospective-e1-v1'
SOURCE_URL = 'https://openapi.taifex.com.tw/v1/DailyMarketReportFut'
POLICY = {
    'version': 'm3-e1-policy-v1',
    'candidate_count': 1,
    'selection': 'frozen_before_first_observation',
    'returns': 'net_daily_returns_including_flat_days',
    'session_scope': 'TMF_official_full_day_only',
    'warmup': 'independent_flat_start_no_earlier_data',
    'bootstrap_draws': 5000,
    'bootstrap_seed': 20261021,
    'alpha': '0.05',
    'required_verdict': 'statistical_edge',
    'minimum_observations': 30,
    'max_bars': 10000,
    'max_runtime_seconds': 900,
    'worker_memory_mb': 512,
    'max_ipc_bytes': 16384,
}
SOURCE_FILES = (
    'core.py',
    'research.py',
    'backtest.py',
    'strategies.py',
    'data.py',
    'significance.py',
    'verdict.py',
    'trading/domain/automatic_calendar.py',
    'trading/domain/signal_strategy.py',
    'trading/domain/validation.py',
    'trading/domain/promotion.py',
    'trading/domain/models.py',
    'configuration.py',
    'strict_json.py',
    'value_bounds.py',
    'windows_paths.py',
    'trading/runtime/v1_signal_source.py',
    'trading/runtime/e1_protocol.py',
    'trading/runtime/e1_store.py',
    'trading/runtime/e1_source.py',
    'trading/runtime/e1_qualification.py',
    'trading/runtime/e1_reader.py',
)
PLAN_KEYS = {
    'protocol',
    'created_at',
    'workspace',
    'registry',
    'campaign_ref',
    'contract_id',
    'spec_json',
    'candidate_fingerprint',
    'strategy_hash',
    'calendar',
    'config',
    'source_digest',
    'source_url',
    'dataset_family',
    'dataset_interval',
    'evidence_mode',
    'policy',
}


def refuse():
    raise DomainError('candidate_unavailable')


OUTCOME_KEYS = frozenset(('verdict', 'sample_count', 'result_hash'))


def valid_outcome_shape(value):
    """The structure of a minimal E1 outcome. Callers add their own sample_count semantics."""
    return (
        type(value) is dict
        and set(value) == OUTCOME_KEYS
        and value['verdict'] in LEVELS
        and type(value['sample_count']) is int
        and is_hash(value['result_hash'])
    )


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    if type(value) is not str or len(value) > 40:
        refuse()
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        refuse()
    if result.utcoffset() is None or result.utcoffset().total_seconds() != 0:
        refuse()
    return result


def text_time(value):
    if not isinstance(value, datetime) or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
        refuse()
    return value.isoformat().replace('+00:00', 'Z')


def coverage_time(value):
    return value.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def is_hash(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def source_digest():
    root = Path(__file__).resolve().parents[2]
    return content_hash({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_FILES})


def calendar_for(plan):
    value = plan['calendar']
    if type(value) is not dict or set(value) != {'version', 'sessions'} or type(value['sessions']) is not list:
        refuse()
    if not 1 <= len(value['sessions']) <= POLICY['max_bars']:
        refuse()
    calendar = SessionCalendar(value['sessions'], version=value['version'])
    # Exact contract-specific sessions avoid shadowing or inferred holidays/expiry.
    for row in calendar.sessions:
        if row.get('contract_id') != plan['contract_id'] or row.get('closed', False) or row['session'] != 'day':
            refuse()
    if len({(row['trade_date'], row['session']) for row in calendar.sessions}) != len(calendar.sessions):
        refuse()
    return calendar


def validate_plan(plan, *, workspace, registry, current_sources=True):
    if type(plan) is not dict or set(plan) != PLAN_KEYS:
        refuse()
    _bounded_value(plan, max_nodes=200000)
    if (
        plan['protocol'] != PROTOCOL
        or plan['policy'] != POLICY
        or plan['source_url'] != SOURCE_URL
        or plan['dataset_family'] != 'TMF'
        or plan['dataset_interval'] != '1d'
        or plan['evidence_mode'] not in ('production', 'synthetic_validation')
        or plan['workspace'] != str(workspace)
        or plan['registry'] != str(registry)
    ):
        refuse()
    identity(plan['campaign_ref'])
    validate_contract(plan['contract_id'])
    if canonical_spec_json(plan['spec_json']) != plan['spec_json']:
        refuse()
    spec = validated_spec(plan['spec_json'])
    if (
        any(key in spec.parameters for key in ('stop_ticks', 'target_ticks'))
        or type(spec.parameters.get('quantity', 1)) is not int
        or spec.parameters.get('quantity', 1) != 1
    ):
        refuse()
    if (
        spec_fingerprint(plan['spec_json']) != plan['candidate_fingerprint']
        or content_hash(spec) != plan['strategy_hash']
        or not is_hash(plan['source_digest'])
    ):
        refuse()
    if current_sources and (plan['source_digest'] != source_digest() or plan['source_digest'] != RUNTIME_SOURCE_DIGEST):
        refuse()
    calendar = calendar_for(plan)
    created = timestamp(plan['created_at'])
    if created >= min(row['open'] for row in calendar.sessions) or created > utc_now():
        refuse()
    taipei = ZoneInfo('Asia/Taipei')
    for row in calendar.sessions:
        report_date = date.fromisoformat(row['trade_date'])
        if (
            report_date <= created.astimezone(taipei).date()
            or row['open'].astimezone(taipei).date() != report_date
            or row['end'].astimezone(taipei).date() != report_date
        ):
            refuse()
    config = config_from_json(plan['config'])
    config.__post_init__()
    if canonical_json(config) != canonical_json(plan['config']):
        refuse()
    if plan['contract_id'] not in config.instrument_expiries:
        refuse()
    expiry = config.instrument_expiries[plan['contract_id']]
    for row in calendar.sessions:
        close = TMF_EXPIRY_CLOSE if row['trade_date'] == expiry else TMF_CLOSE
        if row['trade_date'] > expiry or row['open'].astimezone(taipei).time() != TMF_OPEN or row['end'].astimezone(taipei).time() != close:
            refuse()
    return calendar, config


def make_plan(*, workspace, registry, campaign_ref, contract_id, signal_spec_json, calendar, config, evidence_mode):
    if not isinstance(calendar, SessionCalendar) or not isinstance(config, BacktestConfig):
        refuse()
    plan = {
        'protocol': PROTOCOL,
        'created_at': text_time(utc_now()),
        'workspace': str(workspace),
        'registry': str(registry),
        'campaign_ref': campaign_ref,
        'contract_id': contract_id,
        'spec_json': canonical_spec_json(signal_spec_json),
        'candidate_fingerprint': spec_fingerprint(signal_spec_json),
        'strategy_hash': content_hash(validated_spec(signal_spec_json)),
        'calendar': {'version': calendar.version, 'sessions': [to_dict(row) for row in calendar.sessions]},
        'config': to_dict(config),
        'source_digest': source_digest(),
        'source_url': SOURCE_URL,
        'dataset_family': 'TMF',
        'dataset_interval': '1d',
        'evidence_mode': evidence_mode,
        'policy': dict(POLICY),
    }
    validate_plan(plan, workspace=workspace, registry=registry)
    return plan


def decode(text):
    if type(text) is not str or not 0 < len(text.encode('utf-8')) <= 2_000_000:
        refuse()
    value = loads(text)
    if canonical_json(value) != text:
        refuse()
    return value


def reservation_values(reference, plan):
    calendar = calendar_for(plan)
    return (
        content_hash(['e1-reservation', reference]),
        content_hash(['prospective-envelope', reference]),
        reference,
        reference,
        plan['workspace'],
    ), (plan['contract_id'], coverage_time(min(row['open'] for row in calendar.sessions)), coverage_time(max(row['end'] for row in calendar.sessions)))


# An in-place source update cannot relabel already imported code as a new producer.
# Restarting under a reviewed new source version still rejects old receipts.
RUNTIME_SOURCE_DIGEST = source_digest()

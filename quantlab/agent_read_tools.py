"""Bounded offline D3 reads; host provenance is separate from untrusted saved JSON.

Use READ_REGISTRY.call with a ReadContext. A trusted host must bind each approved
training-only result to its exact dataset hash. Never construct evidence from a
model request, a saved partition label, mixed-period totals or consumed guards.
Legacy results without this evidence fail closed. No tools are UI-wired here.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, Context, localcontext
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from quantlab.agent_return import bounded_return
import quantlab.agent_manifest as agent_manifest
from quantlab.agent_tool_contract import MAX_LIMIT, MAX_RETURN_BYTES, RETURN_SCHEMA, validate
from quantlab.agent_tools import Registry, ReferenceNotFound
from quantlab.core import content_hash
from quantlab.paper import PaperBroker
from quantlab.reporting import validate_result_payload
from quantlab.research import PARAMETER_CONTRACTS


MAX_SAVED_BYTES = 32 * 1024 * 1024
MAX_SAVED_ITEMS = 100000
METRICS = ('initial_cash', 'final_equity', 'net_pnl', 'total_costs', 'return', 'max_drawdown', 'max_drawdown_pct', 'trade_count', 'fill_count', 'win_rate')
NUMERIC = {'type': 'string', 'pattern': r'-?(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,64})?', 'maxLength': 96}
HASH = {'type': 'string', 'pattern': r'[0-9a-f]{64}'}
INTEGER = {'type': 'integer', 'minimum': 0, 'maximum': MAX_SAVED_ITEMS}
TOOL_NAMES = (
    'list_saved_results',
    'get_backtest_summary',
    'get_backtest_trades',
    'get_backtest_equity',
    'compare_results',
    'get_data_quality_summary',
    'get_strategy_params',
    'get_paper_positions',
    'get_paper_orders',
    'get_result_manifest',
    'compare_result_manifests',
)


@dataclass(frozen=True)
class TrainingEvidence:
    result_id: str
    data_hash: str
    observations: int
    missing: int = 0
    duplicates: int = 0


@dataclass(frozen=True)
class ReadContext:
    saved_root: Path
    training: tuple[TrainingEvidence, ...] = ()
    paper_journal: Path | None = None


def _identity(value):
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError
    return value


def _approved(context):
    if not isinstance(context, ReadContext) or type(context.training) is not tuple or len(context.training) > MAX_SAVED_ITEMS:
        raise ValueError
    result = {}
    for evidence in context.training:
        if type(evidence) is not TrainingEvidence:
            raise ValueError
        identity = _identity(evidence.result_id)
        _identity(evidence.data_hash)
        if identity in result or any(
            type(v) is not int or not 0 <= v <= MAX_SAVED_ITEMS for v in (evidence.observations, evidence.missing, evidence.duplicates)
        ):
            raise ValueError
        result[identity] = evidence
    return result


def _result(context, identity):
    identity = _identity(identity)  # Validate before any filesystem operation.
    evidence = _approved(context)[identity]
    root = Path(context.saved_root).resolve(strict=True)
    folder = root / identity
    path = folder / 'result.json'
    if folder.is_symlink() or path.is_symlink() or path.resolve(strict=True).parent.parent != root:
        raise ValueError
    # Bounded binary read also handles files which grow after stat; no partial
    # content is ever returned. Reporting validates nested immutable bindings.
    with path.open('rb') as stream:
        raw = stream.read(MAX_SAVED_BYTES + 1)
    if len(raw) > MAX_SAVED_BYTES:
        raise ValueError
    envelope = json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_reject)
    if envelope.get('kind') != 'quantlab_result_v1' or envelope.get('sha256') != identity or content_hash(envelope['payload']) != identity:
        raise ValueError
    payload = envelope['payload']
    if type(payload) is not dict or set(payload) != {'manifest', 'signals', 'fills', 'ledger', 'equity', 'metrics', 'rejects', 'warnings'}:
        raise ValueError
    if type(payload['metrics']) is not dict or not set(METRICS) <= payload['metrics'].keys():
        raise ValueError
    for key in ('signals', 'fills', 'ledger', 'equity', 'rejects', 'warnings'):
        if type(payload[key]) is not list or len(payload[key]) > MAX_SAVED_ITEMS:
            raise ValueError
    if any(type(row) is not dict for key in ('signals', 'fills', 'ledger', 'equity', 'rejects') for row in payload[key]):
        raise ValueError
    # Validate already bounded bytes, avoiding a second read / replacement race.
    validate_result_payload(envelope['payload'])
    result = SimpleNamespace(**envelope['payload'])
    if result.manifest['data_hash'] != evidence.data_hash:
        raise ValueError
    # Validate every exposed record even for aggregate/list calls, so malformed
    # saved sequences cannot masquerade as a usable summary or partial listing.
    _metrics(result)
    for row in result.ledger:
        for key in ('quantity', 'entry_price', 'exit_price', 'net_pnl'):
            _number(row[key])
    for row in result.equity:
        _number(row['equity'])
        _time(row['timestamp'])
    return result


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject(_value):
    raise ValueError


def _number(value):
    if type(value) not in (int, str, Decimal) or len(str(value)) > 96:
        raise ValueError
    value = Decimal(value)
    if not value.is_finite() or value.copy_abs() >= Decimal('1e30') or value.as_tuple().exponent < -64:
        raise ValueError
    return format(value, 'f')


def _metrics(result):
    return {key: _number(result.metrics[key]) for key in METRICS if result.metrics.get(key) is not None}


def _time(value):
    if type(value) is not str or len(value) > 32:
        raise ValueError
    return datetime.fromisoformat(value.replace('Z', '+00:00')).isoformat()


def _paper_rows(context, name):
    if not isinstance(context, ReadContext) or context.paper_journal is None:
        raise ValueError
    path = Path(context.paper_journal)
    if path.is_symlink() or path.stat().st_size > MAX_SAVED_BYTES:
        raise ValueError
    state = PaperBroker.read_snapshot(path)
    if state.get('verification') != 'synthetic_paper_only':
        raise ValueError
    rows = state['positions' if name == 'get_paper_positions' else 'orders']
    if len(rows) > MAX_SAVED_ITEMS:
        raise ValueError
    output = []
    for key, value in sorted(rows.items()):
        item = {'id': hashlib.sha256(key.encode('utf-8')).hexdigest()}
        if name == 'get_paper_positions':
            item['quantity'] = _number(value)
        else:
            item.update(quantity=_number(value['intent']['quantity']), filled_quantity=_number(value['filled_quantity']), status=value['status'])
            if item['status'] not in ('submitting', 'accepted', 'partial', 'filled', 'cancelled', 'rejected', 'unknown'):
                raise ValueError
        output.append(item)
    return output


def _read(name, context, arguments):
    if name in ('get_result_manifest', 'compare_result_manifests'):

        def manifest(identity):
            _identity(identity)
            approved = _approved(context)
            if identity not in approved:
                # Existing records without provenance remain refused, not exposed.
                if not (Path(context.saved_root) / identity / 'result.json').exists():
                    raise ReferenceNotFound
                raise ValueError
            try:
                return _result(context, identity).manifest
            except FileNotFoundError:
                raise ReferenceNotFound from None

        left = manifest(arguments['result_id'])
        if name == 'compare_result_manifests':
            return agent_manifest.compare(left, manifest(arguments['other_id']))
        return agent_manifest.summary(left)
    if name.startswith('get_paper_'):
        return _paper_rows(context, name)
    if name == 'list_saved_results':
        # Listing verifies approved records too: stale/corrupt evidence never
        # produces plausible partial results, filenames or protected row counts.
        rows = []
        for identity in sorted(_approved(context)):
            result = _result(context, identity)
            row = {'id': identity}
            if arguments.get('include_datasets') == 1:
                row['data_hash'] = result.manifest['data_hash']
            rows.append(row)
        return rows
    identity = _identity(arguments['result_id'])
    result = _result(context, identity)
    if name == 'get_backtest_summary':
        rows = [_metrics(result)]
    elif name == 'compare_results':
        other_id = _identity(arguments['other_id'])
        if identity == other_id:
            raise ValueError
        other = _metrics(_result(context, other_id))
        with localcontext(Context(prec=64)):
            rows = [{key: _number(Decimal(other[key]) - Decimal(value)) for key, value in _metrics(result).items() if key in other}]
    elif name == 'get_data_quality_summary':
        evidence = _approved(context)[identity]
        rows = [{'observations': evidence.observations, 'missing': evidence.missing, 'duplicates': evidence.duplicates, 'has_gaps': evidence.missing > 0}]
    elif name == 'get_strategy_params':
        spec = result.manifest['strategy']
        rows = [{key: _number(spec['parameters'][key]) for key in PARAMETER_CONTRACTS[spec['family']]}]
    elif name == 'get_backtest_trades':
        rows = [
            dict(
                index=i,
                quantity=_number(row['quantity']),
                entry_price=_number(row['entry_price']),
                exit_price=_number(row['exit_price']),
                net_pnl=_number(row['net_pnl']),
            )
            for i, row in enumerate(result.ledger)
        ]
    elif name == 'get_backtest_equity':
        rows = [dict(index=i, timestamp=_time(row['timestamp']), equity=_number(row['equity'])) for i, row in enumerate(result.equity)]
    else:
        raise ValueError
    return rows


def _row_schema(name):
    if name in ('get_result_manifest', 'compare_result_manifests'):
        return agent_manifest.row_schema(name == 'compare_result_manifests')
    properties = {}
    if name == 'list_saved_results':
        properties = {'id': HASH, 'data_hash': HASH}
    elif name in ('get_backtest_summary', 'compare_results'):
        properties = {key: NUMERIC for key in METRICS}
    elif name == 'get_backtest_trades':
        properties = {key: NUMERIC for key in ('quantity', 'entry_price', 'exit_price', 'net_pnl')}
        properties['index'] = INTEGER
    elif name == 'get_backtest_equity':
        properties = {'index': INTEGER, 'timestamp': {'type': 'string', 'pattern': r'[0-9T:.+\-]{19,32}'}, 'equity': NUMERIC}
    elif name == 'get_data_quality_summary':
        properties = {key: INTEGER for key in ('observations', 'missing', 'duplicates')}
        properties['has_gaps'] = {'type': 'boolean'}
    elif name == 'get_strategy_params':
        properties = {key: NUMERIC for family in PARAMETER_CONTRACTS.values() for key in family}
    elif name == 'get_paper_positions':
        properties = {'id': HASH, 'quantity': NUMERIC}
    elif name == 'get_paper_orders':
        properties = {
            'id': HASH,
            'quantity': NUMERIC,
            'filled_quantity': NUMERIC,
            'status': {'enum': ['submitting', 'accepted', 'partial', 'filled', 'cancelled', 'rejected', 'unknown']},
        }
    return {'type': 'object', 'additionalProperties': False, 'properties': properties}


def create_registry():
    """Read tools through D1; each handler has a closed per-tool output."""
    schema = deepcopy(RETURN_SCHEMA)
    # Per-tool validation is enforced before D1's common envelope validation.
    schema['properties']['items']['items'] = {'type': 'object'}
    registry = Registry(return_schema=schema)
    for name in TOOL_NAMES:
        fields = {'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_LIMIT}, 'cursor': {'type': 'string', 'minLength': 66, 'maxLength': 128}}
        required = []
        if name == 'list_saved_results':
            fields['include_datasets'] = {'type': 'integer', 'minimum': 0, 'maximum': 1}
        if name != 'list_saved_results' and not name.startswith('get_paper_'):
            fields['result_id'] = {**HASH, 'minLength': 64, 'maxLength': 64}
            required.append('result_id')
        if name in ('compare_results', 'compare_result_manifests'):
            fields['other_id'] = {**HASH, 'minLength': 64, 'maxLength': 64}
            required.append('other_id')
        declaration = {
            'contractVersion': 1,
            'name': name,
            'effect': 'read',
            'capability': 'paper.read' if name.startswith('get_paper_') else 'research.read',
            'maxItems': MAX_LIMIT,
            'maxSerializedBytes': MAX_RETURN_BYTES,
            'pageSizeCap': MAX_LIMIT,
            'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': required, 'properties': fields},
        }
        registry.register(declaration, _handler(name))
    registry.freeze()
    return registry


def _handler(name):
    def call(context, arguments):
        # Validate all fields before the shared D11 serialization/byte bound.
        output = _read(name, context, arguments)
        if any(not validate(row, _row_schema(name)) for row in output):
            raise ValueError
        scope = json.dumps([name, {key: value for key, value in arguments.items() if key != 'cursor'}], sort_keys=True)
        return bounded_return(output, limit=arguments.get('limit', MAX_LIMIT), cursor=arguments.get('cursor'), scope=scope)

    return call


READ_REGISTRY = create_registry()

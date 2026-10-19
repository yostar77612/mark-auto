"""Default-deny, in-memory read tools. No provider, UI, broker or filesystem access."""

from copy import deepcopy
from dataclasses import dataclass
import json
from types import MappingProxyType

from quantlab.agent_tool_contract import CAPABILITIES, MAX_LIMIT, MAX_RETURN_BYTES, RETURN_SCHEMA, TOOL_SCHEMA, strict_json, validate
from quantlab.errors import ErrorCode


def _refusal():
    # B1 owns all human text. Never echo arguments, context, names or exceptions.
    return {'ok': False, 'error': {'code': ErrorCode.AGENT_TOOL_REFUSED.value, 'params': {}}}


@dataclass(frozen=True)
class _Entry:
    declaration_json: str
    handler: object


class Registry:
    """Registration is host-only; a valid declaration never grants execution."""

    def __init__(self, *, return_schema=None):
        self._entries = {}
        self._frozen = False
        self._return_schema = deepcopy(RETURN_SCHEMA if return_schema is None else return_schema)

    @property
    def declarations(self):
        return MappingProxyType({name: json.loads(entry.declaration_json) for name, entry in self._entries.items()})

    def freeze(self):
        self._frozen = True

    def register(self, declaration, handler):
        try:
            # Own a JSON-only snapshot: callers cannot alter authorization later.
            declaration = strict_json(json.dumps(declaration, allow_nan=False))
            if self._frozen or not validate(declaration, TOOL_SCHEMA) or not callable(handler):
                return _refusal()
            schema = declaration['inputSchema']
            fields = schema['properties']
            if not set(schema['required']) <= fields.keys():
                return _refusal()
            if declaration['effect'] == 'mutation':
                key = fields.get('idempotency_key', {})
                if 'idempotency_key' not in schema['required'] or key.get('type') != 'string' or key.get('minLength', 0) < 1:
                    return _refusal()
            for rule in fields.values():
                if rule.get('minimum', 0) > rule.get('maximum', 1000000000) or rule.get('minLength', 0) > rule.get('maxLength', 128):
                    return _refusal()
            name = declaration['name']
            if name in self._entries:
                return _refusal()
            self._entries[name] = _Entry(json.dumps(declaration, sort_keys=True), handler)
            return {'ok': True}
        except (TypeError, ValueError, RecursionError, UnicodeError):
            return _refusal()

    def resolve(self, name, capabilities=()):
        """Return a declaration or refusal, never an executable handler."""
        try:
            grants = set(capabilities)
            entry = self._entries.get(name)
            if not entry or not grants <= CAPABILITIES:
                return _refusal()
            declaration = json.loads(entry.declaration_json)
            if declaration['capability'] not in grants or declaration['capability'] not in {'research.read', 'paper.read'} or declaration['effect'] != 'read':
                return _refusal()
            return {'ok': True, 'tool': declaration}
        except (TypeError, ValueError):
            return _refusal()

    def call(self, name, arguments_json, *, capabilities=(), context=()):
        resolved = self.resolve(name, capabilities)
        if not resolved['ok']:
            return resolved
        try:
            arguments = strict_json(arguments_json)
            if not validate(arguments, resolved['tool']['inputSchema']):
                return _refusal()
            result = self._entries[name].handler(context, deepcopy(arguments))
            if not validate(result, self._return_schema) or len(json.dumps(result, allow_nan=False).encode('utf-8')) > MAX_RETURN_BYTES:
                return _refusal()
            if len(result['items']) > result['limit'] or result['limit'] != arguments.get('limit', MAX_LIMIT):
                return _refusal()
            expected = arguments.get('cursor', 0) + len(result['items']) if result['truncated'] else None
            if result['next_cursor'] != expected or (result['truncated'] and not result['items']):
                return _refusal()
            return result
        except Exception:
            # An untrusted host record or failing adapter cannot leak exception text.
            return _refusal()


def _training_records(context):
    # Partition provenance is assigned by a trusted host adapter, NEVER by a model.
    # Do this BEFORE projecting, counting or paging. No aggregate across partitions.
    return [row for row in context if type(row) is dict and row.get('partition') == 'training']


def _training_status(context, arguments):
    rows = _training_records(context)
    cursor, limit = arguments.get('cursor', 0), arguments.get('limit', MAX_LIMIT)
    if cursor > len(rows):
        return _refusal()
    page = rows[cursor : cursor + limit]
    # Positive field allowlist: no identifiers, strings, metrics, raw content or guards.
    items = [{'completed': row['completed'], 'observations': row['observations']} for row in page]
    end = cursor + len(page)
    truncated = end < len(rows)
    return {'ok': True, 'items': items, 'truncated': truncated, 'limit': limit, 'next_cursor': end if truncated else None}


PRODUCTION_REGISTRY = Registry()
PRODUCTION_REGISTRY.register(
    {
        'contractVersion': 1,
        'name': 'research.list_training_status',
        'capability': 'research.read',
        'effect': 'read',
        'inputSchema': {
            'type': 'object',
            'additionalProperties': False,
            'required': [],
            'properties': {
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_LIMIT},
                'cursor': {'type': 'integer', 'minimum': 0, 'maximum': 1000000000},
            },
        },
    },
    _training_status,
)
PRODUCTION_REGISTRY.freeze()

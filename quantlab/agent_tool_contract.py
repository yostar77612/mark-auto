"""Closed JSON-schema vocabulary for the offline agent contract (no code inputs)."""

import json
import re


CAPABILITIES = frozenset({'research.read', 'paper.read', 'ui.navigate', 'research.run'})
EFFECTS = frozenset({'read', 'mutation'})
MAX_LIMIT = 50
MAX_INPUT_BYTES = 4096
MAX_RETURN_BYTES = 8192

_SCALAR_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['type'],
    'properties': {
        'type': {'enum': ['string', 'integer']},
        'minimum': {'type': 'integer', 'minimum': 0},
        'maximum': {'type': 'integer', 'minimum': 0},
        'minLength': {'type': 'integer', 'minimum': 0},
        'maxLength': {'type': 'integer', 'minimum': 1, 'maximum': 128},
    },
}
TOOL_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['contractVersion', 'name', 'capability', 'effect', 'inputSchema'],
    'properties': {
        'contractVersion': {'type': 'integer', 'const': 1},
        'name': {'type': 'string', 'pattern': r'^[a-z][a-z0-9_.]{0,63}$'},
        'capability': {'enum': sorted(CAPABILITIES)},
        'effect': {'enum': sorted(EFFECTS)},
        'maxItems': {'type': 'integer', 'const': MAX_LIMIT},
        'maxSerializedBytes': {'type': 'integer', 'const': MAX_RETURN_BYTES},
        'pageSizeCap': {'type': 'integer', 'const': MAX_LIMIT},
        'inputSchema': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['type', 'properties', 'required', 'additionalProperties'],
            'properties': {
                'type': {'const': 'object'},
                'properties': {'type': 'object', 'maxProperties': 8, 'additionalProperties': _SCALAR_SCHEMA},
                'required': {'type': 'array', 'maxItems': 8, 'uniqueItems': True, 'items': {'type': 'string'}},
                'additionalProperties': {'const': False},
            },
        },
    },
    'allOf': [
        {
            'if': {'properties': {'effect': {'const': 'mutation'}}},
            'then': {
                'properties': {
                    'inputSchema': {
                        'properties': {
                            'required': {'contains': {'const': 'idempotency_key'}},
                            'properties': {
                                'required': ['idempotency_key'],
                                'properties': {
                                    'idempotency_key': {
                                        'required': ['minLength'],
                                        'properties': {'type': {'const': 'string'}, 'minLength': {'minimum': 1}},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    ],
}
ROW_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['completed', 'observations'],
    'properties': {'completed': {'type': 'boolean'}, 'observations': {'type': 'integer', 'minimum': 0, 'maximum': 1000000000}},
}
RETURN_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['ok', 'items', 'truncated', 'limit', 'next_cursor'],
    'properties': {
        'ok': {'const': True},
        'items': {'type': 'array', 'maxItems': MAX_LIMIT, 'items': ROW_SCHEMA},
        'truncated': {'type': 'boolean'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_LIMIT},
        'next_cursor': {'type': ['integer', 'null'], 'minimum': 0},
    },
}
DOCUMENT_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': 'Agent App Tools v1',
    **TOOL_SCHEMA,
    '$defs': {'boundedReturn': RETURN_SCHEMA},
}


def validate(value, schema):
    """Validate our closed schema subset. No coercion, refs, or remote resolution.

    Only host-owned schemas reach this interpreter; tool input schemas must first
    pass TOOL_SCHEMA and the semantic checks in Registry.register.
    """
    kinds = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool, 'null': type(None)}
    if 'type' in schema:
        names = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not any(type(value) is kinds[name] for name in names):
            return False
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        return False
    if 'enum' in schema and not any(type(value) is type(item) and value == item for item in schema['enum']):
        return False
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        if not set(schema.get('required', ())) <= value.keys() or len(value) > schema.get('maxProperties', len(value)):
            return False
        for key, item in value.items():
            rule = properties.get(key, schema.get('additionalProperties', True))
            if rule is False or (isinstance(rule, dict) and not validate(item, rule)):
                return False
    if isinstance(value, list):
        if len(value) > schema.get('maxItems', len(value)) or any(not validate(item, schema.get('items', {})) for item in value):
            return False
        if schema.get('uniqueItems') and any(item in value[:index] for index, item in enumerate(value)):
            return False
        if 'contains' in schema and not any(validate(item, schema['contains']) for item in value):
            return False
    if isinstance(value, str):
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', len(value)):
            return False
        if 'pattern' in schema and re.fullmatch(schema['pattern'], value) is None:
            return False
    if type(value) is int and not schema.get('minimum', value) <= value <= schema.get('maximum', value):
        return False
    if any(not validate(value, rule) for rule in schema.get('allOf', ())):
        return False
    return not ('if' in schema and validate(value, schema['if']) and not validate(value, schema.get('then', {})))


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _constant(_value):
    raise ValueError


def strict_json(text):
    """Model text must be a bounded, duplicate-free JSON object; never a program."""
    if type(text) is not str or len(text.encode('utf-8')) > MAX_INPUT_BYTES:
        raise ValueError
    result = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    if type(result) is not dict:
        raise ValueError
    return result

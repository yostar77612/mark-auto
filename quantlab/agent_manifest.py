"""Positive manifest projection: saved identities and typed costs, never datasets.

spec_hash is the immutable strategy revision (ADR 0005). Free-form strategy IDs,
cost version labels, source paths and dataset metadata deliberately stay private.
Callers must validate the saved envelope and trusted training evidence first.
"""

import re

from quantlab.agent_tool_contract import validate


IDENTITIES = ('spec_hash', 'data_hash', 'cost_hash', 'engine_version')
COST_FIELDS = ('commission_per_side', 'tax_rate', 'slippage_ticks', 'tax_rounding', 'effective_from')
NON_COMPARABLE = frozenset(('data_hash', 'cost_hash', 'engine_version'))
VALUE = {'type': ['string', 'integer', 'null'], 'maxLength': 96}
FIELD = {
    'type': 'string',
    'pattern': r'(?:spec_hash|data_hash|cost_hash|engine_version|costs\.(?:commission_per_side|tax_rate|slippage_ticks|tax_rounding|effective_from)|cost_schedule\.[0-9]{5}\.(?:commission_per_side|tax_rate|slippage_ticks|tax_rounding|effective_from))',
}


def row_schema(compare=False):
    properties = {'field': FIELD, 'value': VALUE}
    if compare:
        properties = {
            'field': FIELD,
            'left': VALUE,
            'right': VALUE,
            'status': {'enum': ['same', 'different']},
            'non_comparable': {'type': 'boolean'},
        }
    schema = {'type': 'object', 'additionalProperties': False, 'required': list(properties), 'properties': properties, 'allOf': []}
    for field in IDENTITIES:
        rule = {'type': ['string', 'null'], 'pattern': r'quantlab-event-v[0-9]{1,6}' if field == 'engine_version' else r'[0-9a-f]{64}'}
        schema['allOf'].append(
            {
                'if': {'properties': {'field': {'const': field}}},
                'then': {'properties': {key: rule for key in (('left', 'right') if compare else ('value',))}},
            }
        )
    costs = {
        'commission_per_side': {'type': ['string', 'null'], 'pattern': r'[0-9]{1,30}(?:\.[0-9]{1,64})?', 'maxLength': 96},
        'tax_rate': {'type': ['string', 'null'], 'pattern': r'[0-9]{1,30}(?:\.[0-9]{1,64})?', 'maxLength': 96},
        'slippage_ticks': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 1000000000},
        'tax_rounding': {'enum': [None, 'none', 'floor_twd', 'half_up_twd', 'ceiling_twd']},
        'effective_from': {'type': ['string', 'null'], 'pattern': r'[0-9]{4}-[0-9]{2}-[0-9]{2}'},
    }
    for field, rule in costs.items():
        schema['allOf'].append(
            {
                'if': {'properties': {'field': {'pattern': r'(?:costs|cost_schedule\.[0-9]{5})\.' + field}}},
                'then': {'properties': {key: rule for key in (('left', 'right') if compare else ('value',))}},
            }
        )
    return schema


def _cost_value(key, value):
    if value is None:
        return None
    if key == 'slippage_ticks':
        if type(value) is not int or not 0 <= value <= 1000000000:
            raise ValueError
    elif key in ('commission_per_side', 'tax_rate'):
        if type(value) is not str or re.fullmatch(r'[0-9]{1,30}(?:\.[0-9]{1,64})?', value) is None or len(value) > 96:
            raise ValueError
    elif key == 'tax_rounding':
        if value not in ('none', 'floor_twd', 'half_up_twd', 'ceiling_twd'):
            raise ValueError
    elif type(value) is not str or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value) is None:
        raise ValueError
    return value


def summary(manifest):
    """Values are returned verbatim; absent optional fields remain explicit nulls."""
    values = {field: manifest.get(field) for field in IDENTITIES}
    config = manifest.get('config', {})
    costs = config.get('costs', {})
    for field in COST_FIELDS:
        values['costs.' + field] = _cost_value(field, costs.get(field))
    schedule = config.get('cost_schedule', [])
    if type(schedule) is not list or len(schedule) > 10000:
        raise ValueError
    for index, entry in enumerate(schedule):
        for field in COST_FIELDS:
            values[f'cost_schedule.{index:05d}.' + field] = _cost_value(field, entry.get(field))
    rows = [{'field': key, 'value': values[key]} for key in sorted(values)]
    if any(not validate(row, row_schema()) for row in rows):
        raise ValueError
    return rows


def compare(left, right):
    a = {row['field']: row['value'] for row in summary(left)}
    b = {row['field']: row['value'] for row in summary(right)}
    return [
        {
            'field': field,
            'left': a.get(field),
            'right': b.get(field),
            'status': 'same' if a.get(field) == b.get(field) else 'different',
            'non_comparable': field in NON_COMPARABLE and a.get(field) != b.get(field),
        }
        for field in sorted(a.keys() | b.keys())
    ]

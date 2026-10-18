"""Five causal, finite strategy families and a deliberately small numeric rule AST."""
from decimal import Decimal, InvalidOperation, localcontext, Context, ROUND_HALF_EVEN
from .core import Bar, Signal, StrategySpec, ValidationError, canonical_json

FAMILIES = ('trend', 'mean_reversion', 'channel_breakout', 'momentum', 'volatility_compression')
DEFAULTS = {
    'trend': {'fast': 5, 'slow': 20},
    'mean_reversion': {'lookback': 20, 'entry_bps': '50'},
    'channel_breakout': {'lookback': 20},
    'momentum': {'lookback': 10, 'threshold_bps': '30', 'max_holding_bars': 10},
    'volatility_compression': {'lookback': 10, 'max_range_bps': '40'},
}


def builtin_strategies():
    return tuple(StrategySpec(f'{family}-v1', family, dict(params), {}) for family, params in DEFAULTS.items())


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValidationError('numeric rule/parameter must be decimal string or integer')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValidationError('invalid decimal') from None
    if not result.is_finite() or abs(result) > Decimal('1e12'):
        raise ValidationError('numeric value out of bounds')
    return result


def _integer(value, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        raise ValidationError(f'integer required in [{lo}, {hi}]')


def _validate_node(node, depth=0, counter=None):
    counter = [0] if counter is None else counter
    counter[0] += 1
    if depth > 12 or counter[0] > 128 or not isinstance(node, dict):
        raise ValidationError('rule AST exceeds limits or invalid node')
    op = node.get('op')
    def keys(required, optional=()):
        if not set(required) <= node.keys() or node.keys() - set(required) - set(optional):
            raise ValidationError(f'invalid {op} node keys')
    def child(n, kind):
        if _validate_node(n, depth+1, counter) != kind:
            raise ValidationError('AST operand type mismatch')
    if op == 'const':
        keys(('op', 'value')); _number(node['value']); return 'numeric'
    if op in ('field', 'sma', 'highest', 'lowest', 'return_bps'):
        field_key = 'name' if op == 'field' else 'field'
        keys(('op', field_key) if op == 'field' else ('op', field_key, 'period'), ('lag',))
        if node[field_key] not in ('open', 'high', 'low', 'close', 'volume'):
            raise ValidationError('unsupported field')
        _integer(node.get('lag', 0), 0, 500)
        if op != 'field': _integer(node['period'], 1, 500)
        return 'numeric'
    if op in ('gt', 'gte', 'lt', 'lte', 'eq'):
        keys(('op', 'left', 'right')); child(node['left'], 'numeric'); child(node['right'], 'numeric'); return 'boolean'
    if op in ('and', 'or'):
        keys(('op', 'args'))
        if not isinstance(node['args'], list) or not 1 <= len(node['args']) <= 16:
            raise ValidationError('invalid boolean args')
        for arg in node['args']: child(arg, 'boolean')
        return 'boolean'
    if op == 'not':
        keys(('op', 'arg')); child(node['arg'], 'boolean'); return 'boolean'
    raise ValidationError('unsupported rule operator')


def validate_strategy(spec):
    if not isinstance(spec, StrategySpec) or spec.schema_version != 1 or spec.family not in FAMILIES:
        raise ValidationError('unsupported strategy schema/family')
    if len(canonical_json(spec).encode()) > 32768:
        raise ValidationError('strategy too large')
    p = spec.parameters
    required = set(DEFAULTS[spec.family])
    if not required <= p.keys() or p.keys() - required - {'quantity', 'stop_ticks', 'target_ticks'}:
        raise ValidationError('missing or unknown strategy parameters')
    for key, value in p.items():
        if key in ('entry_bps', 'threshold_bps', 'max_range_bps'):
            if not 0 < _number(value) <= 10000: raise ValidationError('basis point parameter out of bounds')
        else:
            bounds = {'fast': (1,999), 'quantity': (1,100), 'stop_ticks': (1,100000), 'target_ticks': (1,100000), 'max_holding_bars': (1,1000)}.get(key, (2,1000))
            _integer(value, *bounds)
    if spec.family == 'trend' and p['fast'] >= p['slow']:
        raise ValidationError('fast must be below slow')
    if spec.rules:
        if not {'long', 'short'} <= spec.rules.keys() or spec.rules.keys() - {'long', 'short', 'exit'}:
            raise ValidationError('rules require long and short, optionally exit')
        counter = [0]
        for node in spec.rules.values():
            if _validate_node(node, counter=counter) != 'boolean': raise ValidationError('rule must be boolean')


def _evaluate(node, bars, i):
    op = node['op']
    if op == 'const': return _number(node['value'])
    if op in ('field', 'sma', 'highest', 'lowest', 'return_bps'):
        end = i-node.get('lag',0)
        period = node.get('period',1)
        start = end - period + (0 if op == 'return_bps' else 1)
        if start < 0: return None
        field = node.get('field', node.get('name'))
        values = [Decimal(getattr(b,field)) for b in bars[start:end+1]]
        if op == 'field': return values[-1]
        if op == 'sma': return sum(values)/len(values)
        if op == 'highest': return max(values)
        if op == 'lowest': return min(values)
        return (values[-1]/values[0]-1)*10000 if values[0] else None
    if op == 'not':
        v = _evaluate(node['arg'], bars, i)
        return None if v is None else not v
    if op in ('and','or'):
        values = [_evaluate(n,bars,i) for n in node['args']]
        return None if None in values else (all(values) if op=='and' else any(values))
    left, right = _evaluate(node['left'],bars,i), _evaluate(node['right'],bars,i)
    if left is None or right is None: return None
    return {'gt':left>right,'gte':left>=right,'lt':left<right,'lte':left<=right,'eq':left==right}[op]


def _validate_bars(bars):
    previous = {}
    for b in bars:
        if not isinstance(b, Bar): raise ValidationError('Bar required')
        b.__post_init__()
        if b.contract_id in previous and b.timestamp < previous[b.contract_id]:
            raise ValidationError('overlapping or unsorted bars')
        previous[b.contract_id] = b.end
    if any(a.timestamp > b.timestamp for a,b in zip(bars,bars[1:])):
        raise ValidationError('bars must be chronological')


def generate_signals(bars, spec):
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        return _generate_signals(bars,spec)


def _generate_signals(bars, spec):
    """Signals stamped at availability (bar.end); never on preceding prices.

    State is per explicit contract. A signal is emitted only on desired-target
    changes. Engine stops may flatten independently; a new trigger is needed.
    """
    validate_strategy(spec); _validate_bars(bars)
    histories, states, entered = {}, {}, {}
    signals = []
    p, family = spec.parameters, spec.family
    quantity = p.get('quantity',1)
    for b in bars:
        history = histories.setdefault(b.contract_id, [])
        history.append(b); i=len(history)-1
        state = states.get(b.contract_id,0); target=state; reason=family
        if b.volume == 0: continue
        if spec.rules:
            values={key:_evaluate(node,history,i) for key,node in spec.rules.items()}
            if any(v is None for v in values.values()): continue
            if values.get('exit') or (values['long'] and values['short']): target=0; reason='rule_exit_or_conflict'
            elif values['long']: target=quantity
            elif values['short']: target=-quantity
        elif family == 'trend':
            fast,slow=p['fast'],p['slow']
            if len(history) < slow+1: continue
            now=sum(x.close for x in history[-fast:])/fast-sum(x.close for x in history[-slow:])/slow
            before=sum(x.close for x in history[-fast-1:-1])/fast-sum(x.close for x in history[-slow-1:-1])/slow
            if now>0 and before<=0: target=quantity
            elif now<0 and before>=0: target=-quantity
        elif family == 'mean_reversion':
            n=p['lookback']
            if i<n: continue
            mean=sum(x.close for x in history[i-n:i])/n
            if not mean: continue
            deviation=(b.close/mean-1)*10000; band=_number(p['entry_bps'])
            if (state>0 and b.close>=mean) or (state<0 and b.close<=mean): target=0
            elif not state and deviation<=-band: target=quantity
            elif not state and deviation>=band: target=-quantity
        elif family in ('channel_breakout','volatility_compression'):
            n=p['lookback']
            if i<n: continue
            prior=history[i-n:i]; high=max(x.high for x in prior); low=min(x.low for x in prior)
            quiet=family=='channel_breakout' or (low>0 and (high-low)/low*10000<=_number(p['max_range_bps']))
            if quiet and b.close>high: target=quantity
            elif quiet and b.close<low: target=-quantity
        else:
            n=p['lookback']
            if i<n or not history[i-n].close: continue
            change=(b.close/history[i-n].close-1)*10000; threshold=_number(p['threshold_bps'])
            if state and i-entered.get(b.contract_id,i)>=p['max_holding_bars']: target=0
            elif not state and change>=threshold: target=quantity
            elif not state and change<=-threshold: target=-quantity
        if target != state:
            signals.append(Signal(b.end,b.contract_id,target,reason))
            states[b.contract_id]=target
            if target: entered[b.contract_id]=i
    return tuple(signals)

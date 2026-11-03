"""The v1/v2 composition boundary: unchanged research DSL and signal callable.

No rule translation, market-data access, execution, or strategy mutation lives here.
"""

from datetime import timezone

from quantlab.core import Bar, StrategySpec, ValidationError, canonical_json, validate_signal_contract
from quantlab.research import candidate_fingerprint, validate_dsl
from quantlab.strategies import generate_signals
from quantlab.strict_json import loads
from quantlab.trading.domain.signal_strategy import MAX_SPEC_JSON_CHARS, SignalBar, SignalPoint
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.signals import SignalSource


def validated_spec(signal_spec_json: str) -> StrategySpec:
    """Use the existing research AST admission path, never a parallel interpreter."""
    if not isinstance(signal_spec_json, str) or not signal_spec_json or len(signal_spec_json) > MAX_SPEC_JSON_CHARS:
        raise DomainError('candidate_spec_unsupported')
    try:
        return validate_dsl(loads(signal_spec_json))
    except (ValidationError, TypeError, KeyError, RecursionError):
        # Do not echo untrusted JSON or rule contents into the error channel.
        raise DomainError('candidate_spec_unsupported') from None


def spec_fingerprint(signal_spec_json: str) -> str:
    """The original v1 behavioral fingerprint, including its default normalization."""
    return candidate_fingerprint(validated_spec(signal_spec_json))


def canonical_spec_json(signal_spec_json: str) -> str:
    """Canonical serialization of the admitted v1 specification, without rewriting rules."""
    return canonical_json(validated_spec(signal_spec_json))


class V1SignalSource(SignalSource):
    def signals(self, contract_ref: str, bars: tuple[SignalBar, ...], signal_spec_json: str) -> tuple[SignalPoint, ...]:
        spec = validated_spec(signal_spec_json)
        try:
            # Validate even an empty history; no unsupported instrument can slip through.
            validate_signal_contract(contract_ref)
            mapped = tuple(
                Bar(
                    timestamp=bar.starts_at.astimezone(timezone.utc),
                    end=bar.ends_at.astimezone(timezone.utc),
                    trade_date=bar.trade_date.isoformat(),
                    session=bar.session,
                    contract_id=contract_ref,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
                for bar in bars
            )
            signals = generate_signals(mapped, spec)
        except ValidationError:
            raise DomainError('validation_failed', 'v1 signal input') from None
        return tuple(SignalPoint(point.timestamp, point.target_position, point.reason) for point in signals)

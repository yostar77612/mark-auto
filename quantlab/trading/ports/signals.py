"""Signal-function boundary. The only implementation lives in runtime and calls the v1 research function."""

from typing import Protocol

from quantlab.trading.domain.signal_strategy import SignalBar, SignalPoint


class SignalSource(Protocol):
    def signals(self, contract_ref: str, bars: tuple[SignalBar, ...], signal_spec_json: str) -> tuple[SignalPoint, ...]: ...

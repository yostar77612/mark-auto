"""Explicit trusted DTO registry. No module names from incoming data execute."""

from dataclasses import is_dataclass
from enum import Enum

from . import broker_settings, contracts, lifecycle_models, performance, provenance, state, sessions
from .codec import register
from quantlab.trading.domain import calendar, costs, lifecycle, live_bars, models, risk, strategy
from quantlab.trading.ports import contracts as port_contracts


def initialize() -> None:
    for module in (
        models,
        calendar,
        costs,
        risk,
        strategy,
        lifecycle,
        live_bars,
        port_contracts,
        broker_settings,
        contracts,
        lifecycle_models,
        performance,
        provenance,
        state,
        sessions,
    ):
        for value in vars(module).values():
            if isinstance(value, type) and value.__module__ == module.__name__ and (is_dataclass(value) or issubclass(value, Enum)):
                register(value)

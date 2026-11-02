"""Explicit trusted DTO registry. No module names from incoming data execute."""

from dataclasses import is_dataclass
from enum import Enum

from . import (
    automatic_state,
    broker_settings,
    contracts,
    daily_closes,
    daily_state,
    lifecycle_models,
    manual_book,
    manual_contracts,
    market_settings,
    performance,
    preflight,
    provenance,
    state,
    sessions,
    sinopac_contracts,
)
from .codec import register
from quantlab.trading.domain import auto_cycle, calendar, costs, lifecycle, live_bars, maintenance, models, risk, strategy, watch
from quantlab.trading.ports import contracts as port_contracts
from quantlab.trading.ports import manual as manual_ports


def initialize() -> None:
    for module in (
        auto_cycle,
        automatic_state,
        daily_state,
        daily_closes,
        models,
        calendar,
        costs,
        maintenance,
        risk,
        strategy,
        lifecycle,
        live_bars,
        port_contracts,
        manual_ports,
        broker_settings,
        market_settings,
        sinopac_contracts,
        manual_contracts,
        manual_book,
        watch,
        contracts,
        lifecycle_models,
        performance,
        preflight,
        provenance,
        state,
        sessions,
    ):
        for value in vars(module).values():
            if isinstance(value, type) and value.__module__ == module.__name__ and (is_dataclass(value) or issubclass(value, Enum)):
                register(value)

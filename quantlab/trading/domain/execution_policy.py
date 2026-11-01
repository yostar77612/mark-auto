"""M2 execution scope: production mutations require a future owner decision."""

from .models import Environment


def orders_enabled(environment: Environment) -> bool:
    return environment is Environment.LOCAL or environment is Environment.BROKER_SIMULATION

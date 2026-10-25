"""Deterministic fault-injectable local exchange; never opens a network connection."""

from .broker import FaultPlan, RemoteState, SimulatedBroker

__all__ = ['FaultPlan', 'RemoteState', 'SimulatedBroker']

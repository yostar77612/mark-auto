"""The single explicit optional SDK import boundary; never construct a client."""

from types import ModuleType

from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BROKER_SDK_VERSION


def load_pinned_sdk() -> ModuleType:
    """Load the installed optional module only for an explicit connect request.

    Neither importing this adapter module nor inspecting configuration calls
    this function. Version validation grants no broker capability or permission.
    """
    try:
        import shioaji
    except ImportError as exc:
        raise DomainError('capability_missing', 'optional pinned broker SDK is unavailable') from exc
    if getattr(shioaji, '__version__', None) != BROKER_SDK_VERSION:
        raise DomainError('capability_missing', 'unsupported broker SDK version')
    return shioaji

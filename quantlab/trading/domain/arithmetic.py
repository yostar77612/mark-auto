"""Stable Decimal context shared by financial and signal calculations."""

from decimal import Context, ROUND_HALF_EVEN, localcontext
from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from .validation import DomainError


P = ParamSpec('P')
R = TypeVar('R')


def decimal_operation(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def calculate(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
                return function(*args, **kwargs)
        except ArithmeticError as exc:
            raise DomainError('validation_failed', 'financial arithmetic outside supported bounds') from exc

    return calculate

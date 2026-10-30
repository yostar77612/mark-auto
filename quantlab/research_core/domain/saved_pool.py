"""Saved campaign evidence; no provider calls or credential access."""

from __future__ import annotations
import re
from dataclasses import dataclass
from functools import wraps
from quantlab.core import StrategySpec, ValidationError, freeze
from quantlab.errors import fail, saved_candidate_reason

MAX_AUDIT_BYTES = 32 * 1024 * 1024
MAX_SOURCE_BARS = 100000


@dataclass(frozen=True)
class SavedCandidatePool:
    candidate_pool: tuple[StrategySpec, ...]
    admission: dict

    def __post_init__(self):
        object.__setattr__(self, 'candidate_pool', tuple(self.candidate_pool))
        object.__setattr__(self, 'admission', freeze(self.admission))


class SavedCandidatePoolError(ValidationError):
    """Only a fixed public reason code should cross a redacted desktop boundary."""

    __module__ = 'quantlab.saved_candidate_pool'

    def __init__(self, message, reason_code='source_invalid_evidence'):
        super().__init__(message)
        self.reason_code = reason_code


def _hash(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _fail(message):
    fail(message, SavedCandidatePoolError, saved_candidate_reason(message))


def _safe_boundary(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except SavedCandidatePoolError:
            raise
        except (ValidationError, KeyError, TypeError, ValueError, OverflowError, RecursionError, OSError) as exc:
            raise SavedCandidatePoolError('Invalid saved source evidence') from exc

    return wrapped

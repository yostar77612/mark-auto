"""Read-only boundary to passed research candidates (qualification facts only)."""

from typing import Protocol

from quantlab.trading.domain.signal_strategy import CandidateEvidence, CandidateSummary


class CandidateCatalog(Protocol):
    def passed(self) -> tuple[CandidateSummary, ...]: ...

    def resolve(self, candidate_ref: str) -> CandidateEvidence:
        """Missing, unreadable or mismatching candidates raise ``DomainError('candidate_unavailable')``."""
        ...

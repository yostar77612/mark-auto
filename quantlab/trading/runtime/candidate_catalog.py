"""Read-only E1 projection; never load research/OOS payloads to infer qualification.

The current research journal has no authoritative per-candidate E1 summary.
Its display-only walk-forward verdict combines fold winners and is not such a
summary. Consequently the default reader fails closed. A composition-owned
reader may be supplied only when it validates authoritative research summaries
(including source binding and one-time consumption) before returning E1 values.
It must not return raw research records, OOS values or final-holdout values.
"""

from collections.abc import Callable
from pathlib import Path
import sqlite3

from quantlab.trading.domain.promotion import PromotionThresholds
from quantlab.trading.domain.signal_strategy import CandidateEvidence, CandidateSummary
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.v1_signal_source import canonical_spec_json, spec_fingerprint


ValidatedSummaryReader = Callable[[Path], tuple[CandidateEvidence, ...]]


def _unavailable_summaries(workspace: Path) -> tuple[CandidateEvidence, ...]:
    # Do not replace this with JSON exports or the display-only verdict: neither
    # establishes the per-candidate E1 contract. Wiring a producer is separate work.
    raise DomainError('candidate_unavailable')


class ResearchWorkspaceCandidateCatalog:
    """Project already validated, source-bound E1 summaries without copying OOS.

    ``read_validated_summaries`` is a trusted host composition dependency, not a
    UI/IPC/AI input. It must perform any bootstrap-lock checks required by its
    workspace configuration; the catalogue additionally rejects a local desktop
    lock. No locks are acquired and no research state is created or modified.
    """

    def __init__(self, workspace: Path, *, read_validated_summaries: ValidatedSummaryReader = _unavailable_summaries) -> None:
        self._workspace = Path(workspace)
        self._read_validated_summaries = read_validated_summaries

    def _check_workspace(self) -> None:
        if not self._workspace.is_dir() or (self._workspace / 'desktop.lock').exists():
            raise DomainError('candidate_unavailable')

    def _evidence(self) -> tuple[CandidateEvidence, ...]:
        try:
            self._check_workspace()
            rows = self._read_validated_summaries(self._workspace)
            self._check_workspace()
            if type(rows) is not tuple or any(type(row) is not CandidateEvidence for row in rows):
                raise DomainError('candidate_unavailable')
            references = set()
            for row in rows:
                if row.candidate_ref in references or spec_fingerprint(row.signal_spec_json) != row.candidate_fingerprint:
                    raise DomainError('candidate_unavailable')
                references.add(row.candidate_ref)
                if canonical_spec_json(row.signal_spec_json) != row.signal_spec_json:
                    raise DomainError('candidate_unavailable')
            return rows
        except (OSError, sqlite3.Error, ValueError, TypeError):
            # Deliberately discard source details: they can contain paths or
            # research payloads and must not cross the catalogue boundary.
            raise DomainError('candidate_unavailable') from None

    def passed(self) -> tuple[CandidateSummary, ...]:
        return tuple(
            CandidateSummary(row.candidate_ref, row.verdict, row.completed_at, row.dataset_interval)
            for row in self._evidence()
            if row.verdict == PromotionThresholds().BUILD_REQUIRED_VERDICT and row.oos_consumed
        )

    def resolve(self, candidate_ref: str) -> CandidateEvidence:
        for row in self._evidence():
            if row.candidate_ref == candidate_ref:
                return row
        raise DomainError('candidate_unavailable')

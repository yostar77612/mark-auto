# M2-3d official daily source review fixes

Owner request: fix the #161 independent review before enabling stock swing
automation. Branch `codex/m2-3d-daily-basis-fixes`, one direct-to-main PR.
Estimated implementation and local verification: 180 minutes; at 270 minutes
publish the tested minimum and explicitly defer anything unfinished. Order-path
changes require full green CI followed by Claude review; no autonomous merge.

## First-commit interface contract

- `DailySignalDataView` appends `verified_at: datetime | None = None` and
  `expires_at: datetime | None = None`. Old wire values load with empty defaults.
  `verified_at` is the server's validation time; `expires_at` bounds a displayed
  VERIFIED status. `available_at` means the persisted arrival time of the
  required official facts, not the time a view or history method was called.
- `AutomaticView.daily_signal_data` remains the cache-only source of these
  rows. Dispatch revalidation failure must immediately invalidate its row.
- No new `UiAction`, IPC operation or error code. Existing
  `daily_signal_source_unverified`, `daily_signal_basis_mismatch` and
  `daily_signal_not_available` remain fail-closed. A temporary source IO error
  must not become a permanent engine `storage_failed` condition.
- Internal source verification is revision-bound and bounded; a changed store
  revision requires complete byte/schema validation again. Cold validation is
  outside bundle/engine/owner locks; a locked miss defers the signal.
- An explicit official-data import command accepts recorded public responses or
  per-invocation consent for official downloads, including complete TWT49U
  negative evidence. Neither pump nor rendering downloads data.

## Scope and acceptance

F1: cursor-first admission, bounded revision cache, bounded active manifests,
immutable historical evidence retained, large-cache pump lock measurements.
F2: public source and application read boundaries contain every ordinary IO or
parser exception without accepting an unverified signal.
F3: a usable offline-testable import tool and a real SQLite/source/ManualRuntime
assembly/engine/fake SDK end-to-end test.
F4 is optional: preserve strict research coverage unless a separate signal
window can be proven without weakening it. Document manifest recovery.
F5: compare action previous-close facts against the previous verified raw DAY.
F6: invalidate stale dispatch views and expire cached VERIFIED claims.
Also independently test the BROKER_SIMULATION discriminator, check the legacy
`sinopac=False` route, and record arrival-time and slippage semantics.

No desktop edits, LIVE path/setting, real keys/CA/network tests, G3/pin/workflow
changes, weakened assertions, automatic retry, resume or fabricated market rows.

New files planned: this contract, `tools/import_official_daily.py`, operational
import instructions, focused source/cache/import/runtime integration test modules
and review-verification evidence. Product helpers may be split by responsibility
if needed; final new-file list belongs in the PR. Generated baseline inventory
updates happen once after functionality, in a separate commit.

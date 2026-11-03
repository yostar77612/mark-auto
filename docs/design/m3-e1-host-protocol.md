# M3 E1 trusted-host implementation contract

Protocol: `m3-prospective-e1-v1`. Decision and limits:
[ADR 0007](../adr/0007-prospective-e1-qualification.md).
This replaces neither historical research results nor the display-only WF verdict.

## Host interface

`E1QualificationHost(workspace, registry_path=...)` takes the research state
workspace and the existing separate bootstrap control authority. Neither location
may be supplied by an AI/tool result. Symlinked paths and a registry inside
restorable state refuse. Use the same authority selected by `research_controls`;
a fresh location does not establish historical provenance.

1. `freeze(campaign_ref=..., contract_id=..., signal_spec_json=..., calendar=...,
   config=..., evidence_mode='production') -> reference` freezes and consumes the
   future window. The source endpoint and evaluation policy are fixed by code,
   not model/user JSON. Unsupported stop/target/quantity parameters refuse.
2. Later, explicitly invoke `capture(reference, network_authorized=True)` on the
   host while the official report is available. It returns `None`, not data,
   counts or metrics. Repeated already-captured identical rows are not overwritten;
   a no-new-session response is not an evaluation. There are no implicit retries.
3. After every declared session was captured, explicitly invoke
   `evaluate(reference)`. It returns `None`; it never returns a backtest payload.
   The local reader is the only E1 summary projection. Failed/in-progress/unknown
   attempts cannot resume or retry. `cancel(reference)` retains consumed coverage.
4. Construct `ResearchWorkspaceCandidateCatalog(workspace,
   qualification_registry=authority)`. Alternatively a trusted composition can
   inject `read_e1_summaries(workspace, registry_path=authority)`. Supplying both
   registry configuration and a custom reader is rejected. No default path is
   guessed, and old JSON/sidecar/WF claims cannot supply qualification.

The API is host-only. No command is registered with the AI harness or added to
UI/IPC schemas. In this change there is no automatic capture, evaluation or LIVE
transition and no true-market execution. Future owner operation and separate
integration determine when this flow runs.

## Persistence and frozen inputs

`reservations` and `coverage` remain the existing schemas. E1 reserves a prospective
coverage identity; it does not pretend that future bar contents already exist.
`e1_plans` and `e1_captures` are separate versioned records in the same authority.
The exact observed dataset is frozen durably before the evaluation worker starts.

The initial reservation first enters `committing`. Only a post-commit timestamp
before the first observation changes it to `reserved`; a crash/late commit cannot
be retried. Capture exclusively claims `capturing` before the request and moves
to quiescent `captured` only after a successful append. Evaluation and another
capture refuse while a capture is in flight; an interrupted capture is consumed
and cannot resume. Only sessions closed before request start are admitted.
Completion admission changes to
`evaluating` once; a valid receipt atomically changes it to `completed`. All
failure/cancellation/unknown states retain reservation coverage and cannot confer
E1. Receipt creation cannot occur from a display-only verdict or a mixed strategy.

The receipt contains only protocol/reference/plan/dataset/source hashes, actual
completion timestamp, verdict, sample count and result hash. The reader checks
all bindings against the same read transaction and the current source version.
Historical terminal rows remain reserved but are not active evidence. Old-source
receipts are ignored, never upgraded. Hash checks detect inconsistent records;
they do not authenticate a registry coherently rewritten by an attacker.
Stored captures and results are never AI conversation/tool/prompt material.

## Files and verification scope

- `trading/runtime/e1_protocol.py`: strict prospective plan/policy/source bindings.
- `trading/runtime/e1_store.py`: shared atomic irreversible authority.
- `trading/runtime/e1_source.py`: bounded fixed-source host HTTPS capture/import.
- `trading/runtime/e1_qualification.py`: freeze/capture/single evaluation/receipt.
- `trading/runtime/e1_reader.py`: metadata-only readonly E1 projection.
- `trading/runtime/candidate_catalog.py`: explicit registry composition option.
- `research.py`: new-campaign atomic OOS-plus-holdout accounting.
- `saved_candidate_pool.py` and saved-pool validator: additive producer profile
  and producer-specific union verification; historical profiles unchanged.
- Packaging includes exact provenance source bytes for the new reader/evaluator.

Focused verification covers prospective dates and session timing, commit-clock
crossing, exact spec/source/dataset identity, complete capture, shared overlap,
concurrency, interruption, failure/no retry, real synthetic bounded evaluation,
receipt tampering, readonly payload denial, historical compatibility, explicit
network action, redirect/size refusal and dynamic AI/log leakage sentinels.
Synthetic checks do not certify market profitability, native Windows packaging,
UI integration or any real user's dataset. Formal acceptance score is unchanged.

The historical UI registry golden remains unchanged. The additive
`tests/fixtures/ui_operations_e1_exposure_delta.json` changes exactly four expected
leaves: `holdout_registry.holdout_hash` and `reservation_id` for the synthetic
240-bar fixture and 241-bar mock subscription campaign. Their reservation now
covers OOS plus holdout, rather than holdout alone. Tests pin the delta, derive
both old and new identities independently from synthetic bars and coverage,
reject tampering, and assert the new identities on every platform. All other
golden values, exact Windows comparisons, and old-dispatcher/registry equality
remain intact; observed hashes are never masked or rewritten.

## Independent branch integration

This branch's `E1_EXPOSURE_PROFILE_V1` binds its current research source tuple.
A separate stock branch changes core/backtest sources. Combining those branches
requires ONE new combined exact-source profile and consolidated baseline commit;
neither standalone profile can be relabeled as evidence for the combined runtime.

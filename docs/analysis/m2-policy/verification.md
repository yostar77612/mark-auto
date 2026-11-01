# M2-0 policy verification

Date: 2026-11-01, Asia/Taipei.

Policy and exact D1 baseline changes are implemented. Focused checks and
both actual offline application launches passed. Final complete local
discovery has only reviewed failures already present on main; its nonzero
result is documented below, not described as passing. PR #128 source head
`97e2a8b` passed all35 CI checks; the documentation-only delivery commit
will receive its own remote checks.

## Tested source and scope

| Item | Identity |
|---|---|
| Base | `origin/main`, `045313634a6fe4c33aeacfc972182d00e83cd58e` |
| Branch | `codex/m2-0-policy` |
| Policy/banner source commit | `7e8df5b` |
| Separate D1 baseline commit and frozen tested head | `97e2a8bd1c774fff9d90f9b5d973048efc112fd3` |

Owner decision D1 dated 2026-11-01 changes v2 policy to **production orders
disabled by default**, with future enablement requiring a separate explicit
owner decision. M2 must keep production orders hard-disabled; no LIVE opt-in
is introduced. The v1 research/Paper real-order prohibition remains permanent.
M2 authorizes subsequent SinoPac simulation-order implementation and
verification; this policy PR does not enable execution or alter any runtime
gate.

README, contributor safety/mission guidance, the upgrade contract, six ADRs,
glossary and PR risk checklist express this distinction. The two equivalent
existing banner records display `研究模式・正式下單停用`; their keys, phase/order
values and aliases are unchanged. Baseline changes are a separate commit:
five exact catalog snapshot values, explicit overrides of the two banner
digests, the one historical banner alias, one R7 accessible-name row and one
banner row in each of four refresh states. Only the two existing R7 observer
line fields move from 73 to 74 because the M2 fixture declaration adds a line.

Historical alias provenance and bytes, `r7_base`, original safety-message
digests, all eight result snapshots, painter pixels/counts, call order, errors,
row multiplicities, visibility/enabled flags and unrelated expected values
remain pinned. The ADR safety test remains present, now asserting the exact
new policy phrase plus the D1 date/authority; original OOS, timeout and
acceptance checks remain.

M2-1/M2-2 are outside this PR. The owner's follow-up assigns the market-settings
fix to this implementation run: complete its PR and green CI, then continue
M2-1/M2-2 on the dependent branches without waiting for a main merge.
The updated specification and M2-8 cleanup are now included in round one.
Round-two automatic-trading work requires
the owner's first-round acceptance and a separate start. No actual SDK login,
CA activation, external financial operation or real credential use is part of
this verification.

## Focused and static checks

Commands ran from the policy checkout with `QT_QPA_PLATFORM=offscreen`,
`PYTHONUTF8=1` and `PYTHONPATH=<policy-checkout>/tests;<policy-checkout>`.
The provisioned interpreter was
`C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe`.
Each module below ran separately using
`python -m unittest discover -s tests -p <module>.py -v`.

| Module | Passed tests |
|---|---:|
| `test_adr_glossary` | 4 |
| `test_glossary_terms` | 7 |
| `test_desktop_text_aliases` | 9 |
| `test_desktop_catalog_split` | 2 |
| `test_r7_characterization` | 15 |
| `test_docs_layering` | 8 |
| `test_repo_layout` | 29 |
| `test_header_c1` | 6 |
| `test_idle_hint_u1` | 4 |
| `test_b4_appearance` | 9 |
| `test_page_services_r1` | 15 |
| `test_m1_ui_defects` | 6 |
| `test_ui_redesign_shell` | 11 |
| `test_ui_redesign_strategy` | 12 |
| `test_ui_redesign_preview` | 5 |
| `test_ui_redesign_paper_settings` | 7 |
| `test_ui_redesign_data_results` | 10 |
| `test_download_auto_import_contracts` | 4 |
| **Total: 18 actual modules** | **163** |

All 18 module runs exited 0. Two initially mistyped, nonexistent module patterns
ran zero tests; they were corrected and are excluded from these counts.

`pwsh -NoProfile -File tools/prepush.ps1 -Tests -Base origin/main` passed:
Ruff check and format (1,100 files), the Python 3.11 syntax scan (1,037 sources,
zero failing), static/credential gate (zero findings), and **41 selected tests
in 6.055 s**. `tools/check_layers.py` separately reported zero findings.
The 41 selected tests overlap the focused runs; these are separate scopes,
not 204 distinct tests and not full discovery.

Before each commit, GitNexus `detect_changes(scope=all)` completed without
partial/truncation flags: source 24 symbols / 15 files / LOW; baseline 11 symbols
/ seven files / LOW. Upstream UNKNOWN results for literal record assembly and
unittest methods were checked against direct source and text references.
Graph results do not substitute for tests.

## Actual application startup checks

These checks used the original `trading_runtime._run_window` composition and
real `TradingWindow` constructor at frozen head `97e2a8b`, with disposable
trading/research roots. Instrumentation delegated the original constructors
and composition. The interpreter was the existing
`C:/Users/Mark/Desktop/Mark auto/.runtime-sqlite/python.exe -S`, with the tested
checkout, tests and existing venv site-packages explicitly added to `sys.path`.
The recorded SQLite runtime was 3.54.0. No dependency was installed or changed.

| Check | LOCAL | BROKER_SIMULATION with fake SDK |
|---|---|---|
| Actual `_run_window` return | 0 | 0 |
| Elapsed | 6.375 s | 5.138 s |
| Visible real window | `TradingWindow` | `TradingWindow` |
| Embedded research | Seven pages, 2,726 widgets | Seven pages, 2,726 widgets |
| Observed engine state | `WAITING_RECONCILIATION` | `WAITING_RECONCILIATION` |
| Financial facts verified | true for synthetic LOCAL book | false, retained honestly |
| Research released / engine shutdown clean | true / true | true / true |
| Real Shioaji imported | false | false |
| Recorded errors | none | none |

The broker check used a real authenticated named-pipe server in an owned
thread with an injected fake SDK: **one login, one logout, two subscriptions,
zero order constructions and zero orders**. This proves offline composition
and release, not real broker permissions, CA requirements or execution.
Before/after evidence retained the same tested head and clean tracked source.

The disposable embedded-research bootstrap uses the neutral directory name
`v1-bootstrap`. Correcting the earlier probe's bootstrap path changed only
the harness input; it did not change product path guards, settings, runtime
code, permissions or execution gates. These offscreen launch checks do not
claim native human visual, DPI or broker acceptance.

Local evidence is in
`.worktrees/m2-launch-probe/.tmp/m2-0-97e2a8b/`: `local/result.json`,
`broker/result.json`, launch logs, before/after head and tracked-status records.

## Complete unchanged-main baseline

The exact main run completed before the policy suite began:

**3,888 tests in 1,968.015 s; FAILED (failures=10, errors=27, skipped=42).**

All 37 traceback occurrences were reviewed; they represent 36 distinct IDs
because one symlink case has two subtests. The 42 skips are baseline skips,
not newly added applicability exceptions. The concise categories are:

| Category | Occurrences | Evidence limits |
|---|---:|---|
| Synthetic symlink creation | 20 ERROR, 19 IDs | Every traceback directly ends in WinError 1314 before the intended product rejection check. |
| Initial LOCAL runtime launch | 5 ERROR | Four context-client cases and one runtime class hit `ensure_engine`'s original startup deadline. Wrapper/session PID mismatch is directly proven for the class fixture; the other four per-case PIDs were not logged. |
| Native worker cleanup | 1 ERROR | WinError 32 removes a still-owned worker log after its case-body checks; exact holder not captured. This block does not prove a DuplicateHandle error. |
| Crash-driver process identity | 1 ERROR | Actual PID 306352 differs from retained Popen PID 256312, followed by WinError 32 cleanup. |
| Paper probe parent ownership | 4 FAIL | Exit1 before checkpoints; the same source/test bytes were previously diagnosed with the parent-PID guard. This run discards child stderr, so no fresh stderr capture is claimed. |
| Named mutex visibility | 3 FAIL | OpenMutex returns HANDLE 2448 and later cases observe the named object. The owner is unidentified; a HANDLE is not a PID, and the failed assertion can retain it for later cases. |
| Retained grandchild handle | 3 FAIL | Direct DuplicateHandle Errno 6, then failed cooperative cleanup; consistent with the documented redirector handle-table mismatch. |

No unrelated new failure ID/exception family or native access violation was
found in this main run. These are baseline observations, not blanket waivers
for branch failures. Complete branch identities and actual traceback evidence
must be compared, and mandatory remote CI must be checked independently.
The durable companion `main-host-baseline.md` must retain the exact-ID list,
complete result and evidence limits before this document is finalized.

The main runtime-class fixture published session PID **333180**, while the
retained `.venv` wrapper PID was **307132**, launched by the full-suite Python
PID **48188**. It therefore cannot satisfy the unchanged exact-PID startup
guard. For only this exact disposable fixture, the coordinating cleanup agent
subsequently obtained an authenticated `WAITING_RECONCILIATION`, version 1
snapshot, then received an accepted `SHUTDOWN_ENGINE` and confirmed `CLOSED`,
version 2. All three owned fixture PIDs were confirmed gone. No forceful
termination, user-process action or data deletion was used. This later
authenticated observation confirms the fixture was responsive; it does not
retroactively turn its failed startup test into a pass or prove the other
four startup cases individually healthy.

## Final complete branch discovery

The coordinating agent serializes full suites. Policy discovery runs only
after the complete main baseline, on frozen clean head
`97e2a8bd1c774fff9d90f9b5d973048efc112fd3`, using:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = '<policy-checkout>/tests;<policy-checkout>'
& 'C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe' -m unittest discover -s tests -v
```

**Final complete retry: 3,888 tests in 2,380.898 s; FAILED (failures=10, errors=27, skipped=42).**

All 36 distinct failure identities already occur in
the measured main baseline. Exact traceback comparison and independently
reviewed variants are recorded in [full-comparison.md](full-comparison.md).
The same tested head and clean tracked source were retained throughout.

All37 traceback blocks match main's ordered file/line/function frames and
exception-type chains; all19 referenced repository sources are byte-identical.
The coordinator also checked the actual exception messages and causal chains:

| Occurrences | Final retry evidence |
| ---: | --- |
| 20 | WinError1314 while creating the synthetic symlink, before product rejection assertions;19 IDs, with both archive-name and orphan-name subtests retained. |
| 5 | The same initial LOCAL `ensure_engine` deadline:four context-client cases and the IndependentEngineRuntime class setup. |
| 1 | Native worker cleanup raises WinError32 for worker-0.log; exact holder is still unproven. |
| 1 | E06 first reports actual198848 versus retained98320, then WinError32 on simulated-exchange-v2.sqlite; same primary/secondary families and frames as main. |
| 3 | Named mutex remains visible; HANDLE3208 is not a PID. The later installer cases reject a preexisting lifetime before creating their native fixtures. |
| 4 | Paper probes exit1 before checkpoints; cleanup is recorded and the same unchanged-source prior parent-PID diagnosis applies, without claiming fresh child-stderr evidence. |
| 3 | Retained-grandchild DuplicateHandle Errno6 and unconfirmed cooperative cleanup, matching main. No already-signaled variant occurs in this retry. |

Temporary paths, generated archive IDs, process/handle numbers and elapsed
measurements differ as expected between runs. Matching normalizes only the
generated16-hex archive component in the subtest label. Full raw logs remain
unchanged. One earlier comparison-summary field reused the sibling subtest's
exception text; it was corrected from the already retained, correctly matched
raw traceback. Both real subtests raise1314, and this correction changes no
test identity, frame/type result, source or verdict.

The final log's SHA256 is
`e766c5ffa28256b2b1fdb600c38cacf242ac863df677021c10955fee74162e5c`.
The original complete main log's SHA256 remains
`9de08cc417a5927ce1b0c9fc868a2bfc1fef06fb07032892a969ae22b27f5fc3`.
The previously additional smoke cleanup-marker case now explicitly reports
`ok` in this complete run; its original assertion and1s deadline are unchanged.

After the full runner224972 exited, fresh process inspection revalidated only
the disposable class fixture:wrapper155812/native268268, their parent chain,
creation times and exact `v2-runtime-os87smf1/isolated` root. Its authenticated
LOCAL snapshot was WAITING_RECONCILIATION/version1. Normal SHUTDOWN_ENGINE was
accepted and returned CLOSED/version2; both exact processes were then confirmed
gone. No forceful termination, user application control or data deletion was
used. This verifies that one fixture's later normal cleanup, not a passing
startup test or the individual health of the other four failed launches.

The owner-installed application remains outside this cleanup. The result is
the same nonzero host baseline, not an all-passing local suite. Source PR128's
remote35/35 result and final documentation-head CI are separate checks.

The first complete run had one additional smoke stderr-marker failure;
it was not waived. The unchanged test passes in this final full retry.
[first-full-comparison.md](first-full-comparison.md) retains the initial
failure and evidence limits. An intervening restricted-context attempt
never completed and is excluded; its exact tempfile permission-loop
diagnosis and owned-runner shutdown are recorded in
[retry-execution-context.md](retry-execution-context.md). No assertions,
timeouts, skips, ACLs or dependencies were changed to obtain the retry.

Remote source CI: [PR #128](https://github.com/yostar77612/mark-auto/pull/128),
[run41276871367](https://github.com/yostar77612/mark-auto/actions/runs/41276871367),
attempt1, exact97e2a8b, all35 checks SUCCESS. Final documentation-head CI
is tracked separately in the PR and first-round run report; source-head
success is not represented as final-head success.

## Protected-source audit

The coordinating audit `.tmp-m2-qa/protected-audit.json` compares `97e2a8b`
against exact main `0453136`: **all 30 G3 source blobs are equal**, as are
`docs/agent/PROJECT_STATE.md` and `docs/agent/ACCEPTANCE.json` (32 protected
blobs total). It also records the **entire `quantlab` tree as identical**.
The broker SDK pin, domain/application/adapter/runtime execution logic,
historical producer profiles, OOS/budget/timeouts and acceptance score
therefore remain unchanged by this policy PR. Only the approved two UI string
records, policy documents and separately reviewed baselines differ in the
relevant scope. No main merge, history rewrite or financial operation is
authorized by this verification document.

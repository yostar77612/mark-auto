# Standalone clean Windows client acceptance kit

Status: **EXTERNAL BLOCKED until actually executed on both clean target VMs**.
The target needs only built-in x64 Windows PowerShell 5.1, an interactive desktop,
and the extracted kit. No Python, pip, Git, compiler, source checkout or broker
account is required. `clean_windows_kit.py` runs only on the maintainer's machine.

## Build the kit (maintainer)

Obtain baseline 0.2.1 and candidate 0.2.2 installers plus their original
`build-manifest.json` from their verified exact-commit GitHub release/CI artifacts.
Put each installer next to its own manifest in separate folders. Verify the
release URL, source commit and published SHA256 independently first. Hashes
inside a downloaded manifest alone are integrity checks, not publisher identity.
Do not substitute the 0.0.0 same-payload installer fixture for historical upgrade.

    python packaging/clean_windows_kit.py --baseline BASELINE_DIR --baseline-version 0.2.1 --candidate CANDIDATE_DIR --version 0.2.2 --output clean-client-kit

The assembler rejects mismatched installer hashes, absent source digests,
same-version/reversed upgrades and identical commits/installers. It copies the
existing lifecycle harness, not a second implementation. Each installed version
is checked against its own six engine source hashes and app version. Retain the
kit.json SHA256 alongside the verified release records and archive the complete
kit. The manifest includes neither credentials nor license keys.

## Provisioning and license boundary

Use **two disposable fresh client VMs**, one Windows 10 22H2 x64 (build 19045),
one Windows 11 x64 (record exact build). Use official media with a valid existing
license or permitted Microsoft evaluation. An ISO download is not a free license.
A human must review and accept any new license agreements first. This kit does
not register accounts, accept OS agreements, bypass activation/TPM, buy anything,
start paid trials or disable security controls. Server and ARM clients do not
meet these targets. Developer VM images are not clean even if PATH is trimmed.

Before installing developer tools or MarkAuto, create an ordinary standard-user
account and a VM snapshot. Record ISO SHA256/source, OS edition/build, activation
or evaluation validity (no product keys), hypervisor, RAM/CPU and snapshot ID.
Use a Chinese-named account/path for one run; preserve a normal Latin-path run
as well. Keep Windows security defaults. If unsigned-installer security controls
block execution, preserve the exact warning and report BLOCKED; do not disable
protections or prescribe a warning bypass. No live broker credentials or money.

## Run the automatic subset

Extract a fresh copy of the kit. From **non-elevated x64 Windows PowerShell**:

    & .\packaging\clean_windows_acceptance.ps1 -Target Windows10-22H2 -SnapshotReference 'win10-19045-clean-001' -DisposableVmConfirmed -LicenseAlreadyAccepted

For the other VM, use `-Target Windows11` and its actual snapshot reference.
Do not set system-wide ExecutionPolicy or disable security to make it run. If
local script execution policy blocks the kit, report that restriction separately
and use the organization's approved execution route. Never run this test against
a real working profile: it installs/upgrades/uninstalls the app and creates test
data. Preflight refuses existing app/data/shortcuts and detected developer tools.
It cannot prove an entire machine's software history; clean-image provenance and
operator attestation are mandatory in addition to machine checks.

`dist/validation/clean-client-results.json` is the authoritative wrapper result.
Exit 1 means failed execution; exit 2 means EXTERNAL BLOCKED, including when the
automated subset passes but full acceptance is incomplete. Existing evidence is
never overwritten. Restore the original VM snapshot and use a fresh kit for a
repeat. No automatic cleanup of application data occurs after failure/success.

The reused harness records install logs, both source-hash maps, fixture smoke
reports, shortcut launch/window, same-process active-upgrade/uninstall refusal,
normal close, uninstall and preservation of a unique test sentinel. Its legacy
`client_os_acceptance=BLOCKED` and CI performance scope labels remain conservative;
wrapper OS evidence identifies the actual client. Timing is an observation, not
an SLO or claim of full usability. Lifecycle passing proves sentinel preservation,
not migration of all real saved application state.

## Full manual acceptance (separate snapshot/run per OS)

Record each row as PASS/FAIL/NOT_RUN/EXTERNAL BLOCKED with UTC time, versions, exact
steps, expected and actual outcomes, and evidence filenames. NOT_RUN means the case
was not executed; EXTERNAL BLOCKED means a named external prerequisite prevented
execution. FAIL means an executed case contradicted its expected outcome. Never
replace missing evidence with PASS. Record both OS rows independently. Capture
screenshots without credentials.
Keep automatic results untouched; add `manual-results.json` and evidence alongside
an archived copy. This script never reads a manual checklist and promotes itself
to full PASS. A reviewer reconciles the complete evidence and outstanding blockers.

1. Normal installer wizard: install as standard user; exact path/version, visible
   license/publisher warning, no admin request, shortcuts and Installed Apps entry.
2. Launch each shortcut separately; all navigation pages render. Record first
   window latency, idle memory, 100%/150%/200% display scaling, Chinese input/path,
   resize, close and reopen. No cut-off controls or blank dialogs.
3. Offline demo/import: load bundled synthetic example via UI; verify synthetic
   label, timezone/contracts/calendar, invalid input diagnostics, no data loss.
   Import a malformed file and cancel file selection; previous state persists.
4. Backtest/report: run UI workflow, inspect equity/trades/metrics, switch reports,
   export then reopen. Record actual files and compare values to the same fixture.
5. Campaign: fixture provider run, progress/cancel/retry and repeated-click controls;
   selection/ranking/provenance and failures visible. Fixture remains visibly
   synthetic, `real_model_status=not_verified`, never advertised as real AI.
6. Paper: reconcile a synthetic account, replay, pause, continue, kill switch,
   duplicate events and close/reopen; no external order route. After interrupted
   close/crash or sleep/resume require reconciliation; capture exact state.
7. Persistence and historical upgrade: on baseline 0.2.1 create/export representative
   saved settings, imported dataset, backtest/report, campaign, paper journal and
   backup using UI. Record file hashes and expected semantic contents. Close app,
   install 0.2.2, reopen each item and verify compatibility and preservation. Test
   backup restore to a disposable location, cancelled restore, corrupt/incompatible
   state rejection and recovery without overwriting original data. A sentinel
   alone does not pass this row. Preserve before/after manifests and reports.
8. Refusal/recovery: while running a job attempt upgrade/uninstall, ensure explicit
   refusal and continuing app/job. Cancel/close manually, repeat normally. Do not
   force-kill real work. Record interrupted test recovery separately.
9. Uninstall through Windows Settings; verify executable, shortcuts and app entry
   removed while saved data remains. Reinstall and verify preserved data opens.
10. Official ChatGPT subscription validation: execute the 12-case checklist below.
    No local model, API-key provider, paid API or credits fallback is permitted.
    Real owner authorization and actual completed responses are separate evidence
    from fixture/parser tests. An unavailable owner grant is EXTERNAL BLOCKED.
11. Real market correctness: cite authorized official data snapshots/checksums,
    contract/session/fees/margin and independent expected results. Synthetic replay
    is insufficient. No funded account, real orders or paid market data.

### Official subscription acceptance: 12 required cases on each client

Use the same verified candidate installer and record its exact source commit and
SHA256. Keep existing automatic results untouched. Record each case independently
on Windows 10 22H2 x64 and Windows 11 x64; one client's result cannot qualify the
other. The automatic lifecycle wrapper stays EXTERNAL BLOCKED until a reviewer has
reconciled all required evidence. This checklist does not make the wrapper read a
manual file or promote itself to PASS.

Only the owner may complete the interactive official sign-in and grant. Never use
copied browser tokens, session cookies, an API key, a local model, or a substitute
account to claim the owner's subscription works. Before inference, verify the
owner's official account settings prohibit paid overage/credits and record that
check without secrets. If included-only use cannot be established, stop before
inference and record EXTERNAL BLOCKED; a warning or checkbox is not proof of a
zero-charge route. Model discovery is not completed inference. No broker account,
funded order, paid market data, new purchase, or security-warning bypass is needed.

1. **Launch without Qwen/Ollama.** From the fresh standard-user snapshot, install
   and launch the candidate without installing Qwen, Ollama, llama.cpp, a GGUF
   model, or a model server. Record the installed-program check, first window and
   installer payload inventory. No local-model download or startup prompt occurs.
2. **Non-AI independence.** With no model runtime and AI disconnected, exercise
   offline import, charts/indicators, built-in strategy editing, deterministic
   backtest, saved-result comparison, paper replay, settings, backup and restore.
   Record individual results and close/reopen preservation. Use labeled synthetic
   fixtures where appropriate; this does not certify real-market correctness.
3. **Start official login.** In the subscription settings, initiate a connection
   and open the official authorization page. Record the verified official origin,
   cancellation and retry behavior. A started page can pass this case but cannot
   pass cases 4–9; those require the owner's completed real grant.
4. **Accurate authorization state.** The owner finishes sign-in/authorization.
   Confirm the UI shows the selected connection's actual state, then close/reopen
   and inspect it again. Cancelled, incomplete, expired and signed-out states must
   not appear ready. Record only masked identity/status, never tokens or codes.
5. **Actual available models.** Explicitly discover models for that connection
   and select one returned by the official service. Record the selected model and
   discovery time; an invented, fixture or stale catalog is insufficient.
6. **Completed AI response.** Preview the allowed research inputs and set explicit
   request/runtime limits, then authorize one bounded real subscription run. Keep
   sanitized durable request/response hashes, final status, observed usage (or
   unknown), selected model and input provenance. Only a complete, validated
   response passes; partial streams, timeouts and parser fixtures do not.
7. **Generate and save strategies.** Use multiple selected strategy families
   within the approved budget. Verify validated candidates, immutable versions,
   provenance and failures are saved and can be reopened from research history.
   Record strategy/campaign identities and saved-file hashes. A renamed built-in
   or fixture candidate is not evidence of an actual model-generated strategy.
8. **Deterministic backtest handoff.** Select a saved AI candidate in the ordinary
   UI and run the local backtest. Verify the exact strategy/data/config hashes,
   trades, costs and metrics against deterministic engine output; reopen the
   result. AI text must not replace engine calculations or gain order authority.
9. **Analyze and improve results.** Ask the subscription AI to analyze permitted
   train/validation results, identify weaknesses and risks, and propose a distinct
   version. Verify visible saved analysis, parent/version links, unchanged user
   risk controls and deterministic re-evaluation. Compare saved strategies and
   their explanations. Check the actual submitted inputs exclude OOS/holdout
   feedback from generation/improvement; screenshots of metrics alone cannot pass.
10. **Quota and expired authorization.** Clearly labeled deterministic
    fault-injection tests are valid evidence for error handling: pause on
    quota/eligibility failure, show actionable expired-grant status, require
    explicit recovery, and prevent implicit replay or refund of unknown/completed
    requests. Record the exact tested build, injected conditions and observed
    behavior. These tests cannot substitute for the real OAuth/inference success
    evidence in cases 4–9. Real service error observations are supplementary;
    record them when safely available, or mark them NOT_RUN without creating an
    additional acceptance barrier. Never exhaust quota deliberately or revoke
    another session solely to obtain evidence.
11. **No extra paid route.** Verify no API key or API billing route is selected,
    included-only account policy is established before calls, and failures never
    fall back to paid API or credits. Retain sanitized endpoint/receipt evidence
    plus the official account's before/after usage evidence where available. A
    mock transport, missing invoice, or `paid_api_fallback=false` field alone does
    not prove this case. Unverifiable charge policy remains EXTERNAL BLOCKED.
12. **Windows installer usability.** For each target, retain normal installer,
    shortcut, all-page rendering, Chinese-path, display-scaling, close/reopen,
    upgrade and uninstall evidence from the manual/lifecycle checks above. Verify
    saved research survives permitted lifecycle operations. Windows Server CI or
    an offscreen Qt run is supporting evidence, not Windows 10/11 client acceptance.

For every case, add an entry to the existing separate `manual-results.json` with
the following shape (repeat for each OS and case; leave unavailable facts null):

```json
{
  "case_id": "subscription-06",
  "target": "Windows10-22H2",
  "os_build": null,
  "candidate_version": null,
  "candidate_commit": null,
  "installer_sha256": null,
  "snapshot_reference": null,
  "status": "NOT_RUN",
  "evidence_kind": "none",
  "started_utc": null,
  "finished_utc": null,
  "owner_grant_completed": false,
  "included_only_policy_verified": false,
  "model": null,
  "steps": [],
  "expected": "One authorized subscription request returns complete validated output.",
  "actual": "Not executed.",
  "blocker": null,
  "evidence_files": []
}
```

Use `evidence_kind` values `real_client`, `real_subscription`, `offline_fixture`,
or `none` accurately. Supporting fixtures never replace real OAuth/inference
success in cases 4–9; case 10 explicitly permits deterministic fault injection.
Judge PASS against the checks stated in each of these 12 fixed required cases;
supplementary or hypothetical scenarios do not create new gates. Record their
results separately when useful. Redact credentials, cookies,
authorization URLs containing temporary secrets, account identifiers and personal
data from screenshots/logs before archiving. Preserve hashes and nonsecret status
fields needed to trace a result. If grant access or a suitable Windows client is
unavailable in the current environment, name that blocker and retain a reproducible
NOT_RUN/EXTERNAL BLOCKED record instead of performing an unauthorized inference.

Archive kit.json, both original build manifests, OS/snapshot records, complete
validation directory and manual evidence with a SHA256 listing. Full functionality
remains BLOCKED while any required row lacks trustworthy evidence on either target.

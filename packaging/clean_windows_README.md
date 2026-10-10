# Standalone clean Windows client acceptance kit

Status: **EXTERNAL BLOCKED until actually executed on both clean target VMs**.
The target needs only built-in x64 Windows PowerShell 5.1, an interactive desktop,
and the extracted kit. No Python, pip, Git, compiler, source checkout or broker
account is required. `clean_windows_kit.py` runs only on the maintainer's machine.

## Build the kit (maintainer)

Obtain baseline 0.2.0 and candidate 0.2.1 installers plus their original
`build-manifest.json` from their verified exact-commit GitHub release/CI artifacts.
Put each installer next to its own manifest in separate folders. Verify the
release URL, source commit and published SHA256 independently first. Hashes
inside a downloaded manifest alone are integrity checks, not publisher identity.
Do not substitute the 0.0.0 same-payload installer fixture for historical upgrade.

    python packaging/clean_windows_kit.py --baseline BASELINE_DIR --baseline-version 0.2.0 --candidate CANDIDATE_DIR --version 0.2.1 --output clean-client-kit

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

Record each row as PASS/FAIL/BLOCKED with UTC time, versions, exact steps, expected
and actual outcomes, and evidence filename. Never replace missing evidence with
PASS. Record both OS rows independently. Capture screenshots without credentials.
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
7. Persistence and historical upgrade: on baseline 0.2.0 create/export representative
   saved settings, imported dataset, backtest/report, campaign, paper journal and
   backup using UI. Record file hashes and expected semantic contents. Close app,
   install 0.2.1, reopen each item and verify compatibility and preservation. Test
   backup restore to a disposable location, cancelled restore, corrupt/incompatible
   state rejection and recovery without overwriting original data. A sentinel
   alone does not pass this row. Preserve before/after manifests and reports.
8. Refusal/recovery: while running a job attempt upgrade/uninstall, ensure explicit
   refusal and continuing app/job. Cancel/close manually, repeat normally. Do not
   force-kill real work. Record interrupted test recovery separately.
9. Uninstall through Windows Settings; verify executable, shortcuts and app entry
   removed while saved data remains. Reinstall and verify preserved data opens.
10. Real AI/provider validation: only authorized free provider path; record model,
    request/response provenance and candidate validation with secrets redacted.
    If no authorized zero-cost provider, BLOCKED. Fixture output is insufficient.
11. Real market correctness: cite authorized official data snapshots/checksums,
    contract/session/fees/margin and independent expected results. Synthetic replay
    is insufficient. No funded account, real orders or paid market data.

Archive kit.json, both original build manifests, OS/snapshot records, complete
validation directory and manual evidence with a SHA256 listing. Full functionality
remains BLOCKED while any required row lacks trustworthy evidence on either target.

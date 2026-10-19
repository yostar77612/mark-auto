# T15 — P3-04, P3-05, P3-06, P3-08

## Decisions

- Settings → About → version maintenance adds explicit update and old-program-version checks. Cleanup
  is offered only from the supported frozen executable location:
  `%LOCALAPPDATA%\Programs\MarkAuto\payloads\<version>\<unique-name>`.
  It deletes direct version directories (all attempts within them), keeping the
  current version and newest strictly older version. Other versions, including
  newer directories, are candidates named in a default-No confirmation.
  Retained-version duplicate attempts are not pruned.
- Canonical numeric versions accept two/three components (1.0, 0.2.2). Leading
  zeroes, prereleases, traversal, duplicate normalized versions, unknown entries,
  missing current directory, permission errors, links/junctions/reparse points
  anywhere in the tree or ancestors, and resolution outside root refuse the
  whole plan. Roots cannot be inside the default user
  workspace. Plans record filesystem identities and revalidate before execution
  and immediately before each rmtree. Errors stop; a failed candidate may be
  partially removed. This is not an atomic defense against hostile same-user
  filesystem races. No user workspace or sibling is a deletion target.
- Updates run on a daemon thread only after clicking; a Qt timer polls its queue
  and the button is disabled until completion. No startup/periodic check,
  installer download, process/browser launch, file write, cookie or telemetry is
  introduced. The existing Releases link remains a separate explicit action.
- Release convention: publish `release-manifest.json`, containing
  `{"version":"0.2.3"}`, and `release-manifest.json.sha256`, containing 64 hex
  digits optionally followed by two spaces and `release-manifest.json`.
  The default placeholder uses the project's GitHub `releases/latest/download`
  manifest URL. Transport returns `(body_bytes, sidecar_text)`; SHA-256 is checked
  before JSON is parsed. Limits: JSON 64 KiB, sidecar 256 bytes, timeout eight
  seconds per request (two requests, bounded urllib redirects). Verified TLS uses
  `build_trust_context()`; HTTP downgrade redirects are refused. User-Agent is
  generic and contains no identity or installed version. SHA-256 proves content
  consistency, not publisher authenticity; errors never announce an update.
- Signing is [documentation only](../../packaging/SIGNING_CHECKLIST.md).
  Nothing is signed today; installer and build are unchanged.
- Streamlit gains only a notice after its title: developer research workspace;
  the desktop app is the product. No imports or logic changed. Tests inspect the
  notice, original imports and packaging exclusion. A direct comparison against
  HEAD verifies the AST is identical after removing the notice.

## Pending external evidence / deferred work

| Item | Pending evidence |
|---|---|
| Real update server unavailable | Publish both manifest assets, verify real HTTPS responses and release selection. Offline tests do not establish live server readiness. |
| Real installer upgrade run | Controller runs full regression and disposable Windows upgrade/recovery validation, including the frozen cleanup layout. No real installation or user data used here. |
| Signing certificate | Acquisition, protected CI signing, final exe/installer verification and signed lifecycle tests remain outstanding. |

The optimization plan is unchanged; no acceptance score is raised for pending
evidence. G3 sources and existing assertion strength are unchanged.
GitNexus: build_settings LOW (SettingsPage constructor caller); shared catalog
CRITICAL (42 upstream files), new keys plus one static About wording correction;
research_app UNKNOWN, checked
directly as a standalone entry with packaging references. Index refresh failed
with sandbox child-process spawn EPERM. Focused verification is recorded in
ACCEPTANCE.json; full existing regressions are controller-owned.

Default Settings button count remains 8: a visible version-maintenance disclosure
reveals the two actions without exceeding the existing default button budget.
At 1366×768, default page height changes from 1005 to 1043 px; visible input
count changes from 5 to 6 (the disclosure), label characters change from 70 to 69. All six
other pages have identical metrics and PNG bytes. Exact snapshot assertions are
retained; only Settings PNGs and the corresponding metric record are refreshed.
Before images: t15_ui/07_*_before.png; after images:
../../tests/fixtures/desktop_pages_before/07_*.png. Full measurements:
t15_snapshot_numbers.json.

GitNexus detect_changes (all) reported 10 changed indexed symbols, eight affected
processes and high risk through the shared catalog/Streamlit entry. This does not
cover untracked new modules in the stale index; no clean full-graph claim is made.

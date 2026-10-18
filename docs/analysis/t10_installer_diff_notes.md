# T10 part C installer diff review

Changed line categories in markauto.iss:

- Added the single Traditional Chinese [Languages] entry, relative to the .iss.
- [Run] Description: Launch Mark Auto -> 啟動 Mark Auto; flags unchanged.
- All 14 RaiseException message literals translated; expressions, concatenated
  paths, conditions, calls and control flow unchanged.
- Both SuppressibleMsgBox message literals translated, including uninstall refusal;
  severity, buttons and defaults unchanged.
- UTF-8 BOM added so Inno reads Chinese source without depending on host codepage.

There are no [CustomMessages] or [Tasks] sections in the original script. Existing
shortcut names contain only the product identity Mark Auto and remain byte-identical.
Internal Log literals (including MARKAUTO_* keys) remain unchanged for harness
compatibility. No English end-user message remains in custom dialogs/errors.
The standard wizard/uninstall prompts come from the unmodified upstream language.

The static regression oracle was captured with git show HEAD:packaging/markauto.iss
(before this run's changes). It pins identity/security lines and every non-message
byte after canonicalizing only line endings/BOM, the added language section and
UI literal bodies. This includes full uninstall handling, payload verification,
mutex refusal, per-user paths, inventory and recovery control flow.

Build manifest adds packaging/languages/* as build-time input only. .gitattributes
keeps the upstream language bytes intact. PyInstaller datas, payload inventory,
build.ps1 network/download behavior and installer lifecycle harness are unchanged.
No installer lifecycle harness assertions depended on English message text.

GitNexus: installer File impact UNKNOWN; direct references confirmed in build.ps1,
packaging tests and icon/recovery tests. build_manifest.main impact LOW (module
entry point only; no affected processes resolved). Existing test entry points are
unittest-discovered; UNKNOWN graph results were confirmed by direct source reads.

Verification: 46 focused language/packaging/recovery/icon/guard tests passed in
5.261 seconds, exit 0, with 3 existing skips (pwsh unavailable). An execution-only
os.mkdir inherited-ACL shim fixes the sandbox temporary-directory artifact; no
test assertion was changed or skipped by the shim. The initial direct run hit
5 such ACL errors. New language tests plus both guards independently passed
13 tests in 0.725 seconds, exit 0. Native Windows PowerShell parser passed all
11 packaging scripts. Quality gate: zero findings. Python 3.11 compile checked
301 tracked/new Python sources with utf-8-sig. No new desktop metrics were
needed; part A/B snapshot numbers are retained with a part C scope note.

ISCC unavailable at C:/Program Files (x86)/Inno Setup 6/ISCC.exe and the exact
TEMP/MarkAuto-Inno-6.4.3/ISCC.exe used by build.ps1. No compiler installation or
network change was made; native compilation, wizard display and lifecycle remain
unverified. Full suite runs outside this sandbox under controller ownership.
Graph refresh failed with sandbox spawn EPERM; existing index was used, with
UNKNOWN results verified against direct build/test references. No commit made.

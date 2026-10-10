# Installer update and recovery contract

Starting with 0.1.2, the installer never overlays a running payload. Each install
attempt reserves a fresh installer-generated directory under
`%LOCALAPPDATA%\Programs\MarkAuto\payloads\<version>\<unique-name>`.
The complete frozen payload and an embedded SHA-256 inventory are copied there.
The inventory's own digest is compiled into Setup; every file's digest and the
exact file count must pass before either shortcut can change. No new launcher,
service, scheduled task, auto-start, or trading behavior is introduced.

The released 0.1.1 root executable and dependencies remain intact during upgrade.
The Start Menu and Desktop shortcuts identify the active version; do not use the
legacy root executable to identify the active version. A crash between updating
the two shortcuts can leave them selecting different complete verified versions.
It cannot deliberately activate a partially extracted version. Rerun the same
installer to verify and activate a fresh complete attempt for both shortcuts.
If needed, the previous shortcut target recorded in validation evidence remains
runnable directly. Close any running Mark Auto window yourself before retrying.

An interrupted attempt is never reused. Old and abandoned payload directories
are intentionally retained, costing roughly one full frozen application's size
per completed attempt and up to that much per interrupted attempt. Ordinary
uninstall removes files tracked by Inno's uninstall log, while unknown files or
crash-orphaned files can remain. There is no wildcard cleanup or automatic
rollback-directory deletion. Do not delete the whole installation root to repair
an update. User state remains in the separate `%LOCALAPPDATA%\MarkAuto` directory
and is never targeted by installer cleanup. No historical schema migration is
claimed merely because sentinel files survive.

Only the normal local per-user install location is supported. Setup rejects
custom/redirected install locations and detected reparse points in the installation
path or payload; uninstall similarly refuses detected reparse points. This is not
an atomic filesystem transaction or a defense against a malicious same-user
process continuously racing filesystem writes. SHA-256 inventory checks prove
payload consistency, not publisher authenticity; the installer remains unsigned.

## Evidence and validation

Generate the inventory after freezing and before compiling Inno:

    python packaging/payload_inventory.py dist/MarkAuto dist/payload-inventory.txt dist/payload-inventory.iss

Run `test_update_recovery.ps1` only on a disposable Windows test profile after the
ordinary lifecycle suite uninstalls its app. Supply the exact released 0.1.1 EXE
and its build manifest plus the candidate manifest. It verifies artifact hashes,
installs and runs 0.1.1, creates absent-only non-sensitive schema-version-1
preferences at the actual `state-v1/settings.json` location, runs released 0.1.1
again with those preferences, freezes prior payload/sentinel expectations, kills the
actual candidate Setup process tree during extraction, confirms old shortcuts,
hashes and launch still work, then reruns Setup and verifies the new inventory,
obsolete-file isolation, normal launch, and same-version reinstall isolation.
It separately constructs an old/new split-shortcut state and proves an ordinary
rerun repairs both links. That constructed state is explicitly not presented as
an additional real crash checkpoint.
Every subsequent old/new smoke startup loads the actual settings file, checks
that the default data workspace is used, and verifies the settings bytes remain
unchanged. Existing settings or a workspace-location pointer cause refusal; no
unknown preferences are overwritten. This establishes compatible existing
settings preservation, not historical schema migration.
An extraction race that misses the incomplete checkpoint fails explicitly; no
mock result substitutes for that execution. Logs and JSON go under
`dist/validation/update-recovery`.

This tests a real process-crash checkpoint, not every possible power-loss phase,
filesystem durability guarantee, or independent clean Windows 10/11 acceptance.
The Python unit tests cover manifest generation and static installer safeguards;
they are not Windows execution evidence.

Implementation follows Inno's documented [installation order](https://jrsoftware.org/ishelp/topic_installorder.htm)
and [BeforeInstall/AfterInstall hooks](https://jrsoftware.org/ishelp/topic_scriptinstall.htm).

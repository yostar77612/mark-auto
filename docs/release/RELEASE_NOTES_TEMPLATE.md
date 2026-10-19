# Release notes — document template

This is a document template, not an announcement of a released version.
It publishes no GitHub Release or git tag and provides no download links.
Live trading remains permanently disabled. This document grants no trading capability.

Draft identity: [commit SHA / comparison range / preparation date / author].
Replace bracketed placeholders with evidence-backed text before review; a filled
document still requires a separate publication decision. Do not infer acceptance
from engineering completion or automated checks.

## Summary of changes

- [Describe the user-visible change and its scope.]
- [Link the reviewed change and distinguish implemented behavior from design.]

## Upgrade / migration notes

- [Describe compatibility, workspace backup and migration requirements, or state
  that none apply only after checking the reviewed change.]
- [Record recovery instructions and any user action required.]

## Verification scope and ongoing tracking

**Always retain this section and its tracking table in every copy.** The initial
ledger below mirrors the ten unfinished rows in
[PROJECT_STATE.md, 尚未完成](../agent/PROJECT_STATE.md#尚未完成).
All are UNVERIFIED; this template performs none of the outstanding verification.
The recorded formal acceptance remains **230/300**; neither this document nor
its local checks earn points or change [ACCEPTANCE.json](../agent/ACCEPTANCE.json).

Tracking IDs identify release-note ledger rows, remain stable across copies,
and must not be reused. They are local document IDs, not claims of filed issues.
The source column identifies the exact existing state row and, where applicable,
the separate E2 checklist IDs. Preserve those E2 IDs when recording display
evidence; the release-note IDs do not replace or renumber them.

| Item | Status | Tracking ID | Source / outstanding evidence |
| --- | --- | --- | --- |
| Manual paper submission/cancellation and saved-candidate Walk-forward | UNVERIFIED / pending external evidence | RN-001 | State row 手動紙上委託／取消、保存候選池 Walk-forward: actual operations in an isolated workspace remain required. |
| Real ChatGPT inference | UNVERIFIED / pending external evidence | RN-002 | State row 真實 ChatGPT 推論: owner verification of inference, quota exhaustion and expired authorization remains required; login/model listing does not establish inference. |
| Physical-display 150% / 200% DPI across seven pages | UNVERIFIED / pending external evidence | RN-003 | State row 150%／200% DPI; E2 [display checklist](../qa/display-compatibility.md#external-checklist), DISP-03 and DISP-04. Offscreen checks are not physical-display evidence. |
| Chinese Windows installer lifecycle | UNVERIFIED / pending external evidence | RN-004 | State row 中文安裝精靈: actual Chinese Windows installation, upgrade and uninstall remain required. |
| Clean Windows 10 / 11 client lifecycle | UNVERIFIED / pending external evidence | RN-005 | State row 乾淨 Windows 10／11: authorized clean client environments remain required; Server CI and previously used machines are insufficient. |
| Official trading holiday calendar | UNVERIFIED / pending external evidence | RN-006 | State row 官方交易日曆: holiday calendar must still be supplied manually; the finite expiry-date checks do not establish it. |
| Extracted P2-B2 module source hashes | UNVERIFIED / pending separate engine-profile evidence | RN-007 | State row P2-B2 抽出模組來源雜湊: new lower-level modules await a future engine profile update; this template makes no engine change. |
| B4 theme appearance on physical displays | UNVERIFIED / pending external evidence | RN-008 | State row B4 主題在實體螢幕的外觀; E2 [display checklist](../qa/display-compatibility.md#external-checklist) requires both themes, including DISP-03 and DISP-04. Automated accessibility checks do not close this item. |
| B10 / B13 real-machine interaction | UNVERIFIED / pending external evidence | RN-009 | State row B10／B13 在真實操作下的體驗: re-price dragging, pause and speed changes still require actual machine operation. |
| B7 strategy intent implementation | UNVERIFIED / pending separate task and G3 approval | RN-010 | State row B7 策略意圖層 and [ADR 0006](../adr/0006-strategy-intent-pipeline.md): design only; implementation is conditional and is not supplied by this template. |

For each later attempt, record [tracking ID / tested commit / tester / date and
timezone / exact scope / result / sanitized evidence reference]. Retain failures,
blocked attempts and unattempted scope. A partial or automated result must not
close an external item. Add new rows with unused IDs as evidence reveals gaps;
retain completed rows with their dated evidence rather than silently deleting them.
For display attempts, also record the original E2 checklist ID and its required
environment fields; user confirmation remains pending until actually recorded.

Keep credentials, private account details, OOS and final-holdout data out of notes
and evidence attachments. OOS and final-holdout data must never enter any AI
conversation, tool return or prompt.

## Known limitations

- [Describe limitations introduced or affected by the reviewed change.]
- [Link unresolved defects and state their practical impact; do not imply a fix.]
- The [recorded known risks](../agent/PROJECT_STATE.md#已知風險) remain relevant:
  intermittent Paper/smoke timeouts, performance work, limited worker error
  observability, unsigned installers, old payload accumulation, external main
  protection limits and default TLS trust on non-login downloads. This template
  supplies no remediation evidence. Do not bypass SmartScreen.
- Live trading remains permanently disabled. Preserve fail-closed validation,
  one-time OOS consumption and irreversible budgets. Timeouts remain Paper 30 s,
  smoke 40 s and 15 min per job; stopping new orders does not close positions.

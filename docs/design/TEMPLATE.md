# [Item ID]: [Change title]

Status: PROPOSED / NOT IMPLEMENTED. Verification: NOT RUN.

Use before implementing a UI or behavior change. Replace bracketed fields,
retain these headings, and keep the proposal short. Link repository evidence;
distinguish current observations from future requirements.
See [C5 example](c5-market-dock-workspace.md), [ADRs](../adr/),
[glossary](../GLOSSARY.md) and [engineering contracts](../agent/IMPLEMENTATION_CONTRACTS.md).

## Problem

[Upcoming requirement ID, source section, user problem and current source evidence.]

## Goals/Non-goals

[Observable goals, explicit exclusions and compatibility requirements.]

## Design

[Proposed behavior, state transitions, failure behavior and alternatives.]
[List exact existing repository paths to touch with resolving links and reasons.
Label any proposed new file as future rather than linking a nonexistent path.]
For UI changes, use literal ui_text keys in [desktop_app/strings/catalog.py](../../desktop_app/strings/catalog.py)
and the B1 [ERROR_TABLE](../../quantlab/errors.py) for errors.

## Safety constraints (live trading disabled, G3, OOS/budget)

Live trading stays permanently disabled; add no real order path.
Keep all eight G3 files and protected saved-candidate profile blocks untouched;
if a future change needs them, obtain owner approval before editing. The exact
protected paths are in the [contributor guide](../CONTRIBUTING.md).
Preserve fail-closed validation, OOS one-time consumption, irreversible budgets
and every timeout (Paper 30 s, smoke 40 s, 15 min per job).
OOS and final-holdout data must never enter AI conversations, tool returns or
prompts. AI output remains untrusted input subject to existing AST validation.
No eval/exec/new Function or other dynamic execution; no ChatGPT credential
reading, storage or display. Money arithmetic remains Decimal.

## Test plan

[Name existing test modules/commands and planned cheap offline cases; record
expected outcomes as requirements, never as results before execution.]
For new UI, require an accessibility walk and snapshot comparison, preserving
existing objectNames and platform-independent assertions. Identify intended
baseline changes; the controller refreshes fixtures in a separate commit.
Real-App visual inspection is the user's final confirmation and remains pending.
Use the [contributor guide](../CONTRIBUTING.md) for lint, compile, quality-gate
and one-module-at-a-time test commands. Include documentation link/layout checks.

## Rollout/Verification status

[Implementation sequence, review boundary and rollback approach.]
Implementation: NOT IMPLEMENTED. Automated verification: NOT RUN.
Real-App visual check: PENDING USER FINAL CONFIRMATION (for UI changes).
Record evidence with command, result and revision only after running it.
Keep [PROJECT_STATE](../agent/PROJECT_STATE.md) and acceptance scores unchanged;
formal acceptance remains 230/300. No Release or tag is part of a design proposal.

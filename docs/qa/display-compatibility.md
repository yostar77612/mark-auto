# Display compatibility checklist — EXTERNAL / UNVERIFIED

Every item below is EXTERNAL / UNVERIFIED. No 150% or 200% DPI run has been
performed by this commit. All boxes are intentionally unchecked; expected
results describe what a tester must observe, not measured outcomes.
Automation cannot claim visual completeness; final confirmation is the user's.

## Pages and evidence boundary

Inspect these seven sidebar pages, named exactly as in
[desktop_strings.py](../../desktop_strings.py):

1. 市場總覽
2. 資料匯入與更新
3. AI 策略中心
4. 回測與結果
5. 比較與策略選擇
6. 紙上交易與復原
7. 設定與備份

In this checklist, **All pages** means all seven names above, including their
tabs, scrollable content and expanded advanced sections. **Maintenance** means
the 設定與備份 panel **版本維護（檢查更新／舊程式版本）**
(`maintenance.options` in the same catalog), expanded for inspection.

The [user manual](../user/使用手冊.md) contains the existing seven 1366×768
offscreen screenshots in [its image directory](../user/img/).
These are automated-only snapshot evidence, not a substitute for real-DPI
verification on physical Windows displays. The
[recorded project state](../agent/PROJECT_STATE.md) retains the external
150%/200% DPI work. Neither snapshots nor changing a Qt test font establishes
Windows display-scale or mixed-monitor behavior.

## Preparation

Use an isolated disposable workspace and offline synthetic demonstration data.
Do not use OOS or final-holdout data, credentials or private account information
in screenshots or reports. Live trading remains permanently disabled.
Inspection requires no research generation, network request, order submission,
restore or cleanup action. Open menus and confirmation dialogs only where they
can be dismissed without executing the action.

Use Windows Display settings to select the actual display scale; record native
resolution, working area, monitor arrangement and Windows text size separately.
Restart the app at each scale, then inspect resizing and scrolling. Repeat each
row in both available themes. Compare visible labels, values, focus outlines,
tooltips, tables, charts, menus and dismissible dialogs. Preserve the default
view first, then expand advanced sections and Maintenance. Record unavailable
hardware or settings as blocked, never infer an outcome from another scale.

## External checklist

- [ ] **DISP-01 — 100% display scaling. Pages: All pages + Maintenance.**
  Expected: sidebar names, labels and button text are readable without overlap;
  controls and dialog dismissal remain reachable by mouse and keyboard; scrolling
  exposes the entire content rather than cutting off the final rows.
- [ ] **DISP-02 — 125% display scaling. Pages: All pages + Maintenance.**
  Expected: text and icons remain legible; labels, input values and selected tabs
  are not clipped; table headers align with cells and scrollbars reach all rows.
- [ ] **DISP-03 — 150% display scaling. Pages: All pages + Maintenance.**
  Expected: enlarged controls do not overlap or hide actions; sidebar navigation,
  advanced sections, tooltips and dialogs remain readable and operable; chart
  axis labels remain distinguishable from plotted content.
- [ ] **DISP-04 — 200% display scaling. Pages: All pages + Maintenance.**
  Expected: all navigation and dismiss controls remain reachable; scrolling
  reaches the last field; text, focus outlines and chart/table content remain
  readable without overlap, truncation that hides meaning, or offscreen dialogs.
- [ ] **DISP-05 — Mixed-DPI multi-monitor. Pages: All pages + Maintenance.**
  Use monitors at 100% and 150%, then 100% and 200% where hardware permits.
  Move the main window in both directions, maximize/restore it on each monitor,
  and open/dismiss menus and dialogs after each move.
  Expected: text and controls rescale coherently, pointer targets align with
  their visible controls, popups remain on a reachable display, and content
  remains readable without stale sizing, overlap or lost scroll access.
- [ ] **DISP-06 — 1366x768 minimum-size inspection. Pages: All pages + Maintenance.**
  Use a 1366×768 Windows display at 100%, record taskbar/working-area dimensions,
  and inspect maximized and restored windows. Repeat at each available higher
  scale, recording the resulting logical working area rather than assuming it
  remains 1366×768.
  Expected: navigation, essential actions and dialog dismissal are reachable;
  scrolling exposes bottom fields and expanded content; no fixed-height area
  traps controls outside the visible working area.
- [ ] **DISP-07 — Windows font scaling. Pages: All pages + Maintenance.**
  Independently vary Windows Accessibility text size from 100% to 125%, 150%
  and 200% where offered, first at 100% display scale and then at 150%/200%
  display scale; record every combination and restart as Windows requests.
  Expected: enlarged text is readable in sidebar entries, labels, inputs,
  buttons, tables and dialogs; controls expand or allow access by scrolling
  without hiding values, focus indicators or dismissal actions.

## Recording a result

For each actual attempt, add a row to the empty table below. Record tester,
date with timezone, Windows edition/build (from `winver`), full tested commit
SHA (from `git rev-parse HEAD`), checklist ID and exact pages inspected.
Include display scale, Windows text size, resolution/working area, monitor
layout, theme and startup/move sequence. Record observed behavior, an outcome
using the result column's categories, and a sanitized evidence location or issue reference.
Leave unattempted items unchecked. A checkbox may only be marked after that
item's full scope has been observed and evidence recorded; partial attempts
need separate rows. Keep failures and blocked attempts in the record.

| ID / pages | Tester | Date / timezone | Windows edition / build | Commit SHA | Display / text scale | Resolution / working area / monitors | Theme / sequence | Observed result | Pass / fail / blocked | Evidence / issue |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

User confirmation is pending. Record the user's dated confirmation and its
exact scope separately after review of the physical-display evidence; a local
automated check cannot supply that confirmation or raise the acceptance score.

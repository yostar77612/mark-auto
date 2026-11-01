# M2-6 exact feature-baseline delta

This commit pins the reviewed M2-6 presentation additions independently of the
feature implementation. It changes no product source, assertion operator, test
scope, skip, timeout, class budget, style hash or historical producer profile.

- `desktop_catalog_main_6b78239.json`: add exactly 23 `m2t.*` keys to the current
  locale values/lookups and append their exact insertion order. All previous
  values, keys, aliases and their order remain byte-equivalent as JSON values.
  Historical `source_commit: 6b78239` and all 1323 aliases remain intact.
- `test_desktop_catalog_split.py`: exact continuous order is now 0–2775
  (2776 records), previously 0–2752. The test still verifies every literal value,
  per-phase key uniqueness, complete alias equality and exact insertion order.
  New phase61 orders2753–2775 come only from `strings/m2_trading.py`.

The 23 labels comprise three environment bands, the LIVE refusal, environment
help, six action explanations, ten compact position headings and the precise
LIVE-only stop caption/help. No existing string is replaced. No v1 widget-name,
page-service, appearance or UI screenshot baseline is modified by M2-6.

Catalogue/appearance/hardcoded-text/placeholders focused checks: all 30 passed
against these exact pins. Full-suite and remote CI verification remain
coordinator work.

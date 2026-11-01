# Exact UI-guideline presentation/interaction baseline

Product/new acceptance-test source commit: `a16e9e5`.

Owner authorized PR127's scoped guidelines for the already-modified M2-6
regions. This commit changes only exact feature pins and the explicit approval
step expected by existing action tests; source and new cancellation/default/
keyboard/persistence/formatting acceptance tests are in the preceding source
commit. No applicability skip, limit, timeout or financial assertion changes.

- Add exactly10 keys at orders2796–2805 (2806 ordered records;2805 unique locale
  keys, retaining the historical duplicate record). A regeneration check proves all old
  locale and alias lookup values, relative order, aliases and alias order stay
  identical. Source provenance6b78239 is retained.
- Existing stop/cancel/dashboard keyboard/priority-stop/busy tests explicitly
  approve the newly required dialog. Their original exact actions, versions,
  counts, timing and stale-response assertions are untouched. Eight separate
  actual-widget cases cover native Cancel defaults, zero-command cancellation,
  confirmed action routing and context-change rejection. These tests do not
  globally mock confirmations or bypass the new cancellation evidence.
- Original1366 test still asserts12 total data columns, complete tooltips,
  first-column bounding geometry and actual scrollbar maximum0. Add the exact
  six-column visible set and bind the last visible column9 rather than hidden11.
- The original empty-strategy wizard test now asserts its newly required
  visible explanation and exact text, retaining navigation, wizard-open and
  zero-command assertions. No money/provenance assertion is removed or relaxed.

Root still owns the final full suite, actual LOCAL/fake-SIM starts and CI.

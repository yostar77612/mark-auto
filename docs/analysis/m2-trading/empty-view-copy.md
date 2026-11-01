# Empty read-model wording correction

Root review found that "currently no positions/orders" overstated what an empty
broker read model proves when disconnected or financial facts are unverified.
The two existing catalogue keys now describe absent displayable data, without
claiming verified zero exposure or requiring a future automatic strategy.
Current strategy-navigation CTAs are retained as requested; no readiness,
financial state, account selection, command or runtime behavior changes.

An actual-widget regression applies accepted SIM and LIVE disconnected snapshots
with `financial_facts_verified=False` and empty position/order projections.
Both environments failed on the previous copy, then passed on the new wording;
the test checks accessible text, available CTA and zero mutation commands.
All original M2-6 and guideline regressions remain in the focused run.
The final26 focused widget cases passed in9.447 seconds;21 catalogue/literal
text/placeholder checks passed in1.813 seconds. Ruff and diff checks are clean.

The1366×768 and1920×1080 empty trading screenshots are refreshed. Catalogue
orders/keys/counts/aliases are unchanged (maximum2805). Only the two existing
locale/lookup values are re-pinned in an independent baseline commit.

The preceding f610cb7 actual LOCAL/fake-SIM startups passed under root control;
root will repeat them on this new final head. No full suite, real SDK login,
CA action, order, engine process or push is performed by this correction.

# Official daily importer and native integration evidence

The operational entry point is `python -m tools.import_official_daily`; see
[operator instructions](../design/m2-3d-official-daily-import.md). Its offline
manifest path and per-call consented download path publish one validated RAW
daily/event batch using the existing atomic cache import. The production runtime
never acquires public data implicitly. No desktop, SDK pin, CA, cost rule or LIVE
order path changes belong to this slice.

## Focused checks

| Check | Result |
| --- | --- |
| New importer cases |30 PASS|
| Existing HTTP boundary cases |3 PASS|
| Actual connected ManualRuntime / SQLite / official source / fake SDK |4 PASS|
| Actual large-cache public host pump |1 PASS|
| Independent original-one-test / mutated-same-test pairs |22 KILLED|
| Owned source/tests Ruff and Python3.11 syntax |PASS|

The four connected cases include actual `_materialize` composition, real research
and deployment from recorded official inputs, pre-open publication followed by
one native SDK submission at the current quote, refusal to invent an opening
catch-up signal, and transient SQLite read failure followed by a successful later
pump without poisoning the engine. No test installs a synthetic official source
port in this connected chain, changes pause/reconciliation flags to make it pass,
or reseeds the next day's baseline. SDK observations and the playback clock are
explicit doubles; they do not claim historical broker balances or market ticks.

The new public TWT49U recording covers2025-06-01 through2025-06-30, with245 native
rows and49867 original bytes. The manifest retains its actual2026-11-02T21:29:50Z
receipt, official URL and SHA256. Existing6225/2330 monthly recordings are copied
byte for byte. This was one separate owner-consented public recording; tests
remain offline. The complete live monthly-plus-events download was exercised
through a fake HTTP transport, not claimed as a live-network acceptance run.

## Lock and cache measurements

The size fixture has a finite, explicitly synthetic DAY calendar,1553 bars,
72 monthly responses,250 progressively enclosing refreshes,573 archived raw
payloads and73 active sources in one manifest. A next-day extension makes the
archive574. These are real SQLite writes and actual provider parsing/hashing;
they do not establish an exchange holiday calendar or economic ranking quality.

Two earlier fresh-process results with the unchanged0.5-second pump lock
threshold remain retained. They precede the final strict API split reported below:

| Sample | Cold pump total s | Cold lock s | Three-hot lock max s | Revision lock s | Separate query/adopt lock s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Native five-case run |0.20098|0.09257|0.02720|0.40285|0.02273|
| Independent single-test baseline |0.19440|0.09411|0.03105|0.44866|0.02810|

Each cold pump performs72 daily parses,1 event parse,74 source hashes and73 raw
payload reads, all outside bundle/engine/owner locks. Three duplicate pumps add
zero source hashes, parses, full reads or payload reads. A real cache revision
causes144 daily parses and148 hashes across two full source requests before the
actual one-time native dispatch. No background query or diagnostic order is
counted as a strategy fill.

## Red evidence and mutation classification

The first native assembly found the storage reader selecting `sources` and later
using that JSON value as a rowid. The original TypeError trace is retained; the
fix selects the actual rowid. A second actual counterexample found maintenance
display changes advancing the authenticated control revision across a normal
night; the normal cross-day native case now passes without relaxing real owner
epoch checks. These fixes are supplied by their owning modules.

The original quadratic signal-window lookup held the lock for about0.72s cold
and1.51s on revision. Profiling identified repeated `calendar.day_session` walks
inside the history scan. The equivalent one-time DAY map keeps exact history
membership and opening-time comparison. Its independent mutation restores only
the old lookup: the same single TestCase passes unchanged first, then fails its
body assertion with0errors/0skips at0.58467s cold and1.39103s revision.

Later harness runs also retained whole input batches through a heartbeat Mock's
call history. Unprofiled cold spikes around0.93–0.96s and all intermediate results
remain recorded. Passive GC observation saw1,848,143 objects reclaimed in0.81544s
during that old harness's revision prewarm; that observed run itself passed.
This does not uniquely establish the cause of every earlier spike. The final
harness uses a transparent, non-recording heartbeat wrapper around the original
import method. It retains the complete data size and250 real updates, leaves GC
enabled and unchanged, and preserves the original0.5s assertion. Both earlier fresh
samples above are reported, rather than selecting the faster one.

The21 importer/URL mutations each pass their exact single test in a fresh process
before another process compiles one changed guard in memory. Assertion failures
and actual boundary errors count only when the requested TestCase body appears
in the traceback; loader, import, setup, cleanup and skipped tests do not count.
The adjacent JSON lists every case, test identity and target source hash. The
separate performance pair brings the independent kill count to22. Product files
are never edited by these mutation runners.

Full raw local reports remain under `.gitnexus/verification/official-daily-*`,
including all superseded red/profiling observations. This document records focused
local evidence; the integration owner records final branch CI and review status.


## Final strict API and native Windows startup verification

The final API split retains the ordinary store revision's blocking/fresh behavior.
Official-source cache keys and final checks use the distinct strict nonblocking
`verification_revision`. The legacy SIM pump without ManualRuntime denies new
entries; the generic engine submission API remains compatible with its legacy
fixtures. These changes are covered by the integration owner's separate tests.

After that split, the same native five-case slice passes5/5 in36.976s.
The full1553-bar/250-refresh/573-to574-archive fixture and original0.5s threshold
are unchanged. The final measured phases are:

| Cold pump total s | Cold lock s | Three-hot lock max s | Revision lock s | Query/adopt lock s |
| ---: | ---: | ---: | ---: | ---: |
|0.23249|0.11096|0.03408|0.42952|0.02457|

Payload verification remains outside bundle/engine/owner locks, the three duplicate
pumps add zero hashes/parses/reads, and a real revision revalidates before the
single native SDK submission. All22 earlier independent mutation targets retain
their exact source hashes; their raw reports are preserved rather than presented
as newly rerun mutation pairs for this API split.

Both original `_run_window` lifecycle checks also pass with actual native Windows
Qt windows (`qt_platform=windows`, `window_visible=true`): LOCAL8.070s
and fake BROKER_SIMULATION4.773s. Their return codes are0, research
sessions are released, and owned endpoints are removed. Fake-SIM login/logout are
each1; the real SDK is not imported. An ignored wrapper changes only the original
harness's offscreen selection in memory and asserts the native platform. It keeps
the original lifecycle and owned-cleanup assertions. It closes only the helper's
newly created test window/processes, not the user's existing applications.

The adjacent JSON replaces current source hashes with the final snapshot, preserves
the prior snapshot, and adds complete native/startup reports. No product/test
edits, baseline writes, staging, commits, pushes or CI actions belong to this
verification update.

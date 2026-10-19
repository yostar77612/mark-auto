# T14 P3-11 — dataset storage design

This is a design assessment, not an engine or file-format migration. The eight
G3 sources and all producer profiles remain unchanged.

## Identity and provenance in the current implementation

`quantlab/data.py::_dataset` sorts normalized bars by timestamp, contract and end.
`data_hash = content_hash(bars)` covers the complete ordered typed bar sequence:
timestamps/endpoints, trading date/session, contract, OHLC Decimal values, volume
and source. It is not a digest of the pretty-printed dataset JSON file.
`core.py::canonical_json` uses sorted keys, compact separators, UTF-8, no NaN;
typed values are serialized by `_json_value` (including Decimal text and datetime
ISO strings). Float conversion or reordering can therefore change identity.

`manifest_hash` covers all manifest fields except `imported_at` and the digest
itself. That includes source type/URL/filename/hash, calendar version/hash,
schema/encoding/timezone, aggregation and endpoint conventions, quality status
and coverage. The source hash records the original source bytes for imported
files, whereas the synthetic generator uses bar content. Preserve that distinction.
`validate_dataset` recomputes these hashes and validates bars/quality; a matching
hash alone does not establish validity, licensing, independent OOS, or eligibility.

The public synthetic API is `reporting.synthetic_dataset`, capped at 10,000 bars;
there is no public synthetic generator in `data.py`. `reporting.save_dataset`
wraps the entire typed payload (bars, manifest, quality) in a
`quantlab_dataset_v1` envelope with its own content hash. Thus quality metadata
is additionally protected by the envelope even where not in `data_hash`.
Research splits and saved candidates also bind parent data/provenance and pinned
producer sources; a storage migration must preserve all those identities, not
merely reproduce close prices. See [scale evidence](t14_p3_scale.md).

## Options

| Option | Potential benefit | Identity, migration and operational risks | Dependencies |
|---|---|---|---|
| Canonical JSON | Existing loader/validation/profile behavior; transparent interchange | Full parsing/materialization and repeated hashing; measured 2.41 MB for 10,000 bars; no partial column reads | Current standard library |
| SQLite derived cache | Indexed ranges; explicit ordinal and transactional cache publication | Store Decimal and original ISO values as TEXT/BLOB, never REAL or NUMERIC affinity; retain full manifest/quality and order. DB file bytes, page layout and WAL are not dataset identities. Cache concurrency, stale entries, torn publication and schema upgrades need testing | Existing `sqlite3`; retain the project's WAL runtime/version and filesystem rules where applicable |
| Parquet / Arrow derived cache | Column projections, compression, reusable typed batches | Need explicit Decimal precision/scale, timestamp unit/timezone and stable row ordinal; preserve original representations when reconstructing canonical bars. Missing vs null, dictionary encoding and library conversion must not silently alter canonical values. Parquet bytes are not a canonical hash input | Adds Arrow/Parquet libraries, native wheels, installer size/notices and platform maintenance; conflicts with current standard-library research boundary unless architecture is explicitly approved |
| NPZ derived cache | Convenient column arrays and optional compression | NumPy has no native arbitrary Decimal array representation preserving this contract; use scaled integers only with proven bounds or exact strings. Reject object arrays; load with `allow_pickle=False`. Keep manifest/quality/column types and ordinals in a separate validated schema. ZIP bytes are not a data identity | Adds NumPy; object-array pickling would violate the research boundary |

SQLite REAL is IEEE binary64 and numeric affinity may coerce numeric strings;
TEXT/BLOB is the safer proposed exact-value representation.
[SQLite datatype specification](https://www.sqlite.org/datatype3.html).
Parquet separates physical types from logical annotations; its storage encoding
does not define this project's canonical serialization.
[Parquet types](https://parquet.apache.org/docs/file-format/types/).
NPZ stores named arrays in a ZIP container and object serialization needs special
care. [NumPy savez](https://numpy.org/doc/stable/reference/generated/numpy.savez.html).
Benefits above are design expectations, not measured speedups in this change.

## Migration path and explicit recommendation

Keep JSON plus the existing typed canonical hash as the authoritative form.
Defer changing the engine or canonical storage to a planned engine version with
a new producer profile, exact round-trip/hash fixtures, cross-version and
cross-platform regressions, and explicit rollback/export procedures.

If future measurements justify caching, first prototype an optional disposable
SQLite cache outside authoritative research evidence. Key it by envelope hash,
data hash, manifest hash, cache schema and converter version. Build from a fully
validated canonical dataset, publish atomically, and verify exact reconstruction
and all hashes on cache acceptance; reject/delete invalid entries and reload JSON.
Never replace source evidence, mutate a manifest to fit cached values, or use a
cache to bypass fail-closed validation, quotas or OOS one-time consumption.
Test corruption, truncation, source replacement, timestamps/Decimal spellings,
duplicate/order handling, stale converter versions and concurrent readers.

This cache would mainly address loading/range access. It cannot remove per-run
full engine validation or process startup costs while preserving today's engine
behavior. A cache that still reconstructs and hashes every bar may save little;
measure end-to-end performance before adding that maintenance burden.

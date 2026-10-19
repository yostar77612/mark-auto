# Agent harness contract v1 — A1-D1

This is the offline core contract, with no network transport or conversation UI.
Trust boundaries, evidence and residual risks are recorded in the
[agent harness threat model](AGENT_HARNESS_THREAT_MODEL.md).
The [machine-readable schema](agent-app-tools-v1.schema.json) is mirrored by
`quantlab.agent_tool_contract` and checked for exact equality in contract tests.
The schema is JSON Schema draft 2020-12; the runtime uses a deliberately closed,
standard-library-only subset, without reference resolution or remote loading.

| Capability layer | Scope | Executable in v1 |
| --- | --- | --- |
| `research.read` | Sanitized training-only research status | Yes, one bounded read |
| `paper.read` | Future sanitized simulated journal reads | No handlers yet |
| `ui.navigate` | Future semantic navigation | No handlers |
| `research.run` | Future explicitly authorized research operations | No handlers |

## Default deny and effects

Every declaration has `contractVersion: 1`, semantic `name`, `capability`,
`effect: read|mutation`, and a closed `inputSchema`. Unknown declaration or
argument fields are rejected. Missing/unknown effects, unknown capabilities,
duplicates and invalid schemas refuse registration without changing the registry.
Mutation schemas must require a nonempty string `idempotency_key`; this is
necessary, never sufficient, for a future mutation. The test-only fake mutation
is absent from production. All mutation execution is refused in this version.

Registration accepts trusted host-owned handlers only. Model output cannot
register a handler, assign partition provenance, grant capabilities, or supply
host context. Model arguments are parsed only as bounded strict JSON: no fences,
duplicate keys, nonfinite numbers, coercion, or executable expressions. Input
schemas have at most eight string/integer fields, no references or extensions.
Registration validates required fields and idempotency semantics as well as
the declaration schema. No code generation or dynamic execution is involved.

Resolution and calls require explicit capability grants; the default grant set
is empty. An unregistered name, unknown capability, absent grant, invalid JSON,
invalid return or adapter failure yields only
`{"ok": false, "error": {"code": "agent_tool_refused", "params": {}}}`.
That stable code belongs to B1's single `quantlab.errors.ERROR_TABLE`. Nothing
from exceptions, rejected inputs or host records is included in refusals.
Resolution exposes a copied declaration, never a handler. The production
registry is frozen and holds only `effect=read` tools; it contains no trading,
order, amend, cancel or placement operation.

## Information boundary

`research.list_training_status` is a minimal contract exerciser, not the D3
research tool suite. A trusted host adapter supplies an in-memory sequence of
partition-labelled dictionaries. It must derive `partition=training` and the
training-only `observations` count from approved training evidence, independently
of model/user text. Do not label a whole mixed-period run as training or supply
whole-run counts. There is no production storage/provider adapter in D1.

The tool excludes every partition other than exactly `training` BEFORE counting,
projection or pagination. It returns only `completed` (boolean) and
`observations` (integer count of training observations). It never copies record
IDs, names, free text, prices, returns, metrics, trades, equity, paths, credentials,
user raw files or consumed-guard contents. OOS/out-of-sample and final-holdout
records and their counts cannot influence the output or cursors. Missing and
unknown partition labels are denied visibility. Malformed visible rows refuse
the entire call. The strict output schema rejects unknown fields and strings.

The sentinel test enumerates EVERY registered read tool, including all pages,
and recursively scans all return fields for protected values. It compares clean
and contaminated contexts, including credential/path/raw-content sentinels.
A negative control removes partition filtering and proves the same scanner
detects leaked protected row counts; no fake is installed in production.

## Bounded return (D11 boundary)

Every D1/D3 handler returns through `quantlab.agent_return.bounded_return`.
Successful reads return exactly `ok`, `items`, `count`, `total`, `truncated`,
`limit`, `next_cursor`, `reason` and `field_truncations`. Counts and cursor hashes
are derived ONLY from already authorized, positively projected visible rows.
`limit` is a strict integer from 1 to 50 (default 50); booleans, nonintegers and
out-of-range values refuse. Arguments retain their 4096-byte UTF-8 cap; complete
serialized envelopes retain the 8192-byte cap, including metadata and cursors.
Both canonical UTF-8 and ordinary ASCII-escaped JSON serialization fit the cap.
The helper has no I/O, clock, randomness, credentials or provenance inference.

Item and byte overflow page at whole-item boundaries with `truncated=true`,
`reason=item_limit|byte_limit` and a nonnull opaque string cursor. A cursor binds
the visible snapshot, offset and host-supplied request scope. Tampered, stale,
cross-scope and legacy integer cursors refuse with B1 `agent_tool_refused`.
Cursor hashes provide consistency, not authentication or authorization. The
trusted host must still supply approved training-only evidence on EVERY call.

Strings exceeding 256 characters are capped with an envelope marker containing
the page-relative item ordinal, nested field components and `truncated=true`.
Field loss sets the envelope flag even on the last page (`reason=field_limit`,
null cursor). Pagination never promises to recover capped field suffixes.
Without field loss, concatenated pages exactly reconstruct the source sequence.
An indivisible row that cannot fit refuses rather than returning a zero-progress
page. Non-JSON-safe values, NaN, Infinity, bytes, paths and lone surrogates refuse.
No truncation has `reason=null`; exhaustion has `next_cursor=null`.

## Unchanged safety contracts

Live trading permanently disabled. No real order path, network request, UI
handler, research execution, timeout, gate, threshold, budget or OOS-consumption
change. [ADR 0001](adr/0001-oos-consumption-and-budget.md),
[ADR 0004](adr/0004-restricted-ast-rules.md), and
[ADR 0005](adr/0005-decimal-and-content-hash.md) remain authoritative.
All G3 sources and saved-candidate profile blocks remain byte-identical.
No money math is introduced. State documents and acceptance scores are unchanged.

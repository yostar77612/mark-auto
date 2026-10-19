# Local research skills (D7)

Registered prompt files live only in [docs/skills](skills). The shipped skills
are [interpret-backtest](skills/interpret-backtest.md),
[check-overfitting-risk](skills/check-overfitting-risk.md),
[compare-two-results](skills/compare-two-results.md) and
[check-data-quality](skills/check-data-quality.md).
These are untrusted prompt data for approved training evidence, never authority.
Live trading remains permanently disabled.

The [loader](../quantlab/agent_skills.py) implements a deliberately narrow
front-matter dialect. The first line and the closing delimiter must be `---`.
Exactly four unique fields are required. Each field is a single line with
`key: value`; scalar values are JSON strings and allowed_tools is a JSON list.
There is no general YAML interpreter, tag, alias, multiline scalar or code runner.

```text
---
name: "check-data-quality"
description: "Explain aggregate quality counts for approved training data."
allowed_tools: ["get_data_quality_summary"]
output_format: "Observed counts, potential impact, limitations, questions."
---
Prompt body here.
```

Names are lowercase ASCII kebab names, at most 64 characters, matching the
Markdown filename stem. Description and output_format are nonempty strings of
at most 256 characters without control characters. allowed_tools is a nonempty,
duplicate-free list of at most 50 names already registered with effect=read and
capability research.read or paper.read. Unknown fields, tools, mutations and
other capabilities fail closed. Files must be strict UTF-8, contain a nonempty
body and fit 16384 bytes. Catalogs contain at most 128 files. Invalid entries
refuse the whole catalog, including duplicate names or filename mismatches.

The directory is fixed by the application, without a model-selectable root.
Names are checked before filesystem access. Symlinks, Windows reparse points,
absolute names, separators and traversal fail closed. Every read uses a bounded
binary read and checks containment. Catalog output contains no filesystem paths.
This protects access to other user files; authors must keep secrets and user
data out of prompt packages. Prompt text is not a secret-redaction service.
Concurrent hostile filesystem replacement is outside this host-owned local
directory's trust model; write access to the directory is a host responsibility.

`SkillLoader.list` and `read` take strict duplicate-free JSON objects.
Listing accepts only limit/cursor; body reads additionally require name.
Both use the existing [D11 envelope](AGENT_HARNESS_CONTRACT.md).
Bodies are divided into ordered chunks of at most 256 characters so pagination
can reconstruct all text without silent truncation. Cursors bind visible content
and scope; file changes invalidate them. Invalid inputs return only B1's existing
agent_tool_refused code with empty params, without exception text or paths.

The host activates a skill using `activate(name, capabilities=existing_grants)`.
It must route every model tool request through the returned `SkillSession.call`
while the skill is active. The session snapshots immutable prompt data and
intersects host grants with the registered whitelist's read capabilities.
There is no grant API. Each call checks the skill whitelist before invoking the
existing registry, which independently checks capability, effect and strict
JSON/input/output schemas. Refusals use the same B1 code even for existing tools.
Model arguments cannot change active skills, grants, registry or evidence.
Registration and activation are host operations, never model tools.

Skill text can contain authority claims or fenced code, but is never executed
or interpreted as permissions. A host must keep it labeled as untrusted prompt
material. No provider calls, UI wiring, dataset readers or execution paths are
added. Training provenance and positive output projection remain D3's boundary;
skills cannot provide evidence or relabel protected results. No OOS, final
holdout or consumed-guard reader exists here.

The [D7 tests](../tests/test_agent_skills_d7.py) reuse D3's sentinel fixture
through an active session for all tool outputs and pages. They also run the
negative control: removing provenance filtering must fail the same recursive
oracle for both protected metrics and aggregate row counts. Other tests cover
schema failures, inert code, authority claims, strict JSON, stable refusal,
catalog bounds, path confinement, whitelist enforcement and shipped-prompt lint.

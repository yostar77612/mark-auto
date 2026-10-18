# Saved-campaign producer audit: optional connected-peer verifier

## Token-format auth revision (2026-10-15)

`TOKEN_FORMAT_SIWC_ANALYSIS_PROFILE_V1` appends protocol
`mark_auto_0_2_2_campaign_siwc_token_formats_v1`. Its complete profile identity is
`ae17850d264a810ba51e499a50e28c72cc4f907a9f43c92ca07c282d1f11c632`.
Only the protocol and the reviewed auth source SHA256 pair differ from
`DEADLINE_SIWC_ANALYSIS_PROFILE_V1`: LF
`3c2eef9d3b46b9ae74369fad67d5c016dbd97ea24d4c6f38a989d8b813f52f44`, CRLF
`c62dc5ba0f06f04997d792e81552a41faa9f983f4a1fb6ef3a59e8596dee05b5`.
Provider, engine, prompt, result, dependency versions/targets, manifest and
artifact-evidence values remain exact. No transport profile or selector change
is needed because the ordinary campaign engine did not change.

All fifteen historical profile literals and identities remain unchanged.
Historical and current checkout assertions are separate: historical auth pins
stay literal, current LF/CRLF auth/provider/manifest bytes match the new profile.
The current-source test now checks the provider bytes too, without its older
provider exception. New regressions pin the entire historical prefix and new
profile, require unique exact old/new selection independent of list order,
reject mixed/tampered descriptors and undeclared targets, and admit old/new
manufactured campaigns read-only with auth/provider imports disabled. They
establish compatibility only, never real OAuth, inference or market acceptance.

The earlier revision rationale below remains historical evidence.

## Scope and decision

Saved candidate admission compares complete, literal source-hash tuples and the
prompt hash against reviewed producer profiles. It does not infer compatibility
from the running checkout. These checks establish local artifact consistency,
not cryptographic authenticity, proof that a model ran, or investment quality.

The current campaign producer always hashes `research.py`, `provider.py`,
`core.py`, `strategies.py`, and `backtest.py` when recording its binding, including
for fixture and ChatGPT campaigns which do not use `HTTPTransport`.

The reviewed `provider.py` change is limited to:

- An optional `connection_verifier` callable, defaulting to `None`.
- Constructor rejection of non-callable, non-`None` values.
- When configured, connecting and retaining the actual socket, then calling the
  verifier before sending the HTTP POST, body or authorization header.

The default transport branch is unchanged. The configured branch can reject a
connection before any request content is sent. Existing deadline, response size,
JSON parsing, credential redaction and cleanup behavior remain in force. No
campaign generation, prompt, request construction, receipt accounting, strategy,
backtest, result schema, or provider-mode admission rules changed.

The audited campaign source hash for `provider.py` changes from
`ef7a1027b6b375cb1189a2282ce7f8025b60e023900b620f8c198a29d89e297f`
to `0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d`.
These are the producer's `content_hash` values for UTF-8-decoded source text,
not raw file SHA-256 values. Every other engine hash and the prompt hash remains
unchanged.

## Explicit profile extension

Two new, fully literal immutable profiles cover the new engine tuple:

- `TRANSPORT_VERIFIER_PRODUCER` uses protocol
  `mark_auto_0_2_2_campaign_transport_verifier_v1` and the prior exact ChatGPT
  implementation pairs. It is the canonical fixture/compatible profile.
- `TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2` uses protocol
  `mark_auto_0_2_2_campaign_transport_verifier_chatgpt_dependencies_v2`, restricted
  to ChatGPT mode and its separately reviewed dependency-target pairs.

The names identify support for this source revision. They do not claim that a
verifier was configured or that any peer was verified during a campaign.
The GUI's `LocalCompatibleProvider` inherits the existing `openai_compatible`
identity and can be admitted under its unchanged zero-rate request/receipt rules.
A literal unknown provider mode such as `local_free_ai` remains unsupported.
This does not establish authenticity of local-model or process-ownership claims.

`AUDITED_PRODUCER`, `CURRENT_PRODUCER`, and `CURRENT_CHATGPT_PROFILE_V2` retain their
original values and identities. No historical campaign, fixture hash, receipt,
or snapshot is rewritten. Historical and new-source descriptor profiles cannot
be selected interchangeably: the engine tuple must match first, followed by a
unique exact descriptor tuple and target. Non-ChatGPT selection explicitly adds
only the new canonical profile. Unknown or mixed engine hashes, unknown targets,
unsupported modes, malformed receipts and ambiguous profiles still fail closed.

## Test assertion migration

Only three pre-existing assertions change:

1. The real-spawn current-producer roundtrip compares the genuinely generated
   source tuple against `TRANSPORT_VERIFIER_PRODUCER`.
2. The genuine current fixture-to-walk-forward roundtrip compares against that
   same new source tuple.
3. That roundtrip expects the new protocol name in the admission snapshot.

These tests still generate real current campaign evidence without relabeling
any source hashes. Workload, timeout, success, candidate count, no-new-generation,
and no-source-rewrite assertions are unchanged. Historical profile identity and
admission assertions remain unchanged.

Additional regressions pin all prior profiles (including the dependency-target
extension), both new full profile values, the current source tuple and prompt;
cover both exact ChatGPT descriptor sets and their targets; and reject unknown
or mixed source/descriptor hashes, unknown targets, and an unknown literal provider mode; the GUI local provider identity is also
checked through generated-schema admission without invoking a model.
Existing saved-pool, research, result-reference and immutable serialization
checks remain required. Focused local tests do not establish native Windows or
frozen executable acceptance.

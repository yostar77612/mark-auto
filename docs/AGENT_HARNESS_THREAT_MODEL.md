# Agent harness threat model — TASK A1-D2

This models the offline [tool contract](AGENT_HARNESS_CONTRACT.md) and existing
strategy admission paths. The AI is a research assistant. Live trading is
permanently disabled, with no mutation tool in the production registry.
The reference project's trading authority, shell access and provider processes
are not capabilities of this harness. No conversation transport, skill loader
or D3 storage adapter is claimed here.

## Trusted components

Trust means reviewed application code, not permission conferred by model text.

| Component | Real module | Responsibility |
| --- | --- | --- |
| Core engine | `quantlab/core.py`, `quantlab/backtest.py` | Immutable typed strategy/data records, Decimal money, bounded offline evaluation |
| AST validator | `quantlab/research.py`, `quantlab/strategies.py` | Closed JSON DSL and recursive finite operator/type/depth/node allowlists |
| DPAPI store | `quantlab/assistant/adapters/chatgpt/auth.py` | Installation-local DPAPIVault, Windows ACL checks and explicit authentication lifecycle; read-only evidence for this task |
| Local journal | `quantlab/paper.py` | PaperBroker durable simulated events, risk latches and reconciliation; never a live broker |
| Tool boundary | `quantlab/agent_tools.py`, `quantlab/agent_tool_contract.py` | Host-owned handlers/grants/provenance, frozen read-only registry, strict input and output schemas |

## Untrusted inputs

- **Model output**, including proposed JSON, returned code, arguments, explanations
  and claims of permission.
- **Manual import files**, including strategy responses and saved results. A
  local filename or valid content hash does not establish trusted origin.
- **Remote-compatible API responses**, including malformed JSON, oversized
  responses, errors and plausible but incorrect strategies.
- Skill text, copied instructions and saved-result free text, including prompt
  injection that asks to reveal credentials, relabel partitions or grant tools.
  These remain data, even when they claim to be system instructions.

## Trust boundaries, controls and residual risk

| Boundary | Control | Residual risk |
| --- | --- | --- |
| Model/API response to strategy engine | Strict JSON admission followed by closed DSL/AST validation before strategy use; unknown operators/keys/types and resource excess fail closed | A valid strategy can be misleading, overfit or unprofitable; syntax validation proves no performance claim |
| Manual file to application records | Bounded JSON reader and dedicated manual-exchange strict parser, identity/context/schema checks, then DSL validation | Reporting read_json alone rejects nonfinite numbers but is not the duplicate-key validator or a provenance check; saved records must not be promoted to grants |
| Model arguments to tool dispatch | Bounded strict JSON/schema validation, explicit host capability grants, fixed handlers, all mutation execution denied | A compromised host can replace handlers; this is not an OS sandbox |
| Skill/saved-result text to authority | No skill loader or text interpreter in v1; prose and unknown argument fields refuse, extra record fields are not projected, text cannot supply grants or trusted context | Future skill loading needs its own schema/whitelist and injection tests; persuasive text may still mislead a human |
| Research partitions to tool returns/prompts | Host-derived training provenance; partition filter BEFORE counts/paging, positive field projection, typed bounded returns; OOS and final holdout never enter any AI conversation, tool return or prompt | A host adapter falsely labelling mixed-period data/counts as training defeats provenance; future D3 adapters must derive training-only evidence, never trust user labels |
| Protected local state to model-visible fields | No free-text/raw-file/path/credential fields in tool returns; fixed empty-parameter refusals, no exception echo | Future tools must extend the all-tool sentinel fixture; schema alone cannot determine the provenance of an integer |
| Credential storage to harness | Credentials never leave DPAPI through harness outputs, prompts, logs or saved research; the harness has no vault access | DPAPI is at-rest protection, not a promise that tokens never enter memory: existing authorized authentication unseals tokens and sends them to its intended endpoint; same-user compromise and real Windows ACL/DPAPI QA remain outside these fixture proofs |
| Engine/journal to external effects | Live trading permanently disabled; frozen production registry has zero mutation tools and no trade/order/amend/cancel/place names; simulated journal remains local | Trusted code/OS compromise is outside this boundary; Paper is not evidence of real fills |
| Evaluation to durable guards/budget/deadlines | Existing one-time OOS/holdout consumption, irreversible budget and fail-closed gates remain; Paper 30 s, smoke 40 s, job 15 min unchanged | Local deletion/rollback can destroy audit evidence and cannot make seen data unseen; failure/timeout does not refund or authorize retry |

## Evidence: no-execution

**Model-returned code is never executed.** Only finite JSON strategy data can
reach the existing strategy interpreter; Python/JavaScript snippets, imports
and unknown operators are rejected. No dynamic code execution is added.

- `docs/adr/0004-restricted-ast-rules.md`
- `quantlab/research.py::validate_dsl`
- `quantlab/strategies.py::_validate_node`
- `tests/test_strategies.py::StrategyTests.test_reject_ast_attack_and_negative_lag`
- `tests/test_agent_harness_d1.py::AgentHarnessD1Tests.test_new_core_modules_have_no_dynamic_execution_or_ui_imports`

## Evidence: ast-validation

**Model output passes AST validation before any use as a strategy.** The
campaign calls validate_dsl before evaluation/fingerprinting; validate_strategy
also enforces executable registry semantics. Raw bounded output may be retained
locally for audit before AST validation; that is not execution or authority.
Tool arguments are a separate closed strict JSON/schema protocol, not strategy
ASTs, and cannot carry executable code.

- `quantlab/research.py::run_campaign`
- `quantlab/research.py::validate_dsl`
- `quantlab/strategies.py::validate_strategy`
- `tests/test_research.py::ResearchTests.test_reject_corpus`
- `tests/test_research.py::ResearchTests.test_ast_depth_and_lag`
- `tests/test_agent_harness_d2.py::ThreatModelD2Tests.test_model_strategy_output_rejects_code_and_unknown_ast`

## Evidence: credentials

**Credentials never leave DPAPI through the agent harness.** This claim is
scoped to the model boundary above, not the authorized authentication transport.
The locked auth source is cited read only; no credential store is opened by
these tests. Synthetic credentials/tokens never appear in any tool output.

- `quantlab/assistant/adapters/chatgpt/vault.py::DPAPIVault`
- `quantlab/agent_tools.py::Registry.call`
- `tests/test_agent_harness_d1.py::AgentHarnessD1Tests.test_every_registered_read_tool_and_all_pages_are_sentinel_safe`
- `tests/test_agent_harness_d1.py::AgentHarnessD1Tests.test_invalid_return_and_exception_do_not_echo_raw_content`

## Evidence: imports-and-api

- `quantlab/reporting.py::read_json`
- `quantlab/manual_exchange.py::_strict`
- `quantlab/manual_exchange.py::_validate_response`
- `quantlab/provider.py`
- `tests/test_manual_exchange.py::ManualExchangeTests.test_identity_family_context_extra_duplicate_and_code_rejected`
- `tests/test_research.py::ResearchTests.test_provider_rejects_duplicate_and_nonfinite_json`

## Evidence: partition-and-injection

The D3/D11 information boundary is currently exercised by the D1 in-memory
read tool, not a full saved-results tool suite. Its recursive oracle walks all
fields of every registered read tool and every fixture page, including empty
and protected-only contexts. Protected fixture values cover OOS/holdout prices,
returns, metrics, trades, equity, row counts, consumed guards, credentials,
tokens, local paths, user names and raw files. Removing the partition filter
makes the same oracle fail. The D7 regression below tests injected skill text
and saved results against today's boundary without claiming D7 loading exists.

- `quantlab/agent_tools.py::_training_records`
- `quantlab/agent_tools.py::_training_status`
- `quantlab/agent_tool_contract.py::strict_json`
- `tests/test_agent_harness_d1.py::AgentHarnessD1Tests.test_every_registered_read_tool_and_all_pages_are_sentinel_safe`
- `tests/test_agent_harness_d1.py::AgentHarnessD1Tests.test_sentinel_oracle_fails_when_partition_filter_is_removed`
- `tests/test_agent_harness_d7.py::PromptInjectionD7BoundaryTests.test_skill_and_saved_result_text_cannot_grant_authority`
- `tests/test_agent_harness_d7.py::PromptInjectionD7BoundaryTests.test_saved_result_injection_cannot_change_projection_or_provenance`

## Evidence: disabled-live-and-local-state

- `quantlab/agent_tools.py::Registry.resolve`
- `quantlab/paper.py::LiveBroker`
- `quantlab/paper.py::PaperBroker`
- `docs/adr/0001-oos-consumption-and-budget.md`
- `docs/adr/0002-paper-is-a-journal.md`
- `tests/test_agent_harness_d1.py::AgentHarnessD1Tests.test_production_read_only_frozen_registry_and_copied_declarations`

## Verification limits

The D2 evidence checker resolves every backticked repository path in the
Evidence sections and verifies definition symbols where specified. Mandatory
claim references cannot be silently dropped; negative controls remove a path
and corrupt a symbol. This detects stale citations, not proof of arbitrary
semantic claims. The document scan rejects local paths, usernames and secret
shapes. All checks are offline and deterministic. Real authentication,
clean-machine DPAPI/ACL behavior and broader CI remain separate verification.

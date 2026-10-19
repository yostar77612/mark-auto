# Terminology and tooltip style

This guide defines the writing policy for new and revised desktop text. The
[glossary](../GLOSSARY.md) is authoritative for domain meanings; this guide does
not rename existing catalog entries or certify that every existing string
already follows the policy. Live trading remains permanently disabled.

## Recorded coverage and its limits

The existing [T16 measurement](../analysis/t16_tooltip_metrics.json) records:

| JSON field | Recorded count |
| --- | ---: |
| `tooltip_widgets` | 89 |
| `visible_inputs` | 41 |
| `inputs_with_tooltips` | 30 |
| `obvious_controls_without_tooltips` | 11 |
| `non_obvious_inputs_without_tooltips` | 0 |

The 41 default-visible inputs comprise 30 with tooltips and 11 obvious controls
without them. The 89 tooltip widgets are a separate widget count, not 89 inputs.
The [T16 policy and evidence](../analysis/t16_final_targets.md) identify the
seven-page default-view scope and list the 11 exceptions by catalog key with
individual reasons. The JSON labels its SHA as `HEAD at commit time`; it does
not pin a commit hash. These are recorded measurements, not a claim of complete
coverage of all hidden controls, future pages, wording quality or physical
display configurations.

## Canonical terminology

Use these exact English/Traditional Chinese pairings from the glossary. Prefer
the Chinese wording in ordinary labels; introduce the English term in help
when it helps identify a technical concept. Preserve the distinctions in the
glossary rather than using the terms interchangeably.

| English | Traditional Chinese | Writing constraint |
| --- | --- | --- |
| Backtest | 回測 | Results depend on historical data and execution assumptions. |
| Paper | 紙上交易 | Offline synthetic account events; no claim of real fills. |
| Replay | 重播 | Bounded historical execution driving Paper; do not equate its fill semantics with Backtest. |
| Research eligibility | 研究資格 | Does not automatically confer Paper eligibility. |
| Paper eligibility | 紙上資格 | Requires its own strategy, data, risk and accounting policies. |
| OOS | 樣本外 | One-time evaluation after candidate freezing; not iterative selection data. |
| Holdout | 保留集 | Final evaluation data separate from training, validation and OOS. |
| Consumed guard | 已消耗防護 | Persistent consumed state; overlapping reserved intervals in the same workspace are also seen. |
| Irreversible budget | 不可逆預算 | Failure, interruption or unknown outcome does not refund reserved consumption. |
| Strategy artifact | 策略成品 | A managed strategy concept; its name is not immutable content identity. |
| Strategy revision | 策略修訂 | Fixed immutable content; edits form another revision. |
| Live trading | 實盤交易 | Permanently disabled in this product. |

## Tooltip rules for authors and reviewers

- Require a nonempty tooltip for every non-obvious input: explain its meaning,
  unit or format, and any consequential constraint or prerequisite. A short
  label alone is insufficient when users must infer those details. Keep the
  existing default-view exceptions explicit in the T16 policy; do not silently
  expand its allowlist. Disabled actions also need a reason and an adjacent
  prerequisite hint, following the [engineering contract](../agent/IMPLEMENTATION_CONTRACTS.md).
- Limit new or revised explanatory tooltips to **120 Unicode characters after
  substitution, including spaces and punctuation**, in **one or two complete
  sentences**. Start with the input meaning or action, then give the constraint
  or consequence. Use Traditional Chinese sentence punctuation, ending with
  `。`; a semicolon may join closely related clauses. Put longer procedures in
  linked help or advanced details. Exact raw-value diagnostic tooltips retain
  their evidence role and are outside this explanatory-text length rule.
- Use plain language. Do not introduce unexplained jargon: use a glossary term
  and explain it on first use; if a necessary domain term is missing, add its
  reviewed definition to the glossary before using it. An uppercase-token
  allowlist in T16 is a technical scan policy, not permission to omit an
  explanation. Keep internal identifiers in advanced diagnostics.
- Describe the actual input and current behavior. Preserve units, blank-value
  defaults, consent requirements and failure conditions. Never promise profit,
  guaranteed performance, real fills or live execution. Paper eligibility never
  unlocks Live trading. State that Live trading is permanently disabled when
  execution scope could otherwise be ambiguous.
- Preserve fail-closed validation, OOS one-time consumption, Consumed guard and
  Irreversible budget semantics. Never suggest that cancellation or failure
  refunds consumption. OOS and final Holdout data must never enter an AI
  conversation, tool return or prompt. Do not solicit credentials in help text.
  Keep the existing Paper 30 s, smoke 40 s and 15 min per-job timeouts unchanged.

## Current catalog examples

Each quoted value below exists verbatim in
[desktop_strings.py](../../desktop_strings.py). These are current text, not
proposed replacement strings.

| Catalog key | Current value | Why it is useful |
| --- | --- | --- |
| `tooltip.import_path` | 要匯入的本機資料檔完整路徑；格式須符合下方選擇的資料類型。 | Meaning followed by a format constraint. |
| `tooltip.entry_bps` | 突破進場門檻，以基點表示；100 基點等於 1%。 | Unit and conversion are explicit. |
| `tooltip.quantity` | 每次策略訊號的委託口數；留白使用預設 1 口，仍須通過部位與風控限制。 | Default and remaining risk checks are explicit. |
| `tooltip.replay_bars` | 本次紙上重播最多讀取的歷史 K 棒根數；不是委託口數，也不會送出真實交易。 | Separates the input unit from order quantity and states execution scope. |

## Observed catalog inconsistencies; no string changes in E5

These are wording observations, not findings that execution behavior is wrong.
The values are also verbatim current catalog text.

| Catalog key | Current value | Observation |
| --- | --- | --- |
| `logs.operation.ui_paper_snapshot` | 讀取模擬帳戶 | Paper log wording uses 模擬 rather than the canonical 紙上交易 wording. |
| `logs.operation.ui_paper_replay` | 重播模擬交易 | The same variation appears in the replay log label. |
| `ui.analysis_preview_text.text_1` | 僅傳送以下訓練 OHLC／指標及重新計算的 train／validation 摘要；不傳送樣本外／holdout。 | Mixes English training/validation terms and lowercase holdout with Chinese; canonical Holdout is 保留集. |
| `tooltip.bars` | 建立合成示範資料的 K 棒根數；只供操作練習，不代表真實行情。 | Uses a space in K 棒, whereas the catalog's `GLOSSARY` entry for `bar` uses K棒. |

Review any future wording change separately with its affected tests and
snapshots. This item leaves the catalog and default views unchanged.

## Adding text and verifying it

All new UI strings must be added through `desktop_strings.py` and referenced
with literal `ui_text` keys. Error messages use the existing B1
[`ERROR_TABLE`](../../quantlab/errors.py), without a second message table or raw
exception text. Review the glossary pairing, rendered length after substitution,
sentence form, units, prerequisites and execution disclaimer for each change.

[`tests/test_t16_tooltips.py`](../../tests/test_t16_tooltips.py) must pass
unmodified. From the repository root, with `QT_QPA_PLATFORM=offscreen` and
`PYTHONUTF8=1`, use the configured Python interpreter for each module separately:

```text
python -m unittest discover -s tests -p test_t16_tooltips.py
python -m unittest discover -s tests -p test_docs_layering.py
python -m unittest discover -s tests -p test_repo_layout.py
```

For quoted examples, look up each listed literal key and compare the value
verbatim in the catalog; for coverage, compare every table count with the JSON.
These are offline checks. The T16 test covers default inputs, rebuilt strategy
fields, domain tokens and presentation invariants; it does not enforce this
guide's new length or sentence policy. Run the pinned Ruff, Python 3.11 compile
check and quality gate as described in the
[contributor guide](../CONTRIBUTING.md). A command listed here is a required
check, not a claim that an unperformed run passed.

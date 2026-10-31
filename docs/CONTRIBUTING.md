# Contributing

Keep each PR focused and use the [PR template](../.github/pull_request_template.md).
Read the [implementation contracts](agent/IMPLEMENTATION_CONTRACTS.md),
[project state](agent/PROJECT_STATE.md), [ADRs](adr/) and [glossary](GLOSSARY.md).
Feature PRs must not edit `docs/agent/PROJECT_STATE.md`. Append the item's behavior
contract to `docs/agent/IMPLEMENTATION_CONTRACTS.md`; do not change acceptance scores
or present unverified work as passed. Formal acceptance remains 230/300 in
[ACCEPTANCE.json](agent/ACCEPTANCE.json).

## Safety and ownership

Live trading is permanently disabled. Do not add a real order-placing path or
broker import. Never loosen fail-closed gates, OOS one-time consumption,
irreversible budgets or timeouts (Paper 30 s, smoke 40 s, 15 min per research job).
Failures, cancellation and unknown outcomes do not refund consumed budget.
OUT-OF-SAMPLE and FINAL-HOLDOUT data must never enter AI conversations, tool
returns or prompts. Treat AI output as untrusted input validated by the existing
AST rules; do not add dynamic execution. Money calculations stay `Decimal`.
Do not read, store or display ChatGPT credentials.

The G3 locked file set covers the following 30 source files. They must not be edited
without owner approval:

- `quantlab/research.py`
- `quantlab/provider.py`
- `quantlab/core.py`
- `quantlab/strategies.py`
- `quantlab/backtest.py`
- `quantlab/data.py`
- `quantlab/assistant/adapters/chatgpt/auth.py`
- `quantlab/assistant/adapters/chatgpt/provider.py`
- `quantlab/assistant/adapters/chatgpt/vault.py`
- `quantlab/assistant/adapters/chatgpt/identity.py`
- `quantlab/assistant/adapters/chatgpt/loopback.py`
- `quantlab/assistant/adapters/chatgpt/account_summary.py`
- `quantlab/assistant/adapters/chatgpt/account_paths.py`
- `quantlab/assistant/adapters/chatgpt/response_stream.py`
- `quantlab/assistant/adapters/chatgpt/transport.py`
- `quantlab/assistant/adapters/chatgpt/provenance.py`
- `quantlab/assistant/adapters/chatgpt/account_store.py`
- `quantlab/assistant/adapters/chatgpt/resolution_audit.py`
- `quantlab/assistant/adapters/chatgpt/unknown_reconciliation.py`
- `quantlab/assistant/adapters/chatgpt/finished_reconciliation.py`
- `quantlab/assistant/adapters/chatgpt/campaign_receipts.py`
- `quantlab/assistant/domain/auth_protocol.py`
- `quantlab/assistant/domain/auth_tokens.py`
- `quantlab/assistant/domain/plan_protocol.py`
- `quantlab/assistant/domain/source_components.py`
- `quantlab/assistant/ports/auth.py`
- `quantlab/research_core/domain/receipts.py`
- `quantlab/assistant/domain/__init__.py`
- `quantlab/assistant/ports/__init__.py`
- `quantlab/research_core/domain/__init__.py`

The owner approved relocation and splitting of G3 files for this refactor on
2026-10-29, with unchanged behavior and per-file QA. The list above names their
current paths; historical producer hash keys retain their original names.
Preserve all existing profile blocks in `quantlab/saved_candidate_pool.py` byte
for byte. New source identities require an explicit new current profile; never
re-pin historical profiles to the moved sources.
New UI strings go through [desktop_app/strings/catalog.py](../desktop_app/strings/catalog.py) with literal
`ui_text` keys; no hardcoded CJK literals in desktop modules or pages. Error text
uses the single B1 `ERROR_TABLE` in [quantlab/errors.py](../quantlab/errors.py).
Do not weaken, skip or delete existing tests or rewrite baseline fixtures to
conceal behavior changes.

## Fast pre-push check

### Owner-authorized v2 engineering mission (2026-10-25)

The separate `quantlab/trading` and `desktop_app/features/trading` platform is governed by
[the v2 upgrade contract](implementation/multi-market/UPGRADE_CONTRACT.md).
The owner authorized its controlled connector implementation and necessary
engineering upgrades. The permanent live prohibition above remains the v1
contract; it is not silently removed. V2 defaults to local simulation and its
broker connector remains disconnected/read-only/execution-disabled. This mission
does not authorize real financial operations, credential discovery, remote pushes,
merges or releases. Preserve all historical v1 profiles, results and safeguards.
Run the additional AST layer gate and v2 behavior tests alongside existing gates.

Before pushing, run `powershell -File tools/prepush.ps1` (add `-Tests` to also run the
unit tests of changed files). It is offline and runs Ruff check and format, a Python 3.11
syntax scan of every tracked `.py`, and `tools/quality_gate.py`; it exits nonzero on failure.

## CI behavior for pull requests

- Documentation-only PRs (only `docs/**`/`*.md`/PR template that no test or tool reads;
  see `tools/ci_changes.py`) run Ruff, the static/credential gate and the aggregate
  `Quantlab gates complete` check; heavy test groups are skipped. Pushes to main, tags and
  manual runs always run everything.
- The Windows installer workflow runs on a PR only when packaging inputs change
  (`packaging/**`, `requirements*`, `*.spec`, `*.iss`, `tools/make_icon.py`,
  the dependency manifest). It always runs on main, `desktop-v*` tags and manual dispatch.
- New pushes to a PR cancel its older runs. If a job must be rerun, use **Re-run all jobs**
  (G8): the aggregate coverage check only accepts evidence from a single run attempt.
- Linux UI dependencies run the original core/research module partitions on separate
  15-minute jobs. The mandatory `ui` aggregate independently discovers the complete
  suite and verifies exact execution, source/runtime/run/attempt identity and the
  original Linux applicability skips. All five Streamlit cases are mandatory.
  This retains full UI coverage without extending job or test timeouts.
- Linux offline 3.11/3.12 uses the same original module partitions and independent
  exact coverage under its original dependency profile. Its stable mandatory
  check names require both producers, exact original applicability skips and
  matching source/run/attempt/Python/SQLite; they cannot replace the UI profile.

## Local verification

Run from the repository root in PowerShell. Use Python 3.11 (`py -3.11`). Ruff
**0.16.10** is pinned with hashes in
[requirements-ruff.lock](../requirements-ruff.lock); configuration is in
[pyproject.toml](../pyproject.toml). For developer environment setup, see
[tools/dev_setup.ps1](../tools/dev_setup.ps1).

For the controller's Windows lane environment, the shared tools below are already
provisioned. These commands use that environment and do not install dependencies:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe' --version
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe' check .
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe' format --check .
py -3.11 -m compileall -q quantlab desktop_app tools tests desktop.py
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe' tools/quality_gate.py
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe' -m unittest discover -s tests -p test_docs_layering.py
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe' -m unittest discover -s tests -p test_repo_layout.py
```

Each check must exit 0, including [tools/quality_gate.py](../tools/quality_gate.py).
Record the exact commands and exit codes in the PR, including any failures.
In Windows worktrees, a known CRLF checkout issue may cause repo-wide formatting
to flag only `docs/adr/0006-strategy-intent-pipeline.md`. Do not normalize that
design document for this item; report the failure and separately check
changed files. This exception is not a claim that the repo-wide check passed.

Unit tests live under [tests/](../tests/). Run each affected module separately
using the discovery form above; dotted test names can be shadowed by an installed
package. Add the modules relevant to the change and record which modules ran.
These two documentation checks alone do not verify runtime behavior or full CI.
Keep new tests offline, deterministic and cheap; do not extend timeouts.
For Windows retained-handle tests and symlink prerequisites, follow
[Windows native testing](windows-native-testing.md); a virtual-environment
redirector is not the Python child whose handles the observer must retain.

CI definitions are [quantlab.yml](../.github/workflows/quantlab.yml)
(Quantlab offline gates) and
[windows-desktop.yml](../.github/workflows/windows-desktop.yml)
(Windows desktop installer). Inspect their actual jobs when reporting CI
evidence; a local check does not establish that a workflow passed.
This documentation task does not publish a GitHub Release or create a git tag.

The developer-only workspace runs from the repository root with
`streamlit run tools/research_app.py`; this retains the repository-local
`.streamlit/config.toml` server/privacy settings. It is excluded from the installer.
Install it with `python -m pip install -r requirements-ui.lock` followed by
`python -m pip install --no-deps -r requirements-ui-pillow.lock`; the second step is a
deliberate Pillow 13 override of Streamlit's `pillow<13` metadata (see that file).


## Resulting structure and section 4 rules

## 現行責任與路徑

| 路徑 | 責任 |
|---|---|
| `desktop_app/shell/` | 視窗、頁面組裝、生命週期、應用服務接線 |
| `desktop_app/features/` | 各功能 widget、presenter 與 view-model |
| `desktop_app/components/` | 共用表格、表單、圖表、隱私與非同步狀態顯示 |
| `desktop_app/strings/` | 按功能拆分的字串與單一查詢入口 |
| `desktop_app/smoke/` | 桌面啟動、TLS 與 UI smoke 驗證 |
| `quantlab/research_core/domain/` | 研究協定與純資料／證據語意 |
| `quantlab/research_core/application/` | 研究、分析、paper 與 UI 資料作業用例 |
| `quantlab/research_core/ports/` | 用例依賴的 Protocol 介面 |
| `quantlab/research_core/adapters/` | 工作區、備份、程序、資料來源與具體服務接線 |
| `quantlab/assistant/domain/` | 認證、方案、回應與來源資料協定 |
| `quantlab/assistant/application/` | 助手連線與操作協調 |
| `quantlab/assistant/ports/` | 外部認證與服務 Protocol |
| `quantlab/assistant/adapters/chatgpt/` | ChatGPT HTTP、認證、憑證與 receipt 實作 |
| `quantlab/shared/` | 至少三個使用點所證明的核心共用純函式 |
| `quantlab/trading/domain/` | v2 交易領域資料與規則 |
| `quantlab/trading/application/` | v2 用例與服務協調 |
| `quantlab/trading/ports/` | broker、資料與儲存介面 |
| `quantlab/trading/adapters/` | 具體外部介接；SDK 僅經受限 lazy loader |
| `quantlab/trading/runtime/` | 本機程序、IPC 與 composition |
| `tools/` | 品質閘門、開發、機械遷移與診斷工具 |
| `packaging/` | 凍結、安裝、授權與發布驗證 |

`quantlab/research.py` 保留原模組位置，避免模組與套件同名；僅清單指定的研究責任
進入 research_core。`quantlab/saved_candidate_pool.py` 保留歷史 producer profile
原文，新來源使用新的 current profile，不重釘歷史 hash。

## 分層與依賴

Domain 只依賴 domain/shared；application 只依賴 application/domain/shared。
Infrastructure（adapters）依賴 domain/shared 與明確的 application ports，不能反向
依賴具體用例。Presentation 依賴 application/domain/shared，不直接接 SDK、磁碟或
具體 infrastructure。Shared 不依賴其他產品層。Composition 負責建構並傳入具體依賴；
tooling 可跨層診斷，產品 runtime 不反向匯入 tooling。

Widget 只呈現狀態與送出意圖；流程、驗證與副作用由 presenter、用例與 adapter 負責。
`tools/check_layers.py` 以明確分類與只能縮減的 allowlist 檢查依賴；既有安全閘門獨立執行。

## 規格第 4 節的工程規則

依責任拆分；檔案 400、類別 300、函式 50 行是可讀性目標，例外須在盤點表寫出理由。
超過 600 行的檔案必須有拆分方案。第三個呼叫點出現才抽共用（rule of three）；
只有 UI 使用的共用放 components，核心共用放 shared。

外部服務以 `typing.Protocol` ports 表達契約，只有已有多實作或測試隔離需求才引入。
組裝點使用普通 dict registry 或 `create_xxx(config)` 函式；不新增 Factory 類別階層、
Singleton、Builder、深層繼承或 DI 框架。依賴由建構子明確傳入。

使用者輸入、API、磁碟／反序列化與 IPC 要驗證；已確立的內部型別不重複 None 檢查，
不以 getattr fallback、理論性 catch 或無使用者的 Optional 擴充點掩蓋程式錯誤。
Shioaji 載入限制、pickle/eval／動態執行禁令、live／credential／TLS 防護、OOS／holdout、
不可逆預算、deadline、未知結果 fail-closed、來源 hash、路徑與 restore 證據全部保留。

搬檔、import、字串 patch target 與私有呼叫的機械修改須以 `tools/refactor/` 中的腳本重現。
不留 re-export shim、模組別名或 `sys.modules` 相容層。
See [architecture](analysis/01_PROJECT_ARCHITECTURE.md) and [inventory](analysis/08_REFACTOR_INVENTORY.md).


PR E runtime ownership: `quantlab/research_core/adapters/workspace_store.py`,
`settings_store.py`, `state_json.py`, `runtime_safety.py`, `event_log.py` and
`walk_forward_owner.py` own workspace and runtime IO. The lifecycle coordinator is
`quantlab/research_core/application/job_manager.py`; its process, storage and log
contracts live in `quantlab/research_core/ports/jobs.py`. Default adapters are
composed by `desktop_app/research_bootstrap.py` without importing Qt; the Qt
session lives in `desktop_app/research_session.py`. CredentialVault,
DesktopCredentialReference and the atomic_write binding remain in
`quantlab/desktop_runtime.py`. Historical producer profiles and G3 locks are unchanged.

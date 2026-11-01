# M3 規格書：AI 研究策略 → 券商模擬自動交易 → 擁有者核准正式

Status: SPEC FOR IMPLEMENTATION / NOT IMPLEMENTED. Verification: NOT RUN.
Audience: implementing agent (Codex). Owner decisions dated 2026-11-01.
前置與關係：[M2 規格](m2-sinopac-sim-auto-trading-spec.md) 的 M2-1～M2-9 是本規格的底座（M2 正由其他分支實作中，**本規格不修改 M2 的任何檔案**）。
M3-1～M3-3 只新增檔案，可在 M2 第二輪進行時同步開工；碰到 M2 共用檔的工作（M3-4 起）須等對應的 M2 工作合併後才開始（第 13 節）。

> 命名提醒：[M2 規格第 7 節](m2-sinopac-sim-auto-trading-spec.md) 把「五檔與成交明細、類股排行、手機推播、正式下單啟用流程」記為「延後到 M3」。
> 擁有者 2026-11-01 指定的 M3 是**本文件的範圍**（AI 研究策略接到自動交易）。上述延後項目**不在本文件**，建議另列為 M4（見第 16 節 OQ-14）。

## 0. 工作規則

全部沿用 [Codex 作業規則](codex-work-rules.md)（R1–R11）與 [M1 規格](m1-implementation-spec.md) 第 0、0.1（不過度防禦）、0.2（能併行就併行）、0.3（自主決策、不提問、不停下）節，
以及 [M2 規格第 0 節](m2-sinopac-sim-auto-trading-spec.md) 的啟動檢查與基準 commit 規則。本次特別強調：

1. **只在邊界驗證**：候選證據、使用者輸入、檔案讀取是邊界；通過 `build` 後的凍結規格（第 6.1 節）在內部互相信任，不重複驗證。
2. **不動 G3 鎖定檔**：`quantlab/strategies.py`、`core.py`、`backtest.py`、`research.py`、`data.py` 等（[CONTRIBUTING](../CONTRIBUTING.md) G3 清單）一個字都不改（第 3 節 F1）。
3. **基準集中一次**（R1、R4、R11）：第 8 節已預先列出全部新檔案、字串、物件名稱、錯誤碼；子分支不碰共用基準檔，整合分支以一組 `test(baseline)` commit 一次登記。
4. 編輯任何既有函式／類別前跑 GitNexus impact（`AGENTS.md`）；`UiAction`、`UiCommand`、`AppState`、IPC `Operation`／`_dispatch` 在 M1 紀錄中為 CRITICAL，M3-4 的 PR 說明必須列出 impact 結果與逐一測過的相關測試。
5. 所有測試只用 fake SDK 與 fixture，**不得登入永豐**；不得讀取真實金鑰。
6. 新 UI 遵守 [介面設計準則](ui-guidelines.md)，PR 附準則第 10 節檢查清單。文件用繁體中文；程式碼、commit、PR 用英文。

## 1. 問題

現況有兩條互不相通的線：

- **v1 研究線**：`quantlab/strategies.py` 的五個家族（`trend`、`mean_reversion`、`channel_breakout`、`momentum`、`volatility_compression`，各帶參數）
  加上受 AST 驗證的規則樹（`long`／`short`／`exit`），在日 K 上走 回測 → 滾動式驗證（walk-forward）→ 一次性樣本外（OOS）。AI 只能提出候選，結果由主機端驗證。
- **v2 交易線**：[`StrategyDefinition`](../../quantlab/trading/domain/strategy.py) 只有 `MA_CROSS`／`BREAKOUT`／`BUY_AND_HOLD`／`STRUCTURED_JSON`，
  規則欄位僅 `close／sma5／sma20／return5／volume`、週期 `1m／5m／1d`，無狀態；它能表達的策略遠少於 v1 研究出來的候選。

結果：AI 研究出的通過驗證的策略**無法**進入自動交易；若要手動翻成 v2 規則，行為會改變，回測證據就不再適用。
擁有者決定（2026-11-01）：**不做翻譯層**，v2 直接執行研究時用的同一個信號函式；通過的候選以「建成自動交易策略」動作變成自動交易策略，
先在券商模擬自動晉級，達標後由擁有者按一下才進入「正式」，且正式下單目前硬性關閉。

## 2. 擁有者決定（2026-11-01）

| # | 決定 |
|---|---|
| M3-D1 | v2 執行**研究時使用的同一個信號函式**（`generate_signals`），不做 v1→v2 規則翻譯。 |
| M3-D2 | 通過研究的候選可用「**建成自動交易策略**」動作變成自動交易策略：選持有型態（當沖／短波／長波）、商品、配置；規格**凍結並雜湊**；AI 只提案，任何參數變更 = 新版本。 |
| M3-D3 | 當沖需要分鐘 K（依賴 M2-7）。 |
| M3-D4 | **漂移自動暫停**：模擬虧損超過回測最大回撤的 **1.5 倍**時自動暫停。 |
| M3-D5 | 階段只有兩個：**回測 → 券商模擬 → （擁有者按一下）→ 正式**。券商模擬內自動晉級：門檻 ≥10 個交易日且績效不比回測差太多；長波改用「≥3 次完整來回交易」。 |
| M3-D6 | **本機模擬是工具**（離線／回放），**不是階段**。 |
| M3-D7 | **絕不自動晉級到正式**；正式下單維持硬性關閉，並有測試證明。 |
| M3-D8 | OOS／最終保留資料**永遠不得**進入 AI 對話、工具回傳或提示。 |
| 沿用 | M2 的 D1（正式下單預設停用）、D6（當沖只做微台 TMF；短波、長波只做股票）、D9（部位大小）、D10（換月）。 |

## 3. 現況證據與六個關鍵發現

以下是讀程式後確認的事實，直接決定設計；每項都有「因此」。

| # | 發現（證據） | 因此 |
|---|---|---|
| F1 | 信號函式與其資料型別受 **G3 鎖定**：`strategies.py`、`core.py`、`backtest.py`、`research.py`、`data.py`（[CONTRIBUTING](../CONTRIBUTING.md)）。`walk_forward.py` 的 `SOURCE_FILES` 把它們納入來源指紋，任何改動都會使既有研究證據失效。 | M3 **不改動**這些檔案；v2 只能經 port 呼叫它們（第 7 節）。 |
| F2 | v1 `Bar` 只接受 `TAIFEX:TMF:YYYYMM` 契約與**整數價**（[core.py](../../quantlab/core.py) `validate_contract`、`validate_decimal(tick=True)`），研究範圍限 TMF（[ADR 0003](../adr/0003-tmf-research-scope.md)）。股價（如 585.5）進不去 `generate_signals`。 | 今天的 v1 信號函式只能服務 **TMF**。短波、長波（只做股票，M2 D6）必須等「股票研究範圍」——這需要擁有者核准修改 G3 檔，列為 **M3-9（延後，預設不啟動）**。 |
| F3 | 分層閘門：[`tools/check_trading_architecture.py`](../../tools/check_trading_architecture.py) 規定 `quantlab/trading/{domain,ports,application,adapters}` 只能 import `quantlab.trading.*`（application／adapters 另可 `quantlab.errors`），
  所以**不能** import `quantlab.strategies`；只有 `quantlab/trading/runtime/`（composition，見 [layer_map.json](../../tools/layer_map.json)）可以。presentation 只允許清單內的 application 模組。 | 橋接程式放 `runtime/`；application 只認 port；presentation 用的檢視 DTO 需在 check_trading_architecture 的允許清單新增**一個**模組（先例：M1 的 `alert_contracts`）。 |
| F4 | 語意不同：v1 `generate_signals` 是「整段歷史 → 目標部位序列」，**有狀態**（`momentum` 的 `max_holding_bars`、`mean_reversion` 回到均值出場、規則的 `exit`）；v2 `Rule` 是無狀態條件，欄位只有 5 個，無法表達 `highest／lowest／return_bps／lag`。 | 不翻譯。v2 新增「**信號策略**」型態：每根 K 棒完成時，用凍結的錨點重算整段歷史，取最後的目標部位。以「前綴一致性」測試證明即時 == 回測（第 6.3 節）。 |
| F5 | v1 回測內建 `stop_ticks`／`target_ticks`（盤中停損停利）、保證金、結算（[backtest.py](../../quantlab/backtest.py) 約第 298 行起），無法抽出給 v2 用。 | 第一版**拒絕**含 `stop_ticks`／`target_ticks` 的候選；v1 證據只當「候選資格閘」，**另在實際執行資料上用 v2 的保護性停損與成本重跑一次**當執行證據（第 6.4 節）。 |
| F6 | v1 資料集 `source_type` 只收 `synthetic／proxy／official_local`（[backtest.py](../../quantlab/backtest.py) `_run`），券商分鐘 K 不能進 v1 回測；v1 今天產出的候選都來自 TMF 日 K。 | 分鐘 K 的證據只能在 v2 側產生（M2-7 的分鐘回測引擎 + 本規格的信號策略研究，M3-7）。日 K 候選資格閘不等於分鐘證據，UI 必須明講（第 11 節）。 |

另有兩項既有行為要遵守：

- [`domain/strategy.py`](../../quantlab/trading/domain/strategy.py) 的 `STAGES`／`ResearchEvidence`／`StrategyVersion` 目前只有測試使用，**不沿用**其六階段模型，也不修改（避免動到 M2 檔案與 `tests/test_trading_domain.py`）；M3 另立兩階段模型（第 9 節）。
- `ProducerProfile` 的來源指紋涵蓋 `quantlab/trading/**/*.py` 全部檔案（[runtime/provenance.py](../../quantlab/trading/runtime/provenance.py)），所以**每次升級**程式，v2 研究證據的 `source_digest` 都會變。M3 另存 `behavior_hash`（只含輸入與交易結果，不含來源指紋），用來區分「程式改了但行為一樣」與「行為真的變了」（第 6.4 節）。

## 4. 目標與非目標

### 目標

1. 通過 v1 驗證的候選可在 UI 按「建成自動交易策略」，變成 v2 的信號策略；規格凍結、雜湊，之後只能產生新版本。
2. v2 用**同一個信號函式**決定目標部位；有自動化測試證明「逐根 K 棒的即時決策 == 一次性回測的信號序列」。
3. 建成後先有「執行資料回測」證據；自動在**券商模擬**執行；每個完整交易日收盤後自動評估晉級；達標只顯示「可申請正式」，等擁有者點擊。
4. 漂移監控：模擬回撤超過回測最大回撤 × 1.5 自動暫停該策略的新倉（保護性出場保留）。
5. 全部門檻是具名、有版本的設定，不散落在程式裡。
6. 安全不退讓：正式下單送單路徑仍硬性關閉並有測試；OOS／最終保留資料不進 AI；M3 不新增任何會把證據、績效或模擬結果交給 AI 的路徑。

### 非目標

- **不實作正式下單**，也不實作「正式」階段的實際執行。「核准正式」只記錄擁有者的決定（第 9 節）。
- 不修改 G3 檔案、信號函式、v1 回測引擎或 v1 研究流程（M3-9 若啟動需另有擁有者核准）。
- 不做 v1→v2 規則翻譯；不擴充 `StrategyDefinition` 的 5 個欄位。
- 不做股票 v1 研究、短波／長波的建成（M3-9，預設不啟動）；不提供「自訂」型態的信號策略（OQ-3）。
- 不新增 AI 工具或提示；AI 不能建立、修改、啟動、暫停任何自動交易策略。
- 不做五檔、類股排行、手機推播、正式下單啟用流程（OQ-14）。
- 不改變本機模擬的既有「推進一個模擬交易日」流程；它不產生晉級證據。

## 5. 資料流

```
┌───────────────────────── v1 研究（既有，不改）────────────────────────┐
│ AI 提案候選 ─► AST 驗證 ─► 回測 ─► walk-forward ─► 一次性 OOS ─► verdict   │
│  (只看 TRAINING 摘要)                         (OOS 結果只存主機端)         │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ 「建成自動交易策略」(UI) 只送 candidate_ref
                                ▼
┌─────────────── v2 引擎行程（M3 新增，見第 7 節）──────────────────────────┐
│ runtime/candidate_catalog ──讀取（唯讀）研究工作區──► CandidateEvidence     │
│        │                                                                   │
│        ▼  application/candidate_intake.build_auto_strategy                 │
│  E1 候選資格閘（verdict=具統計優勢、規格受支援）                           │
│  E2 執行資料回測 ◄── application/signal_research ◄── KlineStore(M1/M2-7/9) │
│        │                                  └─ 信號 = ports.SignalSource ───┐│
│        ▼                                                                  ││
│  凍結規格 + frozen_hash ──► AutoStrategy（階段 BACKTEST）──► 日誌(journal) ││
│        │ 自動：證據一致 ∧ 開盤前檢查通過 ∧ 同意在模擬執行                  ││
│        ▼                                                                  ││
│  階段 BROKER_SIM ◄── M2-3 K 棒完成事件                                    ││
│     application/signal_executor.decide ── ports.SignalSource ◄────────────┘│
│        │  TargetIntent（目標口／張數）  idempotency key = hash+K 棒結束時間│
│        ▼                                                                   │
│  既有 engine.submit（風控、保證金、整張、LIVE 硬關閉）──► 永豐模擬下單      │
│        │                                                                   │
│        ├─► promotion_service（每個完整交易日收盤後）：晉級評估／漂移檢查   │
│        │        └─► 可申請正式 ──► （擁有者按「核准正式」）──► 只記錄       │
│        └─► 暫停（漂移／證據不符／手動）與警示                              │
└────────────────────────────────────────────────────────────────────────────┘
runtime/v1_signal_source：唯一 import quantlab.strategies 的地方（composition 層）
```

## 6. 核心概念與契約

### 6.1 候選、凍結規格與版本

- **候選**（candidate）：v1 的 `StrategySpec`（`family`、`parameters`、`rules`、`schema_version`）加上研究證據。它沒有商品、沒有部位大小。
- **自動交易策略**（`AutoStrategy`，新 domain 型別）：候選 + 執行設定。建成當下凍結下列欄位並計算 `frozen_hash`（sha256，標準化 JSON，鍵排序）：

| 欄位 | 說明 |
|---|---|
| `signal_spec_json` | 候選規格的標準化 JSON（原樣，不改寫）。 |
| `candidate_fingerprint` | v1 `candidate_fingerprint(spec)` 的值，用來對回研究證據。 |
| `holding_kind` | `INTRADAY`／`SWING`／`POSITION`（不含 `CUSTOM`，OQ-3）。 |
| `instrument_rule` | 具體商品 ID，或當沖的 `TMF_NEAR`（微台近月，換月依 M2 D10）。 |
| `bar_interval` | `1m`／`5m`／`1d`，由型態預設（M2 D5）決定，建成時可在型態允許的範圍內選。 |
| `window_mode` | `FULL_HISTORY`（自 `history_anchor` 起整段重算）或 `PER_SESSION`（每個交易日獨立，當沖用）。 |
| `history_anchor` | `FULL_HISTORY` 的起點日期（= 執行資料回測的第一根 K 棒日期）。 |
| `direction_policy` | `BOTH`（TMF 當沖）或 `LONG_ONLY`（股票）。`LONG_ONLY` 把負的目標部位視為 0，回測與執行用同一個函式。 |
| `sizing` | TMF：固定口數（1–5，M2 D9）；股票：每筆金額換算整張（M2 D9）。 |
| `protective_stop_pct` | 型態預設（M2 D5：當沖 1%、短波 3%、長波 8%），可調。 |
| `max_hold_days` | 時間停損，型態預設上限（短波 10、長波 60；當沖 0）。 |
| `cost_version`、`risk_ref` | 沿用既有成本與風險版本識別。 |
| `thresholds_version` | 晉級／漂移門檻的版本（第 10 節），建成當下釘住，之後改預設值不影響已建成的策略。 |
| `protocol_version` | 本規格的執行協定版本，固定 `m3-auto-v1`。 |

- **凍結即不可變**：`AutoStrategy` 是 frozen dataclass，沒有 `replace` 類方法；唯一的變更方式是 `revised(**changes)` 產生 `version + 1` 的**新策略**，
  新版本從 `BACKTEST` 階段重新開始，舊版本保留紀錄（沿用 `StrategyDefinition.revised` 的精神）。**配置金額、口數、停損的變更也是新版本**（擁有者「任何參數變更 = 新版本」）。
- 候選規格的 `parameters.quantity` 必須為 1（執行只用目標部位的**正負號**，大小由 `sizing` 決定）；`stop_ticks`／`target_ticks` 存在則拒絕建成（F5）。
- AI 與規格的關係：AI 只能在 v1 研究流程中提出候選；M3 沒有任何接受 AI 輸入的 `AutoStrategy` 方法。這由 M3-8 的靜態測試保證（第 12 節）。

### 6.2 信號來源 port

```python
# quantlab/trading/ports/signals.py（application 側定義；domain 值型別在 domain/signal_strategy.py）
class SignalSource(Protocol):
    def signals(self, contract_ref: str, bars: tuple[SignalBar, ...], signal_spec_json: str) -> tuple[SignalPoint, ...]: ...
```

- `SignalBar`：`starts_at`、`ends_at`（UTC，K 棒結束 = 資訊可用時間）、`trade_date`、`session`（`day`／`night`）、`open／high／low／close`（`Decimal`）、`volume`（int）。
- `SignalPoint`：`at`（= K 棒結束時間）、`target`（有號整數，與 v1 `Signal.target_position` 相同）、`reason`。
- 唯一的實作是 `runtime/v1_signal_source.V1SignalSource`：把 `SignalBar` 對映成 `quantlab.core.Bar`、把 JSON 還原成 `StrategySpec`，**直接呼叫 `quantlab.strategies.generate_signals`**，再把 `Signal` 對映成 `SignalPoint`。
  它是資料型別對映，不是規則翻譯；`contract_ref` 必須符合 v1 的 `TAIFEX:TMF:YYYYMM`，否則在邊界拒絕（F2）。
- 身分測試（M3-2）：`V1SignalSource` 對映後的結果與直接呼叫 `generate_signals` 逐筆相同，並斷言它呼叫的就是 `quantlab.strategies.generate_signals` 這個函式物件（不是複製品）。

### 6.3 執行協定（信號策略如何下單）

每根「所選週期」的 K 棒**完成**時（M2-3 的 K 棒完成事件；不使用形成中的 K 棒）：

1. 取該策略視窗內的已完成 K 棒：`FULL_HISTORY` 自 `history_anchor` 起；`PER_SESSION` 取當日。K 棒數上限 `EXECUTOR_MAX_BARS`（第 10 節），超過在建成時拒絕。
2. 呼叫 `SignalSource.signals(...)`，取 `at <= 這根 K 棒結束` 的**最後一個**信號的 `target`；沒有信號則為 0。再套 `direction_policy`。
3. `desired = sign(target) × sizing 換算的數量`；與策略自己名下的部位相減得到差額。需要反手時先平倉再建倉，兩筆依序送出（與回測在同一個開盤價反手的差異由執行證據與漂移監控吸收）。
4. 產生 `TargetIntent(strategy_id, version, bar_end, desired_quantity, reason, frozen_hash)`，交給既有 `engine.submit`（風控、保證金、整張檢查、LIVE 硬關閉都在那裡）。
   冪等鍵：`auto:{frozen_hash[:12]}:{bar_end_iso}:{leg}`，同一根 K 棒重啟後不會重複下單。
5. 成交模型與回測一致：訊號後**下一根 K 棒開盤**成交（不偷看未來）。

**前綴一致性（核心正確性性質）**：對任意歷史序列與任一時間點 `i`，用 `bars[:i+1]` 做即時決策得到的目標部位，必須等於用整段 `bars` 一次回測得到的信號序列在 `i` 時的目標部位。
M3-3 用性質測試（五個家族 + AST 規則 + 多組參數 + 固定亂數種子的合成資料）證明；這個測試失敗代表即時與回測不一致，**不得放寬**。

### 6.4 兩層證據

| 層 | 內容 | 來源 | 用途 |
|---|---|---|---|
| **E1 候選資格閘** | v1 verdict 等級必須為 `statistical_edge`（[verdict.py](../../quantlab/verdict.py)）、OOS 已一次性消耗、候選指紋與研究紀錄相符、規格受支援（第 6.1 節）。只保存：campaign 參照、候選指紋、verdict 等級、樣本數、完成時間、資料集家族與週期。**不複製 OOS 的數值序列**。 | `runtime/candidate_catalog` 唯讀讀取研究工作區（用既有 `walk_forward_projection.compact_walk_forward`／`oos_statistics_data` 等讀取 API） | 決定「能不能建成」 |
| **E2 執行資料回測** | 在**實際執行的商品、週期、成本、保護性停損、時間停損、當沖強平**上，用 `SignalSource` 重跑訓練分段（與既有 v2 研究相同的 `available_at < now` 切法，不碰 OOS／最終保留）。輸出：交易明細、淨損益、`max_drawdown_pct`、每交易日平均報酬、勝率、`dataset_id`、`result_hash`、`behavior_hash`、`source_digest`。 | `application/signal_research` | 晉級比較的「回測期望」、漂移的參考回撤、啟動前的重現檢查 |

- `behavior_hash` = sha256(`frozen_hash` + 資料集雜湊 + 交易明細)，不含 `source_digest`。升級程式後 `source_digest` 變了（證據顯示過期），引擎自動重跑 E2：
  `behavior_hash` 相同 → 證據更新為新來源指紋，策略照常；不同 → 該策略暫停（原因 `EVIDENCE_CHANGED`），等擁有者決定。
- E2 的 `max_drawdown_pct` 與 `per_day_return` 以「配置金額」為分母，才能與模擬的 `VersionEquityTrack`（[performance.py](../../quantlab/trading/application/performance.py)）直接比較。
- **E1 對分鐘 K 的限度**：F6 說明 v1 候選的統計驗證來自日 K。當沖（分鐘 K）建成時 UI 顯示警示「統計驗證來自日 K；5 分 K 的表現將在券商模擬階段確認」（第 11 節），
  且券商模擬階段的門檻不放寬。要用分鐘 K 取得統計驗證，需要擁有者核准修改 G3（讓 v1 回測接受券商分鐘 K，OQ-1），不在本規格內。

## 7. 分層變更（精確）

分層依 [layer_map.json](../../tools/layer_map.json)：`domain` ← `application`／`ports` ← `adapters`（infrastructure）← `runtime`（composition）；`desktop_app/features` 為 presentation。
**不需要**修改 `layer_map.json`（所有新檔案都落在既有前綴下）。需要修改 `tools/check_trading_architecture.py` 一處（presentation 允許清單，見下）。

### 7.1 domain（`quantlab/trading/domain/`，只 import 標準庫與 domain）

| 檔案 | 內容 |
|---|---|
| `signal_strategy.py`（新） | `SignalBar`、`SignalPoint`、`TargetIntent`、`DirectionPolicy`、`WindowMode`、`SizingRule`、`AutoStrategy`（凍結規格，含 `frozen_hash` 計算與 `revised`）、`window_bars(...)`、`desired_target(points, as_of)`、`apply_direction(target, policy)`。純函式，無 I/O。 |
| `promotion.py`（新） | `Stage`（`BACKTEST`／`BROKER_SIM`／`LIVE_APPROVED`）、`RunState`（`RUNNING`／`PAUSED`／`RETIRED`）、`PauseReason`、`PromotionThresholds`（具名門檻，第 10 節）、`ExecutionExpectation`（E2 的期望）、`SimObservation`（模擬觀察）、
  `evaluate_promotion(...) -> PromotionVerdict`、`evaluate_drift(...) -> DriftVerdict`、`next_stage(...)`（唯一的階段轉移函式）。純函式。 |

不修改 `domain/strategy.py`、`models.py`、`risk.py`、`policies.py`。

### 7.2 ports（`quantlab/trading/ports/`）

| 檔案 | 內容 |
|---|---|
| `signals.py`（新） | `SignalSource` Protocol（第 6.2 節）。 |
| `candidates.py`（新） | `CandidateCatalog` Protocol：`passed() -> tuple[CandidateSummary, ...]`、`resolve(candidate_ref: str) -> CandidateEvidence`（缺失或不符一律 `DomainError('candidate_unavailable')`）。`CandidateSummary`／`CandidateEvidence` 為 domain 值型別（放 `signal_strategy.py`）。 |

### 7.3 application（`quantlab/trading/application/`，只 import `quantlab.trading.*` 與 `quantlab.errors`）

| 檔案 | 內容 |
|---|---|
| `candidate_intake.py`（新） | `AutoBuildRequest`（`candidate_ref`、`holding_kind`、`instrument_rule`、`bar_interval`、`sizing`、`protective_stop_pct`、`start_in_sim`）；`build_auto_strategy(...)`：邊界驗證（D6 商品限制、型態預設、E1 閘、F5 規格限制、同帳戶同商品僅一個執行中策略）→ 呼叫 `signal_research` 取得 E2 → 凍結 → 寫入日誌。 |
| `signal_executor.py`（新） | `SignalExecutor.decide(auto, bars, now, held_quantity) -> TargetIntent \| None`（第 6.3 節）。無下單、無 I/O，只決策。 |
| `signal_research.py`（新） | `research_auto_strategy(auto, spec, calendar, bars, fees, source) -> ExecutionEvidence`：E2。沿用 `FeeSchedule.transaction`、`InstrumentSpec.shift_ticks`、下一根開盤成交；加上保護性停損、時間停損、當沖強平。 |
| `promotion_service.py`（新） | `PromotionService`：`evaluate_after_close(trade_date)`（冪等，日誌事件 `auto_promotion_evaluated` 以 (策略, 版本, 交易日) 為鍵）、`check_drift(strategy)`（每根 K 棒完成與每次估值後）、`approve_live(strategy, version)`（只記錄）、`pause`／`resume`／`retire`。所有轉移經 `domain.promotion.next_stage`。 |
| `auto_strategy_views.py`（新） | 給 UI 的唯讀 DTO：`AutoStrategyView`、`PromotionProgressView`、`CandidateSummaryView`、`BuildDialogOptions`。 |
| `errors.py`（既有，追加） | 第 8.3 節的錯誤碼（`ErrorText(訊息, 下一步)`）。 |
| `state.py`（既有，追加） | `AppState.auto_strategies: tuple[AutoStrategyRecord, ...] = ()`（預設空，舊日誌可重放）。**M2 也會改此檔 → M3-4 在 M2 合併後才做**。 |
| `contracts.py`（既有，追加） | `UiAction` 新增 `BUILD_AUTO_STRATEGY`、`PAUSE_AUTO_STRATEGY`、`RESUME_AUTO_STRATEGY`、`RETIRE_AUTO_STRATEGY`、`APPROVE_LIVE_INTENT`；`UiCommand.auto_build: AutoBuildRequest \| None = None`；`UiState.auto_strategies`（檢視）。 |
| `registry.py`（既有，追加） | 註冊新 dataclass 到 codec。 |
| `facade.py`、`engine.py`（既有，追加） | `facade.candidates()`、`engine` 轉發新命令；**不新增下單路徑**。 |

### 7.4 adapters（infrastructure）

M3 **不新增 adapters 檔案**：信號來源與候選目錄需要 import `quantlab.*` 根目錄模組，adapters 層不允許（F3），所以放 runtime。券商、K 線、日誌沿用 M1／M2 的既有 adapters。

### 7.5 runtime（composition，可 import 任何層）

| 檔案 | 內容 |
|---|---|
| `v1_signal_source.py`（新） | `V1SignalSource(SignalSource)`；全專案**唯一** import `quantlab.strategies`／`quantlab.core` 的 v2 檔案。 |
| `candidate_catalog.py`（新） | `ResearchWorkspaceCandidateCatalog(CandidateCatalog)`：唯讀讀取研究工作區（不取得單寫入者鎖；若無法無鎖唯讀則 fail closed 回 `candidate_unavailable`，OQ-11）。把 verdict、候選指紋、規格轉成 `CandidateEvidence`；只取第 6.4 節 E1 列出的欄位。 |
| `bootstrap.py`（既有，追加） | 組裝：把 `V1SignalSource`、`ResearchWorkspaceCandidateCatalog`、`PromotionService`、`SignalExecutor` 接到引擎；**M2-3 合併後**接到 K 棒完成事件（M3-6）。 |
| `ipc.py`／`protocol.py`（既有，追加） | 新 `Operation`：`build_auto_strategy`、`auto_strategy_command`、`list_candidates`（唯讀）。 |

### 7.6 presentation（`desktop_app/features/trading/` 與研究結果頁）

| 檔案 | 內容 |
|---|---|
| `build_auto_dialog.py`（新） | 「建成自動交易策略」對話框（第 11.2 節）。 |
| `promotion_panel.py`（新） | 策略列選取後顯示的「晉級進度」面板。 |
| `auto_strategy_rows.py`（新） | 表格列與欄位定義（階段、狀態、模擬進度、與回測差距）。 |
| `window.py`、`workspaces.py`、`dashboard.py`（既有，追加） | 掛上面板、總覽卡片、策略表欄位（**M2-4／M2-6 合併後**）。 |
| 研究結果頁（`desktop_app/features/walk_forward/` 的結果區） | 加「建成自動交易策略」入口按鈕，點擊只發 `candidate_ref`。確切 widget 以實作時的 `grep` 為準，並記入 `m3-decisions.md`。 |
| `desktop_app/shell/theme.py`（既有，追加） | 階段標章與漂移量表樣式（只放 theme.py，無 inline 樣式）。 |
| `tools/check_trading_architecture.py`（既有，追加一行） | presentation 允許清單加入 `application.auto_strategy_views`。 |

## 8. 新檔案、新字串、新名稱（供預先登記，R11）

### 8.1 新檔案

原始碼（15）：

```
quantlab/trading/domain/signal_strategy.py
quantlab/trading/domain/promotion.py
quantlab/trading/ports/signals.py
quantlab/trading/ports/candidates.py
quantlab/trading/application/candidate_intake.py
quantlab/trading/application/signal_executor.py
quantlab/trading/application/signal_research.py
quantlab/trading/application/promotion_service.py
quantlab/trading/application/auto_strategy_views.py
quantlab/trading/runtime/v1_signal_source.py
quantlab/trading/runtime/candidate_catalog.py
desktop_app/features/trading/build_auto_dialog.py
desktop_app/features/trading/promotion_panel.py
desktop_app/features/trading/auto_strategy_rows.py
desktop_app/strings/m3_ui.py
```

測試（11）：

```
tests/test_m3_signal_strategy.py      # 凍結、雜湊、revised、方向政策、視窗
tests/test_m3_promotion.py            # 狀態機、門檻、漂移（純函式）
tests/test_m3_signal_identity.py      # 同一函式身分 + 與直接呼叫逐筆相同
tests/test_m3_prefix_consistency.py   # 前綴一致性性質測試
tests/test_m3_candidate_intake.py     # 建成流程、D6、E1 閘、F5 拒絕
tests/test_m3_signal_research.py      # E2、behavior_hash、停損／強平／成本
tests/test_m3_promotion_service.py    # 冪等評估、暫停、核准、重啟
tests/test_m3_live_hard_off.py        # 逐一呼叫 M3 入口，LIVE 下零送單
tests/test_m3_ai_boundary.py          # OOS／證據不進 AI（靜態 + 動態）
tests/test_m3_ui.py                   # 對話框、面板、表格、空狀態、1366 寬
tests/test_m3_stage_matrix.py         # 型態 × 商品 × 週期的允許矩陣（D6）
```

文件：`docs/design/m3-decisions.md`（自主決策紀錄，M2 同格式）、`docs/design/m3-run-report.md`（每輪完成後）、
`docs/agent/IMPLEMENTATION_CONTRACTS.md` 追加 M3 行為契約（既有檔，只追加）。

**共用基準檔（只有整合分支碰，R1／R4）**：`docs/analysis/08_REFACTOR_INVENTORY.md` 第 2 節（登記上述 15 個原始碼檔）、
`desktop_app/strings/translation_parts.py`（註冊 `m3_ui`）、字串目錄固定檔（`tests/fixtures/desktop_catalog_main_6b78239.json` 等，依 M1-U 先例以 delta 檔 `tests/fixtures/m3_ui_delta.json` 處理，實際清單由 R6 工具列出）、
`tests/fixtures/desktop_widget_names.json`、`tests/fixtures/desktop_ui_public_names.json`（第 8.4 節 objectName）、樣式表雜湊（`theme.py`）、`tools/check_trading_architecture.py` 的允許清單。

### 8.2 新字串（`desktop_app/strings/m3_ui.py`，key 前綴 `m3.`）

群組編號與 order 在整合分支開工時取「目前最大值 +1 起連續編號」，依下表順序（`+1`、`+2`…）。字面 `ui_text('key')`，桌面模組不得寫死中文。

| # | key | 文字 |
|---|---|---|
| +1 | `m3.build_button` | 建成自動交易策略 |
| +2 | `m3.build_button_tip` | 把這個通過驗證的候選，建成可在券商模擬自動執行的策略。 |
| +3 | `m3.build_blocked_not_passed` | 尚未通過驗證，不能建成。 |
| +4 | `m3.build_blocked_wrong_data` | 此候選的研究資料與所選型態不符，需先用對應資料重新研究。 |
| +5 | `m3.dialog_title` | 建成自動交易策略 |
| +6 | `m3.dialog_hint` | 規格建成後即凍結；要修改請建立新版本。 |
| +7 | `m3.field_kind` | 型態 |
| +8 | `m3.kind_intraday` | 當沖 |
| +9 | `m3.kind_swing` | 短波 |
| +10 | `m3.kind_position` | 長波 |
| +11 | `m3.kind_stock_unavailable` | 短波、長波僅限股票；股票研究尚未開放。 |
| +12 | `m3.field_instrument` | 商品 |
| +13 | `m3.field_interval` | 週期 |
| +14 | `m3.field_size_contracts` | 每次口數 |
| +15 | `m3.field_size_amount` | 每筆金額（元） |
| +16 | `m3.field_stop` | 停損（進場價的 %） |
| +17 | `m3.field_start_sim` | 建成後立即在券商模擬自動執行 |
| +18 | `m3.dialog_sim_only` | 只會在券商模擬下單；正式下單未啟用。 |
| +19 | `m3.dialog_fingerprint` | 規格指紋 {0} |
| +20 | `m3.dialog_data_warning` | 統計驗證來自日 K；{0} 的表現將在券商模擬階段確認。 |
| +21 | `m3.dialog_confirm` | 建成 |
| +22 | `m3.dialog_cancel` | 取消 |
| +23 | `m3.built_ok` | 已建成「{0}」，目前在回測階段。 |
| +24 | `m3.built_ok_sim` | 已建成「{0}」，將在券商模擬自動執行。 |
| +25 | `m3.stage_backtest` | 回測 |
| +26 | `m3.stage_sim` | 券商模擬 |
| +27 | `m3.stage_live_approved` | 已核准正式 |
| +28 | `m3.stage_live_approved_note` | 正式下單未啟用，仍在券商模擬執行。 |
| +29 | `m3.state_running` | 執行中 |
| +30 | `m3.state_paused` | 已暫停：{0} |
| +31 | `m3.state_retired` | 已停用 |
| +32 | `m3.state_eligible` | 可申請正式 |
| +33 | `m3.state_waiting_checks` | 等待開盤前檢查通過 |
| +34 | `m3.pause_drift` | 模擬回撤超過回測最大回撤的 {0} 倍 |
| +35 | `m3.pause_evidence` | 程式更新後回測結果不同 |
| +36 | `m3.pause_manual` | 手動暫停 |
| +37 | `m3.pause_orders` | 連續下單失敗 |
| +38 | `m3.col_stage` | 階段 |
| +39 | `m3.col_progress` | 模擬進度 |
| +40 | `m3.col_vs_backtest` | 與回測差距 |
| +41 | `m3.panel_title` | 晉級進度 |
| +42 | `m3.panel_days` | 完整模擬交易日 {0}/{1} |
| +43 | `m3.panel_round_trips` | 完成來回交易 {0}/{1} |
| +44 | `m3.panel_trades` | 成交筆數 {0}/{1} |
| +45 | `m3.panel_return` | 報酬：模擬 {0}／回測同期 {1} |
| +46 | `m3.panel_drawdown` | 回撤：模擬 {0}／暫停線 {1} |
| +47 | `m3.panel_clean` | 沒有未處理的對帳異常與下單拒絕 |
| +48 | `m3.panel_eligible_note` | 已達門檻。核准只會記錄您的決定，正式下單仍未啟用。 |
| +49 | `m3.panel_sim_optimistic` | 永豐模擬成交可能較真實市場樂觀。 |
| +50 | `m3.approve_button` | 核准正式 |
| +51 | `m3.approve_confirm_title` | 確認核准正式 |
| +52 | `m3.approve_confirm_body` | 正式下單目前未啟用。此操作只記錄您對「{0}」的核准，{1} 天內有效。 |
| +53 | `m3.pause_button` | 暫停 |
| +54 | `m3.resume_button` | 恢復 |
| +55 | `m3.retire_button` | 停用 |
| +56 | `m3.retire_confirm` | 停用後不能再啟動；會停止新倉並平掉這個策略的部位。確定停用？ |
| +57 | `m3.goto_research` | 前往研究 |
| +58 | `m3.empty_title` | 還沒有自動交易策略。 |
| +59 | `m3.empty_hint` | 先到研究頁完成回測與驗證，再按「建成自動交易策略」。 |
| +60 | `m3.overview_card` | 自動策略 |
| +61 | `m3.overview_card_value` | {0} 執行中・{1} 已暫停・{2} 可申請正式 |
| +62 | `m3.help_stage` | 回測：規格已凍結，尚未下單。券商模擬：在永豐模擬自動下單並累積成績。核准正式：只記錄您的決定。 |
| +63 | `m3.help_promotion` | 完整交易日指策略全日正常執行（引擎未停止、行情即時、開盤前檢查通過）的日子。 |

### 8.3 新錯誤碼（`application/errors.py` 的 `ERROR_TABLE`，`ErrorText(發生什麼, 下一步)`）

| code | 發生什麼 | 下一步 |
|---|---|---|
| `candidate_not_passed` | 這個候選尚未通過驗證。 | 回研究頁完成回測與樣本外驗證後再建成。 |
| `candidate_unavailable` | 找不到這個候選的研究紀錄。 | 確認研究工作區可用後重試。 |
| `candidate_spec_unsupported` | 候選含有目前不支援的設定（例如固定停損跳數）。 | 回研究頁產生不含該設定的候選。 |
| `candidate_data_mismatch` | 候選的研究資料與所選型態不符。 | 用對應週期的資料重新研究，再建成。 |
| `auto_instrument_not_allowed` | 這個型態不能使用所選商品。 | 當沖只選微台；短波、長波只選股票。 |
| `auto_instrument_busy` | 這個帳戶的這個商品已有執行中的自動策略。 | 先暫停或停用原策略。 |
| `auto_execution_data_insufficient` | 執行資料不足，無法重跑回測。 | 先回補 K 線資料。 |
| `auto_evidence_changed` | 程式更新後回測結果與原本不同。 | 檢視新的回測結果後，決定恢復或停用。 |
| `auto_not_eligible` | 這個策略尚未達到申請正式的門檻。 | 等待模擬累積足夠的交易日與成績。 |
| `auto_frozen` | 已建成的策略不能直接修改。 | 建立新版本。 |

### 8.4 新 objectName

`build_auto_strategy_button`、`build_auto_dialog`、`auto_holding_kind`、`auto_instrument`、`auto_interval`、`auto_size`、`auto_stop_pct`、`auto_start_in_sim`、`auto_confirm_build`、
`auto_strategy_table`、`promotion_panel`、`promotion_days`、`promotion_progress`、`approve_live_button`、`pause_auto_button`、`resume_auto_button`、`retire_auto_button`、`drift_gauge`、`auto_stage_badge`、`overview_auto_card`。

### 8.5 新日誌事件種類（`Journal.append(kind, …)`）

`auto_strategy_built`、`auto_stage_changed`、`auto_promotion_evaluated`、`auto_paused`、`auto_resumed`、`auto_retired`、`auto_live_intent_approved`、`auto_evidence_refreshed`。

## 9. 階段狀態機

兩個階段加一個「核准記錄」。`LIVE_APPROVED` **不是**會下單的階段：它只表示擁有者已核准；在「正式下單閘門」（M2 的單一集中判斷，目前硬性關閉）由擁有者日後另案開啟之前，策略仍在券商模擬執行。

```
                 v1 通過（verdict=具統計優勢）
                           │
       擁有者按「建成自動交易策略」（= 同意在券商模擬自動執行）
                           │  E1 閘 ∧ E2 重跑成功 ∧ 規格凍結
                           ▼
                 ┌──────────────────┐
                 │ BACKTEST  回測    │  不下單；顯示 E2 結果
                 └────────┬─────────┘
                          │ 自動：start_in_sim ∧ 證據一致 ∧ 開盤前檢查通過
                          ▼
   ┌────────────────────────────────────────────────────────┐
   │ BROKER_SIM  券商模擬（只在永豐模擬環境下單）               │
   │   RunState: RUNNING ⇄ PAUSED(原因)                        │
   │   每個完整交易日收盤後：evaluate_promotion                 │
   │     未達標 → 繼續累積        達標 → 旗標「可申請正式」      │
   └───────────────┬───────────────────────┬────────────────┘
                   │ 擁有者按「核准正式」      │ 任何參數變更
                   │（二次確認，只記錄）       ▼
                   ▼                     新版本 → 回到 BACKTEST（舊版本保留）
   ┌────────────────────────────────────────┐
   │ LIVE_APPROVED  已核准正式（未啟用）      │  仍在券商模擬執行；
   │   核准 30 天內有效（LIVE_APPROVAL_DAYS） │  正式下單閘門關閉 → 零送單
   └────────────────────────────────────────┘
        任一階段：停用 → RETIRED（停止新倉、平倉、終態）
```

轉移規則（全部經 `domain.promotion.next_stage`，單一入口、純函式、可窮舉測試）：

| 從 | 到 | 條件 | 觸發者 |
|---|---|---|---|
| （候選） | `BACKTEST` | E1 通過 ∧ E2 完成 ∧ 凍結成功 | 擁有者（建成） |
| `BACKTEST` | `BROKER_SIM` | `start_in_sim` ∧ 重現檢查（`behavior_hash` 相符）∧ M2-5 開盤前檢查通過 ∧ 環境為 `BROKER_SIMULATION` | 自動 |
| `BROKER_SIM`（RUNNING） | `BROKER_SIM`（PAUSED） | 漂移 ∨ `EVIDENCE_CHANGED` ∨ 連續下單失敗 ∨ 手動 | 自動／擁有者 |
| `BROKER_SIM`（PAUSED） | `BROKER_SIM`（RUNNING） | 擁有者按「恢復」∧ 已對帳 ∧ 原因已排除；**晉級觀察期從恢復日重新起算** | 擁有者 |
| `BROKER_SIM` | （旗標「可申請正式」） | `evaluate_promotion` 全部通過 | 自動（每交易日收盤後） |
| `BROKER_SIM` | `LIVE_APPROVED` | 旗標成立 ∧ 擁有者在二次確認框按確定（預設選取消） | **只有擁有者** |
| `LIVE_APPROVED` | `BROKER_SIM`（失效） | 核准逾 `LIVE_APPROVAL_DAYS` ∨ 漂移暫停 ∨ 新版本 | 自動 |
| 任一 | `RETIRED` | 擁有者按「停用」（二次確認） | 擁有者 |

不存在的轉移（以測試窮舉證明不可達）：任何自動路徑進入 `LIVE_APPROVED`；從 `RETIRED` 離開；跳過 `BACKTEST`；在 `LOCAL` 或 `LIVE` 環境進入 `BROKER_SIM`。

## 10. 門檻（具名設定，版本 `m3-thresholds-v1`）

放在 `domain/promotion.py` 的 `PromotionThresholds`（frozen dataclass，預設值如下）。建成當下把 `thresholds_version` 釘進凍結規格；
M3 **不提供**使用者調整門檻的介面（調整 = 修改程式的新版本，走 PR；OQ-8）。UI 的「?」只讀顯示目前套用的數值。

| 名稱 | 預設 | 意義 |
|---|---|---|
| `BUILD_REQUIRED_VERDICT` | `statistical_edge` | E1 閘：v1 verdict 等級（與 `quantlab.verdict.STATISTICAL_EDGE` 字面相同，由測試比對）。 |
| `BUILD_MIN_RESEARCH_TRADES` | 10 | E2 至少 10 筆完成的交易，否則不能建成（長波交易少，所以不設更高）。 |
| `EXECUTOR_MAX_BARS` | 5000 | 視窗 K 棒數上限（每根 K 棒重算整段歷史的成本上限）。 |
| `PROMOTION_MIN_TRADING_DAYS` | 10 | 當沖、短波：至少 10 個**完整**交易日。 |
| `PROMOTION_MIN_TRADES` | 5 | 當沖、短波：觀察期內至少 5 筆完成交易（避免一次都沒交易就達標）。 |
| `PROMOTION_MIN_ROUND_TRIPS_POSITION` | 3 | 長波：改用至少 3 次完整來回交易，**不看天數**。 |
| `PROMOTION_POSITION_REVIEW_DAYS` | 120 | 長波超過 120 個交易日仍不足 3 次來回：只發通知請擁有者檢視，不自動處置。 |
| `PROMOTION_FULL_DAY_REQUIRED` | 真 | 只計「完整日」：全日策略為 RUNNING、引擎未停止、行情即時、開盤前檢查通過。 |
| `PROMOTION_MIN_RETURN_RATIO` | 0.5 | 觀察期模擬淨報酬 ≥ 0.5 × E2 同期期望報酬，且 ≥ 0。 |
| `PROMOTION_MAX_DRAWDOWN_RATIO` | 1.0 | 觀察期模擬最大回撤 ≤ 1.0 × 參考回撤（參考回撤見下）。 |
| `PROMOTION_WIN_RATE_TOLERANCE` | 0.15 | 完成交易 ≥10 筆時，勝率不得比 E2 低超過 15 個百分點。 |
| `PROMOTION_MAX_REJECT_RATE` | 0.05 | 觀察期被拒絕或結果未知的委託 ≤ 5%，且無未處理的對帳異常。 |
| `DRIFT_DRAWDOWN_MULTIPLE` | 1.5 | **漂移線** = 1.5 × 參考回撤；模擬從峰值回撤達到漂移線即自動暫停。 |
| `DRIFT_MIN_REFERENCE_PCT` | 0.02 | 參考回撤的下限（配置金額的 2%），避免回測回撤過小造成雜訊暫停。 |
| `ORDER_FAILURE_PAUSE_COUNT` | 3 | 同一策略連續 3 次下單失敗（拒絕或未知）自動暫停。 |
| `LIVE_APPROVAL_DAYS` | 30 | 核准記錄的有效天數。 |

**參考回撤** = `max(E2.max_drawdown_pct, DRIFT_MIN_REFERENCE_PCT)`（以配置金額為分母）。模擬回撤取自 `VersionEquityTrack`（`peak - equity`）；
`history_complete` 為假（歷史不完整）時不評估晉級，且在 UI 顯示「模擬紀錄不完整」，不得用部分資料宣告達標。

晉級條件的評估次序與結果都寫進 `auto_promotion_evaluated` 事件（每項條件的實測值與門檻），UI 的晉級進度面板與事件內容一致。

## 11. UI 變更（遵守 [介面設計準則](ui-guidelines.md)）

### 11.1 入口：研究結果頁

- 在 walk-forward 結果區（候選通過驗證時）加一個按鈕「建成自動交易策略」，`role=primary`；該區原有的主要動作降為一般。
  未通過驗證時按鈕停用，tooltip 說明原因與下一步（`m3.build_blocked_not_passed`）。
- 按鈕只送出 `candidate_ref`，**不**帶任何證據內容；引擎端自行讀取並驗證（第 7.5 節）。

### 11.2 對話框「建成自動交易策略」

```
建成自動交易策略                                        [?]
規格建成後即凍結；要修改請建立新版本。
────────────────────────────────────────────
型態     (•) 當沖   ( ) 短波（僅限股票；股票研究尚未開放）  ( ) 長波（同上）
商品     [微台 近月 ▼]          週期 [5 分 ▼]
每次口數 [1]   停損（進場價的 %） [1.0]
☑ 建成後立即在券商模擬自動執行
⚠ 統計驗證來自日 K；5 分 K 的表現將在券商模擬階段確認。
只會在券商模擬下單；正式下單未啟用。          規格指紋 a1b2c3d4
                                   [取消]  [建成]（primary）
```

- 短波、長波選項在 M3-9 完成前**停用**並顯示原因（不隱藏，讓使用者知道這是刻意的）。商品清單依 D6 過濾；型態切換時自動帶入 M2 D5 預設值。
- 確認列出將建立的內容與指紋；按「建成」後以 `AsyncStatus` 顯示進行中（重跑 E2 可能超過 0.5 秒），完成顯示 `m3.built_ok` 或 `m3.built_ok_sim`；失敗用 `ERROR_TABLE` 兩段式。
- 無彈出視窗打斷其他流程；對話框本身是使用者主動操作，可接受。

### 11.3 策略頁（M2-4 的清單）

- 預設欄位（≤6）：名稱、型態、商品、**階段**（標章）、今日損益、狀態。其餘（模擬進度 `7/10`、與回測差距、最近訊號）由「欄位」選單勾選。1366×768 無橫向捲軸。
- 階段標章：回測＝中性、券商模擬＝成功色、已核准正式＝成功色 + 附註「正式下單未啟用」（不只靠顏色，文字同時標示）。
- 狀態「已暫停：…」用**警示色**（系統依規則自動處置，屬注意；真正異常如對帳不符才用危險色）。
- 選取一列顯示「晉級進度」面板（`promotion_panel`）：條列每項門檻的實測值／門檻值與勾選狀態、漂移量表（模擬回撤 vs 暫停線）、
  「永豐模擬成交可能較真實市場樂觀」固定註記。按鈕：**核准正式**（僅「可申請正式」時啟用；`role=primary`；二次確認框預設選取消，內文明講正式下單未啟用）、
  暫停／恢復（一般）、停用（`role=danger`，二次確認，預設取消）。
- 信號策略不提供「調參數」：按鈕停用，tooltip 說明「參數由研究產生；請回研究頁產生新候選」，旁邊放「前往研究」按鈕。
- 空狀態：`m3.empty_title` + `m3.empty_hint` + 「前往研究」按鈕。

### 11.4 總覽與績效

- 總覽重點卡片加「自動策略：N 執行中・M 已暫停・K 可申請正式」；暫停原因進頁面頂端單一提示列（不在多處重複）。
- 績效頁（M2-6 已分回測／模擬／正式）：回測欄顯示 E2，模擬欄顯示 `VersionEquityTrack`；漂移量表放在選取策略下方。

### 11.5 文字與無障礙

- 全繁體中文；英文代碼（`INTRADAY`、`BROKER_SIM`、`DRIFT` 等）不得直接顯示；時間台北時間 `MM/DD HH:mm`；單位「口」「張」「元」。
- 每個控制項有無障礙名稱與可鍵盤操作；新樣式只進 `theme.py`；PR 附準則第 10 節檢查清單與 1366×768／1920×1080 截圖。

## 12. 安全限制

1. **LIVE 下單硬性關閉**：M3 不新增任何會呼叫 `place_order`／`update_order`／`cancel_order` 的程式路徑；自動策略的所有下單都經既有 `engine.submit`，
   其 LIVE 判斷維持 M2 的單一集中判斷。`approve_live` 只寫日誌事件，**不呼叫任何閘道方法**。
   `tests/test_m3_live_hard_off.py`：以 fake gateway 在 `Environment.LIVE` 與 `LOCAL` 下逐一呼叫 M3 全部入口（建成、評估、決策、暫停、恢復、核准、停用、K 棒事件），斷言閘道的送單方法被呼叫 0 次；
   另斷言 `LIVE_APPROVED` 狀態下仍然 0 次。
2. **永不自動晉級到正式**：`next_stage` 窮舉測試證明沒有任何自動轉移進入 `LIVE_APPROVED`；`approve_live` 只接受 UI 命令且需 `expected_version`、策略版本與當前 `frozen_hash` 相符。
3. **OOS／最終保留資料不進 AI**（[ADR 0001](../adr/0001-oos-consumption-and-budget.md)、[威脅模型](../AGENT_HARNESS_THREAT_MODEL.md)）：
   - 候選目錄只取 E1 欄位，不複製 OOS 數值序列；證據只存於 v2 日誌與 UI。
   - M3 不新增 AI 工具、提示、`AIContext` 欄位；`ai_context()` 輸出不變。
   - **前向（模擬）成績同樣不進 AI**：它是後續階段的樣本外證據，進了 AI 就被污染。AI 要改進策略只能用 TRAINING 資料產生新候選，走完整 v1 流程；新版本回到 `BACKTEST`。
   - `tests/test_m3_ai_boundary.py`：靜態 AST 掃描 `quantlab/assistant*`、`quantlab/agent_*`、`quantlab/assistant_chat.py`、`desktop_app/features/assistant/` 不得 import `quantlab.trading`；
     動態：用含哨兵值的 `CandidateEvidence`／模擬成績跑一輪，攔截所有 AI 工具回傳與提示組裝，斷言哨兵值不出現。
4. **模擬環境限定**：自動策略只在 `BROKER_SIMULATION` 下單；`LOCAL`（本機模擬）可用來離線回放同一個凍結規格但**不產生晉級證據**；進入 `BROKER_SIM` 階段時檢查環境。
5. **單寫入者與日誌**：所有轉移是日誌事件，重啟後由重放還原；重啟後引擎維持 M2 的「停止新倉，不自動恢復」，自動策略一併顯示「已暫停，等待恢復」（原因：程式重新啟動）。
6. 金額、價格一律 `Decimal`；未知值顯示「未知」；金鑰、CA 不碰；不用 `eval`／`exec`；候選 JSON 只經 `V1SignalSource` 的 v1 AST 驗證路徑，不另開解析路徑。
7. 不碰 G3 鎖定檔、`BROKER_SDK_VERSION`、`PROJECT_STATE.md`；不降低既有 fail-closed、OOS、預算、逾時規則。
8. 同一帳戶同一商品最多一個 RUNNING 的信號策略（避免部位歸屬衝突，OQ-12）。

## 13. 工作項目

估計為 Codex 工時（供 R5 的 1.5 倍上限判斷）。分支前綴 `codex/`。**整合分支** `codex/m3-integration` 是唯一對 main 開 PR 的分支，也是唯一碰共用基準檔的分支（R1、R4）；
M3-1～M3-3 以子分支開發，PR 目標為整合分支。不合併到 main。

### 13.1 相依與併行

```
M2 狀態            →   M3
（不需等 M2）            M3-1 ─┬─► M3-2 ─┐
                                └─► M3-3 ─┤
M2-4/M2-5/M2-6 合併 ───────────────────────┴─► M3-4 ─┬─► M3-5（UI；另需 M2-4、M2-6）
M2-3 合併 ──────────────────────────────────────────────┼─► M3-6（K 棒事件接線、漂移、晉級排程）
M2-7 合併 ──────────────────────────────────────────────┴─► M3-7（分鐘 K 路徑）
                                                          M3-5/6/7 ─► M3-8（安全與整合測試、文件）
M3-9 股票研究範圍：需擁有者核准 G3 變更，預設不啟動
```

| 工作 | 分支 | 擁有的檔案區域（互不重疊，R1） | 相依 | 可併行對象 | 估計 |
|---|---|---|---|---|---|
| M3-1 | `codex/m3-1-domain` | `domain/signal_strategy.py`、`domain/promotion.py`、`ports/signals.py`、`ports/candidates.py`、其測試 | 無（第一天開工） | M2 全部 | 4h |
| M3-2 | `codex/m3-2-v1-bridge` | `runtime/v1_signal_source.py`、`runtime/candidate_catalog.py`、其測試 | M3-1 | M3-3、M2 全部 | 6h |
| M3-3 | `codex/m3-3-application` | `application/candidate_intake.py`、`signal_executor.py`、`signal_research.py`、`promotion_service.py`、`auto_strategy_views.py`、其測試 | M3-1 | M3-2、M2 全部 | 12h |
| M3-4 | `codex/m3-integration`（直接） | `state.py`、`contracts.py`、`registry.py`、`facade.py`、`engine.py`、`errors.py`、`runtime/bootstrap.py`、`ipc.py`、`protocol.py` 的追加 | M3-2、M3-3；M2-4、M2-5、M2-6 已合併 | 無（碰 M2 共用檔，單獨做） | 6h |
| M3-5 | `codex/m3-5-ui` | 3 個新 UI 檔、`m3_ui.py`、研究結果頁入口、`window/workspaces/dashboard` 追加、`theme.py` | M3-4 的第一個 commit（契約 DTO 與 UiAction）；M2-4、M2-6 | M3-6、M3-7 | 10h |
| M3-6 | `codex/m3-6-live-cycle` | `bootstrap.py` 的 K 棒事件接線、`promotion_service` 的排程與漂移接線 | M3-4；M2-3、M2-5 | M3-5、M3-7 | 8h |
| M3-7 | `codex/m3-7-minute-path` | `signal_research.py` 的分鐘模式（`PER_SESSION`、強平）、`candidate_intake` 的分鐘 K 規則 | M3-4；M2-7 | M3-5、M3-6 | 8h |
| M3-8 | 整合分支 | `tests/test_m3_live_hard_off.py`、`test_m3_ai_boundary.py`、`test_m3_stage_matrix.py`、`m3-decisions.md`、`m3-run-report.md`、IMPLEMENTATION_CONTRACTS 追加、全部基準 `test(baseline)` | M3-5～M3-7 | — | 4h |
| M3-9 | `codex/m3-9-stock-research` | 股票研究範圍（見下） | **擁有者核准 G3 變更** | — | 預設不啟動 |

子分支只跑自己相關的測試模組與 `compileall`（R3）；整合分支推送前跑一次完整測試與兩次實際啟動檢查（LOCAL、fake BROKER_SIMULATION，見 M2 規格第 0 節）。
推送後等 CI 時立刻開始下一個沒被擋住的工作（R2）。

### M3-1 領域型別與純函式

- **做什麼**：第 7.1、7.2 節的全部 domain 與 port 型別；`frozen_hash`（標準化 JSON、鍵排序、sha256）；`revised`；`window_bars`；`desired_target`；`apply_direction`；`PromotionThresholds`；`evaluate_promotion`；`evaluate_drift`；`next_stage`。
- **驗收**：
  - [ ] `AutoStrategy` 欄位全部進 `frozen_hash`；任一欄位不同 → 雜湊不同；同內容跨平台雜湊相同。
  - [ ] 沒有修改既有欄位的方法；`revised` 產生 `version+1` 且 `stage=BACKTEST`。
  - [ ] `next_stage` 轉移表與第 9 節一致；不存在的轉移全部拋出 `DomainError`。
  - [ ] `evaluate_promotion` 各門檻邊界值（剛好、差一個單位）結果正確；長波只看來回次數；`history_complete=False` 一律不達標。
  - [ ] `evaluate_drift`：回撤剛好等於 1.5 × 參考回撤即觸發；參考回撤低於 2% 時用 2%。
  - [ ] `python tools/check_layers.py` 與 `tools/check_trading_architecture.py` 通過。
- **測試**：`test_m3_signal_strategy.py`、`test_m3_promotion.py`（含表格驅動的轉移窮舉）。

### M3-2 v1 橋接（runtime）

- **做什麼**：`V1SignalSource`（資料型別對映 + 直接呼叫 `generate_signals`）；`ResearchWorkspaceCandidateCatalog`（唯讀、只取 E1 欄位、驗證候選指紋）。
- **驗收**：
  - [ ] 身分：`V1SignalSource` 呼叫的函式物件 `is quantlab.strategies.generate_signals`。
  - [ ] 對映後的信號與直接呼叫 `generate_signals` 逐筆相同（時間、`target`、`reason`），涵蓋五個家族與帶 AST 規則的規格。
  - [ ] 非 `TAIFEX:TMF:YYYYMM` 的 `contract_ref`、非整數價在邊界以 `DomainError` 拒絕。
  - [ ] 目錄不複製 OOS 數值序列（結構測試：`CandidateEvidence` 欄位集合固定）；研究工作區不存在或被鎖定 → `candidate_unavailable`，不拋未處理例外。
  - [ ] G3 檔案位元組不變（測試比對檔案雜湊與 `git diff --stat` 為空）。
- **測試**：`test_m3_signal_identity.py`、`test_m3_candidate_intake.py` 中的目錄部分（用 fixture 工作區）。

### M3-3 應用服務

- **做什麼**：第 7.3 節的 5 個新檔。`build_auto_strategy`（含 D6 矩陣、E1 閘、F5 拒絕、同商品唯一）；`SignalExecutor`；E2 `research_auto_strategy`；`PromotionService`；檢視 DTO。
- **驗收**：
  - [ ] **前綴一致性**：五個家族 + AST 規則 + 多組參數 + 合成資料，逐一 `i`，即時決策 == 整段回測在 `i` 的目標部位。
  - [ ] 方向政策：`LONG_ONLY` 負目標視為 0，回測與執行同一函式；`BOTH` 保留反手。
  - [ ] E2：下一根開盤成交、成本與滑價用 `FeeSchedule`、保護性停損、時間停損、當沖強平時間；相同輸入 → 相同 `result_hash`／`behavior_hash`。
  - [ ] 建成：E1 未通過、規格含 `stop_ticks`／`target_ticks`、`quantity != 1`、商品不符 D6、執行資料不足、同商品已有執行中策略，各自得到對應錯誤碼且**不寫入任何日誌**。
  - [ ] 晉級評估冪等：同一 (策略, 版本, 交易日) 重複呼叫不重複寫事件、結果相同；重啟重放後結果相同。
  - [ ] 漂移：達線 → 該策略 PAUSED、新倉停止、保護性出場保留；恢復後觀察期重新起算。
  - [ ] 升級模擬：`source_digest` 變、`behavior_hash` 同 → 繼續；不同 → 暫停 `EVIDENCE_CHANGED`。
- **測試**：`test_m3_prefix_consistency.py`、`test_m3_candidate_intake.py`、`test_m3_signal_research.py`、`test_m3_promotion_service.py`、`test_m3_stage_matrix.py`（型態 × 商品 × 週期矩陣）。

### M3-4 狀態、契約與引擎整合

- **做什麼**：`AppState.auto_strategies`（預設空）；`UiAction`／`UiCommand`／`UiState` 追加；codec 註冊；facade／engine 轉發；IPC 新 `Operation`；`bootstrap` 組裝；`errors.py` 追加。**第一個 commit 只放契約 DTO 與 `UiAction`**，讓 M3-5 可立刻開工。
- **前置**：開工時 `git fetch` 並確認 M2-4、M2-5、M2-6 已合併；對 `UiAction`、`UiCommand`、`AppState`、`Operation`／`_dispatch` 跑 GitNexus impact 並記錄（CRITICAL 項目逐一列出已測的相關測試）。
- **驗收**：
  - [ ] 舊日誌（無 `auto_strategies`）重放後狀態相同；新事件種類重放後還原。
  - [ ] 新命令經 IPC 往返；`expected_version` 衝突被拒絕。
  - [ ] 沒有新增任何可呼叫閘道送單方法的程式路徑（M3-8 的測試覆蓋）。
  - [ ] `tools/check_trading_architecture.py` 通過（含新增的一行允許清單）。
- **測試**：既有 codec／ipc／state 測試模組逐一執行 + 新增往返測試。

### M3-5 UI

- **做什麼**：第 11 節。研究結果頁入口、對話框、策略頁欄位與面板、總覽卡片、績效頁漂移量表、字串、樣式。
- **驗收**：
  - [ ] 準則第 10 節檢查清單全勾；1366×768 與 1920×1080 截圖無截斷、無橫向捲軸。
  - [ ] 一頁最多一個 `primary`；停用的按鈕有原因；危險操作確認框預設選取消。
  - [ ] 短波／長波選項停用且有原因；商品清單依 D6；型態切換帶入 M2 D5 預設。
  - [ ] 沒有英文代碼、UTC 時間直接顯示；無 inline 樣式；空狀態有下一步按鈕。
  - [ ] 只送 `candidate_ref`（測試攔截命令內容）。
- **測試**：`test_m3_ui.py`（離屏 Qt，假 facade）、既有 `test_trading_ui.py` 相關部分、字串與 widget 名稱基準（整合分支）。

### M3-6 K 棒事件接線、漂移與晉級排程

- **做什麼**：把 `SignalExecutor` 接到 M2-3 的 K 棒完成分派點（以其實際名稱為準，記入 `m3-decisions.md`）；收盤後對帳完成才呼叫 `evaluate_after_close`；每次估值後 `check_drift`；暫停與可申請正式的警示。
- **驗收**：
  - [ ] 只在 K 棒完成時決策，不用形成中 K 棒；同一根 K 棒重啟後不重複下單（冪等鍵）。
  - [ ] 行情非即時或斷線：不產生新倉意圖，保護性出場保留。
  - [ ] 當日未完整執行（引擎停止、斷線、檢查未過）不計入晉級天數。
  - [ ] 重啟後顯示「已暫停，等待恢復」，不自動恢復。
  - [ ] 模擬時鐘／fixture 推進 10 個完整日 → 旗標「可申請正式」；差一天不亮；長波 3 次來回後亮。
- **測試**：`test_m3_promotion_service.py` 的時間推進案例 + M2-3 既有 fixture 驅動測試。

### M3-7 分鐘 K 路徑（當沖）

- **做什麼**：`PER_SESSION` 視窗；當沖 E2（分鐘 K、強平時間、不跨日）；與 M2-7 的分鐘回測資料來源與證據格式對接；分鐘 K 的建成規則（`bar_interval` ∈ {1m, 5m}、警示字串）。
- **驗收**：
  - [ ] 每個交易日信號狀態獨立重置；當沖部位不跨日。
  - [ ] 資料不足 → 先觸發 M1 回補再跑（沿用 M2-7 的行為），不以不完整資料產生證據。
  - [ ] 前綴一致性在分鐘 K 合成資料上同樣成立。
  - [ ] 既有日 K 研究結果與指紋不變（既有測試）。
- **測試**：`test_m3_signal_research.py` 的分鐘案例、`test_m3_prefix_consistency.py` 的 `PER_SESSION` 案例。

### M3-8 安全、AI 邊界與收尾

- **做什麼**：`test_m3_live_hard_off.py`、`test_m3_ai_boundary.py`、`test_m3_stage_matrix.py` 補齊；`m3-decisions.md`、`m3-run-report.md`；IMPLEMENTATION_CONTRACTS 追加；整合分支的 `test(baseline)` 系列 commit（R4、R6）；完整測試與實際啟動檢查。
- **驗收**：第 14 節全部；CI 全綠。

### M3-9 股票研究範圍（延後，預設不啟動）

- **為什麼延後**：F2——v1 `Bar` 不收股價，短波、長波（只做股票）無法用同一個信號函式；解法需修改 G3 的 `core.py`／`strategies.py`／`backtest.py`（例如讓 `Bar` 接受股票代號與小數價），並重新評估來源指紋與 [ADR 0003](../adr/0003-tmf-research-scope.md)。
- **前置**：(1) 擁有者明確核准修改 G3 並新增研究商品範圍；(2) M2-9 的股票多年日線與除權息還原；(3) 新的 ADR。
- **開工後內容（先寫好以免日後再設計）**：v1 `Bar` 泛化 + 股票資料集；E1 對股票日 K 有效，短波／長波的 E2 與建成才可用；M3-5 的停用選項改為啟用。
- 在擁有者核准前，M3-1～M3-8 完整可用於 TMF 當沖，且所有 port 已預留（`SignalSource.contract_ref` 之外不需改動）。

## 14. 驗收條件總表

- [ ] 沒有任何 G3 檔案被修改（檔案雜湊測試 + diff）。
- [ ] `V1SignalSource` 直接呼叫 `quantlab.strategies.generate_signals`（身分測試）；對映後逐筆相同。
- [ ] 前綴一致性性質測試通過（五個家族 + AST 規則 + 日 K／分鐘 K）。
- [ ] 建成流程：E1 閘、F5 拒絕、D6 商品矩陣、同商品唯一、規格凍結與雜湊、任何參數變更 = 新版本且回到 `BACKTEST`。
- [ ] 階段狀態機與第 9 節一致，不可達轉移窮舉證明；沒有任何自動路徑進入 `LIVE_APPROVED`。
- [ ] 晉級門檻與漂移門檻全部來自 `PromotionThresholds`，邊界值測試通過；長波只看來回次數。
- [ ] 漂移 1.5 倍自動暫停，保護性出場保留；恢復後觀察期重新起算。
- [ ] `LIVE`／`LOCAL` 下所有 M3 入口閘道送單 0 次；`LIVE_APPROVED` 狀態下仍 0 次。
- [ ] AI 邊界：靜態與動態測試通過；M3 沒有新增 AI 工具或提示欄位。
- [ ] 重啟後維持停止新倉並顯示原因；冪等鍵避免同一 K 棒重複下單；升級後 `behavior_hash` 檢查有效。
- [ ] UI 符合準則第 10 節；字串、objectName、樣式基準在整合分支以獨立 `test(baseline)` commit 登記並逐項說明原因。
- [ ] 整合分支：完整測試與 `main` 比對無新增失敗、LOCAL 與 fake BROKER_SIMULATION 實際啟動檢查回傳 0、CI 全綠。

## 15. 測試計畫（總覽）

| 範圍 | 測試 | 重點 |
|---|---|---|
| 純函式 | `test_m3_signal_strategy.py`、`test_m3_promotion.py` | 雜湊穩定、不可變、狀態機窮舉、門檻邊界 |
| 同一函式 | `test_m3_signal_identity.py` | 函式物件身分、逐筆相同、G3 檔案雜湊 |
| 即時 == 回測 | `test_m3_prefix_consistency.py` | 逐 K 棒前綴一致性（性質測試，固定種子） |
| 建成 | `test_m3_candidate_intake.py`、`test_m3_stage_matrix.py` | 錯誤碼、無副作用、D6 矩陣 |
| 執行證據 | `test_m3_signal_research.py` | 成交模型、成本、停損、強平、`behavior_hash` |
| 晉級與漂移 | `test_m3_promotion_service.py` | 冪等、重放、暫停／恢復、重啟 |
| 安全 | `test_m3_live_hard_off.py`、`test_m3_ai_boundary.py` | 零送單、OOS／前向成績不進 AI |
| UI | `test_m3_ui.py` | 對話框、面板、空狀態、1366 寬、命令內容 |
| 既有 | 受影響的 codec／ipc／state／trading_ui／layer／docs 測試 | 不退步 |

所有測試使用 fake SDK 與合成 fixture，**不登入永豐、不讀真實金鑰**。本機只跑相關模組與啟動檢查，完整測試由 CI 與整合分支推送前的一次完整執行負責（R3）。
文件變更另跑 `python -m unittest tests.test_docs_layering`。

## 16. 開放問題與預設（每項皆已選安全預設，**不阻擋任何工作**）

| # | 問題 | 預設（已採用） |
|---|---|---|
| OQ-1 | 日 K 候選的統計驗證能否直接用於分鐘 K 當沖？要讓 v1 回測接受券商分鐘 K 需改 G3。 | **不能直接用**。以 E1（日 K 資格閘）+ E2（分鐘 K 執行回測）+ 券商模擬階段確認，UI 明確警示；G3 變更不在本規格，需擁有者另行核准。 |
| OQ-2 | 短波、長波（股票）何時開放？ | M3-9 預設不啟動；UI 顯示停用與原因。M3-1～M3-8 不依賴它。 |
| OQ-3 | 「自訂」型態是否可建成信號策略？ | 否（第一版只提供當沖／短波／長波）。 |
| OQ-4 | 「券商模擬內自動晉級」的範圍？ | 回測 → 券商模擬：建成時同意後自動進行。模擬 → 正式：系統只**自動評估並亮旗標「可申請正式」**，進入「已核准正式」只能由擁有者按鈕。 |
| OQ-5 | 含 `stop_ticks`／`target_ticks` 的 v1 候選？ | 拒絕建成（`candidate_spec_unsupported`）；v2 用自己的保護性停損於 E2 重跑。 |
| OQ-6 | 做空？ | TMF 當沖 `BOTH`；股票 `LONG_ONLY`（M2 不支援融券）。負目標在股票視為 0，回測與執行同一函式。 |
| OQ-7 | 「回測最大回撤」取哪個？ | E2（執行資料、訓練分段）的 `max_drawdown_pct`，下限 2%；不使用 OOS 數值，OOS 只當資格閘。 |
| OQ-8 | 門檻可否由使用者調整？ | 否。具名、有版本、建成時釘住；調整走程式 PR 與新版本。 |
| OQ-9 | AI 能否看模擬成績？ | 否（前向成績屬樣本外證據）。AI 只能用 TRAINING 產生新候選。 |
| OQ-10 | 「核准正式」的有效期？ | 30 天（`LIVE_APPROVAL_DAYS`）；新版本、漂移暫停立即失效。 |
| OQ-11 | 引擎行程如何讀研究工作區？ | 引擎端用 `CandidateCatalog` 唯讀讀取，UI 只傳 `candidate_ref`；若無法無鎖唯讀則 fail closed（`candidate_unavailable`），不改研究的單寫入者鎖行為。 |
| OQ-12 | 同一候選可建成多個策略？同商品並行？ | 可建成多個（各自版本）；同帳戶同商品最多一個 RUNNING。 |
| OQ-13 | 反手時兩筆委託的時序差？ | 先平後開依序送出；差異由 E2 的成本／滑價假設與漂移監控吸收，不在回測中假設同價反手成交無風險。 |
| OQ-14 | M2 列為「延後到 M3」的五檔、類股排行、手機推播、正式下單啟用流程？ | 不在本文件；建議另列 M4。 |
| OQ-15 | 完整日的定義與長波長期不達標？ | 見第 10 節 `PROMOTION_FULL_DAY_REQUIRED`、`PROMOTION_POSITION_REVIEW_DAYS`（只通知，不自動處置）。 |

## 17. 交付與順序

1. 本文件合併後，M3-1 立即開工（不依賴 M2）；完成後 M3-2、M3-3 同時開工。
2. M3-4 起等 M2 對應工作合併；M3-5、M3-6、M3-7 在 M3-4 的第一個 commit 之後同時進行。
3. 整合分支 `codex/m3-integration`：M3-8 收尾 → 一組 `test(baseline)` commit → 完整測試與啟動檢查 → 一個 PR 到 main，CI 全綠；**不合併**，等待擁有者驗收。
4. 擁有者驗收項目（實作完成後）：(a) 以 TMF 當沖候選實際走一遍建成 → 券商模擬自動執行 → 晉級進度面板；(b) 故意製造漂移確認自動暫停；(c) 確認「核准正式」只記錄、正式下單仍然送不出；(d) 確認短波／長波的停用提示符合預期。

## Rollout/Verification status

Implementation: NOT IMPLEMENTED. Automated verification: NOT RUN.
Real-App visual check: PENDING USER FINAL CONFIRMATION (for UI changes).
本文件只含設計；第 3 節的「發現」來自 2026-11-01 對 `main`（`eb08d82`）的程式閱讀，實作前請以 GitNexus 與文字搜尋再確認（尤其 M2 合併後的 `state.py`、`contracts.py`、`engine.py` 與 K 棒完成分派點的實際名稱）。
[PROJECT_STATE](../agent/PROJECT_STATE.md) 與驗收分數不變；不涉及任何 Release 或 tag。

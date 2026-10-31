# M1 實作規格書：個股與指數看盤終端

Status: SPEC FOR IMPLEMENTATION / NOT IMPLEMENTED. Verification: NOT RUN.
Audience: implementing agent (Codex). Owner decisions dated 2026-10-31.
Design rationale and layout sketch: [m1-stock-index-market-terminal.md](m1-stock-index-market-terminal.md).

本規格把 M1 拆成四個可獨立交付的工作（M1-1、M1-2、M1-3，以及既有畫面瑕疵修正 M1-U），每項一個 PR。
M1-4 只列大綱，另開規格。所有「必須」為驗收條件；「建議」可依程式現況調整，
但須在 PR 說明理由。

---

## 0. 開工前必讀與工作規則

1. 讀 [CONTRIBUTING.md](../CONTRIBUTING.md)、[IMPLEMENTATION_CONTRACTS.md](../agent/IMPLEMENTATION_CONTRACTS.md)、
   [v2 upgrade contract](../implementation/multi-market/UPGRADE_CONTRACT.md)、本規格與設計稿。
2. 專案根目錄的 `AGENTS.md`：編輯任何函式、類別、方法前**必須**先跑 GitNexus impact
   （`node .gitnexus/run.cjs impact "<symbol>" --direction upstream --repo .`），回報呼叫者與風險；
   HIGH／CRITICAL 要在 PR 說明；`UNKNOWN` 不等於安全，需以文字搜尋確認。
   提交前跑 `node .gitnexus/run.cjs detect-changes --scope all --repo .`。
3. 分層規則見 [tools/layer_map.json](../../tools/layer_map.json)：
   `quantlab/trading/domain`（domain）← `application`／`ports`（application）←
   `adapters`（infrastructure）← `runtime`（composition）；`desktop_app/features`、`components`
   為 presentation。domain 不得 import 外層；presentation 不得直接 import adapters 或 SDK。
   `python tools/check_layers.py` 必須通過。
4. 新 UI 文字一律走字串目錄（[desktop_app/strings/catalog.py](../../desktop_app/strings/catalog.py)，
   各功能檔如 [watch.py](../../desktop_app/strings/watch.py)），用字面 `ui_text('key')`；
   桌面模組不得寫死中文字面。新增條目沿用該檔既有 `(群組, 序號, key, 文字)` 格式與編號慣例。
5. v2 交易錯誤文字放 [quantlab/trading/application/errors.py](../../quantlab/trading/application/errors.py)
   的 `ErrorText(訊息, 下一步)`；以 `DomainError(code, detail)` 拋出。
6. 不可修改 G3 鎖定檔（清單見 CONTRIBUTING）；不可削弱、跳過、刪除既有測試；
   改基準 fixture 須獨立 commit 並說明原因。
7. 每階段推送前：`powershell -File tools/prepush.ps1 -Tests`；相關測試模組逐一以
   `python -m unittest tests.<module>` 執行。
8. 每階段 PR：分支 `codex/m1-1-market-history`、`codex/m1-2-terminal-layout`、
   `codex/m1-3-alerts`、`codex/m1-u-ui-defects`；用 PR 範本；把該階段行為契約追加到 IMPLEMENTATION_CONTRACTS；
   **不得**編輯 `docs/agent/PROJECT_STATE.md`；不得把未驗證項目寫成已通過。
9. 任何測試都不得登入永豐。SDK 一律用 fake／錄製 fixture。
10. 程式碼不要過度防禦，規則見 0.1。
11. 以最快方式完成：能不等就不等、能併行就併行，規則見 0.2。
12. 全程自主決策，不提問、不中途停下，規則見 0.3。

### 0.1 程式碼寫作：不要過度防禦（擁有者要求，2026-11-01）

**只在邊界驗證，內部互相信任。** 邊界指：使用者輸入、永豐 SDK 回傳、讀檔／寫檔、
跨執行緒交接。資料一旦在邊界轉成已驗證的 dataclass，內部函式就直接使用，不再重驗。

要做：
- 在邊界驗證一次，轉成型別明確的物件（例如 `WatchInstrument`、`AlertRule`）。
- 錯誤用既有的 `DomainError(code, …)` 往上拋，由呼叫端（UI）統一顯示。
- 用型別註記表達前提，而不是用執行期檢查。

不要做：
- 對內部函式的參數再做 `isinstance`／`type(x) is` 檢查，或重複驗證上游已驗證的值。
- 為「理論上不會發生」的情況加分支、預設值或 fallback。
- 用 `try/except Exception` 包住內部呼叫再吞掉或轉換；只在 SDK 與檔案 I/O 邊界捕捉，
  而且只捕捉會真的發生的例外。
- 同一個條件在 adapter、application、UI 各檢查一次。
- 為單一用途寫通用框架、抽象基底類別、註冊表或設定開關。
- 為了防禦而保留舊路徑的平行實作；被取代的就移除（既有測試另依第 0 節第 6 點處理）。

不在此限：第 1 節的安全邊界（不碰 CA、不下單、金鑰不外洩、「未知」顯示、`Decimal`）
與既有的 fail-closed 檢查**一律保留**，不得以「不過度防禦」為由刪除或削弱。
新程式碼不要比照既有模組的重複驗證風格。

### 0.2 執行節奏：最快完成，能不等就不等，能併行就併行（擁有者要求，2026-11-01）

**相依關係**（只有箭頭處必須等）：

```
M1-1a 行情連線＋商品目錄 ──┐
M1-1b K 線庫（SQLite）  ──┼─► M1-1d 回補 HistorySync ─► M1-2b 主圖接真實資料
M1-1c 週期四選一（UI）     │                              M1-2c 搜尋接商品目錄
M1-2a 版面骨架（fake 資料）─┘
M1-3a 警示 domain 純函式（SMA、KD、12 類判斷）  ← 不依賴任何其他工作，第一天就開始
M1-U  既有畫面瑕疵修正（第 7.5 節）              ← 不依賴任何其他工作，第一天就開始
M1-3b 警示 UI 與規則存檔                       ← 只依賴 M1-2a 的 alerts 區塊
```

**要做：**
- 開工當下就同時開始所有沒有箭頭指向的工作：M1-1a、M1-1b、M1-1c、M1-2a、M1-3a、M1-U。
  可用多個 worktree 或子代理平行寫，各自只動自己的檔案。
- UI 先用 fake 資料把版面做出來，不必等後端完成。
- 介面（port、dataclass 欄位）先在一個小 commit 定下來，雙方依介面平行實作。
- PR 堆疊：M1-1 的 PR 在跑 CI／審查時，就從它的分支開 M1-2 分支繼續寫，不等合併。
  前一個 PR 有修改時再 rebase。
- 長時間的指令（完整測試、`prepush.ps1 -Tests`、截圖）放背景執行，等待時繼續寫下一段。
- 開發中只跑改動相關的測試模組；完整檢查在推送前跑**一次**。
- 互不相關的測試模組可同時執行；但不要同時跑兩套完整測試（會互搶資源、造成時序測試失敗）。
- 遇到第 10 節「需擁有者確認」的項目，先用 fake 完成實作並在 PR 註明，不停下來等。

**不要做：**
- 不要在 CI 或審查進行時閒置；去做下一個沒被擋住的工作。
- 不要用 sleep 或固定間隔輪詢等待；用背景執行、完成通知。
- 不要為了快而跳過驗收條件、測試、GitNexus impact 或第 11 節交付檢查表——
  快是靠重疊工作，不是靠省略步驟。

### 0.3 自主決策：不提問、不停下（擁有者要求，2026-11-01）

擁有者執行期間不在線上。**所有決策由你做，不得提問等待回覆，也不得在工作未完成時結束。**

**遇到問題時怎麼決定**

1. 規格沒寫到或有歧義：選「最安全 → 改動最小 → 最符合專案現有慣例」的做法，直接做下去。
2. 每個自主決定都寫進 `docs/design/m1-decisions.md`（新檔，逐條追加）：
   日期時間、所屬工作（M1-1／2／3／U）、問題、選項、選擇與理由、影響的檔案。
   同時摘要到該 PR 說明的「自主決策」段落。
3. 測試失敗：修正。若同一測試在 `main` 上也失敗（既有問題），記錄在決策檔與 PR，繼續做。
4. 同一個問題換了 3 種修法仍失敗：記錄現況與已試方法，跳過這一小項，先做其他不受影響的工作，
   最後再回頭試一次；仍不行就在 PR 標為未完成項目。不得因此停止整個任務。
5. 需要真實帳號、網路或外部條件才能驗證的項目：用 fake／fixture 完成，PR 標為「待擁有者實測」，繼續做。
6. 推送或開 PR 失敗（例如網路或權限）：在本機分支 commit，記錄在決策檔，繼續下一項工作。

**工作流程不停頓**

- 一個 PR 開出後**不等**審查或合併，立刻依 0.2 節開下一個堆疊分支繼續。
- **不得合併到 `main`**、不得 force-push `main`、只推自己的 `codex/m1-*` 分支；合併由擁有者處理。
- 只有在以下情況才算完成並結束：M1-1、M1-2、M1-3、M1-U 都已開 PR（或至少已在本機 commit），
  每個 PR 的第 11 節檢查表都已逐項處理（做完或註明原因），並寫好最終報告。
- 最終報告寫在 `docs/design/m1-run-report.md`：各工作完成度、PR 連結、未完成項目與原因、
  所有「待擁有者實測」項目、決策檔重點。

**唯一的硬性停止線**（遇到時：不做這件事、記錄原因，然後繼續其他工作，不是停止整個任務）

- 需要用真實金鑰登入永豐、啟用 CA、或任何下單／改單／刪單。
- 刪除使用者資料（工作區、K 線庫、設定檔）或改寫 git 歷史。
- 修改 G3 鎖定檔、`BROKER_SDK_VERSION`、`docs/agent/PROJECT_STATE.md`，或削弱既有測試。

## 1. 永久安全邊界（每階段都要遵守）

- 實盤永久停用。行情路徑**不得**呼叫 `activate_ca`、`place_order`、`update_order`、
  `cancel_order`、`list_accounts`、帳務查詢；不得讀取 CA 引用。
- 行情登入使用 `login(api_key=…, secret_key=…, subscribe_trade=False)`。
- 金鑰只經 `SecretResolver` 由引用名稱（`MarkAuto/v2/broker/<alias>`）解析；不得顯示、
  記錄、寫檔或放入例外訊息。
- 未知值顯示「未知」，不得顯示 0，也不得把舊值當即時值。
- 金額與價格運算維持 `Decimal`；時間在 domain 內為 aware UTC，畫面一律顯示台北時間
  （`Asia/Taipei`），不得顯示 `+00:00`。
- OOS／最終保留資料規則、各種逾時與預算不變。

## 2. 名詞

| 名詞 | 定義 |
|---|---|
| 觀察商品 | 只用於看盤的商品（個股或指數），**不**需要交易用的 `InstrumentMapping`／SHA 資源 |
| 自選 | 使用者手動加入的觀察商品清單，持久化，計入訂閱上限 |
| 暫時訂閱 | 主圖顯示不在自選內的商品時建立的即時訂閱，切換商品即退訂 |
| K 線庫 | 本機 SQLite，存 1 分 K，是所有週期的來源 |
| 商品目錄 | 登入後由永豐合約資料建立的股票與指數清單，供搜尋 |

## 3. 現況（main `ba597b5`，實作前請以 GitNexus 重新確認）

| 項目 | 現況 | 位置 |
|---|---|---|
| tick 回呼 | 已註冊股票與期權 tick | [tick_stream.py](../../quantlab/trading/adapters/shioaji/tick_stream.py) |
| 五檔回呼 | facade 有 `set_on_bidask_*`，無人註冊 | [sdk_facade.py](../../quantlab/trading/adapters/shioaji/sdk_facade.py) |
| facade 缺少 | `usage()`、合約清單列舉、`subscribe_scanner` | 同上 |
| 歷史查詢 | `history()` 單次 ≤ 30 天，需 `bindings[instrument_id]` | [market_data.py](../../quantlab/trading/adapters/shioaji/market_data.py) |
| 回補 | `LiveMarketService.backfill()` 以 30 天為窗 | [live_market.py](../../quantlab/trading/application/live_market.py) |
| 記憶體緩衝 | `buffer_trade_days=30`、`subscription_limit=20` | [freshness.py](../../quantlab/trading/domain/freshness.py) |
| K 棒組合 | 1m → 3m/5m/15m/30m/60m/1d | [live_bars.py](../../quantlab/trading/domain/live_bars.py) |
| 週期查詢 | `MarketSeriesQuery.period` 接受七種 | [contracts.py](../../quantlab/trading/application/contracts.py) |
| 商品類型 | `Market` 只有 STOCK／INDEX_FUTURE／STOCK_FUTURE，**沒有指數** | [models.py](../../quantlab/trading/domain/models.py) |
| 商品綁定 | `InstrumentMapping` 需 spec＋SHA 資源，為交易設計 | [config.py](../../quantlab/trading/runtime/config.py) |
| 連接器設定 | 12 個引用欄位 | [broker_settings.py](../../quantlab/trading/application/broker_settings.py)、[broker_panel.py](../../desktop_app/features/trading/broker_panel.py) |
| 市場頁 | 表格＋小圖＋原始明細 | [market_watch.py](../../desktop_app/features/trading/market_watch.py)、[market_watch_rows.py](../../desktop_app/features/trading/market_watch_rows.py)、[workspaces.py](../../desktop_app/features/trading/workspaces.py) `_market_page` |
| 停靠區塊 | C5 研究版，固定 3 個 panel id | [workspace.py](../../desktop_app/features/market/workspace.py)、[market_layout.py](../../quantlab/research_core/adapters/market_layout.py) |
| K 線圖 | `CandlestickChart.set_series(...)` | [charts.py](../../desktop_app/components/charts.py) |
| SQLite 範例 | 交易帳本 | [ledger.py](../../quantlab/trading/adapters/storage/ledger.py) |

永豐限制（Shioaji 參考 1.7.10；專案鎖 SDK 1.7.9）：歷史自 2020-03-02（指數、股票）；
`kbars` 單次 ≤ 30 日曆天（實作以 **29 天**分段）；行情查詢 50 次／10 秒；每人 5 條連線；
每日流量 500MB–10GB；`kbars` 為 1 分 K、**右標**（`ts` 為該分鐘結束）；
加權指數 `IX0001`、櫃買指數 `IX0043`（1.7.0 起舊代碼 `001` 失效）。
`kbars` 回空時先查流量（`api.usage()`）。

---

## 4. M1-1：行情連線與歷史 K 線庫

### 4.1 行情連線（與交易連接器分離）

**必須**

1. 新增 `MarketDataSettings`（application，凍結 dataclass）：
   `environment: Environment`（`BROKER_SIMULATION` 或 `LIVE`，此處 LIVE 僅表示正式行情來源，
   不開啟任何交易能力）、`secret_ref: str`（格式 `MarkAuto/v2/broker/<alias>`，沿用
   `_secret_reference` 驗證）、`enabled: bool`。持久化位置與既有 v2 設定相同的工作區設定檔，
   新增獨立區段，舊檔缺此區段時視為未設定。
2. 新增 `UiAction.CONNECT_MARKET_DATA`、`UiAction.DISCONNECT_MARKET_DATA`、
   `UiAction.SAVE_MARKET_DATA_SETTINGS`。既有 `CONNECT_READ_ONLY` 與交易連接器行為不變。
3. 新增行情 session 物件（infrastructure，建議 `quantlab/trading/adapters/shioaji/market_session.py`）：
   - `connect()`：建立 `Shioaji(simulation=…)`、以引用解析金鑰、`login(subscribe_trade=False)`、
     下載合約；成功後啟動 `ShioajiTickStream`。
   - `disconnect()`：退訂全部、`logout()`。
   - 不持有帳戶、不建 `InstrumentMapping`、不碰 CA。
   - 登入失敗回傳錯誤碼，不得洩漏金鑰或 SDK 原始例外字串。
4. 連線狀態（`CONNECTED`／`CONNECTING`／`DISCONNECTED`／`UNKNOWN`）沿用現有
   `market_connection` 欄位顯示。
5. 設定頁 UI（[broker_panel.py](../../desktop_app/features/trading/broker_panel.py) 或新面板）：
   最上方新增「行情連線」區塊：環境下拉、API 金鑰引用名稱（預設帶 `MarkAuto/v2/broker/sinopac`）、
   「儲存」、「測試連線」、狀態文字。原 12 欄位改放在預設收合的「交易連接器（進階）」內，
   欄位與檢查邏輯不變。

### 4.2 觀察商品與商品目錄

**必須**

1. domain 新增 `WatchKind(str, Enum)`：`STOCK`、`INDEX`。新增凍結 dataclass
   `WatchInstrument(instrument_id, kind, exchange, code, name)`：
   - `exchange`：`TSE`、`OTC`、`INDEX`。
   - `instrument_id` 規則：個股沿用現有 `TWSE:<code>`（上市）；上櫃與指數的前綴
     **先以 `git grep` 確認現有慣例**，若無則用 `TPEX:<code>`、`INDEX:<code>`（例 `INDEX:IX0001`），
     並通過既有 `identity()` 驗證。
   - 不得把 `WatchInstrument` 放入交易 `Catalog` 或 `bindings`；交易路徑不可接受它。
2. 商品目錄（建議 `quantlab/trading/adapters/shioaji/symbol_directory.py`）：
   登入後以 Contract V2 列舉 `api.contracts.list("STK")` 與 `api.contracts.list("IND")`
   （以 facade 新增的方法取得，不在 adapter 外直接碰 SDK），只收普通股、ETF 與指數（排除權證）。
   **實測：`contracts.get()` 回傳的 `BaseContract` 沒有名稱（`name` 為空）**；
   名稱要從 `api.contracts.info(base).name`（`StockInfo`／`IndexInfo`）取得。
   實作時先量測對全部股票逐一呼叫 `info` 的耗時；若過慢，改為只在建立目錄時批次取得並快取，
   不得在搜尋時即時呼叫。
   寫入工作區 `market/symbol_directory.json`：`{"version":1,"fetched_at":ISO8601,"items":[[id,kind,exchange,code,name],...]}`，
   原子寫入（暫存檔＋`os.replace`）。每個交易日最多更新一次；讀檔失敗時視為空目錄，不中斷。
3. 指數清單固定提供 `IX0001 加權指數`、`IX0043 櫃買指數`，即使目錄尚未下載。
4. 歷史查詢與訂閱改為以 `WatchInstrument` 解析 SDK 合約（`code`＋`exchange`），
   不再要求交易用 `bindings`。交易用路徑保持原樣。

### 4.3 K 線庫（SQLite）

**必須**

1. 新增 infrastructure `KlineStore`（建議 `quantlab/trading/adapters/storage/kline_store.py`），
   檔案位於工作區 `market/klines.sqlite3`，連線方式比照 [ledger.py](../../quantlab/trading/adapters/storage/ledger.py)
   （同版本檢查、timeout、WAL）。
2. 結構：

   ```sql
   CREATE TABLE IF NOT EXISTS bars_1m (
     instrument_id TEXT NOT NULL,
     start_utc     TEXT NOT NULL,   -- ISO8601 UTC, 分鐘起點 = kbars ts - 1 分鐘
     end_utc       TEXT NOT NULL,
     trade_date    TEXT NOT NULL,   -- YYYY-MM-DD
     session       TEXT NOT NULL,
     open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL,  -- Decimal 字串
     volume INTEGER NOT NULL,
     source TEXT NOT NULL,          -- 'SHIOAJI_KBARS' 或 'LIVE_TICKS'
     PRIMARY KEY (instrument_id, start_utc)
   );
   CREATE TABLE IF NOT EXISTS coverage (
     instrument_id TEXT NOT NULL, start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
     PRIMARY KEY (instrument_id, start_utc)
   );
   CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- schema_version=1
   ```

3. 寫入規則：同一分鐘若已有 `SHIOAJI_KBARS`，`LIVE_TICKS` 不得覆蓋；收盤後回補的
   `SHIOAJI_KBARS` 可覆蓋同分鐘的 `LIVE_TICKS`（以官方為準）。`coverage` 記錄已成功查詢的區間
   （含查無資料的休市區間），合併相鄰區間。
4. API：`upsert(bars)`、`missing_ranges(instrument_id, start, end) -> tuple[(start,end),...]`、
   `read(instrument_id, start, end) -> tuple[LiveBar,...]`、`last_bar(instrument_id)`。
   讀取依 `start_utc` 排序。
5. 損毀或版本不符時：保留原檔改名 `klines.sqlite3.bad-<UTC時間>`、建新檔、在狀態列提示；
   不得刪除使用者資料。

### 4.4 歷史回補（定時更新）

**必須**

1. application 新增 `HistorySync`（建議 `quantlab/trading/application/history_sync.py`），
   透過 port 使用 `KlineStore` 與行情 session；不直接 import adapters。
2. 設定（凍結 dataclass，含驗證）：
   `minute_lookback_days=60`（1、5、15 分 K 用）、`daily_lookback_days=365`（日 K 用，
   由 1 分 K 彙整；**擁有者 2026-11-01 確認日 K 先回補 1 年**，更長期留待日後改用官方日資料）、`chunk_days=29`、`earliest=2020-03-02`、
   `quota_reserve_ratio=Decimal('0.10')`。
3. **回補範圍依商品身分決定（擁有者 2026-11-01 決定）**：自選一開始是 **0 檔**，
   不預先回補任何個股；只有加入自選的商品才抓近一年。

   | 商品身分 | 回補範圍 | 何時抓 |
   |---|---|---|
   | 固定指數 `IX0001`、`IX0043` | 1 年 1 分 K | 第一次連線成功後 |
   | 自選股 | 1 年 1 分 K（`daily_lookback_days`） | **按「加入自選」的當下**；之後只補缺口 |
   | 只在主圖瀏覽、未加入自選 | 60 天 1 分 K（`minute_lookback_days`）；切到「日K」時才補到 1 年 | 主圖切換到該商品時 |
   | 已移出自選 | 不再更新；K 線庫已有資料保留 | — |

4. 觸發時機：
   - 行情連線成功後：固定指數與既有自選只補缺口（含斷線、休市後新增的交易日）。
   - 每個交易日股票收盤後（台北 13:35 起）一次，對固定指數與自選補當日完整 1 分 K。
   - 斷線恢復後，只補斷線期間。
   - 使用者在主圖按「更新歷史」。
   - 加入自選、主圖切換商品：依第 3 點的範圍補該商品。
5. 優先順序：主圖商品 → 剛加入自選的商品 → 加權指數 → 其餘自選（依清單順序）。
   同一時間只跑一個回補工作，新請求排入佇列，重複請求合併。
6. 每段查詢前讀取流量；剩餘低於 `limit × quota_reserve_ratio` 時暫停回補，
   狀態列顯示「今日行情流量將滿，已暫停歷史更新」。`usage()` 不可用時照常回補，
   但狀態列流量顯示「未知」。
   **實測（第 10 節）：額度 500 MB／日；`kbars` 幾乎不計入流量**（3,645 根只增加約 7 KB），
   所以流量主要會被盤中即時行情使用。另以本機累計「本日已查詢 K 棒根數」做防失控上限
   （預設每日 3,000,000 根，約 45 檔 × 一年 1 分 K），超過即暫停，次日歸零。
7. 查詢頻率不得超過 40 次／10 秒（低於官方 50 次以留餘裕）。
8. 盤中（09:00–13:30）不得對已有 K 線庫涵蓋的區間重查；盤中只用即時 tick 組 K
   並以 `LIVE_TICKS` 寫入 K 線庫（只寫已完成的分鐘）。
9. 所有回補在背景執行緒，不得阻塞 UI；失敗記錄錯誤碼於該商品 `history_error`，
   並在主圖顯示「重試」。

### 4.5 週期與序列查詢

**必須**

1. 畫面只提供四個週期：`1m`、`5m`、`15m`、`1d`，顯示文字「1分」「5分」「15分」「日K」。
   `MarketSeriesQuery` 仍接受七種週期（相容），不得移除。
2. `market_series` 的資料來源改為「K 線庫 ＋ 記憶體即時 K 棒」合併，
   超過 `buffer_trade_days` 的歷史從 K 線庫讀取；分頁行為不變。
3. 1 分 K 的時間標示：K 線庫存「分鐘起點」，畫面 x 軸以起點顯示；收盤集合競價那根照實顯示。
4. 日 K 依 `trade_date` 彙整；當日未收盤時最後一根標為未完成。
5. 冷門股的 1 分 K 會缺分鐘（實測 6104 四天只有 406 根，熱門股約 266 根／天）。
   缺的分鐘不補假 K 棒、不視為資料缺口，也不觸發重查；coverage 以查詢區間為準。

### 4.6 M1-1 驗收條件

- [ ] 只設定環境與 API 金鑰引用即可連線並取得歷史 K 線；交易連接器 12 欄位留空也可以。
- [ ] 行情路徑全程沒有呼叫 CA、帳戶、下單相關 SDK 方法（以 fake SDK 記錄呼叫驗證）。
- [ ] 回補以 ≤ 29 天分段；不重查已涵蓋區間；休市區間記入 coverage 後不再查。
- [ ] 自選為 0 檔時不回補任何個股；加入自選當下才回補該股 1 年；只瀏覽未加入的商品只回補 60 天（切到日K才補 1 年）。
- [ ] 流量低於保留比例時暫停並顯示提示；恢復後可繼續。
- [ ] 1、5、15 分與日 K 和 fixture 的手算結果一致（含右標轉起點）。
- [ ] K 線庫損毀時保留原檔並重建。
- [ ] 畫面週期只剩四個；舊七種週期查詢 API 仍可用。

### 4.7 M1-1 測試

新增 `tests/test_kline_store.py`、`tests/test_history_sync.py`、`tests/test_market_session.py`、
`tests/test_symbol_directory.py`；延伸 [test_live_bars.py](../../tests/test_live_bars.py)、
[test_trading_sdk_facade.py](../../tests/test_trading_sdk_facade.py)、
[test_shioaji_tick_stream.py](../../tests/test_shioaji_tick_stream.py)。至少涵蓋：
分段邊界（29 天、跨月、含休市）、覆蓋合併、`LIVE_TICKS` 與 `SHIOAJI_KBARS` 的覆寫規則、
流量暫停、斷線補洞、金鑰不出現在任何 log／例外、`check_layers.py` 通過。

---

## 5. M1-2：看盤終端版面

### 5.1 整體結構

**必須**

1. 新增 presentation `MarketTerminalWidget`（建議 `desktop_app/features/trading/market_terminal.py`），
   在 `_market_page` 取代 `MarketWatchWidget` 的位置。`MarketWatchWidget` 若仍被其他地方或測試引用，
   保留其 objectName 與既有測試；需改測試時只能在等價行為下更新，並在 PR 說明。
2. 區塊（panel id 固定）：

   | id | 名稱 | 內容 |
   |---|---|---|
   | `search` | 搜尋列 | 固定在頂部，不可拖曳 |
   | `quotes` | 報價清單 | 分頁「自選」「指數」 |
   | `alerts` | 警示紀錄 | M1-2 先放空狀態文字「警示功能即將推出」，M1-3 實作 |
   | `chart` | 主圖 | 選中商品的 K 線＋成交量 |
   | `index` | 加權指數 | 固定顯示 IX0001 小圖 |
   | `status` | 狀態列 | 固定在底部，不可拖曳 |

3. `quotes`、`alerts`、`chart`、`index` 可拖曳、收合、存具名版面，沿用 C5 的
   `WorkspacePanel`／`LayoutStore` 行為。C5 目前 panel id 固定為三個：
   以參數化方式擴充（例如 `LayoutStore(panel_ids=…, file_name=…)`），**不得**改變 C5 既有預設、
   檔名 `market-layout-v1.json` 與測試結果；終端版面另存 `market-terminal-layout-v1.json`。
4. 預設版面（1366×768 下，比例可微調）：左欄寬 40%（上 `quotes` 60%、下 `alerts` 40%），
   右欄寬 60%（上 `chart` 70%、下 `index` 30%）。預設集：`terminal_default`、`chart_focus`
   （收合 `alerts` 與 `index`，`chart` 佔右欄全部）。「重設」回到 `terminal_default`。
5. 整頁不得出現外層捲軸；主圖隨視窗放大填滿。

### 5.2 搜尋列（`search`）

**必須**

1. 單一輸入框，placeholder「輸入股號或名稱，例如 2330、台積」，左側放大鏡圖示。
2. 輸入停止 150 ms 後搜尋商品目錄與固定指數；最多顯示 20 筆，每筆格式
   「2330　台積電　上市」（指數顯示「指數」、上櫃顯示「上櫃」）。
3. 排序：代碼完全相符 → 代碼開頭相符 → 名稱開頭相符 → 名稱包含；同級依代碼排序。
   全形數字與英文先轉半形；不分大小寫。
4. 操作：↑↓ 選擇、Enter 選定（未選時取第一筆）、Esc 清空並關閉清單、滑鼠點選。
5. 選定後：主圖切換到該商品；**不**自動加入自選；輸入框保留顯示選定商品代碼與名稱。
6. 無結果時清單顯示「找不到符合的商品」。目錄尚未下載且未連線時，只搜尋 K 線庫已有的商品與
   固定指數，清單上方顯示「未連線，結果不完整」。

### 5.3 主圖（`chart`）

**必須**

1. 標題列（左到右）：代碼、名稱、最新價、漲跌、漲幅％、行情狀態點（即時綠、延遲黃、
   停止／休市灰、未知灰）、「☆ 加入自選」／「★ 移出自選」切換鈕、「更新歷史」鈕。
   價格與漲跌依「漲跌配色」設定上色（預設紅漲綠跌）。
2. 週期分段切換：「1分｜5分｜15分｜日K」，選中者有底色；預設 `1分`；
   每個商品記住最後的週期（本次執行期間）。
3. 圖表沿用 `CandlestickChart`，含成交量副圖；滾輪縮放、拖曳平移維持現有行為。
4. 主圖商品來源以最後一次操作為準：搜尋選定、報價清單點選、警示紀錄點選、指數區塊點選。
   啟動時顯示上次查看的商品（存 UI 偏好）；沒有紀錄時顯示 `IX0001`。
5. 暫時訂閱：主圖商品不在自選且不是固定指數時，建立暫時訂閱；切換後退訂。
   訂閱已滿時不訂閱，主圖照常顯示歷史 K 線，標題列狀態顯示「僅歷史（訂閱已滿）」。
6. 「加入自選」：未滿時加入並把暫時訂閱轉為自選訂閱（不重複訂閱）；已滿時顯示
   「自選已滿（上限 N 檔），請先移除其他商品」，按鈕不改狀態。「移出自選」後若主圖仍顯示該商品，
   轉為暫時訂閱。
7. 歷史載入中顯示「載入歷史 K 線…」；失敗顯示錯誤文字與「重試」。

### 5.4 報價清單（`quotes`）

**必須**

1. 分頁「自選」「指數」。欄位固定六欄：代碼、名稱、成交、漲跌、漲幅％、總量。
   代碼不含交易所前綴。
2. 格式：成交依商品跳動單位小數位；漲跌帶正負號；漲幅％兩位小數加「%」；
   總量加千分位（個股單位「張」，指數顯示成交金額「億」或「未知」——以 SDK 實際欄位為準，
   無法取得時顯示「未知」）。未知值灰色「未知」。
3. 成交、漲跌、漲幅％依漲跌上色；平盤用預設文字色。
4. 點欄位標題可排序（再點反向）；預設依自選加入順序。
5. 單擊或 Enter → 主圖切換。右鍵選單：「移出自選」「上移」「下移」（只在自選分頁）。
6. 「指數」分頁固定列出 `IX0001`、`IX0043`；連線時永遠訂閱，計入訂閱數。
   自選可用上限 = `subscription_limit − 2 −（暫時訂閱 0 或 1）`，此計算要顯示在狀態列。
7. 列不得出現橫向捲軸（1366 寬、左欄 40% 時六欄須能完整顯示，名稱可截斷加「…」並有 tooltip）。

### 5.5 加權指數（`index`）

**必須**

標題列：「加權指數」、最新值、漲跌、漲幅％；下方為當日 1 分 K 小圖（無成交量副圖）。
點擊區塊 → 主圖切換到 `IX0001`。

### 5.6 狀態列（`status`）

**必須**

1. 單行：「● 已連線」或「○ 未連線」· 「訂閱 n/上限」· 「今日流量 使用量/額度（xx%）」·
   「最新警示：…」（M1-3 之前隱藏）。
2. 行情狀態彙總：全部即時時顯示「行情即時」；否則只列出非即時的商品，例如
   「2330 延遲、IX0043 停止」，最多 3 檔，其餘「等 N 檔」。**不得**逐檔串接全部狀態
   （取代現行 `header_text` 的做法）。
3. 點擊狀態列開啟「進階診斷」小視窗：主圖商品的買價、賣價、開高低、參考價、交易日、盤別、
   來源（中文：本機模擬／永豐模擬／永豐正式）、接收延遲、最後更新與來源時間（台北時間）。
4. 提示訊息（如訂閱已滿）以狀態列右側短暫顯示 5 秒，不得常駐、不得重複串接。

### 5.7 M1-2 驗收條件

- [ ] 搜尋 `2330`、`台積`、`ix0001` 均能找到並切換主圖，且不改變自選。
- [ ] 主圖 ☆／★ 切換正確；自選滿時有說明且不默默失敗。
- [ ] 暫時訂閱在切換商品後確實退訂（以 fake SDK 計數驗證）。
- [ ] 報價清單六欄完整、無橫向捲軸、顏色與「未知」顯示正確。
- [ ] 狀態列不再出現逐檔「即時・即時…」字串；時間全為台北時間；來源為中文。
- [ ] 版面可拖曳、收合、存取具名版面；C5 研究版行為與測試不變。
- [ ] 1366×768 與 1920×1080 下無外層捲軸，主圖填滿。

### 5.8 M1-2 測試

新增 `tests/test_market_terminal_ui.py`、`tests/test_symbol_search.py`；延伸
[test_market_watch_ui.py](../../tests/test_market_watch_ui.py)、
[test_trading_ui_market_watch.py](../../tests/test_trading_ui_market_watch.py)、
[test_market_workspace_c5.py](../../tests/test_market_workspace_c5.py)。
搜尋排序與半形轉換做純函式測試（放 application 或 presentation 的純 helper，不依賴 Qt）。
UI 需做無障礙巡覽（每個控制項有 accessibleName）與 `tools/ui_snapshot.py` 截圖比對；
真實 App 目視檢查由擁有者最終確認，PR 標為待確認。

---

## 6. M1-3：警示

### 6.1 資料模型（domain）

```text
AlertKind(str, Enum): PRICE_CROSS, CHANGE_PERCENT, FAST_MOVE, DAY_HIGH_LOW, PREV_DAY_BREAK,
                      VOLUME_SURGE, MA_CROSS, KD_CROSS,
                      LIMIT_UP, LIMIT_DOWN, PRICE_JUMP, VOLUME_BURST
AlertRule:  rule_id, kind, scope ('INSTRUMENT' | 'WATCHLIST' | 'MARKET'), instrument_id (scope=INSTRUMENT),
            params (依 kind 驗證的不可變 mapping), enabled, cooldown_seconds (預設 60, 範圍 10–3600)
AlertEvent: event_id, rule_id, kind, instrument_id, occurred_at (UTC), value (Decimal|None), message_key, message_args
```

規則持久化於工作區 `market/alert_rules.json`（`{"version":1,"rules":[...]}`，原子寫入，最多 100 條）。
事件只保留記憶體最近 500 筆，並附加寫入 `market/alert_events.jsonl`（只保留最近 30 天，啟動時清理）。

### 6.2 警示類型（下拉選單依此順序）

| kind | 顯示名稱 | 參數（驗證範圍） | 判斷時機 | 觸發條件 | 適用 |
|---|---|---|---|---|---|
| `PRICE_CROSS` | 價格突破／跌破 | 價位 > 0；方向 上穿／下穿／任一 | 每筆 tick | 前價在一側、新價到另一側（含等於） | 個股、指數 |
| `CHANGE_PERCENT` | 漲跌幅超過 | X% 0.1–10；方向 漲／跌／任一 | 每筆 tick | \|漲幅％\| 首次 ≥ X | 個股、指數 |
| `FAST_MOVE` | 短時間急漲急跌 | N 分 1–30；X% 0.1–10；方向 | 1 分 K 完成時 | 最近 N 根完成 K 的首開到末收變動 ≥ X% | 個股、指數 |
| `DAY_HIGH_LOW` | 創當日新高／新低 | 新高／新低／任一 | 每筆 tick | 開盤 5 分鐘後，價格超過當日先前高點或低點 | 個股、指數 |
| `PREV_DAY_BREAK` | 突破前日高／跌破前日低 | 方向 | 每筆 tick | 價格首次 > 前一交易日高或 < 前一交易日低 | 個股、指數 |
| `VOLUME_SURGE` | 量能放大 | 週期 1/5/15 分；前 N 根 3–60；倍數 1.5–20 | 該週期 K 完成時 | 本根量 ≥ 前 N 根平均量 × 倍數 | 個股 |
| `MA_CROSS` | 均線交叉 | 週期 1/5/15 分／日；短 2–60、長 3–240（短 < 長）；方向 | 該週期 K 完成時 | 短 SMA 由下往上／由上往下穿越長 SMA | 個股、指數 |
| `KD_CROSS` | KD 黃金／死亡交叉 | 週期；N=9、K 平滑 3、D 平滑 3（可調 2–30）；低檔門檻 0–50、高檔門檻 50–100 | 該週期 K 完成時 | 黃金：K 上穿 D 且 K < 低檔門檻；死亡：K 下穿 D 且 K > 高檔門檻 | 個股、指數 |
| `LIMIT_UP` | 漲停相關 | 子類：接近漲停／觸及漲停／漲停打開 | 永豐訊號推送 | 永豐 `LimitScanner` 對應事件 | 上市櫃個股 |
| `LIMIT_DOWN` | 跌停相關 | 子類：接近跌停／觸及跌停／跌停打開 | 永豐訊號推送 | 同上 | 上市櫃個股 |
| `PRICE_JUMP` | 1 秒急漲急跌 | 方向 | 永豐訊號推送 | 永豐 `PriceMoveScanner`（1 秒內 >1% 且 ≥3 跳） | 上市櫃個股 |
| `VOLUME_BURST` | 爆量大單 | 無 | 永豐訊號推送 | 永豐 `VolumeScanner.burst` | 上市櫃個股 |

公式（全部用 `Decimal`）：
- SMA(n) = 最近 n 根完成 K 收盤價平均；不足 n 根不判斷。
- KD：RSV = (C − Ln) / (Hn − Ln) × 100（Hn = Ln 時 RSV = 50）；
  K = (2/3)·K₋₁ + (1/3)·RSV，D = (2/3)·D₋₁ + (1/3)·K（平滑 3 時；一般式為 (s−1)/s 與 1/s）；
  初始 K₋₁ = D₋₁ = 50；不足 N 根不判斷。
- 漲跌幅以參考價（前一交易日收盤）計算；參考價未知時不判斷。

共通規則：
- 只用已完成的 K 棒（`final=True`）判斷 K 棒類警示；絕不使用形成中的 K 棒。
- 邊緣觸發：條件由假轉真才觸發；條件回到假後重新武裝。
- 冷卻：同一規則、同一商品在 `cooldown_seconds` 內不重複觸發。
- 行情狀態非「即時」或該商品在回補中時，不判斷 tick 類警示，避免回補資料誤觸發。
- `scope=WATCHLIST` 時對自選與固定指數逐一判斷；`scope=MARKET` 只允許永豐訊號類。

### 6.3 永豐訊號（kinds 9–12）

1. facade 新增 `subscribe_scanner`、`unsubscribe_scanner`、`set_on_scanner_callback`（以 SDK 實際名稱為準），
   範圍 `Region.TW`、`SecurityType.Stock`、`Exchange.TSE` 與 `Exchange.OTC`。
2. 已實測 SDK 1.7.9 提供 `subscribe_scanner(scanner, *, region, security_type, exchange)`、
   `set_on_scanner_callback`（見第 10 節），直接實作，不需要「不支援」分支；
   不得自行升級 SDK 版本（`BROKER_SDK_VERSION` 屬鎖定設定）。
3. 只有存在至少一條啟用中的 9–12 類規則時才訂閱；全部停用或刪除時退訂。
4. `scope=WATCHLIST` 時在本機過濾非自選事件。

### 6.4 警示 UI（`alerts` 區塊）

1. 上方工具列：「＋ 新增警示」、「管理規則」、「清除紀錄」。
2. 紀錄表欄位：時間（台北，HH:MM:SS）、代碼、名稱、警示、內容（如「突破 600.00」「KD 黃金交叉 K=18.2」）。
   最新在上；上漲類文字紅色、下跌類綠色、中性預設色。點選列 → 主圖切換並捲到觸發時間。
3. 「新增警示」對話框：
   - 「警示類型」下拉（6.2 表格順序與名稱）。
   - 「對象」：目前主圖商品（預設）／全部自選／全市場（只對 9–12 類開放）。
   - 依類型動態顯示參數欄位，帶預設值與範圍驗證，錯誤顯示在欄位旁。
   - 「冷卻秒數」預設 60。
   - 「建立」後立即生效。
4. 「管理規則」：表格列出規則（類型、對象、參數摘要、啟用勾選、刪除）。
5. 觸發時狀態列「最新警示」更新；若設定頁「作業完成／失敗時顯示本機提示」已開啟，
   比照既有通知機制發桌面提示（不得新增網路傳送）。

### 6.5 M1-3 驗收條件

- [ ] 下拉選單恰為 12 類、順序與名稱同 6.2。
- [ ] 每類以 fixture 驗證：條件成立時觸發一次、冷卻內不重複、條件解除後可再觸發。
- [ ] K 棒類只在 K 棒完成後判斷；形成中 K 棒不觸發（以刻意構造的反例驗證）。
- [ ] 回補中或行情非即時時 tick 類不觸發。
- [ ] 規則重開程式後仍在；檔案損毀時以空規則啟動並提示，原檔保留為 `.bad-<時間>`。
- [ ] 9–12 類只在有啟用規則時訂閱永豐訊號，全部停用或刪除後退訂。

### 6.6 M1-3 測試

新增 `tests/test_alert_rules.py`（domain 純函式：SMA、KD、各 kind 判斷、邊緣觸發、冷卻）、
`tests/test_alert_service.py`（application：規則持久化、事件流、scope 過濾）、
`tests/test_alert_ui.py`（對話框欄位動態切換、驗證訊息、紀錄點選切換主圖）。

---

## 7. M1-4（另開規格，此處只列範圍）

- 五檔與成交明細：註冊 `set_on_bidask_stk_v1_callback`，主圖右側可收合面板。
- 類股排行：`IndustryContribution`（`IX0001/TSE`、`IX0043/OTC`）或盤後排行查詢。
- 期指加入觀察商品（`TXFR1`、`MXFR1`；只看盤，不得綁定交易）。

## 7.5 M1-U：既有畫面瑕疵修正（擁有者要求，2026-11-01）

獨立 PR，分支 `codex/m1-u-ui-defects`，第一天即可開始。研究版（`desktop.py` 啟動的 7 頁）與
v2 交易版共用 [theme.py](../../desktop_app/shell/theme.py)。改動前後以
`tools/ui_snapshot.py --size 1366x768` 截圖附在 PR（研究版 7 頁全部）。
v2「市場」頁的混亂由 M1-2 整頁取代，不在此節處理。

| # | 瑕疵（2026-10-31 截圖觀察） | 位置 | 修正後應有的結果 |
|---|---|---|---|
| U1 | 缺字方塊：「進階・資料來源與診斷 □」、圖例「紅／跌 □ 綠」 | [market.py](../../desktop_app/strings/market.py) 的 `▸`／`▾`、[charts.py](../../desktop_app/strings/charts.py)、[appearance.py](../../desktop_app/strings/appearance.py) 的 `−`（U+2212）；`NUMERIC_FONT_FAMILY='monospace'` 見 [theme.py](../../desktop_app/shell/theme.py) | 所有字串改用 Microsoft JhengHei UI 確定有的字元（例：`▸`→ Qt 原生箭頭或 `›`，`−`→ `-`），或讓該元件改用 CJK 字型；全專案字串不再出現會缺字的符號，並加一個測試掃描字串目錄禁止這些字元 |
| U2 | 側欄選中項目內多一層方框 | [setup.py](../../desktop_app/shell/setup.py) `window.navigation`、[theme.py](../../desktop_app/shell/theme.py) `QListWidget::item` | 選中項目只有一層藍底；鍵盤焦點改以樣式表 `:focus` 呈現，不出現內框 |
| U3 | 頂部進度鈕（資料、策略、回測、結果比較、紙上交易）與側欄項目、順序不一致，且全部顯示「待完成」 | [onboarding.py](../../desktop_app/shell/onboarding.py) | 進度與側欄用同一份順序；可點擊切頁；已完成、進行中、待完成三種狀態用不同顏色；目前頁面有標示 |
| U4 | 「說明」勾選框與「說明：開始使用」按鈕重複；「研究模式・實盤停用」做成按鈕樣式；狀態列「就緒」與頂部「作業：待命」重複 | [app_header.py](../../desktop_app/shell/app_header.py)、[onboarding.py](../../desktop_app/shell/onboarding.py) | 說明入口只留一個；研究模式改為不可點的標章樣式；作業狀態只在一處顯示 |
| U5 | 比較頁表格欄位被截斷（「建立時間（台」「最…」），沒資料時一片空白 | [compare_table.py](../../desktop_app/features/compare/compare_table.py) | 1366 寬下欄位標題完整可讀（可縮短標題、加 tooltip 或調整欄寬策略）；空表顯示「尚無保存的回測結果，先到回測頁執行」 |
| U6 | 回測頁停用原因「需要先完成：匯入並／驗證研究資料」被擠成兩行窄欄 | [polish.py](../../desktop_app/shell/polish.py) `prerequisite_required` 的標籤 | 提示與按鈕同列時不換行，或改放按鈕下方整列 |
| U7 | 回測摘要顯示英文代號「策略：trend」 | [backtest.py](../../desktop_app/features/backtest/backtest.py) `redesign.backtest.summary` | 顯示策略的中文名稱（沿用策略頁已有的中文名稱來源） |
| U8 | 紙上交易「本次重播 K 棒數」與「歷史重播長度」兩個標籤對應同一個輸入框 | [paper_layout.py](../../desktop_app/features/paper/paper_layout.py)、[polish.py](../../desktop_app/shell/polish.py) `replay_bars` | 只留一個標籤「本次重播 K 棒數」 |
| U9 | 進階區塊有的用 ▸ 展開、有的用勾選框（紙上交易「進階・手動委託…」「進階診斷 JSON」） | [widgets.py](../../desktop_app/components/widgets.py) `_advanced`、[help.py](../../desktop_app/components/help.py) | 全部進階區塊統一用同一種展開元件與樣式 |
| U10 | 「?」說明鈕位置不一致（左下角、主要按鈕下、群組框內） | [help.py](../../desktop_app/components/help.py) 與各頁 | 統一放在頁面標題右側 |
| U11 | 策略中心四個入口（找策略點子、AI 研究、自行設定、進階驗證）是分頁卻長得像按鈕，第一個還是主要按鈕的藍色 | [strategy_tabs.py](../../desktop_app/features/strategy/strategy_tabs.py) | 改為分頁樣式，選中者有底線或底色，不使用主要按鈕色 |
| U12 | 回測頁有兩個搶眼的主要按鈕（「準備回測資料與策略」整列藍色、「執行回測」） | [backtest.py](../../desktop_app/features/backtest/backtest.py) | 每頁只有一個主要按鈕；未完成前置條件時主要按鈕是「前往…」，完成後才是「執行回測」 |
| U13 | v2 頂部狀態佔 4 行（環境、帳戶、引擎、交易日、持有政策、資金、損益、風險、行情、待處理） | [window.py](../../desktop_app/features/trading/window.py) `v2.context_line`、`v2.summary_line`、`v2.issue_summary` | 縮成一行：「本機模擬 · 交易日 10/23 · 淨損益 0 · 剩餘風險 10,000 · ⚠ 1 項待處理」，其餘點擊後展開；全部頁面頂部高度不超過 48px |

**M1-U 驗收條件**

- [ ] U1–U13 逐項附修正前後截圖。
- [ ] 字串目錄掃描測試：不含已知缺字符號。
- [ ] 既有 objectName、無障礙名稱保留；鍵盤可操作性不退步。
- [ ] 既有 UI 測試全部通過；需更新的截圖基準以獨立 commit 說明原因。
- [ ] 真實 App 目視由擁有者最終確認，PR 標為待確認。

## 8. 新增字串（key 建議，文字為最終顯示）

`watch.*` 延用；新增 `terminal.*`、`alert.*`、`marketdata.*`。下列為必要項，實作時可補充：

| key | 文字 |
|---|---|
| `marketdata.title` | 行情連線 |
| `marketdata.environment` | 行情環境 |
| `marketdata.secret_ref` | API 金鑰引用名稱 |
| `marketdata.save` | 儲存 |
| `marketdata.test` | 測試連線 |
| `marketdata.advanced_broker` | 交易連接器（進階） |
| `terminal.search_placeholder` | 輸入股號或名稱，例如 2330、台積 |
| `terminal.search_none` | 找不到符合的商品 |
| `terminal.search_offline` | 未連線，結果不完整 |
| `terminal.exchange_tse` | 上市 |
| `terminal.exchange_otc` | 上櫃 |
| `terminal.exchange_index` | 指數 |
| `terminal.tab_watchlist` | 自選 |
| `terminal.tab_index` | 指數 |
| `terminal.col_code` / `col_name` / `col_price` / `col_change` / `col_percent` / `col_volume` | 代碼／名稱／成交／漲跌／漲幅％／總量 |
| `terminal.add_watch` | ☆ 加入自選 |
| `terminal.remove_watch` | ★ 移出自選 |
| `terminal.watch_full` | 自選已滿（上限 {0} 檔），請先移除其他商品 |
| `terminal.refresh_history` | 更新歷史 |
| `terminal.history_loading` | 載入歷史 K 線… |
| `terminal.history_only` | 僅歷史（訂閱已滿） |
| `terminal.period_1m` / `period_5m` / `period_15m` / `period_1d` | 1分／5分／15分／日K |
| `terminal.taiex` | 加權指數 |
| `terminal.all_live` | 行情即時 |
| `terminal.quota` | 今日流量 {0}/{1}（{2}%） |
| `terminal.quota_paused` | 今日行情流量將滿，已暫停歷史更新 |
| `terminal.alerts_soon` | 警示功能即將推出 |
| `terminal.source_local` / `source_sim` / `source_live` | 本機模擬／永豐模擬／永豐正式 |
| `alert.add` / `alert.manage` / `alert.clear` | ＋ 新增警示／管理規則／清除紀錄 |
| `alert.kind_*` | 6.2 表格「顯示名稱」欄 |
| `alert.scope_instrument` / `scope_watchlist` / `scope_market` | 目前主圖商品／全部自選／全市場 |
| `alert.cooldown` | 冷卻秒數 |

## 9. 新增錯誤碼（`quantlab/trading/application/errors.py`）

| code | 訊息 | 下一步 |
|---|---|---|
| `market_data_not_configured` | 尚未設定行情連線。 | 到設定頁填入環境與 API 金鑰引用名稱。 |
| `market_data_login_failed` | 行情登入失敗。 | 確認金鑰已用 store_sinopac_key.py 存入，並檢查網路後重試。 |
| `market_data_not_connected` | 行情未連線。 | 先連線，或改看本機已有的歷史 K 線。 |
| `history_quota_low` | 今日行情流量將滿。 | 歷史更新已暫停，明日或額度恢復後再試。 |
| `symbol_not_found` | 找不到這個商品。 | 確認股號；未連線時只能搜尋本機已有資料。 |
| `kline_store_unavailable` | 本機 K 線庫無法使用。 | 原檔已保留，已建立新檔；可重新更新歷史。 |
| `alert_invalid_params` | 警示參數不正確。 | 依欄位提示修正後再建立。 |

既有 `subscription_limit_reached` 的下一步文字目前與訊息串接會重複出現「既有策略訂閱保留」，
M1-2 一併修正顯示方式（只顯示一次）。

## 10. 真實帳號實測結果（2026-11-01，`tools/m1_market_probe.py`，SDK 1.7.9）

查詢區間 2026-10-26～11-01；10-26 為光復節補假，實得 10-27～10-30 四個交易日。

| 問題 | 結果 | 對實作的影響 |
|---|---|---|
| `IX0001`、`IX0043` 能否以 `kbars` 取 1 分 K | **可以**，各 1088 根（272 根／天） | 指數與個股走同一條歷史路徑 |
| `simulation=True` 是否回傳真實歷史 | **是**，與正式環境逐值相同（2330 首末收盤 2390／2370） | 行情環境預設用模擬即可看真實歷史 |
| 每日流量額度 | **500 MB**（`limit_bytes=524288000`） | 見 4.4 第 6 點 |
| `usage()` 是否即時反映查詢 | **否**，同一 session 查詢前後數值相同；約 20 分鐘後再登入才看到變化 | 不能用前後差值估單次用量 |
| `kbars` 計入多少流量 | **幾乎不計**：兩次登入間正式環境查 3,645 根 1 分 K，計數只從 220,572 增為 227,829 bytes（約 7 KB，約 2 bytes／根，含登入） | 歷史回補不受 500 MB 限制；流量主要留給盤中即時行情。見 4.4 第 6 點 |
| 名稱欄位 | `BaseContract` 無名稱 | 見 4.2 第 2 點，改用 `info().name` |
| 冷門股 1 分 K | 會缺分鐘（6104 四天 406 根） | 見 4.5 第 5 點 |
| 連線數 | 模擬與正式各算一條（正式登入時顯示 2） | 同一時間只保留一個行情 session，切換環境前必須先 `logout` |
| `subscribe_scanner` | **SDK 1.7.9 有提供**（含 `LimitScanner`、`PriceMoveScanner`、`VolumeScanner`） | 6.3 第 2 點的停用分支不需要，警示 9–12 類照常實作 |

仍未確認：永豐即時訂閱的實際檔數上限（文件未列、本次未測）。先維持
`subscription_limit=20`，上線後由擁有者觀察再調整。

## 11. 交付檢查表（每個 PR）

- [ ] GitNexus impact 已對每個修改的符號執行，PR 列出 HIGH／CRITICAL 與處理方式。
- [ ] `tools/prepush.ps1 -Tests` 通過；新增與相關測試模組逐一通過；`check_layers.py` 通過。
- [ ] `detect-changes --scope all` 已執行且非 partial／truncated。
- [ ] IMPLEMENTATION_CONTRACTS 已追加本階段契約；設計稿狀態更新為 IMPLEMENTED（驗證欄位據實填寫）。
- [ ] 沒有改動 G3 檔、`PROJECT_STATE.md`、既有測試的斷言強度。
- [ ] 行情路徑無 CA／帳戶／下單呼叫（測試證明）。
- [ ] 截圖（`tools/ui_snapshot.py`）附在 PR；真實 App 目視檢查標為待擁有者確認。

# LM1：唯讀即時看盤與自動交易總覽

Status: PROPOSED / NOT IMPLEMENTED. Verification: NOT RUN.

本提案同時規畫兩個畫面及兩者共用的即時行情層。看盤只看不下單；總覽監控自動交易，只提供停止類操作。

## Problem

使用者下一步要接永豐（Shioaji）API，取得即時行情與歷史 K 線，需要能看盤，也需要在自動交易執行時一眼確認系統狀態。對應設計草案
[multi-market-trading-platform-v1.md](multi-market-trading-platform-v1.md) §4.1「市場」「總覽」兩個工作區。

目前程式的實際狀態（2026-10-28，main `4750156`）：

| 項目 | 現況 | 位置 |
|---|---|---|
| 行情接口 | `MarketDataPort` 只有 `history`、`subscribe`、`unsubscribe`、`latest` | [interfaces.py](../../quantlab/trading/ports/interfaces.py) |
| 歷史 K 線 | 永豐單次查詢區間上限 30 天 | [market_data.py](../../quantlab/trading/adapters/shioaji/market_data.py) |
| 即時訂閱 | 最多 20 檔、`quote_type='tick'`；同一商品被多個訂閱共用時依引用計數退訂 | 同上 |
| tick 回呼 | `sdk_facade` 有 `set_on_tick_stk_v1_callback`／`set_on_tick_fop_v1_callback`，但**沒有任何程式碼註冊回呼**；已訂閱的 tick 不會進入引擎 | [sdk_facade.py](../../quantlab/trading/adapters/shioaji/sdk_facade.py) |
| 最新報價 | `latest()` 以 `snapshots` 主動查詢，產生 `Quote`（bid/ask/last、交易日、盤別） | [market_data.py](../../quantlab/trading/adapters/shioaji/market_data.py) |
| 報價到畫面 | `engine.quote()` 遞增 `quote_count` → `UiState.quote_revision`；視窗每 1 秒輪詢快照 | [engine.py](../../quantlab/trading/application/engine.py)、[window.py](../../desktop_trading/window.py) |
| 畫面資料 | `MarketView` 只有價格、報價時間、可交易狀態、來源；沒有 K 線、成交量、漲跌 | [contracts.py](../../quantlab/trading/application/contracts.py) |
| 市場工作區 | 只有一張商品表格 | [workspaces.py](../../desktop_trading/workspaces.py) `_market_page` |
| 總覽工作區 | 按鈕、兩段狀態文字、待處理清單、最近事件清單 | [workspaces.py](../../desktop_trading/workspaces.py) `_overview_page` |
| K 線圖 | `CandlestickChart`：OHLCV、成交量、`1m`…`1w` 週期；週期切換只發出請求，不自行重組；`set_series` 每次驗證整個序列，上限 100,000 根，沒有增量更新 | [desktop_charts.py](../../desktop_charts.py) |
| 舊研究 UI | C5 市場停靠工作區：商品卡、自選清單、圖表、版面預設 | [c5-market-dock-workspace.md](c5-market-dock-workspace.md) |
| 唯讀連線 | 已有 `UiAction.CONNECT_READ_ONLY` | [contracts.py](../../quantlab/trading/application/contracts.py) |

## Goals/Non-goals

### Goals

- **G1 共用即時行情層**：接收券商 tick，在 Application 端組成 K 棒、維護最新報價統計與行情新鮮度，以唯讀檢視提供給兩個畫面。
- **G2 唯讀看盤**（v2「市場」工作區）：自選清單、歷史加即時 K 線、報價明細、行情狀態。
- **G3 自動交易總覽**（v2「總覽」工作區）：系統狀態燈、今日摘要、策略、部位、待處理異常、停止類操作、最近事件。
- 兩個畫面使用同一套行情新鮮度判斷；任一處顯示行情停滯，另一處同步顯示。
- 未知值一律顯示「未知」，不顯示為 0 或沿用舊值冒充即時值。

### Non-goals

- 不從圖表或看盤畫面下單、改單、撤單。
- 不開啟正式交易；正式交易維持停用（見 Safety constraints）。
- 第一版不把券商 K 線存成研究資料；如要用於回測，另開項目並走既有品質驗證。
- 第一版不做五檔報價與逐筆成交明細；預留為後續選項。
- 不新增技術指標計算；沿用圖表既有能力。
- 不支援多家券商；只對接永豐。

## Design

### A. 資料流

```text
永豐 SDK 回呼執行緒
  → Shioaji adapter：轉成網域 Tick（立即返回，不在回呼內做運算）
  → 有上限的佇列
  → Application：LiveMarketService
       ├ 依商品組 1 分 K（環形緩衝）
       ├ 最新報價統計（最新價、買賣價、開高低、成交量、參考價）
       └ 行情新鮮度狀態
  → 唯讀檢視（MarketWatchView、MarketHealthView）
  → Runtime IPC 快照 → 桌面每秒輪詢（沿用既有 1 秒 poll）
```

- 桌面不接觸原始 tick，也不載入 SDK，符合 [desktop_trading/README.md](../../desktop_trading/README.md) 的分層原則。
- 畫面更新頻率上限為每秒一次，與 tick 頻率無關。
- 另設 `market_revision` 計數器；只有行情變動時，畫面只更新行情相關元件，不重建策略、部位等表格，做法與現有 `quote_revision` 相同。

### B. 新增網域型別：Tick

欄位：`instrument_id`、`price`、`volume`（該筆成交量）、`source_at`（交易所時間）、`received_at`（本機接收時間）、`trade_date`、`session`（`DAY`／`NIGHT`）、`sequence`、`source`。

- 金額使用 `Decimal`；`received_at < source_at`、價格非正數、盤別不明時拒絕。
- 交易日與盤別由既有 `session_resolver` 決定；缺少日曆時拒絕，不推測。
- `MarketDataPort` 新增 tick 串流能力（例如 `drain_ticks(max_items)`）。模擬連接器 [simulated/broker.py](../../quantlab/trading/adapters/simulated/broker.py) 同步實作，供離線測試。

### C. K 棒組成規則

- 以 `source_at` 分桶，不用本機接收時間，避免網路延遲把成交放錯分鐘。
- 1 分 K 是唯一由 tick 直接組成的週期。3、5、15、30、60 分 K 與日 K 由 1 分 K 重組。重組在 Application 端完成，圖表只顯示（符合 `CandlestickChart` 的契約）。
- 夜盤歸屬下一交易日，依 `session_resolver` 的結果，不自行判斷。
- 正在形成的 K 棒標示為「形成中」；收盤後才定案。
- 每商品保留最近 30 個交易日的 1 分 K（TMF 約 1,140 根／日，約 34,000 根），低於圖表 100,000 根上限。

### D. 歷史與即時銜接

1. 開啟某商品圖表時，在背景以 `history()` 抓歷史 K 線，每次查詢 ≤30 天。
2. 已訂閱的 tick 持續組成即時 K 棒。
3. 合併時，以第一根即時 K 棒的起始時間為界，丟棄起始時間不早於它的歷史 K 棒，避免重複。
4. 歷史資料結束時間和即時資料開始時間之間若有空隙，標示「資料缺口」，不插值、不補平。
5. 歷史查詢失敗時，即時部分照常顯示，並在圖表上方顯示錯誤與重試按鈕。

### E. 行情新鮮度

每個商品依「最後接收時間」與交易日曆判斷：

| 狀態 | 條件（預設值，可在設定調整） | 顯示 |
|---|---|---|
| 即時 | 交易時段內，10 秒內有新資料 | 正常 |
| 延遲 | 交易時段內，超過 10 秒沒有新資料 | 黃色＋最後更新時間 |
| 停止 | 超過 60 秒沒有新資料，或連線中斷 | 紅色；價格以灰色顯示並附時間 |
| 休市 | 依日曆不在交易時段 | 中性色；顯示最後收盤價與時間 |
| 未知 | 沒有日曆或尚未收到任何資料 | 「未知」 |

- 冷門商品可能本來就很久才成交一筆，所以「延遲」不等於斷線；只有「停止」計入總覽的異常。
- 判斷所用的時鐘走既有 `Clock` 接口，測試可注入假時鐘。

### F. 訂閱名額

- 永豐上限 20 檔。策略需要的商品優先，看盤自選清單使用剩餘名額。
- 加入自選會超過上限時，拒絕並說明原因；不擠掉策略的訂閱。
- 自選清單保存在設定檔；重新連線後自動恢復訂閱。

### G. 看盤畫面（v2「市場」工作區）

```text
頂部  連線狀態  行情狀態  名額 8/20                     [加入自選]
左    自選清單：商品｜最新價｜漲跌｜漲跌%｜成交量｜時間｜狀態
中    K 線圖（CandlestickChart，週期按鈕 1m 3m 5m 15m 30m 60m 1d）
右    報價明細：買價／賣價、開／高／低、參考價、總量、交易日、盤別、來源、接收延遲
底部  原「商品表格」收合保留，並保留舊研究入口
```

- 支援商品：微型臺指期（TMF）、臺股期貨（TX）與現股（使用者 2026-10-28 確認）。三者共用同一套自選、圖表與報價元件；商品差異（合約乘數、跳動點、交易時段、有無夜盤）只來自 `InstrumentSpec` 與交易日曆，畫面不寫商品類型分支。
- 漲跌的參考價：期貨與現股一律用前一交易日收盤價（使用者 2026-10-28 確認），由 Application 計算後提供；沒有參考價時顯示「未知」。期貨有夜盤時，「前一交易日」依交易日曆決定，不以日曆日判斷。
- 圖表需要增量更新：新增「替換最後一根／附加一根」的方法，避免每秒重新驗證數萬根 K 棒。實作前先量測整段 `set_series` 在 34,000 根時的耗時，若每次低於 50 ms，可先以每秒整段更新上線，再改增量。
- 版面沿用 C5 的停靠概念（自選、圖表、明細三個面板），但資料來源改為 v2 的唯讀檢視；不改動舊研究 UI。
- 第二階段可在圖上顯示策略的委託與成交標記（唯讀，使用既有 `ChartMarker`）。

### H. 總覽 dashboard（v2「總覽」工作區）

```text
狀態燈  券商連線 ● 行情 ● 引擎 ● 對帳 ●     模式：本機模擬／券商模擬
今日    淨損益｜未實現損益｜剩餘風險｜當日虧損上限剩餘｜成交筆數
策略    名稱｜版本｜狀態（運行／暫停／風控停止）｜今日委託｜今日損益
部位    商品｜策略｜方向數量｜持有天數｜預計出場日｜未實現損益｜報價時間
異常    待處理異常清單（沿用 issue_details，置頂且最醒目）
操作    [停止新倉] [撤銷進場單] [對帳]      （只放停止類，不放下單）
事件    最近事件（沿用 events，可展開）
```

- 大部分資料已在 `UiState`：`environment`、`engine_state`、`daily_pnl`、`remaining_risk`、`strategies`、`positions`、`issues`、`events`、`reconciliation_verified`。
- 需要新增：
  - 連線與行情摘要（`MarketHealthView`）。
  - 每個策略的今日委託數與今日損益。
  - 部位未實現損益：由 Application 以 `Decimal` 計算（最新價 × 數量 × 合約乘數，扣除成本）；報價不是「即時」時顯示「未知」或附上報價時間，不用舊價冒充。
- 狀態燈規則：任何一項是紅色時，總覽頂部顯示一行摘要文字，不只靠顏色（符合設計草案 §4.3 不依賴顏色的要求）。
- 操作沿用既有 `UiAction.STOP_NEW`、`CANCEL_ENTRIES`、`RECONCILE`，不新增命令。

### I. 分層架構與可維護性

本項目的程式必須符合設計草案 [§5 分層架構](multi-market-trading-platform-v1.md) 與既有層次檢查 [tools/check_trading_architecture.py](../../tools/check_trading_architecture.py)（由 [tests/test_trading_architecture.py](../../tests/test_trading_architecture.py) 執行）。不得放寬該檢查；新增模組必須被它涵蓋。

#### I.1 各層責任

依賴方向只能由上往下；Domain 不依賴任何其他層。

| 層 | 本項目放什麼 | 不能做什麼 |
|---|---|---|
| Domain（`quantlab/trading/domain/`） | `Tick`、即時 K 棒型別；**純函式**：tick 併入 1 分 K、多週期重組、歷史與即時合併、新鮮度判斷、參考價選擇、未實現損益計算 | 不 import Qt、SDK、檔案、資料庫、執行緒；不讀系統時間（時間一律由參數傳入） |
| Ports（`quantlab/trading/ports/`） | `MarketDataPort` 的 tick 串流方法與其 DTO | 不暴露 SDK 物件或欄位名稱 |
| Adapters（`quantlab/trading/adapters/`） | 永豐：註冊回呼、SDK 資料 → `Tick`、有上限佇列、例外轉換；模擬：可重現的 tick 來源 | 不做 K 棒組成或新鮮度判斷（那是 Domain 的事） |
| Application（`quantlab/trading/application/`） | 即時行情服務：持有各商品緩衝、分配訂閱名額、協調歷史補抓；把 Domain 結果組成唯讀檢視 | 不含 SDK 欄位細節；不直接開執行緒或連網 |
| Runtime（`quantlab/trading/runtime/`） | 組裝：建立服務、注入連接器、啟動抽取 tick 的背景迴圈；IPC 新增欄位 | 不藏任何行情或交易規則 |
| Presentation（`desktop_trading/`） | 看盤與總覽的 widget；把檢視轉成表格列與文字的**純函式**（沿用 [rendering.py](../../desktop_trading/rendering.py) 的做法） | 只能用 `application.contracts` 的公開型別；不計算損益、新鮮度或 K 棒 |

`desktop_charts.py` 是新舊 UI 共用的根層模組，只新增「替換最後一根／附加一根」這類顯示方法，不加入資料取得或計算。

#### I.2 可維護性規則

1. **單一權威實作**：K 棒組成、週期重組、新鮮度、參考價、未實現損益各只有一份實作，看盤、總覽、日後的自動交易引擎共用。不得在畫面或 adapter 另寫一份。
2. **小而專一的模組**：新增程式放在新檔案，不擴大既有大檔：`engine.py`（約 500 行）、`window.py`（約 600 行）、`desktop_market.py`（約 1,300 行）只加接線，不加邏輯。單一新模組以 400 行為上限，超過就依責任拆分。
3. **核心邏輯是純函式**：Domain 函式只接收參數並回傳新值，不改動輸入、不讀時鐘、不做 I/O，可直接單元測試。
4. **型別明確**：資料型別使用 `@dataclass(frozen=True)` 與完整型別標註；金額與價格使用 `Decimal`；不用裸 `dict` 在層與層之間傳資料。
5. **設定集中**：新鮮度門檻、緩衝長度、佇列上限、訂閱上限等數值放在一個有型別的設定物件，有預設值與驗證，不寫成散落各處的常數。
6. **商品差異靠資料**：TMF、TX、現股的差異來自 `InstrumentSpec` 與交易日曆，不寫 `if 商品 == ...` 分支（設計草案 §5.2）。
7. **連接器契約測試**：同一組測試同時跑模擬與永豐（以假 SDK）連接器，確保兩者行為一致；換券商時只需新 adapter 通過同一組測試。
8. **IPC 只做加法**：快照新增欄位附預設值，舊欄位不改名、不改意義，維持新舊程序相容。
9. **先寫特徵測試再改舊碼**：修改 `engine.py`、`window.py`、`desktop_charts.py`、`workspaces.py` 前，先補上鎖住現有行為的測試。
10. **文字與錯誤**：畫面文字使用字面 `ui_text` 鍵；錯誤使用既有錯誤表與 `DomainError` 代碼，不拼接自由文字。
11. **每個模組開頭一段說明**：寫清楚這個模組負責什麼、不負責什麼，沿用 repo 現有風格。

#### I.3 預計新增的模組（尚不存在）

```text
quantlab/trading/domain/
  ticks.py            Tick 型別與驗證
  live_bars.py        tick → 1 分 K、多週期重組、歷史與即時合併
  freshness.py        新鮮度狀態判斷與門檻設定
  quote_stats.py      參考價、漲跌、未實現損益
quantlab/trading/adapters/shioaji/
  tick_stream.py      回呼註冊、SDK → Tick、有上限佇列
quantlab/trading/adapters/simulated/
  tick_feed.py        可重現的模擬 tick
quantlab/trading/application/
  live_market.py      即時行情服務（緩衝、名額、補抓協調）
  market_views.py     組成 MarketWatchView、MarketHealthView、總覽檢視
desktop_trading/
  market_watch.py     看盤 widget（自選、圖表、明細）
  market_watch_rows.py 看盤檢視 → 表格列與文字（純函式）
  dashboard.py        總覽 widget
  dashboard_rows.py   總覽檢視 → 表格列與文字（純函式）
tests/
  test_live_bars.py、test_freshness.py、test_quote_stats.py、
  test_tick_adapters_contract.py、test_live_market_service.py、
  test_market_watch_ui.py、test_dashboard_ui.py
```

實作時可依既有命名微調檔名，但責任邊界必須保留。

### J. 失敗處理

| 情況 | 行為 |
|---|---|
| 券商斷線 | 保留最後已知資料並標示「停止」；總覽狀態燈轉紅；不清空表格 |
| 重新連線 | 恢復訂閱；以 `history()` 補抓斷線期間的 K 棒；補不到的區間標示資料缺口 |
| SDK 回呼丟出例外 | 在 adapter 內攔截並記錄，不影響 SDK 執行緒與引擎 |
| 佇列滿 | 不默默丟資料；該分鐘的 K 棒標示「資料不完整」，並記一筆異常 |
| 本機時鐘與交易所時間差距過大 | 顯示警告；分桶仍以交易所時間為準 |
| 歷史查詢失敗 | 即時部分照常；顯示錯誤與重試 |

### K. 預計修改的檔案

既有檔案：

- [quantlab/trading/ports/interfaces.py](../../quantlab/trading/ports/interfaces.py)：`MarketDataPort` 增加 tick 串流。
- [quantlab/trading/domain/models.py](../../quantlab/trading/domain/models.py)：新增 `Tick`。
- [quantlab/trading/adapters/shioaji/market_data.py](../../quantlab/trading/adapters/shioaji/market_data.py)、[sdk_facade.py](../../quantlab/trading/adapters/shioaji/sdk_facade.py)：註冊 tick 回呼、轉換、佇列。
- [quantlab/trading/adapters/simulated/broker.py](../../quantlab/trading/adapters/simulated/broker.py)：模擬 tick 來源。
- [quantlab/trading/application/engine.py](../../quantlab/trading/application/engine.py)、[contracts.py](../../quantlab/trading/application/contracts.py)、[views.py](../../quantlab/trading/application/views.py)：接上即時行情服務與新檢視。
- [quantlab/trading/runtime/protocol.py](../../quantlab/trading/runtime/protocol.py)、[ipc.py](../../quantlab/trading/runtime/ipc.py)：快照新增欄位。
- [desktop_trading/workspaces.py](../../desktop_trading/workspaces.py)、[window.py](../../desktop_trading/window.py)：兩個工作區的版面與 `market_revision` 局部更新。
- [desktop_charts.py](../../desktop_charts.py)：增量更新方法。
- [desktop_strings.py](../../desktop_strings.py)：所有新文字使用字面 `ui_text` 鍵。

預計新增（尚不存在）：見 I.3。
另外擴充 [tools/check_trading_architecture.py](../../tools/check_trading_architecture.py) 的測試案例，確認新模組受層次檢查涵蓋；不放寬任何既有規則。

## Safety constraints (live trading disabled, G3, OOS/budget)

Live trading stays permanently disabled; add no real order path. 本提案的兩個畫面都不提供下單入口；總覽只沿用既有的停止類命令。

> 注意：使用者的長期目標是自動交易。要讓引擎真的對券商送單，必須另外修改這條專案契約，並取得擁有者的明確核准；不在本提案範圍內。

Keep all eight G3 files and protected saved-candidate profile blocks untouched; if a future change needs them, obtain owner approval before editing. The exact protected paths are in the [contributor guide](../CONTRIBUTING.md).
Preserve fail-closed validation, OOS one-time consumption, irreversible budgets and every timeout (Paper 30 s, smoke 40 s, 15 min per job).
OOS and final-holdout data must never enter AI conversations, tool returns or prompts. AI output remains untrusted input subject to existing AST validation.
No eval/exec/new Function or other dynamic execution; no ChatGPT credential reading, storage or display. Money arithmetic remains Decimal.

其他：券商憑證只透過既有 OS 金鑰引用存取，畫面不顯示帳號或憑證；期交所與券商行情不轉發給第三方。

## Test plan

離線、可重現，使用模擬 tick 來源與假時鐘：

- K 棒組成：分鐘邊界、夜盤歸屬下一交易日、成交量加總、亂序 tick、重複 `sequence`。
- 多週期重組：由 1 分 K 重組 5 分 K、日 K，與直接計算的結果一致。
- 歷史銜接：重疊時去除重複；有空隙時標示缺口；歷史查詢失敗時即時部分仍正常。
- 行情新鮮度：即時 → 延遲 → 停止 → 休市的轉換；斷線與重連。
- 訂閱名額：策略優先；超過 20 檔時拒絕並提示原因。
- 未實現損益：`Decimal` 計算；報價不是即時時顯示未知。
- UI（離屏 Qt）：延伸 [tests/test_trading_ui.py](../../tests/test_trading_ui.py)；`market_revision` 只更新行情元件，保留表格選取；新元件有 objectName 與無障礙名稱；鍵盤可操作；大字型與縮小視窗版面正常。
- 效能：20 檔 × 每秒 10 筆，連續 10 分鐘；每次畫面更新耗時與記憶體上限要先定義成需求，再量測。
- 依 [CONTRIBUTING.md](../CONTRIBUTING.md) 執行 lint、編譯、quality gate 與逐一模組測試。

以下不能用離線測試取代，要分開列在驗收紀錄：永豐真實帳號（先用券商模擬環境）的訂閱與回呼、實體 Windows 畫面與 150%／200% 縮放、使用者實際看盤確認。

## Rollout/Verification status

建議順序；每一階段各自一個 PR，可以獨立回退：

1. **P1 共用行情層**：Domain 純函式、`Tick`、模擬 tick 來源、即時行情服務、檢視與 IPC 欄位。不改畫面。
2. **P2 看盤畫面**：自選清單、圖表、報價明細；圖表增量更新。
3. **P3 總覽 dashboard**：狀態燈、今日摘要、策略與部位欄位。
4. **P4 永豐串接**：註冊回呼、重連補資料；程式與假 SDK 測試可先完成，真實驗證要在券商模擬環境以 `CONNECT_READ_ONLY` 由使用者進行。
5. **P5 後續選項**：圖上策略標記、五檔／逐筆、券商 K 線存成研究資料。

使用者已確認的決定（2026-10-28）：

- 支援商品：TMF、TX、現股三者都要。
- 新鮮度門檻：10 秒算延遲、60 秒算停止。
- 漲跌參考價：期貨與現股都用前一交易日收盤價。
- 順序：先做看盤（P2），再做總覽（P3）。

Implementation: NOT IMPLEMENTED. Automated verification: NOT RUN.
Real-App visual check: PENDING USER FINAL CONFIRMATION.
Record evidence with command, result and revision only after running it.
Keep [PROJECT_STATE](../agent/PROJECT_STATE.md) and acceptance scores unchanged; formal acceptance remains 230/300. No Release or tag is part of a design proposal.

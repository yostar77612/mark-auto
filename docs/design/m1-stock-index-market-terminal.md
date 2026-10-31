# M1：個股與指數看盤終端

Status: PROPOSED / NOT IMPLEMENTED. Verification: NOT RUN.
Owner review: PENDING（區塊切法與警示清單待使用者確認）。

## Problem

使用者要把 v2「市場」工作區做成券商看盤軟體式的多區塊畫面（2026-10-31 參考圖：
報價清單、警示紀錄、指數報價、類股排行、個股分時與五檔、加權指數分時、訊息列）。
目前的「市場」頁只有一張窄表格、一張小 K 線圖與一欄原始明細，資訊擠在一起、
沒有重心（見 [market_watch.py](../../desktop_app/features/trading/market_watch.py)、
[market_watch_rows.py](../../desktop_app/features/trading/market_watch_rows.py)）。

使用者已確認的需求（2026-10-31）：

| # | 決定 |
|---|---|
| 1 | 先做**個股與指數**；期指之後再加 |
| 2 | 歷史 K 線**定時更新**；盤中**即時跳動** |
| 3 | 警示用**下拉選單**選類型（清單見下方「警示類型」） |
| 4 | 報價清單欄位：**成交、漲跌、漲幅％、總量** |
| 5 | 主圖為 **K 線**，週期 **1 分、5 分、15 分、日 K** |
| 6 | 要有**股號搜尋**；選到的商品直接顯示在右側主圖 |
| 7 | 主圖要有「**加入自選**」 |

目前程式的狀態（main `ba597b5`）：

| 項目 | 現況 | 位置 |
|---|---|---|
| 即時 tick | 已註冊永豐 tick 回呼（股票與期權） | [tick_stream.py](../../quantlab/trading/adapters/shioaji/tick_stream.py) |
| 五檔 | facade 有 `set_on_bidask_*` 但沒有人註冊；訂閱只用 `tick` | [sdk_facade.py](../../quantlab/trading/adapters/shioaji/sdk_facade.py)、[market_data.py](../../quantlab/trading/adapters/shioaji/market_data.py) |
| K 棒組合 | 1m 為基礎，可組 3m/5m/15m/30m/60m/1d | [live_bars.py](../../quantlab/trading/domain/live_bars.py) |
| 訂閱上限 | 預設 20 檔 | [freshness.py](../../quantlab/trading/domain/freshness.py) |
| 歷史 K 線 | `kbars` 單次 ≤ 30 天；需經完整交易引擎 | [market_data.py](../../quantlab/trading/adapters/shioaji/market_data.py) |
| 可停靠區塊 | 研究版 C5 已有拖曳、收合、具名版面 | [workspace.py](../../desktop_app/features/market/workspace.py)、[market_layout.py](../../quantlab/research_core/adapters/market_layout.py) |
| K 線圖 | `CandlestickChart`，含成交量 | [charts.py](../../desktop_app/components/charts.py) |

永豐限制（Shioaji 1.7.10 參考，專案鎖 1.7.9）：歷史資料指數／股票自 2020-03-02；
單次 `kbars` ≤ 30 日曆天；每日流量 500MB–10GB 依交易量；行情查詢 50 次／10 秒；
每人 5 條連線。加權指數代碼 `IX0001`、櫃買 `IX0043`。

## Goals/Non-goals

### Goals

- **G1 版面**：可停靠、可收合、可存版面的多區塊看盤畫面，沿用 C5 機制。
- **G2 報價清單**：分頁「自選」「指數」；欄位為代碼／名稱、成交、漲跌、漲幅％、總量；漲紅跌綠。
- **G3 主圖**：選中商品的 K 線加成交量；週期 1 分／5 分／15 分／日 K。
  標題列有「☆ 加入自選」，已在自選時改為「★ 移出自選」。
- **G7 股號搜尋**：頂部搜尋框，可輸入股號或名稱（例如 `2330`、`台積`），
  下拉列出符合的上市櫃股票與指數；選定後主圖立即切換到該商品，不必先加入自選。
- **G4 定時回補**：啟動時與收盤後補齊歷史 K 線，存在本機；盤中由即時 tick 接續。
- **G5 警示**：下拉選單選類型、設定參數、指定商品；觸發寫入警示紀錄。
- **G6 行情連線拆分**：只要環境與 API 金鑰就能看行情，不需交易連接器的其他欄位。

### Non-goals

- 期指（之後的階段再加）。
- 任何下單、改單、刪單；不讀取、不啟用 CA。
- 新聞（永豐沒有新聞 API）。
- 外盤／特大單比等看盤軟體自算指標（第一版不做）。

## Design

### 區塊配置（預設版面）

```
┌──────────────────────────────────────────────────────────────┐
│ 🔍 [股號或名稱，例如 2330、台積 ▼]                               │
├───────────────────────────────┬──────────────────────────────┤
│ ① 報價清單  [自選|指數]          │ ⑤ 主圖：選中商品               │
│  代碼 名稱  成交  漲跌  漲幅% 總量  │  2330 台積電 106 +0 ● 即時     │
│                               │  [☆ 加入自選]                 │
│                               │  [1分|5分|15分|日K]           │
│                               │  K 線 ＋ 成交量                │
├───────────────────────────────┤                              │
│ ② 警示紀錄  [新增警示 ▼]          ├──────────────────────────────┤
│  時間 商品 警示類型 觸發值          │ ⑥ 加權指數（固定，小 K 線）      │
├───────────────────────────────┴──────────────────────────────┤
│ ⑦ 狀態列：連線 · 訂閱 n/上限 · 今日流量 · 最新警示                   │
└──────────────────────────────────────────────────────────────┘
```

- 主圖顯示的商品來自三處，最後一次操作為準：搜尋選定、點選報價清單、點選警示紀錄。
  啟動時主圖預設顯示上次查看的商品；沒有紀錄時顯示加權指數。
- 搜尋清單取自登入後永豐提供的合約資料（股號、名稱、交易所），快取在本機；
  未登入時只能搜尋本機已有 K 線的商品，並註明「未連線，結果不完整」。
- 搜尋到的商品若不在自選，只為主圖做暫時訂閱；切換到別的商品就退訂，
  不佔用自選額度。訂閱已滿時主圖仍可看歷史 K 線，並提示無法即時跳動。
- 「加入自選」受訂閱上限限制，滿了會說明原因，不會默默失敗。
- 區塊皆可拖曳、收合、存為具名版面；預設版面與「重設」沿用 C5 行為。
- 參考圖的「五檔／成交明細」與「類股排行」列為後續階段（M1-4）。
- 原「市場」頁的原始明細（延遲、來源時間）移到 ⑦ 點開的「進階」，時間一律顯示台北時間。

### 警示類型（下拉選單）

| # | 類型 | 參數 | 適用 | 來源 |
|---|---|---|---|---|
| 1 | 價格突破／跌破 | 價位 | 個股、指數 | 自算 |
| 2 | 漲跌幅超過 | ±X% | 個股、指數 | 自算 |
| 3 | N 分鐘內急漲／急跌 | N 分、X% | 個股、指數 | 自算 |
| 4 | 創當日新高／新低 | — | 個股、指數 | 自算 |
| 5 | 突破前日高／跌破前日低 | — | 個股、指數 | 自算 |
| 6 | 量能放大 | 週期、前 N 根、倍數 | 個股 | 自算 |
| 7 | 均線交叉 | 週期、短／長均線 | 個股、指數 | 自算 |
| 8 | KD 黃金／死亡交叉 | 週期、低檔／高檔門檻 | 個股、指數 | 自算 |
| 9 | 接近／觸及漲停、漲停打開 | — | 個股（全市場或自選） | 永豐市場訊號 |
| 10 | 接近／觸及跌停、跌停打開 | — | 個股 | 永豐市場訊號 |
| 11 | 1 秒急漲／急跌 | — | 個股 | 永豐市場訊號 |
| 12 | 爆量大單 | — | 個股 | 永豐市場訊號 |

自算警示只看已完成的 K 棒或已收到的 tick，不偷看未來；同一條件觸發後有冷卻時間，
避免洗版。永豐市場訊號只涵蓋上市櫃個股。

### 定時更新

- 啟動時：對自選與指數清單，以 ≤ 29 天分段補齊缺漏的 1 分 K，存到工作區內的本機
  K 線庫（未來檔案，格式另議，傾向 Parquet）。
- 收盤後（股票 13:30 之後）：補當日完整 1 分 K，校正即時組出的 K 棒。
- 盤中：只用即時 tick 組 K，不重複查長區間；斷線恢復後只補斷線期間。
- 補資料前後讀 `api.usage()`，接近流量上限就暫停回補並在 ⑦ 提示。

### 階段

| 階段 | 內容 |
|---|---|
| M1-1 | 行情連線拆分（G6）＋ 歷史 K 線回補與本機 K 線庫（G4）＋ 週期改為 1/5/15/日 |
| M1-2 | 多區塊版面（G1）＋ 股號搜尋（G7）＋ 報價清單（G2）＋ 主圖與加入自選（G3）＋ 加權指數區塊 ＋ 狀態列 |
| M1-3 | 警示下拉選單、規則引擎、警示紀錄（G5） |
| M1-4 | 五檔與成交明細（訂閱 bidask）、類股排行（`IndustryContribution` 或排行查詢） |

### 待實測確認

1. `IX0001` 能否以 `kbars` 取得 1 分 K。
2. `simulation=True` 時 `kbars` 是否回傳真實歷史資料。
3. 帳號每日流量額度，以及一次完整回補實際用量。
4. 永豐即時訂閱的實際檔數上限（參考文件未列），決定 20 檔預設是否放寬。

## Safety constraints (live trading disabled, G3, OOS/budget)

Live trading stays permanently disabled; add no real order path. The market-data
connection never reads or activates the CA, so the SDK cannot place orders.
Keep all eight G3 files and protected saved-candidate profile blocks untouched;
if a future change needs them, obtain owner approval before editing. The exact
protected paths are in the [contributor guide](../CONTRIBUTING.md).
Preserve fail-closed validation, OOS one-time consumption, irreversible budgets
and every timeout (Paper 30 s, smoke 40 s, 15 min per job).
OOS and final-holdout data must never enter AI conversations, tool returns or
prompts. No eval/exec/new Function or other dynamic execution; no ChatGPT
credential reading, storage or display. Money arithmetic remains Decimal.
Unknown quote values display「未知」, never 0 or a stale value posing as live.

## Test plan

Each phase adds offline tests with a fake SDK and recorded fixtures; no test
logs in to SinoPac. Planned cases (requirements, not results):

- M1-1: 29-day chunking, gap-only backfill, quota-near-limit pause, 1/5/15/1d
  aggregation matching `kbars` right-labelled bars, no CA access on the
  market-data path.
- M1-2: accessibility walk and snapshot comparison of the new workspace;
  existing objectNames preserved; quote list colours and「未知」display;
  search by code and by name prefix, selecting a result switches the main
  chart without touching the watchlist, temporary subscription released on
  switch, add/remove watchlist toggle and the full-quota message.
- M1-3: each alert rule fires once on fixture bars/ticks, respects cooldown,
  never uses incomplete bars; dropdown lists exactly the types above.

Extend [test_market_watch_ui.py](../../tests/test_market_watch_ui.py),
[test_live_bars.py](../../tests/test_live_bars.py) and
[test_market_workspace_c5.py](../../tests/test_market_workspace_c5.py).
Real-App visual inspection is the user's final confirmation and remains pending.
Use the [contributor guide](../CONTRIBUTING.md) for lint, compile, quality-gate
and one-module-at-a-time test commands.

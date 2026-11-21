# M6：選股清單與條件觸發 K 線下載

Status: PROPOSED / NOT IMPLEMENTED. Verification: NOT RUN.
Scope owner decisions: 2026-11-21 chat (see 「使用者已確認的需求」).
Related: [m5-sector-board.md](m5-sector-board.md), [m1-stock-index-market-terminal.md](m1-stock-index-market-terminal.md).

## Problem

使用者做**當沖**，想在股票「平常沒什麼量、突然爆量拉出大紅 K」或「帶量突破新高」時，
立刻能看那檔股票過去一年的 1 分 K。現況：

- 一年 K 線只能用批次工具 [bulk_kline_backfill.py](../../tools/bulk_kline_backfill.py)
  依「成交金額前 N 名」手動下載，或在 App 裡選到某檔時才補歷史
  （[history_sync.py](../../quantlab/trading/application/history_sync.py)）。
  冷門股突然爆量的那天，本機通常沒有它的歷史。
- 市場頁報價清單只有「自選／指數／期貨」三個分頁
  （[market_terminal_widgets.py](../../desktop_app/features/trading/market_terminal_widgets.py) `build_terminal`），
  沒有依條件篩出股票的清單。
- 族群看盤的快照輪詢
  （[sector_service.py](../../quantlab/trading/application/sector_service.py) `SectorService.refresh`）
  每輪已經抓**全市場所有普通股**的快照（盤中約每 10 秒一輪），但只用來算族群統計；
  [QuoteRow](../../quantlab/trading/domain/sector.py) 沒有保留開盤價、最高價、最低價。
- 官方日 K（[daily_stock_store.py](../../quantlab/trading/adapters/storage/daily_stock_store.py)）
  只存有設定的個別股票，不是全市場，無法替任意股票判斷「N 日新高」。

## 使用者已確認的需求（2026-11-21）

| # | 決定 |
|---|---|
| 1 | 報價清單在「期貨」旁加一個**下拉式分頁**，名稱暫定「選股 ▾」，分頁上顯示目前選的清單 |
| 2 | 第一版清單：**爆量**（依量比排序，篩選「全部／長紅／長黑」）、**帶量突破新高**、**已下載 K 線**；選單最後一項「條件設定…」 |
| 3 | 不做：成交金額排行、漲幅排行、漲停／接近漲停、獨立的爆量長黑清單（併入「爆量」的篩選）、庫存分頁 |
| 4 | **盤中與收盤後都偵測** |
| 5 | **不設每日下載上限**，只沿用現有「流量用到 90% 就停」的保護 |
| 6 | **爆量長紅**與**帶量突破新高**都自動下載近一年 1 分 K；長黑預設不自動下載（可在設定開啟） |
| 7 | 第二版再做：跳空大漲、下載佇列清單 |
| 8 | D1：**回補**最近 240 個交易日的全市場日 K（2026-11-21） |
| 9 | D2：「平常冷門」預設 20 日均額 < 5,000 萬，**所有門檻都要能在「條件設定」自己調整**（2026-11-21） |

## Goals/Non-goals

Goals：

- 爆量清單即時列出量比最高的股票，並標出長紅／長黑型態。
- 符合「爆量長紅」或「帶量突破新高」的股票，自動排入一年 1 分 K 下載，不必手動。
- 「已下載 K 線」清單讓使用者看得出哪些股票本機已有歷史。
- 偵測不增加快照流量：沿用族群看盤既有的快照輪詢結果。

Non-goals：

- 不下單、不產生交易訊號、不影響自動交易或風控（純行情與下載）。
- 不改 K 線庫的完整性檢查（OPT-1 P10）與流量保護比例。
- 不做三大法人、注意／處置股等需要新資料源的條件（永豐 API 未提供）。
- 不在第一版做跳空大漲與下載佇列清單。

## Design

### A. 資料

1. **快照欄位**：[snapshot_poller.py](../../quantlab/trading/adapters/shioaji/snapshot_poller.py)
   `normalise_snapshot` 另外保存 SDK 快照已有的 `open`、`high`、`low`、`yesterday_volume`，
   [QuoteRow](../../quantlab/trading/domain/sector.py) 加對應欄位（族群統計不受影響）。
2. **全市場日 K（新）**：未來新檔 `quantlab/trading/adapters/storage/market_daily_store.py`，
   存在**獨立的** `market/market_daily.sqlite3`（不放進 K 線庫，避免拉長 K 線庫的完整性檢查）。
   每個交易日、每檔股票一列：開、高、低、收、量、金額。來源：
   - 每個交易日收盤後，用該日最後一輪快照寫入（不增加網路流量）；
   - **一次性回補**最近 240 個交易日（見待決定事項 D1）。
3. 「平常冷門」的基準：20 日平均成交金額，取自全市場日 K。日 K 不足 20 日時，暫用
   `total_amount ÷ volume_ratio` 估計平常同時段的成交金額（量比本身就是和前 5 日同時段比）。

### B. 條件（預設值，皆可在「條件設定」調整）

共通排除：非普通股（沿用 `eligible_stock`）、股價低於 10 元、當日成交量低於 500 張。
盤中開盤 10 分鐘（09:10）後才開始排名與觸發，避開剛開盤量比失真。

| 清單／型態 | 判斷 |
|---|---|
| 爆量（全部） | 依量比由高到低，最多 50 列 |
| 型態：長紅 | 量比 ≥ 3、漲幅 ≥ +5%、成交價 > 開盤價、距最高價 ≤ 1.5%、平常冷門（20 日均額 < 5,000 萬） |
| 型態：長黑 | 量比 ≥ 3、跌幅 ≥ 5%、成交價 < 開盤價、距最低價 ≤ 1.5% |
| 帶量突破新高（收盤後，正式） | 收盤 > 前 N 日最高價（N = 60／120／240，顯示達到的最大 N），且當日量 ≥ 20 日均量 × 2 |
| 帶量突破新高（盤中，暫定） | 成交價 > 前 N 日最高價且量比 ≥ 2；列中標示「盤中」，收盤後以正式條件重算 |

全市場日 K 不足 N 日時，該 N 不參與判斷；清單顯示「資料累積中（n／60 日）」。

### C. 觸發與下載

- 新的應用層服務（未來新檔 `quantlab/trading/application/stock_screener.py`）掛在
  `SectorService.on_round`（與既有族群警訊串接），每輪拿到全市場快照後計算清單與觸發，
  不另外呼叫快照。
- 同一檔股票、同一條件、同一天只觸發一次；寫入既有警示紀錄（`market/alert_events.jsonl`），
  內容例如「已加入 K 線下載：爆量長紅」。
- 觸發後呼叫 `HistorySync.request(股票, 現在-365 日, 結束時間, priority=觸發優先序)`：
  優先序低於主圖與自選，已下載的範圍會被跳過（`missing_ranges`），所以已有資料的股票幾乎不花流量。
- **盤中的結束時間設為前一個交易日收盤**：開盤期間查「範圍包含今天」的 K 線會逾時
  （2026-11-20 實測）。13:35 收盤後再補一次到現在，把當天補齊。
- **流量**：不另設上限（需求 5）。`HistorySync` 既有的 `quota_reserve_ratio`（保留 10%）用到就暫停；
  暫停期間仍照常偵測並列入清單，排隊的下載隔天流量重置後接續（既有行為）。
- 收盤後偵測：13:35 以後額外跑一輪快照（現在非交易時段只在沒有資料時跑一輪），
  用完整的當日 K 棒判斷，並寫入全市場日 K。

### D. UI

- `build_terminal`：報價分頁加第 4 個分頁，點分頁名稱跳出選單切換清單；內容沿用同一種報價表，
  點一列 = 主圖切到該股（既有 `select_instrument`）。
- 選單：
  ```
  ── 條件選股 ──
    爆量（篩選：全部／長紅／長黑）
    帶量突破新高
  ── K 線資料 ──
    已下載 K 線
  ──────────
    條件設定…
  ```
- 欄位：
  - 爆量：代碼、名稱、成交、漲幅%、量比、型態、K線。
  - 帶量突破新高：代碼、名稱、成交、漲幅%、突破（60／120／240 日）、量÷均量、K線。
  - 已下載 K 線：代碼、名稱、最早、最新、最後更新。只用 K 線庫既有的 `instrument_ids`（loose index
    scan）和主鍵 MIN／MAX，不做全表 COUNT。
  - 「K線」欄：✓ 已有一年、↓ 下載中、空白 = 沒有。
- 爆量清單上方一排篩選按鈕「全部／長紅／長黑」，以及顯示目前的最低成交量門檻。
- 右鍵：加入自選、下載近一年 K 線（手動觸發，同一條下載路徑）。
- 收盤後顯示「非交易時段・最後收盤資料」（同族群頁）。
- 「條件設定…」：門檻、每個條件是否自動下載；存在 `settings.json`（`MarketTerminalSettings`）。
- 新的讀取操作走 `ContextIpcFacade`；必須用真實 facade 測試參數有轉送（M5 #206 的教訓）。
- 字串用 `ui_text` key 登記在 [catalog](../../desktop_app/strings/catalog.py)；錯誤碼用
  [ERROR_TABLE](../../quantlab/errors.py)。

### E. 失敗行為

- 快照失敗：清單保留上一輪資料並標示過期；不觸發新下載。
- 下載失敗：沿用 `HistorySync` 的重試與退避（#252）；K 線欄顯示失敗。
- K 線庫或全市場日 K 無法使用：清單顯示原因代碼，不影響族群頁與報價。

### F. 考慮過但不採用

- **永豐 scanners 排行**（`VolumeRank` 等）：只給固定前幾名，沒有「平常冷門」的基準，也篩不出新高。
- **只用快照、不做全市場日 K**：爆量可以做，但「N 日新高」與「20 日均額」無從判斷。
  所以分階段：爆量先上（只靠快照），新高在全市場日 K 之後。

## 待使用者決定

- ~~D1~~ 已決定：回補（需求 8）。~~D2~~ 已決定：5,000 萬為預設，所有門檻可自行調整（需求 9）。
- **D3 K 線庫大小**：不設每日上限之下，K 線庫會持續變大（每多 100 檔約 +1 GB；完整檢查約每 GB 7–13 秒，
  啟動等待已放寬到 180 秒，#259）。是否要設一個總檔數上限（例如 400 檔）？

## Safety constraints (live trading disabled, G3, OOS/budget)

- 正式下單維持停用；本功能純行情與 K 線下載，不新增也不改動任何下單路徑，不產生交易訊號。
- 不改 K 線庫完整性檢查（OPT-1 P10）、流量保護比例、每日 K 棒上限與任何既有 timeout
  （Paper 30 s、smoke 40 s、每個 job 15 分鐘）。
- G3 檔案與 saved-candidate profile 區塊不動（清單見 [CONTRIBUTING.md](../CONTRIBUTING.md)）。
- OOS／final-holdout 資料不進任何清單、記錄或 AI 對話。金額運算維持 Decimal。
- 公開資料請求（D1）不帶任何帳號或憑證。

## Test plan

- 條件判斷為純函式：以 `QuoteRow` 與日 K 列為輸入，測每個門檻的邊界（剛好等於、差一點）、
  09:10 前不排名、低價／低量排除、日 K 不足 N 日時不判斷。
- 觸發去重：同股票同條件同日只觸發一次；跨日重置。
- 下載：盤中結束時間 = 前一交易日收盤；13:35 後補當日；優先序低於主圖與自選；流量暫停時仍列入清單。
- UI：offscreen 元件測試（分頁選單、篩選按鈕、欄位、右鍵、收盤後標示）、無障礙走查與快照比對，
  保留既有 objectName；新的 IPC 操作用真實 `ContextIpcFacade` 測試。
- 全市場日 K：收盤快照寫入、回補解析（固定測資，不連網）、缺日修補。
- 推送前跑完整 `unittest discover -s tests`、`tools/check_layers.py`、ruff、`tools/quality_gate.py --history`、
  `repin_baselines.py`（新檔 inventory 與字串 catalog）。
- 安裝後用 UIA 操作已安裝的 App 走一遍；即時資料（盤中觸發）需開盤時確認。

## Rollout/Verification status

分階段，每段一個 PR（各自獨立 QA、CI 全綠才合併）：

1. **M6-1 引擎**：`QuoteRow` 加欄位、`stock_screener` 服務、爆量條件與觸發下載（含盤中結束時間規則）。
2. **M6-2 UI**：選股分頁、爆量清單、已下載 K 線清單、條件設定、IPC 讀取操作。完成後發布一次並實機測試。
3. **M6-3 新高**：全市場日 K（收盤寫入；D1 同意則加回補）、帶量突破新高清單與觸發、改用 20 日均額判斷冷門。完成後再發布一次。

回退：各階段獨立，可單獨 revert；自動下載可在條件設定關閉。

Implementation: NOT IMPLEMENTED. Automated verification: NOT RUN.
Real-App visual check: PENDING USER FINAL CONFIRMATION.
Keep [PROJECT_STATE](../agent/PROJECT_STATE.md) and acceptance scores unchanged; formal acceptance remains 230/300.
No Release or tag is part of this design proposal.

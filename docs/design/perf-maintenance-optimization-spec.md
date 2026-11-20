# OPT-1：效能與維護性優化規格書

Status: IN PROGRESS (per-phase status in the Rollout section). P7: implemented after the owner's explicit approval (2026-11-20).
Audience: implementing agent. 觀察基準：`main` @ `d6c8d10f`，2026-11-20。
本文件的「現況」來自讀程式碼與 grep；僅標示「實測」者附有量測數字，其餘**尚未實測效能**；所有速度目標都要先量測再主張。
範本對照：[TEMPLATE.md](TEMPLATE.md)；工作規則沿用 [m1-implementation-spec.md](m1-implementation-spec.md) §0。

## Problem

一次抽樣程式碼檢視（回測、指標、交易檢視層、專案結構）找到下列可優化處。排序依「風險由低到高、
投入產出比由高到低」。每個階段（P0–P10）各一個 PR，可獨立交付與回退。
P8–P10 為第二輪檢視（2026-11-20，`main` @ `88c571fb`）新增，P7 同步擴充；其中標示「實測」者附有量測數字，
其餘為讀程式碼推斷，**必須先量測再動手**。

| 階段 | 主題 | 風險 | 是否碰 G3 |
|---|---|---|---|
| P0 | 專案整潔（ignore 規則、Git 物件庫） | 極低 | 否 |
| P1 | 靜默例外審計（`except …: pass`） | 低 | 否（G3 檔跳過） |
| P2 | `views.snapshot` 重複掃描 | 中 | 否 |
| P3 | KD 指標視窗極值 O(N×period)→O(N) | 低 | 否 |
| P4 | SQLite 開檔樣板收斂 | 低 | 否（G3 檔跳過） |
| P5 | Ruff 規則擴充（非凍結碼） | 低 | 否 |
| P6 | 超長函式拆分 | 中 | 否（凍結檔跳過） |
| P7 | 回測引擎查找與驗證拆分；重複雜湊／驗證快取（見 P7 第 6 項） | **高** | **是，需 owner 明確核准** |
| P8 | 板塊看盤詳情圖不再每 2 秒整段重抓 | 低 | 否 |
| P9 | 即時行情 tick 遺失處理的平方級掃描 | 中 | 否（先量測） |
| P10 | K 線資料庫開啟時的 `quick_check` 成本 | 中（動到 fail-closed 閘門） | 否（先量測，取捨需 owner 同意） |

### 現況證據

- **P0**：根目錄有 27 個 `tmp*` 資料夾、`t/`、`t2-*.log`、`shioaji.log`；`.gitignore` 第 160 行 `/.tmp*/` 只擋資料夾，
  `.tmp-m1-ci-*`、`.tmp-m2-*` 等檔案持續顯示為 untracked（約 173 筆）。`git count-objects -v` 回報
  多個沒有對應 `.pack` 的 `.idx`、`garbage: 77`、`prune-packable: 242`。另有 `.t-b2-work`、`.t2-work`、
  `.t4b-work`（16 MB，內含整份原始碼副本）、`.t6-work` 與 `.claude/worktrees/*`，會讓全專案 grep／索引出現重複命中。
- **P1**：原始碼 `except Exception` 約 169 處；`except …:` 緊接 `pass` 約 52 處（比對含合理的窄例外，為上限）。
  集中處：`quantlab/trading/runtime/context_client.py`(4)、`server.py`(3)、`web_fetch.py`、`sinopac_transition.py`、
  `sector_monitor.py`、`market_terminal_service.py`、`diagnostics.py`、`analysis_recovery_windows.py`、
  `desktop_app/smoke/auth.py`、`desktop_app/features/settings/automatic_backup.py` 等（各 1–2）。
  `loopback.py` 屬 G3，不碰。
- **P2**：[quantlab/trading/application/views.py:67](../../quantlab/trading/application/views.py) `snapshot` 共 358 行。
  對每個策略掃兩次 `state.orders`（`any` + `sum`，約 107–109 行），`tracks[...]` 同鍵在單一運算式查 5 次，
  `_order_trading_day`（58–63 行）對每張單線性掃策略與交易時段。`facade.snapshot()` 由
  [window.py](../../desktop_app/features/trading/window.py) 的指令 worker 每個指令呼叫 2–3 次（非定時輪詢）。
- **P3**：[quantlab/indicators.py:366](../../quantlab/indicators.py) `kd` 每步對整個視窗做 `max`/`min`；
  上限 `MAX_WINDOW_WORK = 5_000_000` 即為此成本而設。使用者：`desktop_app/features/market/indicator_presenter.py`。
  （`quantlab/trading/domain/alerts.py` 呼叫的是另一個 `kd`，不在本範圍。）
- **P4**：`sqlite3.connect(sqlite_uri(path) + '?mode=…', uri=True, timeout=…)` 樣板重複約 10 處
  （`sqlite_uri` 在 [quantlab/windows_paths.py:44](../../quantlab/windows_paths.py)）。
  其中 `account_store`、`finished_reconciliation`、`unknown_reconciliation`、`provider`、`research.py` 為 G3，**不遷移**；
  可遷移：`analysis_recovery.py`、`paper.py`、`paper_replay.py` 等非 G3 站點。
- **P5**：`pyproject.toml` 的 `[tool.ruff.lint] select` 只有 `E402/E711–E714/E721/E722/E9/F`。
- **P6**：最長函式：`views.snapshot` 358、`desktop_app/smoke/runner.py:run_smoke` 268、`backtest._run` 248（G3）、
  `research.run_campaign` 220（G3）、`desktop.run_gui` 208、`engine.submit` 204。
- **P7**：[quantlab/backtest.py:185](../../quantlab/backtest.py) 對每個結算事件執行
  `[b for b in dataset.bars if b.end==… and b.contract_id==…]`（O(事件數×K 棒數)）；199–210 行每根 K 棒重建
  `ZoneInfo('Asia/Taipei')`；`_run` 前約 90 行為輸入驗證。`backtest.py` 在 G3 清單內，且其原始碼雜湊進入 run manifest
  （`engine_hash`／`source_hashes`）與歷史 profile。
  **實測**（5,000 根合成 K 棒、單次 `run_backtest` 329 ms，無 profiler）：`content_hash(dataset.bars)` 53 ms；
  `_validate_bars` 28 ms，且在 `_run` 與 `generate_signals` 各跑一次；`canonical_json(result)`
  （`BacktestResult.__post_init__`）51 ms。三項合計約佔一半，且在同一份不可變資料集上反覆回測（campaign、walk-forward）
  時每次重算。profiler 下 `canonical_json` 單項佔累積時間 52%。涉及的 `backtest.py`、`strategies.py`、`core.py` 皆為 G3。
- **P8**（讀碼推斷；單次抓取成本**實測**）：[desktop_app/features/trading/sector_board.py:249](../../desktop_app/features/trading/sector_board.py)
  `refresh()` 由 2 秒計時器（`REFRESH_MS`）觸發，並呼叫 `_refresh_detail()`；後者只擋「同一鍵正在載入中」，載入完成
  即重新抓取選定個股的**整段**序列（`market_series` 分頁抓完）與五檔。
  `LiveMarketService.series()`（[live_market.py:341](../../quantlab/trading/application/live_market.py)）對回傳的每根
  K 棒逐一 `dumps(bar)` 估大小。實測 8,100 根 1 分 K：該迴圈 151 ms、3.76 MB（尚未含傳輸與解碼）。
  另 `bars += page.bars`（tuple 反覆串接）為 O(頁數²)，量小。
- **P9**（讀碼推斷）：[live_market.py:206](../../quantlab/trading/application/live_market.py) 每個 tick 對
  `buffer.losses` 做 `any(_affected_minute(...))`；處理每筆遺失時對整段 `history` 與 `live` 各做一次
  `_replace_bars` 全掃。上限皆為 `buffer_trade_days(30)×24×60 = 43,200`。只有大量 tick 遺失（斷線、佇列溢位）才會明顯。
- **P10**（讀碼推斷）：[kline_store.py:103](../../quantlab/trading/adapters/storage/kline_store.py) `_open` 每次開啟都執行
  `PRAGMA quick_check`，成本隨資料庫大小線性增加；批次回補工具（`tools/bulk_kline_backfill.py`）會讓資料庫持續變大。
  這是 fail-closed 的完整性閘門，且損毀時會把檔案連同 WAL 保留為 `.bad-*` 後重建。

## Goals/Non-goals

Goals
1. 各階段**行為逐位元不變**：輸出、雜湊、錯誤碼、時序保證都不得改變。
2. P2、P3 先建立量測與等價測試，再改實作，PR 附前後數據（真實跑出來的，不得預寫）。
3. P1 讓「真的會藏錯誤」的靜默例外留下**不含隱私內容**的紀錄；保留所有 fail-closed 與安全閘門。
4. P0 讓 `git status` 回到可讀，且不刪除任何不可還原的資料。

Non-goals
- 不改 Bollinger／SMA／EMA／RSI 等其他指標的算法（滾動變異數會改變 Decimal 末位，影響雜湊）。
- 不改交易、風控、下單路徑語意；不新增任何真實下單路徑。
- 不編輯 G3 鎖定檔（P7 除外且需核准）；不重新 pin 歷史 profile；不改 `saved_candidate_pool.py` 的 profile 區塊。
- 不引入 numpy／pandas 等新相依；金額運算維持 `Decimal`。
- 不做「為了好看」的大規模重排或改名。

## Design

### P0 專案整潔
- `.gitignore` 加 `/.tmp*`（取代 `/.tmp*/`）、`/t/`、`/t2-*.log`、根目錄 `/tmp*/`（先確認這些資料夾是否已被忽略，避免重複）。
- **不刪除**任何檔案或資料夾。先執行 `git worktree list`，列出 `.claude/worktrees/*`、`.t*-work` 是否為已登記的 worktree；
  只把清單與大小寫進 PR 說明，是否清除交給 owner。
- Git 物件庫：只跑預設的 `git gc`（預設 prune 期限，不用 `--prune=now`），並貼出 `git count-objects -vH` 前後。
  若 gc 因殘缺 `.idx` 失敗，記錄原因，不手動刪 `.git` 內檔案。

### P1 靜默例外審計
- 對 P1 範圍內每個 `except …: pass` 分類並在 PR 以表格列出：
  (a) 預期且無害（例如清理、關閉 handle、探測性呼叫）→ 保留，必要時改窄例外型別並加一行註解說明原因；
  (b) 會隱藏真實故障 → 改為記錄後照舊吞掉或重新拋出，**行為（回傳值、是否繼續）不變**，只增加可觀測性。
- 記錄只能含例外類別名稱與固定代碼；**不得**記錄例外訊息本文、路徑中的使用者名稱、憑證或帳號（比照
  [window.py](../../desktop_app/features/trading/window.py) `run` 的做法：never the message）。
- 沿用專案既有記錄機制（先查 `quantlab/diagnostics.py` 與現有 logger 用法）；不新增 logging 框架。
- 凡處於 fail-closed、對帳、憑證、下單相關路徑的吞例外，**預設保留不動**，只在 PR 列為「已審查，保留」。

### P2 `views.snapshot` 優化
1. **先量測**：新增 `tools/bench_snapshot.py`（未來檔案；依先例 `d5ffe4de`，須同 PR 登記到 refactor inventory），
   建構 S 個策略 × O 張單（例如 S∈{10,50}、O∈{100,1000,5000}），輸出每次 `snapshot` 耗時。
2. **等價測試**：新增 characterization 測試，對多組（含空 state、無交易時段、`today_order_count=None` 分支、
   `verified=False`）固定輸入，斷言重構前後 `UiState` 完全相等（dataclass 相等，含順序）。**先在舊實作上通過再重構。**
3. **實作**：
   - 迴圈前一次建立 `orders_by_strategy: dict[(strategy_id, version), list[order]]`，每策略的
     `today_order_count` 由此取得，不再重複掃 `state.orders`。
   - `tracks[...]` 與 `(strategy_id, version)` 在單一策略內只取一次。
   - `_order_trading_day` 的策略查找改用預先建立的 `records` 字典；交易時段查找若 `calendar.sessions` 已排序，
     可二分搜尋，否則維持線性但每個 calendar 只建一次索引。
   - 將 `snapshot` 依區段拆成私有小函式（策略、委託、部位、帳戶風險、市場），主函式只負責組裝。
     保持 `@decimal_operation` 與原有 import 的延遲載入（避免循環 import）。
4. 目標：複雜度由 O(S×O) 降為 O(S+O)；PR 附前後數據。若實測 O 常態很小、差距不顯著，仍可合併（可讀性收益），
   但需在 PR 如實說明「速度提升不顯著」。

### P3 KD 視窗極值
- 在 [quantlab/indicators.py](../../quantlab/indicators.py) `kd` 以兩個單調 deque（最高、最低）取代每步 `max`/`min`。
  僅做比較，不做算術，故輸出逐位元相同。
- 必須維持：`None` 重置視窗、`low <= close <= high` 驗證、`len(window) < period` 暖機行為、
  `MAX_WINDOW_WORK` 保護（改為 O(N) 後可保留該上限以維持對外行為與既有測試）。
- 不改 `bollinger`、不改公式版本字串 `FORMULA_VERSION`（輸出不變）。

### P4 SQLite 開檔收斂
- 新增小型共用函式 `open_sqlite(path, *, mode, timeout, isolation_level=…)`（未來檔案；放置位置須符合
  [tools/layer_map.json](../../tools/layer_map.json)，並跑 `python tools/check_layers.py`），行為與現有
  `sqlite_uri(path) + '?mode=…'` 呼叫等價。
- 只遷移非 G3 站點；每個站點遷移後行為（timeout、`uri=True`、isolation_level、關閉方式）必須不變。
- 若遷移導致任何非 G3 站點需更動既有測試斷言 → 停止該站點，保持原樣。

### P5 Ruff 擴充
- 對**非凍結**程式碼啟用 `B`（bugbear）與 `PERF` 中不會造成大規模改動的子集；先以 `ruff check --statistics` 看量。
- 既有違規採「該 PR 修掉」或「逐檔 `per-file-ignores` 並註明原因」，**禁止**為了通過而大面積加 `# noqa`。
- 不得把 `[tool.ruff] exclude` 的凍結檔納入；不改 `line-length`／格式化設定。
- 若新增規則導致 CI 的 ruff 版本鎖（`requirements-ruff.lock`）需要改，另案處理，不在本階段。

### P6 超長函式拆分
- 範圍：`views.snapshot`（併入 P2）、`desktop.run_gui`、`desktop_app/smoke/runner.py:run_smoke`、`engine.submit`。
- 每個函式單獨一個 commit；純機械式抽出（Extract Function），不改控制流程與例外語意。
- 每次動手前必須跑 GitNexus impact；`engine.submit` 在下單路徑上，若 impact 為 HIGH／CRITICAL，
  PR 說明須列出呼叫者與對應測試，並在無法證明等價時**放棄該函式**。
- 凍結／G3 函式（`backtest._run`、`research.run_campaign`）不在此階段。

### P7 回測引擎（G3，需 owner 核准才能開工）
**預設跳過。** 只有在 owner 於對話中明確核准編輯 `quantlab/backtest.py` 後才執行。內容：
1. 進入結算迴圈前建 `{(end, contract_id): [bars]}`，取代 185 行的全表掃描；保留「必須恰好一筆」的檢查與錯誤訊息。
2. 將 199–210 行的 `ZoneInfo('Asia/Taipei')` 提到迴圈外（模組級或函式內一次）。
3. 把 `_run` 前段輸入驗證抽成 `_validate_inputs`，不改驗證順序與錯誤訊息。
4. 依 CONTRIBUTING 與 `f05328b` 先例處理：新原始碼身分需要新的 current profile，**不得**把歷史 profile 重新 pin 到新原始碼；
   `r7_base.json` 等基準以獨立 fixture-only commit 更新並記錄原因，交 QA 重驗。
5. 必須用同一組固定資料集在新舊實作各跑一次，比對 `run_hash`／`reproducibility_hash`／fills／ledger 完全一致。
6. **重複雜湊／驗證快取**（依上方實測）：在同一個不可變 `Dataset` 實例上快取 `content_hash(bars)` 與「`_validate_bars` 已通過」
   結果，使同一資料集的第二次以後回測不再重算。限制：
   - 快取以物件身分為鍵，且僅在 `bars` 為不可變 tuple、`Dataset` 為凍結時成立；先確認這兩個前提，不成立就放棄本項。
   - 首次仍須完整驗證並比對 `manifest['data_hash']`；錯誤碼與訊息不變。
   - `BacktestResult.__post_init__` 的 `canonical_json(self)` 保留，除非能證明其保證已由建構過程確保；否則只做資料集側快取。
   - 兩次驗證之一（`_run` 與 `generate_signals` 內的 `_validate_bars`）可合併，但不得改變驗證順序與丟出的第一個錯誤。
   - 同樣需要新 current profile 與 fixture-only commit（見第 4 項），並附前後實測（5,000 根與一次多候選 campaign）。

### P8 板塊看盤詳情圖增量更新
1. **先量測**：新增 `tools/bench_series.py`（未來檔案，須登記 refactor inventory），量 `LiveMarketService.series()`
   在 1,000／8,100／43,200 根 1 分 K 下的耗時與 payload 大小，以及 `period` 為 `5m`／`1d` 時的結果。
2. **等價測試**：寫一個模擬器依序餵入多輪 tick（含新增 K 棒、末根更新、歷史回補、遺失標記），斷言「首次整段＋之後每輪只取尾端再合併」
   的結果，與「每輪整段重抓」逐根相等。**先用現有整段策略建立 oracle。**
3. **實作**（[sector_board.py](../../desktop_app/features/trading/sector_board.py)）：
   - 首次載入（或選股／週期改變、`retry_history`、`gaps` 改變、回傳 `offset`／`total` 與快取不連續、`total` 小於快取）仍整段重抓。
   - 之後的 2 秒刷新只抓尾端 `K` 根（`K` 取足以涵蓋末根更新與聚合週期尾巴的小常數，PR 說明理由），以回傳的 `offset` 取代快取尾端。
   - 每隔一段固定時間（例如數分鐘）做一次整段校正，防止漂移。
   - 五檔（`order_book`）照舊每次取得。
   - 可選：若量測顯示 `series()` 內逐根 `dumps` 仍是瓶頸，**在不削弱頁面位元組預算上限保證**的前提下降低估算成本；做不到就不做。
4. UI 原始碼雜湊可能綁入 golden fixture（P3 先例：`ui_operations_golden.json` 需 fixture-only commit 重生）；動手前先搜尋 `sector_board` 的雜湊綁定。
5. 目標：穩態下每次刷新的序列 payload 由整段降為尾端 `K` 根；PR 附前後實測（耗時、位元組）。

### P9 即時行情 tick 遺失處理（先量測，可能結案為不動）
1. 以合成資料量測：`losses` 數量 ∈ {0, 100, 1,000, 10,000}、每個 deque 約 43,200 根時，`poll()` 處理 1,000 個 tick 與一批遺失的耗時。
2. 若在合理負載下 `poll()` 無明顯影響，**結案為不動**，把數字寫進 PR 與本文件，不改程式。
3. 若確有影響：把 `buffer.losses` 維護成合併後、不重疊且有序的分鐘區間，tick 時以 `bisect` 判斷；一批遺失只對 `history`／`live`
   做**單趟**掃描標記 `incomplete`。必須保持：`_replace_bars` 以身分比較決定是否遞增 `history_revision`、`_view_cache` 的失效時機、
   `buffer.minute` 的 `incomplete` 設定、`issues` 佇列內容。以舊實作凍結副本為 oracle 做等價測試。

### P10 K 線資料庫開啟成本（先量測；改動需 owner 明確同意）
1. 量測 `KlineStore._open` 在 {10 MB、200 MB、1 GB} 資料庫上的耗時，並拆出 `quick_check` 佔比。
2. 若 `quick_check` 佔比小，**結案為不動**。
3. 若顯著，且 owner 在對話中明確同意放寬此閘門，才可採：在 `meta` 表記錄「開啟中」旗標，正常 `close()` 清除；開啟時若旗標殘留
   （異常結束）或 `-wal` 非空，才跑 `quick_check`；其餘情況改跑成本固定的檢查（既有的 schema／`table_info` 驗證），
   並定期（記錄時間於 `meta`）補跑完整檢查。任何失敗仍走既有的 `.bad-*` 保留與重建流程與同一錯誤碼 `kline_store_unavailable`；
   旗標寫入失敗時一律退回「跑 `quick_check`」（保守方向）。

## Safety constraints (live trading disabled, G3, OOS/budget)

沿用 [TEMPLATE.md](TEMPLATE.md) 的安全章節全文，另加：
- 本規格每個階段都不得新增或改動任何真實下單路徑；Decimal 金額運算不得改成 float。
- P1 的記錄內容受隱私限制（見上）；OOS／final-holdout 資料不得出現在任何記錄或基準資料中。
- 所有 timeout（Paper 30 s、smoke 40 s、每個 job 15 分鐘）與 fail-closed 驗證保持原樣。
- P0 不做不可逆刪除；`git gc` 不使用 `--prune=now`。
- G3 檔案（見 [CONTRIBUTING.md](../CONTRIBUTING.md)）除 P7（含第 6 項）且經 owner 核准外一律不編輯。
- P8–P10 不改交易、風控、下單語意；P10 不得削弱完整性檢查的保證，只能改變「何時」執行，且失敗時退回較保守的做法。

## Test plan

通用（每階段）：`powershell -File tools/prepush.ps1 -Tests`；相關測試模組逐一
`python -m unittest tests.<module>`；`python tools/check_layers.py`；`python -m ruff check`；
`python -m unittest discover -s tests -p test_layer_gate.py`、`test_quality_gate.py`。
新增檔案（工具、測試）須通過既有品質閘與 refactor inventory 登記檢查。

| 階段 | 既有測試 | 新增（需求，非結果） |
|---|---|---|
| P0 | 無程式變更；跑快速 prepush | `git status --short` 不再列出 `.tmp-*`、`t2-*.log` |
| P1 | 各被改檔案對應模組測試、`tests/test_trading_runtime*`、smoke 相關 | 對 (b) 類改動：觸發例外時行為不變且有一筆不含訊息本文的記錄 |
| P2 | `tests/test_trading_application.py`、`test_trading_ui.py`、`test_trading_sdk_facade.py` | `snapshot` 等價測試（新舊輸出相等）、`tools/bench_snapshot.py` 前後數據 |
| P3 | `tests/test_indicators.py`、`test_lb_b3_indicators.py`、`test_desktop_market*.py` | 隨機＋含 `None`、平盤（highest==lowest）、暖機邊界的新舊 `kd` 逐值相等測試 |
| P4 | 各遷移站點的既有測試（`test_paper*`、`test_analysis_recovery*`） | `open_sqlite` 對唯讀／讀寫／不存在檔案的行為與舊寫法相同 |
| P5 | ruff 全專案 | 無 |
| P6 | 被拆函式所在模組的全部既有測試與 GitNexus `detect_changes` | 拆分前後行為相等的 characterization 測試（若原本缺） |
| P7 | `tests/test_r7_characterization.py`、回測相關全套 | 新舊實作同資料集 hash 完全相等；G3 pins／profile 測試；第 6 項另測「同一資料集連跑兩次結果相同」「資料遭竄改仍丟出原錯誤」 |
| P8 | sector board／market series 相關既有測試（用 `grep sector_board tests` 找出）、`test_trading_ui`、UI 快照測試不得變更基準 | 增量合併與整段重抓逐根相等的模擬器測試；`tools/bench_series.py` 前後數據 |
| P9 | `tests/test_live_market*.py`、`test_m5_monitor`、行情相關測試 | 量測腳本；若實作，舊實作凍結副本為 oracle 的等價測試（含 `history_revision` 遞增時機） |
| P10 | kline store 相關既有測試（`grep kline_store tests`） | 開啟耗時量測；若實作：旗標殘留／`-wal` 非空／旗標寫入失敗／損毀檔案四種情境的測試，損毀仍產生 `.bad-*` 並使用同一錯誤碼 |

UI 無新增畫面，故不要求新的 accessibility walk；若 P2/P6 動到 UI 呼叫端，需跑既有 UI 快照測試且不得變更基準。

## Rollout/Verification status

順序：P0 → P1 → P3 → P2 → P4 → P5 → P6 → P8 → P9 → P10 →（P7，待核准）。P8 不碰 G3、收益最明確，排在 P6 之後即可開工；
P9、P10 為「先量測、可能結案為不動」的階段。P3 排在 P2 前，因為它不碰 G3 且等價性最容易證明；
P2 需先有量測基準，故在 P1 之後。每階段一個 PR、可單獨回退（revert 該 PR）。每個 PR 經獨立 QA（aiworkflow-qa）
驗收、CI 全綠後才合併；controller 不得自行驗收自己的實作。
Implementation／Verification（逐階段，只記錄實際跑過的指令與結果）：

| 階段 | Implementation | Verification |
|---|---|---|
| P0 | `.gitignore`：`/.tmp*/` 改為 `/.tmp*`（同時擋檔案），新增 `/tmp*/`；`/t/` 與 `*.log`（含 `t2-*.log`、`shioaji.log`）原本已忽略，未重複加入。未刪除任何檔案；worktree 清單寫在 PR 說明，是否清除由 owner 決定。 | 主 checkout `git status --short` 原為 174 筆；以新規則模擬（`git ls-files -o --directory --exclude-standard --exclude-from=<新 .gitignore>`）剩 13 筆，`.tmp-*` 與 `tmp*/` 全數不再列出。`git gc`（預設 prune 期限）exit 0；`git count-objects -vH` 前：count 267、packs 4、size-pack 113.24 MiB、prune-packable 242、garbage 77；後：count 0、packs 2、size-pack 108.34 MiB、prune-packable 0、garbage 0。`test_repo_layout`、`test_docs_layering`、`test_dev_setup`、`test_layer_gate`、`test_quality_gate` OK；`check_layers.py` 0 findings；`ruff check` passed。 |
| P1 | AST 掃描 68 處 `except …: pass`；G3 7 處不碰。其餘 61 處分類（表格見 PR）：加記錄 4 處（`MarketTerminalService._try`、`SectorMonitor.on_round`、`SectorMonitor._flow_alert`、`SectorPoller._run`，只記 DomainError 代碼或例外類別名稱，行為不變）；預期無害保留 35；fail-closed／對帳／憑證／下單路徑「已審查，保留」17；桌面 GUI 程序無任何 logging handler（加記錄無可觀測性）保留 5。 | 新測試先在舊實作確認行為部分通過（log 斷言如預期失敗），改後 `python -m unittest tests.test_m5_monitor`、`tests.test_market_terminal_service` OK；`tools/affected_tests.py` 選出的 164 模組逐一執行（`PYTHONPATH=tests`）162 OK，`test_trading_acceptance_combinations`（Windows 檔案鎖 PermissionError）與 `test_trading_installer_guard`（偵測到本機正在執行的 MarkAuto）在未修改的 P0 樹上同樣失敗，屬主機環境；`check_layers.py` 0、`check_trading_architecture.py` 0、`ruff check` 通過。 |
| P3 | `kd` 以兩個單調 deque（只彈出嚴格較小的高點／較大的低點，保留同值中最早者，與 `max`/`min` 回傳同一個 Decimal）取代每步 `max`/`min`；`None` 重置、驗證、暖機、`MAX_WINDOW_WORK`、`FORMULA_VERSION`、bollinger 皆未改。`indicators.py` 原始碼雜湊綁入分析封包，故 `ui_operations_golden.json` 恰 23 個雜湊葉以獨立 fixture-only commit 重生（`docs/analysis/opt1_p3_golden_changes.md`），`test_golden_metadata` 兩個摘要同步重釘。 | 等價測試（舊迴圈凍結副本為 oracle，`str()` 逐值比對）在舊實作先通過、改後通過；破壞同值順序的 mutation 被抓到。實測（Python 3.13.11，5 次中位數）：N=10k/period 9 0.0759→0.0674 s（1.1×）、N=100k/9 0.8456→0.7730 s（1.1×）、N=50k/100 0.8444→0.3572 s（2.4×）、N=5k/1000 0.4442→0.0453 s（9.8×）；預設 period 9 提升不顯著。`prepush.ps1 -Tests` 通過；`affected_tests.py` 選出 255 模組逐一執行 251 OK，`test_e1_qualification`（無 symlink 權限）、`test_paper_diagnostics`、`test_test_group`（WinError 32 檔案占用）、`test_trading_installer_guard` 在未修改樹上同樣失敗，屬主機環境；`test_layer_gate`、`test_quality_gate`、`test_docs_layering`、`check_layers.py` 通過。 |
| P2 | 先新增 `tools/bench_snapshot.py`（已登記 inventory）與等價測試（`tests/trading_snapshot_reference.py` 為機械產生的舊 `snapshot` 凍結副本），在舊實作通過後才重構：委託／部位依 `(strategy_id, version)` 一次分組（保留原順序）、每策略只取一次 track 與解析商品、`_order_trading_days` 一次建立策略字典並對 `TradingCalendar.sessions` 二分搜尋（回退檢查相接時段，結果同舊 `next()`），`snapshot` 拆成依原順序呼叫的私有階段。 | `SnapshotEquivalenceTests`（`==` 與 `repr()` 皆相等，涵蓋空 state、未對帳、30 秒外報價、25 倍放大、`verified=False`、時段邊界與時段外委託、刪除／無策略）與 `SessionDayTests`（200 組隨機日曆；mutation 被抓到）通過。實測 `python tools/bench_snapshot.py --repeat 9` 兩輪中位數（舊→新 ms）：10×100 9.4→7.7、10×1000 53.4→35.4、10×5000 249.1→158.7、50×100 26.5→23.4、50×1000 81.6→53.5、50×5000 319.7→184.9（1.1–1.7×；主要耗時在範圍外的 `engine.reservations()`，提升有限）。`affected_tests.py` 選出 163 模組逐一執行 161 OK，`test_trading_acceptance_combinations`、`test_trading_installer_guard` 與 P1 相同屬主機環境；`test_trading_application`、`test_trading_ui`、`test_trading_sdk_facade`、`test_function_lengths`、`test_layer_gate` OK。 |
| P4 | 新增 `quantlab/shared/sqlite_open.py` 的 `open_sqlite(path, *, mode, timeout)`（即 `sqlite3.connect(sqlite_uri(path) + "?mode=" + mode, uri=True, timeout=timeout)`，已登記 inventory）；遷移 5 處非 G3 站點：`analysis_recovery._connect`、`PaperBroker.read_snapshot`（原隱含預設 timeout 5.0）、`saved_pool_source._read_campaign`／`_validate_source_registry`、`WorkerRepository.candidate_state`（helper 於函式內延遲 import）。放棄：G3 檔；`research_analysis.py`、`walk_forward.py`（原始碼雜湊進 golden，遷移需改基準）；`e1_store.py` 與 `windows_paths.py`（在 `e1_protocol.SOURCE_FILES`）；`paper_replay.py`（非 URI 樣板）。 | `OpenSqliteTests`（原 `tests/test_sqlite_open.py`；合併 #246 與 #241 後 main 的 Linux 3.12 paper-remaining 分片在 `test_market_terminal_ui` setUp 出現 Qt 原生崩潰，依前例改併入既有的 `tests/test_windows_long_paths.py`，測試內容不變）：呼叫形狀與舊寫法逐一相等（mock 記錄）、唯讀／讀寫／rwc／不存在檔案的實際行為相同，OK。`affected_tests.py` 選出 270 模組逐一執行 265 OK；`test_e1_qualification`、`test_paper_diagnostics`、`test_test_group`、`test_trading_installer_guard`、`test_windows_recovery_feasibility`（retained handle）在不含 P4 的樹上同樣失敗，屬主機環境。`test_layer_gate`、`check_layers.py`、`ruff check` 通過。 |
| P5 | `ruff check --select B,PERF --statistics` 共 555 筆；啟用 Ruff 0.16.10 全部 stable 的 B／PERF 規則（逐條列在 `select`，因 `test_ruff_config` 禁止全域 `ignore`），暫不啟用量大的 B007(19)、B008(37)、B009(81)、B023(248)、B905(133)、PERF401(24) 並在 pyproject 註明。其餘 13 筆：PERF102 兩處修正（`.keys()`／`.values()`，同一 dict 順序）；B012（desktop.py 結束碼契約）、B904（改 chaining 會變 `__cause__`）、B020（測試刻意重用迴圈變數）、B018（`test_desktop_analysis` 為存在性檢查；`test_chatgpt_plan` 的 4 處 `self.tmp_path` 是無作用的殘留讀取，為保持測試檔不變而忽略）以逐檔 per-file-ignores 註明原因。未加 `# noqa`，未動凍結排除清單、line-length、格式設定與 `requirements-ruff.lock`。 | `ruff check .`、`ruff format --check .` 通過；`tests.test_ruff_config` OK。pyproject 屬打包輸入，故逐一執行全部 500 個測試模組：494 OK；`test_e1_qualification`、`test_paper_diagnostics`、`test_test_group`、`test_trading_acceptance_combinations`、`test_trading_installer_guard`、`test_windows_recovery_feasibility` 在未修改的樹上同樣失敗，屬主機環境。 |
| P6 | `views.snapshot` 已於 P2 拆分。其餘三個函式經 GitNexus impact 與既有守門測試審查後放棄，不改任何程式碼：`TradingEngine.submit` impact 為 HIGH（lower-bound，105 個呼叫點無法解析），且位於下單路徑，日誌寫入與風控／對帳閘門穿插其中，無法證明機械拆分等價；`desktop.run_gui` 的 except／finally 區塊被 `test_t11_part_b` 的 AST 摘要（HANDLERS_DIGEST／FINALLY_DIGEST）鎖定，`desktop.py` 的頂層定義集合也被 `test_desktop_smoke_package` 鎖定；`run_smoke` 的主體被 SMOKE_DIGEST 鎖定。任何拆分都必須改這些測試斷言，故放棄。 | 僅文件變更：`ruff check .`、`test_docs_layering` 通過。impact（upstream）：`TradingEngine.submit` HIGH、`run_gui` LOW、`run_smoke` LOW。 |
| P7 | owner 已於對話中明確核准編輯 `quantlab/backtest.py`（2026-11-20）。只改 backtest.py：結算事件改用一次建好的 `{(end, contract_id): [bars]}`（保留「恰好一筆」檢查與訊息）；`ZoneInfo('Asia/Taipei')` 提為模組常數；`_run` 前段驗證原樣、原順序抽成 `_validate_inputs`；同一個不可變 Dataset 物件重複回測時重用「`_validate_bars` 已通過」與 `content_hash(bars)`（以物件身分＋weakref＋bars 身分確認，各自在原位置首次計算，驗證順序與第一個錯誤不變，`data_hash` 每次照比）。`strategies.py` 內的第二次 `_validate_bars` 與 `core.py` 的 `canonical_json` 為其他 G3 檔，未動。新增 current profile `STOCK_SIGNAL_PROFILE_V2`（只換 backtest.py 身分），V1 與 30 個歷史 block 逐位元不變，未重新 pin；V2 campaign 與 V1 同樣保留 OOS＋holdout 聯集。 | `FrozenEngineEquivalenceTests`（main 的 backtest.py 原檔凍結為 fixture、記憶體載入）：全部 EngineTests 情境、300／5,000 根內建策略各跑兩次、到期日台北 13:30 邊界，新舊 repr 與 `run_hash` 逐位元相同；時區與結算查詢 mutation 被抓到。基準以獨立 baseline commit 改指向 V2。完整套件 500 模組逐一執行：首輪 21 個非 OK，加入 V2 與基準後重跑剩 7 個，皆為已在未修改樹上確認的主機環境失敗（`test_qt_licenses` 實為 OK）。實測 `python tools/bench_backtest_repeat.py --repeat 5`（5,000 根）：首次 318.9→328.0 ms（持平）、同一 Dataset 重跑 317.4→232.1 ms、15 個候選 4,828.1→3,405.1 ms（約 29%）。 |
| P8（#250 已合併） | 先新增 `tools/bench_series.py`（已登記 inventory）與 `DetailSeriesEquivalenceTests`（真實 LiveMarketService；先在原整段策略確認通過）。`sector_board.py` 改為快取 (股票, 週期) 的序列，每次刷新只讀最後 `SERIES_TAIL_BARS = 240` 根再接上；無快取／換股或週期／錯誤／新增超過一頁／total 變小／gaps 改變／重讀視窗任何不一致時改回整段重抓，並至少每 `SERIES_RESYNC_SECONDS = 120` 秒整段校正一次。五檔照舊每次取得。`sector_board` 未綁任何 golden 或原始碼雜湊；最終 fixture 與 main 無差異。 | 90 輪（新增 K、末根更新、位移型回補、遺失標記、1m→5m）每輪 `repr` 與整段重抓相同、超過 70 輪走尾端；拿掉視窗比對有 56 輪失敗；視窗外同筆數改寫於下一次整段校正（≤120 秒）顯示，已測。實測 `python tools/bench_series.py --repeat 5`（每次刷新、server 端）：43,200 根 1m 695.0 ms／20,476,800 B／11 頁 → 3.8 ms／113,760 B／1 頁；8,100 根 1m 128.8 → 3.8 ms；43,200 根 5m 451.1 → 96.5 ms；1d 持平。affected 99 模組 98 OK（`test_auto_connect` 一次於負載下失敗，重跑 3/3 通過、main 上通過）；QA PASS；CI 35 項全綠。 |
| P9（#253 已合併） | 量測顯示影響明顯，故未結案為「不動」。`live_market.py`：`losses` deque 仍為唯一來源（maxlen 淘汰不變），另快取合併後有序不重疊分鐘區間，tick 以 `bisect` 判斷；一批遺失每個 instrument、每個 deque 只掃一趟，`history_revision` 仍依「遺失 × 有受影響 K 棒的 deque」計數，`issues` 順序與 `_view_cache` 失效不變。新增 `tools/bench_tick_loss.py`（已登記）。 | 舊 `poll` 機械凍結副本為 oracle，`TickLossEquivalenceTests` 240 步隨機 tick／遺失（含逆向、超長、淘汰、未配置標的）全部欄位相同；revision mutation 240 步全失敗。實測 `python tools/bench_tick_loss.py --repeat 3`（1,000 tick，每 deque 約 43,200 根）：保留 0／100／1,000／10,000 筆遺失時只處理 tick 40.6／80.2／418.5／3,783.4 ms → 42.6／43.5／42.2／47.3 ms；加一批 10 筆遺失 295.5／348.0／675.2／4,144.3 → 66.5／62.7／63.6／67.9 ms。affected 314 模組 310 OK，其餘為已確認之主機環境失敗；QA PASS；CI 35 項全綠。 |
| P10 | 第一步僅量測（#256，`tools/bench_kline_open.py`）；佔比顯著，owner 於 2026-11-20 對話中明確同意依 §P10 第 3 點放寬，故實作：`KlineStore` 開啟成功後在 `meta` 寫 `open_state=open`，正常 `close()` 寫回 `closed`；`_open` 僅在 `-wal` 非空、`open_state` 不是 `closed`（異常結束）、或 `last_full_check` 缺漏／無法解析／無時區／在未來／已滿 7 天時才跑 `PRAGMA quick_check`，其餘只跑既有 schema／`table_info` 檢查。開啟旗標寫入失敗時回滾並退回跑 `quick_check`；關閉旗標寫入失敗則旗標維持 `open`，下次開啟必跑。失敗一律走既有 `.bad-*` 保留與重建、同一錯誤碼 `kline_store_unavailable`。先以兩個損毀情境在舊程式確認通過（`beff3ceb`），再加旗標殘留／`-wal` 非空／旗標寫入失敗／損毀四種情境與邊界測試；三種刻意破壞皆被抓到（13／2／3 個失敗）。取捨：正常關閉且 WAL 為空期間發生的損毀，改由定期完整檢查（最多 7 天）發現。 | 放寬後 `python tools/bench_kline_open.py --repeat 5 --sizes 10,200,1024,2350`（同機、暖快取、中位數），正常關閉後開啟／異常結束後開啟／單獨 quick_check：16.4 MiB 6.8／61.4／59.4 ms；202.6 MiB 7.0／661.3／743.2 ms；1,027.7 MiB 7.1／3,061.8／3,064.7 ms；2,350.3 MiB 8.9／13,615.5／11,472.7 ms（單獨重跑 `--sizes 2350`；首次與測試同時執行為 17.1／16,912.5／6,612.5 ms。此大小已超出暖快取能保留的範圍，完整檢查路徑在兩次間浮動 6.6–16.9 s，正常關閉後開啟則穩定在 9–17 ms）。`python -m unittest tests.test_kline_store` 23 OK；`tools/affected_tests.py` 列出的 167 個模組逐一執行，僅 `test_trading_acceptance_combinations`、`test_trading_installer_guard` 兩個既知的本機環境失敗（P1–P4、P9 已在未修改樹上確認）。放寬前（#256）：`python tools/bench_kline_open.py --repeat 5 --sizes 10,200,1024,2350`（Python 3.13.11、SQLite 3.54.0、暖快取、中位數）：16.4 MiB 開啟 39.5 ms（quick_check 38.4 ms，97%）；202.6 MiB 477.8 ms（476.7，100%）；1,027.7 MiB 2,427.3 ms（2,401.3，99%）；2,350.3 MiB 7,966.5 ms（7,150.7，90%）。佔比顯著：owner 本機模擬環境 K 線庫已約 2.46 GB，每次開啟約 8 秒（冷快取只會更慢）。 |

Real-App visual check: 不適用（無 UI 變更）。
本階段不更動 [PROJECT_STATE](../agent/PROJECT_STATE.md) 與驗收分數；不建立 Release 或 tag。

# OPT-1：效能與維護性優化規格書

Status: IN PROGRESS (per-phase status in the Rollout section). P7: NOT STARTED, awaiting owner approval.
Audience: implementing agent. 觀察基準：`main` @ `d6c8d10f`，2026-11-20。
本文件的「現況」皆來自讀程式碼與 grep，**尚未實測效能**；所有速度目標都要先量測再主張。
範本對照：[TEMPLATE.md](TEMPLATE.md)；工作規則沿用 [m1-implementation-spec.md](m1-implementation-spec.md) §0。

## Problem

一次抽樣程式碼檢視（回測、指標、交易檢視層、專案結構）找到下列可優化處。排序依「風險由低到高、
投入產出比由高到低」。每個階段（P0–P7）各一個 PR，可獨立交付與回退。

| 階段 | 主題 | 風險 | 是否碰 G3 |
|---|---|---|---|
| P0 | 專案整潔（ignore 規則、Git 物件庫） | 極低 | 否 |
| P1 | 靜默例外審計（`except …: pass`） | 低 | 否（G3 檔跳過） |
| P2 | `views.snapshot` 重複掃描 | 中 | 否 |
| P3 | KD 指標視窗極值 O(N×period)→O(N) | 低 | 否 |
| P4 | SQLite 開檔樣板收斂 | 低 | 否（G3 檔跳過） |
| P5 | Ruff 規則擴充（非凍結碼） | 低 | 否 |
| P6 | 超長函式拆分 | 中 | 否（凍結檔跳過） |
| P7 | 回測引擎查找與驗證拆分 | **高** | **是，需 owner 明確核准** |

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

## Safety constraints (live trading disabled, G3, OOS/budget)

沿用 [TEMPLATE.md](TEMPLATE.md) 的安全章節全文，另加：
- 本規格每個階段都不得新增或改動任何真實下單路徑；Decimal 金額運算不得改成 float。
- P1 的記錄內容受隱私限制（見上）；OOS／final-holdout 資料不得出現在任何記錄或基準資料中。
- 所有 timeout（Paper 30 s、smoke 40 s、每個 job 15 分鐘）與 fail-closed 驗證保持原樣。
- P0 不做不可逆刪除；`git gc` 不使用 `--prune=now`。
- G3 檔案（見 [CONTRIBUTING.md](../CONTRIBUTING.md)）除 P7 且經 owner 核准外一律不編輯。

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
| P7 | `tests/test_r7_characterization.py`、回測相關全套 | 新舊實作同資料集 hash 完全相等；G3 pins／profile 測試 |

UI 無新增畫面，故不要求新的 accessibility walk；若 P2/P6 動到 UI 呼叫端，需跑既有 UI 快照測試且不得變更基準。

## Rollout/Verification status

順序：P0 → P1 → P3 → P2 → P4 → P5 → P6 →（P7，待核准）。P3 排在 P2 前，因為它不碰 G3 且等價性最容易證明；
P2 需先有量測基準，故在 P1 之後。每階段一個 PR、可單獨回退（revert 該 PR）。每個 PR 經獨立 QA（aiworkflow-qa）
驗收、CI 全綠後才合併；controller 不得自行驗收自己的實作。
Implementation／Verification（逐階段，只記錄實際跑過的指令與結果）：

| 階段 | Implementation | Verification |
|---|---|---|
| P0 | `.gitignore`：`/.tmp*/` 改為 `/.tmp*`（同時擋檔案），新增 `/tmp*/`；`/t/` 與 `*.log`（含 `t2-*.log`、`shioaji.log`）原本已忽略，未重複加入。未刪除任何檔案；worktree 清單寫在 PR 說明，是否清除由 owner 決定。 | 主 checkout `git status --short` 原為 174 筆；以新規則模擬（`git ls-files -o --directory --exclude-standard --exclude-from=<新 .gitignore>`）剩 13 筆，`.tmp-*` 與 `tmp*/` 全數不再列出。`git gc`（預設 prune 期限）exit 0；`git count-objects -vH` 前：count 267、packs 4、size-pack 113.24 MiB、prune-packable 242、garbage 77；後：count 0、packs 2、size-pack 108.34 MiB、prune-packable 0、garbage 0。`test_repo_layout`、`test_docs_layering`、`test_dev_setup`、`test_layer_gate`、`test_quality_gate` OK；`check_layers.py` 0 findings；`ruff check` passed。 |
| P1 | AST 掃描 68 處 `except …: pass`；G3 7 處不碰。其餘 61 處分類（表格見 PR）：加記錄 4 處（`MarketTerminalService._try`、`SectorMonitor.on_round`、`SectorMonitor._flow_alert`、`SectorPoller._run`，只記 DomainError 代碼或例外類別名稱，行為不變）；預期無害保留 35；fail-closed／對帳／憑證／下單路徑「已審查，保留」17；桌面 GUI 程序無任何 logging handler（加記錄無可觀測性）保留 5。 | 新測試先在舊實作確認行為部分通過（log 斷言如預期失敗），改後 `python -m unittest tests.test_m5_monitor`、`tests.test_market_terminal_service` OK；`tools/affected_tests.py` 選出的 164 模組逐一執行（`PYTHONPATH=tests`）162 OK，`test_trading_acceptance_combinations`（Windows 檔案鎖 PermissionError）與 `test_trading_installer_guard`（偵測到本機正在執行的 MarkAuto）在未修改的 P0 樹上同樣失敗，屬主機環境；`check_layers.py` 0、`check_trading_architecture.py` 0、`ruff check` 通過。 |
| P3 | `kd` 以兩個單調 deque（只彈出嚴格較小的高點／較大的低點，保留同值中最早者，與 `max`/`min` 回傳同一個 Decimal）取代每步 `max`/`min`；`None` 重置、驗證、暖機、`MAX_WINDOW_WORK`、`FORMULA_VERSION`、bollinger 皆未改。`indicators.py` 原始碼雜湊綁入分析封包，故 `ui_operations_golden.json` 恰 23 個雜湊葉以獨立 fixture-only commit 重生（`docs/analysis/opt1_p3_golden_changes.md`），`test_golden_metadata` 兩個摘要同步重釘。 | 等價測試（舊迴圈凍結副本為 oracle，`str()` 逐值比對）在舊實作先通過、改後通過；破壞同值順序的 mutation 被抓到。實測（Python 3.13.11，5 次中位數）：N=10k/period 9 0.0759→0.0674 s（1.1×）、N=100k/9 0.8456→0.7730 s（1.1×）、N=50k/100 0.8444→0.3572 s（2.4×）、N=5k/1000 0.4442→0.0453 s（9.8×）；預設 period 9 提升不顯著。`prepush.ps1 -Tests` 通過；`affected_tests.py` 選出 255 模組逐一執行 251 OK，`test_e1_qualification`（無 symlink 權限）、`test_paper_diagnostics`、`test_test_group`（WinError 32 檔案占用）、`test_trading_installer_guard` 在未修改樹上同樣失敗，屬主機環境；`test_layer_gate`、`test_quality_gate`、`test_docs_layering`、`check_layers.py` 通過。 |
| P2 | NOT STARTED | NOT RUN |
| P4 | NOT STARTED | NOT RUN |
| P5 | NOT STARTED | NOT RUN |
| P6 | NOT STARTED | NOT RUN |
| P7 | NOT STARTED（需 owner 明確核准編輯 `quantlab/backtest.py`） | NOT RUN |

Real-App visual check: 不適用（無 UI 變更）。
本階段不更動 [PROJECT_STATE](../agent/PROJECT_STATE.md) 與驗收分數；不建立 Release 或 tag。

# M3-9 股票信號研究：有限交付紀錄

日期：2026-11-03。基準：`c447ba4da6f7dcd356a73f4b1f3cdd5b1b397e45`。
範圍依 [ADR 0007](../adr/0007-stock-signal-research-scope.md)。
狀態：信號 TRAINING 基礎已實作；完整 M3-9、股票 E1／E2／交易建成尚未完成。
正式委託硬性關閉；沒有實際市場、券商登入、憑證或 OOS 驗證。

## 交付契約

- `Bar`、`Signal` 接受明確的 TWSE／TPEX 數字代號及正有限 Decimal 信號價；
  股票日盤限定。TMF 格式、整數跳動及序列化欄位不變。
- G3 只改 `core.py` 與 `backtest.py`。`strategies.py` 不必更改，仍直接使用同一
  `generate_signals`。`validate_contract`、`Instrument`、`Fill` 及 Paper 仍只接納 TMF。
  原期貨回測在帳務開始前拒絕股票；不把股票套進乘數 10 或期貨保證金。
- `runtime.stock_signal_research.research_stock_signals` 以既有官方快取唯讀驗證器取得
  完整、至少五年、已完成的日線。每個決策日從固定起點重建當日已知的完整調整歷史。
  未知資料、完整日曆／事件負證據缺漏、來源變更、取消及期限到期皆不回傳結果。
- 股票目標固定 LONG_ONLY，但未改寫共用信號函式的狀態與負信號。
  結果只含 TRAINING 信號目標及其來源、資料、策略身分；沒有 PnL、E1、E2 或
  啟動資格。不新增 AI 工具、提示、journal 寫入或外部下載路徑。
- TPEx 型別可表示，不等於官方資料已合格；本入口仍直接拒絕 TPEx，直到可驗證的
  官方事件負證據另行完成。測試只用明確標示的合成資料與官方形狀文件。

## 來源與相容性

CONTRIBUTING 明確要求新來源另立 current profile。此次新增
`STOCK_SIGNAL_PROFILE_V1`，保留原有 30 個凍結 profile 區塊逐位元組不變。
新執行的來源指紋誠實反映 G3 修改；不改寫舊結果或讓新來源冒充舊來源。

測試在修改核心前固定六組合成日 K 的結果行為、策略 hash 與候選 fingerprint。
全部通過。比較僅排除來源／Python 執行版本及由來源衍生的 run hash；成交、成本、
帳務、指標、訊號、拒絕及其他 manifest 內容仍完整納入行為 hash。
新來源身分另由 exact LF／CRLF profile 與 G3 Git blob 測試驗證。

歷史測試需要舊來源的部分，使用新增的 `m3_stock_prior_sources` 壓縮封存。
既有 frozen fixture 不改寫。封存 SHA-256、目前來源 SHA-256 及一位元組竄改拒絕
均有測試；這是歷史測試資料，不是產品執行時重新標記證據的機制。

## 驗證

本機 Python 3.12.14。Ruff 0.16.10 由專案 hash-lock 安裝到獨立虛擬環境；
沒有修改系統環境。下列指令從工作樹根目錄執行：

- `ruff check .`：exit 0。
- `ruff format --check .`：exit 0。
- `python -m compileall -q quantlab desktop_app tools tests desktop.py`：exit 0。
- 所有 tracked Python 以 `ast.parse(..., feature_version=(3,11))` 掃描：exit 0。
  這只是 Python 3.11 語法檢查，不是原生 3.11 執行結果。
- `python tools/quality_gate.py`：exit 0，零 finding。
- `python tools/check_layers.py`：exit 0，零 finding。
- `python tools/check_trading_architecture.py`：exit 0，零 violation。
- `git diff --check`：exit 0。
- `python -m unittest discover -s tests -p '*profile.py'`：91 tests，exit 0。
- `python -m unittest discover -s tests -p test_saved_candidate_pool.py`：57 tests，exit 0。
- `python -m unittest discover -s tests -p test_research.py`：51 tests，exit 0。

逐一以 `python -m unittest discover -s tests -p <module>.py` 執行且 exit 0：

| 模組 | 案例數 |
|---|---:|
| test_core | 8 |
| test_backtest | 29 |
| test_strategies | 6 |
| test_data | 19 |
| test_core_scalar_parity | 4 |
| test_core_scalar_snapshot_fixture | 1（637 個固定快照） |
| test_m3_signal_identity | 5 |
| test_m3_stock_signal_research | 12 |
| test_m3_stock_profile | 4 |
| test_m3_prefix_consistency | 7 |
| test_m3_candidate_intake | 27 |
| test_m3_stage_matrix | 2 |
| test_m3_signal_research | 30 |
| test_official_daily_source | 37 |
| test_daily_signal_source_refresh | 7 |
| test_docs_layering | 8 |
| test_repo_layout | 29 |
| test_paper | 59 |
| test_layer_gate（登記後） | 21 |

完整套件依作業規則由整合分支執行一次，本子分支未重跑全套。
GitNexus 工具及 AGENTS 索引未在此環境提供，因此未聲稱已執行 GitNexus impact。
已以文字／AST 及相依測試檢查 Bar、Signal、TMF 回測、研究 campaign、Paper、
shared signal bridge 與 source-profile 消費者。

## 待整合與未通過項目

- `test_layer_gate` 初次為 20 pass／1 fail，原因是新模組尚未登記。後續依指示執行
  `python tools/repin_baselines.py --only inventory --write`，只新增一列並以獨立
  baseline commit 保存；重跑 21 tests 全部通過，dry-run 顯示 up-to-date。
- 初次共用 Qt 環境缺少 jwt／cryptography，來源應用 smoke 與
  `test_desktop_market_smoke` 的來源 smoke 案例因 `ModuleNotFoundError` 失敗；
  同環境未修改的 main 也相同。後續在獨立 stock tools 虛擬環境完成官方
  `tools/install_desktop_auth.py` 的 hash-verified 依賴安裝，以及 Qt CI hash-lock
  安裝，全部 exit 0。離線 `_auth_smoke_dependencies()` 通過，network_used=False。
  已知此執行環境本機 socket/IPC 權限有 EPERM 限制，依指示不重試已拒絕的
  socket／提權路徑，因此完整來源應用啟動仍 NOT PASSED；不聲稱 Windows、LOCAL／
  fake BROKER_SIMULATION 驗收通過。
- CI、正式 PR、獨立整合驗證尚待父任務處理；本工作未 push、merge 或建立 Release。
- 若與獨立 E1／OOS 一致性變更整合，必須依合併後實際 `research.py`／`core.py`／
  `backtest.py` 產生最終 current profile，不能直接把任一分支的來源 tuple 當成組合證據。
- 不變更 PROJECT_STATE 或 230/300 驗收分數。短波／長波 UI 及股票交易建成仍須
  有權威 E1、股票 E2 與所需官方資料後才可解鎖。

## 獨立審查

獨立唯讀審查確認原始三個來源封存與基準 commit 完全相同，未找到此有限產品範圍的
安全阻擋。審查指出原小數價 fixture 對突破與波動收斂家族沒有觸發信號；已改為確實
觸發五家族與 AST 的小數價序列，加入非空斷言，再逐前綴比較。原日 K 歷史行為
基準完全不動。修正後 12 個股票測試及 4 個 profile 測試重新通過。

## 發布範圍與隱私檢查

本次發布不修改或上傳 `docs/agent/IMPLEMENTATION_CONTRACTS.md`，保留 main 原始位元組。
該檔案先前整檔上傳受限，本分支不重試該操作；上述 ADR 與本報告已記錄本次必要契約。
盤點文件的兩處歷史使用者絕對路徑改成工作樹的中性描述，保留索引與來源核對的技術意義。
發布使用從 main 基準建立的乾淨提交鏈，ADR、功能、來源 profile 與 inventory baseline
各自獨立，不推送先前的未整理本機歷史。檢查包含所有變更檔案的完整內容及新壓縮
歷史 fixture 的解壓來源，而不僅是新增行；不讀取實際 OOS 資料。

乾淨發布樹再次通過 Ruff lint／format、compileall、1273 個 tracked Python 的 3.11
語法掃描、quality／layer／trading architecture 閘門、inventory dry-run 及 diff 空白檢查。
另重跑 docs layering（8）、repo layout（29）、layer gate（21）、M3 signal identity（5）、
stock signal research（12）與 stock profile（4），全部 exit 0。獨立完整內容檢查未在
其餘發布內容發現憑證、私鑰、個人聯絡資訊或不必要的個人路徑；合成拒絕測試中的
example.invalid、fixture-user 與假 token 字串保留，不能把它們當成真實憑證。

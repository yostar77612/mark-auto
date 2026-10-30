# 分層式重構盤點報告（R0）

本文件是 [分層式重構規格書](07_LAYERED_REFACTOR_SPEC.md) 的逐檔盤點，提供後續搬檔、分層閘門與責任拆分的依據。只改結構、不改行為；不增加功能或依賴，不新增下單路徑，真實交易維持永久停用。

## 1 範圍、基線與方法

- 盤點日期：2026-10-29；程式基線：`main@7b59809`。盤點工作樹為 `claude/refactor-a-inventory`、`HEAD=f20de6c4aa799268e11c4ac1067cf76d43af5f42`；`git diff --name-only 7b59809 HEAD` 只有規格文件 `07_LAYERED_REFACTOR_SPEC.md`，因此程式行號仍對應基線。07 的歷史基線敘述不覆寫本次控制者指定的基線。
- 範圍：`git ls-files '*.py'`，排除路徑前綴 `tests/`、`archives/`，R0 基線共 **310 檔**；R1 新增 `tools/check_layers.py` 後為 **311 檔**。包含套件初始化檔、打包 hook、開發工具及 `docs/script samples/strategy_sample.py`；不是只盤點產品入口可達的檔案。
- 本版完成 R0 盤點：第 2–6 節的逐檔歸屬、相依違規、匯入副作用、G3 例外與 PR 順序，加上第 7–10 節的共用、死碼、過度防禦與大檔拆分清單。R1 實作與執行方式見 6.1；完整 PR A 仍需獨立 QA、全測試與打包驗收。
- 在作業系統暫存目錄 `%TEMP%/r0-slice1-inventory/` 使用一次性 Python 腳本：由 Git 取得檔案集合，讀取 UTF-8 原始碼、計算 LF 數量（等同 `wc -l`），以 `ast.parse`、`ast.walk` 擷取匯入及定義；輸出表格與違規。腳本與中間 JSON 均不納入版本控制，不 import／執行產品模組。分層、目標與例外是閱讀模組責任、定義及匯入後的人工判定，不由檔名或匯入數量自動推論。
- 匯入解析涵蓋 `import`、`from ... import ...`、相對匯入、別名、函式內匯入與條件／型別檢查區塊。先以受追蹤模組表解析實際子模組；`from quantlab import strict_json` 解析為 `quantlab.strict_json`，匯入符號則歸到宣告匯入的模組。每個 `(path, line, imported module, rule)` 記一筆，同一敘述的多個符號不重複計數；不同位置的同模組匯入分別保留。
- 第 3 節是 **3.1 的模組相依清單**，不是完整副作用或動態執行掃描。一般標準函式庫匯入不直接算跨層邊；例如 SQLite 實際連線、讀檔、時鐘呼叫仍須按責任拆分，不能因沒出現在清單就當作允許。`importlib` 字串、callback 註冊與 re-export 的間接傳遞不併入 145 筆；第 3.2、4 節補充已確認的行為。既有交易閘門的 IO、SDK 與動態載入限制全部保留。
- GitNexus 綁定目前工作樹的絕對路徑 `C:/Users/Mark/Desktop/Mark auto`，排除同名舊測試工作樹。已執行 `node .gitnexus/run.cjs status`：CLI 未讀到 current commit，顯示 stale；但 `.gitnexus/meta.json` 的 `lastCommit` 與 `git rev-parse HEAD` 都是上述完整 SHA，索引時間為 `2026-10-29T07:18:24.291Z`，MCP 列表也指向此索引。本次依這個交叉確認使用現有索引，沒有下載 extension 或重建索引。首次同名查詢不採為本報告證據。

### 1.1 分層判定與目標解讀

層名稱沿用 3.1，另外明列 `tooling`，不把工具誤當成 runtime 的第七層。同層模組可相依；`ports` 是 application 所有的契約，表中統一記為 `application`。Infrastructure 可以引用 `quantlab/trading/ports/`，不能因為服務模組也含某個 DTO 或常數就匯入整個 application 服務。Presentation 可讀 domain 值與呼叫 application，但不能直接依賴 infrastructure、composition 或外部 SDK。Shared 只依賴標準函式庫與其他 shared，不反向匯入產品層。

混合模組按應保留的主要責任歸層，違規照列，不藉改成 composition 消除問題。例如 `quantlab/desktop_runtime.py:1219` 的 `JobManager` 屬 application；同檔 `CredentialVault`／`BackupManager` 的 IO 是待拆責任。`desktop_ui.py:1284` 混入 worker 執行，但整檔仍以 presentation 盤點。`desktop_market_layout.py:67` 的 `LayoutStore` 是 infrastructure。`quantlab/capital_scenario.py:49` 含 deadline 協調，因此屬 application，不能標成無時鐘的純 domain。

Composition 包含根目錄 launchers、桌面 bootstrap 與既有 `quantlab/trading/runtime/` 組裝／process／IPC 支援範圍（不是准許其他服務任意移入該範圍）。`desktop_pages/mount.py:11` 僅掛載 UI 頁面，仍是 presentation。`tools/`、`packaging/`、獨立 smoke 與範例腳本均是 tooling；runtime 模組不得反向依賴 tooling，只有 composition 的顯式 smoke 入口可組裝它。

目標路徑須區分 B 的整檔搬移與 C/D/E 的責任抽取，不代表當下已完成分層；所有既有檔案的整檔搬移均在 B 完成。研究套件採 **`quantlab/research_core/`**，保留 `quantlab/research.py` 的模組身份；其子目錄使用 `domain/`、`application/`、`ports/`、`adapters/`。依 R4，E 只對已列違規或大於 600 行的研究檔案抽取責任，表內研究目標是抽取後的新落點，不是 E 的整檔搬移清單；無觸發者留原路徑。G3 依擁有者第 5 節決定可搬移及拆分，產品行為與歷史 producer profile bytes 必須不變。ChatGPT 非 UI 新抽出服務／port 使用 `quantlab/assistant/application/`，實作使用 `quantlab/assistant/adapters/chatgpt/`；G3 auth/provider 本體於 B 純搬至該 adapter 目錄的 `auth.py`／`provider.py`，D 再依責任拆分。

桌面元件採 `desktop_app/shell/`、`features/<功能>/`、`components/`、`strings/`；所有 `quantlab/trading/` 檔案保持現有路徑。表中 shared 字串目錄是 3.2 明定的例外，雖在 `desktop_app/strings/`，不因此依賴 PySide6。尚未拆開的檔案只列一個主要落點；slice 2 再列拆分後各責任的子模組。

## 2 逐檔分層與目標路徑

共 311 列：domain 29、application 57、infrastructure 41、presentation 97、composition 21、shared 8、tooling 58（含 R1 新增閘門）。表內行數是包含空白、註解的實體換行數，B 修改的列已更新至本輪工作樹；其他來源定位仍是 R0 基線證據；備註的來源定位是定義／匯入證據，不是宣稱該行涵蓋整檔所有責任。

| path | lines | layer | target path | note |
|---|---:|---|---|---|
| `desktop.py` | 430 | composition | `desktop.py` | 啟動入口；C/D 抽出非 launcher 組裝至 desktop_app/bootstrap.py；`_prepare_startup_workspace`，`desktop.py:38` |
| `desktop_accessibility.py` | 150 | presentation | `desktop_app/shell/accessibility.py` | 語意名稱與鍵盤導覽；`semantic_name`，`desktop_accessibility.py:25` |
| `desktop_automatic_backup.py` | 155 | presentation | `desktop_app/features/settings/automatic_backup.py` | 備份設定 UI，直接依賴 adapter；匯入違規見第 3 節；`AutomaticBackupPanel`，`desktop_automatic_backup.py:9` |
| `desktop_capital_scenario.py` | 51 | application | `desktop_app/features/capital_scenario/worker.py` | worker 用例混入 UI；B 先純搬，D 抽取核心責任；匯入違規見第 3 節；`execute`，`desktop_capital_scenario.py:13` |
| `desktop_chart_memory.py` | 96 | presentation | `desktop_app/features/market/chart_memory.py` | 記憶體圖表偏好；`ChartMemory`，`desktop_chart_memory.py:6` |
| `desktop_chart_popout.py` | 190 | presentation | `desktop_app/features/market/chart_popout.py` | 唯讀圖表浮窗；`save_position`，`desktop_chart_popout.py:11` |
| `desktop_charts.py` | 765 | presentation | `desktop_app/components/charts.py` | Qt 圖表；直接引用持久化 drawings 模組；匯入違規見第 3 節；`_paint_drawings`，`desktop_charts.py:25` |
| `desktop_chatgpt_auth.py` | 881 | infrastructure | `quantlab/assistant/adapters/chatgpt/auth.py` | OAuth、DPAPI 與 JWT adapter；匯入違規見第 3 節；`AuthError`，`desktop_chatgpt_auth.py:51` |
| `desktop_chatgpt_provider.py` | 1460 | infrastructure | `quantlab/assistant/adapters/chatgpt/provider.py` | ChatGPT HTTP、stream 與 receipt adapter；匯入違規見第 3 節；`PlanError`，`desktop_chatgpt_provider.py:68` |
| `desktop_chatgpt_states.py` | 63 | presentation | `desktop_app/features/assistant/states.py` | 固定連線狀態文案；`outcome_state`，`desktop_chatgpt_states.py:20` |
| `desktop_chatgpt_ui.py` | 1462 | presentation | `desktop_app/features/assistant/connection.py` | Qt 連線 UI 混合 OAuth 及 provider 控制；匯入違規見第 3 節；`_ref`，`desktop_chatgpt_ui.py:119` |
| `desktop_expiry_inputs.py` | 112 | presentation | `desktop_app/components/expiry_inputs.py` | 到期日輸入元件與資料讀取混合；匯入違規見第 3 節；`ExpiryPicker`，`desktop_expiry_inputs.py:10` |
| `desktop_forms.py` | 1361 | presentation | `desktop_app/components/forms.py` | 研究與 paper 表單；C 按責任拆分；匯入違規見第 3 節；`number`，`desktop_forms.py:65` |
| `desktop_help.py` | 200 | presentation | `desktop_app/components/help.py` | 漸進提示與展開狀態；`help_button`，`desktop_help.py:29` |
| `desktop_icon.py` | 14 | presentation | `desktop_app/components/icon.py` | Qt artwork 載入；`application_icon`，`desktop_icon.py:9` |
| `desktop_market.py` | 1314 | presentation | `desktop_app/features/market/dashboard.py` | 行情畫面混合資料投影；匯入違規見第 3 節；`_identity`，`desktop_market.py:66` |
| `desktop_market_layout.py` | 114 | infrastructure | `quantlab/research_core/adapters/market_layout.py` | LayoutStore 寫檔；B 搬核心 adapter；`preset`，`desktop_market_layout.py:17` |
| `desktop_market_workspace.py` | 324 | presentation | `desktop_app/features/market/workspace.py` | 可移動 UI panel 與 LayoutStore 使用者；匯入違規見第 3 節；`_button`，`desktop_market_workspace.py:17` |
| `desktop_order_lines.py` | 155 | presentation | `desktop_app/features/paper/order_lines.py` | 紙上委託線與手勢投影；`tick_price`，`desktop_order_lines.py:12` |
| `desktop_pages/__init__.py` | 13 | presentation | `desktop_app/shell/pages.py` | 頁面／presenter 與顯示輔助：`__init__`；`desktop_pages/__init__.py:1` |
| `desktop_pages/app_header.py` | 213 | presentation | `desktop_app/shell/app_header.py` | 頁面／presenter 與顯示輔助：`app_header`；`_CloseWatcher`，`desktop_pages/app_header.py:17` |
| `desktop_pages/assistant.py` | 216 | presentation | `desktop_app/features/assistant/assistant.py` | 頁面／presenter 與顯示輔助：`assistant`；`AssistantPanel`，`desktop_pages/assistant.py:19` |
| `desktop_pages/assistant_completion.py` | 161 | presentation | `desktop_app/features/assistant/assistant_completion.py` | 頁面／presenter 與顯示輔助：`assistant_completion`；匯入違規見第 3 節；`reference_catalog`，`desktop_pages/assistant_completion.py:21` |
| `desktop_pages/assistant_details.py` | 154 | presentation | `desktop_app/features/assistant/assistant_details.py` | 頁面／presenter 與顯示輔助：`assistant_details`；`redacted`，`desktop_pages/assistant_details.py:22` |
| `desktop_pages/assistant_manifest.py` | 144 | presentation | `desktop_app/features/assistant/assistant_manifest.py` | 頁面／presenter 與顯示輔助：`assistant_manifest`；`field_label`，`desktop_pages/assistant_manifest.py:12` |
| `desktop_pages/assistant_models.py` | 163 | presentation | `desktop_app/features/assistant/assistant_models.py` | 頁面／presenter 與顯示輔助：`assistant_models`；`advertised_efforts`，`desktop_pages/assistant_models.py:12` |
| `desktop_pages/assistant_permissions.py` | 77 | presentation | `desktop_app/features/assistant/assistant_permissions.py` | 頁面／presenter 與顯示輔助：`assistant_permissions`；`ResearchPermission`，`desktop_pages/assistant_permissions.py:17` |
| `desktop_pages/assistant_runtime.py` | 208 | application | `desktop_app/features/assistant/worker.py` | 對話 worker 與 process 協調，沒有 Qt 物件；B 已純搬至 desktop_app，D 抽取核心責任；匯入違規見第 3 節；`host_context`，`desktop_pages/assistant_runtime.py:21` |
| `desktop_pages/async_status.py` | 78 | presentation | `desktop_app/components/async_status.py` | 頁面／presenter 與顯示輔助：`async_status`；`AsyncStatus`，`desktop_pages/async_status.py:12` |
| `desktop_pages/backtest.py` | 284 | presentation | `desktop_app/features/backtest/backtest.py` | 頁面／presenter 與顯示輔助：`backtest`；匯入違規見第 3 節；`BacktestPage`，`desktop_pages/backtest.py:21` |
| `desktop_pages/backtest_summary_card.py` | 115 | presentation | `desktop_app/features/backtest/backtest_summary_card.py` | 頁面／presenter 與顯示輔助：`backtest_summary_card`；`ReportSummaryCard`，`desktop_pages/backtest_summary_card.py:13` |
| `desktop_pages/backup_inspection.py` | 85 | presentation | `desktop_app/features/settings/backup_inspection.py` | 頁面／presenter 與顯示輔助：`backup_inspection`；匯入違規見第 3 節；`BackupInspectionPanel`，`desktop_pages/backup_inspection.py:12` |
| `desktop_pages/bindings.py` | 276 | presentation | `desktop_app/shell/bindings.py` | 頁面／presenter 與顯示輔助：`bindings`；`StateField`，`desktop_pages/bindings.py:4` |
| `desktop_pages/chatgpt_reconciliation.py` | 199 | presentation | `desktop_app/features/assistant/chatgpt_reconciliation.py` | 頁面／presenter 與顯示輔助：`chatgpt_reconciliation`；`ReconciliationDialog`，`desktop_pages/chatgpt_reconciliation.py:9` |
| `desktop_pages/command_palette.py` | 207 | presentation | `desktop_app/components/command_palette.py` | 頁面／presenter 與顯示輔助：`command_palette`；`_Filter`，`desktop_pages/command_palette.py:10` |
| `desktop_pages/compare.py` | 457 | presentation | `desktop_app/features/compare/compare.py` | 頁面／presenter 與顯示輔助：`compare`；匯入違規見第 3 節；`ComparePage`，`desktop_pages/compare.py:33` |
| `desktop_pages/compare_equity.py` | 269 | presentation | `desktop_app/features/compare/compare_equity.py` | 頁面／presenter 與顯示輔助：`compare_equity`；`series_pen`，`desktop_pages/compare_equity.py:25` |
| `desktop_pages/compare_table.py` | 161 | presentation | `desktop_app/features/compare/compare_table.py` | 頁面／presenter 與顯示輔助：`compare_table`；`safe_text`，`desktop_pages/compare_table.py:19` |
| `desktop_pages/connection_test.py` | 146 | presentation | `desktop_app/features/assistant/connection_test.py` | 頁面／presenter 與顯示輔助：`connection_test`；匯入違規見第 3 節；`ConnectionTest`，`desktop_pages/connection_test.py:15` |
| `desktop_pages/data.py` | 290 | presentation | `desktop_app/features/data/data.py` | 頁面／presenter 與顯示輔助：`data`；`DataPage`，`desktop_pages/data.py:15` |
| `desktop_pages/data_gaps.py` | 109 | presentation | `desktop_app/features/data/data_gaps.py` | 頁面／presenter 與顯示輔助：`data_gaps`；`segment_text`，`desktop_pages/data_gaps.py:17` |
| `desktop_pages/design.py` | 64 | presentation | `desktop_app/components/design.py` | 頁面／presenter 與顯示輔助：`design`；`card`，`desktop_pages/design.py:10` |
| `desktop_pages/diagnostics.py` | 76 | presentation | `desktop_app/features/settings/diagnostics.py` | 頁面／presenter 與顯示輔助：`diagnostics`；`snapshot_for_state`，`desktop_pages/diagnostics.py:11` |
| `desktop_pages/download_import.py` | 66 | presentation | `desktop_app/features/data/download_import.py` | 頁面／presenter 與顯示輔助：`download_import`；`DownloadImportControls`，`desktop_pages/download_import.py:10` |
| `desktop_pages/equity.py` | 147 | presentation | `desktop_app/components/equity.py` | 頁面／presenter 與顯示輔助：`equity`；`EquityPlot`，`desktop_pages/equity.py:15` |
| `desktop_pages/error_guidance.py` | 82 | presentation | `desktop_app/components/error_guidance.py` | 頁面／presenter 與顯示輔助：`error_guidance`；`next_step`，`desktop_pages/error_guidance.py:27` |
| `desktop_pages/host.py` | 230 | presentation | `desktop_app/shell/host.py` | 頁面／presenter 與顯示輔助：`host`；`PageState`，`desktop_pages/host.py:8` |
| `desktop_pages/idea_research.py` | 617 | presentation | `desktop_app/features/strategy/idea_research.py` | 頁面／presenter 與顯示輔助：`idea_research`；`open_url`，`desktop_pages/idea_research.py:83` |
| `desktop_pages/job_progress.py` | 181 | presentation | `desktop_app/components/job_progress.py` | 頁面／presenter 與顯示輔助：`job_progress`；`JobProgress`，`desktop_pages/job_progress.py:19` |
| `desktop_pages/log_table.py` | 79 | presentation | `desktop_app/features/settings/log_table.py` | 頁面／presenter 與顯示輔助：`log_table`；`choose_log_export`，`desktop_pages/log_table.py:14` |
| `desktop_pages/maintenance.py` | 115 | presentation | `desktop_app/features/settings/maintenance.py` | 頁面／presenter 與顯示輔助：`maintenance`；匯入違規見第 3 節；`installed_payload_root`，`desktop_pages/maintenance.py:19` |
| `desktop_pages/market.py` | 226 | presentation | `desktop_app/features/market/market.py` | 頁面／presenter 與顯示輔助：`market`；匯入違規見第 3 節；`MarketPage`，`desktop_pages/market.py:12` |
| `desktop_pages/mount.py` | 361 | presentation | `desktop_app/shell/mount.py` | 僅組合 UI 頁面，沒有 adapter 接線；屬 presentation；`mount_pages`，`desktop_pages/mount.py:11` |
| `desktop_pages/notification_log.py` | 146 | presentation | `desktop_app/shell/notification_log.py` | 頁面／presenter 與顯示輔助：`notification_log`；`safe_operation`，`desktop_pages/notification_log.py:20` |
| `desktop_pages/notifications.py` | 318 | presentation | `desktop_app/shell/notifications.py` | 頁面／presenter 與顯示輔助：`notifications`；`Toast`，`desktop_pages/notifications.py:16` |
| `desktop_pages/onboarding.py` | 217 | presentation | `desktop_app/shell/onboarding.py` | 頁面／presenter 與顯示輔助：`onboarding`；`GettingStarted`，`desktop_pages/onboarding.py:19` |
| `desktop_pages/palette_commands.py` | 67 | presentation | `desktop_app/shell/palette_commands.py` | 頁面／presenter 與顯示輔助：`palette_commands`；`register_pages`，`desktop_pages/palette_commands.py:14` |
| `desktop_pages/paper.py` | 383 | presentation | `desktop_app/features/paper/paper.py` | 頁面／presenter 與顯示輔助：`paper`；匯入違規見第 3 節；`pending_orders`，`desktop_pages/paper.py:20` |
| `desktop_pages/paper_layout.py` | 198 | presentation | `desktop_app/features/paper/paper_layout.py` | 頁面／presenter 與顯示輔助：`paper_layout`；匯入違規見第 3 節；`wrapped`，`desktop_pages/paper_layout.py:19` |
| `desktop_pages/paper_readiness.py` | 41 | presentation | `desktop_app/features/paper/paper_readiness.py` | 頁面／presenter 與顯示輔助：`paper_readiness`；匯入違規見第 3 節；`refresh_readiness`，`desktop_pages/paper_readiness.py:8` |
| `desktop_pages/paper_tabs.py` | 248 | presentation | `desktop_app/features/paper/paper_tabs.py` | 頁面／presenter 與顯示輔助：`paper_tabs`；匯入違規見第 3 節；`PnlDelegate`，`desktop_pages/paper_tabs.py:22` |
| `desktop_pages/preferences.py` | 106 | presentation | `desktop_app/features/settings/preferences.py` | 頁面／presenter 與顯示輔助：`preferences`；匯入違規見第 3 節；`disclosure_value`，`desktop_pages/preferences.py:9` |
| `desktop_pages/quick_start.py` | 87 | presentation | `desktop_app/features/onboarding/quick_start.py` | 頁面／presenter 與顯示輔助：`quick_start`；匯入違規見第 3 節；`QuickStart`，`desktop_pages/quick_start.py:12` |
| `desktop_pages/quick_start_chain.py` | 53 | presentation | `desktop_app/features/onboarding/quick_start_chain.py` | 頁面／presenter 與顯示輔助：`quick_start_chain`；`QuickStartChain`，`desktop_pages/quick_start_chain.py:4` |
| `desktop_pages/redesign_strategy_layout.py` | 362 | presentation | `desktop_app/features/strategy/redesign_strategy_layout.py` | 頁面／presenter 與顯示輔助：`redesign_strategy_layout`；`note`，`desktop_pages/redesign_strategy_layout.py:26` |
| `desktop_pages/replay_controls.py` | 142 | presentation | `desktop_app/features/paper/replay_controls.py` | 頁面／presenter 與顯示輔助：`replay_controls`；`ReplayControls`，`desktop_pages/replay_controls.py:11` |
| `desktop_pages/result_layers.py` | 201 | presentation | `desktop_app/components/result_layers.py` | 頁面／presenter 與顯示輔助：`result_layers`；`result_snapshot_lines`，`desktop_pages/result_layers.py:7` |
| `desktop_pages/result_panels.py` | 137 | presentation | `desktop_app/components/result_panels.py` | 頁面／presenter 與顯示輔助：`result_panels`；`WalkForwardResults`，`desktop_pages/result_panels.py:10` |
| `desktop_pages/result_widgets.py` | 258 | presentation | `desktop_app/components/result_widgets.py` | 頁面／presenter 與顯示輔助：`result_widgets`；匯入違規見第 3 節；`numeric`，`desktop_pages/result_widgets.py:40` |
| `desktop_pages/settings.py` | 320 | presentation | `desktop_app/features/settings/settings.py` | 頁面／presenter 與顯示輔助：`settings`；匯入違規見第 3 節；`SettingsPage`，`desktop_pages/settings.py:13` |
| `desktop_pages/settings_layout.py` | 165 | presentation | `desktop_app/features/settings/settings_layout.py` | 頁面／presenter 與顯示輔助：`settings_layout`；`open_folder`，`desktop_pages/settings_layout.py:13` |
| `desktop_pages/shortcuts.py` | 57 | presentation | `desktop_app/shell/shortcuts.py` | 頁面／presenter 與顯示輔助：`shortcuts`；`install_shortcuts`，`desktop_pages/shortcuts.py:10` |
| `desktop_pages/strategy.py` | 440 | presentation | `desktop_app/features/strategy/strategy.py` | 頁面／presenter 與顯示輔助：`strategy`；匯入違規見第 3 節；`StrategyPage`，`desktop_pages/strategy.py:13` |
| `desktop_pages/strategy_tabs.py` | 40 | presentation | `desktop_app/features/strategy/strategy_tabs.py` | 頁面／presenter 與顯示輔助：`strategy_tabs`；`strategy_tabs`，`desktop_pages/strategy_tabs.py:8` |
| `desktop_pages/views.py` | 236 | presentation | `desktop_app/shell/views.py` | 頁面／presenter 與顯示輔助：`views`；匯入違規見第 3 節；`ViewCoordinator`，`desktop_pages/views.py:14` |
| `desktop_pages/wf_wizard.py` | 368 | presentation | `desktop_app/features/walk_forward/wf_wizard.py` | 頁面／presenter 與顯示輔助：`wf_wizard`；`failure_hint`，`desktop_pages/wf_wizard.py:14` |
| `desktop_pages/widgets.py` | 160 | presentation | `desktop_app/components/widgets.py` | 頁面／presenter 與顯示輔助：`widgets`；匯入違規見第 3 節；`PanelCard`，`desktop_pages/widgets.py:29` |
| `desktop_presentation.py` | 158 | presentation | `desktop_app/components/formatting.py` | 顯示格式化混入 dataset 讀取；匯入違規見第 3 節；`display_status`，`desktop_presentation.py:62` |
| `desktop_privacy.py` | 175 | presentation | `desktop_app/components/privacy.py` | 遮罩與隱私顯示元件；`mask_money`，`desktop_privacy.py:34` |
| `desktop_recovery_smoke.py` | 265 | tooling | `desktop_app/smoke/recovery.py` | 可選打包驗證腳本，非 runtime layer；`_remaining`，`desktop_recovery_smoke.py:26` |
| `desktop_research_runtime.py` | 377 | composition | `desktop_app/research_bootstrap.py` | 既有研究 session 與 v2 視窗接線；`ResearchUnavailable`，`desktop_research_runtime.py:16` |
| `desktop_smoke/__init__.py` | 961 | tooling | `desktop_app/smoke/__init__.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`_SmokeSettingsView`，`desktop_smoke/__init__.py:11` |
| `desktop_strings.py` | 4316 | shared | `desktop_app/strings/catalog.py` | 字串查詢入口；C 依功能拆分，呼叫入口固定；`stage_error_message`，`desktop_strings.py:1726` |
| `desktop_theme.py` | 441 | presentation | `desktop_app/shell/theme.py` | QSS 與 UI 外觀套用；`load_appearance`，`desktop_theme.py:110` |
| `desktop_timeinput.py` | 205 | presentation | `desktop_app/components/timeinput.py` | 日期／時間輸入元件；`taipei_to_utc_iso`，`desktop_timeinput.py:19` |
| `desktop_tls_smoke.py` | 369 | tooling | `desktop_app/smoke/tls.py` | 可選打包 TLS 驗證腳本；`safe_path`，`desktop_tls_smoke.py:36` |
| `desktop_trading/__init__.py` | 5 | presentation | `desktop_app/features/trading/__init__.py` | 既有 v2 UI／row 投影：`__init__`；保留現行較嚴格交易閘門；`desktop_trading/__init__.py:1` |
| `desktop_trading/broker_panel.py` | 174 | presentation | `desktop_app/features/trading/broker_panel.py` | 既有 v2 UI／row 投影：`broker_panel`；保留現行較嚴格交易閘門；`BrokerPanel`，`desktop_trading/broker_panel.py:46` |
| `desktop_trading/dashboard.py` | 166 | presentation | `desktop_app/features/trading/dashboard.py` | 既有 v2 UI／row 投影：`dashboard`；保留現行較嚴格交易閘門；`DashboardWidget`，`desktop_trading/dashboard.py:16` |
| `desktop_trading/dashboard_rows.py` | 135 | presentation | `desktop_app/features/trading/dashboard_rows.py` | 既有 v2 UI／row 投影：`dashboard_rows`；保留現行較嚴格交易閘門；`StatusLight`，`desktop_trading/dashboard_rows.py:18` |
| `desktop_trading/labels.py` | 88 | presentation | `desktop_app/features/trading/labels.py` | 既有 v2 UI／row 投影：`labels`；保留現行較嚴格交易閘門；`state_label`，`desktop_trading/labels.py:74` |
| `desktop_trading/market_watch.py` | 296 | presentation | `desktop_app/features/trading/market_watch.py` | 既有 v2 UI／row 投影：`market_watch`；保留現行較嚴格交易閘門；`_Result`，`desktop_trading/market_watch.py:18` |
| `desktop_trading/market_watch_rows.py` | 133 | presentation | `desktop_app/features/trading/market_watch_rows.py` | 既有 v2 UI／row 投影：`market_watch_rows`；保留現行較嚴格交易閘門；`value_text`，`desktop_trading/market_watch_rows.py:13` |
| `desktop_trading/reconciliation_rows.py` | 29 | presentation | `desktop_app/features/trading/reconciliation_rows.py` | 既有 v2 UI／row 投影：`reconciliation_rows`；保留現行較嚴格交易閘門；`reconciliation_cells`，`desktop_trading/reconciliation_rows.py:8` |
| `desktop_trading/rendering.py` | 167 | presentation | `desktop_app/features/trading/rendering.py` | 既有 v2 UI／row 投影：`rendering`；保留現行較嚴格交易閘門；`render_tables`，`desktop_trading/rendering.py:10` |
| `desktop_trading/research_panel.py` | 78 | presentation | `desktop_app/features/trading/research_panel.py` | 既有 v2 UI／row 投影：`research_panel`；保留現行較嚴格交易閘門；`ResearchPanel`，`desktop_trading/research_panel.py:9` |
| `desktop_trading/widgets.py` | 134 | presentation | `desktop_app/features/trading/widgets.py` | 既有 v2 UI／row 投影：`widgets`；保留現行較嚴格交易閘門；`fit_available_screen`，`desktop_trading/widgets.py:29` |
| `desktop_trading/window.py` | 598 | presentation | `desktop_app/features/trading/window.py` | 既有 v2 UI／row 投影：`window`；保留現行較嚴格交易閘門；`_Operation`，`desktop_trading/window.py:32` |
| `desktop_trading/wizard.py` | 325 | presentation | `desktop_app/features/trading/wizard.py` | 既有 v2 UI／row 投影：`wizard`；保留現行較嚴格交易閘門；`StrategyWizard`，`desktop_trading/wizard.py:41` |
| `desktop_trading/workspaces.py` | 403 | presentation | `desktop_app/features/trading/workspaces.py` | 既有 v2 UI／row 投影：`workspaces`；保留現行較嚴格交易閘門；`build`，`desktop_trading/workspaces.py:38` |
| `desktop_ui.py` | 1902 | presentation | `desktop_app/shell/main_window.py` | 主視窗混合 worker dispatch；C/D 分離責任；匯入違規見第 3 節；`provider_binding_options`，`desktop_ui.py:77` |
| `desktop_ui_polish.py` | 167 | presentation | `desktop_app/shell/polish.py` | 主視窗標籤與停用提示；`DisabledHint`，`desktop_ui_polish.py:8` |
| `desktop_walk_forward.py` | 609 | presentation | `desktop_app/features/walk_forward/presenter.py` | 桌面請求與結果轉譯混合 worker；D 抽離執行責任；`_folder`，`desktop_walk_forward.py:29` |
| `docs/script samples/strategy_sample.py` | 338 | tooling | `docs/script samples/strategy_sample.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`dats_source`，`docs/script samples/strategy_sample.py:11` |
| `packaging/broker_package.py` | 181 | tooling | `packaging/broker_package.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`digest`，`packaging/broker_package.py:23` |
| `packaging/broker_probe.py` | 120 | tooling | `packaging/broker_probe.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`_output`，`packaging/broker_probe.py:16` |
| `packaging/broker_probe_runtime_hook.py` | 12 | tooling | `packaging/broker_probe_runtime_hook.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`packaging/broker_probe_runtime_hook.py:1` |
| `packaging/build_broker_portable.py` | 205 | tooling | `packaging/build_broker_portable.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`_run`，`packaging/build_broker_portable.py:23` |
| `packaging/build_manifest.py` | 82 | tooling | `packaging/build_manifest.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`sha256`，`packaging/build_manifest.py:13` |
| `packaging/clean_windows_kit.py` | 97 | tooling | `packaging/clean_windows_kit.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`digest`，`packaging/clean_windows_kit.py:16` |
| `packaging/collect_licenses.py` | 90 | tooling | `packaging/collect_licenses.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`_reject_reparse_ancestry`，`packaging/collect_licenses.py:25` |
| `packaging/desktop_regression.py` | 283 | tooling | `packaging/desktop_regression.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`digest`，`packaging/desktop_regression.py:31` |
| `packaging/early_multiprocessing_runtime_hook.py` | 14 | tooling | `packaging/early_multiprocessing_runtime_hook.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`packaging/early_multiprocessing_runtime_hook.py:1` |
| `packaging/fetch_baseline.py` | 61 | tooling | `packaging/fetch_baseline.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`fetch`，`packaging/fetch_baseline.py:23` |
| `packaging/fetch_sources.py` | 43 | tooling | `packaging/fetch_sources.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`main`，`packaging/fetch_sources.py:22` |
| `packaging/payload_inventory.py` | 92 | tooling | `packaging/payload_inventory.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`reject_alternate_streams`，`packaging/payload_inventory.py:10` |
| `packaging/qt_licenses.py` | 291 | tooling | `packaging/qt_licenses.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`reject_links`，`packaging/qt_licenses.py:77` |
| `packaging/sqlite_runtime_hook.py` | 7 | tooling | `packaging/sqlite_runtime_hook.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`packaging/sqlite_runtime_hook.py:1` |
| `packaging/validate_tls.py` | 51 | tooling | `packaging/validate_tls.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`validate`，`packaging/validate_tls.py:18` |
| `packaging/version_resource.py` | 63 | tooling | `packaging/version_resource.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`version_tuple`，`packaging/version_resource.py:14` |
| `packaging/wait_for_gates.py` | 66 | tooling | `packaging/wait_for_gates.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`api`，`packaging/wait_for_gates.py:9` |
| `quantlab/__init__.py` | 3 | shared | `quantlab/__init__.py` | 版本常數；無 IO；R4 無違規／超大觸發，原址保留；`quantlab/__init__.py:1` |
| `quantlab/__main__.py` | 110 | composition | `quantlab/__main__.py` | 研究 CLI 組裝與啟動；R4 無違規／超大觸發，原址保留；`parser`，`quantlab/__main__.py:13` |
| `quantlab/agent_manifest.py` | 107 | domain | `quantlab/agent_manifest.py` | 已投影資料的 manifest 與比較規則；R4 無違規／超大觸發，原址保留；`row_schema`，`quantlab/agent_manifest.py:23` |
| `quantlab/agent_read_tools.py` | 332 | application | `quantlab/assistant/application/read_tools.py` | 唯讀工具用例；仍直接使用 paper/reporting；E 按責任抽取；匯入違規見第 3 節；`TrainingEvidence`，`quantlab/agent_read_tools.py:51` |
| `quantlab/agent_return.py` | 107 | domain | `quantlab/agent_return.py` | 有界 JSON 回傳封套；R4 無違規／超大觸發，原址保留；`_json`，`quantlab/agent_return.py:21` |
| `quantlab/agent_skills.py` | 203 | infrastructure | `quantlab/assistant/adapters/skills.py` | 本地 skill 檔案載入；混有 session 協調；E 按責任抽取；匯入違規見第 3 節；`_name`，`quantlab/agent_skills.py:24` |
| `quantlab/agent_tool_contract.py` | 178 | domain | `quantlab/agent_tool_contract.py` | 封閉 JSON schema 與驗證詞彙；R4 無違規／超大觸發，原址保留；`validate`，`quantlab/agent_tool_contract.py:116` |
| `quantlab/agent_tools.py` | 141 | application | `quantlab/agent_tools.py` | 記憶體工具註冊與授權流程；R4 無違規／超大觸發，原址保留；`_refusal`，`quantlab/agent_tools.py:13` |
| `quantlab/analysis_contracts.py` | 363 | domain | `quantlab/research_core/domain/analysis_contracts.py` | 純分析 wire grammar；仍從 research 服務取得驗證規則；E 按責任抽取；匯入違規見第 3 節；`_fail`，`quantlab/analysis_contracts.py:42` |
| `quantlab/analysis_recovery.py` | 768 | infrastructure | `quantlab/research_core/adapters/analysis_recovery.py` | SQLite 復原日誌與作業鎖；E 按責任抽取；`_fail`，`quantlab/analysis_recovery.py:86` |
| `quantlab/analysis_recovery_windows.py` | 423 | infrastructure | `quantlab/analysis_recovery_windows.py` | Windows handle 與復原 helper；R4 無違規／超大觸發，原址保留；`_kernel`，`quantlab/analysis_recovery_windows.py:25` |
| `quantlab/assistant_chat.py` | 49 | application | `quantlab/assistant_chat.py` | 唯讀對話分派用例；R4 無違規／超大觸發，原址保留；`ChatDispatcher`，`quantlab/assistant_chat.py:10` |
| `quantlab/automatic_backup.py` | 179 | infrastructure | `quantlab/research_core/adapters/automatic_backup.py` | 備份排程與檔案實作混合；E 按責任抽取；匯入違規見第 3 節；`AutomaticBackup`，`quantlab/automatic_backup.py:28` |
| `quantlab/backtest.py` | 374 | application | `quantlab/backtest.py` | 回測執行；含來源檔雜湊，非純 domain；`_performance_metrics`，`quantlab/backtest.py:21` |
| `quantlab/backtest_summary.py` | 14 | domain | `quantlab/backtest_summary.py` | 樣本警告規則；R4 無違規／超大觸發，原址保留；`warning_keys`，`quantlab/backtest_summary.py:7` |
| `quantlab/backup_inspection.py` | 156 | infrastructure | `quantlab/research_core/adapters/backup_inspection.py` | ZIP 與備份 metadata 讀取；E 按責任抽取；匯入違規見第 3 節；`ArchiveMetadata`，`quantlab/backup_inspection.py:24` |
| `quantlab/capital_scenario.py` | 113 | application | `quantlab/capital_scenario.py` | 抽樣計算與取消／deadline 協調；使用 monotonic；R4 無違規／超大觸發，原址保留；`empty_result`，`quantlab/capital_scenario.py:19` |
| `quantlab/chart_data.py` | 285 | domain | `quantlab/chart_data.py` | OHLCV 聚合規則；R4 無違規／超大觸發，原址保留；`AggregationResult`，`quantlab/chart_data.py:28` |
| `quantlab/chart_drawings.py` | 253 | infrastructure | `quantlab/chart_drawings.py` | 圖形值物件混合 DrawingStore 檔案儲存；R4 無違規／超大觸發，原址保留；`Anchor`，`quantlab/chart_drawings.py:24` |
| `quantlab/configuration.py` | 37 | domain | `quantlab/configuration.py` | BacktestConfig 純解碼；R4 無違規／超大觸發，原址保留；`config_from_json`，`quantlab/configuration.py:4` |
| `quantlab/core.py` | 342 | domain | `quantlab/core.py` | 不可變研究資料模型與驗證；`ValidationError`，`quantlab/core.py:12` |
| `quantlab/data.py` | 498 | infrastructure | `quantlab/data.py` | 本地資料匯入與 calendar 混合；`parse_timestamp`，`quantlab/data.py:24` |
| `quantlab/data_gap_report.py` | 100 | application | `quantlab/research_core/application/data_gap_report.py` | 匯入品質投影；混入 desktop 錯誤呈現；E 按責任抽取；匯入違規見第 3 節；`Gap`，`quantlab/data_gap_report.py:15` |
| `quantlab/desktop_errors.py` | 38 | presentation | `desktop_app/components/desktop_errors.py` | 桌面例外分類；混入 runtime 依賴；E 按責任抽取；匯入違規見第 3 節；`error_message`，`quantlab/desktop_errors.py:7` |
| `quantlab/desktop_feedback.py` | 171 | presentation | `quantlab/desktop_feedback.py` | 無 Qt 的 UI 完成／停止文案投影；R4 無違規／超大觸發，原址保留；`stop_presentation`，`quantlab/desktop_feedback.py:77` |
| `quantlab/desktop_runtime.py` | 1840 | application | `quantlab/desktop_runtime.py` | 工作管理用例混合路徑、vault、備份與 process IO；不是整檔 composition；保留本體與既有路徑，見 G3 相依限制；匯入違規見第 3 節；`_OperationExecutorRegistry`，`quantlab/desktop_runtime.py:52` |
| `quantlab/diagnostics.py` | 127 | application | `quantlab/research_core/application/diagnostics.py` | 診斷組合用例；混有讀檔與 UI 標籤；E 按責任抽取；匯入違規見第 3 節；`fixed`，`quantlab/diagnostics.py:21` |
| `quantlab/download_import.py` | 177 | application | `quantlab/research_core/application/download_import.py` | 下載與嚴格匯入流程協調；E 按責任抽取；匯入違規見第 3 節；`import_settings`，`quantlab/download_import.py:18` |
| `quantlab/downloads.py` | 250 | infrastructure | `quantlab/downloads.py` | 官方 HTTP 與 archive 下載；R4 無違規／超大觸發，原址保留；`official_url`，`quantlab/downloads.py:38` |
| `quantlab/errors.py` | 182 | shared | `quantlab/errors.py` | 固定錯誤碼與共用例外；R4 無違規／超大觸發，原址保留；`RecoveryError`，`quantlab/errors.py:11` |
| `quantlab/idea_research.py` | 662 | application | `quantlab/research_core/application/idea_research.py` | 搜尋、擷取與候選採用流程；混有 IdeaStore；E 按責任抽取；匯入違規見第 3 節；`new_task`，`quantlab/idea_research.py:98` |
| `quantlab/idea_search.py` | 354 | infrastructure | `quantlab/idea_search.py` | Responses stream 邊界與搜尋結果處理；R4 無違規／超大觸發，原址保留；`SearchUnavailable`，`quantlab/idea_search.py:39` |
| `quantlab/idea_sources.py` | 136 | shared | `quantlab/idea_sources.py` | 固定網址與封鎖設定；R4 無違規／超大觸發，原址保留；`quantlab/idea_sources.py:1` |
| `quantlab/indicators.py` | 434 | domain | `quantlab/indicators.py` | Decimal 指標公式；R4 無違規／超大觸發，原址保留；`IndicatorResourceLimitError`，`quantlab/indicators.py:27` |
| `quantlab/job_stages.py` | 31 | shared | `quantlab/job_stages.py` | 固定工作階段標籤；R4 無違規／超大觸發，原址保留；`normalize_stage`，`quantlab/job_stages.py:6` |
| `quantlab/manual_exchange.py` | 326 | infrastructure | `quantlab/research_core/adapters/manual_exchange.py` | 手動交換檔案與 generator adapter；E 按責任抽取；匯入違規見第 3 節；`_strict`，`quantlab/manual_exchange.py:37` |
| `quantlab/market.py` | 265 | domain | `quantlab/market.py` | 不可變行情資料值；R4 無違規／超大觸發，原址保留；`MarketValidationError`，`quantlab/market.py:13` |
| `quantlab/market_history.py` | 675 | infrastructure | `quantlab/research_core/adapters/market_history.py` | 本地行情匯入與 cache 檔案鎖；E 按責任抽取；`_fail`，`quantlab/market_history.py:50` |
| `quantlab/market_providers.py` | 520 | infrastructure | `quantlab/market_providers.py` | 官方行情 HTTP 與 cache 實作；R4 無違規／超大觸發，原址保留；`official_url`，`quantlab/market_providers.py:60` |
| `quantlab/paper.py` | 969 | application | `quantlab/research_core/application/paper.py` | 紙上交易狀態與風控服務；混有 SQLite journal；E 按責任抽取；`JournalConflict`，`quantlab/paper.py:47` |
| `quantlab/paper_amend.py` | 46 | application | `quantlab/paper_amend.py` | 既有 paper 修改用例；R4 無違規／超大觸發，原址保留；`execute`，`quantlab/paper_amend.py:10` |
| `quantlab/paper_replay.py` | 337 | application | `quantlab/research_core/application/paper_replay.py` | 回播協調；混有 SQLite 持久化；E 按責任抽取；匯入違規見第 3 節；`_require_wal_runtime`，`quantlab/paper_replay.py:24` |
| `quantlab/paper_tab_data.py` | 133 | presentation | `quantlab/paper_tab_data.py` | 純畫面 row 投影；R4 無違規／超大觸發，原址保留；`number`，`quantlab/paper_tab_data.py:7` |
| `quantlab/payload_cleanup.py` | 121 | infrastructure | `quantlab/payload_cleanup.py` | 安裝版本目錄清理實作；R4 無違規／超大觸發，原址保留；`parse_version`，`quantlab/payload_cleanup.py:17` |
| `quantlab/product_keys.py` | 43 | shared | `quantlab/product_keys.py` | 純顯示識別字轉換；R4 無違規／超大觸發，原址保留；`converge_key`，`quantlab/product_keys.py:17` |
| `quantlab/provider.py` | 146 | infrastructure | `quantlab/provider.py` | 預設關閉 HTTP transport；匯入違規見第 3 節；`HTTPTransport`，`quantlab/provider.py:18` |
| `quantlab/replay_pacing.py` | 52 | application | `quantlab/replay_pacing.py` | 回播 pacing 與 monotonic 時鐘協調；R4 無違規／超大觸發，原址保留；`ReplayPacer`，`quantlab/replay_pacing.py:13` |
| `quantlab/reporting.py` | 358 | infrastructure | `quantlab/research_core/adapters/reporting.py` | 結果檔、CSV 匯出與資料持久化；E 按責任抽取；匯入違規見第 3 節；`saved_analysis_entries`，`quantlab/reporting.py:24` |
| `quantlab/research.py` | 1093 | application | `quantlab/research.py` | 研究 campaign 協調與 SQLite 預算混合；匯入違規見第 3 節；`registry_json_schema`，`quantlab/research.py:51` |
| `quantlab/research_analysis.py` | 545 | application | `quantlab/research_analysis.py` | 分析流程與 journal 混合；G3 provider 直接匯入；保留本體與既有路徑，見 G3 相依限制；匯入違規見第 3 節；`_safe_path`，`quantlab/research_analysis.py:60` |
| `quantlab/response_output.py` | 54 | infrastructure | `quantlab/response_output.py` | Responses wire 輸出重組；依賴 transport error；R4 無違規／超大觸發，原址保留；`CompletedOutput`，`quantlab/response_output.py:8` |
| `quantlab/runtime_support.py` | 171 | infrastructure | `quantlab/runtime_support.py` | durable IO 與 Windows mutex；不是純 shared；保留本體與既有路徑，見 G3 相依限制；`RuntimeSafetyError`，`quantlab/runtime_support.py:14` |
| `quantlab/saved_candidate_pool.py` | 2063 | application | `quantlab/saved_candidate_pool.py` | 候選來源 admission 與固定 producer profiles；保留本體與既有路徑，見 G3 相依限制；匯入違規見第 3 節；`SavedCandidatePool`，`quantlab/saved_candidate_pool.py:1160` |
| `quantlab/significance.py` | 311 | domain | `quantlab/significance.py` | 純統計推論公式；R4 無違規／超大觸發，原址保留；`_decimal`，`quantlab/significance.py:33` |
| `quantlab/sqlite_runtime.py` | 84 | infrastructure | `quantlab/sqlite_runtime.py` | 原生 SQLite 載入驗證與來源雜湊；R4 無違規／超大觸發，原址保留；`loaded_library`，`quantlab/sqlite_runtime.py:15` |
| `quantlab/startup_timing.py` | 47 | shared | `quantlab/startup_timing.py` | 共用記憶體計時工具；R4 無違規／超大觸發，原址保留；`StartupTiming`，`quantlab/startup_timing.py:11` |
| `quantlab/strategies.py` | 195 | domain | `quantlab/strategies.py` | 有限策略規則與訊號產生；`builtin_strategies`，`quantlab/strategies.py:15` |
| `quantlab/strict_json.py` | 51 | infrastructure | `quantlab/strict_json.py` | JSON 邊界含檔案讀取；不是純 shared；R4 無違規／超大觸發，原址保留；`_unique_keys`，`quantlab/strict_json.py:9` |
| `quantlab/taifex_expiries.py` | 81 | infrastructure | `quantlab/taifex_expiries.py` | 本地到期日資料讀取與驗證；R4 無違規／超大觸發，原址保留；`_iso`，`quantlab/taifex_expiries.py:15` |
| `quantlab/tls_trust.py` | 37 | infrastructure | `quantlab/tls_trust.py` | 平台 TLS trust context adapter；R4 無違規／超大觸發，原址保留；`build_trust_context`，`quantlab/tls_trust.py:11` |
| `quantlab/trade_statistics.py` | 152 | domain | `quantlab/trade_statistics.py` | 純成交描述統計；R4 無違規／超大觸發，原址保留；`_number`，`quantlab/trade_statistics.py:46` |
| `quantlab/trading/adapters/shioaji/__init__.py` | 6 | infrastructure | `quantlab/trading/adapters/shioaji/__init__.py` | 既有 adapter 實作；保留路徑；`quantlab/trading/adapters/shioaji/__init__.py:1` |
| `quantlab/trading/adapters/shioaji/gateway.py` | 419 | infrastructure | `quantlab/trading/adapters/shioaji/gateway.py` | 既有 adapter 實作；保留路徑；`ShioajiAdapter`，`quantlab/trading/adapters/shioaji/gateway.py:45` |
| `quantlab/trading/adapters/shioaji/mapping.py` | 177 | infrastructure | `quantlab/trading/adapters/shioaji/mapping.py` | 既有 adapter 實作；保留路徑；`stock_sdk_quantity`，`quantlab/trading/adapters/shioaji/mapping.py:24` |
| `quantlab/trading/adapters/shioaji/market_data.py` | 122 | infrastructure | `quantlab/trading/adapters/shioaji/market_data.py` | 既有 adapter 實作；保留路徑；`MarketDataContext`，`quantlab/trading/adapters/shioaji/market_data.py:16` |
| `quantlab/trading/adapters/shioaji/sdk.py` | 138 | infrastructure | `quantlab/trading/adapters/shioaji/sdk.py` | 既有 adapter 實作；保留路徑；`BrokerCredentials`，`quantlab/trading/adapters/shioaji/sdk.py:17` |
| `quantlab/trading/adapters/shioaji/sdk_facade.py` | 251 | infrastructure | `quantlab/trading/adapters/shioaji/sdk_facade.py` | 既有 adapter 實作；保留路徑；`_budget`，`quantlab/trading/adapters/shioaji/sdk_facade.py:25` |
| `quantlab/trading/adapters/shioaji/sdk_loader.py` | 21 | infrastructure | `quantlab/trading/adapters/shioaji/sdk_loader.py` | 既有 adapter 實作；保留路徑；`load_pinned_sdk`，`quantlab/trading/adapters/shioaji/sdk_loader.py:9` |
| `quantlab/trading/adapters/shioaji/secrets.py` | 103 | infrastructure | `quantlab/trading/adapters/shioaji/secrets.py` | 既有 adapter 實作；保留路徑；`CredentialBackend`，`quantlab/trading/adapters/shioaji/secrets.py:19` |
| `quantlab/trading/adapters/shioaji/stock_grid.py` | 97 | infrastructure | `quantlab/trading/adapters/shioaji/stock_grid.py` | 既有 adapter 實作；保留路徑；`StockGridEvidence`，`quantlab/trading/adapters/shioaji/stock_grid.py:49` |
| `quantlab/trading/adapters/shioaji/tick_stream.py` | 113 | infrastructure | `quantlab/trading/adapters/shioaji/tick_stream.py` | 既有 adapter 實作；保留路徑；`normalise_tick`，`quantlab/trading/adapters/shioaji/tick_stream.py:26` |
| `quantlab/trading/adapters/simulated/__init__.py` | 5 | infrastructure | `quantlab/trading/adapters/simulated/__init__.py` | 既有 adapter 實作；保留路徑；`quantlab/trading/adapters/simulated/__init__.py:1` |
| `quantlab/trading/adapters/simulated/broker.py` | 427 | infrastructure | `quantlab/trading/adapters/simulated/broker.py` | 既有 adapter 實作；保留路徑；`FaultPlan`，`quantlab/trading/adapters/simulated/broker.py:41` |
| `quantlab/trading/adapters/simulated/tick_feed.py` | 74 | infrastructure | `quantlab/trading/adapters/simulated/tick_feed.py` | 既有 adapter 實作；保留路徑；`SimulatedTickFeed`，`quantlab/trading/adapters/simulated/tick_feed.py:17` |
| `quantlab/trading/adapters/storage/__init__.py` | 1 | infrastructure | `quantlab/trading/adapters/storage/__init__.py` | 既有 adapter 實作；保留路徑；`quantlab/trading/adapters/storage/__init__.py:1` |
| `quantlab/trading/adapters/storage/ledger.py` | 141 | infrastructure | `quantlab/trading/adapters/storage/ledger.py` | 既有 adapter 實作；保留路徑；`Ledger`，`quantlab/trading/adapters/storage/ledger.py:14` |
| `quantlab/trading/application/__init__.py` | 1 | application | `quantlab/trading/application/__init__.py` | 既有交易用例／契約；保留路徑；`quantlab/trading/application/__init__.py:1` |
| `quantlab/trading/application/broker_settings.py` | 252 | application | `quantlab/trading/application/broker_settings.py` | 既有交易用例／契約；保留路徑；`BrokerSettings`，`quantlab/trading/application/broker_settings.py:14` |
| `quantlab/trading/application/codec.py` | 117 | application | `quantlab/trading/application/codec.py` | 既有交易用例／契約；保留路徑；`register`，`quantlab/trading/application/codec.py:15` |
| `quantlab/trading/application/concurrency.py` | 40 | application | `quantlab/trading/application/concurrency.py` | 既有交易用例／契約；保留路徑；`WriterLock`，`quantlab/trading/application/concurrency.py:8` |
| `quantlab/trading/application/context.py` | 102 | application | `quantlab/trading/application/context.py` | 既有交易用例／契約；保留路徑；`AccountGateway`，`quantlab/trading/application/context.py:22` |
| `quantlab/trading/application/contextnavigation.py` | 143 | application | `quantlab/trading/application/contextnavigation.py` | 既有交易用例／契約；保留路徑；`_failure`，`quantlab/trading/application/contextnavigation.py:12` |
| `quantlab/trading/application/contracts.py` | 360 | application | `quantlab/trading/application/contracts.py` | 既有交易用例／契約；保留路徑；`MarketHealthView`，`quantlab/trading/application/contracts.py:17` |
| `quantlab/trading/application/coordinator.py` | 187 | application | `quantlab/trading/application/coordinator.py` | 既有交易用例／契約；保留路徑；`_attention`，`quantlab/trading/application/coordinator.py:27` |
| `quantlab/trading/application/engine.py` | 505 | application | `quantlab/trading/application/engine.py` | 既有交易用例／契約；保留路徑；`TradingEngine`，`quantlab/trading/application/engine.py:36` |
| `quantlab/trading/application/errors.py` | 48 | application | `quantlab/trading/application/errors.py` | 既有交易用例／契約；保留路徑；`quantlab/trading/application/errors.py:1` |
| `quantlab/trading/application/events.py` | 253 | application | `quantlab/trading/application/events.py` | 既有交易用例／契約；保留路徑；`cursor`，`quantlab/trading/application/events.py:26` |
| `quantlab/trading/application/execution.py` | 115 | application | `quantlab/trading/application/execution.py` | 既有交易用例／契約；保留路徑；`ExecutionService`，`quantlab/trading/application/execution.py:18` |
| `quantlab/trading/application/facade.py` | 139 | application | `quantlab/trading/application/facade.py` | 既有交易用例／契約；保留路徑；`LocalFacade`，`quantlab/trading/application/facade.py:19` |
| `quantlab/trading/application/lifecycle.py` | 364 | application | `quantlab/trading/application/lifecycle.py` | 既有交易用例／契約；保留路徑；`_issue`，`quantlab/trading/application/lifecycle.py:24` |
| `quantlab/trading/application/lifecycle_models.py` | 39 | application | `quantlab/trading/application/lifecycle_models.py` | 既有交易用例／契約；保留路徑；`CorporateActionJob`，`quantlab/trading/application/lifecycle_models.py:11` |
| `quantlab/trading/application/live_market.py` | 377 | application | `quantlab/trading/application/live_market.py` | 既有交易用例／契約；保留路徑；`_affected_minute`，`quantlab/trading/application/live_market.py:41` |
| `quantlab/trading/application/market_cycle.py` | 27 | application | `quantlab/trading/application/market_cycle.py` | 既有交易用例／契約；保留路徑；`poll_market`，`quantlab/trading/application/market_cycle.py:12` |
| `quantlab/trading/application/market_views.py` | 45 | application | `quantlab/trading/application/market_views.py` | 既有交易用例／契約；保留路徑；`market_watch_view`，`quantlab/trading/application/market_views.py:10` |
| `quantlab/trading/application/performance.py` | 187 | application | `quantlab/trading/application/performance.py` | 既有交易用例／契約；保留路徑；`VersionEquityTrack`，`quantlab/trading/application/performance.py:29` |
| `quantlab/trading/application/provenance.py` | 37 | application | `quantlab/trading/application/provenance.py` | 既有交易用例／契約；保留路徑；`ProducerProfile`，`quantlab/trading/application/provenance.py:11` |
| `quantlab/trading/application/readiness_session.py` | 240 | application | `quantlab/trading/application/readiness_session.py` | 既有交易用例／契約；保留路徑；`ReadinessState`，`quantlab/trading/application/readiness_session.py:22` |
| `quantlab/trading/application/reconciliation_state.py` | 23 | application | `quantlab/trading/application/reconciliation_state.py` | 既有交易用例／契約；保留路徑；`confirmed_availability`，`quantlab/trading/application/reconciliation_state.py:10` |
| `quantlab/trading/application/reconciliation_views.py` | 66 | application | `quantlab/trading/application/reconciliation_views.py` | 既有交易用例／契約；保留路徑；`differences`，`quantlab/trading/application/reconciliation_views.py:11` |
| `quantlab/trading/application/registry.py` | 32 | application | `quantlab/trading/application/registry.py` | 既有交易用例／契約；保留路徑；`initialize`，`quantlab/trading/application/registry.py:12` |
| `quantlab/trading/application/research.py` | 155 | application | `quantlab/trading/application/research.py` | 既有交易用例／契約；保留路徑；`ResearchTrade`，`quantlab/trading/application/research.py:19` |
| `quantlab/trading/application/reservations.py` | 40 | application | `quantlab/trading/application/reservations.py` | 既有交易用例／契約；保留路徑；`current_reservations`，`quantlab/trading/application/reservations.py:16` |
| `quantlab/trading/application/scope.py` | 36 | application | `quantlab/trading/application/scope.py` | 既有交易用例／契約；保留路徑；`refresh_scope`，`quantlab/trading/application/scope.py:15` |
| `quantlab/trading/application/sessions.py` | 236 | application | `quantlab/trading/application/sessions.py` | 既有交易用例／契約；保留路徑；`SessionContext`，`quantlab/trading/application/sessions.py:29` |
| `quantlab/trading/application/state.py` | 101 | application | `quantlab/trading/application/state.py` | 既有交易用例／契約；保留路徑；`StrategyRecord`，`quantlab/trading/application/state.py:21` |
| `quantlab/trading/application/views.py` | 294 | application | `quantlab/trading/application/views.py` | 既有交易用例／契約；保留路徑；`_financial_facts_current`，`quantlab/trading/application/views.py:22` |
| `quantlab/trading/application/watchlist.py` | 56 | application | `quantlab/trading/application/watchlist.py` | 既有交易用例／契約；保留路徑；`validate_watchlist`，`quantlab/trading/application/watchlist.py:15` |
| `quantlab/trading/application/workflows.py` | 235 | application | `quantlab/trading/application/workflows.py` | 既有交易用例／契約；保留路徑；`run_research`，`quantlab/trading/application/workflows.py:27` |
| `quantlab/trading/domain/__init__.py` | 1 | domain | `quantlab/trading/domain/__init__.py` | 既有純交易模型／規則；保留路徑；`quantlab/trading/domain/__init__.py:1` |
| `quantlab/trading/domain/arithmetic.py` | 23 | domain | `quantlab/trading/domain/arithmetic.py` | 既有純交易模型／規則；保留路徑；`decimal_operation`，`quantlab/trading/domain/arithmetic.py:14` |
| `quantlab/trading/domain/calendar.py` | 86 | domain | `quantlab/trading/domain/calendar.py` | 既有純交易模型／規則；保留路徑；`TradingSession`，`quantlab/trading/domain/calendar.py:10` |
| `quantlab/trading/domain/costs.py` | 104 | domain | `quantlab/trading/domain/costs.py` | 既有純交易模型／規則；保留路徑；`FeeSchedule`，`quantlab/trading/domain/costs.py:19` |
| `quantlab/trading/domain/freshness.py` | 57 | domain | `quantlab/trading/domain/freshness.py` | 既有純交易模型／規則；保留路徑；`Freshness`，`quantlab/trading/domain/freshness.py:10` |
| `quantlab/trading/domain/lifecycle.py` | 134 | domain | `quantlab/trading/domain/lifecycle.py` | 既有純交易模型／規則；保留路徑；`CorporateAction`，`quantlab/trading/domain/lifecycle.py:18` |
| `quantlab/trading/domain/live_bars.py` | 200 | domain | `quantlab/trading/domain/live_bars.py` | 既有純交易模型／規則；保留路徑；`LiveBar`，`quantlab/trading/domain/live_bars.py:19` |
| `quantlab/trading/domain/models.py` | 458 | domain | `quantlab/trading/domain/models.py` | 既有純交易模型／規則；保留路徑；`Market`，`quantlab/trading/domain/models.py:12` |
| `quantlab/trading/domain/policies.py` | 107 | domain | `quantlab/trading/domain/policies.py` | 既有純交易模型／規則；保留路徑；`HoldingWindow`，`quantlab/trading/domain/policies.py:14` |
| `quantlab/trading/domain/quote_stats.py` | 46 | domain | `quantlab/trading/domain/quote_stats.py` | 既有純交易模型／規則；保留路徑；`TradeDateClose`，`quantlab/trading/domain/quote_stats.py:13` |
| `quantlab/trading/domain/risk.py` | 204 | domain | `quantlab/trading/domain/risk.py` | 既有純交易模型／規則；保留路徑；`RiskPolicy`，`quantlab/trading/domain/risk.py:15` |
| `quantlab/trading/domain/strategy.py` | 278 | domain | `quantlab/trading/domain/strategy.py` | 既有純交易模型／規則；保留路徑；`Rule`，`quantlab/trading/domain/strategy.py:20` |
| `quantlab/trading/domain/ticks.py` | 33 | domain | `quantlab/trading/domain/ticks.py` | 既有純交易模型／規則；保留路徑；`Tick`，`quantlab/trading/domain/ticks.py:11` |
| `quantlab/trading/domain/validation.py` | 45 | domain | `quantlab/trading/domain/validation.py` | 既有純交易模型／規則；保留路徑；`DomainError`，`quantlab/trading/domain/validation.py:7` |
| `quantlab/trading/ports/__init__.py` | 1 | application | `quantlab/trading/ports/__init__.py` | port／資料契約，不是服務實作；保留路徑；`quantlab/trading/ports/__init__.py:1` |
| `quantlab/trading/ports/contracts.py` | 247 | application | `quantlab/trading/ports/contracts.py` | port／資料契約，不是服務實作；保留路徑；`ConnectionState`，`quantlab/trading/ports/contracts.py:14` |
| `quantlab/trading/ports/interfaces.py` | 70 | application | `quantlab/trading/ports/interfaces.py` | port／資料契約，不是服務實作；保留路徑；`Clock`，`quantlab/trading/ports/interfaces.py:22` |
| `quantlab/trading/ports/storage.py` | 30 | application | `quantlab/trading/ports/storage.py` | port／資料契約，不是服務實作；保留路徑；`Fence`，`quantlab/trading/ports/storage.py:10` |
| `quantlab/trading/ports/tick_stream.py` | 38 | application | `quantlab/trading/ports/tick_stream.py` | port／資料契約，不是服務實作；保留路徑；`TickLoss`，`quantlab/trading/ports/tick_stream.py:9` |
| `quantlab/trading/runtime/__init__.py` | 1 | composition | `quantlab/trading/runtime/__init__.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`quantlab/trading/runtime/__init__.py:1` |
| `quantlab/trading/runtime/bootstrap.py` | 517 | composition | `quantlab/trading/runtime/bootstrap.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`WallClock`，`quantlab/trading/runtime/bootstrap.py:26` |
| `quantlab/trading/runtime/broker.py` | 353 | composition | `quantlab/trading/runtime/broker.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`_pairs`，`quantlab/trading/runtime/broker.py:31` |
| `quantlab/trading/runtime/build.py` | 366 | composition | `quantlab/trading/runtime/build.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`SimulationClock`，`quantlab/trading/runtime/build.py:28` |
| `quantlab/trading/runtime/config.py` | 360 | composition | `quantlab/trading/runtime/config.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`RuntimeLaunch`，`quantlab/trading/runtime/config.py:27` |
| `quantlab/trading/runtime/context_client.py` | 374 | composition | `quantlab/trading/runtime/context_client.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`_alive`，`quantlab/trading/runtime/context_client.py:29` |
| `quantlab/trading/runtime/control_secret.py` | 37 | composition | `quantlab/trading/runtime/control_secret.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`_Blob`，`quantlab/trading/runtime/control_secret.py:8` |
| `quantlab/trading/runtime/gateway_cache.py` | 214 | composition | `quantlab/trading/runtime/gateway_cache.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`ReadOnlyGatewayCache`，`quantlab/trading/runtime/gateway_cache.py:21` |
| `quantlab/trading/runtime/ipc.py` | 98 | composition | `quantlab/trading/runtime/ipc.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`Session`，`quantlab/trading/runtime/ipc.py:22` |
| `quantlab/trading/runtime/live_market.py` | 106 | composition | `quantlab/trading/runtime/live_market.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`CalendarResolver`，`quantlab/trading/runtime/live_market.py:15` |
| `quantlab/trading/runtime/protocol.py` | 69 | composition | `quantlab/trading/runtime/protocol.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`Operation`，`quantlab/trading/runtime/protocol.py:14` |
| `quantlab/trading/runtime/provenance.py` | 20 | composition | `quantlab/trading/runtime/provenance.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`compute_profile`，`quantlab/trading/runtime/provenance.py:11` |
| `quantlab/trading/runtime/research_worker.py` | 381 | composition | `quantlab/trading/runtime/research_worker.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`WorkerFault`，`quantlab/trading/runtime/research_worker.py:39` |
| `quantlab/trading/runtime/server.py` | 288 | composition | `quantlab/trading/runtime/server.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`_metrics`，`quantlab/trading/runtime/server.py:25` |
| `quantlab/trading/runtime/unix_socket.py` | 108 | composition | `quantlab/trading/runtime/unix_socket.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`_prefix`，`quantlab/trading/runtime/unix_socket.py:19` |
| `quantlab/trading/runtime/watchlist_settings.py` | 39 | composition | `quantlab/trading/runtime/watchlist_settings.py` | 既有 runtime 組裝與 process/IPC 支援邊界；保留路徑；`WatchlistSettings`，`quantlab/trading/runtime/watchlist_settings.py:14` |
| `quantlab/ui_preferences.py` | 29 | presentation | `quantlab/ui_preferences.py` | 無 Qt 的 UI 偏好投影；R4 無違規／超大觸發，原址保留；`page_row`，`quantlab/ui_preferences.py:4` |
| `quantlab/update_check.py` | 86 | infrastructure | `quantlab/update_check.py` | 使用者觸發的 HTTP 版本查詢；R4 無違規／超大觸發，原址保留；`UpdateResult`，`quantlab/update_check.py:28` |
| `quantlab/value_bounds.py` | 71 | domain | `quantlab/value_bounds.py` | 依賴 core 的數值／metadata 規則；不是 shared；R4 無違規／超大觸發，原址保留；`_bounded_number`，`quantlab/value_bounds.py:11` |
| `quantlab/verdict.py` | 109 | domain | `quantlab/verdict.py` | 純 OOS 顯示判定規則；R4 無違規／超大觸發，原址保留；`_number`，`quantlab/verdict.py:19` |
| `quantlab/walk_forward.py` | 810 | application | `quantlab/research_core/application/walk_forward.py` | 固定候選池選擇協調與 SQLite state；E 按責任抽取；匯入違規見第 3 節；`_bounds`，`quantlab/walk_forward.py:39` |
| `quantlab/web_fetch.py` | 368 | infrastructure | `quantlab/web_fetch.py` | 公開 HTTPS 文件擷取 adapter；R4 無違規／超大觸發，原址保留；`FetchBlocked`，`quantlab/web_fetch.py:54` |
| `quantlab/wf_estimate.py` | 21 | presentation | `quantlab/wf_estimate.py` | 畫面時間估計；R4 無違規／超大觸發，原址保留；`estimated_seconds`，`quantlab/wf_estimate.py:11` |
| `quantlab/windows_paths.py` | 54 | shared | `quantlab/windows_paths.py` | 跨層路徑拼寫工具；無讀寫副作用；保留本體與既有路徑，見 G3 相依限制；`canonical_path`，`quantlab/windows_paths.py:14` |
| `tools/bench_backtest_scale.py` | 57 | tooling | `tools/bench_backtest_scale.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`main`，`tools/bench_backtest_scale.py:17` |
| `tools/bench_worker_latency.py` | 185 | tooling | `tools/bench_worker_latency.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`summary`，`tools/bench_worker_latency.py:23` |
| `tools/check_layers.py` | 207 | tooling | `tools/check_layers.py` | R1 全 repo 匯入分層閘門；只解析來源、不執行產品碼；`tools/check_layers.py:1` |
| `tools/check_trading_architecture.py` | 276 | tooling | `tools/check_trading_architecture.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`Finding`，`tools/check_trading_architecture.py:22` |
| `tools/ci_changes.py` | 95 | tooling | `tools/ci_changes.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`is_doc_candidate`，`tools/ci_changes.py:23` |
| `tools/diagnose_paper_replay.py` | 1070 | tooling | `tools/diagnose_paper_replay.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`Timings`，`tools/diagnose_paper_replay.py:26` |
| `tools/diagnose_research_phases.py` | 401 | tooling | `tools/diagnose_research_phases.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`source_key`，`tools/diagnose_research_phases.py:36` |
| `tools/diagnose_wfo_storage.py` | 472 | tooling | `tools/diagnose_wfo_storage.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`canonical`，`tools/diagnose_wfo_storage.py:39` |
| `tools/extract_desktop_smoke_r2.py` | 66 | tooling | `tools/extract_desktop_smoke_r2.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`main`，`tools/extract_desktop_smoke_r2.py:23` |
| `tools/generate_significance_goldens.py` | 24 | tooling | `tools/generate_significance_goldens.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`generate`，`tools/generate_significance_goldens.py:10` |
| `tools/generate_welch_goldens.py` | 28 | tooling | `tools/generate_welch_goldens.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`generate`，`tools/generate_welch_goldens.py:9` |
| `tools/install_desktop_auth.py` | 114 | tooling | `tools/install_desktop_auth.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`requirements_text`，`tools/install_desktop_auth.py:26` |
| `tools/install_sqlite_runtime.py` | 170 | tooling | `tools/install_sqlite_runtime.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`reject_links`，`tools/install_sqlite_runtime.py:39` |
| `tools/list_unverified_goldens.py` | 55 | tooling | `tools/list_unverified_goldens.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`golden_entries`，`tools/list_unverified_goldens.py:21` |
| `tools/lm1_slice1_probe.py` | 125 | tooling | `tools/lm1_slice1_probe.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`measure`，`tools/lm1_slice1_probe.py:16` |
| `tools/make_icon.py` | 58 | tooling | `tools/make_icon.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`_chunk`，`tools/make_icon.py:12` |
| `tools/measure_ci_margin.py` | 83 | tooling | `tools/measure_ci_margin.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`summarize`，`tools/measure_ci_margin.py:20` |
| `tools/probe_windows_guest_host.py` | 224 | tooling | `tools/probe_windows_guest_host.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`query_kvm_api`，`tools/probe_windows_guest_host.py:42` |
| `tools/quality_gate.py` | 235 | tooling | `tools/quality_gate.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`v2_import_allowance`，`tools/quality_gate.py:36` |
| `tools/research_app.py` | 404 | tooling | `tools/research_app.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`guard`，`tools/research_app.py:37` |
| `tools/research_campaign.py` | 95 | tooling | `tools/research_campaign.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`run_fixture_campaign`，`tools/research_campaign.py:21` |
| `tools/run_test_group.py` | 620 | tooling | `tools/run_test_group.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`core_shard_for_module`，`tools/run_test_group.py:78` |
| `tools/trading_load_probe.py` | 494 | tooling | `tools/trading_load_probe.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`process_memory`，`tools/trading_load_probe.py:42` |
| `tools/trading_load_report.py` | 10 | tooling | `tools/trading_load_report.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`write_report`，`tools/trading_load_report.py:9` |
| `tools/ui_readability_audit.py` | 209 | tooling | `tools/ui_readability_audit.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`_luminance`，`tools/ui_readability_audit.py:26` |
| `tools/ui_redesign_preview.py` | 202 | tooling | `tools/ui_redesign_preview.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`isolate`，`tools/ui_redesign_preview.py:15` |
| `tools/ui_snapshot.py` | 383 | tooling | `tools/ui_snapshot.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`parse_size`，`tools/ui_snapshot.py:19` |
| `tools/ui_test_gate.py` | 252 | tooling | `tools/ui_test_gate.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`producer_assignments`，`tools/ui_test_gate.py:26` |
| `tools/ui_theme_diff.py` | 63 | tooling | `tools/ui_theme_diff.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`compare`，`tools/ui_theme_diff.py:14` |
| `tools/update_taifex_expiries.py` | 107 | tooling | `tools/update_taifex_expiries.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`SettlementTable`，`tools/update_taifex_expiries.py:17` |
| `tools/validate_core_shards.py` | 282 | tooling | `tools/validate_core_shards.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`read_core_report`，`tools/validate_core_shards.py:70` |
| `tools/validate_market_download.py` | 57 | tooling | `tools/validate_market_download.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`validate`，`tools/validate_market_download.py:17` |
| `tools/validate_market_history_import.py` | 99 | tooling | `tools/validate_market_history_import.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`validate`，`tools/validate_market_history_import.py:23` |
| `tools/validate_official_history.py` | 408 | tooling | `tools/validate_official_history.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`verified_oct8_calendar`，`tools/validate_official_history.py:35` |
| `tools/validate_real_ai.py` | 396 | tooling | `tools/validate_real_ai.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`sha256_file`，`tools/validate_real_ai.py:110` |
| `tools/validate_web_search.py` | 160 | tooling | `tools/validate_web_search.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`summarize`，`tools/validate_web_search.py:31` |
| `tools/verify_format_equivalence.py` | 104 | tooling | `tools/verify_format_equivalence.py` | 開發／打包／驗證／範例腳本；不屬 runtime layers；`equivalent`，`tools/verify_format_equivalence.py:26` |
| `trading_entry.py` | 11 | composition | `trading_entry.py` | 根目錄 launcher／桌面接線；保留路徑；`launch`，`trading_entry.py:6` |
| `trading_runtime.py` | 103 | composition | `trading_runtime.py` | 根目錄 launcher／桌面接線；保留路徑；`default_root`，`trading_runtime.py:18` |

| `quantlab/research_core/__init__.py` | 0 | application | `quantlab/research_core/__init__.py` | PR D; slice 2a responsibility owner |
| `quantlab/research_core/adapters/job_process.py` | 325 | application | `quantlab/research_core/adapters/job_process.py` | PR D; slice 2a real owner |
| `quantlab/research_core/adapters/job_worker.py` | 188 | application | `quantlab/research_core/adapters/job_worker.py` | PR D; slice 2a real owner |
| `quantlab/research_core/adapters/saved_pool_source.py` | 297 | application | `quantlab/research_core/adapters/saved_pool_source.py` | PR D; slice 2a real owner |
| `quantlab/research_core/adapters/workspace_backup.py` | 302 | application | `quantlab/research_core/adapters/workspace_backup.py` | PR D; slice 2a real owner |
| `quantlab/research_core/adapters/__init__.py` | 0 | infrastructure | `quantlab/research_core/adapters/__init__.py` | PR D; slice 2a owner; extracted orchestration retains application classification |
| `quantlab/research_core/application/job_requests.py` | 264 | application | `quantlab/research_core/application/job_requests.py` | PR D; slice 2a real owner |
| `quantlab/research_core/application/saved_pool_attempts.py` | 302 | application | `quantlab/research_core/application/saved_pool_attempts.py` | PR D; slice 2a real owner |
| `quantlab/research_core/application/saved_pool_validation.py` | 442 | application | `quantlab/research_core/application/saved_pool_validation.py` | PR D; slice 2a real owner |
| `quantlab/research_core/application/__init__.py` | 1 | application | `quantlab/research_core/application/__init__.py` | PR D; slice 2a real owner |
| `quantlab/research_core/domain/job_protocol.py` | 51 | domain | `quantlab/research_core/domain/job_protocol.py` | PR D; slice 2a real owner |
| `quantlab/research_core/domain/saved_pool.py` | 50 | domain | `quantlab/research_core/domain/saved_pool.py` | PR D; slice 2a real owner |
| `quantlab/research_core/ports/jobs.py` | 15 | application | `quantlab/research_core/ports/jobs.py` | PR D; slice 2a real owner |
| `quantlab/research_core/ports/__init__.py` | 1 | application | `quantlab/research_core/ports/__init__.py` | PR D; slice 2a real owner |
| `tools/refactor/split_core_runtime.py` | 626 | tooling | `tools/refactor/split_core_runtime.py` | PR D reproducible repair |
| `tools/refactor/split_core_controller_fixes.py` | 136 | tooling | `tools/refactor/split_core_controller_fixes.py` | PR D reproducible repair |

| `quantlab/assistant/application/connection_contracts.py` | 420 | application | `quantlab/assistant/application/connection_contracts.py` | PR D slice 2b responsibility owner |
| `quantlab/assistant/application/connection_controller.py` | 387 | application | `quantlab/assistant/application/connection_controller.py` | PR D slice 2b responsibility owner |
| `quantlab/assistant/application/context_usage.py` | 9 | application | `quantlab/assistant/application/context_usage.py` | PR D slice 2b responsibility owner |
| `quantlab/assistant/domain/connection_errors.py` | 15 | domain | `quantlab/assistant/domain/connection_errors.py` | PR D slice 2b responsibility owner |
| `quantlab/assistant/ports/connection.py` | 21 | application | `quantlab/assistant/ports/connection.py` | PR D slice 2b responsibility owner |
| `desktop_app/connection_composition.py` | 15 | composition | `desktop_app/connection_composition.py` | PR D slice 2b responsibility owner |
| `desktop_app/features/assistant/connection_presenter.py` | 233 | presentation | `desktop_app/features/assistant/connection_presenter.py` | PR D slice 2b responsibility owner |
| `desktop_app/features/capital_scenario/presenter.py` | 29 | presentation | `desktop_app/features/capital_scenario/presenter.py` | PR D slice 2b responsibility owner |
| `desktop_app/features/walk_forward/rows.py` | 56 | presentation | `desktop_app/features/walk_forward/rows.py` | PR D slice 2b responsibility owner |
| `quantlab/assistant/adapters/chatgpt/connection_worker.py` | 189 | infrastructure | `quantlab/assistant/adapters/chatgpt/connection_worker.py` | PR D slice 2b responsibility owner |
| `quantlab/assistant/adapters/chatgpt/connection_probe.py` | 72 | infrastructure | `quantlab/assistant/adapters/chatgpt/connection_probe.py` | PR D slice 2b responsibility owner |
| `quantlab/research_core/application/walk_forward_operations.py` | 204 | application | `quantlab/research_core/application/walk_forward_operations.py` | PR D slice 2b responsibility owner |
| `quantlab/research_core/application/walk_forward_projection.py` | 72 | application | `quantlab/research_core/application/walk_forward_projection.py` | PR D slice 2b responsibility owner |
| `quantlab/research_core/application/walk_forward_inputs.py` | 15 | application | `quantlab/research_core/application/walk_forward_inputs.py` | PR D slice 2b responsibility owner |

| `quantlab/assistant/adapters/chatgpt/account_paths.py` | 26 | infrastructure | `quantlab/assistant/adapters/chatgpt/account_paths.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/account_store.py` | 179 | infrastructure | `quantlab/assistant/adapters/chatgpt/account_store.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/account_summary.py` | 32 | infrastructure | `quantlab/assistant/adapters/chatgpt/account_summary.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/campaign_receipts.py` | 70 | infrastructure | `quantlab/assistant/adapters/chatgpt/campaign_receipts.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/finished_reconciliation.py` | 88 | infrastructure | `quantlab/assistant/adapters/chatgpt/finished_reconciliation.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/identity.py` | 221 | infrastructure | `quantlab/assistant/adapters/chatgpt/identity.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/loopback.py` | 92 | infrastructure | `quantlab/assistant/adapters/chatgpt/loopback.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/provenance.py` | 91 | infrastructure | `quantlab/assistant/adapters/chatgpt/provenance.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/resolution_audit.py` | 209 | infrastructure | `quantlab/assistant/adapters/chatgpt/resolution_audit.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/response_stream.py` | 167 | infrastructure | `quantlab/assistant/adapters/chatgpt/response_stream.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/transport.py` | 127 | infrastructure | `quantlab/assistant/adapters/chatgpt/transport.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/unknown_reconciliation.py` | 88 | infrastructure | `quantlab/assistant/adapters/chatgpt/unknown_reconciliation.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/adapters/chatgpt/vault.py` | 174 | infrastructure | `quantlab/assistant/adapters/chatgpt/vault.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/domain/auth_protocol.py` | 186 | domain | `quantlab/assistant/domain/auth_protocol.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/domain/auth_tokens.py` | 45 | domain | `quantlab/assistant/domain/auth_tokens.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/domain/plan_protocol.py` | 183 | domain | `quantlab/assistant/domain/plan_protocol.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/domain/source_components.py` | 28 | domain | `quantlab/assistant/domain/source_components.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/assistant/ports/auth.py` | 25 | application | `quantlab/assistant/ports/auth.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/research_core/domain/receipts.py` | 65 | domain | `quantlab/research_core/domain/receipts.py` | T4 extracted owner; behaviour preserved. |
| `quantlab/shared/runtime_errors.py` | 5 | shared | `quantlab/shared/runtime_errors.py` | T4 extracted owner; behaviour preserved. |
| `tools/refactor/adapt_test_paths.py` | 352 | tooling | `tools/refactor/adapt_test_paths.py` | T4 extracted owner; behaviour preserved. |
| `tools/refactor/extract_runtime_error.py` | 138 | tooling | `tools/refactor/extract_runtime_error.py` | T4 extracted owner; behaviour preserved. |
| `tools/refactor/move_desktop_app.py` | 394 | tooling | `tools/refactor/move_desktop_app.py` | T4 extracted owner; behaviour preserved. |
| `tools/refactor/repair_paths.py` | 283 | tooling | `tools/refactor/repair_paths.py` | T4 extracted owner; behaviour preserved. |
| `tools/refactor/split_core_assistant.py` | 200 | tooling | `tools/refactor/split_core_assistant.py` | PR D reproducible repair |
| `tools/refactor/split_core_lock_paths.py` | 97 | tooling | `tools/refactor/split_core_lock_paths.py` | PR D reproducible repair |
| `tools/refactor/split_core_profile.py` | 99 | tooling | `tools/refactor/split_core_profile.py` | PR D reproducible repair |
| `tools/refactor/split_core_slice1_references.py` | 77 | tooling | `tools/refactor/split_core_slice1_references.py` | PR D reproducible repair |
| `tools/refactor/split_core_test_paths.py` | 94 | tooling | `tools/refactor/split_core_test_paths.py` | PR D reproducible repair |
| `tools/refactor/split_core_ui.py` | 697 | tooling | `tools/refactor/split_core_ui.py` | PR D reproducible repair |
| `tools/refactor/verify_moves.py` | 258 | tooling | `tools/refactor/verify_moves.py` | T4 extracted owner; behaviour preserved. |

| `quantlab/assistant/domain/__init__.py` | 0 | domain | `quantlab/assistant/domain/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `quantlab/assistant/ports/__init__.py` | 0 | application | `quantlab/assistant/ports/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `quantlab/research_core/domain/__init__.py` | 0 | domain | `quantlab/research_core/domain/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `tools/refactor/split_core_r3c.py` | 246 | tooling | `tools/refactor/split_core_r3c.py` | PR D reproducible repair |
| `desktop_app/__init__.py` | 0 | presentation | `desktop_app/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/components/__init__.py` | 0 | presentation | `desktop_app/components/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/__init__.py` | 0 | presentation | `desktop_app/features/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/assistant/__init__.py` | 0 | presentation | `desktop_app/features/assistant/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/backtest/__init__.py` | 0 | presentation | `desktop_app/features/backtest/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/capital_scenario/__init__.py` | 0 | presentation | `desktop_app/features/capital_scenario/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/compare/__init__.py` | 0 | presentation | `desktop_app/features/compare/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/data/__init__.py` | 0 | presentation | `desktop_app/features/data/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/market/__init__.py` | 0 | presentation | `desktop_app/features/market/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/onboarding/__init__.py` | 0 | presentation | `desktop_app/features/onboarding/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/paper/__init__.py` | 0 | presentation | `desktop_app/features/paper/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/settings/__init__.py` | 0 | presentation | `desktop_app/features/settings/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/strategy/__init__.py` | 0 | presentation | `desktop_app/features/strategy/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/features/walk_forward/__init__.py` | 0 | presentation | `desktop_app/features/walk_forward/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/shell/__init__.py` | 0 | presentation | `desktop_app/shell/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `desktop_app/strings/__init__.py` | 0 | shared | `desktop_app/strings/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `quantlab/assistant/__init__.py` | 0 | shared | `quantlab/assistant/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `quantlab/assistant/adapters/__init__.py` | 0 | infrastructure | `quantlab/assistant/adapters/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `quantlab/assistant/adapters/chatgpt/__init__.py` | 0 | infrastructure | `quantlab/assistant/adapters/chatgpt/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |
| `quantlab/shared/__init__.py` | 1 | shared | `quantlab/shared/__init__.py` | PR D extracted responsibility owner (r3c inventory completion) |

| `tools/refactor/split_core_r3d.py` | 206 | tooling | `tools/refactor/split_core_r3d.py` | PR D reproducible repair |

| `tools/refactor/split_core_r3f.py` | 146 | tooling | `tools/refactor/split_core_r3f.py` | PR D reproducible repair |

## 3 跨層匯入違規（GitNexus + AST）

### 3.1 靜態匯入明細

依第 2 節分層，**145 筆、50 檔**。其中包含 2 筆 `shiboken6`：它是 Qt binding 輔助套件，但 3.1 白名單只明列 PySide6，本盤點採字面規則列為既有例外，不暗自擴大可用 SDK。被匯入的模組即使只有某個常數被使用，也按整個模組的層計算；不能因匯入移到函式內就豁免。

下列「位置」即 importer 的 `path.py:line`，箭頭右側是已解析的 imported module。這是未套用 allowlist 的現況；G3 的既有違規也保留可見。R1 應從這份人工分層及完整掃描建立有理由、只能縮減的 allowlist，不在本 slice 修改 gate 或 allowlist。

| 位置（importer） → imported module | 違反規則（3.1） |
|---|---|
| `desktop_automatic_backup.py:6` → `quantlab.automatic_backup` | presentation 不得依賴 infrastructure |
| `desktop_automatic_backup.py:88` → `quantlab.analysis_recovery` | presentation 不得依賴 infrastructure |
| `desktop_capital_scenario.py:6` → `quantlab.desktop_feedback` | application 不得依賴 presentation |
| `desktop_capital_scenario.py:9` → `desktop_walk_forward` | application 不得依賴 presentation |
| `desktop_capital_scenario.py:45` → `desktop_pages.job_progress` | application 不得依賴 presentation |
| `desktop_charts.py:21` → `quantlab.chart_drawings` | presentation 不得依賴 infrastructure |
| `desktop_chatgpt_auth.py:437` → `quantlab.desktop_runtime` | infrastructure 不得依賴 application 服務實作（非 port） |
| `desktop_chatgpt_auth.py:465` → `quantlab.desktop_runtime` | infrastructure 不得依賴 application 服務實作（非 port） |
| `desktop_chatgpt_provider.py:34` → `quantlab.research` | infrastructure 不得依賴 application 服務實作（非 port） |
| `desktop_chatgpt_provider.py:1314` → `quantlab.research_analysis` | infrastructure 不得依賴 application 服務實作（非 port） |
| `desktop_chatgpt_provider.py:1328` → `quantlab.research_analysis` | infrastructure 不得依賴 application 服務實作（非 port） |
| `desktop_chatgpt_provider.py:1377` → `quantlab.research_analysis` | infrastructure 不得依賴 application 服務實作（非 port） |
| `desktop_chatgpt_provider.py:1411` → `quantlab.research_analysis` | infrastructure 不得依賴 application 服務實作（非 port） |
| `desktop_chatgpt_ui.py:1312` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_chatgpt_ui.py:1313` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_chatgpt_ui.py:1384` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_chatgpt_ui.py:1438` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_chatgpt_ui.py:1439` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_expiry_inputs.py:7` → `quantlab.taifex_expiries` | presentation 不得依賴 infrastructure |
| `desktop_forms.py:323` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_forms.py:329` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_forms.py:370` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_forms.py:457` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_forms.py:571` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_market.py:113` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_market.py:888` → `quantlab.market_history` | presentation 不得依賴 infrastructure |
| `desktop_market.py:908` → `quantlab.market_history` | presentation 不得依賴 infrastructure |
| `desktop_market_workspace.py:12` → `desktop_market_layout` | presentation 不得依賴 infrastructure |
| `desktop_pages/assistant_completion.py:11` → `quantlab.agent_skills` | presentation 不得依賴 infrastructure |
| `desktop_pages/assistant_runtime.py:18` → `desktop_pages.assistant_models` | application 不得依賴 presentation |
| `desktop_pages/assistant_runtime.py:58` → `desktop_chatgpt_auth` | application 不得依賴 infrastructure |
| `desktop_pages/assistant_runtime.py:61` → `desktop_chatgpt_provider` | application 不得依賴 infrastructure |
| `desktop_pages/backtest.py:3` → `quantlab.strict_json` | presentation 不得依賴 infrastructure |
| `desktop_pages/backtest.py:9` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_pages/backtest.py:183` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_pages/backup_inspection.py:8` → `quantlab.backup_inspection` | presentation 不得依賴 infrastructure |
| `desktop_pages/compare.py:7` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_pages/compare.py:254` → `quantlab.analysis_recovery` | presentation 不得依賴 infrastructure |
| `desktop_pages/compare.py:313` → `quantlab.analysis_recovery` | presentation 不得依賴 infrastructure |
| `desktop_pages/connection_test.py:86` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_pages/connection_test.py:89` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_pages/maintenance.py:15` → `quantlab.payload_cleanup` | presentation 不得依賴 infrastructure |
| `desktop_pages/maintenance.py:16` → `quantlab.update_check` | presentation 不得依賴 infrastructure |
| `desktop_pages/market.py:5` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_pages/market.py:8` → `quantlab.chart_drawings` | presentation 不得依賴 infrastructure |
| `desktop_pages/market.py:70` → `quantlab.market_providers` | presentation 不得依賴 infrastructure |
| `desktop_pages/market.py:111` → `quantlab.market_history` | presentation 不得依賴 infrastructure |
| `desktop_pages/market.py:161` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_pages/paper.py:12` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_pages/paper_layout.py:10` → `quantlab.strict_json` | presentation 不得依賴 infrastructure |
| `desktop_pages/paper_readiness.py:5` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_pages/paper_tabs.py:3` → `quantlab.strict_json` | presentation 不得依賴 infrastructure |
| `desktop_pages/paper_tabs.py:9` → `shiboken6` | presentation 不得依賴外部 SDK（3.1 明列僅 PySide6） |
| `desktop_pages/preferences.py:4` → `quantlab.runtime_support` | presentation 不得依賴 infrastructure |
| `desktop_pages/quick_start.py:7` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_pages/result_widgets.py:5` → `shiboken6` | presentation 不得依賴外部 SDK（3.1 明列僅 PySide6） |
| `desktop_pages/settings.py:134` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_pages/strategy.py:6` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_pages/strategy.py:368` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_pages/views.py:7` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_pages/widgets.py:6` → `quantlab.strict_json` | presentation 不得依賴 infrastructure |
| `desktop_presentation.py:125` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:23` → `quantlab.reporting` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:124` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:127` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:290` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:318` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:321` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:494` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:497` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:516` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:519` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:526` → `quantlab.analysis_recovery` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:543` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:546` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:553` → `quantlab.analysis_recovery` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:568` → `quantlab.analysis_recovery` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:588` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:591` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:620` → `quantlab.runtime_support` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:633` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_ui.py:709` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_ui.py:721` → `quantlab.manual_exchange` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:774` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_ui.py:795` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:798` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:807` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_ui.py:854` → `quantlab.data` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:883` → `quantlab.market_history` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:904` → `quantlab.market_providers` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1066` → `quantlab.downloads` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1094` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1097` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1100` → `quantlab.idea_search` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1148` → `desktop_chatgpt_auth` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1151` → `desktop_chatgpt_provider` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1202` → `quantlab.manual_exchange` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1205` → `quantlab.__main__` | presentation 不得依賴 composition |
| `desktop_ui.py:1341` → `quantlab.data` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1674` → `quantlab.analysis_recovery` | presentation 不得依賴 infrastructure |
| `desktop_ui.py:1814` → `quantlab.analysis_recovery` | presentation 不得依賴 infrastructure |
| `quantlab/agent_read_tools.py:25` → `quantlab.reporting` | application 不得依賴 infrastructure |
| `quantlab/agent_skills.py:14` → `quantlab.agent_tools` | infrastructure 不得依賴 application 服務實作（非 port） |
| `quantlab/analysis_contracts.py:8` → `quantlab.research` | domain 不得依賴 application 服務實作（非 port） |
| `quantlab/automatic_backup.py:20` → `quantlab.desktop_runtime` | infrastructure 不得依賴 application 服務實作（非 port） |
| `quantlab/backup_inspection.py:15` → `quantlab.desktop_runtime` | infrastructure 不得依賴 application 服務實作（非 port） |
| `quantlab/data_gap_report.py:8` → `quantlab.desktop_errors` | application 不得依賴 presentation |
| `quantlab/data_gap_report.py:98` → `quantlab.data` | application 不得依賴 infrastructure |
| `quantlab/desktop_errors.py:29` → `quantlab.runtime_support` | presentation 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:31` → `quantlab.runtime_support` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:550` → `quantlab.desktop_errors` | application 不得依賴 presentation |
| `quantlab/desktop_runtime.py:586` → `quantlab.desktop_errors` | application 不得依賴 presentation |
| `quantlab/desktop_runtime.py:651` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:676` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:740` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:802` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:870` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:957` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:1009` → `quantlab.__main__` | application 不得依賴 composition |
| `quantlab/desktop_runtime.py:1038` → `quantlab.desktop_errors` | application 不得依賴 presentation |
| `quantlab/desktop_runtime.py:1311` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:1413` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:1431` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:1541` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/desktop_runtime.py:1544` → `quantlab.analysis_recovery_windows` | application 不得依賴 infrastructure |
| `quantlab/diagnostics.py:8` → `quantlab.desktop_feedback` | application 不得依賴 presentation |
| `quantlab/download_import.py:11` → `quantlab.data` | application 不得依賴 infrastructure |
| `quantlab/download_import.py:13` → `quantlab.reporting` | application 不得依賴 infrastructure |
| `quantlab/download_import.py:14` → `quantlab.runtime_support` | application 不得依賴 infrastructure |
| `quantlab/download_import.py:154` → `quantlab.downloads` | application 不得依賴 infrastructure |
| `quantlab/idea_research.py:23` → `quantlab.idea_search` | application 不得依賴 infrastructure |
| `quantlab/idea_research.py:36` → `quantlab.reporting` | application 不得依賴 infrastructure |
| `quantlab/idea_research.py:37` → `quantlab.response_output` | application 不得依賴 infrastructure |
| `quantlab/idea_research.py:39` → `quantlab.web_fetch` | application 不得依賴 infrastructure |
| `quantlab/manual_exchange.py:20` → `quantlab.research` | infrastructure 不得依賴 application 服務實作（非 port） |
| `quantlab/paper_replay.py:18` → `quantlab.data` | application 不得依賴 infrastructure |
| `quantlab/provider.py:131` → `quantlab.research` | infrastructure 不得依賴 application 服務實作（非 port） |
| `quantlab/reporting.py:32` → `quantlab.research_analysis` | infrastructure 不得依賴 application 服務實作（非 port） |
| `quantlab/research.py:9` → `quantlab.runtime_support` | application 不得依賴 infrastructure |
| `quantlab/research_analysis.py:469` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/research_analysis.py:486` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/research_analysis.py:507` → `quantlab.analysis_recovery` | application 不得依賴 infrastructure |
| `quantlab/saved_candidate_pool.py:28` → `quantlab.data` | application 不得依賴 infrastructure |
| `quantlab/walk_forward.py:30` → `quantlab.data` | application 不得依賴 infrastructure |
| `quantlab/walk_forward.py:32` → `quantlab.runtime_support` | application 不得依賴 infrastructure |

### 3.2 最大違規群的 GitNexus 補充

使用目前工作樹的 `context` 與 upstream `impact`，以符號及 `file_path` 消除同名歧義；下列數字為查詢回傳的影響數，不等同匯入違規數，也不取代測試。

| 違規群／定位 | 圖譜與原始碼交叉確認 | 後續意義 |
|---|---|---|
| `desktop_ui.py:1284`，39 筆匯入違規 | `context(execute_ui_operation)` 顯示 preview 的 `build_window` 與多組分析／研究測試呼叫；outgoing 只列 `_root`、`ui_text`。`impact` 為 LOW、direct 1、total 3、processes 0（預設不含測試）。原始碼 `desktop_ui.py:1248` 的 handler dict 與 `desktop_ui.py:1302` 的動態派送另證明 worker 路徑，`desktop_ui.py:1312` 註冊 callback。 | 圖譜未展開 dict handler 不代表沒有工作流程。C 拆視窗，D 拆 worker／provider 接線；驗證 spawn registrar 與字串 patch 路徑。 |
| `quantlab/desktop_runtime.py:1219`，16 筆匯入違規 | `context(JobManager)` 顯示 `desktop.py`、`desktop_ui.py`、assistant runtime、設定／比較／策略頁匯入，以及 `tools/bench_worker_latency.py` 的 `job_sample` 呼叫；`impact` 回報 **HIGH**、direct 26、total 65、`processes_affected=2`，列出 benchmark 的 `job_sample`／`main`。 | 後續 D 必須揭露 HIGH；工作排程、備份、vault、復原與 OS process 控制不能一次當成純搬檔。圖譜列出的 process 不涵蓋所有動態 GUI 路徑。 |
| `desktop_chatgpt_provider.py:1127`，5 筆匯入違規；UI 另有 5 筆 | `context(ChatGPTPlanProvider)` 顯示 `desktop_ui.py`、`desktop_chatgpt_ui.py`、`desktop_pages/assistant_runtime.py`、`desktop_pages/connection_test.py` 的匯入，以及測試中的 `SyntheticPlanProvider` 繼承。`impact` 為 MEDIUM、direct 6、total 28、processes 0。 | 涉及連線、對話、研究與 reconciliation，不只單一畫面；G3 本體保留，由非 G3 application port／composition 限縮新呼叫端。 |

新文件在圖譜中尚不存在：對 `docs/analysis/08_REFACTOR_INVENTORY.md` 的 impact 回報 `UNKNOWN / Target not found`。已用檔案存在檢查與 `git grep` 確認原先只有 07 的預期產出引用；本次僅新增文件，沒有將 UNKNOWN 解讀為程式碼安全或死碼證據。

## 4 匯入期副作用與載入順序

只解析原始碼，不透過 import 驗證，避免意外執行打包腳本。檢查模組頂層、條件分支、class body、decorator／預設引數，並追讀頂層直接呼叫的本地函式；區分「正常 import」、「特定 frozen／script 條件成立」與「之後呼叫函式」。一般常數、dataclass 定義、純字串／數值計算不算外部 IO。

### 4.1 已確認的檔案 IO、環境修改與 hook

| 位置 | 觸發條件與副作用 |
|---|---|
| `packaging/collect_licenses.py:58`、`packaging/collect_licenses.py:63` | 頂層直接讀 notice archive／Qt notices 與 distribution metadata；並非只定義函式。 |
| `packaging/collect_licenses.py:67`、`packaging/collect_licenses.py:76`、`packaging/collect_licenses.py:80`、`packaging/collect_licenses.py:87`、`packaging/collect_licenses.py:90` | 建目錄、複製 license、寫入 notice archive／Qt notices；import 即可能改動 build output。 |
| `packaging/build_broker_portable.py:20` | 頂層 `runpy.run_path` 讀取並執行 `broker_package.py`；不代表當場 build 或登入 SDK。 |
| `packaging/sqlite_runtime_hook.py:7` | frozen 啟動 hook 直接 `verify`；`quantlab/sqlite_runtime.py:39` 的實作讀 pin、開記憶體 SQLite 並驗證已載入 library bytes。普通環境缺 `_MEIPASS` 也可能直接失敗。 |
| `packaging/broker_probe_runtime_hook.py:11`、`packaging/broker_probe_runtime_hook.py:12` | 只在 frozen 且明確 `--broker-sdk-probe` 時 `runpy` 執行 probe、寫出驗證報告並退出；`packaging/broker_probe.py:37` 會載入 SDK，仍不建 client／登入。 |
| `packaging/early_multiprocessing_runtime_hook.py:14` | 只在 Windows frozen child 的 `is_forking` 條件下 `freeze_support()`，可能直接派送 worker；需保持早於 Qt。 |
| `packaging/desktop_regression.py:25` | 頂層 `sys.path.insert`。 |
| `packaging/validate_tls.py:13` | ROOT 尚未存在於 `sys.path` 時插入。 |
| `tools/bench_backtest_scale.py:14`、`tools/bench_worker_latency.py:20` | 頂層插入 repo root 至 `sys.path`。 |
| `tools/diagnose_paper_replay.py:20`、`tools/diagnose_paper_replay.py:21` | 修改 `sys.path`，並以 `os.environ.setdefault` 設定 `QT_QPA_PLATFORM=offscreen`。 |
| `tools/diagnose_research_phases.py:24`、`tools/install_desktop_auth.py:22` | ROOT 不在搜尋路徑時修改 `sys.path`。 |
| `tools/lm1_slice1_probe.py:13`、`tools/run_test_group.py:32`、`tools/ui_redesign_preview.py:12` | 頂層修改 `sys.path`。 |
| `tools/research_app.py:18` | `__package__` 為空／None 的 script 載入方式才修改 `sys.path`；不是每種 package import 都會觸發。 |
| `tools/ui_test_gate.py:17`、`tools/update_taifex_expiries.py:13`、`tools/validate_core_shards.py:22` | 頂層或 ROOT 缺席條件下修改 `sys.path`。 |
| `tools/validate_market_download.py:13`、`tools/validate_market_history_import.py:15`、`tools/validate_real_ai.py:26`、`tools/validate_web_search.py:20` | 頂層或 ROOT 缺席條件下修改 `sys.path`；搬檔須重核相對父目錄。 |

### 4.2 記憶體註冊與載入順序

| 位置 | 副作用與限制 |
|---|---|
| `desktop_ui.py:9`、`desktop_ui.py:1312`、`desktop_ui.py:1313` | 查詢 worker import 狀態，向 runtime 註冊 executor 與 registrar 字串；普通 UI 與 worker 載入走不同 Qt 分支。改檔名須同步更新字串，不能只改 Python import。 |
| `quantlab/desktop_runtime.py:69`、`quantlab/desktop_runtime.py:71` | 建立 executor registry 與 ContextVar；是記憶體狀態，沒有因此建立 GUI、vault、檔案或 worker。 |
| `quantlab/agent_tools.py:122`、`quantlab/agent_tools.py:123`、`quantlab/agent_read_tools.py:332` | 建立並填入工具 registry；`create_registry` 註冊 handler，不在 import 當下執行讀取工作。 |
| `quantlab/trading/application/live_market.py:38`、`quantlab/trading/application/readiness_session.py:71`、`quantlab/trading/application/research.py:46`、`quantlab/trading/application/state.py:101` | 頂層註冊 codec DTO，修改 `quantlab/trading/application/codec.py:20` 的 `_TYPES`。 |
| `quantlab/trading/runtime/bootstrap.py:62`、`quantlab/trading/runtime/config.py:172`、`quantlab/trading/runtime/protocol.py:69` | 頂層註冊 runtime wire 型別；路徑參與型別識別，故本輪保持交易核心路徑。 |
| `quantlab/trading/application/errors.py:46`、`quantlab/trading/application/errors.py:47` | 匯入即檢查錯誤碼重疊，發現碰撞會 raise；不可當成無條件可刪的防禦碼。 |
| `docs/script samples/strategy_sample.py:102` | class body 建立 `Position()`；範例還依賴歷史 `trader` 模組，不能當成可安全 import 的產品模組。 |

### 4.3 Qt／第三方模組載入（不等同建立應用程式）

以下是靜態上會在模組／class 定義階段遇到的第三方 import 位置，條件分支未證明成立者亦保留。Qt import 可能載入 native binding／DLL；不宣稱它會呼叫 `QApplication` 或讀取使用者設定。函式內的延遲 import 不列在此表。`desktop_ui.py` 的 Qt 分支另外受 `_worker_import` 控制。

| 模組 | 頂層 import 定位與目標 |
|---|---|
| `desktop_accessibility.py` | `desktop_accessibility.py:3` → `PySide6.QtCore`；`desktop_accessibility.py:4` → `PySide6.QtWidgets` |
| `desktop_automatic_backup.py` | `desktop_automatic_backup.py:4` → `PySide6.QtCore`；`desktop_automatic_backup.py:5` → `PySide6.QtWidgets` |
| `desktop_chart_popout.py` | `desktop_chart_popout.py:3` → `PySide6.QtCore`；`desktop_chart_popout.py:4` → `PySide6.QtGui`；`desktop_chart_popout.py:5` → `PySide6.QtWidgets` |
| `desktop_charts.py` | `desktop_charts.py:18` → `PySide6.QtCore`；`desktop_charts.py:19` → `PySide6.QtGui`；`desktop_charts.py:20` → `PySide6.QtWidgets` |
| `desktop_chatgpt_ui.py` | `desktop_chatgpt_ui.py:17` → `PySide6.QtCore`；`desktop_chatgpt_ui.py:18` → `PySide6.QtWidgets` |
| `desktop_expiry_inputs.py` | `desktop_expiry_inputs.py:3` → `PySide6.QtCore`；`desktop_expiry_inputs.py:4` → `PySide6.QtWidgets` |
| `desktop_forms.py` | `desktop_forms.py:18` → `PySide6.QtCore`；`desktop_forms.py:19` → `PySide6.QtWidgets` |
| `desktop_help.py` | `desktop_help.py:3` → `PySide6.QtCore`；`desktop_help.py:4` → `PySide6.QtWidgets` |
| `desktop_icon.py` | `desktop_icon.py:5` → `PySide6.QtGui`；`desktop_icon.py:6` → `PySide6.QtWidgets` |
| `desktop_market.py` | `desktop_market.py:15` → `PySide6.QtCore`；`desktop_market.py:16` → `PySide6.QtWidgets` |
| `desktop_market_workspace.py` | `desktop_market_workspace.py:7` → `PySide6.QtCore`；`desktop_market_workspace.py:8` → `PySide6.QtGui`；`desktop_market_workspace.py:9` → `PySide6.QtWidgets` |
| `desktop_order_lines.py` | `desktop_order_lines.py:6` → `PySide6.QtCore`；`desktop_order_lines.py:7` → `PySide6.QtGui` |
| `desktop_pages/app_header.py` | `desktop_pages/app_header.py:5` → `PySide6.QtCore`；`desktop_pages/app_header.py:6` → `PySide6.QtWidgets` |
| `desktop_pages/assistant.py` | `desktop_pages/assistant.py:3` → `PySide6.QtCore`；`desktop_pages/assistant.py:4` → `PySide6.QtGui`；`desktop_pages/assistant.py:5` → `PySide6.QtWidgets` |
| `desktop_pages/assistant_completion.py` | `desktop_pages/assistant_completion.py:6` → `PySide6.QtCore`；`desktop_pages/assistant_completion.py:7` → `PySide6.QtWidgets` |
| `desktop_pages/assistant_details.py` | `desktop_pages/assistant_details.py:7` → `PySide6.QtCore`；`desktop_pages/assistant_details.py:8` → `PySide6.QtWidgets` |
| `desktop_pages/assistant_manifest.py` | `desktop_pages/assistant_manifest.py:5` → `PySide6.QtCore`；`desktop_pages/assistant_manifest.py:6` → `PySide6.QtWidgets` |
| `desktop_pages/assistant_models.py` | `desktop_pages/assistant_models.py:5` → `PySide6.QtCore`；`desktop_pages/assistant_models.py:6` → `PySide6.QtWidgets` |
| `desktop_pages/assistant_permissions.py` | `desktop_pages/assistant_permissions.py:5` → `PySide6.QtCore`；`desktop_pages/assistant_permissions.py:6` → `PySide6.QtWidgets` |
| `desktop_pages/async_status.py` | `desktop_pages/async_status.py:3` → `PySide6.QtCore`；`desktop_pages/async_status.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/backtest.py` | `desktop_pages/backtest.py:4` → `PySide6.QtCore`；`desktop_pages/backtest.py:5` → `PySide6.QtGui`；`desktop_pages/backtest.py:6` → `PySide6.QtWidgets` |
| `desktop_pages/backtest_summary_card.py` | `desktop_pages/backtest_summary_card.py:3` → `PySide6.QtWidgets` |
| `desktop_pages/backup_inspection.py` | `desktop_pages/backup_inspection.py:3` → `PySide6.QtCore`；`desktop_pages/backup_inspection.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/chatgpt_reconciliation.py` | `desktop_pages/chatgpt_reconciliation.py:3` → `PySide6.QtCore`；`desktop_pages/chatgpt_reconciliation.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/command_palette.py` | `desktop_pages/command_palette.py:3` → `PySide6.QtCore`；`desktop_pages/command_palette.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/compare.py` | `desktop_pages/compare.py:8` → `PySide6.QtCore`；`desktop_pages/compare.py:9` → `PySide6.QtWidgets` |
| `desktop_pages/compare_equity.py` | `desktop_pages/compare_equity.py:8` → `PySide6.QtCore`；`desktop_pages/compare_equity.py:9` → `PySide6.QtGui`；`desktop_pages/compare_equity.py:10` → `PySide6.QtWidgets` |
| `desktop_pages/compare_table.py` | `desktop_pages/compare_table.py:6` → `PySide6.QtCore` |
| `desktop_pages/connection_test.py` | `desktop_pages/connection_test.py:6` → `PySide6.QtCore`；`desktop_pages/connection_test.py:7` → `PySide6.QtWidgets` |
| `desktop_pages/data.py` | `desktop_pages/data.py:1` → `PySide6.QtCore`；`desktop_pages/data.py:2` → `PySide6.QtWidgets` |
| `desktop_pages/data_gaps.py` | `desktop_pages/data_gaps.py:6` → `PySide6.QtCore`；`desktop_pages/data_gaps.py:7` → `PySide6.QtGui`；`desktop_pages/data_gaps.py:8` → `PySide6.QtWidgets` |
| `desktop_pages/design.py` | `desktop_pages/design.py:3` → `PySide6.QtCore`；`desktop_pages/design.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/diagnostics.py` | `desktop_pages/diagnostics.py:5` → `PySide6.QtWidgets` |
| `desktop_pages/download_import.py` | `desktop_pages/download_import.py:3` → `PySide6.QtWidgets` |
| `desktop_pages/equity.py` | `desktop_pages/equity.py:5` → `PySide6.QtCore`；`desktop_pages/equity.py:6` → `PySide6.QtGui`；`desktop_pages/equity.py:7` → `PySide6.QtWidgets` |
| `desktop_pages/error_guidance.py` | `desktop_pages/error_guidance.py:3` → `PySide6.QtCore`；`desktop_pages/error_guidance.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/idea_research.py` | `desktop_pages/idea_research.py:9` → `PySide6.QtCore`；`desktop_pages/idea_research.py:10` → `PySide6.QtGui`；`desktop_pages/idea_research.py:11` → `PySide6.QtWidgets` |
| `desktop_pages/job_progress.py` | `desktop_pages/job_progress.py:6` → `PySide6.QtWidgets` |
| `desktop_pages/log_table.py` | `desktop_pages/log_table.py:8` → `PySide6.QtWidgets` |
| `desktop_pages/maintenance.py` | `desktop_pages/maintenance.py:9` → `PySide6.QtCore`；`desktop_pages/maintenance.py:10` → `PySide6.QtWidgets` |
| `desktop_pages/market.py` | `desktop_pages/market.py:2` → `PySide6.QtWidgets` |
| `desktop_pages/notifications.py` | `desktop_pages/notifications.py:6` → `PySide6.QtCore`；`desktop_pages/notifications.py:7` → `PySide6.QtGui`；`desktop_pages/notifications.py:8` → `PySide6.QtWidgets` |
| `desktop_pages/onboarding.py` | `desktop_pages/onboarding.py:3` → `PySide6.QtWidgets` |
| `desktop_pages/paper.py` | `desktop_pages/paper.py:6` → `PySide6.QtCore`；`desktop_pages/paper.py:13` → `PySide6.QtWidgets` |
| `desktop_pages/paper_layout.py` | `desktop_pages/paper_layout.py:3` → `PySide6.QtCore`；`desktop_pages/paper_layout.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/paper_tabs.py` | `desktop_pages/paper_tabs.py:6` → `PySide6.QtCore`；`desktop_pages/paper_tabs.py:7` → `PySide6.QtGui`；`desktop_pages/paper_tabs.py:8` → `PySide6.QtWidgets`；`desktop_pages/paper_tabs.py:9` → `shiboken6` |
| `desktop_pages/preferences.py` | `desktop_pages/preferences.py:3` → `PySide6.QtWidgets` |
| `desktop_pages/quick_start.py` | `desktop_pages/quick_start.py:3` → `PySide6.QtWidgets` |
| `desktop_pages/redesign_strategy_layout.py` | `desktop_pages/redesign_strategy_layout.py:3` → `PySide6.QtCore`；`desktop_pages/redesign_strategy_layout.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/replay_controls.py` | `desktop_pages/replay_controls.py:3` → `PySide6.QtCore`；`desktop_pages/replay_controls.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/result_panels.py` | `desktop_pages/result_panels.py:3` → `PySide6.QtWidgets` |
| `desktop_pages/result_widgets.py` | `desktop_pages/result_widgets.py:5` → `shiboken6`；`desktop_pages/result_widgets.py:7` → `PySide6.QtCore`；`desktop_pages/result_widgets.py:8` → `PySide6.QtGui`；`desktop_pages/result_widgets.py:9` → `PySide6.QtWidgets` |
| `desktop_pages/settings.py` | `desktop_pages/settings.py:6` → `PySide6.QtCore`；`desktop_pages/settings.py:7` → `PySide6.QtGui`；`desktop_pages/settings.py:8` → `PySide6.QtWidgets` |
| `desktop_pages/settings_layout.py` | `desktop_pages/settings_layout.py:3` → `PySide6.QtCore`；`desktop_pages/settings_layout.py:4` → `PySide6.QtGui`；`desktop_pages/settings_layout.py:5` → `PySide6.QtWidgets` |
| `desktop_pages/shortcuts.py` | `desktop_pages/shortcuts.py:3` → `PySide6.QtGui`；`desktop_pages/shortcuts.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/strategy.py` | `desktop_pages/strategy.py:3` → `PySide6.QtWidgets` |
| `desktop_pages/strategy_tabs.py` | `desktop_pages/strategy_tabs.py:3` → `PySide6.QtCore`；`desktop_pages/strategy_tabs.py:4` → `PySide6.QtWidgets` |
| `desktop_pages/views.py` | `desktop_pages/views.py:8` → `PySide6.QtCore` |
| `desktop_pages/wf_wizard.py` | `desktop_pages/wf_wizard.py:3` → `PySide6.QtCore`；`desktop_pages/wf_wizard.py:4` → `PySide6.QtGui`；`desktop_pages/wf_wizard.py:5` → `PySide6.QtWidgets` |
| `desktop_pages/widgets.py` | `desktop_pages/widgets.py:4` → `PySide6.QtCore`；`desktop_pages/widgets.py:7` → `PySide6.QtWidgets` |
| `desktop_privacy.py` | `desktop_privacy.py:5` → `PySide6.QtCore`；`desktop_privacy.py:6` → `PySide6.QtWidgets` |
| `desktop_research_runtime.py` | `desktop_research_runtime.py:9` → `PySide6.QtCore`；`desktop_research_runtime.py:10` → `PySide6.QtGui` |
| `desktop_theme.py` | `desktop_theme.py:5` → `PySide6.QtCore`；`desktop_theme.py:6` → `PySide6.QtGui`；`desktop_theme.py:7` → `PySide6.QtWidgets` |
| `desktop_timeinput.py` | `desktop_timeinput.py:10` → `PySide6.QtCore`；`desktop_timeinput.py:11` → `PySide6.QtWidgets` |
| `desktop_trading/broker_panel.py` | `desktop_trading/broker_panel.py:3` → `PySide6.QtCore`；`desktop_trading/broker_panel.py:4` → `PySide6.QtWidgets` |
| `desktop_trading/dashboard.py` | `desktop_trading/dashboard.py:7` → `PySide6.QtCore`；`desktop_trading/dashboard.py:8` → `PySide6.QtWidgets` |
| `desktop_trading/market_watch.py` | `desktop_trading/market_watch.py:9` → `PySide6.QtCore`；`desktop_trading/market_watch.py:10` → `PySide6.QtGui`；`desktop_trading/market_watch.py:11` → `PySide6.QtWidgets` |
| `desktop_trading/research_panel.py` | `desktop_trading/research_panel.py:3` → `PySide6.QtCore`；`desktop_trading/research_panel.py:4` → `PySide6.QtWidgets` |
| `desktop_trading/widgets.py` | `desktop_trading/widgets.py:3` → `PySide6.QtCore`；`desktop_trading/widgets.py:4` → `PySide6.QtWidgets` |
| `desktop_trading/window.py` | `desktop_trading/window.py:6` → `PySide6.QtCore`；`desktop_trading/window.py:7` → `PySide6.QtGui`；`desktop_trading/window.py:8` → `PySide6.QtWidgets` |
| `desktop_trading/wizard.py` | `desktop_trading/wizard.py:6` → `PySide6.QtCore`；`desktop_trading/wizard.py:8` → `PySide6.QtWidgets` |
| `desktop_trading/workspaces.py` | `desktop_trading/workspaces.py:4` → `PySide6.QtCore`；`desktop_trading/workspaces.py:5` → `PySide6.QtWidgets` |
| `desktop_ui.py` | `desktop_ui.py:1411` → `PySide6.QtCore`；`desktop_ui.py:1412` → `PySide6.QtGui`；`desktop_ui.py:1413` → `PySide6.QtWidgets` |
| `desktop_ui_polish.py` | `desktop_ui_polish.py:4` → `PySide6.QtCore`；`desktop_ui_polish.py:5` → `PySide6.QtWidgets` |
| `docs/script samples/strategy_sample.py` | `docs/script samples/strategy_sample.py:2` → `pandas` |
| `tools/generate_significance_goldens.py` | `tools/generate_significance_goldens.py:7` → `scipy` |
| `tools/generate_welch_goldens.py` | `tools/generate_welch_goldens.py:6` → `scipy` |
| `tools/research_app.py` | `tools/research_app.py:12` → `streamlit` |
| `tools/trading_load_probe.py` | `tools/trading_load_probe.py:25` → `PySide6.QtCore`；`tools/trading_load_probe.py:26` → `PySide6.QtTest`；`tools/trading_load_probe.py:27` → `PySide6.QtWidgets` |
| `tools/ui_theme_diff.py` | `tools/ui_theme_diff.py:11` → `PySide6.QtGui` |

### 4.4 明確排除的「呼叫期」動作

- `desktop.py:198`、`trading_runtime.py:65` 的 `QApplication(...)` 都在啟動函式內，**未發現本範圍模組於普通 import 時直接建立 QApplication**。工具的 `tools/lm1_slice1_probe.py:31`、`tools/trading_load_probe.py:222`、`tools/ui_readability_audit.py:131`、`tools/ui_redesign_preview.py:181`、`tools/ui_snapshot.py:219` 也都在函式／方法內。
- `quantlab/trading/adapters/shioaji/sdk_loader.py:16` 的 `import shioaji` 只在 `load_pinned_sdk()` 內；`desktop_chatgpt_auth.py:246` 的 `import jwt` 也在驗證函式內。本次沒有發現正常產品模組 import 會自動載入這兩個 SDK；第 4.1 的明確 frozen probe 是不同條件。
- `quantlab/backtest.py:370`、`quantlab/research.py:824`、`desktop_chatgpt_provider.py:441` 的來源檔雜湊讀取在執行／provenance 函式內，不誤列為 eager IO，但搬檔仍會破壞其路徑與身份契約。
- `quantlab/taifex_expiries.py:10` 只建立資料路徑，讀檔在 `quantlab/taifex_expiries.py:64` 的 `load_expiries()`；`Path(...)` 本身不是讀檔證據。`Path.resolve()` 等路徑正規化可能查詢檔案系統 metadata，與上述讀寫內容／建立應用程式分開理解。

## 5 G3 來源與歷史 producer 身份

擁有者已於 2026-10-29 明確批准本次重構搬移及拆分八個 G3 檔，前提是產品行為不變、QA 逐檔複核，並同步更新 CONTRIBUTING 鎖定清單。舊控制者的「全部保持原路徑與 bytes」裁定不再適用；A 不修改產品模組，B 只機械搬移與更新 import，D/E 依責任拆分。

- 目前八個 G3：`quantlab/research.py`、`quantlab/provider.py`、`quantlab/core.py`、`quantlab/strategies.py`、`quantlab/backtest.py`、`quantlab/data.py`、`quantlab/assistant/adapters/chatgpt/auth.py`、`quantlab/assistant/adapters/chatgpt/provider.py`。後兩檔由根目錄的 `desktop_chatgpt_auth.py`／`desktop_chatgpt_provider.py` 於 B 搬入；dependency manifest 同步到該 adapter 目錄。歷史 producer 的舊檔名 hash keys 保留作為身份，不代表檔案仍在根目錄。
- saved_candidate_pool 的歷史 producer profile 字面值原始 bytes、每個歷史 digest 與其安全判定逐位元保留，拆出資料模組時加原始 bytes 比對測試。不得重寫舊 profile 或讓新來源假冒歷史 producer；新來源用明確的新身份，舊結果仍以原 profile 驗證。
- `packaging/markauto.spec:22`、`packaging/markauto.spec:23` 將 auth/provider 來源資料複製到 `quantlab/assistant/adapters/chatgpt`（B 前目的地為 `.`）；同檔第 24 行將 dependency manifest 放在相同目錄。engine 來源仍複製到 `quantlab`。這些資料檔是執行期來源 SHA-256/provenance 驗證的必要輸入：`quantlab/backtest.py:370` 讀取 core/data/strategies/backtest 原始 bytes 並計算 SHA-256，第 371 行將 source_hashes 寫入 result manifest；`quantlab/research.py:824`、`quantlab/research.py:825` 對 research/provider/core/strategies/backtest 的 UTF-8 文字計算 engine source identity。B 同步資料目的地、來源查找與測試路徑；不能只更新 import 或刪掉驗證。D 拆分後完整來源集合仍需被驗證。
- quantlab/research.py 保留該模組名稱，新的研究責任使用 quantlab/research_core/，避免同名檔案與套件衝突。E 按第 10 節抽取 domain、port 與 adapter；既有檔若保留須有實際的流程責任，不能成為 re-export shim。

## 6 PR 順序與相依關係

**A -> B -> {C, D} -> E，恰好五個重構 PR。** 所有既有檔案的整檔搬移在 B 完成；C、D、E 是責任抽取與內容修改，不能再混入整檔重新命名。研究檔的 R0 目標表示 E 抽取責任的新落點，原始模組的剩餘實際責任可留原址；不為目錄整齊全面搬家。

| PR | 前置與可平行性 | 內容與界線 |
|---|---|---|
| A | 無 | 規格、完整 R0、R1、固定 92 筆原始違規身份、固定搬移映射與防新增測試、CI。不改產品模組。 |
| B | A | 102 個桌面來源整檔搬移；腳本批次更新 import、patch、registrar、套件與打包來源。auth/provider、market layout 歸 infrastructure；其餘依第 2 節，仍混有顯示依賴的 worker 先留 desktop_app。只改路徑，不改產品行為。 |
| C | B；與 D 在獨立 worktree 平行 | strings、shell/main window、forms、market、charts、idea UI 責任拆分；字串保留單一真正查詢入口。 |
| D | B；與 C 平行 | desktop_runtime、ChatGPT UI/control/auth/provider、saved candidate pool、worker 的核心責任拆分；用 ports 和 composition 接線，歷史 profile bytes 不變。 |
| E | C、D 合併 | R4 共用元件、R0 研究違規與過大檔的責任抽取；R5 死碼與過度防禦清理、刪 archives、更新架構與貢獻文件。E 不再拆成其他 PR。 |

B 的唯一 R0 落點修正：desktop_pages/__init__.py 搬至 desktop_app/shell/pages.py；shell/__init__.py 必須為空 metadata，保留 worker guard 先於 Qt 載入。其餘 101 對映以原始 A fixture 逐項比對，102 來源與 92 債務身份不變。

smoke 使用 desktop_app/smoke/，避免本機 packaging/ namespace 被已安裝 PyPI packaging 套件遮蔽。仍有 UI import 的 application worker 先純搬到 desktop_app/features/*/worker.py，D 再抽取核心責任；不在 B 引入 quantlab 反向依賴 UI。上述差異均是有證據的落點修正。

每個 PR 都需 upstream impact，揭露 HIGH/CRITICAL，commit 前完整 detect_changes；以腳本同步 import/patch/registrar。開發中跑相關群組，送 PR 前全測試與打包 smoke；CI 全綠、獨立 QA 後合併。擁有者已批准本機全測試的唯一例外：與最新 main 完全相同且僅由 symlink 權限造成的失敗，CI 各群仍須全綠。不得把檔案鎖、逾時、其他失敗列為例外。

### 6.1 R1 分層閘門與既有違規基線

- python tools/check_layers.py 掃描所有 tracked Python，排除 tests/、archives/；未分層、遺失、語法錯誤、新違規與 stale allowlist 都失敗。既有交易與品質閘門保持獨立。
- tools/layer_map.json 決定來源實際層，ports 只開放 application 契約。
- tools/layer_allowlist.json 初始 92 筆，對應 145 個匯入位置，固定原始 (path, target module, rule)；各筆理由保留。tests/test_layer_gate.py 原始 BASELINE 不重生。
- tools/layer_relocations.json 是本次 B 的固定一對一整檔映射，測試固定其 SHA-256。搬移後的 finding 只還原該來源與目標的 R0 身份；不准新增來源、目標或規則，原檔與新檔同時存在直接失敗，無法共用一筆豁免。allowlist 本身不因搬檔新增或重寫身份。
- CI 明確使用 --baseline-ref HEAD^，與 PR merge 的第一個 parent（main）或主線上一版比較，拒絕把已移除的舊債加回。最初主線尚無此閘門時，固定 92 筆測試仍限制首次基線。
- 測試保留所有 forbidden edges、ports、相對/別名/條件/局部 import、未分層、CLI 注入、stale、fake 新增與同數替換負測試；新增搬移身份不變、不能擴張/換目標、重複來源、已刪除債務不能恢復的負測試。CI 與完整 discovery 均包含本模組。

## 7 重複程式碼與共用候選

依規格 4.2，計算的是相同責任的出現處，不以三個呼叫或三個相似名稱湊數。`extract` 至少有三處；只有兩處的候選記為 `tolerate`，E 不為它新增抽象。既有共用元件可在 B 純搬移；下表的新合併工作全部由 **E** 擁有。C/D 先拆責任，E 再合併重複，不能把這些內容修改塞進 B。

GitNexus 先查詢 table/row/form/chart/async/provider 流程，再讀表列來源；例如圖中 `MarketWatchWidget.load_series` 的 completion callback 與 `MaintenancePanel.check_payloads -> AsyncStatus.set_state` 是不同工作流程，共用範圍只能是顯示，不是工作生命週期。

| 候選／判定 | 出現位置與相同責任 | 最低共同層／建議落點及合併界線 | PR |
|---|---|---|---|
| 表格填列與欄寬／`extract`（3 處） | `desktop_forms.py:1009` 的 `ResultTable.set_rows`；`desktop_pages/result_widgets.py:157` 的可排序填列；`desktop_forms.py:1240` 的 fills tooltip／欄寬處理 | `desktop_app/components/tables.py`：列到 item、header、欄寬上限與 tooltip 的呈現機制。不同欄位 schema、排序鍵、隱私遮罩、UTC/Taipei 顯示仍由各 rows adapter 提供；不把 financial/raw role 或缺值語意丟掉。 | E |
| row 的金額／缺值格式化／`extract`（3 處） | `desktop_forms.py:1090` 的 `_report_number`；`desktop_presentation.py:69` 的 `display_number`；`desktop_pages/result_widgets.py:69` 的 `shown` | `desktop_app/components/formatting.py`：共用顯示數值解析與格式策略；保留 missing、undefined、zero、diagnostics_required 的差異，保留報告精度與百分比／金額分支。只投影，不把四捨五入結果寫回研究資料。 | E |
| 表單欄位／`extract`（3 處） | `desktop_forms.py:125` 的 label、buddy、accessibleName；`desktop_pages/data.py:150` 的檔案欄位；`desktop_market.py:101` 的 `_named`（用於 `desktop_market.py:804` 的月份欄位） | `desktop_app/components/fields.py`：命名、可及性、label/buddy 與欄位容器。日期／Decimal／選項驗證留給相應輸入 adapter；不以一個萬用表單取代各功能的明確 payload。 | E |
| 驗證提示顯示／`extract`（3 處） | `desktop_ui.py:1662` 的 `form_feedback`；`desktop_pages/error_guidance.py:54` 的 `run_inline`；`desktop_market.py:1000` 的 `accept_import` 錯誤 label | `desktop_app/components/validation_feedback.py`：固定錯誤碼到 label／下一步的呈現。各入口的驗證與 confirm 保留；不把 exception 原文、路徑或憑證傳給共用 renderer。 | E |
| 圖表 widget／`tolerate`（2 個 candlestick host，已共用實作） | `desktop_market.py:1160` 的 dashboard chart；`desktop_chart_popout.py:56` 的 popout chart | 既有 `CandlestickChart` 到 `desktop_app/components/charts.py`，C 的內部拆分見第 10 節。兩處都已用同一 class，不再抽 ChartFactory／基底階層；`desktop_pages/compare_equity.py:94` 是 equity overlay，不能冒充第三個 candlestick 實作。 | E（保留既有共用，無新增抽取） |
| 非同步狀態顯示／`extract`（3 處） | `desktop_pages/async_status.py:35` 的 loading/empty/error/stale；`desktop_market.py:271` 的 loading 標籤；`desktop_pages/idea_research.py:544` 的工作結果標籤 | `desktop_app/components/async_status.py`：狀態文字、錯誤碼與 action 可見性。各 presenter 把自己的狀態映射到顯示值；`desktop_pages/job_progress.py:38` 的取消防重入、worker deadline、unknown 不重試等仍由原 owner 控制。 | E |
| 外部行情服務 port／`tolerate`（2 個官方日資料來源） | `quantlab/market_providers.py:146` 的 TWSE parser；`quantlab/market_providers.py:202` 的 TAIFEX parser；共用 transport 已在 `quantlab/market_providers.py:504` 注入 | 若第三種同契約 transport 出現，純 `str -> bytes` 契約候選落點為 `quantlab/shared/http_types.py`（只依賴標準函式庫）；本輪保留注入點，不新增通用 HTTP 基底類。行情 `MarketSeries` 等業務型別的 port 應由 `quantlab/research_core/ports/` 擁有，不能放進 shared 後反向 import domain。ChatGPT G3 與 v2 broker 契約不是第三個相同 port，不能為共用而改它們。 | E（保留／檢查 port 邊界） |
| aware timestamp 轉換／`extract`（3 處） | `desktop_forms.py:1231` 的 ISO/Z 解析；`desktop_pages/result_widgets.py:61` 的 ISO/Z 解析；`quantlab/market_history.py:66` 的 session ISO/Z 解析 | `quantlab/shared/time.py`：純 aware ISO 解析／UTC 正規化，不依賴 UI 或 domain。各入口仍保留自己的長度、timezone、錯誤型別檢查；UTC 與 Taipei 的最後格式化留在 presentation。不得把 naive timestamp 默認成任何時區。 | E |

不同 JSON 設定不視為可直接合併：`quantlab/market_history.py:55` 使用 `ensure_ascii=False, allow_nan=False`，`quantlab/chart_drawings.py:103` 的 Unicode 預設不同，`quantlab/market_providers.py:472` 的 cache 編碼設定也不同。它們會影響 bytes／digest，不能只因都呼叫 `json.dumps` 就共用同一預設；G3 的 canonical/hash 更不在抽取範圍。

## 8 死碼候選

本節列「圖上沒有直接呼叫」的候選與實際處置，不將它當成可刪清單。查詢綁定 `C:/Users/Mark/Desktop/Mark auto`，索引 commit／來源基線交叉確認同第 1 節。以 GitNexus `context` 與 upstream `impact` 核對，CLI 重現例：

```powershell
node .gitnexus/run.cjs context _training_status --repo .
node .gitnexus/run.cjs impact _training_status --direction upstream --repo .
```

其餘使用相同索引的 MCP context/impact（同名時指定 `file_path`）。下表的 `UNKNOWN / 0 / 0` 分別是 risk、direct callers、affected processes，**不是 LOW**。`_WorkerBindings` 雖沒有建構呼叫，impact 仍辨識到模組 import；也不能算未使用。

文字確認方法：`git ls-files -z` 取得**所有受追蹤檔案，不限 `.py`**，分批作為 `rg -n -- <pattern> <files...>` 的明確引數；搜尋完整 symbol、模組名／路徑、別名與登錄點，涵蓋 tests（含 fixtures）、packaging（含 spec）、tools、`.github`、`pyproject.toml`、文件、字串式 import 與 `mock.patch`。因此不依賴 rg 的 ignore 規則，也不會漏掉同檔中的 callback 引用。起初對整個工作目錄遞迴搜尋碰到無法讀取的未追蹤 `tmp*` 目錄，已改用上述受追蹤全集重跑，所有批次只有 rg exit 0（命中）或 1（未命中），沒有搜尋錯誤。參考計數排除定義本身；本報告新寫入的名稱不拿來證明程式仍被使用。

| 候選與定義證據 | GitNexus 結果 | text-search 確認與裁定 | E 處置 |
|---|---|---|---|
| `_order`，`quantlab/chart_data.py:47` | context incoming 空；UNKNOWN / 0 / 0 | **kept (reason: sorting callback)**。`quantlab/chart_data.py:171`、`quantlab/chart_data.py:172`、`quantlab/chart_data.py:186` 均以 `key=_order` 傳入 sorted。 | 保留；不是直接 call expression 仍會執行。 |
| `_training_packet`，`quantlab/research_analysis.py:80` | context incoming 空；UNKNOWN / 0 / 0 | **kept (reason: bounded worker target)**。`quantlab/research_analysis.py:193` 傳給 `_run_bounded`，不是未使用的資料轉換。 | 保留訓練資料邊界與 worker timeout。 |
| `_training_status`，`quantlab/agent_tools.py:115` | CLI context incoming 空；UNKNOWN / 0 / 0 | **kept (reason: registry handler)**。`quantlab/agent_tools.py:139` 登錄 handler；`tests/test_agent_skills_d7.py:96`、`tests/test_agent_skills_d7.py:97` 也注入它；字串 tool name 在 `quantlab/agent_tools.py:126`。 | 保留登錄與呼叫契約。 |
| `_worker_gui_unavailable`，`desktop_ui.py:1405` | context incoming 空；UNKNOWN / 0 / 0 | **kept (reason: worker-only alias target)**。`desktop_ui.py:1409` 指派給 `result_snapshot_lines`；這是禁止 worker 使用 GUI 的失敗路徑。 | 保留到 C 的 worker/UI 分離完成，不能依零 callers 先刪。 |
| `_WorkerBindings`，`desktop_ui.py:1398` | 無直接建構 call；impact MEDIUM，direct 7、總影響 24、processes 0，主要為模組 imports | **kept (reason: conditional base alias)**。`desktop_ui.py:1408` 指派 `SharedStateBindings`；之後 `desktop_ui.py:1497` 用在 MainWindow 的繼承關係。import 影響含 desktop launcher、research runtime、diagnostic tools，非七個直接 constructor 呼叫。 | 隨 C 分離 worker import；目前保留。 |
| `local_time`，`quantlab/backup_inspection.py:76` | 指定檔案的 impact：UNKNOWN / 0 / 0 | **kept (reason: injected default)**。`desktop_pages/backup_inspection.py:8` 匯入、`desktop_pages/backup_inspection.py:13` 作為 `format_time` 預設值；`desktop_market.py:917` 的同名區域函式另計，不混用。 | 保留 locale/time 邊界。 |
| `WorkspacePanel.dragEnterEvent`，`desktop_market_workspace.py:122` | UNKNOWN / 0 / 0 | **kept (reason: Qt virtual event)**。完整名稱搜尋只有定義（0 個 Python 文字呼叫），但它是 QWidget override，與 `desktop_market_workspace.py:126` 的 dropEvent 配對；Qt 事件分派不需 Python call site。 | 保留，不能僅以 text-search 0 refs 判死。 |
| `StrategyConfig.add_realtime_features`，`docs/script samples/strategy_sample.py:139` | context 僅 has_method；UNKNOWN / 0 / 0 | **kept (reason: documentation example)**。全集搜尋除定義外 0 refs；屬已標示不可直接執行的示例，文件讀者是其用途，非產品擴充點。 | 不假稱有產品 callers；本輪不刪個別示例方法。 |
| `StrategyConfig.selectStocks`，`docs/script samples/strategy_sample.py:167` | context 僅 has_method；UNKNOWN / 0 / 0 | **kept (reason: documentation example)**。全集搜尋除定義外 0 refs；同上，不為刪死碼破壞示例敘述。 | 與整份範例文件一起維護。 |
| 模組 `docs/script samples/strategy_sample.py:1` | File context incoming 空；UNKNOWN / 0 / 0 | **kept (reason: referenced documentation artifact)**。模組路徑搜尋命中 `docs/analysis/01_PROJECT_ARCHITECTURE.md` 的示例表及 `02_EXISTING_FEATURES.md`；沒有產品入口不等於文件無用。 | 保留 tooling 歸屬，不納入產品 import。 |

以上 **10 個候選全部 kept**；本次沒有足以列為 **confirmed dead (text-search: 0 refs)** 的產品符號。這是逐項反證後的結果，不是宣稱全 repo 沒有死碼。E 的 archives 刪除是第 6 節已指定的範圍，與這些 callback、範例的存廢分開；真正刪除前仍需重新確認當時圖與文字參照。

## 9 過度防禦程式碼

依規格 4.3，以下是 **E 的內容清理清單**。需要先形成明確內部型別／presenter 邊界的項目已寫出前置條件；不能在 R0 或搬檔 PR 順手刪除，也不能把「內部呼叫」當成可以刪除反序列化驗證的理由。

| 類別／證據 | 問題與 removal note | owner |
|---|---|---|
| 重複內部條件：`desktop_pages/result_widgets.py:74` | `shown` 在 `desktop_pages/result_widgets.py:72` 已對 None return，ID/hash 分支又判 `value is not None`。刪除第二個 None 條件，保留前面的 MISSING／None／零值區分及外部數值檢查。 | E |
| 掩蓋固定內部型別：`desktop_ui.py:175`、`desktop_ui.py:323`、`desktop_ui.py:505` | `getattr(paths, 'bootstrap', None)` 把缺少 AppPaths 欄位當成合法 None。`quantlab/desktop_runtime.py:229` 已宣告 AppPaths，`quantlab/desktop_runtime.py:231` 明確有 Optional bootstrap。C/D 固定內部參數為 AppPaths 後改為 `paths.bootstrap or paths.root`；保留 bootstrap 為 None 的合法語意與所有 credential path 檢查。 | E |
| 已建立狀態的 getattr fallback：`desktop_charts.py:583` | `_marker_index` 在 `desktop_charts.py:322` 的 series layer reset 建立，正常 paint 先經 set_series。C 在 constructor 也明確初始化後，改直接取欄位，刪除吞掉初始化錯誤的 `{}` fallback；`desktop_charts.py:436` 同步處理。 | E |
| 理論型別錯誤的兜底：`desktop_market.py:428` | `_render_chart` 把 aggregate 的 ValueError 與 TypeError 都當成行情壞資料並清空圖。C 先把來源／timeframe 驗證固定在 adapter/presenter 邊界後，只處理契約內的資料錯誤，移除遮掩內部錯誤的 TypeError catch；保留真實資料失敗的錯誤顯示。未完成該邊界前不刪整個 try/except。 | E |
| 未讀取的內部參數／default：`desktop_ui.py:450` | `_prepare_paper_operation` 的 `paths`、`emit=None`、`descendants_stopped=False` 在函式體未被讀取。現有呼叫如 `desktop_ui.py:946`、`desktop_ui.py:953`、`desktop_ui.py:1044` 也不提供這兩個 keyword。刪除這三個參數並同步私有 helper 的呼叫；不可刪 dispatcher／recovery 真正使用的同名參數，不動 policy 驗證。 | E |
| 未讀取的繪圖參數：`desktop_charts.py:565` | `_prepare_chart_geometry` 不使用 painter `p`；真正繪字走 `text` callback。GitNexus context 指到 `desktop_charts.py:540` 的 paintEvent 呼叫，全集 rg 也只有這兩處。移除 `p` 參數及該實參，保留 font metrics、geometry 與 callback，避免假裝 helper 擁有 painter。 | E |
| 未使用的 extension／Optional 候選，**kept**：`desktop_pages/async_status.py:35` | `exception=None` 沒有被讀取，但 `tests/test_async_status_c4.py:85`、`tests/test_async_status_c4.py:91`、`tests/test_error_guidance_u7.py:178` 刻意傳敏感例外證明不外洩。因此不能當「零使用的擴充點」刪除；保留丟棄原始例外的契約，不增加格式化 exception 的功能。 | E（保留） |
| 無實作的 extension 候選，**kept**：`quantlab/paper.py:434` | `_fault(point)` 的空實作是交易 journal 故障注入 seam，不是未使用抽象；它與 commit 邊界的測試一起保留。也不以少寫幾行為理由移除 `desktop_forms.py:1214` 的多型 `set_rows(..., columns=None)` 參數或 Qt callback 必須接受的 event 參數。 | E（保留） |

**明確排除的刻意安全邊界：** 使用者輸入（如 `desktop_forms.py:65`）、外部 API 回應（如 `quantlab/market_providers.py:325`）、讀檔／反序列化（如 `quantlab/market_history.py:265`、`quantlab/saved_candidate_pool.py:1198`）、IPC（如 `quantlab/desktop_runtime.py:1623`）的檢查均保留。Shioaji 的單一受限 lazy loader、禁止 pickle/eval／動態執行、真實下單停用、憑證／TLS 防護不列入清理。`tools/check_trading_architecture.py:116` 與 `tools/quality_gate.py:129` 所在安全掃描不放寬。

另外保留 OOS／holdout 隔離、不可逆預算、deadline／timeout、取消後未知結果的 fail-closed 行為、來源 SHA-256／producer profile、路徑 reparse/symlink 與 WAL／restore／process-tree 證據。重複驗證若跨越了 IPC、磁碟或不可信 payload，仍是兩個邊界；不能拿本節的內部型別清理去刪除它。G3 八檔須遵循第 5 節逐檔 QA；frozen profiles 的 bytes 不受本節 removal note 授權。

## 10 大於 600 行的責任拆分方案

以 `git ls-files -z '*.py'` 為全集，排除 `tests/`、`archives/` 前綴，逐檔 `Path(path).read_bytes().count(b'\n')`，等同 `wc -l` 的 LF 計數（不以 `splitlines()` 計數）。結果 **實測 21 檔，下面列出 21 檔，measured count = listed count = 21**；每個行數都與題定基線及第 2 節相同。

第 2 節的桌面來源目標是 B 整檔搬移落點；研究目標則是 D/E 的責任抽取落點。本節是內容拆分的最終模組。B 只搬既有檔案，C/D/E 從搬好的本體抽出新模組與責任；不留下舊路徑 re-export shim。每個新模組以 ≤400 行、每類別 ≤300 行為目標，依責任而非等分切割；歷史 producer profile bytes 必須保留，G3 依第 5 節已授權拆分。所有 anchors 都指目前基線的原檔行號。

| 原檔 | LF 行數 | owner | 責任 → 目標模組（基線證據） |
|---|---:|---|---|
| `desktop_strings.py` | 4316 | C | 查詢入口／locale fallback → `desktop_app/strings/catalog.py`（`desktop_strings.py:1755`）；按 key 第一段拆 catalog dictionaries → `desktop_app/strings/assistant.py`（`desktop_strings.py:12`）、`desktop_app/strings/market.py`（`desktop_strings.py:93`）及其他同名功能檔，所有後置 `ZH_TW.update` 保持覆蓋順序（`desktop_strings.py:1701`）；歷史文字 key aliases → `desktop_app/strings/aliases.py` 再依前綴分資料檔（`desktop_strings.py:2992`）；worker stage 錯誤顯示 → `desktop_app/components/job_messages.py`（`desktop_strings.py:1726`）。catalog 保留單一真正查詢實作，不是舊模組 shim。 |
| `quantlab/saved_candidate_pool.py` | 2063 | D；frozen-data 大小例外 | producer profile 字面值留原檔原位元（`quantlab/saved_candidate_pool.py:1010`、`quantlab/saved_candidate_pool.py:1098`）；保留真正的 admission 協調與 profile 選擇本體（`quantlab/saved_candidate_pool.py:1426`、`quantlab/saved_candidate_pool.py:1777`），不是整檔搬走後 re-export。bounded JSON／read-only campaign IO → `quantlab/research_core/adapters/saved_pool_source.py`（`quantlab/saved_candidate_pool.py:1198`、`quantlab/saved_candidate_pool.py:1374`）；snapshot／attempt／selection 驗證 → `quantlab/research_core/application/saved_pool_validation.py`、`saved_pool_attempts.py`（`quantlab/saved_candidate_pool.py:1543`、`quantlab/saved_candidate_pool.py:1871`、`quantlab/saved_candidate_pool.py:1967`），profile 作明確參數傳入，避免回 import 造成循環。凍結資料本身已超過 600 行，故原檔不承諾 ≤400；逐位元比對 profile 與既有 producer 身份。 |
| `desktop_ui.py` | 1902 | C（D 使用已協調契約） | 視窗／導航／掛載 → `desktop_app/shell/main_window.py`（`desktop_ui.py:1497`、`desktop_ui.py:1629`）；busy／poll／notification 投影 → `desktop_app/shell/job_presenter.py`（`desktop_ui.py:1687`、`desktop_ui.py:1715`）；分析／研究／paper handler 分別抽到 `quantlab/research_core/application/analysis_operations.py`、`research_operations.py`、`paper_operations.py`（`desktop_ui.py:489`、`desktop_ui.py:625`、`desktop_ui.py:938`），移除 UI 字串相依、只回錯誤碼／資料；provider/auth 的實體建立與 handler registry → `desktop_app/bootstrap.py`（`desktop_ui.py:121`、`desktop_ui.py:1284`）；分析顯示文字 → `desktop_app/features/analysis/presenter.py`（`desktop_ui.py:360`）。C 擁有此來源檔修改，D 不平行重寫同一組 handlers。 |
| `quantlab/desktop_runtime.py` | 1840 | D | 原路徑留必要的 workspace／credential 本體（`quantlab/desktop_runtime.py:229`、`quantlab/desktop_runtime.py:438`），及 G3 auth 所引用的 write 工具；不把它們搬走再用 shim 補回。備份 archive／restore IO → `quantlab/research_core/adapters/workspace_backup.py`（`quantlab/desktop_runtime.py:626`）；process-tree／spawn／IPC → `quantlab/research_core/adapters/job_process.py`、`job_worker.py`（`quantlab/desktop_runtime.py:1057`、`quantlab/desktop_runtime.py:972`）；launch request 準備 → `quantlab/research_core/application/job_requests.py`（`quantlab/desktop_runtime.py:1325`、`quantlab/desktop_runtime.py:1376`、`quantlab/desktop_runtime.py:1444`）；JobManager 的實際 admission／生命週期協調留本體並只依賴 process/storage port（`quantlab/desktop_runtime.py:1219`、`quantlab/desktop_runtime.py:1573`）；registry 接線交 composition（`quantlab/desktop_runtime.py:74`、`quantlab/desktop_runtime.py:83`）。剩餘本體若仍超標，須附具體職責與進一步抽取方案；不得弱化 credential 邊界以湊行數。 |
| `desktop_chatgpt_ui.py` | 1462 | D | request/event/options 資料與驗證 → `quantlab/assistant/application/connection_contracts.py`（`desktop_chatgpt_ui.py:180`、`desktop_chatgpt_ui.py:237`、`desktop_chatgpt_ui.py:334`、`desktop_chatgpt_ui.py:400`）；連線狀態轉移 → `quantlab/assistant/application/connection_controller.py`（`desktop_chatgpt_ui.py:427`），拆 Qt signals／字串後才成核心服務；widget 與 render → `desktop_app/features/assistant/connection.py`、`connection_presenter.py`（`desktop_chatgpt_ui.py:826`、`desktop_chatgpt_ui.py:1117`）；執行 request 的外部 auth/provider 轉接 → `quantlab/assistant/adapters/chatgpt/connection_worker.py`（`desktop_chatgpt_ui.py:1300`），由 composition 注入，auth/provider 依下列方案抽取，provenance 驗證不得移除。 |
| `desktop_chatgpt_provider.py` | 1460 | D | B 純搬至 assistant adapter；D 按 SSE/HTTP transport（原164、297行）→ transport.py、reservation/unknown receipt reconciliation（原459、748行）→ reservations.py、provider 執行與完整來源 provenance（原431、1127行）→ provider.py 拆分，路徑均在 quantlab/assistant/adapters/chatgpt/。application 以 Protocol 呼叫，歷史 profile digest 不改，新來源身份明確區分。 |
| `desktop_forms.py` | 1361 | C | 通用欄位與數字／日期輸入 → `desktop_app/components/forms.py`、`form_values.py`（`desktop_forms.py:65`、`desktop_forms.py:107`）；策略／回測／campaign／walk-forward payload 表單 → 各自的 `desktop_app/features/strategy/forms.py`、`backtest/forms.py`、`research/forms.py`、`walk_forward/forms.py`（`desktop_forms.py:161`、`desktop_forms.py:280`、`desktop_forms.py:382`、`desktop_forms.py:463`）；paper intent/quote/snapshot/action 與 policy editor → `desktop_app/features/paper/forms.py`、`policy_form.py`（`desktop_forms.py:611`、`desktop_forms.py:798`、`desktop_forms.py:866`）；結果表／summary text → `desktop_app/components/result_tables.py`、`desktop_app/features/backtest/summary.py`、`desktop_app/features/strategy/summary.py`（`desktop_forms.py:1000`、`desktop_forms.py:1105`、`desktop_forms.py:1255`）。E 再做第 7 節跨實作合併。 |
| `desktop_market.py` | 1314 | C | dashboard widget → `desktop_app/features/market/dashboard.py`（`desktop_market.py:157`）；watchlist／series selection → `watchlist_presenter.py`（`desktop_market.py:277`、`desktop_market.py:331`）；chart／indicator 投影與 preferences → `chart_presenter.py`、`indicator_presenter.py`（`desktop_market.py:402`、`desktop_market.py:515`、`desktop_market.py:614`）；歷史檔案／session 輸入 dialog → `history_dialog.py`（`desktop_market.py:775`、`desktop_market.py:903`）；widgets layout → `layout.py` 與 `indicator_controls.py`（`desktop_market.py:1014`、`desktop_market.py:1193`）。目標短名均位於 `desktop_app/features/market/`；讀 cache／store 經 application port。 |
| `quantlab/research.py` | 1093 | E | DSL validation/fingerprint（原174、197行）→ quantlab/research_core/domain/strategy_validation.py；provider/bounded worker（原259、418行）→ quantlab/research_core/adapters/research_worker.py，介面到 ports/；campaign/holdout/reconciliation（原581、806、1024行）留有實際協調責任的 application 服務。保留歷史 producer profiles、資料隔離、OOS/holdout消耗與deadline；不建立與 quantlab/research.py 同名套件。 |
| `tools/diagnose_paper_replay.py` | 1070 | E | CLI 與 child-mode dispatch 留 `tools/diagnose_paper_replay.py`（`tools/diagnose_paper_replay.py:1027`）；timing／connect instrumentation → `tools/paper_replay_diagnostics/timing.py`（`tools/diagnose_paper_replay.py:26`、`tools/diagnose_paper_replay.py:74`）；UI/worker observation → `worker_probe.py`（`tools/diagnose_paper_replay.py:160`、`tools/diagnose_paper_replay.py:438`）；persistence/journal mode → `persistence.py`（`tools/diagnose_paper_replay.py:329`、`tools/diagnose_paper_replay.py:540`）；connection cases／orchestration → `connection_cases.py`、`connections.py`（`tools/diagnose_paper_replay.py:636`、`tools/diagnose_paper_replay.py:810`、`tools/diagnose_paper_replay.py:966`）。子程序 CLI 參數、timeout 與證據格式保留，不把診斷用 180 秒冒充產品 30 秒 gate。 |
| `quantlab/paper.py` | 969 | E | 純資料與 reducer → `quantlab/research_core/domain/paper_state.py`（`quantlab/paper.py:99`、`quantlab/paper.py:152`、`quantlab/paper.py:251`）；risk 計算 → `quantlab/research_core/domain/paper_risk.py`（`quantlab/paper.py:546`、`quantlab/paper.py:636`、`quantlab/paper.py:661`）；SQLite transaction／append／restore → `quantlab/research_core/adapters/paper_journal.py`（`quantlab/paper.py:411`、`quantlab/paper.py:441`、`quantlab/paper.py:477`）；paper-only command／reconcile 協調留 `quantlab/research_core/application/paper.py`（`quantlab/paper.py:689`、`quantlab/paper.py:891`），依賴 `quantlab/research_core/ports/paper_journal.py`。`quantlab/paper.py:960` 的 LiveBroker 禁用行為保持，絕不趁拆分引入真實 broker。 |
| `desktop_smoke/__init__.py` | 961 | E（B 先純搬至 desktop_app/smoke） | orchestrator → `desktop_app/smoke/runner.py`（`desktop_smoke/__init__.py:701`）；auth fixture → `auth.py`（`desktop_smoke/__init__.py:32`）；market UI/result → `market.py`（`desktop_smoke/__init__.py:154`、`desktop_smoke/__init__.py:277`）；history fixture/result → `history.py`（`desktop_smoke/__init__.py:315`、`desktop_smoke/__init__.py:361`）；walk-forward fixture/result → `walk_forward.py`（`desktop_smoke/__init__.py:493`、`desktop_smoke/__init__.py:551`）；worker teardown → `lifecycle.py`（`desktop_smoke/__init__.py:663`、`desktop_smoke/__init__.py:673`）。`desktop_app/smoke/__init__.py` 僅 package metadata；所有 callers 指向真正 runner，不 re-export 舊入口，保留 smoke deadline／證據。 |
| `desktop_chatgpt_auth.py` | 881 | D | B 純搬；D 將 TLS/JWT/identity verification（原111、206行）→ identity.py、DPAPI vault（原337行）→ vault.py、loopback/OAuth lifecycle（原489、536行）→ auth.py。路徑均在 quantlab/assistant/adapters/chatgpt/。來源 bytes 全集合納入原有驗證，保留 callback/state/nonce/PKCE/JWT/TLS、vault 與執行緒終止閘門。 |
| `quantlab/walk_forward.py` | 810 | E | fold／plan／bounds → `quantlab/research_core/domain/walk_forward_plan.py`（`quantlab/walk_forward.py:51`、`quantlab/walk_forward.py:62`、`quantlab/walk_forward.py:160`）；state 讀寫／驗證／SQLite → `quantlab/research_core/adapters/walk_forward_state.py`（`quantlab/walk_forward.py:286`、`quantlab/walk_forward.py:339`、`quantlab/walk_forward.py:360`）；fold scoring → `quantlab/research_core/application/walk_forward_scoring.py`（`quantlab/walk_forward.py:695`）；run／cancel／reconcile 留 `quantlab/research_core/application/walk_forward.py`（`quantlab/walk_forward.py:518`、`quantlab/walk_forward.py:565`、`quantlab/walk_forward.py:746`）。OOS reservation（`quantlab/walk_forward.py:663`）經原有 ledger 契約，不改 budget／source provenance 或 frozen profiles。 |
| `quantlab/analysis_recovery.py` | 768 | E | disposition／launch/receipt 值驗證 → `quantlab/research_core/domain/analysis_recovery.py`（`quantlab/analysis_recovery.py:418`、`quantlab/analysis_recovery.py:536`）；admission OS lock → `quantlab/research_core/adapters/analysis_admission.py`（`quantlab/analysis_recovery.py:186`）；SQLite read/replay/append → `quantlab/research_core/adapters/analysis_recovery.py`（`quantlab/analysis_recovery.py:260`、`quantlab/analysis_recovery.py:319`、`quantlab/analysis_recovery.py:460`）；inspect/register/restore-epoch 協調 → `quantlab/research_core/application/analysis_recovery.py`（`quantlab/analysis_recovery.py:548`、`quantlab/analysis_recovery.py:610`、`quantlab/analysis_recovery.py:747`）。停機 receipt publisher 的受限能力仍封裝在 adapter（`quantlab/analysis_recovery.py:707`），不放進 shared。 |
| `desktop_charts.py` | 765 | C | Qt widget／事件／viewport → `desktop_app/components/charts.py`（`desktop_charts.py:217`、`desktop_charts.py:444`）；ChartTrace／Marker／ReferenceLine 與 annotation setters → `chart_annotations.py`（`desktop_charts.py:97`、`desktop_charts.py:126`、`desktop_charts.py:175`）；geometry → `chart_geometry.py`（`desktop_charts.py:565`）；bars/references/panes/footer paint → `chart_paint.py`、`chart_footer.py`（`desktop_charts.py:598`、`desktop_charts.py:627`、`desktop_charts.py:672`、`desktop_charts.py:724`）。短名均在 `desktop_app/components/`；renderer 接收資料／投影，不擁有 drawing storage，避免用 mixin 數量掩飾原 class 責任。 |
| `quantlab/market_history.py` | 675 | E | session 值與政策驗證 → `quantlab/research_core/domain/market_sessions.py`（`quantlab/market_history.py:75`、`quantlab/market_history.py:121`）；CSV/tick decode／bar projection → `quantlab/research_core/adapters/history_decoder.py`（`quantlab/market_history.py:220`、`quantlab/market_history.py:265`、`quantlab/market_history.py:371`）；bounded local IO／cache entries／locking 留 `quantlab/research_core/adapters/market_history.py`（`quantlab/market_history.py:428`、`quantlab/market_history.py:512`、`quantlab/market_history.py:563`）；import 協調 → `quantlab/research_core/application/history_import.py`（`quantlab/market_history.py:622`）。檔案與時間驗證仍在入境處，不把 local data 標成即時或可信行情。 |
| `quantlab/idea_research.py` | 662 | E | task／候選證據與採用驗證 → `quantlab/research_core/domain/idea_candidates.py`（`quantlab/idea_research.py:98`、`quantlab/idea_research.py:179`、`quantlab/idea_research.py:613`）；extraction request/output → `quantlab/research_core/application/idea_extraction.py`（`quantlab/idea_research.py:242`、`quantlab/idea_research.py:290`）；records/temp/cache → `quantlab/research_core/adapters/idea_store.py`（`quantlab/idea_research.py:341`）；search/fetch/extract 流程留 `quantlab/research_core/application/idea_research.py`（`quantlab/idea_research.py:407`），並依 `quantlab/research_core/ports/idea_sources.py` 注入 caller/fetcher/store；thread pool 排程可獨立到 adapter（`quantlab/idea_research.py:545`），不改取消、費用或來源引述驗證。 |
| `tools/run_test_group.py` | 620 | E | CLI／unittest 執行入口留 `tools/run_test_group.py`（`tools/run_test_group.py:479`）；discovery／partition／固定 shard assignment → `tools/test_group_partition.py`（`tools/run_test_group.py:78`、`tools/run_test_group.py:192`、`tools/run_test_group.py:445`）；source/runtime identity 與 manifest 校驗 → `tools/test_group_evidence.py`（`tools/run_test_group.py:135`、`tools/run_test_group.py:204`、`tools/run_test_group.py:261`）；owned process tree／parallel worker → `tools/test_group_workers.py`（`tools/run_test_group.py:298`、`tools/run_test_group.py:319`）；RecordingResult 留 runner（`tools/run_test_group.py:462`）。拆分不得改 discovery 集合、skip 條件、timeout、run-attempt identity 或聚合成功定義。 |
| `desktop_pages/idea_research.py` | 617 | C | dialog widget／layout → `desktop_app/features/strategy/idea_research.py`（`desktop_pages/idea_research.py:96`）；consent/start/retry/adopt／event 投影 → `idea_presenter.py`（`desktop_pages/idea_research.py:295`、`desktop_pages/idea_research.py:306`、`desktop_pages/idea_research.py:367`、`desktop_pages/idea_research.py:566`）；search/source/candidate rows 與明細 → `idea_rows.py`（`desktop_pages/idea_research.py:440`、`desktop_pages/idea_research.py:464`、`desktop_pages/idea_research.py:500`）。短名均在 `desktop_app/features/strategy/`；網路／storage 操作走 application，不進 widget。 |
| `desktop_walk_forward.py` | 609 | D | paths／saved-pool plan／preview/execute → `quantlab/research_core/application/walk_forward_operations.py`（`desktop_walk_forward.py:29`、`desktop_walk_forward.py:57`、`desktop_walk_forward.py:108`、`desktop_walk_forward.py:215`），先去掉 UI 字串、回固定資料；compact result → 同 application 的 `walk_forward_projection.py`（`desktop_walk_forward.py:168`）；狀態、OOS 文字與 row adapter 留 `desktop_app/features/walk_forward/presenter.py`、`rows.py`（`desktop_walk_forward.py:346`、`desktop_walk_forward.py:351`、`desktop_walk_forward.py:437`、`desktop_walk_forward.py:560`）。worker 不 import presentation；OOS 未評估／已消耗語意不變。 |

字串責任的其餘具體落點包括 `desktop_app/strings/forms.py`（`desktop_strings.py:608`）、`charts.py`（`desktop_strings.py:1298`）、`jobs.py`（`desktop_strings.py:1668`）、`appearance.py`（`desktop_strings.py:1774`）、`workspace.py`（`desktop_strings.py:1887`）、`trading.py`（`desktop_strings.py:2565`），短名均在 `desktop_app/strings/`。較大的 `ui.*` 群（`desktop_strings.py:112`）再按第二段的功能／操作名稱拆到 `desktop_app/strings/ui/`；aliases 同樣依所指向的功能分到 `desktop_app/strings/aliases/` 的資料檔，`aliases.py` 彙整時應改選不同名稱如 `alias_catalog.py`，避免檔案／套件同名衝突。這些均是 C 的資料責任切分，不新增 locale 行為。

G3 拆分以第 5 節授權為準；saved-pool frozen-data 只有資料字面值 bytes 例外。E 涉及 paper、recovery、test runner 的結構修改須跑各自的故障／deadline／provenance 與 coverage 測試，不能只跑文件 gate。後續各 PR 仍依第 6 節重做 symbol impact、完整 detect_changes、全測試及打包 smoke；本次只更新盤點文件。

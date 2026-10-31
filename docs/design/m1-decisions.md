# M1 自主決策紀錄

本次以 `origin/claude/m1-terminal-design`（`f724e06`）為基底；沿用既有
`codex/m1-1-market-history`，不更動根目錄原有未追蹤的交接文件。

## 2026-11-01 01:58 +08:00 — M1-1／2／3／U：分工及既有半成品

- 問題：中斷工作留下跨四階段半成品；直接多人修改會衝突。
- 選項：重寫全部、單一路徑依序完成、隔離 worktree 並保留可用實作。
- 選擇：三個獨立 worktree 分別實作行情連線、終端、警示；主工作區負責歷史、整合與 UI 瑕疵。
  KlineStore 9 測試與 HistorySync 15 測試已通過，沿用並補足整合。
- 影響：`quantlab/trading/{application,ports,adapters}`、`desktop_app/features/trading`。

## 2026-11-01 01:59 +08:00 — M1：工具及驗證邊界

- GitNexus 狀態過期，已以 `analyze --index-only` 更新，不修改 AGENTS.md／CLAUDE.md；
  FTS 擴充未安裝，不下載、不修復。UNKNOWN 的新符號另以文字搜尋確認引用。
- `UiAction`／`UiState` 與 IPC `Operation`／`_dispatch` 為 CRITICAL；註冊點 HIGH。
  新欄位預設值與新增操作維持舊資料／操作相容，逐一執行相關 codec、IPC、runtime 測試。
- ChatGPT 可見委派已初始化並開啟設定的既有對話，但 SDK `messages.ask` 因 textbox
  selector deadline 失敗，回傳 partial；未取得回覆、不重送，改由本機完成驗收分析。
- UI 截圖與 tempfile 測試在預設限制下遇到 WinError 5；以已授權的離線測試提升執行，
  截圖成功，無實際工作區或使用者資料刪除。

## 2026-11-01 02:00 +08:00 — M1-1／2：觀察自選與交易目錄分離

- 問題：既有交易自選依賴交易 Catalog，不能接納指數與不具交易規格的股票。
- 選項：把觀察商品塞進交易 Catalog、擴充原交易服務、建立獨立看盤服務。
- 選擇：獨立 `MarketTerminalService` 與 `market_terminal_v1` 偏好區段，自選初始為空；
  固定指數另計。交易 Catalog、bindings、既有策略自選維持原契約。
- 理由：避免讓看盤商品進入交易能力或依賴十二欄交易設定。
- 影響：新增 application service、settings adapter、IPC 只讀操作；沿用七週期查詢 DTO。

## 2026-11-01 02:01 +08:00 — M1：外部驗證

全程只用 fake SDK／fixture，未讀取實際金鑰、未登入永豐、未啟用 CA、未呼叫任何下單操作。
實際盤中回呼／額度、真實 App 人工目視均保留為「待擁有者實測」，不宣稱通過。

## 2026-11-01 02:25 +08:00 — M1-1：整合修正與相容性

- 獨立行情投影由明確的行情設定或終端選股啟用；未啟用時保留原交易市場讀模型，
  既有交易服務、測試及七週期 API 保持原行為。新自選不挪用交易 Catalog。
- 快速重連保留舊價格但標為停止，直到收到新代 tick；中斷分鐘標不完整，靠官方回補恢復。
- 自選移除以商品 generation 取消正在進行的剩餘區段／回來的結果，不退回已查詢根數。
- 隔日重新啟用配額暫停的佇列；商品目錄缺失時用庫內身份與代碼作未知名稱替代，仍可看離線 K 線。
- 既有嚴格交易依賴檢查新增逐名列出的純資料／UI 契約模組；原 8 項架構測試全部保留通過，
  另增 3 項負向測試確認 UI 仍不能碰 SDK、儲存、runtime 與交易引擎。
- 設定頁行情表單移到頂部，失敗儲存保留輸入；連線失敗顯示目錄字串，不顯示 SDK 例外。
- 共用圖表／Marketplace UI 編輯的 CRITICAL 風險已保留於各階段 notes；沒有因共享軸分數較低而忽略。
- `ruff format --check .` 在含原有未追蹤交接來源的主工作區出現 Ruff 0.16.10 panic；
  不修改這些來源。提交前會核對追蹤檔及新增檔，並在乾淨的相同提交 worktree 執行 prepush。

## 2026-11-01 02:24 +08:00 — M1-1：推送前驗證處置

- 完整 prepush 實際執行 140 測試；3 個失敗都是 Windows retained-grandchild-handle
  測試環境清理問題。M1-U 獨立 worktree 在 origin/main ba597b5 重現同一失敗。
  依 0.3 第 3 點記錄後繼續，未修改測試／逾時／fixture。
- 提升執行後格式檢查只回報 CONTRIBUTING 註明的既有 ADR 換行差異，該檔未動。
  先前一般執行的 Ruff panic 原因未確認，不把它歸因於交接來源。
- Ruff lint、1000 個追蹤 Python 檔的 Python 3.11 語法、static gate、兩套架構檢查皆通過。
  M1-1 新增與既有相關模組逐一通過，詳見 docs/analysis/m1-1-verification.md。
- 圖譜刷新成功（51.8 秒），未下載擴充。共用委託與風險路徑不變。
## 2026-11-01 03:34 +08:00 — CI 修復，M1-U

- 問題：上一輪只跑 changed-file prepush，漏掉完整基準鎖定測試。
  選項：放寬測試／修結構並精確重釘。依擁有者要求選後者；每分支完整 discover，
  與 origin/main 對照，最後讀遠端 CI，不把 changed-file 檢查當成完整驗收。
- 問題：四分支的全域字串 order 會碰撞。選項：保留獨立分支／改單一堆疊。
  依擁有者指定採 U→1→2→3，只用 merge，不重寫歷史。U 的十條新增記錄為2608–2617；
  catalog 註冊移至 `# Lane M1-U`，不改 ui_text 或 alias 規則。
- 問題：U1 的替代字元、U3/U5/U6/U9/U11 的真實畫面與樣式改變舊基準。
  選擇只重釘這些實際差異，保持舊 provenance 欄位、所有斷言與類別上限不變；
  基準更新另作 fixture-only commit，逐項說明。B11 實際是同一個新增 objectName，
  不需要調整類別限制。
- 檔案：strings/catalog.py、strings/m1_ui.py、08_REFACTOR_INVENTORY.md、
  desktop_catalog_main_6b78239.json、desktop_text_alias_map.json、
  download_auto_import_ui_delta.json、desktop_widget_names.json、
  ui_redesign_empty_presentation.json、test_desktop_catalog_split.py、test_b4_appearance.py。
- Graph：catalog.py upstream CRITICAL（129直接、162總參照），以全目錄、alias、
  畫面與完整測試驗證；unittest discovery 方法 UNKNOWN 由原始碼與 runner 引用確認，
  不當成沒人使用。沒有下載 FTS/vector 擴充。

## 2026-11-01 03:45 +08:00 — CI 修復，M1-1

- 正常 merge M1-U，保留兩側契約與全部決策；新的十四條行情設定字串接續為2618–2631，
  改放 Lane M1-1。沒有改 alias 規則或 ui_text 實作。
- 先修來源、再用獨立 fixture-only commit 更新全目錄與 record 總數2632，
  並登記真實新增產品模組。U 基準沿用，不重釘無關基準；B11 原類別上限保留。
- catalog upstream CRITICAL：以完整字串/alias/UI 閘門與本分支 full discover 驗證，
  不用圖譜空流程取代測試。影響 strings/marketdata.py、strings/catalog.py、
  第2節清冊、desktop_catalog_main_6b78239.json、test_desktop_catalog_split.py。

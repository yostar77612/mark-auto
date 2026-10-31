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

## 2026-11-01 02:31 +08:00 — M1-2：堆疊、版面與整合

- M1-2 以 merge 納入 M1-1，保留所有提交歷史，不 rebase／force-push。
- 自動核准曾拒絕未備份 contracts.py 的清理；已先完整備份並核對 SHA256，之後安全恢復借用依賴。
  未遺失任何原始半成品，沒有仍被拒絕的動作。
- 合併兩階段字串註冊，週期保留終端四個中文標籤；原七週期 API 不變。
- 使用注入的 panel_factory／配色函式重用 C5 與外觀，不讓 trading presentation 匯入 infrastructure。
- 指數小圖沒有成交量，略去冗餘圖內標題；預設共用圖表路徑不改，委託線／繪圖測試保持通過。
- 完整 prepush 205 項中，Windows 原生環境失敗據實保留；真正 Python 解釋器的12項程序測試通過。
  已確認測試啟動器 PID 361768 與引擎 PID237016 不同，未增加任何期限或削弱斷言。
- 真實視窗兩種尺寸截圖、六欄、無外層捲軸與無障礙測試完成；最後人工目視仍待擁有者。

## 2026-11-01 02:50 +08:00 — M1-3：規則、接線與資料保留

- 十二類規則與 scanner 皆以 fake 驗證；UI 透過型別化 IPC 使用同一行情引擎，背景序列執行儲存與輪詢。
  第一次載入舊事件只恢復表格與狀態，不重播本機通知。通知沿用研究 presenter 的既有設定。
- 完成回補後重設指標歷史種子；加入排隊判斷，避免尚未回補完成的商品誤觸發警示。
- scanner 無時區 datetime 在 SDK 邊界視為台北時間，再轉 UTC；回傳文字與實際金鑰不進 log。
- 三十天紀錄保留規則與「不刪使用者資料」停止線衝突時，先封存完整原始 JSONL，再重寫活躍檔。
  清除紀錄只清記憶體，不刪磁碟日誌。原測試全部保留並新增封存檢查。
- 重試保留失敗的官方收盤校正 force；已涵蓋區間不會因此跳過必要校正。
- 設定與主圖偏好共用 IO 鎖保護 read-modify-write；獨立行情鎖內不取得核心 writer 鎖，避免反向鎖死。
- 圖譜 UNKNOWN／lower-bound 動態參照以來源和 rg 核對；狀態列 HIGH 風險、共享圖表／契約
  CRITICAL 風險保留，不以通過測試宣稱沒有風險。
- 既有 live-bars 對來源時間空窗的 incomplete 安全標記維持原樣，不為冷門股放寬 fail-closed；
  實際稀疏 tick 行為列待擁有者實測，正式歷史缺分鐘仍依 coverage 處理，不造假 K 線。

## 2026-11-01 02:55 +08:00 — M1-3：最終檢查

- 最終 prepush249測試，仍僅3個既有 retained-handle失敗、1個redirector PID啟動錯誤、1個原平台skip。
  Ruff／格式／3.11語法／static／layers均通過；真正Python程序的12項原生runtime測試通過。
- 同時寫入不同設定區段的回歸案例通過；新增與修改的執行緒操作沒有提升交易能力。
- 失敗測試留下的明確測試專屬LOCAL引擎以正常關閉協定釋放，未終止使用者程序，也未刪其資料。

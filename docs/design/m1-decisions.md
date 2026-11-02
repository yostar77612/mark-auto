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

## 2026-11-01 03:58 +08:00 — CI 修復，M1-2

- 以正常 merge 接續 U→1，終端48條字串為2632–2679，註冊於 Lane M1-2。
- 四處 inline stylesheet 搬至 theme.py 私有 scoped selector，以 semantic properties
  與既有 composition 注入更新；不放寬 AST gate、不直接跨層匯入。保留舊 app/market QSS
  bytes，深淺主題與漲跌配色切換仍更新標題、指數與表格。具體 HIGH/CRITICAL impact
  與新三項/舊12項測試證據見 m1-ci-style-verification.md。
- 只重釘終端新增字串、總數2680、真實新增模組與測試觀察點，獨立 fixture-only commit。
  原 C5、圖表與研究基準沿用上一層，B11 類別/公開介面限制完全保留。
## 2026-11-01 03:54 +08:00 — M1-U：完整基準相依項

- U9 將兩個紙上交易 advanced 勾選框改為 Qt 原生展開按鈕，tooltip 基準輸入數精確5→3；
  原五項 tooltip 測試、術語與可見性斷言全部保留。獨立 fixture-only 提交3ad742c。
- U5 的淨損益／夏普短表頭只改 table_values_e0e604f.json 第一張表兩個 header；
  cells、sort roles、其餘兩表不變。新增 saved_results_empty 另以明確一名稱 delta 准入；
  舊六個 download 名稱與原 historical digest 保持原值，未盲目重釘歷史 hash。
- 選項：重錄 r7_base／另加 U 專屬精確 delta。選後者，m1_u_ui_delta.json 逐列釘選焦點與
  四種 refresh 狀態；原 Counter 數量、八個結果快照、呼叫順序、錯誤與畫筆斷言不變。
  Windows 原像素比對實測通過，保留既有像素 pin，不改未觀察到的基準。
- 新增基準 import 使 R7 兩個 observer 定位72→73；原歷史投影及174筆 guard／hash 全留，
  tests/page_services_inventory.py 在整個投影之後套用完整列與數量的 M1 定位差異，
  test_page_services_r1 仍對全部 inventory 做精確相等。此 helper 在整合圖譜為HIGH，
  直接影響清冊測試與 replay 工具；已讀三個呼叫者並以原完整斷言驗證。
- 相關原閘門73項、相鄰47項通過。完整 discover 與遠端 CI 仍須完成，不能據此宣稱全綠。

## 2026-11-01 04:05 +08:00 — CI 修復，M1-3

- 正常 merge 最新 U→1→2，警示與私有樣式 callback 同時保留，沒有移除任一接線。
- 去除同文字、同 key 的第二筆 alert.latest；保留原來唯一值，依原 order 排序後接續2680編號，
  catalog 放 Lane M1-3。修來源後才獨立重釘總數、目錄、模組與四個 history observer 定位。
- 原 B11 上限與全部原測試斷言保留；不需要放大類別限制。樣式繼承上一層，不重釘未改變的
  app/market 樣式 hash。沒有真實 SDK 登入、CA、帳務或執行能力變更。

## 2026-11-01 04:20 +08:00 — 完整清冊與 main 環境對照

- M1-3 新增 scanner-runtime 測試的 self.bars／self.market 被既有 conservative 清冊掃入。
  選項：改新測試命名掩去觀察／保留並精確釘選。選後者，五個新增完整位置、兩個搬動位置
  與同一 bars alias 的 observer flag False→True 均列入獨立基準提交e48d855；
  原 alias 的 name/page/attribute、順序、歷史投影與精確清冊斷言不變，不代表新增 UI 能力。
- 原失敗閘門76項與樣式/接線46項通過；測試模組名稱誤打的一次載入錯誤已用正確名稱重跑，
  沒有把它當成產品失敗或既有問題。
- origin/main ba597b5 完整 discover：3760項、1898.475秒，10 failures／27 errors／42原平台skips。
  四分支須逐一跑完整相同測試並比對失敗 ID；不以舊 changed-file prepush 當完整驗收。
- main 的四個 ConnectionDiagnosticTests 額外失敗已最小重現：controller100924 →
  venv launcher352236 → actual child232984，子程序 ppid 是launcher而非controller，
  原 controller-owned fixture guard 於首個 checkpoint／DB 寫入前拒絕。
  同一未修改案例改用既有實際解釋器，維持10秒與120次FULL commits，2.08秒完成且正常清理。
  因此保留 PID 安全檢查，不改期限、權限、斷言或來源；第三方 tests 套件不是此四例原因。
- main 的 named mutex／symlink 權限／原生 retained-handle 問題另記錄，不終止使用者程式，
  不取得額外權限、不新增 skip。只有主分支實測已存在的失敗可作對照，遠端 CI 必須另確認。
## 2026-11-01 04:55 +08:00 — M1-U：第一輪完整測試的四項新失敗

- 第一輪完整 discover a210a99：3766項、1524.589秒，14 failures／27 errors／42 skips。
  相對 main 有四個新失敗，因此沒有推送，後續完整測試排程自動停止。
- U3 明確要求比較頁可見；U4 明確要求閒置狀態不重複。選擇獨立 baseline-only 提交b10ea42，
  精確更新兩項舊呈現期望，保留所有七頁身份、重排／快捷操作、原 ready 值、隱私、取消與提示斷言；
  另加 visible-idle／hidden-ready 的正反檢查。兩個原模組六項測試通過。
- 真實功能問題：install_page_help 把七個原先隱藏的設定說明全部移至標題，導致14按鈕超過8。
  選項：提高限制／恢復勾選框／單一說明入口。選第三個，不改8的上限，也不退回舊 advanced 元件。
  標題一個 InstantPopup 入口保留七個原 objectName、accessibleName、tooltip 與全部文字。
- 首版選單功能測試通過但截圖只有33px窄格；保留修復歷史，以後續提交修正，不改寫歷史。
  小問號維持原樣式，完整說明改用480px可換行 PlainText 標籤與 focus proxy；實際讀圖531×474，
  文字完整。新測試檢查幾何容納、七主題鍵盤巡覽、Escape 與可存取描述，不只檢查 text 值。
- 獨立 fixture-only 更新：settings_help_topics 一個新名稱、設定預設按鈕14→8、R7精確焦點／
  四狀態差異、PageIdentity 四個 observer 定位各+1。原 historical digest、r7_base、圖表像素、
  各種上限與斷言不變。修改後135個相關測試全部通過；接著重跑完整 discover。
- 來源在隔離 worktree 完成後 cherry-pick（1b8394f、db5538b），父層之間仍只用正常 merge。
  首次增量圖譜缺 UID 的 CRITICAL 寬泛結果保留為限制，強制離線重建後再完整偵測，不下載擴充。

## 2026-11-02 15:00 Asia/Taipei — graceful exit

- 工作：`codex/fix-graceful-exit`。選項為保留所有獨立引擎、關閉按名稱發現的引擎、
  或只關閉本次視窗啟動並保留原生 Popen 的自有引擎。依本次擁有者要求選第三項；
  重用的既有 host 保留獨立生命週期，不用強制終止或加長逾時。影響 `trading_runtime.py`。
- 以真實 GUI、子程序、IPC、native mutex 與 QLockFile 驗證；fake SDK 在引擎子程序內注入，
  不匯入真 SDK。案例涵蓋訂閱中與尚未完成回補；觀測發生在 fixture 失敗清理之前。
  影響 `tests/test_trading_graceful_exit.py`，詳細計時見 `fix-graceful-exit.md`。
- 現成 frozen 0.3.0 隔離 smoke 通過，但不是本修正的 frozen v2 證據；本機 Python 3.13.11
  不符打包所需 3.13.16，重建安裝版實測明列待擁有者確認。完整測試留給 CI，PR 直接對 main。
- 15:08：main 的 M3 文件 code fence 只有 CRLF/LF 格式差異；依既有 ADR 規則在
  `.gitattributes` 單檔固定 LF，獨立 baseline commit，不改文件文字、產品邏輯或測試斷言。

## 2026-11-02 19:35 Asia/Taipei — U3 strategy presentation

- Start from merged PR150 main0b760665; append phase67/orders2990–3031 after the
  accepted M2-9/U2 strings. Separate source and generated-baseline commits.
- Use only merged typed strategy commands/DTOs. Original direction/rules and full
  historical-fill eligibility are absent: require explicit revision choices and
  retain backend deletion authority; request the missing DTO facts in the PR.
- Whole-lot/margin numbers are labelled estimates; costs and submission capacity
  remain backend decisions. Do not fabricate typed-minute research evidence.
- Preserve lifecycle fixtures' explicit 3–5-day policies and financial assertions;
  assert accepted new product defaults separately. Unchanged polling must preserve
  evidence/selection activation blocking. LIVE guards and exact action pin remain.
- Native LOCAL completed captures but needed a normal Alt+F4 to leave its event
  loop; record91.760s rather than hiding it. Fake-SIM completed6.429s. Requested
  1920x1080 has1920x1061 client due existing screen fit; retain the actual geometry.

- U3 first CI: keep the independent trading architecture gate unchanged; inject
  error copy and table styling at the existing desktop composition boundary.
  Keep50000 as a labelled display-only reference, not an execution decision.
  Fix the old context test's ordinal4 selection to HoldingKind.CUSTOM and explicitly
  provide its stop while retaining every original financial/isolation assertion.
  No new strings/modules or changed style hashes; do not rerun baseline generation.


## 2026-11-02 M4a：一鍵更新與選用開機啟動

- 工作目錄從 `origin/main`（f0e974f）建立 `codex/m4a-update-autostart`；直接對 main 開 PR，不堆疊、不自行合併。僅相關模組與實際視窗檢查在本機執行，完整回歸與 Windows 安裝驗證交 CI（依本次擁有者指令）。
- 安裝接棒使用 Windows 內建 PowerShell，沿用既有 Inno 安裝程式的 `MARKAUTO_PAYLOAD_VERIFIED=` 日誌確認新 payload，不另造 stable launcher。先等自有引擎乾淨退出、安裝 mutex 釋放、原桌面 PID 結束，才啟動安裝；絕不強制終止程序。更新失敗不寫工作區或設定。
- 初始資產 URL 僅接受具名 GitHub repository release HTTPS 前綴。GitHub 正常下載必須轉址至 `release-assets.githubusercontent.com/github-production-release-asset/`，只允許該 CDN 與 objects.githubusercontent.com/github-production-release-asset-2e65be/ 的明確 HTTPS 轉址；逐跳驗證並驗證最終 URL。禁止任意主機、降級、帳密、非標準連接埠。
- manifest 新增 aware `published_at`、`signature_verified: false`、`installer: {url, sha256}`；舊 manifest 僅能檢查版本，無完整安裝資訊時拒絕安裝。發布固定指標引用同次不可變版本 release 的資產雜湊，避免指標更新競態。
- 現有安裝採版本化 payload 路徑，HKCU Run 值指向目前 frozen `MarkAuto.exe`。只有已啟用時在新版啟動修正路徑；原本關閉不建立機碼。只啟動視窗，不接觸交易恢復流程。
- ChatGPT visible delegation 使用既有設定對話，遇到輸入框 selector deadline/no_matches，未送出 prompt，停止此委派並由本地並行審查承接；未繞過登入或 UI 權限。

- 完整 diff 的 GitNexus 變更分析回報 HIGH（79 symbols、6 flows，非 partial／truncated）；主要涉及設定頁組裝、主題與文字顯示。此範圍以專屬測試、既有設定／關閉回歸及 CI 全套驗證；HIGH 未被當成 low。
- 更新確認後沿用既有視窗關閉確認，若使用者再取消關閉則取消待安裝要求並清下載，不碰交易頁檔案；不使用測試專用的跳過確認屬性。
- 下載 worker 採非 daemon，退出期間完成取消清理；成功檔案交接與視窗銷毀以單一 lock 同步，避免未輪詢結果留下完整或半成品檔。
- 本機原生 installer guard 的兩個既有測試因其他使用中 MarkAuto 持有真實 mutex 而安全拒跑；不擾動既有程序、不削弱斷言，交由隔離的 Windows CI 執行。模組式執行曾遇測試互相import路徑差異，改用 discover 的專案標準指令。

- 2026-11-02 23:35 Asia/Taipei，M4a CI 回歸：設定頁不得透過 window() 探索 shell，改由 trading_runtime 注入 maintenanceRequestClose。保留原更新說明的 help 身份與不背景自動下載的提示，同時展示新的手動安裝說明；恢復原完整 help 基準，不改既有邊界／可達性斷言。新 head 重新執行兩套完整 CI，不使用 failed-only。

- M4a 完整 CI 基準收斂：18 個新增 ErrorText 逐項鎖完整 render，另鎖新增來源區塊雜湊，重建後保留原 64 筆／原來源雜湊；三個 widget 名稱獨立列出後仍保留歷史集合 digest。R7 僅加入四列精準增量（focus 與四種 refresh 各四列），無刪除，r7_base 未改。
- 新核取方塊增加預設輸入數 4→5；擴充 repin_baselines 的 settings_inputs plan 以工具集中產生這個精準數據，其他頁面數量、頁高、primary 上限與未標示輸入檢查不變。autostart 只需文字狀態，改 PlainText QLabel 消除不必要的隱藏 action 重名，補上核取方塊 tooltip。20 個錯誤／歷史集合測試、16 個 R7 測試，以及完整原失敗模組 90 個測試通過；最終兩模式 native 視窗與八張截圖皆通過。

## 2026-11-02 — U4 risk and automatic execution desktop

- Start independent U4 from latest merged U3 main f0e974f; append phase68 orders
  3032–3085. Use public AccountRiskLimits/DTOs/actions only; never change quantlab.
- Keep accepted reconciliation proof scoped to context/epoch/environment/account/
  trading day, require separate Cancel-default resume and retain backend admission.
  Add AUTO_RESUME to exact LIVE action pin; no new automatic order policy.
- PR147 is merged: render its daily intent phases/date/window now. Normal next-
  session waiting is neutral and needs no resume; unknown outcomes never replay.
- Preserve true unknown financial/position facts and actual geometry. Baselines
  generated once at feature completion in a separate commit; full tests stay CI.
- Native LOCAL7.816s/fake SIM6.891s pass, normal owned cleanup/no real SDK. CI green
  and Claude review required before merge; Codex does not merge this order path.

- 2026-11-03 M4a 合入最新 main d77a893：保留 M2/M3/U4 與 installer on-demand 的所有意圖；M4a 字串接在 U4 後，phase69、orders3086–3103，catalog 工具量測 +18／0刪／0改、總3104。合併後45字串測試及90相關回歸全通，native LOCAL/fake SIM與8張圖重驗全通。完整合併圖分析 CRITICAL（641 symbols、31 flows，partial=false、truncated=false），風險保留並交完整 CI；相對最新 main，M4a 不含任何交易source變更。

- M4a Linux coverage 診斷：ea75a35 attempt2 所有實際分片成功，但11個新增 Windows registry cases 的既定 Linux 不適用條件未登記，嚴格 aggregate 拒絕。以原 CI reports 三profile重播可穩定紅；精確加入這11筆後，各5517cases原validate皆綠。Windows3.11/3.12證據中這11筆均started/stopped、0skip/error/failure。中央工具 registry_applicability plan 只接受既有decorator、exact11方法與reason，原34/39筆歷史平台資料與hash完整保留；gate/workflow與skip decorator完全未改。39工具/gate測試通過，全部6plans up-to-date；推新head再跑全輪CI。

## 2026-11-03 — A, strategy market empty state

- Use the accepted strategy_products list only; never manufacture market entries.
- Make the market page incomplete when empty; show reason/settings using existing
  roles. LOCAL copy does not claim broker login is required.
- Reject and clear the modal before navigating, so a later connection can reopen
  with a fresh snapshot. No connection action, order or automatic retry is added.
- Append four strings after main M4a3103; repin once in its own commit.

## 2026-11-03 — B, connection failure stage copy

- Start from latest main4867549 after A merged, without stacking. Append
  phase71/orders3108–3110 in a new string file; repin once separately.
- The requested ErrorText/mapping scope includes the existing SDK/runtime error
  boundaries only. Track whether login returned to distinguish initialization
  failure; preserve all connection/cleanup calls and specific error priorities.
- Report a known connected subscription failure through the existing selection
  completion; keep the fresh-status/generation guards and history display.
  Do not extend DTOs or infer failure from silence, and do not change the
  startup service's existing best-effort subscription loop.
- Preserve legacy error table identity and desktop historical strings. No
  connection retry, financial action or LIVE admission change is introduced.

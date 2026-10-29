# 多市場 v2 桌面整合與操作

`TradingWindow(facade, initial_state)` 僅接收 Application 的 `TradingFacade`、`UiState`，所有修改經 `UiCommand`。桌面不讀寫交易帳本，不載入券商 SDK，也不自行計算資格、風控或成交。視窗上的狀態、部位及績效來自 Application 的唯讀模型。

主程式建立引擎或 IPC 連線後，由 `desktop_app.research_bootstrap.UnifiedResearch` 將 `legacy_requested(str)` 接入同視窗的原研究 presenter，保留 `data`、`strategy`、`market`、`backtest`、`compare`、`paper`、`settings` 並新增直接 `connection`、`assistant` 路由；不另開研究應用程式。`close_ui_requested` 只表示關閉畫面；背景引擎生命週期由 Runtime 負責。關閉引擎是獨立的 `SHUTDOWN_ENGINE` 命令。

研究 UI 只接收已組裝的 widget 與導覽訊號。原研究 session、單寫入者鎖、工作管理器、原設定轉接與登入控制器由 Runtime 組裝；研究資料庫與券商 SDK 不進入 Presentation。全域登入狀態及取消入口分別為 `unified_chatgpt_connection`、`unified_cancel_research`，直接助理入口 `ai_assistant_button`，嵌入頁 `unified_research_panel`。原視窗幾何設定不會被內部 widget 的尺寸改寫。

## 首要操作流程

1. 在總覽按「建立策略」，依序選市場、持有政策、方向、商品、帳戶與資金，再選確定性規則，或貼上受限 JSON 草案。草案必須先通過 Application 驗證，不會呼叫模型或執行任意程式。
2. 初始值為現股、做多、3 至 5 個交易日、本機模擬；證券及期貨顯示各自分帳配置，不把總資金重複填入兩個帳戶。
3. 建立後在策略表選中版本，執行「驗證所選規則」與「研究所選策略」。
4. 按「查看啟動摘要」，核對實際策略版本、帳戶、商品、持有政策、有效配置與風險限額，再啟用。
5. 對帳完成後，以「恢復新倉」明確啟用本機模擬；用「推進一個模擬交易日」觀察跨日持有、退出與費用。
6. 交易工作區顯示首次成交日（第 0 日）、持有交易日、可退出量與退出期限。績效工作區分列策略版本，保留環境標示。

當沖資格不足不會把原策略偷偷改成跨日。修改政策建立新版本，表格以 `strategy_id:version` 精確選取；既有部位不因畫面選項改變原政策。

期貨的持有政策步驟可展開到期處理，預設退出。轉倉必須從已解析、同標的且月份較後的商品中明確選擇目標；缺少規格時不推測近月或其他月份。現股不提供轉倉選項。

設定工作區可展開永豐連接器引用設定，只保存帳戶代稱、OS 金鑰引用及規格、日曆、費用、資格等資料引用。儲存後可執行本機 metadata 檢查；這不會登入券商或讀取 Credential Store。檢查結果把本機可核對項與外部帳戶、能力、券商模擬及 CA 驗證分列，正式執行保持停用。空白引用不會阻擋現有本機模擬。

## 控制與異常

「停止新倉並撤進場單」、「只撤銷進場單」、「預覽平倉所選部位」、「檢查並關閉引擎」分別送出不同命令。平倉摘要先列帳戶、商品、數量、可退出量及來源；未接管的外部部位不會被畫面自動擴大選取。

交易工作區另列唯讀對帳差異：帳戶、商品、本機與券商數量、差量、可退出量、委託參考及資料時間。數量正負明示方向，未知不顯示為零；有外部持股或未接管活動委託時，不會把它們加入已接管部位。選取差異列會清除原有持倉選取，平倉會明確拒絕該未接管範圍。即使引擎已關閉，未完成有效對帳的空表也顯示未知，不能當作已確認無差異。

介面查詢與命令在背景執行，一般操作一次一項，不排入重複交易請求。「停止新倉」另有單一去重的優先流程：先核對最新狀態版本再送出，不被研究等待擋住。較舊的研究或行情快照不能把新的停止狀態覆蓋回去。連線失敗保留最後已知部位與資金，持續顯示待對帳說明，不以空表或零價覆蓋未知狀態。操作拒絕提示會保留至下一個動作；總覽保留完整待處理異常清單。

## 操作驗證定位

主視窗：`multi_market_window`。導覽：`trading_navigation`，順序為總覽、策略、市場、交易、績效、設定。

策略操作：`new_strategy_button`、`validate_button`、`research_button`、`deploy_button`、`strategies`。交易操作：`stop_button`、`cancel_entries_button`、`resume_button`、`reconcile_button`、`flatten_button`、`transfer_button`；表格為 `positions`、`orders`。模擬推進：`overview_step`。

精靈：`trading_strategy_wizard`；欄位為 `market`、`policy`、`direction`、`strategy_instrument`、`strategy_account`、`strategy_name`、`strategy_allocation`、`risk`、`rules`、`minimum_days`、`maximum_days`。受限草案：`strategy_draft_json`。期貨到期：`strategy_expiry_action`、`strategy_roll_contract`。

永豐設定：`broker_readiness_panel`；可操作欄位包括 `broker_profile_alias`、`broker_stock_account_ref`、`broker_futures_account_ref`、`broker_broker_secret_ref` 與其他 `broker_` 引用欄位；動作為 `broker_save_button`、`broker_check_button`，結果表為 `broker_readiness_checks`。

快捷鍵：Ctrl+N 建立策略、F5 更新、Ctrl+1 總覽、Ctrl+4 交易。各工作區及精靈頁面可捲動；進階資金設定預設收合。

## 測試證據界線

`tests/test_trading_ui.py` 驗證實際 Qt 元件的命令路由、拒絕回饋、鍵盤、縮小邏輯畫面、大字型與背景操作。`tests/test_trading_ui_integration.py` 使用真實 `LocalFacade`、持久模擬交易帳本及故障可注入的本機連接器，驗證建立、研究、部署、跨日持有、退出與績效，以及無當沖資格的拒絕與版本隔離。

行情用獨立的 `quote_revision` 更新，不為每筆行情寫入交易帳本。只有報價修訂時不重建策略、帳戶、委託、事件與設定；表格原地更新變動欄位，保留選取及未儲存欄位。已選部位消失時清除選取，避免操作落到替代列。

上述測試使用離屏 Qt，不能替代實體 Windows 畫面、150%／200% 原生縮放、三位初次使用者理解測試或券商驗證。這些項目須由主驗收紀錄分開列出，不能因本機模擬成功而標示券商實測通過。

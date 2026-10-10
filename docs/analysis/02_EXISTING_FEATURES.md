# mark-auto 原始功能總表與可重用性

本文件回答原始系統可在程式碼中找到哪些能力、哪些仍缺少，以及哪些適合用於 TMF 研究平台。基線已有行情、訂單、持倉、UI 與通知程式；沒有可供確認的完整歷史回測核心、AI 研究閉環或不可變策略庫。不能從交易程式存在推論交易安全、績效正確或可長期無人值守。

## 1 範圍與狀態定義

查核日期為 2026-10-09 UTC；所有原始碼連結固定在 `1cacce4ee4eef4ce7e8760f8153ef64a74852d22`。完整範圍為 47 檔、38 個 Python 檔；AST 語法解析通過。沒有執行原系統、安裝套件、登入 broker 或測試通知。

- **完成（程式層）**：實際找到可追蹤的處理路徑，不代表整合／執行已驗證。
- **部分完成**：存在一部分能力，但缺關鍵元件、適配或安全／正確性條件。
- **僅文件**：找到主張／範例，缺少能完成該功能的程式。
- **未實作**：在本次完整受追蹤樹未發現；不推論未公開或未受追蹤部署的內容。
- **Mock**：只有模擬替身且明確標示；基線未找到可宣稱為 AI／研究核心的 Mock 實作。
- **驗證未測試**：靜態存在已核對，runtime 沒有執行。**BLOCKED** 表示缺失元件或安全條件使該驗證目前不能成立。

下表把實作與驗證分欄。新增 `quantlab/` 與修補不回填到基線欄；當前成果請看 [ACCEPTANCE.json](../agent/ACCEPTANCE.json)，目標與驗收請看 [04](04_AI_QUANT_TARGET_DESIGN.md) 及 [05](05_IMPLEMENTATION_ROADMAP.md)。

## 2 完整主要功能表

### 2.1 操作與交易功能

| 功能與使用者用途 | 檔案 類別 主要函式與證據 | 實作狀態 | 驗證狀態 | 相依模組 | 問題與限制 | 沿用判斷 | 具體改進 |
|---|---|---|---|---|---|---|---|
| F01 CLI 任務選擇：執行選股、下載、訂閱或自動交易 | `run.parse_args`／`tasker.get_tasks`；[入口](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/run.py#L7-L26)、[派送表](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/tasker.py#L275-L275) | 完成（程式層） | 未測試 | trader／config／tasker | 參數解析前即匯入交易套件；預設 auto_trader | 保留舊入口，研究替換 | 新增離線 CLI，help 與 import 不碰 broker |
| F02 帳戶設定：建立、修改、刪除交易設定 | `gui.user_settings_form`／`update_user_settings`／`delete_user_settings`；[表單與設定寫入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L213-L309) | 完成（程式層） | 未測試 | Streamlit／SQL／UserSettings | 秘密與普通設定混存，未找到應用層登入保護 | 保留情境，修改 | 研究不需要真帳戶；未來秘密獨立保管、UI 有認證 |
| F03 程序控制：啟停、查看執行狀態 | `gui.start_trader`／`render_control_panel`；[啟動](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L96-L123)、[控制面板](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L319-L373) | 完成（程式層） | 未測試 | subprocess／runtime／run.py | 按鈕可能啟動交易；控制命令不等於執行已完成 | 修改 | 研究 UI 僅啟動離線任務；狀態與結果持久化 |
| F04 帳戶查詢：資金、庫存、已實現損益與配額 | `AccountInfo.query_all`／`get_account_margin`／`get_futures_positions`；[帳戶查詢路徑](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/accounts.py#L305-L460) | 完成（程式層） | 未測試 | Shioaji／SQL／pandas | 必須登入；查詢回傳不是本地研究帳本 | 保留 adapter 參考 | 區分唯讀帳戶 port 與送單 port，保存快照時間 |
| F05 股票與期貨委託：建立並送出買賣單 | `OrderTool.place_order`；[訂單與送單](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L800-L904) | 完成（程式層） | 未測試，LIVE 禁用 | API／合約／TradeData／帳戶 | broker-specific；模擬／正式依共享旗標選分支 | 保留隔離，未來抽 adapter | 寫入 intent 後送單；未知結果先對帳 |
| F06 選擇權與組合單：搜尋契約和組合建單 | `get_option_contract`／`OptionOrderFactory`／`place_combo_order`；[契約選取](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/options.py#L87-L127)、[組合委託](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L757-L799) | 完成（程式層） | 未測試 | Shioaji option 合約與回報 | 非 TMF MVP；多腿完整成交與風險未驗證 | 保留，延後整合 | 先完成單商品事件帳本；多腿另訂驗收 |
| F07 委託及成交回報：接收股票／期貨事件 | `StockOrder`／`StockDeal`／`FuturesOrder`／`FuturesDeal`；[回報處理](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L906-L1015) | 部分完成 | 未測試 | callback／TradeData／DB／通知 | 未有重複、亂序、timeout、cancel race 的測試證據 | 修改 | 唯一 event ID、持久 journal、重放與 quarantine |
| F08 持倉管理：策略部位、手工單與 watchlist 同步 | `WatchListTool.sync_strategy_position`／`TradeDataHandler.unify_monitor_data`／`Position`；[策略同步](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/positions.py#L368-L450)、[監控整併](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/positions.py#L640-L766) | 部分完成 | 未測試 | 全域狀態／broker／DB | 斷線及重啟後權威狀態、外部手工單處理未驗證 | 領域概念保留，核心替換 | broker／fills／cash 三方對帳；差異顯式阻單 |
| F09 交易額度與口數控制：防止超量開倉 | `AccountHandler._set_trade_risks`／`_set_margin_limit`、executor 檢查；[風險設定](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/accounts.py#L516-L558)、[持倉與數量檢查](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/executor.py#L652-L761) | 部分完成 | 未測試 | 帳戶／設定／報價／TradeData | 未證明為不可繞過的集中風控；無持久日損及故障矩陣 | 參考後替換 | 單一 RiskGate、日損／頻率／資金／行情年齡與 hard limits |
| F10 本地模擬記帳：不走部分真實送單分支 | `Simulator`／`OrderTool.place_order`；[模擬記帳](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/simulation.py#L10-L44)、[模式分支](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L843-L890) | 部分完成 | 未測試 | 全域模式／行情／持倉 | 模擬仍可能登入；不是歷史撮合引擎或持久 paper broker | 替換核心 | 全離線 PaperBroker、風控、事件重放與恢復 |
| F11 動態多策略 hook：按策略名稱呼叫進出場與口數 | `StrategyList`／`StrategyTool.mapFunction`／`mapQuantities`；[策略載入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L125-L150)、[映射](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/strategy.py#L29-L45) | 部分完成 | 未測試 | 私有 strategy 檔／DB／TradeData | 庫內未附正式策略；動態 Python 不安全隔離 | 保留概念，替換研究介面 | 受限 DSL＋不可變版本；策略只產生 intent |
| F12 Telegram 遠端控制：查部位、暫停／恢復／停止、改最大口數 | `TelegramBot`；[授權檢查](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/bot.py#L168-L195)、[控制指令](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/bot.py#L277-L438) | 部分完成 | 未測試，安全阻塞 | token／允許名單／executor | 空白名單放行；群組授權不是成員授權 | 修復後保留 | user 與 chat 雙重 stable ID、空白拒絕、敏感操作稽核 |
| F13 通知：成交、委託、帳戶及選股訊息 | `TelegramNotify`／`LineNotify`／`Notification`；[通知封裝](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/notify.py#L8-L84)、[業務通知](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/notify.py#L109-L233) | 完成（程式層） | 未測試 | 外部通知服務／設定 | 服務可用性、憑證、投遞確認未驗證；含帳戶資訊風險 | 修改後保留 | 明確選用、去敏、失敗計數與投遞狀態；研究預設關閉 |
| F14 runtime 與日誌檢視：看帳戶狀態和下達本機指令 | `write_status`／`write_command`／`command_is_expired`／`tail_lines`；[runtime](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/runtime.py#L24-L149) | 部分完成 | 未測試 | 本機檔案／GUI／bot | JSON 原子替換有用；缺失／無效命令時間未失敗關閉，非交易 journal | 抽取技巧，修改 | 嚴格識別碼與期限；狀態機、鎖定及帳本分離 |

### 2.2 資料與研究相關功能

| 功能與使用者用途 | 檔案 類別 主要函式與證據 | 實作狀態 | 驗證狀態 | 相依模組 | 問題與限制 | 沿用判斷 | 具體改進 |
|---|---|---|---|---|---|---|---|
| F15 即時行情訂閱：收標的與指數報價 | `Subscriber.update_quote_v1`／`subscribe_targets`／`subscribe_all`；[更新與訂閱](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/subscribe.py#L53-L142) | 完成（程式層） | 未測試 | broker callback／TradeData | 未驗證行情 gap、延遲、sequence 與重連補洞 | adapter 參考 | 事件／接收時間、stale gate、gap 停機 |
| F16 broker 歷史 K 線：載入與合併歷史 | `KBarTool._fetch_history_kbars`／`history_kbars`；[歷史資料](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/kbar.py#L110-L179) | 完成（程式層） | 未測試 | Shioaji／pandas／儲存 | 授權、回溯深度、修訂與完整性未驗證 | 改為 provider | 限速重試、schema／coverage 檢查、來源 manifest |
| F17 公開行情下載：期貨 tick、保證金及其他市場資料 | `CrawlFromHTML.get_FuturesTickData`／`get_IndexMargin`；[期貨資料與保證金](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L602-L638) | 部分完成 | 未測試，安全阻塞 | HTTP／ZIP／檔案系統 | verify=False、下載及壓縮檔驗證不足 | 重寫輸入邊界 | 先 local-only；白名單格式與大小、TLS、授權註記 |
| F18 Tick 轉 K 線與多頻聚合：1 分及多週期訊號資料 | `TickDataProcesser.preprocess_futures_tick`／`tick_2_kbar`、`KBarTool.convert_kbar`；[重採樣](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/kbar.py#L181-L195)、[tick 時段與聚合](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/kbar.py#L373-L454) | 部分完成 | 未測試 | pandas／日期設定／欄位假設 | 日夜盤粗分；night_only 未實際套篩選；資料缺漏與端點語義未驗證 | 公式參考，重建 | 以具版本 calendar 聚合；保留空分鐘與缺資料差異 |
| F19 技術指標：SMA、STD、MACD、RSI、KD、EMA、ATR 等 | `TechnicalSignals`；[均線與振盪指標](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/indicators/signals.py#L49-L192)、[其他指標](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/indicators/signals.py#L211-L378) | 完成（程式層） | 未測試 | pandas／NumPy／時間序列 | warmup、初始化、NaN 與 reference 一致性未測 | 可抽取後沿用 | 純函式、prefix 因果測試、逐筆人工 golden |
| F20 選股：載入選股腳本與篩選資料 | `SelectStock.set_select_scripts`／`pick`／`export`；[選股管線](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/select.py#L53-L139) | 部分完成 | 未測試 | 外部選股腳本／市場資料 | hooks 存在但未附正式選股策略；非 TMF 優先 | 保留，延後 | 不把股票特定邏輯帶入 TMF 研究根 |
| F21 其他市場資訊：除權息、PutCallRatio 等 | `runCrawlPutCallRatio`／`runCrawlExDividendList`、crawler 對應函式；[資料任務](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/tasker.py#L111-L128)、[抓取與匯出](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L408-L481) | 完成（程式層） | 未測試 | 外部 HTML／檔案／SQL | 端點、欄位、授權與公告可用時間待驗證 | 保留參考 | 若當策略特徵，加入 published_at 與 revision，防未來資訊 |
| F22 資料存取：SQL／SQLite／Redis／檔案 | `SQLDatabase`、Redis 與 file handler；[SQL](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/sql.py#L17-L55)、[Redis 反序列化](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/redis.py#L78-L93)、[pickle 讀取](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/file.py#L61-L61) | 完成（程式層） | 未測試 | DB credentials／本機儲存 | import-time 連線、pickle 信任、無資料版本 | 替換研究儲存 | CSV／JSON／SQLite，拒絕 pickle；明確建構生命週期 |
| F23 績效數值：交易轉換、獲利與回撤統計 | `convert_statement`／`compute_profits`；[損益計算](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L69-L119)、[績效函式](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L122-L213) | 部分完成 | 未測試，正確性阻塞 | StrategyList／交易欄位／乘數 | actual 分支費用為 0；TMF margin 缺失；空單勝率符號順序問題 | 替換計算核心 | 用 ledger／equity 計算，固定 costs／multiplier／rounding |
| F24 圖表：K 線、線圖、交易標記與輸出 | `SuplotHandler.add_candlestick`／`add_line`／`add_marker`／`export_figure`；[圖表工具](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/charts.py#L19-L146) | 完成（程式層） | 未測試 | Plotly／資料欄位 | 圖表看起來合理不證明帳務正確 | 可保留呈現概念 | 圖表綁定 run hash、資料來源／OOS／成本標記 |
| F25 綜合報告入口：整理回測／交易報告 | `trader/performance/reports.py`；[報告匯入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/reports.py#L9-L18) | 部分完成 | BLOCKED | 缺少 `.backtest.BacktestPerformance` | 靜態相對匯入唯一直接缺失模組；不能宣稱可產出完整報告 | 替換入口 | 新 reporting 只接受驗證過的 BacktestResult |
| F26 策略範例：示範資料與策略類別 | `docs/script samples/strategy_sample.py`；[佔位資料](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/docs/script%20samples/strategy_sample.py#L11-L20)、[Position 建構](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/docs/script%20samples/strategy_sample.py#L102-L109) | 僅文件／示意碼 | BLOCKED | 私有資料／Position | 類別定義時 Position() 缺必要參數；無法當標準驗收案例 | 替換示例 | 五個獨立、合成資料可重現、無 broker 的策略 |

### 2.3 目標需求但基線未提供的功能

以下缺失依完整固定[原始樹](https://github.com/yostar77612/mark-auto/tree/1cacce4ee4eef4ce7e8760f8153ef64a74852d22)及上述實際呼叫路徑判斷，沒有以 README 宣稱作為成功證據。

| 功能與使用者用途 | 路徑／證據或缺失邊界 | 實作狀態 | 驗證狀態 | 所需相依 | 問題與限制 | 沿用判斷 | 具體改進 |
|---|---|---|---|---|---|---|---|
| F27 歷史回測撮合：可重放的訊號、委託、成交與帳本 | [匯入缺少的 backtest](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/reports.py#L18-L18)；樹中無 BackTester／BacktestPerformance 實作 | 未實作核心 | BLOCKED | snapshots／calendar／cost／engine | 無法驗證歷史 fill 或重現績效 | 新建 | 因果 next-event 撮合與 golden corpus |
| F28 TMF 完整市場模型：契約、時段、到期、成本與換月 | [僅有費用參數線索](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L92-L92)、[非 TMF margin 映射](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L77-L81) | 部分完成的泛期貨支援 | 未測試／缺資料 | 官方規格／歷史 calendar／費稅 | 商品參數出現不等於 TMF 驗收 | 新建模型 | 顯式實際月份；禁止用連續價格結算 |
| F29 資料快照庫：追蹤來源、授權、品質與 hash | 全樹未發現相應 manifest／registry | 未實作 | 無法驗證 | 匯入器／schema／calendar | 檔名不足以識別資料修訂 | 新建 | 不可變 Dataset＋品質報告＋license_note |
| F30 AI 行情分析及策略產生：候選與理由 | 全樹未發現 AI provider、受限 DSL 或候選生成流程 | 未實作 | 無法驗證 | DSL／provider boundary／budget | 不存在可證明的真實模型連線 | 新建 | FixtureGenerator 預設離線；真模型另記 NOT_VERIFIED |
| F31 AI 最佳化與批次研究：改善、比較與停止 | 全樹未發現 campaign、trial store、預算帳本 | 未實作 | 無法驗證 | 因果 engine／DSL／結果儲存 | 任意參數搜索不等於可靠改善證據 | 新建 | generate→evaluate→improve；15 trials 上限與全部嘗試記錄 |
| F32 OOS／walk-forward／holdout：防洩漏與過度擬合 | 全樹未發現 split manifest、purge／embargo、holdout 存取紀錄 | 未實作 | 無法驗證 | 時序資料與 campaign policy | 未見樣本不足不能以合成績效補足 | 新建 | 凍結邊界；生成器不見 OOS／holdout；使用標記持久化 |
| F33 策略版本庫與比較選擇：保存多策略並人工決策 | 動態 Python hooks 不構成 immutable registry；全樹未發現對應功能 | 未實作 | 無法驗證 | spec／data／engine hash 與結果 | 沒有可追溯排名、核準或多策略相關性分析 | 新建 | 內容定址版本、成本後排名、風險相關性、選擇不啟動交易 |
| F34 可驗證 paper 恢復與正式就緒：事故後不重複單 | 模擬記帳見 F10；無完整故障重放 corpus | 未實作完整能力 | BLOCKED | durable journal／risk／adapter contracts | 未知委託不可盲重送；真 broker 未認證 | 新建並隔離 | 故障矩陣、對帳、kill switch；LiveBroker 永遠拒絕 |
| F35 自動化品質門檻：離線測試、CI 與可重現部署 | 全樹無 tests／workflow／lock；[基線忽略規則](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/.gitignore#L133-L146) | 未實作 | 無法驗證 | 測試資料／受控依賴／CI | `*test*.py` 被忽略；無執行證據 | 新建 | 純離線測試、拒網路／broker、fresh checkout 驗證 |

## 3 盤點數量與解讀

上述 35 個功能單位覆蓋本次主要使用者功能，並非函式數或通過測試數。F01–F26 為程式／範例可定位的現有能力；F27–F35 為目標缺口與部分泛期貨適配。個別現有能力的下單、通知、帳戶操作均未執行，不能用「找到 26 項」換算「26 項已測試」。

本基線沒有任何可據本次查核宣稱 runtime PASS 的主要功能。AST 解析通過只回答語法是否可被解析；回測 correctness、broker compatibility、UI 操作與無人值守均須各自的驗收證據。

## 4 重用清單與成本控制

- **保留不動：** LICENSE／既有來源標示、非 TMF 的股票與選擇權領域程式，避免為研究 MVP 大幅改寫無關能力。
- **保留設計知識：** 帳戶快照、委託／成交／庫存概念、圖表構成、Streamlit 使用方式、操作狀態顯示。
- **抽取後重用：** 指標公式、可純化的資料轉換、JSON 原子替換技巧。抽取必須建立新測試與明確輸入型別，不能直接把 `trader` 匯入依賴帶過來。
- **新增必要核心：** calendar、TMF contract／cost、data snapshot、事件帳本回測、受限 DSL、campaign、immutable registry、durable paper journal。
- **暫不整合：** 真實券商、通知帳戶、外部資料訂閱、付費模型、完整策略投資組合最佳化。它們不應成為離線研究閉環的前置依賴。

## 5 驗證計畫與不可誤用的證據

原有程式碼的回歸應在 broker／資料庫／HTTP／通知全部替換或不可到達的環境進行；「設定 Simulation」不足以保證離線。新研究核心的 smoke test 必須不匯入 `trader` 或 `shioaji`，不讀取真憑證，失敗時明確輸出原因。

新功能最低驗證分三層：

1. **單元與 golden：** 手算 TMF 多空損益、費稅、次根成交、時段、訊號因果、無效 DSL 與資料拒絕。
2. **跨模組整合：** local data→quality→strategy→backtest→ledger→report→persistent registry；同輸入三次 hash 一致。
3. **操作與恢復：** UI 空資料、錯誤、重複點擊、重啟；paper partial fill、timeout、重複／亂序、對帳與 stale quote。模型與 broker 實際整合驗證另行處理。

完成新測試後應留下命令、環境、版本、退出碼與逐項結果；不得在本表基線行號上覆寫成「已修好」。原有缺陷與修補證據應分列，讓讀者能分清是原始能力、目標能力或已交付變更。


## 桌面後續交付對照

原始表仍對應固定基線，不把新增模組倒填成原本具備。現有新增桌面提供繁中總覽／資料匯入下載／策略與生成候選版本／日期與參數批次回測／報表比較選擇／Paper對帳重播急停／模型設定與安全備份。主要計算、下載、研究與備份在受控程序執行；大型本機資料或結果的顯示解析仍有同步部分，需用基準決定是否優化。

來源證據為 `desktop_ui.py`、`quantlab/desktop_runtime.py`、`desktop.py` 及 `tests/test_desktop_ui.py`／`tests/test_desktop_runtime.py`。真券商、真模型語義、正式策略績效及乾淨Win10/11驗收並未因此變成已驗證；完整狀態只依ACCEPTANCE.json。GUI的fixture模式與loopback協定測試不冒充外部AI研究成功。

## 0.1.2 功能與驗收對照（接續驗收）

| 功能 | 實作狀態 | 實際證據／仍有限制 |
|---|---|---|
| 原生繁中桌面、總覽、設定 | 已實作 | Qt功能回歸；clean Win10/11未驗證 |
| 免費行情下載、匯入與品質 | 已實作並用真官方資料驗證 | 30 ZIP校驗；12日13,680分鐘+24盤OHLC；缺盤首/尾/整盤拒絕；無自動補造 |
| 因果回測、成本、資金曲線、CSV | 已實作 | 固定Golden與真資料技術回測；費用/流動性仍需正式參數 |
| 真AI策略生成 | 已窄範圍整合驗證 | 官方1.5B受限schema產3候選；一般JSON模式失敗保留，不冒充自由程式創造 |
| OOS、holdout、多策略比較 | 已技術驗證 | 真生成候選完成分割；1虧損2零交易，無正式排名/投資資格 |
| Paper、持倉、對帳、風控、急停 | 已實作並故障回歸 | 61focused tests；新單在不確定狀態保持封鎖；不等於真券商重連 |
| 機密、備份／還原、工作區 | 已實作，新增目的地保護 | DPAPI；備份不含credentials/不可回退controls，拒絕覆寫內部路徑 |
| 安裝、更新、移除 | 已實作新版versioned payload | 必須待Windows CI真升級／中斷恢復；unsigned；不自動下載執行更新 |
| 無開發工具的Win10／Win11完整驗收 | 工具/程序已備，未實測 | kit使用內建PowerShell，EXTERNAL BLOCKED，不能以Server當PASS |
| 實盤與券商 | 固定停用／未驗證 | 無真資金送單或帳戶資格宣稱 |

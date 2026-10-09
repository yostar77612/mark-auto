# mark-auto 原始系統架構與升級邊界

本文件協助維護者理解原始程式真正的執行方式，以及為何 TMF 研究核心需要隔離。結論是保留既有 Python、Streamlit 技術與有價值的交易領域知識，新增同層 `quantlab/` 研究核心。原系統具有交易操作與券商整合程式，並非已完成的 AI 量化研究平台。

## 1 分析版本與證據界線

- 查核日期：2026-10-09 UTC。
- 唯一程式分析來源：[yostar77612/mark-auto](https://github.com/yostar77612/mark-auto)。基線為 `main@1cacce4ee4eef4ce7e8760f8153ef64a74852d22`，不是持續變動的 main。
- 完整基線包含 47 個受追蹤檔案、38 個 Python 檔案。遠端樹未截斷，所有檔案內容與 Git blob 識別相符；無子模組或 symlink。38 個 Python 檔通過 AST 語法解析；這不代表可匯入、可執行或計算正確。
- 基線查核不曾登入券商、啟動交易程式、安裝其依賴、連接資料庫或傳送通知。不得把靜態程式碼存在寫成執行驗證通過。
- 後續已進入自主開發；本系列仍保留原始基線事實。`quantlab/`、安全修補、測試與 CI 屬於後續變更，驗收狀態以 [ACCEPTANCE.json](../agent/ACCEPTANCE.json) 的證據為準。以下基線永久連結不會因後續修補而改變。
- 本文件描述架構；完整功能在 [02](02_EXISTING_FEATURES.md)、風險在 [03](03_CODE_QUALITY_AND_RISKS.md)、目標設計在 [04](04_AI_QUANT_TARGET_DESIGN.md)、工作順序在 [05](05_IMPLEMENTATION_ROADMAP.md)。

## 2 技術堆疊與部署形態

| 層次 | 基線實際內容 | 工程意義與限制 |
|---|---|---|
| 語言與執行 | Python；以根目錄腳本啟動 | 未宣告完整支援 Python 版本；不得只依套件徽章判斷相容性 |
| 操作介面 | `gui.py` 的 Streamlit 頁面、表格、表單、程序控制 | 介面直接讀寫交易設定與資料庫，不是前後端分離服務 |
| 行情及券商 | Shioaji；公開網頁抓取與 TAIFEX 檔案下載路徑 | SDK 初始化、行情、帳戶、下單與研究工具相互耦合 |
| 數值分析 | pandas、NumPy、技術指標函式 | 有公式，不等於有驗證過的歷史撮合引擎 |
| 持久資料 | SQLAlchemy、MySQL 路徑及 SQLite fallback；Redis；本機 CSV／pickle／JSON | 多種儲存並存，沒有統一、不可變、版本化的研究快照 |
| 視覺化與報告 | Plotly、圖表輸出與報表類別 | 報表匯入缺少的 `backtest` 模組；不能視為完整回測報告 |
| 背景工作 | CLI 任務派送、ThreadPoolExecutor、訂閱 callback、交易監控迴圈 | 並非具有持久排程、任務租約與失敗恢復的研究工作佇列 |
| 通知控制 | Telegram、通知封裝、本機 JSON runtime IPC | 控制平面與交易平面未形成嚴格權限邊界 |
| AI 服務 | 基線未發現模型 provider、LLM 呼叫、DSL 或搜尋協調器 | 名稱與文件宣稱不能替代程式證據 |
| 部署與依賴 | 32 項有效直接依賴，多數版本固定 | 無 transitive lock、hash、套件建置設定、CI 或正式測試集 |

依據：[依賴清單](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/requirements.txt#L1-L33)、[UI 直接匯入交易與資料庫](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L10-L18)、[資料庫初始化](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/__init__.py#L25-L42)、[報告依賴](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/reports.py#L9-L18)。Flask、Dash 出現在依賴清單不等於本次已確認另有可部署 Web API。

## 3 目錄與模組責任

| 路徑 | 主要責任 | 相依與重用決策 |
|---|---|---|
| `run.py` | 解析 CLI、初始化 logging、呼叫選定 task | 舊入口；不得作研究 smoke test |
| `gui.py` | 帳戶設定 CRUD、啟停程序、狀態／日誌／庫存顯示 | 保留 UX 概念；研究另設 `research_app.py` |
| `trader/__init__.py` | 全域 thread pool、工具單例、目錄建立 | 匯入有副作用，不能當研究套件根 |
| `trader/config.py` | broker、日期／時段、費率、帳戶、動態策略、儲存設定 | 跨環境設定混合，需邊界驗證和安全預設 |
| `trader/tasker.py` | 選股、資料抓取、訂閱、交易等任務入口 | 可參考任務分類；不要直接接到研究 campaign |
| `trader/executor.py` | 組合帳戶、行情、策略、訂單、模擬、監控與通知 | 高耦合交易協調器，保留參考並隔離 |
| `trader/indicators/signals.py` | 移動平均、RSI、MACD、ATR 等指標 | 有潛力抽取純函式；先建獨立 reference fixture |
| `trader/utils/kbar.py`、`subscribe.py`、`crawler.py` | 行情 callback、歷史 K 線、聚合與網頁／檔案抓取 | 參考資料格式；新匯入器須重新驗證時區、盤別與授權 |
| `trader/utils/strategy.py`、`trader/scripts/` | 動態 Python 策略 hook 與訊號／口數對應 | 沒有隨庫提供正式策略；不是安全 DSL sandbox |
| `trader/utils/accounts.py`、`orders.py`、`callback.py` | 登入、查詢帳戶、建單、送單、處理回報 | 可作未來 broker adapter 的領域參考，不能直接宣稱相容其他券商 |
| `trader/utils/options.py` | 選擇權契約搜尋與組合單資料 | TMF MVP 非核心；保留，不優先擴充 |
| `trader/utils/positions.py`、`simulation.py` | 持倉、watchlist、成本、風險量及模擬記帳 | 有局部功能；缺少持久可重放的委託狀態機證據 |
| `trader/utils/objects/` | Action、帳戶與報價等共享物件及設定 | `TradeData` 全域可變資料不可在研究 trials 共用 |
| `trader/utils/database/`、`file.py` | SQL／Redis 操作、表格、檔案存取 | 新研究不使用 pickle 或 import-time 連線 |
| `trader/utils/runtime.py` | session／status／command JSON、命令 ID／有效時間、日誌解析 | 原子替換技巧可保留；不是交易事件 journal |
| `trader/utils/bot.py`、`notify.py` | Telegram 指令與交易通知 | 安全修補後再評估，研究預設離線 |
| `trader/performance/` | 績效轉換、圖表、報告入口 | 缺少被匯入的 backtest 模組，費用與 TMF 計算亦有缺陷 |
| `docs/script samples/strategy_sample.py` | 策略示意 | 有建構參數錯誤及佔位資料路徑，不能當可執行範例 |

完整檔案範圍可在[固定版本樹](https://github.com/yostar77612/mark-auto/tree/1cacce4ee4eef4ce7e8760f8153ef64a74852d22)核對。基線沒有 `AGENTS.md`、正式測試集、CI workflow、`pyproject.toml`、lockfile、正式策略實作目錄內容或可用市場資料 fixture。

## 4 模組關聯圖

下圖只表示已查得的依賴與呼叫方向，並不代表執行測試通過。

```text
run.py                         gui.py
  │                              ├─ 設定／資料庫 CRUD
  │                              ├─ runtime JSON／日誌
  │                              └─ subprocess 啟動 run.py
  ├─ trader 套件初始化
  │    ├─ config ─ Shioaji API／當日時間／動態策略
  │    ├─ 工具單例／thread pool／資料目錄
  │    └─ database ─ SQL／SQLite／Redis
  └─ tasker.runAutoTrader
       └─ StrategyExecutor
            ├─ AccountHandler ─ 登入／憑證／帳戶
            ├─ Subscriber／callback ─ 報價與成交
            ├─ KBarTool ─ 共享 KBars
            ├─ StrategyTool ─ 動態 Python 策略
            ├─ OrderTool ─ 模擬記帳 或 API.place_order
            ├─ WatchList／Position ─ 持倉與配額
            └─ Telegram／runtime ─ 操作與通知
                   ↕
             全域 TradeData 可變狀態
```

關鍵耦合不是「模組數很多」，而是相依方向會穿透功能邊界：研究常需要的指標、K 線與績效工具位於 `trader` 之下，Python 匯入子模組會先執行父套件初始化。因此只想呼叫一個公式，也可能啟動與研究無關的 broker／資料儲存初始化。

## 5 主要呼叫路徑

### 5.1 CLI 至交易委託

1. `run.py` 在參數分派前先匯入 `trader`、`config`、`tasker`。其預設任務為 `auto_trader`。見 [匯入與預設 task](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/run.py#L7-L26)、[任務派送](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/run.py#L57-L75)。
2. `trader/__init__.py` 建立共用物件、thread pool 與目錄；設定模組建立 Shioaji API。見 [套件初始化](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/__init__.py#L1-L29)、[API 建構預設](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L14-L16)、[API 單例](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L79-L82)。
3. `runAutoTrader` 建立 `StrategyExecutor`，呼叫 `init_account` 再 `run`。見 [自動交易入口](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/tasker.py#L154-L159)。
4. `StrategyExecutor` 組合帳戶、報價、訂單、模擬與策略工具，登入、啟用憑證並註冊 callback。見 [協調器組合](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/executor.py#L40-L65)、[帳戶及 callback 初始化](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/executor.py#L143-L203)。
5. 交易迴圈訂閱、更新 K 線與策略、檢查持倉條件、建單；最終可到 `API.place_order`。見 [執行入口](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/executor.py#L904-L909)、[監控迴圈](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/executor.py#L958-L991)、[模擬與真實送單分支](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L843-L897)。

**安全含義：** `run.py --help` 也會先走匯入鏈，不能當無副作用的離線驗證命令。原模擬旗標不等於未登入或無網路。

### 5.2 即時與歷史資料

報價 callback 更新 `TradeData.Quotes`，K 線工具再聚合／追加共享 KBar 資料供策略使用。歷史資料由 broker 或公開抓取路徑取得，最終寫入本機檔案或資料庫。證據：[報價更新](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/subscribe.py#L53-L105)、[歷史取得與重採樣](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/kbar.py#L110-L195)、[K 線更新](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/kbar.py#L265-L308)、[期貨檔案下載](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L602-L617)。

缺少來源不可變識別、license 註記、資料修訂版本、calendar 版本與聚合模型版本，會使相同策略在不同日期讀到不同資料卻沿用相同名稱。研究層必須先建立資料 manifest，再允許策略取得資料。

### 5.3 策略與共享狀態

設定模組動態載入 Python 策略，`StrategyTool.mapFunction` 以名稱尋找函式，未知策略回傳不動作；口數亦有 fallback。`StrategyTool` 直接依賴 DB、全域日期、`TradeData`。證據：[動態策略設定](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L125-L150)、[策略映射與相依](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/strategy.py#L6-L45)、[共享交易物件](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/objects/data.py#L9-L98)。

這是受信任 Python plugin 機制，沒有有限語法、資源配額、模型輸出驗證或權限沙箱。未來 AI 只能產生結構化規格，不能直接將此動態載入機制當作 AI 程式碼執行器。

### 5.4 UI 與 runtime 控制

`gui.start_trader` 透過 list 形式的 `subprocess.Popen` 啟動舊入口；頁面另讀取日誌與帳戶資料。`runtime` 用暫存檔替換寫 JSON，command 有 ID／時間與過期檢查。證據：[程序啟動](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L96-L123)、[JSON 檔案存取](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/runtime.py#L24-L64)、[命令與到期判斷](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/runtime.py#L97-L126)。

這有助於單機操作，但缺少交易所／券商最終狀態的持久 event journal。UI 所見「已送出控制命令」不能推論交易流程已完成停止、撤單或對帳。

## 6 儲存與設定邊界

基線 SQL 初始化可連接設定資料庫，失敗時轉 SQLite；還有 Redis 與本機檔案存取。`UserSettings` 保存帳戶相關設定；敏感欄位僅在部分 UI 遮蔽。證據：[SQL 建立與 fallback](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/sql.py#L17-L55)、[設定中的敏感欄位](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/tables.py#L15-L18)、[畫面遮蔽](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L519-L522)。

部署設定、當天日期、商品／費用、策略載入與 broker 模式混在同一設定根。基線缺少可交付的 `config.ini`、holiday fixture 與正式 strategy 檔案，表示新環境即使安裝完成，也不能據此認定可以重現使用者原先的部署。未知的部署內容不納入公開文件，也不以假資料冒充現況。

新核心將設定拆成可雜湊的 `Instrument`、`SessionCalendar`、`CostSpec`、`BacktestConfig`、campaign config；秘密與個人帳戶資料不進這些研究設定。SQL fallback 不應掩蓋需要持久保存的實驗或交易狀態。

## 7 保留與替換原則

1. **直接保留版本與權利資訊。** 保留 Apache-2.0 LICENSE 和既有著作權標示。套件版本為 `2.4.2`；原始上游完整來源關係尚未核實。見 [程式版本](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/__init__.py#L9-L9)、[License](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/LICENSE#L1-L15)、[著作權標示](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/LICENSE#L189-L189)。
2. **保留技術與操作知識。** Python／Streamlit、帳戶／訂單事件概念、既有 UI 使用情境及指標演算法仍有價值。
3. **抽取後才重用。** 指標、序列化與部分 runtime 檔案寫入方法需純化、型別化並通過 fixture，避免直接匯入 `trader`。
4. **新增必要缺失核心。** 獨立資料快照、日曆、因果回測、帳務、DSL、實驗預算、策略版本庫與 paper journal 不是重寫已存在的完整功能，而是補上本次基線沒有的能力。
5. **避免不必要擴張。** 不先引入微服務、Kubernetes、分散式排程、向量資料庫或第二套前端。離線核心採標準函式庫，UI 作選用依賴；券商 bridge 等正式需求成立後再加。

工程介面與檔案責任以 [IMPLEMENTATION_CONTRACTS.md](../agent/IMPLEMENTATION_CONTRACTS.md) 為準。改造方向並不自動授權付費資料、模型服務、帳戶開通或真實交易；這些 readiness 必須分開記錄。

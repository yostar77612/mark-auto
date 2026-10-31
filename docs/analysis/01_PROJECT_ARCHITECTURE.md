# 專案架構（PR E）

現行產品是原生桌面研究工具。桌面入口為 `desktop.py`，輔助 Streamlit 研究入口為
`tools/research_app.py`。核心不匯入 Qt；真實交易維持停用。上游 Li Kuei-Wei 的
Apache-2.0 來源歸屬與根目錄 `LICENSE` 保留；舊交易程式已由 PR E 移除，原文可由
[固定歷史版本](https://github.com/yostar77612/mark-auto/tree/909fc49/archives/legacy_autotrading/)追溯。
禁止匯入舊交易模組的規則不依賴封存檔案存在。

## 現行責任與路徑

| 路徑 | 責任 |
|---|---|
| `desktop_app/shell/` | 視窗、頁面組裝、生命週期、應用服務接線 |
| `desktop_app/features/` | 各功能 widget、presenter 與 view-model |
| `desktop_app/components/` | 共用表格、表單、圖表、隱私與非同步狀態顯示 |
| `desktop_app/strings/` | 按功能拆分的字串與單一查詢入口 |
| `desktop_app/smoke/` | 桌面啟動、TLS 與 UI smoke 驗證 |
| `quantlab/research_core/domain/` | 研究協定與純資料／證據語意 |
| `quantlab/research_core/application/` | 研究、分析、paper 與 UI 資料作業用例 |
| `quantlab/research_core/ports/` | 用例依賴的 Protocol 介面 |
| `quantlab/research_core/adapters/` | 工作區、備份、程序、資料來源與具體服務接線 |
| `quantlab/assistant/domain/` | 認證、方案、回應與來源資料協定 |
| `quantlab/assistant/application/` | 助手連線與操作協調 |
| `quantlab/assistant/ports/` | 外部認證與服務 Protocol |
| `quantlab/assistant/adapters/chatgpt/` | ChatGPT HTTP、認證、憑證與 receipt 實作 |
| `quantlab/shared/` | 至少三個使用點所證明的核心共用純函式 |
| `quantlab/trading/domain/` | v2 交易領域資料與規則 |
| `quantlab/trading/application/` | v2 用例與服務協調 |
| `quantlab/trading/ports/` | broker、資料與儲存介面 |
| `quantlab/trading/adapters/` | 具體外部介接；SDK 僅經受限 lazy loader |
| `quantlab/trading/runtime/` | 本機程序、IPC 與 composition |
| `tools/` | 品質閘門、開發、機械遷移與診斷工具 |
| `packaging/` | 凍結、安裝、授權與發布驗證 |

`quantlab/research.py` 保留原模組位置，避免模組與套件同名；僅清單指定的研究責任
進入 research_core。`quantlab/saved_candidate_pool.py` 保留歷史 producer profile
原文，新來源使用新的 current profile，不重釘歷史 hash。

## 分層與依賴

Domain 只依賴 domain/shared；application 只依賴 application/domain/shared。
Infrastructure（adapters）依賴 domain/shared 與明確的 application ports，不能反向
依賴具體用例。Presentation 依賴 application/domain/shared，不直接接 SDK、磁碟或
具體 infrastructure。Shared 不依賴其他產品層。Composition 負責建構並傳入具體依賴；
tooling 可跨層診斷，產品 runtime 不反向匯入 tooling。

Widget 只呈現狀態與送出意圖；流程、驗證與副作用由 presenter、用例與 adapter 負責。
`tools/check_layers.py` 以明確分類與只能縮減的 allowlist 檢查依賴；既有安全閘門獨立執行。

## 規格第 4 節的工程規則

依責任拆分；檔案 400、類別 300、函式 50 行是可讀性目標，例外須在盤點表寫出理由。
超過 600 行的檔案必須有拆分方案。第三個呼叫點出現才抽共用（rule of three）；
只有 UI 使用的共用放 components，核心共用放 shared。

外部服務以 `typing.Protocol` ports 表達契約，只有已有多實作或測試隔離需求才引入。
組裝點使用普通 dict registry 或 `create_xxx(config)` 函式；不新增 Factory 類別階層、
Singleton、Builder、深層繼承或 DI 框架。依賴由建構子明確傳入。

使用者輸入、API、磁碟／反序列化與 IPC 要驗證；已確立的內部型別不重複 None 檢查，
不以 getattr fallback、理論性 catch 或無使用者的 Optional 擴充點掩蓋程式錯誤。
Shioaji 載入限制、pickle/eval／動態執行禁令、live／credential／TLS 防護、OOS／holdout、
不可逆預算、deadline、未知結果 fail-closed、來源 hash、路徑與 restore 證據全部保留。

搬檔、import、字串 patch target 與私有呼叫的機械修改須以 `tools/refactor/` 中的腳本重現。
不留 re-export shim、模組別名或 `sys.modules` 相容層。PR E 的移除與保留結果見
[重構盤點](08_REFACTOR_INVENTORY.md) 8.1、9.1、10.4；完整安全測試與打包由 controller 執行。

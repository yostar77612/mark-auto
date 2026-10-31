> PR E outcome: the legacy autotrading archive was removed from the current tree. References below describe historical evidence at commit `909fc49`, not current installation paths. The legacy import ban remains active.

# 分層式重構規格書

本文件定義 mark-auto 下一階段的 code review 與重構工作：目標架構、程式碼規範、階段計畫與驗收標準。重構只改結構，不改行為；新功能不在本規格範圍內。

- 撰寫日期：2026-10-29
- 基線：`main@ffc66c8`（LM1 P4 合併後）
- 相關文件：架構現況見 [01](01_PROJECT_ARCHITECTURE.md)，品質風險見 [03](03_CODE_QUALITY_AND_RISKS.md)

## 1 目標

1. **分層清楚**：每個模組只屬於一層，依賴方向只能往下，並由自動閘門強制。
2. **能共用就共用**：重複出現的 UI 元件、資料轉換、外部服務介面集中成一份。
3. **單一元件不肥大**：檔案、類別、函式都有大小目標，超過就拆。
4. **好維護、好擴充**：新增一個功能時，主要是新增檔案，不是修改一堆舊檔。
5. **不過度防禦**：只在邊界驗證，不為不會發生的情況擴寫程式碼。

## 2 現況摘要

| 項目 | 現況 | 問題 |
|---|---|---|
| 規模 | 約 8.6 萬行 Python；測試 350 檔 | 測試保護網足夠，可以支撐重構 |
| `quantlab/trading/` | 已分為 `domain/`、`application/`、`ports/`、`adapters/`、`runtime/`，並有 `tools/check_trading_architecture.py` 閘門 | 這是本規格的範本，基本保留 |
| `quantlab/` 其餘 | 約 69 個檔案平鋪在根層，研究、回測、資料、儲存混在一起 | 沒有分層，`desktop_runtime.py`（1840 行）名稱與位置不符 |
| 桌面 UI | 約 30 個 `desktop_*.py` 平鋪在 repo 根目錄，另有 `desktop_pages/`（58 檔）、`desktop_trading/`（14 檔） | 畫面、狀態邏輯、外部服務（ChatGPT）混在同一層 |
| 肥大檔案 | `desktop_strings.py` 4316、`saved_candidate_pool.py` 2024、`desktop_ui.py` 1890、`desktop_runtime.py` 1840、`desktop_chatgpt_ui.py` 1462、`desktop_chatgpt_provider.py` 1460、`desktop_forms.py` 1361、`desktop_market.py` 1314 | 單檔承擔多種責任 |
| `archives/legacy_autotrading/` | 37 檔，現行程式已由閘門禁止匯入 | 只剩參考價值，佔用搜尋與索引 |

## 3 目標架構

### 3.1 四層 + 組裝點 + shared

```text
presentation   PySide6 畫面、元件、presenter / view-model
     │
application    use case、服務、流程協調；只認 port 介面
     │
domain         純資料模型與規則；不碰 IO、UI、網路、時鐘

infrastructure 實作 port：Shioaji、ChatGPT HTTP、行情來源、檔案與 SQLite 儲存
               （依賴 application 定義的 port 與 domain 模型）

composition root  啟動時建立物件並接線（例如選真實或 fake broker）
shared            設定、logging、多語系字串、時間工具；不 import 任何一層
```

| 層 | 可以 import | 不可以 import |
|---|---|---|
| domain | 標準函式庫、shared | application、infrastructure、presentation、PySide6、任何 SDK |
| application | domain、ports、shared | infrastructure 的具體實作、presentation、PySide6 |
| infrastructure | domain、ports、shared、外部 SDK | presentation、application 的服務實作 |
| presentation | application、domain（唯讀顯示用）、shared、PySide6 | infrastructure 的具體實作、外部 SDK |
| composition root | 全部 | — |

四層已經足夠，不再增加層數。presentation 內部再分「畫面元件」與「presenter / view-model」，這是層內分工，不是新的一層。

### 3.2 目錄配置

層以下再**依功能切資料夾**（vertical slice），新增功能就是新增一個資料夾。

```text
quantlab/                    核心（不含任何 UI）
  trading/                   保留現有 domain / application / ports / adapters / runtime
  research/                  由 quantlab 根層平鋪檔案整理而來
    domain/  application/  ports/  adapters/
  assistant/                 ChatGPT 相關的非 UI 部分
    application/  adapters/chatgpt/
  shared/                    設定、時間、格式化等跨層工具

desktop_app/                 只放 presentation 與桌面組裝點
  shell/                     主視窗、導覽、頁面掛載（拆自 desktop_ui.py）
  features/<功能>/           每個功能一個資料夾：view.py、presenter.py、rows.py …
  components/                跨功能共用元件：表格、表單欄位、圖表、對話框
  strings/                   依功能拆分的字串檔
  bootstrap.py               桌面端組裝點

desktop.py、trading_entry.py、trading_runtime.py   保留在根目錄，只做啟動
```

- 套件命名為 `desktop_app`，以免和根目錄的 `desktop.py` 衝突。
- 每個檔案的實際歸屬由 R0 報告逐一決定，本節只定方向。
- ChatGPT 的 auth / provider 有打包限制（`packaging/markauto.spec` 以資料檔方式複製到根目錄），R0 須先確認原因，再決定能不能搬。

## 4 程式碼規範

### 4.1 大小目標（軟性）

| 對象 | 目標 | 說明 |
|---|---|---|
| 檔案 | ≤ 400 行 | 超過 600 行必須在 R0 報告列出拆分方案 |
| 類別 | ≤ 300 行 | UI 類別過大時，把邏輯移到 presenter |
| 函式 | ≤ 50 行 | 以可讀性為準，不為了湊行數硬切 |
| 字串表 | 依功能拆檔 | `desktop_strings.py` 依 key 前綴（`assistant.`、`market.` …）拆到 `desktop_app/strings/` |

這是目標，不是硬性閘門。拆分要依責任邊界切，不能只把行數平均分到幾個檔案。

### 4.2 共用原則

- **第三次出現才抽共用**（rule of three）。兩處相似先容忍，第三處出現時再抽。
- 可共用的優先項目：表格 model 與 row 格式化、表單欄位與驗證提示、圖表元件、非同步狀態顯示、外部服務 port。
- 共用元件放在被使用的最低共同層：只有 UI 用的放 `desktop_app/components/`，核心也用的放 `quantlab/shared/`。

### 4.3 不過度防禦

**要做的：**

- 在邊界驗證：使用者輸入、外部 API 回應、讀檔與反序列化、IPC 訊息。
- 保留既有的安全閘門：Shioaji 載入限制、禁止 pickle / eval、真實下單與憑證防護。這些是刻意的邊界，不屬於過度防禦。

**不做的：**

- 內部函式之間不重複檢查參數；呼叫方是自己的程式碼時，相信型別標註。
- 不為「理論上可能」加 `try/except`、fallback、預設值或 `Optional` 參數。例外該往上拋就往上拋。
- 不預留沒人使用的擴充點、設定開關、抽象基底類別。
- 不用 `getattr(obj, "x", None)` 掩蓋型別錯誤。
- 搬檔時不留 re-export shim 或相容別名，直接修改所有 import。

R5 會清理現有程式碼中的過度防禦寫法；之後每個 PR 的 review 也檢查這一項。

### 4.4 Design Pattern 準則

只有在「已經有兩種以上實作」或「不抽出來就無法測試」時才引入，並用 Python 的輕量寫法。

| Pattern | 使用 | 用在哪裡 / 寫法 |
|---|---|---|
| Ports & Adapters | ✅ | broker、行情、ChatGPT、儲存；用 `typing.Protocol` 定義 port |
| Factory | ✅ 輕量 | 只在組裝點寫 `create_xxx(config)` 函式，或用 dict 註冊表；不寫 Factory 類別階層 |
| Strategy | ✅ | 行情 provider、策略規則等有多種實作的地方 |
| Observer / 事件 | ✅ | tick、狀態變化通知 UI |
| State machine | ✅ 必要時 | 委託單生命週期、ChatGPT 登入狀態 |
| Repository | ✅ | 資料存取集中，業務邏輯不直接讀寫檔案 |
| MVP / view-model | ✅ | 大型 UI 頁面；widget 只管顯示，邏輯放 presenter |
| Singleton | ❌ | 改由組裝點建立一份再傳下去 |
| Builder | ❌ | 使用 dataclass 與 keyword 參數 |
| 深層繼承 / Template Method | ❌ 盡量避免 | 改用組合 |
| Abstract Factory、Visitor、Command | ❌ | 目前沒有對應的問題 |

不引入 DI 框架；依賴注入就是透過建構子參數傳入。

## 5 階段計畫

### 5.0 PR 分組與執行順序

R0–R5 是工作內容，PR 依「變更類型」合併成 5 個，以減少 QA 輪數：

| PR | 內容 | 前置 | 可平行 |
|---|---|---|---|
| A | 本規格 + R0 盤點報告 + R1 分層閘門 | — | — |
| B | R2 全部搬檔 | A | — |
| C | R3 UI 群：strings、desktop_ui、forms、market、charts | B | 與 D 平行 |
| D | R3 核心群：desktop_runtime、desktop_chatgpt_*、saved_candidate_pool | B | 與 C 平行 |
| E | R4 + R5 | C、D | — |

- **搬檔與改內容不得放在同一個 PR**，以保留 git 的 rename 追蹤。
- C、D 各自在獨立 worktree 進行。字串拆檔後仍保留單一的查詢入口，呼叫端不需修改，避免 C、D 衝突。
- 搬檔、改 import、改字串 `mock.patch` 路徑一律用腳本批次處理，不手動修改。
- 開發中用 `tools/run_test_group.py` 跑相關測試群組；全部測試與打包 smoke 在送出 PR 前各跑一次。

### R0 Code review 與盤點報告（不改程式碼）

產出 `docs/analysis/08_REFACTOR_INVENTORY.md`，內容包含：

1. 每個受追蹤 `.py`（不含 `tests/`、`archives/`）的歸屬層與目標路徑。
2. 跨層依賴違規清單（以 GitNexus 呼叫圖與 import 分析為準）。
3. 重複程式碼與共用候選，附出現位置。
4. 死碼候選；GitNexus 回報 `UNKNOWN` 的項目必須以文字搜尋再確認。
5. 過度防禦寫法清單。
6. 超過 600 行的檔案，各附拆分方案。
7. R1–R5 的 PR 順序與相依關係。

驗收：涵蓋範圍完整；每項發現都附 `檔案:行號` 證據；拆分方案說明責任邊界。

### R1 分層閘門

- 擴充 `tools/check_trading_architecture.py`（或在 `tools/quality_gate.py` 加規則），讓第 3.1 節的依賴規則套用到整個 repo。
- 現有違規列入 allowlist，**allowlist 只能縮減不能新增**，由測試保證。

驗收：閘門已接入 CI；故意寫一個違規 import 時會失敗。

### R2 桌面程式搬家

- 根目錄 `desktop_*.py`、`desktop_pages/`、`desktop_trading/` 依 R0 對照表搬到 `desktop_app/`。
- 同步更新 import、`pyproject.toml`（packages、ruff per-file-ignores）、`packaging/markauto.spec`，以及測試裡用字串指定路徑的 `mock.patch`（目前約 170 處指向 `desktop*` 模組）。
- 這階段只搬檔、改 import，不改邏輯。

驗收：根目錄只剩啟動腳本；全部測試通過；打包 smoke（`packaging/desktop_regression.py`）通過。

### R3 拆肥大檔案

依 R0 排序，一個 PR 處理一個檔案。預定順序：

1. `desktop_strings.py`：依功能拆到 `desktop_app/strings/`。
2. `desktop_ui.py`：拆成 shell 與各功能 presenter。
3. `quantlab/desktop_runtime.py`：拆成 application 服務，並移出不屬於核心的部分。
4. `desktop_chatgpt_*`：UI、provider、auth 依層分開。
5. `desktop_forms.py`、`desktop_market.py`、`desktop_charts.py`。
6. `quantlab/saved_candidate_pool.py`：檔案內有凍結的 producer 字面值（ruff 刻意排除），拆分時必須逐位元保留這些字面值，並加上比對測試。

驗收：各檔達到第 4.1 節的目標或附例外說明；行為測試不變。

### R4 抽共用元件與研究核心分層

- 依 R0 的共用候選，建立 `desktop_app/components/` 與 `quantlab/shared/`。
- `quantlab/` 根層的研究檔案，只處理 R0 標出有跨層違規或過大的部分，移到 `quantlab/research/` 的分層結構；不為了目錄整齊而全面搬移。
- 外部服務統一改走 port，例如行情 provider 改用 Strategy + 註冊表。

驗收：重複程式碼清單中的項目已合併；閘門 allowlist 縮減。

### R5 清理

- 移除 R0 確認的死碼與過度防禦寫法。
- 刪除 `archives/legacy_autotrading/`，git 歷史保留可追溯；同步更新參照它的閘門與測試。
- 更新 `01_PROJECT_ARCHITECTURE.md` 與 `CONTRIBUTING.md`，寫入本規格第 4 節的規範。

驗收：閘門 allowlist 清空或只剩附理由的項目；文件與實際結構一致。

## 6 每個 PR 的共通驗收條件

1. **行為不變**：產品行為不得改變。測試的修改由執行者全權決定，不需詢問擁有者，包括：import 與 patch 路徑、斷言、fixture 與基線、搬移或拆分測試檔、刪除已無對應程式碼的測試、為新結構補寫測試。唯一限制是守護安全閘門的測試不得被弱化。所有測試修改都要在 PR 說明逐項列出原因，交給 QA 複核。
2. 修改前已執行 GitNexus `impact`；HIGH / CRITICAL 風險必須在 PR 說明。
3. commit 前已執行 GitNexus `detect_changes`，且結果不是 partial / truncated。
4. ruff、全部測試、分層閘門（R1 之後）都通過，CI 綠燈。
5. 由獨立 QA 驗收，控制者不能驗收自己的實作。
6. 依第 5.0 節分組；搬檔與改內容不混在同一個 PR。

## 7 不做的事

- 不新增功能，不修改交易或研究的業務規則。
- 不更換技術堆疊：PySide6、SQLite、現有測試框架都保留。
- 不引入 DI 框架、import-linter 等新依賴；沿用現有閘門工具擴充。
- 不放寬任何既有的安全閘門。

## 8 風險與對策

| 風險 | 對策 |
|---|---|
| 搬檔後字串形式的 `mock.patch` 路徑失效，測試反而變成假通過 | R2 用 GitNexus 找出所有參照；搬完後確認被 patch 的目標確實存在 |
| 打包遺漏新模組路徑 | 每個搬檔 PR 都跑打包 smoke |
| PySide6 或 SDK 在 import 時有副作用，搬動後載入順序改變 | R0 列出有 import 副作用的模組，R2 優先處理 |
| 和進行中的功能開發衝突 | 重構期間，功能 PR 先合併或暫停；搬檔 PR 盡量小、快速合併 |
| 凍結字面值被格式化工具改動 | 維持 ruff 排除設定，並加上逐位元比對測試 |

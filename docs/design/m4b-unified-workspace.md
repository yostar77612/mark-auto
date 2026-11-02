# M4b：研究與交易共用工作區設計

狀態：提案，待 Claude 審查；本 PR 只新增本文件，不實作、不遷移使用者資料。
盤點基準：main `63879689a290aab800f0d3681f4a36ff73ca6018`，已包含 M4a（#158）。
日期：2026-11-03（Asia/Taipei）。

作業依據：[Codex 作業規則](codex-work-rules.md)、[M1 規格 0.1–0.3](m1-implementation-spec.md)、
[分層與安全規則](../CONTRIBUTING.md)、[既有 v2 相容性契約](../implementation/multi-market/UPGRADE_CONTRACT.md)。
只在檔案、程序與設定輸入邊界驗證，不建立通用遷移框架，不重複驗證已解析的內部物件。

## 1. 目標、範圍與決策

正常安裝只有一個工作區選擇、一個使用者設定來源、一個研究／交易資料集合；
LOCAL、BROKER_SIMULATION 仍各有獨立的帳本與身分，研究 Paper 帳本也維持獨立。
「統一」指儲存位置、路徑解析與設定權威，**不合併財務事件、不更換帳號、不恢復自動交易**。

本設計做以下決定，後續實作不得自行改成雙寫或遺失資料的捷徑：

1. 保留研究工作區原位置與內部結構，將受管理的交易根目錄複製至該工作區下。
   避免為了整齊再次搬動研究檔案、改變備份身分或修改 G3 消費者。
2. `credentials`、`control-v1` 與主機初始化證據仍從固定 bootstrap 原路徑讀取。
   固定的是位置；控制資料仍由既有權威單調寫入，並非唯讀。
3. 設定匯入一個 `settings.json`，以研究、UI、交易 context 命名空間隔離；
   不維持新舊設定雙寫，也不對同名鍵做最後寫入者勝出的猜測。
4. 遷移採「備份 → 複製 → 驗證 → 發布切換紀錄」。不搬走、不刪除、不覆寫來源。
   後續清理舊資料需要另一項明確授權，本設計沒有自動清理期限。
5. 先交付過渡版（bridge），再啟用自動遷移。任意更舊的二進位檔無法被新增標記追溯約束，
   不把「新增格式版本」宣稱成完整降級保護。
6. LIVE 交易在程式邊界持續硬性關閉，沒有設定、遷移或復原的解鎖入口。
   不改引擎／領域／應用層交易決策、不碰 G3 鎖定檔、SDK 版本或驗收分數。

本文件是未來儲存整合的設計；審查通過本文件不代表已完成遷移或真實帳號驗證。
它只擬取代 v2 舊契約的「資料位置／設定來源分離」部分；v1 永久禁單、帳本隔離、
不可逆預算、OOS、單一交易提交權威與風控契約全部保留。實作 PR 才追加相應行為契約。

## 2. 現況與路徑權威

以下僅讀取程式碼，未開啟真實工作區、憑證或財務資料。

| 名稱 | 現況與解析方式 | 來源 |
| --- | --- | --- |
| `B`：固定 bootstrap | Windows Known Folder 的 Local AppData 加 `MarkAuto`；不依工作目錄或環境變數猜測 | [AppPaths.discover](../../quantlab/research_core/adapters/workspace_store.py) |
| `R`：研究根目錄 | 預設 `B`；有 `B/workspace-location.json` 時使用其中已驗證的本機絕對路徑 | [WorkspaceLocator](../../quantlab/research_core/adapters/workspace_store.py) |
| `T`：交易預設根目錄 | 現為環境變數 Local AppData 下 `MarkAuto-v2/local`，無變數時走既有 home fallback | [default_root](../../trading_runtime.py) |
| context 資料 | `T/contexts-v2.json` 記錄 context 身分、環境、帳號、絕對 root、profile 及目前選擇；可另有 `context-engines/*` | [RuntimeContextManager](../../quantlab/trading/runtime/context_client.py) |
| 固定安裝身分 | `B/credentials`、`B/control-v1`、host markers、研究單例鎖不隨 `R` 改變 | [研究路徑](../../quantlab/research_core/adapters/workspace_store.py)、[研究 session](../../desktop_app/research_session.py) |

`--research-bootstrap`、`--trading-root`、`--trading-contexts` 是顯式隔離／開發入口，
不把它們推論為預設工作區來源；smoke 保持隔離。若舊環境變數與 Known Folder 指向不同位置，
先列出候選與已存在來源；出現兩套有內容的候選就停止自動遷移並顯示具體衝突，不能選最新檔。
後續正常預設路徑統一用 Known Folder；顯式隔離入口仍以明確傳入值為準。

## 3. 目標資料夾結構

預設 `R = B = %LOCALAPPDATA%\MarkAuto`；已有自選研究根目錄時維持該 `R`，
只有固定 bootstrap 身分留在 `B`。全程不建立 junction／symlink，現有交易 root 邊界拒絕 reparse points。

```text
B/                                      # 固定每位 Windows 使用者的 bootstrap
  workspace-location.json               # 既有唯一位置指標；不是另一份產品設定
  desktop.lock                          # 既有研究單例鎖，不搬移、不偽造
  migration-compatibility.json           # 新：過渡版／新版共同辨識的啟動 fence
  migrations/<migration-id>/journal.json # 新：持久遷移狀態、來源與切換證據
  credentials/                          # 原位置、原保護方式、原引用名稱
  control-v1/                           # 原位置、不可回退的控制與稽核紀錄
  chatgpt-oauth-host-v1.marker           # 原位置、原 bytes
  chatgpt-plan-controls-v1.marker        # 原位置、原 bytes
  .analysis-recovery-v1.json             # 原位置、原恢復權威
  automatic-backups/<workspace-id>.json  # 保留 durable 每日嘗試 watermark

R/                                      # 一個啟用中的研究＋交易工作區
  workspace-format.json                 # 既有研究格式標記，原樣保留
  workspace-layout.json                 # 新：已提交 layout、workspace-id、migration-id
  settings.json                         # 新：唯一產品設定文件
  state-v1/                             # 研究資料／Paper／證據，原位置
  cache/                                # 研究 cache，原位置
  logs/                                 # 研究 logs，原位置
  session.json                          # 既有 session／未乾淨關閉證據
  trading/contexts/<context-id>/         # 受管理交易資料，context 身分不變
    trading-v2.sqlite                   # 各帳本維持原檔名／各自 schema
    simulated-exchange-v2.sqlite
    broker-trading-v2.sqlite
    manual-trading-v2.sqlite
    manual-resources-v2.sqlite
    readiness-v2.sqlite
    runtime-control-v2.sqlite
    official-stock-research.sqlite
    .sinopac-account-alias.key           # 該 context 原 key，不重新生成
    market/                             # 商品、K線、官方日線、警示歷史
    research/minute-receipts.sqlite3
    logs/engine-startup.log
    legacy-preserved/                    # 該 context 其他原檔與原始設定封存
  .m4b-staging/<migration-id>/           # 新：只在遷移中使用，禁止啟動 writer

%LOCALAPPDATA%/MarkAuto-migration-backups/<migration-id>/
  manifest.json                         # 完整清單／雜湊／來源身分／版本
  bootstrap/                            # 固定身分與控制資料的封存副本
  research/                             # R 的遷移前完整快照
  trading/<source-id>/                   # 各交易 root 的遷移前完整快照
```

備份是獨立復原副本，不是第二個啟用中的工作區。若 `R = B`，同一實體檔只登記／複製一次，
manifest 保留兩種角色；禁止遞迴把本次備份與 staging 再納入自己。
本次正在變動的 fence、journal 與 admission 記錄另列為協定產物，不算進使用者來源 hash；
較早 migration 歷史仍獨立封存，不以整個 `migrations` 目錄為由省略既有證據。
輸出目錄名稱若已被使用者資料占用，停止，不挪走或覆寫該目錄。

路徑解析在 composition 建立一個型別明確的 `WorkspacePaths` 快照後傳入；
presentation 不自行拼接路徑，領域／應用層不依賴 bootstrap 或檔案系統。
layout 版本、各 JSON schema、各 DB schema 與應用程式版本分開記錄。

遷移後切換工作區同樣先停止所有相關 writer，再更新唯一位置指標並重新解析目標 `R` 的
layout／settings／workspace-id；不沿用先前的路徑快照。固定 bootstrap fence 按 workspace-id／canonical root
保存已納管映射與當前選擇，不能以換一個空 `R` 再次吸收已封存的同一 `T`。
已納管來源的身分登記在 bootstrap migration 歷史中，重複匯入／衝突映射一律停止。

## 4. 每類檔案的遷移方式

「留原路徑」表示新版持續以該位置為權威；「匯入」表示讀取舊資料一次、驗證後改由新來源提供。
「複製」均是驗證後切換，舊來源與備份仍保留。所有既存隱藏檔、未知檔、歷史封存、
quarantine 與未完成工作一律進完整 manifest，不能只搬白名單內成功結果。

### 4.1 研究與固定 bootstrap

| 舊路徑／模式 | 新版處理 | 必保留語意 |
| --- | --- | --- |
| `R/workspace-format.json`、`B/workspace-location.json` | 留原路徑，不修改原格式來阻擋舊程式 | 原 schema／WAL runtime 要求及自選 root |
| `R/state-v1/settings.json` | 原檔保留，匯入 `settings.json` 的 `research`／`ui` 對應 namespace | 所有已知及未知鍵；停用的歷史 provider 設定不因此恢復執行 |
| `state-v1/paper.sqlite3`、`paper_policy.json`、`paper_snapshot.json`、`paper_journal_export.json` | 留原路徑，完整一致快照後驗證 | 原財務日誌、決策與政策，不併入 v2 |
| `state-v1/replays/*.sqlite3` | 留原路徑，快照包含 SQLite sidecars | 回放帳本、序列與證據 |
| `dataset.json`、`dataset_calendar.json`、`synthetic-demo-dataset.json` | 留在 `state-v1` 原位置 | dataset hash／calendar binding，不改成交易資料集 |
| `selection.json`、`active_candidate.json`、`active_result.json`、`disabled_selections/` | 留在 `state-v1` 原位置 | 既有參照、停用原因與歷史，不啟用策略 |
| `state-v1/reports/`、`campaigns/`、`analyses/`、`walk_forward/`、`runs/` | 完整樹留原位置 | JSON、SQLite、partial／unknown、所有研究與分析證據 |
| `state-v1/market_cache/`、`market_history/`、`R/cache/` | 留原位置，既存檔仍備份 | 不和交易 `market/` 混存，不以可重建為由刪除 |
| `state-v1/market-layout-v1.json` | 匯入 `ui.research_layout`，原檔保留 | 原 panel／尺寸；與交易 terminal layout 分開 |
| `R/logs/**`（含 `desktop-events.jsonl`） | 留原位置，完整備份 | 不因 `persist_logs` 關閉而略過既有歷史 |
| `R/session.json` | 保留並交既有未乾淨關閉流程判斷 | 不假造乾淨 session，不在盤點時刪除 |
| `state-v1.rollback/`、`restore-transaction.json`、`.restore-transaction`、`state-v1.interrupted-*` | 先識別既有 recovery 狀態；未解決就阻擋 M4b | 封存原 bytes；既有復原的必要寫入須先完成，之後重做遷移前快照 |
| `state-v1/provider_budgets/*`、`campaigns/.holdout_registry.sqlite3*` 等舊控制殘留 | 保留；沿用既有 fail-closed，不自動清空或轉為新預算 | 不可逆預留／看過的 holdout 不得重置 |
| `B/control-v1/**` | 留原路徑，封存副本僅供稽核，禁止一般 rollback 還原 | holdout registry、方案／分析預留、unknown outcomes、analysis recovery epoch |
| `B/credentials/**`、兩個 host markers、`.analysis-recovery-v1.json` | 留原路徑；備份只複製不透明 bytes，限制目前使用者權限，不解密／記錄內容 | 既有 DPAPI 身分、主機證據、憑證引用與恢復權威；不進一般研究 ZIP |
| `B/automatic-backups/<workspace-id>.json` | 保留原 ID、`last_attempt_day`／status／archive；enabled／directory 匯入單一設定 | 原 ID 依 `R.resolve()` hash 產生，故 M4b 不搬 `R`；不可重置每日嘗試 watermark |
| `B/desktop.lock`、credentials 內 lock、control admission lock | 保留原鎖位置；依既有權威取得／釋放 | 備份可保留診斷副本，但不把鎖檔當成可還原的 ownership |

研究原始碼依據：[workspace_store](../../quantlab/research_core/adapters/workspace_store.py)、
[SettingsStore](../../quantlab/research_core/adapters/settings_store.py)、[paper operations](../../quantlab/research_core/application/paper_operations.py)、
[研究備份](../../quantlab/research_core/adapters/workspace_backup.py)、[自動備份](../../quantlab/automatic_backup.py)、
[analysis recovery](../../quantlab/analysis_recovery.py)。G3 認證與研究來源消費者不修改。

### 4.2 交易 root 與每個 context

先解析既有 registry。只有舊預設 `T` 及 registry 明確指向、位於 `T/context-engines` 內的受管理 root
可自動複製；每個 root 映射到 `R/trading/contexts/<既有 context-id>`，保留帳號／環境／context 身分。
registry 缺失時，只有經既有 LOCAL 格式確認的預設 root 才建立 `local` 映射。
重複 root、衝突 context、非空目的地或來源不完整均停止；不能自行替財務身分改名。

| 舊相對路徑 | 新版處理 | 檢查重點 |
| --- | --- | --- |
| `settings.json` | 匯入單一設定 `trading.contexts.<id>`；原件封存 | `market_watch_v2`、`market_data_v1`、`market_terminal_v1`、`sinopac_*` 全部保留 |
| `stock_maintenance.json` | 匯入該 context 的 maintenance namespace | 原 cost inputs、所有 `cost_versions_v1`、expiry metadata；不只留最新成本 |
| `contexts-v2.json` | 匯入單一設定的 context registry | selected／connection context、account、environment 原值；只更新已驗證映射的 owned root |
| `trading-v2.sqlite`、`simulated-exchange-v2.sqlite` | 同一停止寫入時點的一組快照，分別複製到新 context | 應用帳本與模擬交易所相符，不合併 events |
| `broker-trading-v2.sqlite`、`manual-trading-v2.sqlite`、`manual-resources-v2.sqlite` | 逐本一致複製 | 原訂單／成交／資源／unknown 狀態與 journal hash chain |
| `readiness-v2.sqlite`、`runtime-control-v2.sqlite` | 複製，保留 durable 記錄 | 能力與版本 high-water 不歸零；不把 readiness 等同登入或可送單 |
| `official-stock-research.sqlite`、`research/minute-receipts.sqlite3` | 複製，獨立驗證 receipts／digest | 研究證據，不是可刪 cache |
| `.sinopac-account-alias.key` | 原 bytes 複製到同 context | 原 32-byte 身分材料；不可生成新 key 替代或輸出內容 |
| `market/symbol_directory.json`、`market/klines.sqlite3` | 複製到該 context 的 `market` | 商品、分鐘棒、官方日線、公司行動、股息、raw payload、coverage 都保留 |
| `market/alert_rules.json` | 匯入該 context 的設定 namespace，原件保留 | 不在遷移時呼叫會修改／隔離資料的 loader |
| `market/alert_events.jsonl`、`.archive-*`、`.bad-*` | 完整複製，保留相對命名與原內容 | 不執行 active-view 截短或歷史清理 |
| `trading-presentation-v1.json`、`market-terminal-layout-v1.json` | 匯入 `ui.trading.<id>`，原件封存 | columns 與 layout 彼此分開，也不覆蓋研究 layout |
| `engine-startup.log` | 複製至該 context 的 `logs`，遇同名停止覆寫 | 保留歷史輸出，不混到別的 context |
| `engine-session-v2.json`、`session-*.tmp`、owner lease | 只備份／診斷封存；新位置不發布舊 active endpoint | PID、IPC auth／address 不重用；新 host 依原流程取得 lease／建立 session |
| `*-wal`、`*-shm`、`*-journal` | 依第 6 節整組快照；不獨立刪除 | WAL 可含已提交事件；hot journal 是復原資料 |
| 其他未識別／隱藏／備份檔 | 原樣複製到 `legacy-preserved`，manifest 記錄原相對路徑 | 不執行、不推論可丟棄，不遺漏任何可能的財務日誌 |

顯式外部 root、profile 及其資源維持原路徑讀取，列為「外部參照」，不默默搬移或納入 managed root。
由 managed registry 參照的外部 engine 也必須停止，才可匯入其設定／啟用整體工作區。
這些正常 registry context 的產品設定仍須一次匯入 `R/settings.json`，從此使用同一 repository／revision；
外部保留的是帳本、market、key 與 profile 路徑，不是第二份正常設定權威。
外部 context 的原始設定與資料同樣要有完整遷移前快照；無法納入 admission、備份或設定匯入就阻擋整體提交。
外部 profile 的 hash、內部 absolute references 與財務 identity 不改寫。
顯式 CLI 隔離模式維持原入口／原設定權威，不能同時註冊成 unified managed context；
bridge／新版的 CLI 也必須拒絕以舊設定啟動已納管的外部 root writer，
未來要納管須另行驗證與明確匯入，不能自動吸收。

依據：[context registry](../../quantlab/trading/runtime/context_client.py)、[LOCAL build](../../quantlab/trading/runtime/build.py)、
[bootstrap](../../quantlab/trading/runtime/bootstrap.py)、[Ledger](../../quantlab/trading/adapters/storage/ledger.py)、
[account aliases](../../quantlab/trading/runtime/sinopac_aliases.py)、[stock maintenance](../../quantlab/trading/runtime/stock_maintenance.py)、
[minute research](../../quantlab/trading/runtime/minute_research_host.py)、[daily storage](../../quantlab/trading/adapters/storage/daily_stock_store.py)。

## 5. 單一設定來源

`R/settings.json` 擬用獨立 `settings_schema: 1`，含 `revision` 與 `research`、`ui`、
`trading.contexts`、`maintenance` namespaces；context registry 也在同一文件。
layout marker 只記版本與切換身分，不再存一份可變 context 清單。

- 研究欄位保留原值；embedded research 與 standalone window geometry 使用不同 UI namespace，
  不讓研究頁關閉時覆蓋桌面主窗尺寸。
- 交易參數按 context／account 原範圍隔離。帳本、風控狀態、停止新倉 latch、成本歷史及不可逆控制
  都不是能以普通設定還原的布林偏好；保留既有 durable authority。
- secret 只保存既有引用。DPAPI blob、alias key、IPC auth、CA 與 API secret 不寫進設定、錯誤或 log。
- `WorkspaceSettingsStore` 是唯一設定持久化邊界。桌面與獨立 engine 各透過同一 repository 寫入，
  在同一 workspace OS writer lock 下讀取最新 revision、套用型別明確的 namespace 更新、原子發布。
  revision 衝突回報並重新載入；不得以舊整份文件覆蓋別的程序修改，也不要求 engine 反向依賴 GUI 存活。
- 匯入清單逐一列出 old path／old key → new namespace／new key，保留未知鍵及型別、原檔與來源 hash。
  同一最終欄位有不一致來源時回報具體欄位並停止；不靠 mtime 決勝。
  既有 consumer 的相容 adapter 讀新 namespace，不再回讀舊檔作 fallback、不雙寫舊檔。
- `automatic-backups` 的 enabled／directory 是偏好，匯入新設定；每日嘗試 watermark 留在既有 durable 記錄。
  後續 adapter 不再讀舊偏好作第二權威。
- M4a 開機啟動值以 **HKCU Run 的 `MarkAuto` 實際值**為系統權威；設定頁即時查詢它，
  統一 JSON 不另外保存衝突的 enabled 值。只有使用者選擇才修改 HKCU，舊 opt-in 保留並修正 exe 路徑。
- 備份還原 UI／一般設定不能回退財務日誌、OOS／預算、控制 epoch 或自動啟用交易。

新 schema 或損壞文件必須在開啟 writer 前回報具體版本／格式錯誤，原件保留；
不得回傳空設定或重新生成空帳本來「成功啟動」。

一般研究備份／還原也必須接上新設定來源，不能只備份已不再更新的 `state-v1/settings.json`：
新版備份採明確的新 archive 版本，保留研究 state 並附有同 revision 的 canonical settings 快照及 digest，
計入原大小／檔案數上限；不納入 controls／credentials。快照含各 namespace 的來源證據，
普通研究還原只匯入允許的 `research`／研究 UI 偏好，不能還原 context registry、交易參數、
不可改寫成本歷史、帳本或 HKCU autostart。整套災難復原另走第 6 節的停止與財務保留規則。
舊研究 ZIP 繼續驗證原 schema，將其中舊 research settings／layout 轉為同樣範圍的更新；
不直接替換 canonical settings。未來 archive schema 拒絕寫入。
還原在 entry admission 下停止相關 writer，持有 settings writer lock，驗證目前 revision 後發布 scoped 更新；
研究 state 與 settings 的還原 journal 綁定同一 transaction，部分完成只進復原畫面，不能半套啟動。
自動備份使用相同新版格式並保留既有每日 watermark，不重設研究備份預算。

## 6. 自動遷移、備份與失敗回復

### 6.1 啟動順序與互斥

過渡版與新版的每個正常桌面／獨立引擎入口，在開啟任何 store、研究 worker 或 SDK 前讀取 bootstrap fence。
先以新的短期 bootstrap entry admission 與跨程序 migration lock 排除並行啟動，再檢查所有涉及 root 的
engine ownership／endpoint。既有 `desktop.lock` 仍只由研究桌面 lifetime 持有；獨立 engine 不取得桌面單例鎖。
安裝 presence mutex 不能當作排他的 migration lock。
同一鎖順序固定為 bootstrap entry admission → migration → 各 context admission；由同一 composition 協調，避免互等。

已在執行中的自有程序走現有乾淨關閉流程；重用或外部 host 不在 ownership 範圍內，
發現仍活著就停止遷移並提示該 context 未停止，不按程序名稱掃描或強制終止。
既有未乾淨研究 session／restore transaction 必須先由原 recovery 權威解決；無法確認則阻擋。
不能僅憑 lock 檔存在／不存在或 endpoint PID 一個欄位宣稱沒有 writer。

過渡版在取得 entry admission 後再檢查 fence，並持有既有 writer ownership 至結束；
遷移發布 `PREPARING` 後禁止新的 writer 進入，已進入的 writer 必須正常退出才可快照。
不可讓「檢查 fence → 開 DB」之間留下可與遷移交錯的空窗。

### 6.2 持久狀態機

| 狀態 | 已完成內容 | 下次啟動／失敗處理 |
| --- | --- | --- |
| `DISCOVERED` | 已解析 B／R／T、版本、bridge 證據與來源清單，無產品資料變更 | 可重做盤點；來源變動就重建計畫 |
| `PREPARING` | writer 被 fence 擋住；驗證容量、權限、路徑、DB 與復原狀態 | 未達無 writer 條件就中止，保留原資料 |
| `BACKED_UP` | 所有來源一致快照、manifest、hash 與可讀驗證完成並落盤 | 備份不完整／磁碟滿即停止，不能發布新 root |
| `COPIED` | 同目的 volume staging 中有轉換後設定與完整 context 副本 | 可取消；只重做該 migration 的衍生檔，不刪來源／備份 |
| `VERIFIED` | 第 6.3 節驗證通過，journal 綁定 source manifest 與 target manifest | 任一 hash／來源 drift 不符就 `RECOVERY_REQUIRED` |
| `COMMITTED` | 發布 workspace-layout 切換紀錄，fence 指向該已驗證 migration | 新版只開新設定與映射；過渡版拒絕舊布局寫入 |
| `RECOVERY_REQUIRED` | 狀態不一致、切換不明、資料變動或驗證失敗 | 只顯示停止中的復原畫面，禁止初始化空資料／自動選另一套 |

fence 與上表 journal phase 分開：fence 缺席表示 legacy；`PREPARING` 涵蓋所有未提交步驟，
`ACTIVE` 表示已提交且可由相容新版使用；`RECOVERY_REQUIRED` 阻擋 writer。
切換時持有 admission，依序發布已驗證的最終 context 目錄／設定 → workspace-layout →
`COMMITTED` journal → 最後 `ACTIVE` fence。只有所有記錄的 migration ID、layout 與 manifest 相符才放行。
任一步驟中斷，入口均不開 writer；不能看到目的目錄存在就使用它或 fallback 舊 root。

每個 migration 使用不可重用 ID，journal 記來源 canonical path／身分、版本、每檔 size／hash、
DB schema／事件尾端、backup／staging／destination 及目前步驟。路徑與錯誤資訊不含憑證內容。
寫入 journal／單檔切換記錄時沿用可靠落盤做法；發布失敗先保留證據，不把多次 rename 當成跨根目錄交易。
啟動 recovery 以 journal、完整目標與 layout 記錄的相同 migration ID 驗證：
有效 COMMITTED 可冪等續行，殘留 staging 不能自行升格；部分發布或撕裂紀錄進停止復原。

不刪除來源設定或 journal，不能為阻擋舊版而改壞原 `workspace-format.json`。
原來源是否未變以 manifest 比對；其中原位置繼續使用的研究資料／controls 不做「永遠不變」假設，
改由正常 authority 與遷移前後 watermark 檢查。來源 drift 偵測主要針對已封存、不再啟用的舊交易 root／設定。

### 6.3 一致性備份與驗證

既有研究 `BackupManager` 只涵蓋 `state-v1`，排除 controls／credentials／cache／logs，
另有 512 MiB／10000 檔上限，**不能當成本次完整遷移前備份**。
M4b 封存工具獨立於一般研究還原，只處理這份確定的來源集合，不改既有備份預算。

1. 在所有涉及 writer 正常退出後，先保存原始整組檔案：SQLite main、同時點的 WAL／SHM／rollback journal、
   JSON、歷史 exports、logs、未知檔與固定 bootstrap 身分。來源只讀，不 checkpoint、不開會取得 lease 的 `Ledger` 建構子。
2. 備份位於獨立、可寫入的本機使用者目錄。先估算原始備份＋staging＋目的副本＋DB 快照空間；
   空間不足、備份路徑在來源內、不可讀檔案、reparse／UNC／目的衝突都停止，不省略大帳本繼續。
   機密副本維持使用者存取限制，不產生一般可分享 ZIP，也不解密 DPAPI。
3. 原始備份落盤並驗證 bytes 後，從 staging 的原始副本進行必要 SQLite crash recovery，
   再用 SQLite backup API 產生可啟用快照。不能移除 hot WAL／journal、只複製主 DB 或讓來源在備份過程被改寫。
4. 每個 DB 驗證 schema、完整性及既有 verifier；財務 events 比較 count、sequence、previous_hash／digest 全鏈、
   尾端及原 payload；receipt DB 比較序列／digest。金額 Decimal、UTC／時區、account/context、
   unknown outcomes、outbox 與 replay 結果一致。LOCAL 兩帳本及所有 context 同屬一個停止寫入時點。
5. 目的地暫時 ownership lease／session 不可冒充仍有效；依既有 backup 契約移除**衍生目的副本**的 lease，
   保留原始備份、事件與 durable runtime-control high-water。alias key 必須逐位元相同。
6. 設定逐欄驗證；檔案總數／大小／hash 及未知檔 manifest 完整覆蓋。SQLite backup 可正規化頁面，
   其物理 SHA 不要求等於原 DB；原 bytes hash 與邏輯帳本證據分別驗證，不能互相取代。

SQLite 的 [WAL 說明](https://www.sqlite.org/wal.html)、[backup API](https://www.sqlite.org/backup.html)、
[hot journal 與不安全複製](https://www.sqlite.org/howtocorrupt.html) 是上述一致性要求的依據。
[Windows ReplaceFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew)
只提供單檔操作及其錯誤語意，不代表兩套目錄可一次交易提交；所以保留 journal 與啟動 recovery。

### 6.4 取消、重入與回滾

- COMMITTED 前可取消複製；完成目前安全的檔案邊界即停止，不留下可啟動的半套目標。
  原資料／已完成備份保留。驗證與發布的短暫不可中斷段顯示具體步驟，完成後才回報取消結果。
- 同一來源 manifest、版本與目標的重入只續做已驗證步驟；不能重匯入設定、重加事件或生成新帳號 key。
  COMMITTED 再啟動是讀取現有映射；不是再次遷移。舊來源新增內容不能被默默覆蓋或合併。
- 任何錯誤顯示具體階段、檔案類別、原因與下一步，例如容量不足、來源仍有 writer、
  DB 完整性／hash 不符、設定版本未知、目的已存在、發布紀錄不一致；不用籠統的「失敗」。
  後續 ErrorText 放新功能字串／錯誤條目，不把機密值放進 detail。
- COMMITTED 前可經驗證解除本次 fence、停用 staging，回到原版相同資料集合；
  對既有研究 recovery 所作合法變更不逆轉，controls／憑證不從備份回寫。
- COMMITTED 後每次開啟產品 writer 前，先在 admission 下持久記錄 `first-writer-admitted` epoch。
  撤回映射前先擋住 admission、發布 blocking fence，再確認全體 writer 停止與所有證據。
  只有從未 admission 任何新 writer、且無新寫入證據時才可撤回；marker 已存在或狀態不明，
  即使無法證明實際寫過也**禁止自動還原舊快照或自動切回舊交易 root**。
  保留兩邊資料與尾端證據，修復新版或做明確的相容匯出／reconciliation；不拼接事件鏈、不重送舊 outbox。
- 復原後維持停止新倉／未 reconciliation，不自動恢復自動交易。所有財務日誌與未知結果均須可追溯，
  不以重建空資料庫或回退預算消除錯誤。

## 7. 版本、升級與降級保護

先發布 `M4b-0 bridge`，仍使用舊資料布局；其正常桌面及獨立 engine 入口都辨識固定 bootstrap fence，
在啟動 admission 下記錄 bridge-seen 版本證據。正式版本號在該 release 建立時固定，
不得以寬鬆的「版本較大」比較替代相容性清單。

新版 layout 1 的 `workspace-layout.json` 記錄 layout 版本、workspace-id、migration-id、
最小 reader／writer 應用版本與所需獨立 DB schema。fence 狀態與已驗證 journal 相互綁定。
未知未來版本不得開 DB、寫設定、回讀舊路徑或清空重建。

全新安裝是獨立分支：只有所有候選舊來源、控制／主機 markers、已存在目的與遷移證據均不存在時，
才能直接建立 layout 1 與停止交易的單一預設設定，不需 bridge、不進既有資料遷移。
此分類在建立本次協定檔前完成，不能把自己剛寫的 admission／journal 當成舊資料。
只要存在歷史資料或身分證據就適用既有工作區規則；殘留／未知／缺部件不能當成全新安裝。

| 程式／資料組合 | 必須行為 |
| --- | --- |
| 經完整檢查的全新安裝 | 直接初始化 layout 1；不建立舊布局，不要求 bridge |
| bridge 啟動既有布局、無遷移 | 舊行為，建立已測過的 bridge-seen 證據 |
| bridge 遇 `PREPARING`／`ACTIVE`／`RECOVERY_REQUIRED` fence | 拒絕正常 writer 啟動，顯示停止中的升級／復原說明，不寫舊帳本 |
| M4b 新版遇合法 bridge 來源 | 開 stores 前自動遷移，進度可見；成功後仍停止新倉 |
| 從更舊版本直接跳 M4b、沒有 bridge 證據 | 停止於啟動說明，不遷移、不啟動 engine，指明先安裝並啟動指定過渡版 |
| 新版遇已提交 layout 1 | 驗證後只使用新設定／映射，保留舊來源作證據 |
| 新版遇未來 layout／settings／DB schema | 明確版本不相容，原件保留，不降版寫入 |
| 使用者啟動 pre-bridge 舊 exe | **不支援降級**；舊 exe 可能寫舊 root，無法追溯阻擋；新版下次偵測舊來源 drift 即停止並保留雙方歷史 |

已發布舊版不認新 fence，原路徑保留就存在分叉風險。安裝程式的支援版本矩陣／降級拒絕與
bridge 測試可保護受管理的更新流程，不能阻止使用者複製任意舊 exe 執行。
不使用 junction、修改舊 DB schema／研究 marker、唯讀 ACL 或刪來源來偽裝完整防護。
既有研究格式拒絕測試只能證明舊 reader 不接受新格式，不能證明舊 v2 不會寫回原 root。

降級應優先回到可讀 layout 1 的相容程式版本；需要回到舊布局時另做停止中的相容匯出，
不能把「回退 UI／exe」當成「回退帳本、券商責任或不可逆控制」。

## 8. 與一鍵更新、乾淨關閉及開機啟動的互動

M4a 的 manifest／來源白名單／SHA256／使用者確認／未簽章限制不變。
下載或安裝程式不負責遷移，也不直接寫工作區。

1. 更新仍先經使用者確認、完整下載及 hash 驗證。
2. [現有乾淨關閉](../../trading_runtime.py) 只等待本視窗持有 Popen 的自有引擎，
   保留原總計五秒與 zero-exit 判準；失敗中止更新，不強制終止，也不延長原 budget。
3. [安裝 helper](../../quantlab/update_install.py) 等原桌面退出、確認沒有安裝 presence guard，
   重新驗證 installer，再等待靜默安裝 exit 0 及 verified payload marker 後重開程式；
   仍使用 `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`。保留原三十秒 desktop 等待上限。
4. 新版重新開啟後，在研究 session、任何交易 context 與一般設定 store 開啟前進入 M4b 啟動協調。
   bridge 缺失、遷移錯誤或還有外部 writer 時，停在復原畫面，不自動回開另一套帳本。
5. [Inno 安裝程式](../../packaging/markauto.iss) 保持資料保留行為；不能在 uninstall 或 failed update
   清掉來源、遷移備份、fence 或 journal。舊快捷方式／安裝位置修正與工作區版本是不同事情。
6. [開機啟動](../../quantlab/autostart.py) 也走相同新版入口與 admission；遇未完成遷移只顯示停止中的復原畫面。
   既有 HKCU opt-in／exe 路徑修正保留，不建立新的管理員需求、系統設定或排程交易入口。

重啟、升級、遷移、還原、開機啟動全部維持「停止新倉，需使用者 reconciliation 及明確恢復」。
不因設定曾保存 running／automatic 就送單，也不重播 outbox；LIVE 硬關不受任何匯入值影響。

## 9. 測試與驗收計畫

後續實作每個守衛都需要可獨立使其測試失敗的案例；不降低既有斷言、逾時、預算與 coverage。
只用隔離 temp roots／假程序／fake SDK；不讀真實 AppData、不登入券商、不啟用 CA。

| 區域 | 必測案例與獨立判準 |
| --- | --- |
| 路徑與完整盤點 | R=B、自選 R、只有研究／只有交易／全新安裝、多 context、未知及隱藏檔、兩個候選 root 衝突、missing pointer、外部 root/profile、不合法 root；每項來源均出現在 manifest |
| 工作區切換 | 全體 writer 停止、重新解析目標 layout/settings、空 R 不重吸舊 T、bootstrap 多 workspace fence 與來源映射一致 |
| 固定身分 | control／credentials／host marker 位置與 bytes、alias key、既有 secret refs 不變；已消耗預算、holdout／unknown、analysis epoch 不下降；不記錄機密 |
| 設定匯入 | 每個舊檔／鍵的獨立 fixture、未知鍵／型別、同名跨 namespace、真衝突、成本歷史、研究 embedded geometry、autostart 真實權威；無雙寫／無舊檔 fallback |
| 日常備份／還原 | 新 archive roundtrip、舊 ZIP research scoped 匯入、設定快照 revision／digest、未知 schema／namespace、並行設定寫入、state/settings 半途 crash；不回退交易或不可逆資料 |
| 設定並行 | 兩程序同 revision、不同 namespace 更新、writer crash、獨立 engine 在 GUI 關閉後儲存、lock 順序；衝突不覆蓋、不遺失其他設定 |
| SQLite 與財務 | 已提交 WAL 尚未 checkpoint、hot journal、壞鏈／缺 row／receipt、LOCAL 兩帳本一致點、不同 context 帳號、unknown outbox、high-water；驗證所有原事件與原 bytes 備份，不建空帳本 |
| 快照與檔案錯誤 | 大於既有研究 ZIP 限額的日誌、容量不足、不可讀／寫、hash 不符、複製中斷、目的非空、備份路徑在來源內、UNC／reparse；任何一項失敗都不得發布 |
| admission／程序 | migration 競爭、fence 後新 engine 啟動、既有 owned child、reused／external host、PID／endpoint 變動、關閉逾時／非零、未完成研究 recovery；全部不強制終止 |
| crash／取消／冪等 | 狀態機每個持久寫入與發布邊界前後 fault injection；取消、重啟兩次、部分 layout／journal、來源 drift；成功不重加事件，未知狀態停止 |
| 版本與回復 | bridge 每個 desktop/engine 入口、直接跳版、未來 layout/settings/DB、pre-bridge 分叉偵測、已新寫入後拒絕自動舊快照；保留原兩份帳本與 tail 證據 |
| 更新／打包 | 假 HTTP／installer 完成 M4a 流程後新版啟動遷移；安裝非零、關閉失敗不遷移；實際 Windows 安裝／升級／保留資料 uninstall／中斷 recovery |
| 交易安全與 UI | LOCAL、BROKER_SIMULATION fake SDK 真實視窗各一次、兩尺寸；遷移進度／錯誤／恢復狀態；開機重啟仍 STOP_NEW；任意設定匯入不能開 LIVE／自動恢復交易 |

可沿用測試起點：`test_runtime_context_client_v2`、`test_runtime_context_cli_v2`、
`test_trading_graceful_exit`、`test_trading_engine_cleanup`、`test_restart_availability_contract`、
`test_watchlist_settings`、`test_m2_stock_maintenance` 與既有研究 workspace／backup 測試。
新增 migration／settings 測試放專屬模組，不修改歷史 G3 oracle／producer profiles。

實作本機用 `python tools/affected_tests.py` 選相關模組並做必要原生啟動檢查；完整回歸交 CI，
打包相關變更依既有規則跑 Windows 安裝驗證。每輪 CI 重跑全部 jobs；基準用
`python tools/repin_baselines.py` 集中產生，獨立 commit。每個 PR 直接對 main，不堆疊；
合最新 main 後 CI 全綠並等 Claude 審查，不自行合併。

本次 docs-only PR：驗證文件連結、repo layering／layout 與受影響測試；
未改程式，原生啟動、遷移故障注入及 Windows installer 實測列為後續驗收，不宣稱已通過。

## 10. 分階段實作與可並行工作

| 階段 | 工作、預計檔案區域 | 依賴／可並行 | 完成條件 |
| --- | --- | --- | --- |
| M4b-0 | bridge admission／固定 bootstrap fence、獨立 engine 與桌面入口；相容性矩陣與 release 說明 | 先於啟用遷移；可與 1a／1b 的離線開發並行 | 舊布局行為不變；fence 所有入口拒絕寫入；指定 release 已發布且啟動建立證據 |
| M4b-1a | 明確路徑物件、只讀 inventory、完整 snapshot／manifest；新增相鄰 infrastructure 模組 | 與 1b 可並行；先共用一份型別／namespace 契約 | 所有已知／未知來源可追溯；含 WAL 的財務證據完整 |
| M4b-1b | 單一 settings repository、namespace 匯入／衝突、writer lock；研究與交易 runtime、BackupManager／AutomaticBackup adapters | 與 1a 可並行；共用檔由同一整合負責人編輯 | 無雙寫、備份／舊 ZIP 還原不遺失設定、跨程序衝突與 GUI 不在場皆驗證 |
| M4b-2 | 啟動遷移狀態機、目的 staging／驗證／切換／recovery | 等 0 的可用 bridge 與 1a／1b；離線狀態機可先以 fake 開發 | 每個持久邊界 fault injection、冪等及禁止財務 rollback 全通過 |
| M4b-3a | 設定頁／復原進度／具體 ErrorText、composition 接線 | fake view-model 可與 2 並行 | 可取消、具體錯誤、停止新倉、兩模式兩尺寸原生視窗 |
| M4b-3b | installer／M4a 相容版本與升降級驗證、保留資料 uninstall | 測試案例可與 2／3a 並行，實機整合等其完成 | Windows 真安裝／升級／失敗復原、無 user-data cleanup |
| M4b-4 | 整合、基準集中更新、最新 main、完整 CI／Claude review | 共用 strings／inventory／layer_map／fixtures 只在一條整合分支登記 | 所有 CI 綠、歷史保護不弱化、文件與限制一致，待審不自合併 |

各階段可獨立 PR，但尚未具備 bridge／完整驗證前不得啟用正常啟動遷移；
不以多條子分支各自重釘共用基準。每個實作 PR 追加行為契約、具體測試與未驗證項，
本設計不授權修改交易邏輯或 G3。

## 11. 風險、回復與待實作假設

| 風險 | 處理與回復 |
| --- | --- |
| 任意舊 exe 寫回來源造成兩條財務歷史 | bridge 是支援前提；pre-bridge 不支援；drift 時保留雙方、停止新 writer，不自動 merge／覆蓋 |
| 鎖不完整、外部 host 仍存活 | 同一 admission 協定＋每 root ownership；無法證明停止就不遷移，不強殺 |
| SQLite sidecars／多 DB 不同時點 | 所有 writer 停止後完整 raw snapshot，副本 recovery、API backup 與獨立邏輯驗證；不改原 source |
| 複製耗時、磁碟滿或斷電 | 先估完整容量、可取消複製、持久 journal；舊原件／完整備份保留；部分發布停止 recovery |
| 控制／憑證復原重置預算或身分 | 固定原位置；不可逆記錄不 rollback；ciphertext 備份限制權限；不重建 alias key |
| 自選 workspace／外部 profile 路徑與 hash | 不搬 R，不改外部 profile；受管理 root 明確映射；未知／衝突不猜測 |
| 新設定整份覆寫造成遺失 | 同 repository、writer lock、revision／namespace 更新；未知鍵與來源證據保留 |
| 升級成功但遷移失敗 | 新版顯示停止中的復原畫面，保留資料；installer 成功不代表資料遷移成功 |

假設與未完成項：目前只承諾同一 Windows 使用者、同一台電腦的本機磁碟遷移；
不新增跨機憑證攜帶、network workspace 或雲端同步。
DPAPI 原權限與身分限制依 [Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)，
不把複製 ciphertext 當成跨機可解密保證。
bridge 的實際 release 號、所有已發布 reader 的拒絕矩陣、完整欄位 fixture 與 Windows
斷電／安裝證據留在對應實作階段完成；來源 schema 盤點若發現未列檔案，以完整保留／停止為準，
不擅自縮減財務日誌集合。

本次自主決策全部記於第 1、3、5、7 節：保留研究 root、固定不可逆資料、單一設定持久化邊界、
mandatory bridge 與 pre-bridge 降級限制。可見 ChatGPT 複核因 `existing_tab_not_found`
在提交前停止，未傳送內容；設計由 GitNexus 導航、main 原始碼盤點與並行審閱交叉確認。

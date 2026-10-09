# mark-auto 程式品質與交易風險審查

本文件區分已確認的原始碼缺陷、可能風險與尚未驗證的部署條件。優先處理會讓研究誤用交易權限、造成錯誤回測結論或容許未授權控制的路徑，再建立確定性測試。基線不具備可證明安全的無人值守条件。

## 1 範圍 方法與限制

查核日期為 2026-10-09 UTC；所有程式證據固定於 `1cacce4ee4eef4ce7e8760f8153ef64a74852d22`。當前安全修補與 `quantlab/` 屬後續開發，不改變歷史缺陷事實。修復是否成立以 [ACCEPTANCE.json](../agent/ACCEPTANCE.json) 的測試證據及變更 diff 為準，本文件不預先宣稱修復完成。

已執行的查核：完整檔案樹／blob 核對、38 個 Python 檔 AST 解析、相對匯入解析、重要控制流、依賴及設定檔盤點、完整可取得 Git 歷史文字掃描。未執行：產品匯入／啟動、套件安裝、broker／DB／通知登入、真實行情下載、憑證有效性測試、真實交易、依賴漏洞解算或滲透測試。

嚴重度定義：

| 等級 | 本文件判準 |
|---|---|
| Critical | 已證實可跨權限造成重大帳戶損害、任意程式執行並接觸秘密，或等同危害；本次沒有足以宣布已遭利用的證據 |
| High | 高後果的明確程式路徑，或會使交易／回測核心結論失真；部署可利用性可仍待核實 |
| Medium | 有條件可利用、可靠性／可維護性明顯缺口，需前置條件或限制範圍 |
| Low | 局部風格、警告與流程改善，不直接造成核心損害 |

優先度 P0／P1／P2 是修復先後，不等於嚴重度。關閉危險功能是一種暫時處置，不能等同整個舊交易平台已安全。

## 2 已確認的原始程式風格與品質

### 2.1 可保留慣例

- 模組責任已有基本切分，帳戶、訂單、部位、行情與圖表各有專屬檔案，便於隔離抽取。問題主要在相依方向及共享狀態，而非必須全盤換語言。
- `runtime.py` 使用 `Path`、部分型別註解與暫存檔替換，有照顧 Windows 檔案鎖定造成的 `PermissionError`。見 [檔案存取與重試](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/runtime.py#L24-L64)。
- GUI 啟動程序採參數 list 形式，靜態未發現 `shell=True`、`os.system` 或直接內建 `eval`／`exec`。見 [Popen 呼叫](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L100-L123)。這只是縮小特定攻擊面，不代表整個動態策略系統安全。

### 2.2 已確認技術債

| 面向 | 實際觀察與原始證據 | 影響與處理 |
|---|---|---|
| 命名及型別一致性 | 同檔混用 `check_can_stock`、`mapFunction`、`mapQuantities`；[命名樣本](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/strategy.py#L21-L45) | 新核心使用 snake_case 與完整邊界型別；不為風格全面重命名舊 API |
| 單一責任 | executor 同時組合 broker、DB、策略、模擬、通知、控制；[協調器](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/executor.py#L40-L65) | 抽出研究與執行 ports，而不是新增更多共享旗標 |
| 全域狀態 | `TradeData` 的帳戶、證券、期貨、報價及 KBars 共用；[狀態容器](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/objects/data.py#L9-L98) | 平行 trials 可能相互污染；改用每 run 獨立不可變輸入與帳本 |
| 隱含副作用 | 套件匯入建立目錄、API、資料庫與 table；[目錄](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/__init__.py#L16-L26)、[DB 初始化](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/__init__.py#L25-L42) | 不能安全匯入測試；建構生命週期要明確 |
| 靜默 fallback | `_read_json` 對廣泛例外回傳預設；缺失／壞命令日期不視為過期；[讀檔錯誤](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/runtime.py#L33-L40)、[日期錯誤](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/runtime.py#L112-L124) | 壞資料與「沒有資料」被混同；新系統記錄 typed error 並失敗關閉 |
| 缺值語義 | `_get_value` 將 NaN 填 0、缺資料回 0；[策略取值](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/strategy.py#L74-L94) | 真實零值、尚未 warmup、行情缺漏混淆，可能生成錯誤訊號 |
| 時間測試性 | 全域 TODAY 與當天 naive timestamp；[假日載入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L54-L76)、[時段](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L159-L179) | 歷史回放依執行日改變；calendar 與 clock 必須顯式注入 |
| 多重責任與重複風險 | 訂單回報與庫存監控分散在 orders／positions／executor | 目前未量測 clone density，不宣稱某段一定冗餘；先統一狀態契約再決定刪除 |
| 無用程式判定 | 私有策略以動態 import 呼叫；[plugin 載入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L125-L150) | 靜態未引用不等於可刪；先保留，蒐集使用證據，不憑搜尋結果清除 |
| 語法與警告 | 38 檔 AST 通過，3 個 invalid-escape SyntaxWarning | 修正警告屬 Low；解析通過不等於 import／執行通過 |
| 測試與格式工具 | 全樹無測試設定、formatter／linter／型別工具設定；[測試忽略範圍](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/.gitignore#L133-L146) | 新增具版本工程慣例與測試追蹤；不假稱符合已不存在的標準 |

### 2.3 新核心工程慣例

以 [IMPLEMENTATION_CONTRACTS.md](../agent/IMPLEMENTATION_CONTRACTS.md) 固定型別與序列化契約。價格用 Decimal 點數並驗證 1 點 tick；金額用 Decimal TWD；口數拒絕 bool；時間為 aware UTC，另存交易日及 Asia/Taipei 規則。所有外部資料先驗證，未知欄位與缺少必要版本應拒絕。

Domain 層不匯入 UI、broker、DB driver 或外部模型 SDK。副作用由 adapter 負責，核心函數 deterministic；例外使用穩定類型與可診斷 reason code。新檔完整型別註解、清楚英文程式識別碼及繁體中文操作文件即可，不需要為了統一風格全面重排舊程式。

## 3 安全與正確性發現

| ID 等級 優先度 | 已確認事實與固定證據 | 後果與驗證限制 | 修復與驗收要求 |
|---|---|---|---|
| R01 High P0 | Shioaji 建構預設 simulation=False；`Mode='Simulation'` 與 `Simulate=False` 並存；[API 預設](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L14-L16)、[API 建立](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L79-L82)、[矛盾初值](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/objects/data.py#L9-L11) | 原匯入不是可靠離線邊界；未宣稱 bare import 本身會下單 | 研究完全不依賴 trader／shioaji；舊 live 路徑停用；缺少／未知模式一律拒絕 |
| R02 High P0 | Telegram 空白 whitelist 放行；[授權邏輯](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/bot.py#L168-L195)，可控制交易／口數；[控制功能](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/bot.py#L277-L438) | 配置 token 後可能被未授權訊息控制；沒有已被攻擊證據 | fail closed；stable user AND chat ID；空、缺、錯誤、未授權群組成員測試 |
| R03 High P0 | 全域 TLS 驗證覆寫；[HTTPS context](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/executor.py#L37-L37) | 受影響標準函式庫 HTTPS 可能接受攻擊者憑證；不推論所有 library 同受影響 | 移除覆寫；測試 source 無 bypass；以正常 trust store 修復憑證問題 |
| R04 High P0 | crawler 存在 verify=False；[HTTP 呼叫](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L350-L350)、[下載與解壓](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L610-L613) | 資料可能遭污染或耗盡資源；未實際證明任意 path traversal | 開啟 TLS、timeout／status／size／archive 白名單；MVP 先 local-only |
| R05 High P0 | SQL connection string 包含帳密並寫入 log；[DB URL](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L111-L111)、[log 與連線字串](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/sql.py#L23-L44) | 運行時 DB credentials 可能外洩；庫内沒發現實際紀錄 | 診斷去敏、synthetic secret regression；部署 log 由授權者另行審閱 |
| R06 High P1 | report 匯入不存在的 `.backtest`；[缺少模組](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/reports.py#L18-L18) | 無法把報告功能當完整回測；靜態缺失而非已執行例外 | 新建獨立 engine／report，不能用 placeholder 冒充回測通過 |
| R07 High P1 | actual 成本為 0，margin 僅 MX/TX，dropna 可丟 TMF；[成本與 margin](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L69-L81) | 淨利及報酬可能失真、TMF 記錄消失 | 明確 multiplier／fee／tax／slippage，ledger 對帳；禁止用當前 margin 套全歷史 |
| R08 High P1 | `iswin` 在空單損益反號前計算；[勝負判定順序](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L111-L116) | 空單勝率可能與最終 PnL 不一致 | 多空鏡像 golden；由配對帳本統一導出勝率 |
| R09 High P1 | calendar 限當年、缺檔 fallback 空假日、用 TODAY 判歷史；[假日](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L54-L76)、[時段判定](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/time.py#L224-L242) | 休市、夜盤歸屬、跨年及到期可能錯配 | 版本化 session records；覆蓋不足即拒絕；官方交易日及公告優先 |
| R10 Medium P1 | `night_only` 文義存在但僅 day_only 有過濾；[盤別條件](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/kbar.py#L433-L454)；另有盤中時間 skip 與註解相反；[時間 skip](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/time.py#L124-L126) | 盤別統計及樣本選取不可靠 | 日夜盤邊界 fixture、clock 注入與文字／行為一致性檢查 |
| R11 Medium P0 | Redis `pickle.loads` 與 `pandas.read_pickle`；[Redis](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/redis.py#L78-L93)、[本機 pickle](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/file.py#L61-L61) | 若輸入可被攻擊者改寫，可能程式執行；本次未提供惡意內容或復現 | 新研究禁止 pickle；限制 legacy 信任來源並規劃格式遷移 |
| R12 Medium P1 | API key／secret／憑證密碼為普通資料庫欄位；[欄位](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/tables.py#L15-L18)、[表單寫入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L304-L309)、[編輯寫入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L550-L555) | 畫面遮蔽不是加密；未知部署是否有反向代理認證 | GUI 暫限私有使用；secret store 與部署權限須另立授權驗收 |
| R13 Medium P1 | account normalization 可保留 `.`／`..`；[原始識別碼規則](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/runtime.py#L24-L28)；GUI 直接組日誌路徑；[路徑](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L92-L94) | 共享控制／檔案邊界不足；未嘗試越界寫入 | 嚴格 allowlist ID，拒絕 dot segment／separator，驗證輸出 root |
| R14 Medium P1 | sample 在類別定義呼叫 `Position()`；[範例](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/docs/script%20samples/strategy_sample.py#L102-L109)，建構需帳戶與策略；[必要參數](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/positions.py#L815-L821) | 範例不能原樣執行；資料亦為佔位路徑 | 替換為離線、可驗證範例；保持新老範例狀態區分 |
| R15 Medium P1 | 32 項直接依賴無完整 lock/hash；[依賴](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/requirements.txt#L1-L33)，無 CI／測試 | 供應鏈、環境重現與版本漂移風險；未執行漏洞掃描 | 隔離研究依賴；固定適用環境，SBOM／授權及漏洞掃描另驗收 |
| R16 Medium P1 | 共用狀態、動態 Python 策略、無實驗 provenance；[耦合](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/strategy.py#L6-L12)、[共享狀態](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/objects/data.py#L9-L98) | AI 不能安全直接生成可執行程式；trial 污染難追溯 | schema／AST 白名單、每 run 空間、版本及資源限制 |
| R17 Low P2 | 命名、型別、docstring、警告與 fallback 慣例不一 | 增加維護與審查成本，不等同每處皆漏洞 | 在新增及實際修改範圍漸進改善，禁止無目的大重排 |

R11 的條件若擴大為不受信任者可寫入、且交易程序持有秘密，嚴重度應上調；未調查部署前不直接宣告 Critical。R01–R05 先隔離或停用，避免開發時進入高風險路徑。

## 4 可取得歷史的秘密掃描

### 4.1 覆蓋範圍

- remote advertisement 與 refs 查核只有 `refs/heads/main`；HEAD 為 符號別名，未見其他 branch 或 tag。當時所有狀態 PR 清單為 0。
- 完整非 shallow clone，Git object 完整性檢查未回報錯誤。
- 掃描兩個可達 commit：目前基線及根 commit `eb462f9dcde9b7a446be8ed902eeb629f7f39f1a`。根 commit 無 parent。
- 48 個唯一可達 blob，共 425,164 bytes；HEAD 47 檔，額外歷史內容為較早 README。
- 使用 inert 文字／regex 檢查 private-key header、常見 token 格式、JWT、URL 帳密、字面 credential assignment、高 entropy 字串。沒有匯入產品或對任何服務試用候選值。

### 4.2 結果與處置

**未發現高可信度已提交憑證或私鑰。** 這是有範圍的靜態結果，不是「完全無秘密」保證。[第三方資料 URL 組成](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L283-L340)有一個低可信度短字面值，用於共享 CDN 路徑；其是否被供應商視為 access credential 尚不明。公開報告不重貼該值，也不因此要求輪替無關帳戶。

未找到追蹤中的 `.env`、私鑰、broker certificate、帳戶 database、`config.ini` 或 log。忽略規則可以降低新檔誤入版控，不能保護已追蹤或已外傳的檔案。

不涵蓋刪除／未公告／不可達遠端 object、fork、release artifact、issue comment、外部系統及未追蹤部署檔。兩個 commit 不足以證明最初完整開發歷史。若日後確認真憑證曝光，應由擁有者先撤銷／輪替並稽核使用紀錄，再討論歷史清理；只刪程式字串不會消除風險。

## 5 工程合規矩陣

此處「合規」指本專案工程慣例符合度，不是法遵認證。`符合` 有限定範圍；`部分` 有實作但不完整；`缺少` 是完整基線未找到；`BLOCKED` 需要外部或執行證據。沒有可引用檔案的缺失列明完整固定樹，不能編造行號。

| 控制／慣例 | 基線判定 | 固定證據 | 最小補強與驗收 |
|---|---|---|---|
| 原始碼可定位及語法解析 | 符合，僅靜態 | [固定完整樹](https://github.com/yostar77612/mark-auto/tree/1cacce4ee4eef4ce7e8760f8153ef64a74852d22)，47 檔／38 AST 通過 | 變更後重新解析及測試，不能沿用歷史結果 |
| License 與原作者標示 | 部分 | [Apache-2.0](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/LICENSE#L1-L15)、[著作權](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/LICENSE#L189-L189) | 保存通知與修改標示；完整上游來源仍待核對 |
| 無直接 shell 字串執行 | 符合，限本次掃描模式 | [list Popen](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L100-L123)；全 38 檔 AST／文字檢查 | 不擴大成所有動態程式皆安全 |
| 模組匯入純淨 | 缺少 | [副作用](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/__init__.py#L16-L26)、[DB 建立](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/__init__.py#L25-L42) | 新核心 import graph／拒網路／拒秘密測試 |
| 實盤失敗關閉 | 缺少 | [預設 live](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L14-L16)、[送單分支](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L843-L897) | 不可由單一 flag 啟用；LiveBroker 拒絕所有操作 |
| TLS 驗證 | 缺少 | [全域覆寫](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/executor.py#L37-L37)、[下載 bypass](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L610-L613) | 移除全部 bypass 並靜態回歸 |
| 操作身份驗證 | 部分 | [白名單失敗開放](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/bot.py#L168-L195) | stable numeric ID、空白拒絕、群組成員測試 |
| 日誌不包含秘密 | 缺少 | [connection log](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/sql.py#L23-L44) | central redactor、synthetic credentials 測試 |
| 不受信任輸入安全 | 部分 | [pickle](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/redis.py#L78-L93)、[下載](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L610-L613) | typed JSON／CSV、大小／欄位／輸出路徑檢查 |
| 型別與時間一致性 | 部分 | [型別與 naive 時間](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/runtime.py#L97-L124)、[全域日期](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L159-L179) | Decimal／aware UTC／交易日分離；邊界錯誤顯式化 |
| 訊號資料缺漏處理 | 缺少 | [缺值變零](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/strategy.py#L74-L94) | 缺值／warmup／真零值分開；不補造行情 |
| 成本後帳務可信 | 缺少 | [費用零與 margin](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L69-L81)、[空單勝率](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L111-L116) | 手算 golden、lot matching、費稅版本 |
| 不可變研究 provenance | 缺少 | [完整固定樹](https://github.com/yostar77612/mark-auto/tree/1cacce4ee4eef4ce7e8760f8153ef64a74852d22)，無 manifest／trial store | spec／data／engine／config hash 與全部嘗試 |
| 測試、CI、依賴鎖定 | 缺少 | [僅直接依賴](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/requirements.txt#L1-L33)、[測試忽略](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/.gitignore#L133-L146)；樹無 workflow | 測試可追蹤、最小權限 CI、fresh checkout |
| 第三方套件授權與漏洞清單 | BLOCKED | [需盤點的直接依賴](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/requirements.txt#L1-L33)；無 transitive lock／SBOM | 在選定環境建立精確版本清單、授權與漏洞報告 |
| 券商、資料授權與無人值守 | BLOCKED | [broker 登入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/accounts.py#L59-L78)；無新 broker 認證或持久故障驗收 | 正式文件、資格、授權、RPO／RTO 演練，另行核準 |

## 6 威脅模型與必要控制

| 信任邊界／資產 | 攻擊或故障情境 | 控制與保留證據 |
|---|---|---|
| 公開 repository／CI／產物 | 誤提交秘密、PR 執行外部程式偷取權限 | 全歷史範圍掃描、低權限 CI、外來 PR 無 secrets；公開 artifact 僅合成資料 |
| 下載檔案與資料匯入 | 巨檔、壓縮炸彈、惡意 pickle、錯欄位或污染行情 | MVP 拒 URL 自動抓取與 pickle；限制檔案／列數，驗證 schema、range、hash 與 calendar |
| 外部文件與模型輸出 | prompt injection 要求改門檻、執行 shell、看秘密或送單 | 外部文字僅資料；模型只輸出有限 DSL；確定性驗證器與最小權限阻擋能力擴張 |
| 研究候選至策略庫 | 用最佳回測結果悄悄改成本、split 或版本 | 鎖定接受標準、內容雜湊與 all-trial log；任何變動新增版本與重新驗收 |
| 訊號至執行 | 重複 intent、行情過期、超量或 margin 不足 | risk gate、唯一 client_order_id、account snapshot age、hard limits，拒絕原因記錄 |
| 送單至回報／重啟 | ACK timeout 但單已接受、部分成交、取消競速、漏回報 | 持久 intent／事件、UNKNOWN 停新單、查詢及三方對帳，不盲重送或補償下單 |
| 操作者控制平面 | 未授權 bot 成員或 UI 使用者改部位限制 | 身分與情境雙檢查、最小權限、變更稽核；策略無權修改交易權限 |

依據 [NIST SSDF 1.1](https://csrc.nist.gov/pubs/sp/800/218/final)、[NIST SP 800-218A](https://csrc.nist.gov/pubs/sp/800/218/a/final)作工程控制參考，不宣稱認證。Prompt injection 不可僅靠模型提示解決，應限制工具權限並驗證輸出，參考 [OWASP LLM01](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) 與 [LLM06](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)。

## 7 License 與供應鏈判斷

基線 LICENSE 為 Apache-2.0，包含既有著作權；再利用時需保留適用 license／notice、合理標示修改，不能把原始程式改稱全為新作。本次樹未見 NOTICE，不能因此推論上游從未有 NOTICE。[MDD 程式引用](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L211-L213)另指向外部演算法來源；完整來源及其適用授權仍需查證。

第三方依賴包括 Shioaji、pandas／NumPy、SQLAlchemy／MySQL／Redis、cryptography、HTTP／HTML、Telegram、Streamlit／Flask／Dash 與繪圖工具。多數直接版本固定，但 pytz 只有下限；沒有 transitive lock、source hash 與完整套件 license 清單。`urllib3` 有直接匯入卻依賴 requests 間接帶入，亦應明列或移除該耦合。

因此本次可確認 repository 自帶授權文件，**不能確認所有上游及第三方再散布條件已滿足**。交付可發布程式前，對實際選定的研究與 UI 環境輸出 SBOM，核對確切版本 license、保留所需通知，確認 broker SDK 及行情資料另有服務條款。Apache-2.0 不授予第三方市場資料重製權，也不提供券商帳戶操作權。依賴版本老舊是風險線索，未完成當前漏洞掃描前不列猜測 CVE。

## 8 優先修復及釋出阻擋條件

1. **P0 安全邊界：** 研究不匯入舊交易樹、live 固定停用、Telegram fail closed、TLS 修復、DB log 去敏、危險反序列化不進新核心。不能因架設了新 UI 就略過舊入口仍可啟動的風險。
2. **P1 正確性：** calendar／資料品質／TMF contract／cost／causal engine／lot ledger，用獨立 hand-calculated golden 驗收；修復 sample 與 tests ignore。
3. **P1 工程基礎：** 版本、固定接受標準、離線 test entry、CI、all-trial log、hash；研究與策略績效分開驗收。
4. **P2 可用性：** 可追溯 UI、錯誤訊息、恢復操作、效能基準，避免以圖表或漂亮 Sharpe 遮掩未驗證部分。

未解決的高後果執行路徑、失敗的因果／帳務 golden、無法追溯的資料、越權模型輸出或 UNKNOWN 仍放行新單，均是一票否決的釋出阻擋條件。分數再高也不補償安全失敗。實際模型、真實市場策略表現、券商認證及實盤仍保持獨立 readiness，不能由 Mock 或合成資料測試代替。


## 自主實作後複查（2026-10-09）

以下是原始基線分析之後的工程處置，不回寫或混淆上方固定 SHA 證據。新 `quantlab` 研究樹不匯入券商 SDK；舊交易入口、危險反序列化與舊 ZIP 路徑已封鎖。實際修復與測試證據分別在 `tests/test_legacy_security.py`、`tests/test_architecture.py`。新資料下載 `quantlab/downloads.py` 有官方 HTTPS 白名單、大小／CRC／路徑及壓縮比限制，快取保留內容 SHA，未完成品質驗證的資料不能標為正式排名可用。

最後審查另發現 provider 端點在 HTTP 呼叫前可能被記入 campaign：即使 transport 拒絕有帳密的 URL，研究初始化仍可能先保存它。已於 `quantlab/research.py:CompatibleProvider.__init__` 提早拒絕 userinfo、query、fragment、非法 port 與控制字元，錯誤不回顯 URL；`tests/test_research.py` 驗證拒絕發生在序列化與 budget 目錄建立前。這是防洩漏修復；未發現實際使用者憑證遭寫入。

本地最終產品提交 `e5e56bb` 的完整可達掃描包含 7 個提交、132 個不同 blob、1,360,512 bytes，非 shallow；未找到高可信度密鑰。比對命中為合成負向測試、cost_per_token 名稱誤報及既有 CDN 路徑常值（仍保留待核实風險，不顯示其值）。靜態樣式掃描不能保證不存在秘密，也未測試任何疑似憑證有效性。後續文件提交以增量檢查驗證。

全套本地與 fresh-checkout 各 177 項測試通過、無 skip，包含 5 個 UI AppTest；wheel／sdist 成功建置，wheel 不含 legacy trader。Windows／Linux 遠端 CI、整合 SHA 與最新進度以 `../agent/PROJECT_STATE.md` 為準，不能把此本地結果当成 Win10／Win11 桌面安裝驗證或長期實盤就緒。

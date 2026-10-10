# mark-auto 程式品質與交易風險審查

<!-- CURRENT_STATUS_START -->
## 當前交付摘要（2026-10-10 06:20 UTC）

- **實際下載仍是 0.2.1 unsigned preview**，release main `2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`；[已核驗的下載與 manifest](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1)。八項主要 assets／56 個來源輸入、EXE／kit SHA-256與ZIP CRC及該版postmerge均已通過。**0.2.2尚未發布**，README保持這個已驗證入口。
- **PR #5 已於05:59:46 UTC合併，但新版發布被postmerge失敗阻擋。** 目前main `94aca46777bd19619c9cbc0721a888173395243e`，tree `53c2a9930cf6fd05536fe2470af7d223d0535d6b`；狀態 `MERGED_POSTMERGE_FAIL_REPAIR`。不是Draft／未合併，也不能稱新版已交付。
- **PR階段的成功單獨保留：** head `06bcc3a` 的10個Quantlab必要jobs通過，每profile inventory 1016唯一案例＝796 core＋220 research，實際開始清單無遺漏或重複；每Windows Python profile 1002 PASS／14 skips。Server `38028085841` 全套1016項，1002 PASS／14 skips、811.530秒；native frozen history、synthetic WFO兩折22次、安裝／真0.2.1升級／中斷恢復／移除保存通過。60個source inputs與PR artifact hash／CRC已核驗，僅證明此PR artifact，不能取代postmerge Release校驗。
- **最新postmerge Quantlab `38029388781`：8/10 jobs PASS，兩個core失敗。** Win3.11 core796項＝785 PASS／10 skips／1 failure，465.966秒，原960-bar typed120000 Paper 30秒未完成；Win3.12 core796項＝784 PASS／10 skips／1 failure／1 error，472.222秒，同一Paper 30秒失敗，另 `GenericSmokeTerminalProcessTests` 的 `SystemExit` 子案例超過原40秒subprocess上限。Windows research各220項＝216 PASS／4 skips（3.11為611.210秒；3.12為624.649秒）；Linux3.11／3.12各1016項＝998 PASS／18 skips（382.055／305.411秒），UI1016項＝1003 PASS／13 skips、448.669秒；static／audits通過；**整體FAIL**。Win312 job `114146946655` 的原始log已保存。
- **postmerge Windows Server `38029388676`仍執行中。** 尚無最後結論，不挪用較早Server PASS，也不把PR candidate EXE當作已發布的0.2.2。release guard原碼及獨立審查已確認：同SHA push的非成功結論在gh release之前拒絕，PR同tree不能代替；candidate artifact仍可能上傳，這不等於Release。
- **下一步是有界診斷與原生重验，不加新功能。** 僅測試用途的 smoke timeout 診斷、可驗證子樹清理及去敏 artifact 保留已完成本地與獨立審查；本地診斷5項、原終態9項、分片9項、發布來源5項共28項通過，歷史／靜態掃描0 findings。這是可觀測性與測試清理修補，尚未證明原生40秒逾時的根因或修復。原Paper30秒、smoke40秒、process-death10秒及Quantlab每job15分鐘均不放寬；不删測試、不縮工作量、不改產品storage／FULL耐久，也未搬移TEMP或改變測試資料位置。後續test-only來源亦須綁新head驗證。
- **WFO／PF／Sharpe／參考快照／普通繁中UI已合併但未發布。** 真實Oct8 WFO仍 `BLOCKED_NO_RUN`：完整guard與既有consumed coverage重疊170 bars，0新評估／model calls／reservation；不改windows或另建registry規避。synthetic WFO不是adaptive AI、真實未見資料或正式排名／Paper資格證明。
- **固定驗收仍210/300＝70%，未接受90點。** 研究100、桌面70、市場40；M4保持PARTIAL／0分，postmerge失敗尚未解除，不採用先前有條件的加分建議。權重／分母／原門檻不變；分數不是工時、全需求、生產或投資認證。
- **外部／安全界線不變：** clean Win10 22H2 x64／Win11 x64 EXTERNAL_BLOCKED、實際ChatGPT grant／inference NOT_VERIFIED、TAIEX盤中自動使用權限未核实；main protected=false／管理API403、unsigned不繞過警告、真交易DISABLED。05:02觀測為一台desktop連線但未授權task、另一台offline，無saved coding environment；不能說沒有電腦連線。
- **歷史與分支已保留：** 遠端自動刪合併分支後只剩main；全歷史及merge已保存在已驗證的 `mark-auto-preserved-20261010-0602.bundle`。舊CI、timeout、fixture、Qt與I/O負結果保留，不因較早PR成功或分支清理改寫。

### 原需求、設計提案與未驗證項目

- **本輪已明確必要的原需求：** Walk-forward，以及使用者原文 §5.1 的 Profit Factor／Sharpe、§3.4 的停損／停利／持倉成本參考線；已合併及PR階段PASS不等於postmerge／已發布交付。
- **尚未採用的完整目標設計延伸：** 04 §9.1 提出的 Average Trade、Sortino、Calmar、延伸分解與成本壓力測試保留為提案。02 歷史原文已明示「若最終採用該完整規格」；未取得使用者直接要求這些延伸的原始證據，因此不把設計表的「必須公開的計算與例外」升格為本輪新增驗收門檻，也不刪除提案。
- **尚未驗證的結果：** postmerge修復／發布、clean client、真實授權與真實研究各依目前證據判定；未驗證不表示功能未實作，設計提案未採用也不等於本輪驗收失敗。

## 當前優先風險與最小閉合證據

| 順序 | 風險／目前判定 | 下一個必要證據與依賴 |
|---|---|---|
| P0-1 postmerge原生timeout | main94aca467：Win311原Paper30秒FAIL；Win312同Paper30秒FAIL與GenericSmokeTerminal SystemExit40秒ERROR | 測試診斷、子樹清理及artifact保留已本地通過，最後原生待驗；根因未定，不放寬30／40／10秒、不減fixture／工作量、不改storage／FULL／TEMP |
| P0-2 必要發布gates | Quantlab38029388781為8/10 PASS，兩core FAIL；兩research／Linux／UI／static／audits PASS。Server38029388676仍執行中 | 保留10個具名必需jobs、原OS／Python／完整覆蓋與Quantlab job15分鐘；失敗不能由PR歷史PASS抵銷，當前禁止0.2.2發布 |
| P0-3 證據與來源連續性 | PR06bcc3a所有10jobs及Server1016／安裝／真0.2.1升級通過；60inputs／artifact已核對。同tree的postmerge新失敗仍是真失敗 | 保存兩階段log及partial artifacts；新test-only patch需新head原生重驗；不將PR EXE digest填成尚未存在的Release digest |
| P1-1 普通操作 | expiry／typed Paper margin／TX-MXF分鐘入口與可讀表單已隨PR5合併main；仍非已下載0.2.1能力 | 修復發布否決後才核對實際Release；M2／M4均仍PARTIAL／0分，不提前採用條件式加分 |
| P1-2 必要研究與報表 | WFO／PF／Sharpe／參考快照／指南與普通UI已合併，PR完整1016與native/frozen通過 | postmerge整體失敗／Release未完成；fixed/saved pool不冒稱adaptive AI或真研究未見性 |
| P1-3 真實研究有效性 | Oct8 WFO 完整 guard 與已 consumed 170 bars 重疊，BLOCKED_NO_RUN；既有真模型負／零交易 | 不新增評估、不改 window／registry 規避；保留原完整 protocol／negative results。新的合格研究須另有合法且合規資料與預宣告；不得承諾獲利 |
| P2-1 外部 client／授權 | Win10／Win11 clean install/DPI、實際 ChatGPT grant／inference、TAIEX 盤中權限仍未成立 | 合法已授權環境與使用者官方流程／可核實來源權限；Server／synthetic／日線授權不能替代；禁止越權／警告繞過 |
| P2-2 發行信任／權限 | main protected=false／rulesets 空／管理 API 403；unsigned preview | 保留限制，只有適當權限與明確授權才變更；SHA-256 不當簽章。不得自行買簽章或擴 persistent access |
| 持續安全底線 | real money DISABLED；不消除未知請求、不重開研究／provider 預算；原門檻不降低 | 任一安全失敗獨立否決發布；不得用 70% 或舊 PASS 抵銷 |

### 05:32及以前的歷史檢查點（保留原失敗，不是最新狀態）

以下1–6為先前來源／當時狀態；最新PR成功與postmerge失敗以本頁06:16摘要為準。

1. 已發布仍為0.2.1／main2ed1e3e，EXE／kit／manifest已核驗；版本0.2.2與PR5不變，新head不等於已交付。
2. 新remote12e088f／local2021cd7為同tree。Quantlab38026398885：Linux3111000項982PASS18skip／372.491秒，Linux312982PASS18skip／368.935秒，UI987PASS13skip／411.012秒；audit／static PASS。Windows311／312兩個15分鐘job CANCELLED，即使兩者原Paper30秒單項PASS，也不記整體PASS。
3. Server38026398890：1000項／918.891秒，4failures、2errors、14skips，包含原Paper30秒FAIL；build在新EXE前停止。六類失敗按上表保留，沒有用Linux結果覆蓋原生失敗。
4. 原生connection artifact（SHA-256前綴54cc9098）：10完整cases、FULL／NORMAL、每profile240commits，30children全部joined。每120commit的C DELETE reopen5.153／4.017秒、DELETE step4.439／3.929秒、PERSIST step5.764／5.902秒，D DELETE0.112／0.105秒。這支持I/O環境敏感度，不支持改產品storage、TEMP移動或宣告效能修好。
5. 05:32修補檢查：UI test-only57 focused＋25 independent PASS；WFO兩檔33 PASS／36.641秒；arity18 PASS／2.781秒；混合root85項84PASS1PowerShellskip／11.791秒。CI五檔partition獨立14 PASS，discovery1016唯一＝796core＋220research且精確無重疊；不是完整執行。後續native仍待，所有局部計數不相加。
6. 較早root773、候選981、root97／145及各native head都依原來源保留。981候選是在25檔精確複製前執行，不改稱root最終全套；本次1000項CI也不認證它之後的本地修補。Oct8實際WFO仍BLOCKED_NO_RUN，無新評估／模型呼叫。

歷史驗證位置補註：較早981項在隔離候選執行，25檔按manifest複製；不是最後root全套。12e088f的1000項失敗／cancelled與05:32局部18／33／85項屬先前checkpoint；其後06bcc3a的完整PR1016已通過，但94aca467 postmerge又出現上列兩種timeout。所有來源、平台及計數分開，不相加或追溯改寫。

診斷接續分支為 `agent/windows-release-validation`，從已合併 `94aca467` 建立；舊已合併分支及原始提交保留。新的5項診斷案例使完整 discovery 為1021＝801 core＋220 research；discovery 不是全套測試通過。Windows Job Object 真實巢狀案例必須由原生CI驗證；mock的拒絕授權案例只驗證失敗關閉。沒有修改產品程式或SQLite儲存模式。

<!-- CURRENT_STATUS_END -->

## 歷史原文與逐次證據（依原記錄保留）

以下完整保留本次整理前的內容、要求、來源、失敗與各時點判定。內文即使寫「目前／最新」，也只屬原有日期快照；現在的交付與下一步以本檔最上方有日期的摘要為準。原始基線盤點、固定驗收條款與年代順序均未被當成新版本成功證據。


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


## 桌面整合風險與已執行修復

- 中斷還原與安全凍結競態：舊資料移到rollback後若先重建state再恢復，會危及原資料。現實作先join/cancel寫入程序，再恢復，最後才能寫安全狀態。刪除rollback必須有相符的durable commit identity與promoted token；模糊狀態隔離保存，不猜測成功。測試注入兩次rename之間中止、未退出worker與journal清理中斷。
- 研究控制狀態回退：支出預留與已見holdout原先在可還原state內。現移到固定bootstrap/control-v1，舊備份／同bootstrap切換工作區不會重開預算或已消耗保留集。舊in-state控制帳本存在時阻擋新研究，不自行刪除或假定新帳本。這不是對使用者任意複製至另一台電腦的全域防作弊或帳單保證。
- 候選資格資料被單獨修改：JSON結果須與唯讀SQLite authoritative state一致，並核對selection hash、策略與資料綁定；未合格的OOS／holdout不能在桌面啟用Paper。無法防禦同一OS帳號惡意改寫全部檔案，這個信任邊界須保留。
- 凍結版來源完整性：six engine sources明確列入PyInstaller資料，安装後與source SHA逐檔核對。只有demo啟動不足；smoke必須完成真正凍結版backtest、bounded fixture campaign及paper流程。
- Windows資源與輸入：終端錯誤訊息與子程序退出同步，失敗不被清理誤標成使用者取消；固定bootstrap lock和命名mutex避免切換工作區重複啟動；DPAPI、Job Object取消／父程序當機及junction拒絕以Windows integration tests驗證。
- 供應鏈：桌面使用官方有Windows二進位安全更新的CPython3.13.16，取代3.12.10；版本／SHA／官網來源在 `packaging/python-runtime.json`。Qt6.12是Win10支援線，不能盲升不支援Win10版本。安裝器未簽章，不绕過Windows警告。

本地fresh checkout `8bc19e1`：258 tests，共253 PASS與5個Windows限定項未在Linux執行；兩套UI測試均實際執行。遠端同tree為 `d0665e1417a6c31d0978e93a9bf2d2194eba913d`，Windows最終結果須獨立讀CI。Linux Qt可見視窗＋worker smoke單次0.932秒、子程序最高RSS83,908KiB；不是Windows首屏或效能SLO。先前1000bar回測中位0.522秒屬合成基準，不作市場資料吞吐保證。

上述桌面處置的可定位證據：`quantlab/desktop_runtime.py`（`JobManager`、`WorkspaceLocator`、`DesktopCredentialReference`、backup/restore 與 recovery）、`desktop_ui.py`（`_quiesce_and_recover`、候選啟用與設定事件）、`tests/test_desktop_runtime.py`、`tests/test_desktop_ui.py`、`packaging/markauto.spec`、`packaging/test_installer.ps1`。Windows CI 尚未全通過時，這些是已實作／部分驗證，不是所有平台驗收完成。

### 當前符合度與殘餘風險

| 分類 | 當前狀態 | 證據與限制 |
|---|---|---|
| 核心因果、帳務與 Golden Cases | 工程 Gate 已符合 | `tests/test_backtest.py`、`tests/test_strategies.py`；市場參數與資料涵蓋另驗 |
| 模型任意程式執行與券商隔離 | 已符合目前受限研究架構 | `quantlab/strategies.py`、`provider.py`、`tests/test_architecture.py`；不執行模型 Python |
| 研究洩漏、預算與版本 | 工程控制已建立；桌面部分驗證 | `research.py`、`desktop_runtime.py`、相對應 tests；真模型／正式資料未驗證 |
| 桌面安全恢復、DPAPI、單例 | 已實作；Windows 最終 Gate 尚待修復重驗 | runtime／UI tests；不得以 Linux skip 當 PASS |
| 自動品質／憑證／依賴 Gate | 已建立並實際執行 | `.github/workflows/quantlab.yml`、`windows-desktop.yml`、`tools/quality_gate.py` |
| main 強制保護 | 缺失且管理權限阻塞 | GitHub metadata `protected=false`、rulesets 空、protection API 403；流程自律不等於服務端防護 |
| 乾淨 Win10／Win11 驗收 | 缺失，外部環境阻塞 | D7／D8 BLOCKED；Windows Server 不可替代 |
| 正式即時交易、券商認證與長期無人值守 | 缺失／未驗證 | `LiveBroker` 停用、Paper 歷史批次；須獨立資格與實際故障演練 |
| 長期資料與正式策略排名 | 部分符合 | 官方下載與品質框架存在；30 個 ZIP 不能證明完整歷史或有效樣本外 |

立即優先處理所有實際失敗的安全／恢復 Gate；其後才可發布預覽。正式交付仍受 clean client OS、資料與外部連線驗收限制。無證據的憑證「未外洩」、長期穩定性或交易績效結論一律不得宣稱。

### Windows 工程驗證結果（17:21 UTC 更新）

來源 `3246cdc`／遠端 `b62803a` 已通過 [Quantlab 七 jobs](https://github.com/yostar77612/mark-auto/actions/runs/37964547136) 及 [Windows installer build／安全 Gate](https://github.com/yostar77612/mark-auto/actions/runs/37964547102)。Windows Server2022 Python3.13.16 完整 suite 263 tests：256 PASS、7項 Linux／選用 Streamlit 未執行，其適用情境由 Linux jobs 覆蓋；DPAPI、JobObject、mutex、junction、真 PowerShell parser 均實際執行。WinError109正常 EOF 誤分類及短路徑已修正，不再阻擋此來源整合。

安裝測試通過 frozen 七步研究／Paper、程式來源 hashes、捷徑、正常視窗、升級、拒绝正在執行時更新／移除、正常關閉及解除安裝後資料保留。此處升級fixture使用同payload的0.0.0→0.1.1，**不是歷史資料 schema migration 證明**。移除PATH工具不是乾淨機；D5、D7、D8仍 BLOCKED。驗證產物包含OS／版本／執行結果與單次效能觀察，不作client OS或長期無人值守承諾。

## 0.1.2 接續驗收與新發現（2026-10-09）

此節優先於前文歷史快照，並保留缺陷原始事實。0.1.1已交付的是unsigned preview，不代表安全與產品驗收結束。

| 風險／原本缺口 | 本輪處置與證據 | 驗收界線 |
|---|---|---|
| High：備份目的地可覆寫control-v1帳本／bootstrap指標 | `BackupManager.create`在任何恢復/寫入前拒絕active workspace及固定bootstrap內目的地；`test_desktop_runtime.py`覆蓋所有sentinels及搬移工作區 | 外部備份成功且內部資料保持；Windows整合仍須重跑 |
| High：Paper衝突duplicate、截斷fill或SQLite恢復後仍可能送新單 | `paper.py`持久quarantine及同程序storage-uncertainty latch；`test_paper.py`／`test_paper_replay.py`新增12案例，61focused tests | timeout模擬、實際SQLiterollback／程序當機，不是假稱真券商重連 |
| High：official/proxy資料缺盤首／盘尾／整盤仍可匯入 | `data.py`共用_dataset完整calendar coverage，新增5回歸；synthetic短fixture保留明示warning | 真Oct7缺03:29–03:30被拒絕，不能補造bar |
| High：overlay更新殘留舊DLL／中斷混合runtime | `markauto.iss`每次全新payload、編譯綁定inventory與全部檔案hash後才啟用捷徑；`test_update_recovery.ps1`實際kill安裝程序驗收 | Windows實跑前不計PASS；保留旧payload會占磁碟，不任意刪使用者檔案 |
| Medium：發布來源可不是main、任意單job成功可混充完整Gate | `wait_for_gates.py`檢查main ancestry及7個必要named jobs，全數成功才發布；`test_release_provenance.py`負向測試 | 不等於main服務端保護已啟用 |
| Medium：真小模型不理解未提供的DSL／自由JSON不可靠 | `research.py`明示schema/train-only context，新增可選registry_json_schema；desktop設定持久化且預設budget identity不變 | 前6calls失敗保留，structured3calls有效；無默默fallback，不宣稱任意AST可靠 |

### 真實整合結果

免費官方Qwen1.5B的3個受限家族參數候選，經原生provider/HTTP→train/validation→固定選擇→OOS/holdout→多策略比較完成。這是實際推論，不是mock。Trend的OOS為-33,820、holdout為-49,546 TWD；另兩候選各split零交易，不能視為最佳獲利策略。資料僅12日，費用/保證金屬明示假設，沒有經濟／實盤資格。資料、模型、runtime與請求回應的hash及全部失敗紀錄保留供重現；原始行情不發布至Git。

官方12日資料為2026-09-17至10-06同一TMF202610契約，13,680根分鐘K、24盤OHLC符合另一官方日行情；2026-10-07缺1分鐘，拒絕而不判定一定是資料故障（也可能無成交，無證據不能補bar）。免費2025年度日行情涵蓋243交易日，但不能轉稱分鐘級歷史。到期日依[官方年度calendar](https://www.taifex.com.tw/file/taifex/CHINESE/4/2026Calendar.pdf)與[TMF規格](https://www.taifex.com.tw/cht/2/tMF)核驗為已公布10/21台北13:30；後續正式公告可再變更。

### Windows／簽章／權限的實際限制

[Windows11 Enterprise](https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise)有90日評估管道，涉及註冊、既定授權條件及可用VM；不是永久免費授權。Win10舊evaluation URL目前導向終止支援資訊；[ISO媒體](https://www.microsoft.com/en-us/software-download/windows10ISO)存在不等於新VM已有免費授權。未下載非官方OS、接受新協議、繞過啟用或使用付費試用。現有Linux無KVM且無授權clean client；無法以Server／ARM／PATH隱藏工具冒充Win10/11 x64。

EXE仍unsigned；ASLR/DEP靜態存在不等於通過全面安全檢測。[SignPath Foundation](https://signpath.org/terms.html)免費簽章有OSS資格、MFA、角色/政策與人工批准要求，尚未核准；Store的免費簽章針對其MSIX管道，不會自動簽既有EXE。[SmartScreen](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)亦可能警告已簽章的新檔，不建議繞過保護。沒有購買或建立簽章憑證。

main仍protected=false、rulesets空，管理級API403。Code/PR/Actions正常，不代表具管理授權。此限制維持EXTERNAL BLOCKED；未申請擴權或假裝保護啟用。

### 真模型改善迴路補驗

另以獨立明示 synthetic 512 bars 驗證一次初始生成＋一次改善，未重用真實OOS/holdout。第二次真HTTP請求包含先前train/validation回饋、改善指令與parent/iteration；模型只將trend_0改名trend_1，fast=2/slow=4未變。正規化語意指紋忽略名稱、等價數值及default lag/quantity，成功拒絕重複而保留raw/call/父鏈，沒有重跑回測。工程feedback/去重PASS；有效不同改善候選FAILED，績效改善不成立，不能寫成外部授權阻塞。累計11次真推論已停止；研究40、provider8、真AI工具9 focused tests通過。

## 新增市場/UI範圍的實作前安全界線

舊trader行情工具有全域交易初始化，不能直接解除封鎖或匯入桌面；新增僅讀市場型別與TMF交易資料分開。TX/MXF/index行情展示不等於其回測或下單引擎通過。官方小台每日原碼MTX與UI MXF需明示映射；價格前收與前结算不可混用（實際10/8 TX前收差-630、官方前結算差-619）。日資料日期不代表精確成交時間，缺OHLC不得由成交量猜補，公開歷史不得冒充即時。

OpenAI現在有[官方OSS/本機Sign in with ChatGPT計畫用量](https://developers.openai.com/siwc/token-sharing-open-source)途徑，並非一般API免費額度。需要本應用自己的使用者授權、PKCE/OIDC驗證與安全儲存，不能拷貝其他工具token。HTTP Responses/SSE與既有chat-completions協定不同；不支持max_output_tokens時，客戶端截流/逾時不能聲稱限制伺服器token消耗，須独立透明用量政策。實際登入/授權與帳戶可用性尚未驗證；付費API與額外credit不自動啟用。

### 0.1.2 Windows實測與正式保留證據（2026-10-10 00:38 UTC）

PR#2已合併28c9f902，最後head9008522完整tree6338b6ef9828892e53fbf1a543ada0ec9bd8f154與本地ccb74d2等價；Quantlab7jobs38008659312、Windowsbuild/security38008659297全PASS。Windows測到原inventory排序隨OS不同及NTFS ADS未被rglob看見，已修productioncode固定排序並列舉拒絕ADS；失敗測試沒有刪除/跳過/降門檻。341測試334PASS、7適用其他環境/選用工具skip。

合併後38009150044在WindowsServer2022build20348完成真0.1.1→0.1.2、安裝程序實際kill、舊runtime恢復、新payload驗證啟用、保留927個原檔及5資料sentinels、實際schema1設定位元不變，並完成同版本重裝修復split-shortcut。這是單一程序當機點，非完整斷電耐久證明；compatible設定保留不是跨schema migration。原生命週期10checks也PASS。單次啟動1.033秒、working set77,676,544bytes，不是Win10/11SLO。

[Release與驗收工具包](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38009150044-1)已實際下載：EXE36,695,486bytes、SHA256 0f92f70fb17bc3f0c2c816cbb5f963ecb2de6dde40745759f415a4755e85c469；kit72,324,965bytes、SHA256317f98560ae1c29ee4d7c99e81ed2d8bab55d010114f765b756cdcd9ae076079，ZIPCRC通過。Win10/11clean、main管理權限與簽章限制未因此解除。

### 0.2.0 市場模組架構 Gate 修復（2026-10-10 00:46 UTC）

靜態Gate發現3個Qt檔案放在quantlab研究樹，違反既有stdlib-only邊界；沒有放寬研究規則。已將desktop_charts.py、desktop_forms.py、desktop_market.py移至既有desktop_ui.py旁，UI向quantlab資料/策略依賴，核心不依賴Qt；同時把既有desktop禁止券商/dynamic-execution掃描延伸到全部4個UI檔，新增負向回歸。證據：tools/quality_gate.py、tests/test_quality_gate.py。可選Qt測試遵循原矩陣分層，在有完整桌面依賴的Windows job必須執行；minimalstdlib job明示skip，不能算桌面PASS。

最新報價卡與歷史圖表分離；只持有較新已驗證分鐘history時可以顯示卡，但不升格為即時。日期/盤別無法排序時不虛構日行情時間。證據：desktop_ui.py與tests/test_desktop_market_integration.py。官方直連DNS失敗保留BLOCKED；本地匯入標history/source-unverified，不能以URL字串證明來源真實性。

CI run38010756018揭露deadline測試fixture競態：30ms計時包含SSL初始化，慢runner在fake connect前合法逾時。未放寬產品30s限制或測試0.5s關閉門檻；僅隔離handler時計，仍以真30ms threading.Timer驗證shutdown，新增已逾時不連線案例。23focused、200重複及10次故意60ms SSL初始化均通過；原失敗保留，下一head重新驗收。desktop.py另把原7步frozen smoke保留，再增加獨立synthetic market_smoke（真Qt非空圖表/週期/指標/typedforms、manual export/import worker與來源hash），任一失敗阻擋overall。這是打包工程測試，不是行情/AI實測替代。

同次Windows CI另發現payload path驗收把原字串和GetFullPath結果要求完全相同，可能誤拒TEMP含8.3別名的合法路徑。改為canonical target/trusted root比對，同時明確拒絕relative/drive-relative/UNC、dot traversal、ADS；原精確layout/reparse門檻保留，動態測試增加ShortPath。來源packaging/test_update_recovery.ps1、tests/test_update_recovery.py；Windows需重驗，Linux skip不作成功。新市場/原7步整合source smoke及其完整Linux suite459項451PASS8skip（72.056s）；另最新recovery focused10PASS1Windows skip。原失敗CI不能被這些本地結果抹除。

第二輪 e066693 的Quantlab七jobs全部PASS，Windows build及frozen市場/原7步、安裝生命週期通過，官方日行情實際HTTP下載診斷VERIFIED。接續歷史版本恢復驗收正確阻擋了前一輪正常關閉留下的設定：新UI會保存市場/視窗偏好，而uninstall保留資料。處置不刪設定或降低hash驗收：lifecycle明示opt-in且啟動前證明設定/工作區指標不存在，完成後寫create-only ownership receipt；recovery驗version/path/hash後將已知test-owned設定搬至唯一保留副本，未知資料仍拒絕。--smoke-test另採載入已驗證真設定後的記憶體view，僅自動化測試不回寫偏好；正常GUI持久化不變。來源desktop.py、tests/test_desktop_market_smoke.py、兩支installer/recovery harness與對應tests。失敗診斷artifacts改always保留，但release依賴必要Gate不變。最新Windows重驗前仍BLOCKED。build manifest涵蓋全部desktop*.py，包含新chart/form/dashboard來源。

## 0.2.1 官方訂閱整合安全驗收（實作中）

官方授權與Responses SDK邊界置於root desktop_chatgpt_auth.py／desktop_chatgpt_provider.py／desktop_chatgpt_ui.py；quantlab仍僅stdlib，唯一既有runtime→desktop_ui橋接維持。新增檔案納入原禁止券商匯入/動態程式執行Gate。沒有實際OAuth授權或訂閱推論，所有fixture僅為工程測試。

重點威脅與驗證位置：
- 授權callback重播、錯host/state/nonce/audience/issuer、JWKS不明key、RS256演算法混淆：auth模組及test_chatgpt_auth.py；使用PyJWT驗簽而非自製密碼學。
- 明文凭證、跨使用者檔案、junction/鎖/refresh中斷：DPAPI vault、private DACL與tests/test_chatgpt_windows.py，只有實際Windows測試通過才可列native PASS；Linux skip不計。
- 跨研究/模型/工作區重置支出或未知請求重送：固定bootstrap control帳本、先預留/不退還、帳戶暫停及嚴格完整receipt。獨立審查曾實際重現「global DB遺失後新研究可重建」和「campaign DB遺失被當空receipt」；已列release-blocking待修復，不得以一般SQLite交易成功忽略資料遺失情境。
- 父程序被取消但子孫仍推論：desktop_runtime整個process group／Windows Job active count，以及same-manager停止證明/不可變launch snapshot。terminal IPC packet不等於已退出，未知狀態禁止新操作；tests/test_desktop_chatgpt_integration.py含忽略TERM子孫反例。
- 不可信新provider稽核資料：research.py限制descriptor深度/大小與receipt欄位、sequence、status、hash，未知結果在下一trial/selection/holdout前阻擋；outer中斷只進行本機exclusive-lock對帳，保存既有attempt/holdout，不重新產生任何結果。

四個desktop-only依賴固定PyJWT2.15.1、cryptography50.0.2、cffi2.1.1、pycparser3.11，wheel digest與雙平台manifest保存。native attribution以已獨立審閱的固定ZIP交付，不解壓不可信archive至產品路徑。archive完整SHA256 cbf2c6123cd25e53b33e766fb27bea9c9b4d8d174deb5ae54519d07f62dc9b24，含93個hash驗證檔與manifest；5個來源archive403仍如實記錄，必要notice以官方immutable Git物件補證，不宣稱archive全部下載。詳細inventory在packaging/third_party及發行licenses ZIP。這是工程授權清單，不是法律保證。

完整桌面smoke另呼叫offline auth_smoke：新鮮synthetic RSA key、真native OpenSSL/CFFI/parser、實際IdentityValidator、錯nonce/audience與algorithm rejection；socket/DNS當場阻擋並恢復，沒有寫入真vault或授權。real_oauth_status及real_model_status保持not_verified。Windows frozen與實際帳戶需各自證據。

01:28 UTC補驗：上述missing-control release blocker已在staging修復，原failed repro保留。bootstrap建立create-only/fsync marker（不隨workspace/backup回退）；marker、global DB、schema或已登記campaign ledger任一遺失／部分初始化／count回退即阻擋，不能當新帳本重建。global plan_ledgers index與預留在同一attached transaction更新；snapshot以單次read-only attached transaction驗binding/count/rows，不再RW/create重讀。獨立76項offline組合與原刪檔反例通過；這不保證使用者惡意同時刪除所有bootstrap痕跡或真斷電耐久。tests/test_chatgpt_plan.py、test_chatgpt_research.py為對應可重現案例，正式exact-head/Windows Gate仍待。

固定驗收另發現兩個UI接線缺口：MACD histogram數值為1倍但實際圖例未揭露倍數；PaperActionForm雖有risk說明但未實例化到主畫面。0.2.1用實際圖例與同一RiskLimits factory產生唯讀風控摘要修正，不新增無效可編輯參數，也不改實際風控門檻。tests/test_desktop_market_acceptance.py直接檢查MainWindow與非零histogram，避免只測未使用元件。

### 0.2.0 合併後正式產物核對（01:39 UTC）

mainfc2dfac，postmerge Windows38013204925 build/security/release及Quantlab38013204921通過；[0.2.0 Release](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38013204925-1)實際下載校验：EXE36,848,324bytes／SHA256be1c749e9fc83ede8c9a0e18d9be99a3c7e3104b4798dda6ccb1834f29471f29；kit72,511,372bytes／SHA2566aef9b3fe5a81913528fee9436a98c4e85edd3fa46a69f5e78a2f4dd058be3f3，ZIP8entries CRC PASS。build-manifest6,539bytes／SHA2567cf66be9406b842949cdf5501c2c28915a6baad532a46dcd4d911e818174e33d绑定fc2dfac。復原報告保留928舊檔/5資料sentinels/原設定，lifecycle設定另保留hash副本未刪。官方HTTP證據TAIEX6bars、TAIFEX19series38bars，皆EOD，非即時。

下一版baseline改固定為以上真0.2.0；初次633測試只有舊baseline測試仍期待0.1.2的metadata失敗，故依已實際下載的新版commit/size/digest更新固定fixture，並加強manifest與完整EXE digest斷言。品質門檻、未知檔保留及內容驗證沒有放寬，失敗紀錄保留；CI仍須在最終head重跑完整矩陣。

0.2.1首輪Windows CI（38014286480／38014286482）保留FAILED證據，未合併。四個根因分開處理：六個測試fixture用了SQLite connection context但未close，導致Windows刪除temporary時WinError32；改為closing＋原transaction，另保留connection物件測production成功/錯誤路徑明確close，沒有用GC/延遲/忽略cleanup掩蓋。DACL測試把SDDL縮寫LA直接和full SID文字比較；改讀原binaryACE並EqualSid，同時仍要求protected、單一allowACE、full access，另加異主體/異domain RID500反例，不允許泛用LA例外。deadline合成測試原只patch POSIX killpg，現分別測Linux killpg與Windows terminate分支，保留join/close/unknown-error全部斷言；native JobObject測試獨立。唯一production修正是build-manifest輸入路徑統一POSIX字元，原Windows反斜線key令跨平台雜湊查核失敗；既有kit/PowerShell讀取兼容兩種格式。92focused tests85PASS7native/tool skip，原完整633Linux結果保留，最終headWindows必須重驗。


0.2.1第二輪exact-head `7dc3536f`／本地`797f3cd`，Quantlab `38014802083`七jobs與Windows `38014802079` build/security全部通過：635測試624PASS11適用profile skip，原生DPAPI/DACL/refresh-lock、frozen crypto、安裝/升級/中斷復原Gate通過。這是Windows Server runner，非clean Win10/11。release因PR不是main正常skipped。

合併前新增offline反例實際重現release-blocking缺口：同bootstrap但不同OAuth registration，A預留未知請求後B仍status ready且能預留。來源 `desktop_chatgpt_provider.py` registration-keyed account lookup；不能假定issuer/client/subject跨registration必然代表相同人，也不能因此允許重試不確定呼叫。PR4保持未合併，修復方向為本安裝跨registration的active/unknown/paused屏障及既有ledger完整性確認，保留各自receipt/身分。新增反例與並行/明確解除已知pause驗收先固定，修復後重新跑exact-head Gate。沒有真正授權、token或網路推論。

獨立反例再確認兩個同源缺口：A已完成但其預期ledger遺失／毀損／回退時，B仍可當ready；較晚返回的model catalog已知quota錯誤能覆蓋先前未知推論狀態，使人工解除pause後誤允許新call。另standalone模型發現原未保存新觀察到的quota/auth pause。修復保持最小同一provider邊界：以全域交易內有界索引驗全部已登記ledger、receipt推導不可清除未知屏障、已知錯誤不得降低未知狀態、共用已知pause持久化。各registration身分和收據仍隔離，不查email或假定subject跨client相等。正式採用仍以最後來源的獨立反例／完整CI為準，原PASS不覆蓋後續修改。

02:11 UTC修復來源凍結：provider SHA256 `96d8c73b52c8cf337e1837ee0cb625cc0f5367e140b3cce595141d86cbdaffdb`、testplan `5a23e18746a2428883acd57d8a2d79a9e6ae107e8f2f1d58767463c7a6b7509b`。獨立10項反例、106相關回歸、35受支援auth測試通過，無剩餘範圍內阻擋；初始錯用非固定依賴環境的失敗另外保留。根目錄完整644測試629PASS15原生Windows/PowerShell不適用skip（85.155s），quality＋全可達Git歷史掃描0finding。新版exact-head Windows/PR Gate仍必須重新通過後才可合併；這些本地證據不是實際官方帳戶驗證。


## 0.2.2 一般操作與行情缺口補验

已確認的三個實際產品缺口：`desktop_market.py`沒有TX/MXF原生分鐘檔入口；`desktop_forms.BacktestForm`缺 `instrument_expiries`正常輸入，導致真13,680bar資料未跑即被核心正確拒絕；`desktop_ui.py:ui_paper_replay`忽略typed margin policy，固定100000，而正常120000設定在第一筆計畫被Paper核心拒絕。前兩個不是資料不存在，後者也不是應降低風控。

修復沿用現有市場bar/聚合與JobManager，新增bounded `quantlab/market_history.py`；table型別化到期設定；既有`PaperReplay`增加明示effective-datedschedule模式並從已鎖定broker取得trade_date政策。相同replay路径對不相容旧binding保留檔案、拒絕，不能改檔或重送。獨立95項Paper驗證含原缺陷cursor61失敗/保留pendingplan／原bytes不變／無替換ledger，與所有中斷重啟不重複下單。這些為simulationfixture，不是真券商驗證。

行情審查實際重現cache重新載入接受非法volume／長度、相同source吞入tamperedcache、並行quota競態、unknown檔忽略、鎖初始化/cleanup競態等，皆修正並保留原反例。64MiB輸入、百萬row、120秒、16MiBnormalizedcache與entry/combinedbytes雙quota；OS鎖內admission、immutable source/policyhash及hardlink發布、不覆蓋lastgood。CP950/UTF8九欄CSV與comma-delimitedRPT，未知fixedwidth拒絕；必須明示datedsession，不複製TMFcalendar到其他商品。來源policyURL為參考，不等於已認證。

原始privateCSV/RPT各677441rows/34363020bytes，SHA2566807f4c3b7f977cb7e5109b1135fe69bbfe18d7c6b71a445e6576bb6be6163a8，獨立各重現TX/MTX/TMF202610各300min共900bars，24商品周期GUI組合；outright量與含spread官方日量差保留說明。研究資料品質完全不放寬；market import仍history/unverified，不自動成為研究eligible。獨立159項市場組合通過，nativeWindows仍待本版Gate。

到期表單獨立九項與普通GUI真資料training-only重播兩次通過，5700bars結果hash81d5bf95bd100acd6ad4922f22da78bcf0b841d1e145ee4b48de2f249e7eae8b對同版同設定reference一致；沒有model/network/OOS/holdout呼叫。原dataset/calendar/expiry證據不變。不以此聲稱策略獲利、日期未來不會被交易所修訂或Windowsclient已驗證。

另重新核對需求確認：現有`research._campaign_config`只接受一次train/validation/oos/holdout，`purge_bars`不構成Walk-forward。這是尚待補齊的工程驗收項，不得列外部授權阻塞或宣稱全研究規範已滿。下一獨立模組先做預宣告固定built-in候選池的真rolling/expanding驗證，不假裝adaptiveAI或允許來歷不明AI候選。原百分比是既有清單計分，不覆蓋此次完整需求重驗發現的缺口。


### 02:36 UTC發布與分數核對

0.2.1 [Release](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1)已實際下載核對：EXE41,583,381bytes／SHA256cce3f6242068affa91ab5c242f6ac655bbb59c677e4abda8b85065b97e48e0b1；clean-kit77,401,239bytes／SHA256850e2157d8b6652bc5d269bcd6dc76eba88f0ec7f81c29a75bc7e5b5a91768d4，8entriesCRC PASS；manifest7,247bytes／SHA2564c6c6b0a0ddff170c5394b7b04f03f3575c29b54087c9e042a60c3fb38bc5639綁main2ed1e3e。PostmergeWindows38016622951三jobs與Quantlab38016622996七jobsPASS。獨立重核全部8下載asset及56source inputs，Windows CRLF hash差與Git LF的確切轉換相符，沒有假定hash相同。更新復原保留929舊檔、5sentinel、真設定與lifecycle副本。Server單次啟動1.0279063s/RSS103309312bytes，非clientSLO。

M3完整15點可驗證，新增40/100，原170/200保留，已記錄總210/300＝70%，剩30%。M2/M4仍待候選0.2.2完整Gate，TAIEX分線能力/來源權限未解，M6真授權、M7cleanDPI仍未滿。重新比對使用者原文另確認ProfitFactor/Sharpe實作與停損/停利/成本參考線接線待補，連同Walk-forward列工程工作，不能拿既有窄項分數掩蓋。不得用新權重或移除需求美化百分比。

0.2.2沿用上述真正已發布0.2.1baseline，hash及測試固定fixture依實際下載更新。曾不必要修改recovery腳本舊default導致一項相容性測試失敗，已還原原default而非改門檻；工作流/kit仍明示0.2.1。後續40packaging測試36PASS4PowerShellskip，失敗log保留。另Qt對話框exec被原AST dynamic-call Gate同名拒絕，改用Qt正式非同步open/accepted/finished流程，加重複開啟／取消／关闭期间不啟動工作檢查，54相關測試PASS，原Gate不改，沒有改名或getattr隱藏呼叫。


### 2026-10-10 02:52 UTC：0.2.2 首輪 CI 與 TAIEX 分線權限

PR #5 的 acd2bfee（與本地 43811fa 相同 tree）首輪未通過，未合併、未發布。
- Windows run 38017986367 / job 114112443026：725 項，1 failure、1 error、12 skips。原生完整套件揭露 `tests/test_desktop_market_smoke.py:23` 未指定 UTF-8，在 CP1252 讀取新增中文字串時失敗；改為明示 UTF-8，原斷言不變。
- 同一 job 的 `test_paper_replay_policy.TypedReplayWorkerTests.test_typed_120000_normal_worker_and_repeat_are_safe` 在原 30 秒工作預算內未完成。Linux 相同 960 bars 測試 8.105 秒通過，cProfile 指向每 bar 重讀重建整份 broker journal（980 snapshots、21,136 reductions）及空計畫的 1,920 次 plan/cursor 寫入。正在做局部優化與中斷／篡改回歸，不延長門檻、不刪測試、不減少 fixture。
- Quantlab run 38017986330 的 core/UI jobs 缺少 Qt，新增 GUI 測試模組無法匯入。工作流將安裝同版 PySide6 Essentials / shiboken6 6.12.0 再跑完整套件，不把 import failure 改成跳過。Windows 正式發行仍使用原 hash-pinned 完整 runtime lock 與 native preflight。依賴、安全與完整 Git 歷史靜態 Gate 首輪通過，不代表整體 Gate 通過。

TAIEX 官方五秒指數來源存在，但免費自動下載／再利用權限尚未取得可核實依據，狀態為 EXTERNAL BLOCKED，不串接自動輪詢。
- 實際單次官方 `MI_5MINS_INDEX` 2026-10-08 回應為 3,241 rows / 39 columns，含時間與指數，無成交量；五秒取樣不是交易所原生分鐘 OHLC。09:00:00 是前日收盤 49,806.37，09:00:05 才與當日開盤 49,783.06 相符，不能把前日值算進當日最高價。
- [證交所使用條款](https://www.twse.com.tw/zh/terms/use.html) 第 6、8 節對自動下載另有限制與例外；[政府資料集 11755](https://data.gov.tw/dataset/11755) 是每日 OHLC，不能將其授權套用到五秒來源。[官方 OpenAPI](https://openapi.twse.com.tw/v1/swagger.json) 未列該五秒 endpoint。
- 確認限制後停止後續 payload 下載，僅查條款／目錄。未以 MIS 瀏覽頁或其他端點繞過限制，未將原始 payload 或衍生 bars 放進產品、Git 或 Release。未宣稱該來源一定違法；結論限於本次無法證實所需自動使用權限。


Paper 局部修復已經獨立套用並进入完整回歸：`paper._restore` 每次交易仍在鎖內逐列讀取 seq / identity / operation / payload / state_hash 與 materialized snapshot；只有所有 bytes 與上次已驗證內容完全一致才复用驗證結果，回傳重新解析的 detached state。快取限制為 1 MiB serialized proof，大於限制回到原 streaming replay；儲存不確定標記在兩條路徑後皆執行。外部 kill／restart／篡改／截斷與 transaction rollback 均加入回歸。此機制沒有外部 monotonic anchor，不能識別所有自洽整庫回滾，不作 anti-rollback 新保證。

空決策與 consumed cursor 合成一次 FULL-sync transaction；不能在重啟後重新解讀已滿足的 target，舊版持久化 `[]` 也按既有決策消耗。量測相同 960 bars、17 orders、5 fills、31 journal events：Linux replay 4.254 秒 → 0.517 秒，原 typed Qt/spawn-worker 案例 8.105 秒 → 3.899 秒；原 30 秒上限不改。這是 Linux 量測，Windows 仍須 exact-head CI 實測，不能先報通過。

修復後完整 Linux suite：738 項，723 PASS、15 項既有 Windows／PowerShell 平台檢查未執行，105.539 秒；靜態／完整 Git 歷史 Gate 0 findings。原 960-bar／30 秒 GUI case 通過，Windows exact-head 驗證仍待新 CI，不以 Linux 結果替代。


CI 環境補齊另保留兩次失敗：run 38019029420 因 shell 參數 `--only-binary=:all:` 未作 YAML 字串引用而解析失敗，已引用並本地解析檢查；後續 head 716763a / Linux job 114116001456 在 Qt wheel 安裝後缺 `libEGL.so.1`。現明確安裝 Ubuntu 官方 libegl1 / libopengl0 / libxkbcommon0 並設定 offscreen，保留完整測試，不把 GUI 缺環境改成跳過。Windows 正式產品仍使用自己的原生 Qt 環境與鎖檔；Linux headless 測試不作 Windows 相容性替代。


### 2026-10-10 03:18 UTC：原生結果差異與下一次診斷

head 716763a 的 Windows Server 2022 / Python 3.13.16 run 38019136760 已通過 build、安全、738 項原生測試（726 PASS、12 profile skips）、frozen history smoke、安裝與真正 0.2.1 升級／中斷復原。此結果不能替代尚失敗的完整矩陣：Windows-latest / Python 3.11 的相同 30 秒 replay case 仍逾時；Python 3.12 另有原本 10 秒 process-death golden 逾時。未合併，未發布 0.2.2。

增加僅在 Windows CI 失敗後執行的 `tools/diagnose_paper_replay.py`，以同一 960-bar／120000 typed UI 與真 spawn worker 觀測 SQLite connect／transaction／commit／close、restore、啟動及完整工作時間，並測量原 before/after-event-commit fixture。它不改 SQL、sync、原 30 秒／10 秒 Gate；獨立 180 秒上限僅用於取得診斷，有清理保留與子樹停止，輸出明示非驗收。失敗的原 CI 不因診斷成功變成 PASS。先取得 Windows 時間分布，再決定 scoped connection reuse 是否必要；尚未改 journaling mode 或持久化語意。


### 2026-10-10 03:34 UTC：原生逾時已定位，完整 Gate 仍未通過

同一 PR #5 head `71f8feb73f4f73d09f9ffe14d1f8e6970ab63ecc` 的 Windows Server 2022 run 38020197303 / build 114119289481 再次通過 build、安全、安裝、真 0.2.1 升級、移除保存及中斷復原。Quantlab Windows 3.11 通過，但 Windows 3.12 job 114119289510 仍未達原 30 秒 Paper 門檻，不合併、不發布。Linux Qt 系統函式庫問題已解除，完整 source smoke 接著揭露四個 auth runtime 缺失；工作流補齊既有固定 PyJWT/cryptography/cffi/pycparser 版本，先做原本離線驗證，再跑完整套件，不跳過失敗。

Windows Server 2025 / Python 3.12.10 / SQLite 3.49.1 的相同 960-bar 診斷：worker 29.718 秒，其中 960 次 cursor commit 25.713 秒；所有 replay connection 0.376 秒、broker connection 0.253 秒，故不能把重用連線當主要解法。兩個原 process-death fixture 本次 0.281/0.297 秒，皆 exit 73，先前 10 秒逾時未重現，門檻保持不變。診斷有界且完成 worker 清理，不取代原測試 FAILED。

下一步先在原生 runner 的 disposable 檔案測 DELETE/TRUNCATE/PERSIST + FULL，保留每個既有耐久邊界。尚未改產品 journal mode。[SQLite 官方 WAL 說明](https://sqlite.org/wal.html#walreset)與[3.51.3 修復說明](https://sqlite.org/releaselog/3_51_3.html)指出現有 3.49.1 屬 WAL-reset 問題版本範圍；不得為效能直接開啟未審核 WAL。若採 rollback-journal 模式改善，仍須真實 process-death、備份還原、legacy pending plan、外部 kill 與完整 native 原門檻。


### Smoke 驗收寫入使用者狀態：已重現、修復中

独立反例在隔離的既有模擬帳戶副本執行原 `desktop.py --smoke-test`：exit 0/status passed，但 `state-v1/desktop_safety.json` 與 `state-v1/paper.sqlite3` bytes 改變，kill switch 變 true。原因為合成 worker 雖隔離，主視窗仍先用正式 workspace 啟動並執行 `freeze_paper`。只有 settings 檔不變的既有測試不足以涵蓋此缺陷。這是當前 release blocker；正常啟動的安全停止仍必要，不可刪除。修復須在主視窗/lock/guard 建立前隔離整個 smoke workspace，原設定只讀快照，並以成功與注入失敗測試證明正式目錄、broker、safety、settings、recovery 記錄皆不變。保留原安裝路徑檢查語意，明示 report 的被檢查位置與真正暫存執行位置；最終 exact-head 安裝／升級／復原 Gate 需重跑。


### 03:53 UTC：Smoke 只讀隔離與 CI 固定依賴目標修復

主視窗 smoke startup 現在先建立暫存 root，原設定 workspace 僅透過 `WorkspaceLocator.load(probe=False)` 驗證後讀取；正常 startup 的探測、復原、mutex、停止／對帳規則不變。report.data_dir 保留被檢查設定位置，smoke_data_dir 明示真正暫存執行位置。七項來源測試覆蓋 default/redirected/不存在 root、broker/safety/settings/recovery 全目錄 bytes/names 與 transient write audit hook；Linux PASS。Windows來源測試只把 known-folder discovery 指向測試fixture，native mutex/Qt/spawn 保留真實，非 clean-client 或 known-folder API 的替代驗證。

新增依賴後，原 matrix 的 Win3.11/3.12/Linux3.11 被既有嚴格來源驗證以 unsupported_dependency_target 拒絕（run38021395788），並未執行套件或取得 native benchmark；Linux3.12和UI完整套件已通過。修復明示新增這三個既有CI目標，不刪矩陣／測試。原 Win3.13/Linux3.12 target records 與正式 Windows lock 不變；從官方 PyPI 實際下載九個不同wheel逐一驗hash。共享manifest解析留在已hash綁定的 provider.py，CI-only installer採binary-only、require-hashes、isolated PyPI、force-reinstall並逐一核對pip report的closure/version/digest。真Linux3.12 fresh及已有套件重裝、原OpenSSL4.0.3離線驗證通過；新增native目標仍待CI。

Root完整759 tests：744PASS、15既有Windows/PowerShell平台skip，103.709秒；quality及全Git歷史0finding。四個auth runtime套件的獨立供應鏈audit無已知漏洞；bootstrap pip工具自身的掃描發現另記錄，不能用runtime結果認證工具。原30秒Paper與10秒process-death門檻不變。仍待原生磁碟模式量測、最終timer/cleanup錯誤terminal-proof與exact-head完整Gate，未合併。

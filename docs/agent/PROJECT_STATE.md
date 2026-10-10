# mark-auto 開發接續狀態

<!-- CURRENT_STATUS_START -->
## 當前交付摘要（2026-10-10 06:40 UTC）

- **實際下載仍是 0.2.1 unsigned preview**，release main `2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`；[已核驗的下載與 manifest](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1)。八項主要 assets／56 個來源輸入、EXE／kit SHA-256與ZIP CRC及該版postmerge均已通過。**0.2.2尚未發布**，README保持這個已驗證入口。
- **PR #5已合併；目前接續PR #6，候選仍0.2.2。** main仍是 `94aca46777bd19619c9cbc0721a888173395243e`；PR #6為Draft，remote `dbe7c655`／local `0ab452e`，同tree `87f7d938c29dfd7cfa45089402bbb4af0f037dce`，分支 `agent/windows-release-validation`。新的Linux程序消失修補尚待push／exact-head驗證；不要把此未提交修補算入dbe7c655的CI。
- **PR階段的成功單獨保留：** head `06bcc3a` 的10個Quantlab必要jobs通過，每profile inventory 1016唯一案例＝796 core＋220 research，實際開始清單無遺漏或重複；每Windows Python profile 1002 PASS／14 skips。Server `38028085841` 全套1016項，1002 PASS／14 skips、811.530秒；native frozen history、synthetic WFO兩折22次、安裝／真0.2.1升級／中斷恢復／移除保存通過。60個source inputs與PR artifact hash／CRC已核驗，僅證明此PR artifact，不能取代postmerge Release校驗。
- **保留main94aca467 postmerge失敗：** Quantlab `38029388781`為8/10 PASS；Win311原Paper30秒FAIL，Win312同Paper FAIL另GenericSmokeTerminal SystemExit40秒ERROR。原完整log／計數在ACCEPTANCE的main postmerge evidence保留；這不是目前PR6的兩項失敗，不能混為一個來源。
- **main94aca467的Server已完成，但Release被正確拒絕。** Windows `38029388676` build／security PASS，1016項＝1002 PASS／14 skips、816.337秒；安裝／真0.2.1升級／中斷恢復通過。release job `114150590389`因exact-head Quantlab失敗拒絕，**沒有0.2.2 Release**；Server成功或candidate artifact不能代替發布gates。
- **最新PR6 Quantlab `38030765302`：8/10 PASS。** Win312 core801項＝791 PASS／10 skips、360.075秒；Win311 core801項＝790 PASS／10 skips／1 failure、509.566秒，僅原Paper30秒FAIL。UI1021項＝1007 PASS／13 skips／1 failure、426.451秒，失敗為新增diagnostic的 `cleanup_verified`；兩Linux／Windows research／security通過。PR6 Server `38030765321`仍執行中，不能填PASS。
- **窄Linux程序消失修補已局部驗證，尚未push。** 獨立真實重現：先開 `/proc/PID/stat`，程序隨後退出並reap，讀取可拋ESRCH／ProcessLookupError而非FileNotFound。修補僅讓desktop_runtime及兩個測試helper識別已消失程序，permission／未知錯誤仍fail closed；不據此斷言該次UI遺失artifact的精確根因。isolated45 PASS／53.422秒、independent10 PASS／12.138秒、root43 PASS／52.626秒（集合重疊，不相加）。最新discovery1026＝806 core＋220 research，只是發現，非完整suite PASS；最後native待驗，Paper效能未修好。
- **變更與門檻界線：** 只有上述窄Linux程序消失修補及診斷／測試helper調整，沒有新的產品功能；沒有persistence、storage／FULL、TEMP或測試資料位置變更。原Paper30秒、smoke40秒、process-death10秒及Quantlab每job15分鐘不變。靜態／歷史掃描仍在執行，未提前填結果。
- **WFO／PF／Sharpe／參考快照／普通繁中UI已合併但未發布。** 真實Oct8 WFO仍 `BLOCKED_NO_RUN`：完整guard與既有consumed coverage重疊170 bars，0新評估／model calls／reservation；不改windows或另建registry規避。synthetic WFO不是adaptive AI、真實未見資料或正式排名／Paper資格證明。
- **固定驗收仍210/300＝70%，未接受90點。** 研究100、桌面70、市場40；M4保持PARTIAL／0分，postmerge失敗尚未解除，不採用先前有條件的加分建議。權重／分母／原門檻不變；分數不是工時、全需求、生產或投資認證。
- **外部／安全界線不變：** clean Win10 22H2 x64／Win11 x64 EXTERNAL_BLOCKED、實際ChatGPT grant／inference NOT_VERIFIED、TAIEX盤中自動使用權限未核实；main protected=false／管理API403、unsigned不繞過警告、真交易DISABLED。05:02觀測為一台desktop連線但未授權task、另一台offline，無saved coding environment；不能說沒有電腦連線。
- **歷史與分支已保留：** 06:02時合併分支已自動清理、main與全歷史bundle已核驗；之後新建PR6接續分支，不能仍把「遠端只剩main」當最新分支清單。舊CI、timeout、fixture、Qt與I/O負結果保留。

### 原需求、設計提案與未驗證項目

- **本輪已明確必要的原需求：** Walk-forward，以及使用者原文 §5.1 的 Profit Factor／Sharpe、§3.4 的停損／停利／持倉成本參考線；已合併及PR階段PASS不等於postmerge／已發布交付。
- **尚未採用的完整目標設計延伸：** 04 §9.1 提出的 Average Trade、Sortino、Calmar、延伸分解與成本壓力測試保留為提案。02 歷史原文已明示「若最終採用該完整規格」；未取得使用者直接要求這些延伸的原始證據，因此不把設計表的「必須公開的計算與例外」升格為本輪新增驗收門檻，也不刪除提案。
- **尚未驗證的結果：** postmerge修復／發布、clean client、真實授權與真實研究各依目前證據判定；未驗證不表示功能未實作，設計提案未採用也不等於本輪驗收失敗。

## 現在應接續的工作

1. **當前工作為Draft PR #6**：remote dbe7c655／local0ab452e／tree87f7d938；main仍94aca467，候選0.2.2未發布。PR5已合併，不能再列為待合併工作。
2. PR6 Quantlab38030765302為8/10 PASS：Win312 core801 PASS；Win311只有Paper30秒FAIL；UI1021中新增diagnostic cleanup_verified FAIL。Server38030765321仍執行。main94 Server已PASS，但release114150590389因Quantlab失敗正確拒絕。
3. Linux open /proc/PID/stat後exit/reap的ESRCH已獨立重現；窄修補只處理vanished process，permission／未知仍fail closed。isolated45、independent10、root43項PASS不加總；discovery1026不是全套PASS。尚未push／原生驗證，不稱精確UI根因或Paper效能已修，persistence／deadline不變。
4. 現有公開下載仍0.2.1，210/300＝70%，M4仍PARTIAL。只有postmerge與實際Release完整核驗後才重新逐條對帳，不提前套用條件式230分提案。
5. Oct8 WFO仍BLOCKED_NO_RUN／170 consumed bars，0新evaluation／model／reservation，不改window／registry。clean client、真grant與TAIEX盤中權限保持外部狀態。
6. 06:02已保存完整歷史含merge bundle（1,123,457 bytes）；之後新建PR6接續分支。保留原local歷史／失敗與未提交窄修補，不把舊「只剩main」當現在分支狀態。

### 導覽與單一事實來源

- [功能矩陣](../analysis/02_EXISTING_FEATURES.md)：已發布／候選工作樹整合進度分欄，以及原 F01–F35 與所有歷史證據。
- [風險與發布否決](../analysis/03_CODE_QUALITY_AND_RISKS.md)：當前優先風險、negative results、必要閉合證據。
- [依賴與固定驗收](../analysis/05_IMPLEMENTATION_ROADMAP.md)：下一步順序，Phase／D／M 原門檻及需求對照。
- [機器可讀帳本](ACCEPTANCE.json)：原 gate 與權重保留；current_snapshot 為有日期的摘要，candidate_022_ci 由整合者持續更新，不用舊副本覆蓋。

開發命令仍為 `python -m unittest discover -s tests -v` 與 `python tools/quality_gate.py --history`。使用者開已發布 installer／捷徑；舊 `run.py`／`gui.py` 不作研究入口。未授權的帳戶、電腦、付費服務或真資金交易一律不因接續工作而開啟。


### 歷史檢查點：04:24 整合來源 Gate（當時狀態，不是目前待辦）

- 候選修補完整 Linux root suite：773 項，758 PASS＋15 個既有 native Windows／PowerShell applicability skips，127.279 秒、exit 0；歷史掃描 0 findings。涵蓋 smoke 終態、canonical fixture 與 FULL 設定失敗關閉連線，SQLite mode／耐久邊界／既有門檻不變。此結果取代上文針對較早來源的「最終 root 待驗」，原生 exact-head CI 仍待。
- Qt CI-only 相容鎖及獨立 Linux311 套件稽核已納入 workflow；官方來源、完整 SHA-256、強制重新安裝及 pip report 保留。Windows 產品依賴鎖不變；套件 advisory audit 不等於所有 native library 已安全認證。
- 後續 WFO／報表 combined staging 完整 947 項：932 PASS＋15 既有 applicability skips，270.314 秒。再套用同一 Paper 連線小修補後 5 項 storage regression PASS；仍非已發布或 Windows／真實研究驗收。


歷史驗證位置補註：較早981項在隔離候選執行，25檔按manifest複製；不是最後root全套。12e088f的1000項失敗／cancelled與05:32局部18／33／85項屬先前checkpoint；其後06bcc3a的完整PR1016已通過，但94aca467 postmerge又出現上列兩種timeout。所有來源、平台及計數分開，不相加或追溯改寫。


診斷接續PR #6／`agent/windows-release-validation` 的已推送dbe7c655來自main94aca467。該head為1021＝801 core＋220 research，Quantlab8/10 PASS；未提交的窄Linux ESRCH修補後discovery為1026＝806 core＋220 research，不代表整套PASS。原Windows Job Object與未知／permission失敗關閉要求保留。產品修改限窄Linux程序消失處理；沒有persistence、SQLite模式、TEMP或deadline變更。

<!-- CURRENT_STATUS_END -->

## 歷史原文與逐次證據（依原記錄保留）

以下完整保留本次整理前的內容、要求、來源、失敗與各時點判定。內文即使寫「目前／最新」，也只屬原有日期快照；現在的交付與下一步以本檔最上方有日期的摘要為準。原始基線盤點、固定驗收條款與年代順序均未被當成新版本成功證據。


更新：2026-10-10 02:36 UTC。唯一正式來源：https://github.com/yostar77612/mark-auto。

## 最新接續：02:36 UTC

0.2.1 main2ed1e3e postmerge雙CI全部PASS，Release desktop-preview-38016622951-1八個主要assets已下載驗hash，kitCRC PASS；基線EXE cce3f6242068affa91ab5c242f6ac655bbb59c677e4abda8b85065b97e48e0b1、41583381bytes，manifest4c6c6b0a0ddff170c5394b7b04f03f3575c29b54087c9e042a60c3fb38bc5639、7247bytes。獨立證據接受M3，總210/300=70%，餘30%，不能解讀為所有重新核對需求已認證。

本分支候選0.2.2 history/expiry/Paper margin已合併到工作樹，724完整測試709PASS15skip；後續async對話框54PASS，實際baseline更新40packaging tests36PASS4skip，quality/history0。最終exact-head原生Windows/發布尚待。其他隔離工作：WFO固定pool與明示historical replay；必要PF/Sharpe/持倉保護參考線；TAIEX intraday合法來源研究。不能刪任何原始本地branch，先保存Git bundle/tree映射再清理。

## 02:25 UTC 接續狀態（以下較早快照保留）

PR4已合併main `2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`，headf11e2ef／localfea95b2 tree12804de7477ce6ca2da5d11d474240a795bd9025完全相同。Windows38016153320已PASS644tests633PASS11skip、frozencrypto/真0.2.0upgrade/recovery，Quantlab38016153246七jobsPASS。postmergeWindows38016622951與Quantlab38016622996進行中，尚未校驗新Release。

現在唯一新功能分支agent/market-history-acceptance-v1，候選0.2.2，沿用已合併main並接入已獨立review的history/expiry/Paper margin及historyfrozen smoke。完整724測試709PASS15平台skip。不能在實際0.2.1Release可下載前編造新baselinehash；nextheadWindows尚未跑。mandatoryWalk-forward確認缺失，另隔離最小固定poolrolling evaluator開發中，不把單次OOS當完成。詳細完整功能與限制新增至02分析附錄，原47檔盤點保留。

## 最新狀態與計分

- PR #3 已整合 main `fc2dfacbf297004095e971ec10cf3620307417a2`；0.2.0 unsigned preview 與 no-Python clean-client kit 已發布並實際下載校驗SHA256／ZIP CRC。Release：https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38013204925-1 。
- 原200點170 PASS＝85%；新增市場範圍M1/M5共25/100 PASS；合计195/300＝65%，剩35%，是固定驗收權重，不是工時估計。M2/M3/M4尚待相應版本完整Gate，M6/M7未全滿，不能提前給分。
- 現有PR #4／`agent/chatgpt-desktop-v1`候選0.2.1，remote `7dc3536f`與本地`797f3cd`完整tree相同。Quantlab `38014802083`七jobs與Windows `38014802079` build/security全通過；635 tests624PASS11適用profile skip，原生加密／DPAPI／安裝／真0.2.0升級／中斷復原PASS。Server runner不等於clean Win10/11。
- PR4合併暫緩：offline反例發現新增OAuth registration能繞過另一registration尚未確認的呼叫屏障；修復已通過獨立151項檢查及完整644測試629PASS15平台skip；最終head原生Windows仍須重驗。沒有真帳戶授權或訂閱模型呼叫，不能以工程fixture冒充。
- 下一個行情分鐘匯入模組僅在隔離staging：TX/MTX/TMF真CSV/RPT900bars、24商品/周期組合及159項獨立組合測試通過；另source smoke保留原7步＋manual2步＋auth並新增24圖表組合。尚未整合、未原生Windows/frozen驗證，不能當已發布。
- 真AI：免費Qwen1.5B實際生成3候選並完成回測/OOS/holdout/比較，1個虧損、2個零交易，不合投資晉級。v3兩次duplicate失敗保留；v4固定1次實際改善產生不同參數，技術去重PASS，沒有新回測/OOS/holdout或獲利改善證據。累計14次真免費呼叫，不追加無限制搜尋。
- 真行情：12連續交易日13,680分鐘、24盤獨立官方OHLC；Oct7缺分鐘拒絕。0.2.0 Windows實際官方HTTP診斷VERIFIED，來源皆EOD非realtime；雲端直接HTTP的DNS限制保留，不把另一环境成功改寫舊失敗。
- 圖表真訓練區間重播淨損益−143,590 TWD、1,917訊號、3,831成交；非新模型/OOS/holdout或真交易。Linux截圖檢視通過，非Windows DPI實測。
- clean Win10 22H2 x64／Win11 x64仍EXTERNAL BLOCKED；main管理級保護403／未啟用，簽章及使用者官方授權未取得。真資金交易固定停用。

## 已保留的原始成果與 Git 映射

GitHub App 可正常讀寫 Git 物件、分支與 PR；CLI 無登入不阻礙連接器發布。連接器建立新 commit metadata，因此 SHA 不同，但逐次驗證完整 tree 相同。

| 本地原始提交 | 遠端提交 |
|---|---|
| 0430a74 | eeccb3296e47e84fe8d0f68446dda6cae58976a0 |
| 5bcfbe5 | a90fcb846c358b6867cf3cdf902db858200b1766 |
| 2110016 | b3ad661309d0a514a0889be5cbb214ad0a843933 |
| e5e56bb（含 cde65fb） | 8597dd6e6a0f6f95337e2a17ca98798da9ca2252 |
| 76ad3a5 | 8cea2729fa5f0acca1d1ff947b08d173ffddcd71 |
| 1f78a52 | 8b1f007abdb325c6ddc97707e1e2ab8c6211e5ca |
| 468b86c | 4def6c8907bb00ee975e38912b029648eee97ad0 |
| 8bc19e1 | d0665e1417a6c31d0978e93a9bf2d2194eba913d |
| 3246cdc | b62803a529994f114cb4a4be301e0c62a757ac7e |

`0430a74` 與 `eeccb329` 的 tree 均為 `df167ff071331a6eb75007a72c0d3637e4fc899a`：所有檔案路徑、內容、模式完全相同。原本本地歷史全部保留；本地原始 commit 不在遠端新 metadata 圖的祖先鏈，不能僅憑 PR 合併就刪掉本地分支。

## 目前實作

研究核心：標準庫 quantlab、版本化日夜盤與到期、官方資料匯入／有界免費下載、Decimal 因果回測、五種策略、受限 DSL、持久研究預算、樣本外與保留集隔離、報表／版本選擇、Paper 持久帳本／對帳／風控／故障恢復。

桌面：PySide6 原生繁中介面，既有核心不重寫；七個頁面涵蓋總覽、資料、策略、回測、比較、Paper、設定。工作採 allowlist 子程序、進度／取消、Windows Job Object、單例與睡眠凍結。DPAPI 機密、每使用者 AppData、工作區切換、備份恢復、不可回退研究預算／holdout 控制已實作。

打包：鎖定 CPython 3.13.16、PySide6 6.12.0、PyInstaller 6.22.3、Inno Setup 6.4.3；每使用者安裝與捷徑、保留使用者資料、拒絕更新／移除正在運作的 app。Windows Server CI 必须實際完成 frozen research／Paper 流程與安裝升級移除，並附來源／依賴／授權／hash 證據。未簽章，Release 僅能標 preview。

## 已驗證與尚未驗證的界線

- 原研究來源 `76ad3a5`／`8cea2729`：本地 180 tests 通過，GitHub run `37959451997` 的 Linux／Windows Server Python3.11/3.12 和 UI 五 jobs 全成功。這不取代新增桌面的最終 head 回歸。
- 真實 2026-10-08 TAIFEX CSV／RPT／日報匯入 1140 根分鐘 K，OHLC 一致；價差成交量口徑仍待正式證據。最近 30 官方 ZIP 已下載，保持 `provisional_unverified`／`ranking_eligible=false`，原始行情不提交 Git。
- 預設AI使用明示Fixture；本輪另以實際免費本地Qwen推論驗證受限家族參數生成與整體研究流程，未呼叫付費模型。早期有效新改善候選FAILED（只改名），去重拒絕成功；後續v4限1call產生不同參數，技術去重PASS，累計14真calls，全部舊失敗保留；沒有改善獲利證據。
- Paper 是有限歷史重播，沒有正式即時行情串流。盤中停損／停利未支援即拒絕。未知委託／部位先凍結，禁止猜測補單。
- 實盤固定停用。真券商資格、行情授權、憑證、完整歷史品質與真市場策略績效尚未驗證。
- Windows10 22H2／Windows11 乾淨環境實測 **BLOCKED**：目前無已授權可用 client OS；Windows Server 不能冒充通過。未使用使用者未授權電腦。
- main 保護 **未啟用**：metadata `protected=false`，rulesets 空，管理級 protection API 403 `Resource not accessible by integration`。Code／PR 授權有效；缺管理權限不是證明需重新登入。不可宣稱有防護，也不自行擴權。

## 接續順序與命令

1. 先 `git status`，保留所有未提交修改；閱讀固定合約與驗收清單。
2. 修復並獨立驗證PR4跨registration安全屏障，在原功能分支更新；exact-head完整Gate後才整合。其後接續已保留的行情匯入模組，不覆蓋新修正。
3. 最終 head 的研究／UI／品質／依賴／installer 全通過才可整合 main，並驗證 post-merge build 與 preview Release。
4. 保存原始 Git 歷史與五份分析文件；清理分支前確認保存、已合併與無競態，不具安全刪除條件就保留並說明。
5. 剩餘真 client OS、外部服務與權限阻塞誠實記錄，不降低門檻或以 mock 代替。

開發測試：`python -m unittest discover -s tests -v`、`python tools/quality_gate.py --history`。
桌面開發入口：`python desktop.py`。最終使用者使用安裝檔與捷徑，不需上述指令。
舊 `run.py`／`gui.py` 不得作研究啟動入口。Streamlit 僅保留輔助介面。

## 新增產品範圍

22:52 UTC使用者正式加入市場優先儀表板、真行情/K線/技術指標及無JSON的專業研究交易介面，詳05 Roadmap第18節。原85%只限原範圍；新增及新版整體百分比待盤點凍結權重，不沿用85%。本輪安全修復先驗收整合，再接續市場/UI模組，不以0.1.2預覽當全部完成。

00:15 UTC新增市場範圍100點已實作前凍結（M1–M7），原170/200=85%，新增0/100=0%，整體170/300=56.67%、剩43.33%。採二元證據Gate非工時估计，安全否決與clean Windows門檻不變。0.1.2修復本地203b4af/遠端48a0d833完整tree982a8d2相同，PR#2必要CI正在驗證；市場新檔及其合約為下一批未提交變更，未包含於該驗證head。

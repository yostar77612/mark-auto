# mark-auto 開發接續狀態

<!-- CURRENT_STATUS_START -->
## 當前整合狀態與最後已驗證基線（2026-10-10 09:12 UTC）

**以下分開記錄「最後已驗證來源」與「尚未原生驗證的工作樹整合」。** 最後remote為 `0088b505f236a54323c6cfd94cd00df51ea9db25`／local `f10b6549ed4f78c28b3e557fadb3adc9ccd2e799`，tree `d88b1fd2bcfaed9286c45a51058f21069242abb6`；之後的整合不能繼承這份CI作為新來源PASS。

- **公開下載仍只有0.2.1 unsigned preview。** [已核驗安裝檔與證據](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1)，release main `2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`；PR5已合併main94aca467，但候選0.2.2／PR6仍Draft、未合併／未發布。
- **最後Quantlab38032142094為9/10 PASS、整體FAIL。** Windows3.11 core806項＝790 PASS／15 skips／1 failure、433.599秒，唯一失敗仍是原960-bar Paper30秒。Windows3.12 core806項＝791 PASS／15 skips、339.431秒；UI1026項＝1013 PASS／13 skips、366.894秒；其他Linux／research／security通過。窄Linux ESRCH與Windows nested cleanup已有此來源驗證，不能冒稱新WAL／runtime／AI整合已通過。
- **最後Server38032142096 build／security及安裝流程PASS。** Server2022完整1026項＝1007 PASS／19 skips、808.047秒，該profile原Paper30秒／SystemExit40秒、frozen/history/WFO、真0.2.1升級／中斷恢復／移除保存通過；PR release skipped。實際候選artifact11663227244、PR merge703686e2、60個source inputs及EXE／kit／ZIP hashes已驗證，與0088b505同tree；這不是Release，也不能抵銷Windows311失敗或替代clean client。
- **本次root combined FAIL保留，來源綁定修補focused150 PASS，remote／native CI待驗。** WAL／FULL保留每個原COMMIT邊界、帳本identity與風控；官方固定hash私有SQLite3.54.0／runtime hook、舊0.2.1 workspace guard／schema2 backup、host probe、EXE版本metadata及實際舊EXE拒絕測試程式已套用。舊版source fixture已驗證拒絕；新增舊EXE原生測試尚NOT_RUN，不能把測試程式存在寫成PASS。原960 bars／Windows30秒測試未改。
- **新增本機證據按來源分開。** pre-AI root完整1096項＝1081 PASS／15 applicability skips、291.408秒，log `quant-audit/pre-ai-wal-integrated-full-20261010.log`與source manifest `quant-audit/pre-ai-wal-integrated-source-20261010.json`固定該次來源。其後本機AI focused153項＝152 PASS／1 skip、5.866秒；自動備份初次focused21項全PASS、0.966秒；offline-drive設定恢復修補後23項全PASS、0.962秒。focused logs見`local-ai-integrated-focused-20261010.log`、`automatic-backup-integrated-20261010.log`及`automatic-backup-integrated-final-20261010.log`。目前root venv實測為Linux Python3.12.14／SQLite3.53.1／Qt6.12.0，見`quant-audit/integrated-final-source-20261010.json`；早先手記Qt版本不作獨立量測證據。最終combined suite本次FAIL：1243項＝1225 PASS／15 skips／2 failures／1 error、300.720秒（`quant-audit/integrated-final-full-20261010.log`）。三項均為saved-candidate producer來源綁定未涵蓋provider hook變更後的source hash；現有fail-closed防線正確拒絕未匹配來源。兩個新的literal 0_2_2 transport-verifier profiles已獨立審查並root套用；原三個literal profiles與historical exact-hash測試未改，只將三個真正current-generated identity assertions移至新profile，tamper／mixed-source拒絕保留。修補後root focused150／150 PASS、0 skip、30.760秒（`quant-audit/provenance-integrated-focused-20261010.log`）；隔離54與138項PASS為重疊範圍，不相加。本次1243項FAIL保留，沒有第二次root完整重跑；下一full gate為新exact-head remote CI，native仍NOT_RUN。另`/usr/bin/python3`私有SQLite3.54.0載入probe及Paper111項＝110 PASS／1 skip、5.172秒屬獨立Linux範圍，見`/tmp/markauto-sqlite354-verified-setup.log`、`/tmp/sqlite354-paper-tests.log`。各集合不相加、不互相認證；目前root全套不是3.54或Windows證據。
- **免費本機AI已接入普通GUI，實際新推論仍NOT_RUN。** 可選llama.cpp／Qwen2.5-1.5B路徑使用官方固定hash runtime／model／support DLL來源；無付費fallback，official API預設off。MSVC support DLL再散布授權／打包範圍仍待獨立覆核，尚未作合法性結論。實際native frozen單次呼叫驗證程式已套用並完成審查，尚未執行；mock、歷史14次呼叫或focused PASS均不能替代新路徑證據。
- **每日自動備份與審查修補已root套用，最終驗證仍待。** 預設off，開啟後app運作且所有manager閒置才嘗試，每UTC日最多一次；7份／2 GiB上限、連結保護、不自動刪檔或還原。獨立審查指出舊共用備份可經regular-file hardlink納入外部內容；共用BackupManager的hardlink拒絕已套用並包含於21項focused PASS。移除式磁碟離線時停用／更換目的地的設定恢復亦已修補，root focused23 PASS；最終combined／native未驗，不能宣稱漏洞或整項已完整閉合。
- **耐久與門檻不降級。** 舊來源同960 bars診斷worker35.562622秒，960次FULL cursor commits30.6026735秒，UI35.937秒；瓶頸位於耐久寫入路徑，物理原因未知。新WAL候選是待驗證設計，不是既有30秒PASS；保留原per-bar耐久／帳本identity／風控與30秒、40秒、process-death10秒、job預算，不減bar／commit、不搬TEMP。不再無變更重跑湊綠，但經審查的新實作必須原生重驗。
- **執行責任與AI優先順序已更新。** 依使用者最新授權，assistant承擔工程、環境調查、可合法執行的設定與驗證，不預設把VM、測試或GitHub設定交給使用者。免費本機AI為主；官方API只是可選路徑、預設不呼叫，不暗中使用付費或借用其他工具帳戶。零費用、零真資金交易及原驗收門檻保持。不可代行的帳戶、license、明示條款或持久權限，只提出精確最小確認，不包裝成整套技術作業。
- **外部證據如實保留。** 目前沒有已驗證且已授權的零費用clean Win10/11 x64路徑；GitHub nested guest僅是資源／媒體／license條件未齊的候選。SignPath僅可準備免付費申請材料，尚未獲接納。08:18只讀查核rulesets=[]、main保護仍未啟用；GitHub App無Administration scope，先前403未解除，換CLI／GraphQL／workflow token不會增加權限。實際服務、TAIEX盤中權利、clean client不以mock／Server替代。
- **原始匯入來源已有範圍明確的證據。** 原import `1cacce4ee4eef4ce7e8760f8153ef64a74852d22` 的47檔，其Git mode／type／blob全部與官方upstream `chrisli-kw/AutoTradingPlatform@a0ecf8895716bf5883184fdd27a52023f9700bf3`相同；upstream共49檔，另有`trader/APItest.py`與`trader/performance/backtest.py`未在該import。這證明47檔內容對應，不證明整棵tree／完整history相同，也不是維護者owner attestation；Apache LICENSE與Li Kuei-Wei署名保留。
- **210/300＝70%、M4 PARTIAL不變。** 一個原Paper工程gate仍未通過，另保留本次producer provenance整合回歸FAIL，修補後僅focused150 PASS、remote全套待驗；其餘外部條件分開列示，不能把餘項全說成external。Oct8 WFO仍BLOCKED_NO_RUN，170 consumed bars、0新評估／model calls／reservation；不改window／registry。原需求、權重、失敗與歷史不重寫。

### 原需求、設計提案與未驗證項目

- **本輪已明確必要的原需求：** Walk-forward，以及使用者原文 §5.1 的 Profit Factor／Sharpe、§3.4 的停損／停利／持倉成本參考線；已合併及PR階段PASS不等於postmerge／已發布交付。
- **尚未採用的完整目標設計延伸：** 04 §9.1 提出的 Average Trade、Sortino、Calmar、延伸分解與成本壓力測試保留為提案。02 歷史原文已明示「若最終採用該完整規格」；未取得使用者直接要求這些延伸的原始證據，因此不把設計表的「必須公開的計算與例外」升格為本輪新增驗收門檻，也不刪除提案。
- **尚未驗證的結果：** 原Paper效能gate／發布、clean client、真實授權與真實研究各依目前證據判定；未驗證不表示功能未實作，設計提案未採用也不等於本輪驗收失敗。

## 現在應接續的工作

1. PR #6最後推送0088b505／localf10／tree d88b的Quantlab9/10，唯一Win311 Paper30秒FAIL；Server與候選artifact驗證已完成但不是Release。Main仍94aca467、0.2.2未發布。
2. WAL／FULL、官方private SQLite3.54.0／hook、workspace guard、舊EXE測試程式／版本metadata、GUI免費本機AI及預設off每日備份已root套用。pre-AI1096、AI focused153與備份focused23只認證各次來源；offline-drive設定恢復已修補，native frozen單次AI驗證程式已套用、實際執行仍待，沒有新native PASS。本次combined1243項FAIL保留；新literal producer profiles已審查套用、focused150 PASS，historical profiles未改。沒有第二次root全套；下一full gate為remote CI，native仍NOT_RUN。
3. 舊窄Linux ESRCH修補已有完整Linux／UI及Windowsnested cleanup成功；原Paper耐久路徑worker35.562622／cursor commits30.6026735秒的失敗證據保留。WAL候選尚未證明原Windows30秒達標。
4. 固定210/300＝70%、M4 PARTIAL保持。Assistant承擔工程與環境準備，不預設要求使用者搭VM、跑測試或處理GitHub技術設定；僅對無法代行的帳戶／license／條款／persistent access精確確認。免費本機AI優先、official API可選，零費用／零實單。
5. Oct8 WFO仍BLOCKED_NO_RUN／170 consumed bars，0新evaluation／model／reservation，不改window／registry。clean client、真grant與TAIEX盤中權限保持外部狀態。
6. 保留全部Git歷史、0088b505候選artifact及歷次失敗；目前文件同步只補最近可證基線與整合中計畫。後續CI終態由其新head記錄，不預填PASS，不改原權重／門檻。

### 自主接續計畫與不可代行的邊界

1. **固定候選來源並重驗，而非提前授分：** WAL／FULL、官方私有SQLite3.54.0／runtime hook、workspace guard、版本metadata、免費本機AI及預設off每日備份已root套用；備份offline-drive設定恢復已focused23 PASS，native frozen單次AI驗證程式已套用、實際執行仍待。producer profile修補已focused150 PASS；保留本次1243項FAIL、不宣稱第二次root完整重跑，固定最終來源／runtime／依賴／manifest後由remote CI驗證full gate、原30秒與全部必要native、frozen、安裝／真0.2.1升級／中斷恢復。pre-AI全套與各focused證據只屬各自來源；未出現新exact-head結果前保持NATIVE_CI_PENDING／NOT_VERIFIED。
2. **保留原持久語義：** WAL候選需逐個原邊界COMMIT＋FULL、無外包整段transaction／降級NORMAL或OFF，既有mutex、cursor／pending plan／stable IDs不變；broker DELETE／FULL仍分開。SQLite版本／官方hash／native載入來源、local filesystem、舊版本workspace拒絕及DB／WAL／SHM備份恢复都須有實證；guard已用精確0.2.1 source fixture證明startup／schema2 archive拒絕；實際舊EXE拒絕測試程式已加入但尚NOT_RUN，仍需原生結果。備份hardlink修補與移除式磁碟離線設定恢復須完成最終整合回歸。這是必要待驗證清單，不是完成宣告。
3. **驗證免費本機AI普通流程：** GUI管理的可選llama.cpp／Qwen2.5-1.5B已整合，官方runtime／model／support DLLs固定hash，loopback、有限budget與輸出驗證保持；一般使用者不需手寫JSON或自行架服務。下一證據為同來源native frozen實際單次呼叫及乾淨終止，不以153項focused、mock或歷史llama.cpp／Qwen呼叫代替；此新呼叫尚NOT_RUN。官方API可選、預設off，不設付費fallback；M6與其餘原權重／狀態本次不改。
4. **Windows驗證由assistant持續承擔：** 已授權標準public GitHub runner可提供Server證據；先做只讀host能力／磁碟調查。Nested x64 guest在GitHub官方文件中是實驗性、無保證路徑；需實際可用加速／資源、合法精確Win10 22H2／Win11媒體及所需license／條款確認。此cloud shell目前無現成KVM／VM工具，不代表免費虛擬化普遍不可能。Windows11 ARM、Server、過期Win10 evaluation頁面與未授權Azure試用均不可冒充目標client；不繞TPM／Secure Boot／啟用限制、不預設使用者需準備VM或跑測試。
5. **保護與簽章保持誠實：** assistant準備main protection精確所需scope／規則與可行路徑，現有連線缺Administration則只停在該操作，不反覆撞403、不換transport冒充授權，也不索取聊天中的token。SignPath可先準備真實申請草稿；47檔upstream內容對應已驗，但完整lineage／維護者權利陳述、打包界線與metadata／政策仍需分別補證；OSI授權、MFA／角色、來源到binary及每次release核准仍待確認。外部提交、帳戶／條款、GitHub App或簽章persistent access須個別具備所需授權；不買付費簽章、不保證免SmartScreen。
6. **保留每次結果：** 舊0088b505的806core／220research、9/10與同工作量diagnostic作為固定比較；新來源完整清單與依賴另行記錄。全部PASS／FAIL／ERROR／SKIP、elapsed、source／runtime hashes、OS／volume、cursor／orders／fills與清理／恢復證據保留；不按結果追加無變更重跑，不將別台host PASS寫成失敗CI已通過。

本計畫依據當日既有查核：`windows-environment-options-20261010.md`、`signpath-eligibility-20261010.md`、`github-protection-options-20261010.json`。可用方案、授權缺口與推論分開；不新增權重、不把準備材料算成外部已通過。

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


最後已推送／驗證來源仍PR #6 head0088b505／localf10b654／tree d88b1fd2，1026＝806core＋220research且Win311 Paper30秒FAIL。工作樹後續WAL／runtime／guard／AI／每日備份已套用、程式delta已齊；另待最終來源固定、combined及原生驗證；各歷史checkpoint按原日期解讀。

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

# mark-auto 開發接續狀態

<!-- CURRENT_STATUS_START -->
## 當前交付摘要（2026-10-10 05:02 UTC）

- **已發布：0.2.1 unsigned preview**，main `2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`；[正式下載與該版 manifest](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1)。已實際核對八項主要 assets／56 個來源輸入、EXE 與 kit SHA-256／ZIP CRC；postmerge Windows 與 Quantlab 全部 PASS。這是研究／Paper 預覽版，並非 clean-client 或投資合格證明。
- **正在修復：PR #5／候選 0.2.2，DRAFT／FAIL_REPAIR_IN_PROGRESS**。版本及功能分支不變；上次推送 head `d598b39` 的 Quantlab `38024116768` 為 8 jobs 中 7 PASS，Windows 3.12 在原 960-bar／30 秒 Paper case 再次逾時。診斷 worker 36.453 秒，其中 960 次 FULL cursor commit 31.587 秒；不能沿用較早 head 的 PASS。未合併、未發布，沒有 0.2.3 Release，也沒有已發布 0.2.2 baseline。
- **已整合但未推送：** WFO、PF／描述性 Sharpe／參考快照、普通回測繁中呈現與指南的 981 項全套，實際在 `/tmp/mark-auto-023-candidate` 執行：966 PASS＋15 個既有 native／PowerShell skips，271.745 秒。其後依 `root-integration-manifest.json` 逐檔核對，將 25 個相同 bytes 檔案複製至 root；這是該整合檢查點的來源等價候選證據，**不是最後整合 root 全套**。之後 CandidateSummary 與診斷新增不在這 981 項執行範圍內，最終全套／native CI 仍待。
- **後續呈現／診斷：** CandidateSummary 已套用至 root 並獨立審查：79 項 focused PASS；root 97 項＝96 PASS＋1 Windows-only skip，27.561 秒。Paper 顯示未改。diagnostic-only 新增另有 root 145 項＝140 PASS＋5 skips，8.223 秒；上述集合重疊，不相加，也不替代最後全套。原普通回測／footer 的 53 項獨立、139 項 focused 屬較早檢查點。
- **原生與診斷範圍：** 上次 head 的 Server run `38024116755` build／security PASS，773 項＝761 PASS＋12 profile skips，238.878 秒；native frozen、安裝、真 0.2.1 升級／復原 PASS，PR release job 正常 skip。完整矩陣仍因 Win312 Paper 預算失敗而未過。下一步僅做同一原生 host 的 C:／RUNNER_TEMP 與 DELETE／PERSIST fresh／held 有界比較；尚未改產品儲存、FULL 耐久或原 30 秒／10 秒 Gate。
- **研究仍有明確限制：** saved-pool 的 157 項獨立審查屬整合前證據，目前功能已在未發布工作樹；不是 adaptive AI 或正式排名認證。真實 Oct8 WFO 仍為 `BLOCKED_NO_RUN`，完整 guard 與既有 consumed coverage 重疊 170 bars；0 新評估／模型呼叫／reservation，不改 window 或另建 registry 繞過。
- **固定歷史驗收帳本：210/300＝70%，未接受 90 點**。原研究 100、桌面 70、市場 40；僅已取得證據的整項 PASS 計分。這不是剩餘工時、完整原需求或生產就緒百分比；後來重新確認的必要需求仍明列，分母／門檻不降低。
- **外部與安全邊界：** clean Win10 22H2 x64／Win11 x64 為 EXTERNAL_BLOCKED；實際 ChatGPT grant／訂閱推論 NOT_VERIFIED；TAIEX 盤中自動使用權限未核實；main protection 未啟用且管理 API 403；unsigned 不繞過安全警告；真資金交易固定 DISABLED。 05:02 環境重查列出兩台桌機，一台已連線但未授權執行工作，另一台離線；沒有 saved coding environment，仍無已授權的乾淨 Windows 驗收環境，未要求更改設定。


已推送身分對照：remote `d598b39` 對應 local `9c8708a`，tree `84978f8be8d4a2ced60e5b90a7ee746c2690acc0`。之後的未提交整合／呈現／診斷工作不包含在這個舊 remote tree。

### 原需求、設計提案與未驗證項目

- **本輪已明確必要的原需求：** Walk-forward，以及使用者原文 §5.1 的 Profit Factor／Sharpe、§3.4 的停損／停利／持倉成本參考線；工作樹整合及本地 PASS 不等於已發布交付。
- **尚未採用的完整目標設計延伸：** 04 §9.1 提出的 Average Trade、Sortino、Calmar、延伸分解與成本壓力測試保留為提案。02 歷史原文已明示「若最終採用該完整規格」；未取得使用者直接要求這些延伸的原始證據，因此不把設計表的「必須公開的計算與例外」升格為本輪新增驗收門檻，也不刪除提案。
- **尚未驗證的結果：** 最終 exact-head native／發布、clean client、真實授權與真實研究各依目前證據判定；未驗證不表示功能未實作，設計提案未採用也不等於本輪驗收失敗。

## 現在應接續的工作

1. 當前主工作是 **PR #5／agent/market-history-acceptance-v1／候選 0.2.2**；PR #4 已合併並隨 0.2.1 發布。下方舊「修 PR4／待 0.2.1」是歷史，不是最新待辦。
2. 最新d598b39 Quantlab7/8 PASS，Win312原960bar／30秒Paper再次FAIL；Server frozen／install／真0.2.1upgrade／recovery通過不替代矩陣。先做同host儲存位置／DELETE與PERSIST fresh／held有界診斷，未改產品耐久或時間門檻。
3. 候選 981 項全套於 /tmp/mark-auto-023-candidate 完成後，25 個精確檔案依 manifest 複製至 root；這不是最後 root 全套。後續 CandidateSummary 已套用、獨立審查 79 focused PASS，root 97 項 96 PASS／1 skip；Paper 顯示未改。診斷另有 root 145 項 140 PASS／5 skips；最後完整／native CI 仍待，保持同 0.2.2／PR5。
4. 真實 Oct8 WFO 停在 BLOCKED_NO_RUN；保留原來源／registry／window，不重設、不新增呼叫或評估來規避。外部 clean client／grant／盤中授權另列。
5. 每次整合前保留未提交修改與原本本地歷史；需要清理分支時先確認完整保存、tree 映射與無競態。無安全條件便保留，不擅刪。

### 導覽與單一事實來源

- [功能矩陣](../analysis/02_EXISTING_FEATURES.md)：已發布／候選工作樹整合進度分欄，以及原 F01–F35 與所有歷史證據。
- [風險與發布否決](../analysis/03_CODE_QUALITY_AND_RISKS.md)：當前優先風險、negative results、必要閉合證據。
- [依賴與固定驗收](../analysis/05_IMPLEMENTATION_ROADMAP.md)：下一步順序，Phase／D／M 原門檻及需求對照。
- [機器可讀帳本](ACCEPTANCE.json)：原 gate 與權重保留；current_snapshot 為有日期的摘要，candidate_022_ci 由整合者持續更新，不用舊副本覆蓋。

開發命令仍為 `python -m unittest discover -s tests -v` 與 `python tools/quality_gate.py --history`。使用者開已發布 installer／捷徑；舊 `run.py`／`gui.py` 不作研究入口。未授權的帳戶、電腦、付費服務或真資金交易一律不因接續工作而開啟。


### 04:24 整合來源 Gate 更新

- 候選修補完整 Linux root suite：773 項，758 PASS＋15 個既有 native Windows／PowerShell applicability skips，127.279 秒、exit 0；歷史掃描 0 findings。涵蓋 smoke 終態、canonical fixture 與 FULL 設定失敗關閉連線，SQLite mode／耐久邊界／既有門檻不變。此結果取代上文針對較早來源的「最終 root 待驗」，原生 exact-head CI 仍待。
- Qt CI-only 相容鎖及獨立 Linux311 套件稽核已納入 workflow；官方來源、完整 SHA-256、強制重新安裝及 pip report 保留。Windows 產品依賴鎖不變；套件 advisory audit 不等於所有 native library 已安全認證。
- 後續 WFO／報表 combined staging 完整 947 項：932 PASS＋15 既有 applicability skips，270.314 秒。再套用同一 Paper 連線小修補後 5 項 storage regression PASS；仍非已發布或 Windows／真實研究驗收。


驗證位置補註：981 項在隔離候選工作樹執行，25 檔複製當下的 bytes 由 root-integration-manifest.json 綁定；其後已加入 CandidateSummary 與 diagnostic-only 變更，不能把早期來源等價延伸為最終 root 全套通過。較早真正 root 全套 773 項、候選 981 項、後續 root 97／145 項各自保留範圍；最終完整／原生 CI 待驗。

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

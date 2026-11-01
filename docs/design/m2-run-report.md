# M2 第一輪實作與驗證報告

## 最新補正驗證與交付基準（2026-11-02T04:43+08:00）

功能範圍已全部完成；交付須以四個開放 PR 最新 Head 的全部適用 CI 成功為準。
此段取代下方較早的 Head／CI 快照；舊失敗、重跑與原始來源記錄均保留。
本報告本身包含在最後提交的 CI 中，因此最終綠燈以每列 Checks 連結為準。

| 工作 | 最終實作來源／發布版本 | 完整本機測試與實際啟動 | 最終 CI |
| --- | --- | --- | --- |
| 行情設定 #129 | 34673c2／2d8319b（他人已合併） | 3893 項、2094.353s；無新增失敗；既錄 LOCAL／fake SIM 啟動 | [35/35 成功](https://github.com/yostar77612/mark-auto/pull/129/checks) |
| M2-0 #128 | 66c3957／e7e3e13（他人已合併） | 3888 項、2380.898s；無新增失敗；既錄兩種啟動 | [35/35 成功](https://github.com/yostar77612/mark-auto/pull/128/checks) |
| M2-8 #130 | 5906460／8b55c3d | 3916 項、1422.446s；LOCAL5.692s／fake SIM3.718s | [35/35 成功；run41345845844](https://github.com/yostar77612/mark-auto/pull/130/checks) |
| M2-6 #131 | b39af9c／58a233a | 3943 項、1456.190s；LOCAL5.496s／fake SIM3.557s | [最新版本 CI 為必要交付檢查；run41348100137](https://github.com/yostar77612/mark-auto/pull/131/checks) |
| M2-1 #132 | b605466／d2c11f2 | 4005 項、1426.235s；原有三項真實視窗啟動來源不變 | [離線全工作流程重跑及安裝驗證](https://github.com/yostar77612/mark-auto/pull/132/checks) |
| M2-2 #136 | 7d72c5f／本報告所屬最後文件提交 | 4125 項、1442.544s；原有三項啟動／功能流程來源不變 | [最後報告版本須全綠後交付](https://github.com/yostar77612/mark-auto/pull/136/checks) |

上述最新四個實作來源的本機完整結果均為10F22E42既有skip，屬非零結果，
不是宣稱本機全數通過。每次全部32筆／31個失敗身份的實際原因逐項與原main0453136
比對：20項symlink1314、worker-log32、原生啟動PID、三項既存mutex、四項提早結束
paper probe、三項retained-grandchild Errno6。最新 M2-8／M2-6 的E06次要清理為
兩次WinError32/.sqlite，與main相同；較早來源的WinError5/.sqlite-shm差異仍保留。
兩次新完整測試的30/32 frame、32/32例外型別鏈、15/16來源相同；只有原installer
斷言因既有清理fixture移行，未改斷言。沒有擴大main失敗允許清單。

M2-8完整原始log SHA256：`3686f198b4d8c60fffcedd6cc43b91b72783822deb838e600b4b0fb9599c7e28`。
M2-6完整原始log SHA256：`56c77a6fe6dbe361a10f5e8dc88fc994a5fe84453fcd47094f69f33fa51ec40b`。
詳見 [M2-8補正比對](m2-8-endpoint-backport-full-comparison.json)、
[M2-8啟動](m2-8-endpoint-backport-startup.json)、
[M2-6補正比對](../analysis/m2-trading/endpoint-backport-full-comparison.json)、
[M2-6啟動](../analysis/m2-trading/endpoint-backport-startup.json)。
兩次實際啟動都走原始 `_run_window`、真正視窗與七頁研究介面，正常關閉自有程序／
執行緒及端點。SIM為自有執行緒中的真正認證IPC伺服器加fake SDK；零真實SDK登入、
CA或外部委託。最後唯讀檢查時間2026-11-01T20:42:24.3580699Z：0個本工作交易引擎。

補正原因：#130文件版CI41342046048的Windows3.11清理案例，暴露正常關閉先移除
端點的競態。已驗證的1ebc27e原先只在M2-1，漏回補上游；現已原樣回補M2-8／6，
新增兩個方法涵蓋snapshot／execute與仍存活／異常退出反例。RED為2個子案例錯誤；
GREEN為12個實際程序／邊界案例。原15s、保留PID、CAS與零退出仍嚴格；兩項清冊
測量128→134、211→267已獨立提交。兩個上游分支實際重新完成全測後才推送。

M2-1 d2c11f2的所有非docs內容與完整驗證的b605466逐位元相同；對最新M2-6
58a233a做真正三方merge-tree可無衝突，合併後所有非docs內容仍相同。保留此版本
的安裝驗證持續執行。M2-2正常合入M2-1及最新上游證據，所有非docs內容仍等同
已完整測試且實際啟動的7d72c5f；不因文件重組重跑相同程式的本機全測。
最終報告提交仍實際跑完整遠端CI。全部正常merge，沒有rebase、force或main合併。

另保留 #132 run41344493949 attempt1：Linux3.11 Qt原生程序在
`CommandPalette.populate` line99（toggle137，原測試264）崩潰，exit139；另三個
紅燈為相依彙總。該模組及測試與原main逐位元相同。原因尚未證實，未宣稱已修好或
列成main允許失敗；完整保存trace，依指示重跑整個工作流程attempt2。原失敗分組
已在attempt2成功，其餘工作及獨立安裝結果仍以最新Checks為準。沒有skip、放寬斷言
或只重跑失敗job。較早已取代／取消的同Head工作不作最終成功證據。

LIVE送單／改單／撤單仍硬性停用；G3、SDK1.7.9與鎖檔、PROJECT_STATE、ACCEPTANCE
及candidate pool均無變動。第一輪外的M2-3／4／5／7／9沒有開始；真實帳戶SDK／CA／
模擬券商時序與回報屬擁有者D8驗收，fake證據不冒充實際券商委託。

---

報告時間：2026-11-02T03:02+08:00（Asia/Taipei；含兩次安裝復原失敗後的預算判斷與順序修正）。

本輪涵蓋行情設定前置修正、M2-0、M2-8、M2-6（含擁有者追加第6–8點）、
M2-1、M2-2。未開始第二輪 M2-3／4／5／7／9，也未擴充成全站 UX-1 改版。
所有券商操作驗證使用 fake SDK；沒有使用真實金鑰登入、啟用真實 CA，或送出
任何真實／券商模擬環境的實際委託。LIVE 下單、改單、撤單仍由程式硬性拒絕。

本報告與最後分支的最終提交一起接受 CI；只有各 PR 最新 Head 的全部適用工作
成功後才交付。Checks 連結保留實際最終結果，避免為了補寫報告再跑一次相同 CI。
未合併 PR 的 release 工作依既有流程跳過，並非新增測試 skip。

追加的一小時交付時限未達成；完整重測與 CI 結果均照實記錄。

## 交付與合併順序

| 工作 | PR | 完整本機測試 | CI 證據 |
| --- | --- | --- | --- |
| 行情設定前置修正 | [#129](https://github.com/yostar77612/mark-auto/pull/129) |3,893／2,094.353s；10F27E42skip；無新增失敗|35/35成功，head2d8319b，run41279585267 attempt2|
| M2-0 政策 | [#128](https://github.com/yostar77612/mark-auto/pull/128) |3,888／2,380.898s；10F27E42skip；無新增失敗|35/35成功，外部最終heade7e3e13，run41286744449|
| M2-8 引擎清理 | [#130](https://github.com/yostar77612/mark-auto/pull/130) |3,914／1,593.006s；10F22E42skip；無新增失敗|35/35成功，head868da0c，run41292665501|
| M2-6 交易頁與顯示 | [#131](https://github.com/yostar77612/mark-auto/pull/131) |3,941／1,543.784s；10F22E42skip；無新增失敗|35/35成功，headd2db0d6，run41293906679|
| M2-1 永豐連線 | [#132](https://github.com/yostar77612/mark-auto/pull/132) |4,005／1,426.235s；10F22E42skip；無新增失敗；sourceb605466|最新分支提交獨立接受完整CI，以[最終Checks](https://github.com/yostar77612/mark-auto/pull/132/checks)為交付門檻；不沿用歷史Head的成功結果|
| M2-2 手動模擬交易 | [#136](https://github.com/yostar77612/mark-auto/pull/136) |4,125／1,442.544s；10F22E42skip；無新增失敗；source7d72c5f|最新分支提交獨立接受完整CI，以[最終Checks](https://github.com/yostar77612/mark-auto/pull/136/checks)為交付門檻；不沿用歷史Head的成功結果|

F／E／skip 為原始 unittest 結果。本機完整測試仍是非零 FAILED，不能描述成全部
通過；最終接受的是逐項核對後僅剩 main 既有 Windows 主機限制，且無新增失敗。

本報告提交前已核對 #132 head2901ea7 的離線流程41337526546：35/35成功。
Windows安裝流程41337526430及 #136 本報告所在最終提交，仍須以各最新Head的
Checks全部適用工作成功為交付條件；此處不預先宣稱尚未完成的工作成功。

#129 與 #128 由其他執行者合併到 main；本代理未合併任何 PR。其餘堆疊為
**#130 → #131 → #132 → #136**，全部以正常 merge／fast-forward 整合，沒有改寫
歷史或 force push。M2-8 後續發現的清理競態修正在 #132，包含於最終堆疊。

## 完成的功能

- 政策與標章改為「正式下單預設停用，日後需擁有者另行明確啟用」，本輪沒有
  正式下單開關；相關文件斷言保留並依 D1 獨立更新基準。
- 設定頁整合成同一個永豐連線：儲存並連線、登入後發現並遮蔽帳戶、signed
  狀態、逐步 CA 與就緒原因。行情、歷史回補與警示共用登入；未知舊登出結果
  同時阻擋兩個舊入口，避免再開另一條 session。舊工作區可啟動。
- 交易頁支援環境切換與色帶、真實日期／模擬交易日分開顯示、中性首次對帳、
  策略精靈入口、短說明與鍵盤可用的「?」。績效來源分開呈現。
- 券商模擬環境提供明確確認的手動預覽、送單、只改價改單、撤單、原生回報與
  對帳。最小 TMF 診斷單由後端準備並確認後送出；未知／部分成交不自動重送。
  每次操作保留帳戶、環境、登入世代、版本與委託身分，沿用既有 canonical
  交易引擎與日誌，不新增另一個 financial writer。
- 顯示獨立的應用程式虛擬模擬資金，未把未知券商資金當成可用餘額。股票以
  整張輸入、原始股數仍保留；期貨以口數顯示。委託表預設六欄，獨立保存欄位
  偏好，完整帳戶與委託識別仍在確認／tooltip 中。
- 自有測試引擎在成功、初始化／測試／結束例外與逾時時均有保留身分的清理。
  已正常關閉而端點先消失時，只有保留程序確認退出0才接受；存活、異常退出
  或外來 session 仍失敗。未以程序名稱強制關閉使用者或其他任務的引擎。

手動停損值是預覽／風控參考；自動保護單、策略排程、分鐘回測與第二輪風控
不是本次交付功能。

## 實際啟動與功能證據

以既有 private SQLite interpreter、原始 LOCAL child guard、真實 `_run_window`
與 research session 啟動；broker 端注入 fake SDK，使用真實認證 IPC。

| 測試程式提交 | LOCAL | fake SIM | 完整 UI／IPC 功能流程 |
| --- | --- | --- | --- |
| M2-1 b605466 |0／6.145s|設定儲存連線與鍵盤選帳戶0／6.613s；直接啟動0／3.602s|連線組合，resource_calls0，0 CA／委託|
| M2-2 7d72c5f |0／5.976s|實際週一時鐘直接啟動0／3.749s，未確認資金故0委託|0／7.416s；2次canonical送單鏈、2次place、1次amend、2次cancel|

最後一列的正向操作明確使用涵蓋的10月假市場時鐘及窄範圍 UI 時間讀取，沒有
改變真實 UTC 租約或期限，也沒有聲稱實際當日可交易。流程確認虛擬資金40000、
拒絕過期31秒的預覽、TMF診斷送單後已知未成交撤單，再完成一般假委託改價撤單。
五個真實危險確認框預設 Cancel；financial_query_calls0、CA_calls0、resource_calls1。
每個自有 LOCAL 程序正常退出，fake host thread join、research 釋放與端點移除均成功。
這些啟動檢查沒有匯入真實 SDK。

前次歷史 M2-1 完整測試來源為 f77d2b07f5ed24bd276f42c520b26efc033f6f49，原始日誌 SHA256：
`6c3f6e05332ab30fbf107039caa1873f94047d639bc1cf0d9011ab289a1af313`。
前次歷史 M2-2 完整測試來源為32ad38428e5da8959c18aad9fa403e15edbce55d，原始日誌 SHA256：
`393d28bd1c61cb5ac703594a853d87aaca7014cbc14cc191f02a056524e203f1`。上述兩份保留為歷史；新的順序修正另以本次完整測試驗證。

最新完整測試來源：M2-1 `b605466455655b17251122347ba28da202776653`，原始日誌 SHA256 `b74e4e04a3d03103cec67db72fdb63f6d21f62a5946009c6cd9397cb19154cdc`；M2-2 `7d72c5f38ac32d38709a39bcfb6ecb0ce23c7177`，原始日誌 SHA256 `c7d319dbf306ba8357815ef5902a56180ab189978103c878980dd2364e015b95`。各實際失敗均個別比對，日誌不改寫；後續僅提交證據文件，非文件 Git blobs 必須與新完整測試來源相同。

## 失敗歷史與修正

- 未隱藏先前完整測試中的 frozen metadata probe 參數缺漏與兩個逾時案例；參數
  修正、main／分支原樣對照及完整重跑結果分別保留。
- #132 首輪 CI 的原始 IPC/CAS 案例暴露重複清理的端點競態，另三項為彙整失敗。
  兩個新回歸先 RED 再 GREEN；原始真實案例與清理回歸共12項／24.115s通過。
  其首輪 Windows 安裝三項工作已通過，最終修正 Head 仍獨立接受完整 CI。
- 修正 Head a62a110 的離線35項全部通過；Windows安裝流程41323736442
  attempt1在重裝後的 retained-candidate 自測回報 InsufficientExistingSmokeBudget。
  七項UI操作與行情／認證／歷史／walk-forward檢查均通過，程序清理已驗證；
  失敗artifact13091592701保留。未歸入允許的main失敗、未放寬任何時間或斷言，
  重跑整個流程並要求最新Head全部適用工作成功；最終結果見上方Checks連結。
- f77 第一輪4,000項中新增一次 alert store WinError5；main與同程式各100次對照
  均未重現。未把它加入允許基準，也未加入臆測的儲存重試；保留失敗紀錄，
  以不變程式完整重跑4,000項後才接受零新增失敗。
- 舊799efad的4,118項完整測試發現 native Cancel 案例受先前 Qt 退出狀態影響。
  原案例獨跑通過；明確先退出可重現原斷言失敗。修正為擁有外層事件迴圈，
  保留原本 Cancel／Escape／不送單斷言並增加退出碼斷言；55項相關測試通過。
- main 基準的符號連結權限、檔案 handle、啟動 PID／mutex、早退 probe 與保留
  子孫 handle 問題逐段核對；同名失敗不直接視為同因。E06次要清理路徑變體
  與未能僅由當次堆疊證明的 paper probe 歸因，均在個別驗證文件中明確保留。

## 檢查、安全邊界與待擁有者實測

M2-1／M2-2 全專案 Ruff lint／format、Python3.11 syntax與credential/static gate
皆通過；最終分別1154／1182個格式檔（後者含本地檢查檔）、1071／1094個語法檔，static finding0。
新增 Python 路徑均登記清冊；字串連續且在 Lane 區塊，樣式僅在 theme。功能造成
的字串、樣式、AST與清冊基準均用獨立且逐項說明的提交；沒有調高限制、削弱
斷言或新增 skip。精確閱讀性例外與後續窄範圍拆分計畫照實記錄。

GitNexus 為唯一圖工具；編輯前 impact、提交前完整 all／staged與新增定義對照
均保留。HIGH／CRITICAL 警告沒有被較低共同軸數字抵銷；UNKNOWN與截斷結果不
作為無影響證據。兩個獨立 Standards／Spec 檢查及其已修正舊登出入口問題見
[review](../analysis/m2-manual/review.md)。30場景尺寸紀錄／13張一致畫面保留來源
e833622，沒有把視覺 fake DTO 當成真實 IPC 或券商驗收。

30個 G3 檔案、兩份 ACCEPTANCE、PROJECT_STATE、candidate pool與SDK1.7.9 pin／lock
保持不變。根目錄原有 AGENTS／CLAUDE／handoff及使用者資料未修改或提交。
最終自有引擎程序檢查結果：0個符合已知M2 worktree路徑且帶--trading-engine的程序；使用者安裝版與其他任務未受控。

仍待擁有者依 D8 驗收：安裝環境的實際 SDK 可用性、真實帳戶權限／簽署狀態、
模擬服務時段／CA行為與實際 order／deal 回報。這些沒有使用真實帳號驗證，
沒有聲稱已實際完成券商模擬委託。擁有者驗收前不開始第二輪。

詳細證據：[行情修正](../analysis/market-settings-fix/verification.md)、
[政策](../analysis/m2-policy/verification.md)、[清理](m2-8-verification.md)、
[交易頁](../analysis/m2-trading/verification.md)、
[連線](../analysis/m2-connection/verification.md)、[手動模擬](m2-2-verification.md)、
[自主決策](m2-decisions.md)。

## 安裝復原預算與順序修正的最終驗證

原41323736442 attempt1／2分別在 retained-candidate／recovered-candidate 自測回報 InsufficientExistingSmokeBudget，artifact13091592701／13092473832均保留，未歸入main允許失敗。實際attempt2新程式執行最多30.359秒，排除一般預算耗盡；原浮點減法會將40秒誤算為39.99999999999994。三個指數邊界的實際函式控制先RED後GREEN；改比較相同期限端點，不加epsilon或寬限，短一個浮點單位仍拒絕。實際callback以70s前段、102s尾段在原120s總期限內重現失敗，再將原復原呼叫移到原工作manager.join/close後、walk-forward manager建立前，控制案例轉綠。40s復原、6s準備、120s總期限與全部原檢查不變。順序控制證明可能的晚啟動問題，不能單獨歸因為實際CI根因；舊db1候選的中斷測試未當作完整結果。共五個新案例保留不足預算與總時限失敗；31項相關測試完成含4個既有skip，另43項分層／頁面檢查通過。caa首輪4005項／1427.181s另發現自測AST指紋尚未更新；獨立基準提交僅重釘SMOKE_DIGEST，原相等斷言、metadata計數、handler／finally指紋、預算與skip不變；11項啟動契約通過後再完整重測，該失敗輪未放行。此為來源／fake時間證據，最終實際frozen安裝復原仍由最新Head CI確認，不能用過去成功或同名失敗代替。

新完整測試後保留原先完整結果與raw SHA；兩分支實際啟動重新驗證且均正常零退出、owned清理與端點移除。修正沒有改券商／金融寫入／GUI樣式或G3。新force graph all／staged完整，排程的9個與期限比較的2個新增定義都對應實際UID；共用smoke流程HIGH風險已記錄。runner276→282、run_smoke262→268、complete_smoke175→181的當前量測以獨立基準提交記錄；歷史列、限制值、舊斷言與skip不變。

## Final documentation integration audit — 2026-11-02

After the initial six-PR green gate, main PR #133 introduced two append-only
document conflicts. Preserve its historical packaging records and all original
M2 records, reorganizing addenda through normal stacked merges. Restore the
M2-1 wire-contract continuation retained by the connection branch as well. No
code, tests, fixtures, protected files or SDK pins change from the final
complete-suite and actual-startup sources identified above. All original
evidence remains valid within those explicit source scopes; this is not a new
program integration with the packaging implementation. GitNexus checks are
complete and LOW risk. The live PR Checks links above are the final delivery
gate for the resulting documentation heads; earlier literal head hashes remain
historical snapshots. Verify main and each stacked base for merge conflicts.

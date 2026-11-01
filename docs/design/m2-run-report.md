# M2 第一輪實作與驗證報告

報告時間：2026-11-02T00:24+08:00（Asia/Taipei）。

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
| M2-1 永豐連線 | [#132](https://github.com/yostar77612/mark-auto/pull/132) |4,000／1,436.847s；10F22E42skip；無新增失敗|離線35/35成功，heada62a110，run41323736469；Windows安裝流程為最終必要檢查；[最終Checks](https://github.com/yostar77612/mark-auto/pull/132/checks)|
| M2-2 手動模擬交易 | [#136](https://github.com/yostar77612/mark-auto/pull/136) |4,120／1,508.968s；10F22E42skip；無新增失敗|本報告所在最終Head一併驗證；[最終Checks](https://github.com/yostar77612/mark-auto/pull/136/checks)|

F／E／skip 為原始 unittest 結果。本機完整測試仍是非零 FAILED，不能描述成全部
通過；最終接受的是逐項核對後僅剩 main 既有 Windows 主機限制，且無新增失敗。

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
| M2-1 f77d2b0 |0／5.835s|設定儲存連線與鍵盤選帳戶0／6.661s；直接啟動0／3.621s|連線組合，resource_calls0，0 CA／委託|
| M2-2 32ad384 |0／5.952s|真實週日直接啟動0／3.669s，休市且0委託|0／7.417s；2次canonical送單鏈、2次place、1次amend、2次cancel|

最後一列的正向操作明確使用涵蓋的10月假市場時鐘及窄範圍 UI 時間讀取，沒有
改變真實 UTC 租約或期限，也沒有聲稱週日實際可交易。流程確認虛擬資金40000、
拒絕過期31秒的預覽、TMF診斷送單後已知未成交撤單，再完成一般假委託改價撤單。
五個真實危險確認框預設 Cancel；financial_query_calls0、CA_calls0、resource_calls1。
每個自有 LOCAL 程序正常退出，fake host thread join、research 釋放與端點移除均成功。
這些啟動檢查沒有匯入真實 SDK。

M2-1 完整測試來源為 f77d2b07f5ed24bd276f42c520b26efc033f6f49，原始日誌 SHA256：
`6c3f6e05332ab30fbf107039caa1873f94047d639bc1cf0d9011ab289a1af313`。
M2-2 完整測試來源為32ad38428e5da8959c18aad9fa403e15edbce55d，原始日誌 SHA256：
`393d28bd1c61cb5ac703594a853d87aaca7014cbc14cc191f02a056524e203f1`。後續僅整合驗證文件／報告，逐一確認非文件 Git blobs 相同。

## 失敗歷史與修正

- 未隱藏先前完整測試中的 frozen metadata probe 參數缺漏與兩個逾時案例；參數
  修正、main／分支原樣對照及完整重跑結果分別保留。
- #132 首輪 CI 的原始 IPC/CAS 案例暴露重複清理的端點競態，另三項為彙整失敗。
  兩個新回歸先 RED 再 GREEN；原始真實案例與清理回歸共12項／24.115s通過。
  其首輪 Windows 安裝三項工作已通過，最終修正 Head 仍獨立接受完整 CI。
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
皆通過；最終分別1154／1181個格式檔、1071／1094個語法檔，static finding0。
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

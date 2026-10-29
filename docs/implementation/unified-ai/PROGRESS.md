# AI 與多市場單一介面整合

授權：2026-10-26，將原 AI 研究與 ChatGPT 登入完整整合多市場介面，保留原資料、設定、登入，不動 Sitecore；實作與測試到通過。

工作樹：`C:\Users\mark.tsai\Desktop\markauto\unified-ai`，分支 `feat/unified-ai-workspace`，基準 main `159f308181d8d84f4db8e0964d8ee3e95383bf3f`。原主工作樹設計文件未提交變更與其他工作樹保留。

最新狀態（2026-10-26）：使用者已授權完成本機測試、建置與安裝驗證後推送及合併main，再驗證main CI／最新安裝包，最後整理跨電腦交接包。原28項權限補測已全數通過；本機新安裝版完整smoke、實際統一UI及原登入／資料保留檢查完成。已修正本機封裝誤收外部工具ICU DLL的問題，並補齊新入口的來源雜湊紀錄。接續執行PR完整CI與main發布驗證；下列歷史待測記錄以本文最後更新為準。

## 驗收追蹤

- [x] 一個主視窗，六工作區；AI 研究、原資料／結果／助理、登入入口不再啟動第二套視窗。
- [x] 共用一個原研究 session、原工作區、設定、登入引用、控制日誌與工作管理器；不複製／重設金鑰或 OOS 預算。
- [x] ChatGPT 連線狀態在新版可見，可開啟原登入／模型／額度／助理功能；錯誤、登出及登入失效仍經原控制器。
- [x] 完整原研究工具、已存候選與回測入口可用；研究和多市場策略之間明確說明相容性，不把研究結果冒充三市場交易證據。
- [x] 原研究工作與 v2 引擎可並行；停止、取消與關閉依原保護收尾，重啟資料保留。
- [x] 完整一般權限回歸無失敗，獨立網頁補測通過；架構／lint／語法通過；實際 Windows 來源 UI 檢查完成。
- [x] 28項原生檔案連結防護案例：使用者本次一次UAC授權，28項全過、0略過，來源未變。
- [x] 本機新安裝版完整smoke及實際UI／原登入驗證通過，舊payload與原資料保留。
- [ ] PR與main完整CI、最新發布安裝包下載／安裝重驗；完成後才整理跨電腦交接包。Linux及乾淨客戶端範圍分別記錄，不冒充通過。
- [x] 最終核對資料保留、記錄測試與外部限制；未做真實金融操作，未動 Sitecore。

## 起始狀態與已確認邊界

- 起始版本 `trading_runtime.show_legacy` 透過 `Popen` 另開整套研究介面；原v2自己不載入原登入狀態。本次已改為同視窗組裝。
- 原研究的 `desktop.run_gui/prepare_workspace` 已有單寫入者鎖、復原、RuntimeGuard、原設定與 remembered login；應重用，不可自行用新 bootstrap 替代。
- 原程式自動恢復後畫面已確認 ChatGPT 已連線；本次不直接讀取／複製憑證。
- codebase-memory 技能已讀；索引工具 Transport closed，改採限縮來源核對，不宣稱圖索引完整。

## 目前階段與下一步

組裝已實作：`desktop_app/research_bootstrap.py` 共用原 prepare_workspace/MainWindow/session；`desktop_app/features/trading/research_panel.py` 在六工作區內呈現原頁面，ChatGPT 狀態使用原控制器，研究工作狀態常駐，原深淺色偏好同步新版。`desktop.py` 一般入口與 --platform-v2 同指統一介面，舊 smoke/TLS/worker 路徑保留；新增明確測試用 --research-bootstrap，不自動恢復使用者登入。

已跑：最初新增8項整合測試14.988秒全通過；原多市場UI30項2.328秒全通過。新增CLI／非同步關閉測試後總11項。Ruff全庫check通過、689檔format通過；quality_gate 0 finding、分層gate 0 violation。

相關9模組152項：兩項原生安裝互斥在舊程式背景引擎仍存活時拒絕，其他150項無失敗（含1項原適用性skip）。後一次18項重驗仍遇同一全域互斥；唯讀程序核對找到先前使用者視窗14328留下的LOCAL引擎34348（原GUI關閉不等於引擎停止）。已透過公開IPC確認合成環境、0持倉、0委託，再正常SHUTDOWN_ENGINE成功；收據存工作樹旁 `unified-ai-audit-20261026/preexisting-local-engine-shutdown.json`。沒有強制殺程序、動Sitecore或放寬門檻。

原生guard＋新增整合18項37.534秒全通過，輸出 `unified-ai-audit-20261026/guard-unified-tests.log`。另原worker／完整桌面、啟動、新整合與真實LocalFacade UI流程54項153.885秒全通過，輸出 original-worker-unified-regression.log。後續新增全域研究取消的防重送與不送交易命令測試，新增整合現為12項。

ChatGPT全系列309項50.708秒：305通過、2項原適用性skip、2項原符號連結測試 WinError1314（權限不足），完整輸出 chatgpt-regression.log。測試內容未改；WSL唯讀查核顯示未安裝，不安裝系統工具、不改ACL／開發者模式／測試門檻。需要有符號連結權限的原生測試脈絡才能完成這兩項，不宣稱通過。

實際來源Qt視窗完成同視窗ChatGPT面板、AI策略頁面、六工作區、深色偏好及正常引擎／研究關閉。截圖與UIA在 audit/screens/source-embedded-*；此為來源程式、私有資料，不是安裝版或真實登入驗證。最初 QA launcher 使用Hidden造成Qt主視窗不可見，只結束已核對的私有無部位引擎與該測試UI（hidden-launch-cleanup.json），改用pythonw正常GUI。第二個可見QA視窗PID23828已從UI正常關閉，未碰原資料。

已根據畫面把頂部登入及研究狀態整併成兩行，實際一般入口來源GUI PID4700成功使用原bootstrap與原v2帳簿，沒有研究資料位置覆寫；自動恢復ChatGPT已連線，原已保存連線、模型與額度管理完整呈現在同視窗。截圖 source-original-login-restored／source-original-account-model-panel；未執行真實推論，沿用原狀態「推論尚未驗證」。原資料基準已保存為 audit/original-state-before.json，183研究檔＋4交易檔，憑證排除於任何hash／檢視之前。

新增同工作區滑鼠點擊返回、直接助理入口、助理不可停止時拒絕關閉等行為。初次助理fixture測試缺少原必需的模型發現結果而未送出，已明確注入離線fixture模型（沒有繞過原門檻）；重新15項57.273秒全通過，assistant-navigation-final.log。原生畫面發現同一左側工作區再次點擊不返回的問題，已增加itemClicked/itemActivated路由並補實際QTest滑鼠測試。最後另修正狀態文字換行與連線accessibleName，將於重新啟動核對。

PID4700與其本機引擎均已透過UI在0部位／0委託下正常關閉。資料比對找出原設定的window.height/width/y被內嵌視窗幾何寫回；已新增只保留既有window欄位（包括原本缺省）的EmbeddedSettings轉接，其他明確業務偏好仍交給原SettingsStore驗證／原子儲存。原設定before SHA與前輪備份完全相符，確認其他業務欄位皆未變後只修復window，原設定恢復逐位元組一致，未回復任何控制／額度／日誌。原183檔只有應用程式正常追加的logs/desktop-events.jsonl不同，研究資料與設定全數逐位元組保留。證據 settings-layout-correction.json、original-settings-and-data-after-correction.json。原v2兩個SQLite因合法啟動／關閉追加日誌而變動，未刪除或回滾。

新16項整合含設定保留與明確業務偏好保存，63.787秒全通過（settings-preservation-tests.log）。主程式名稱／組織／版本也統一為原MarkAuto識別。接著凍結source/context，執行全部普通使用者與固定19項符號連結權限分區；audit/run_permission_partition.py已從先前核對腳本複用，僅改ROOT指向unified-ai。新一輪19項尚未獲UAC授權，不得沿用上輪一次性授權。最後仍需新修正版原生畫面、完整回歸及可行的本機封裝；遠端不自動推送。

尚未宣稱任何新測試或新安裝版完成；不推送／合併本任務遠端分支，除非另有明確授權。


### 2026-10-26：普通權限回歸的修正與恢復

使用者選擇先完成其他測試；固定19項權限案例維持待執行，不啟動UAC。97f3406完整普通分區在原T11啟動測試卡住，該輪只能視為未完成，保留原log；已核對並停止唯一測試runner33036，再透過正式IPC關閉其私有LOCAL引擎37732。未動使用者引擎或Sitecore。

根因與修正：歷史程式呼叫desktop.main([])是既有復原／診斷契約，改路由使原測試接縫失效。保留這個可呼叫契約，增加公開launch入口供實際來源／安裝執行（__main__）使用；無參數及--platform-v2同樣開啟整合UI，既有smoke/TLS/engine參數原樣分派。沒有依測試環境或frozen狀態隱藏分支。研究視窗自行關閉後立即停用內嵌功能並排程關閉外框，避免資料鎖釋放後繼續使用。

其他大量候選pool profile子案例錯誤已確定為隔離TEMP路徑過長：long-profile-diagnostic.log保留WinError3原堆疊；短TEMP單例通過，後續使用workspace/t私有短路徑，不變更Windows設定、舊profile或測試。新增取消案例改驗證實際safety狀態與防重送，而非新增原服務patch observer，保留舊R1 inventory。新增測試模組改名test_desktop_unified_research.py以符合原CI桌面分組；只移動本次新測試，不刪既有案例。

中斷後資料再次比對post-interrupted-regression-data-audit.json：原183研究檔仍僅正常追加診斷log不同；研究資料、設定、工作區指標保留。v2仍僅兩個正常啟動／關閉的SQLite日誌變更，未回滾。

下一步：短TEMP重驗全部失敗模組、新17項整合及T11／復原；確認後凍結新來源、重新完整普通分區，繼續原生畫面與可行封裝。

修正後證據：startup-inventory-compatibility.log 35項9.704秒全部通過；short-temp-diagnostics.log 原故障清理／隔離／候選來源24項357.241秒通過（含1原適用性skip）；lifecycle-ui-regression.log 新17項整合＋原復原／圖表共38項94.626秒全部通過；release-timers-native-guards.log 補強研究關閉停止所有子定時器後，原桌面runtime／安裝互斥與新增釋放案例共44項17.692秒全部通過。Python3.11 AST656檔通過，Ruff check/format、quality0及architecture0。接續以固定新來源重新完整普通權限3590項（全3609項，19項仍待權限）。


### 完整普通分區 dbcabc8 與後續修正（2026-10-26）

完整普通分區3590項已實際跑完，source_unchanged=true，6 failures、0 errors、42原條件skip，證據partition-regular-final-dbcabc8.json/.log。此輪不是通過；完整保留失敗結果。固定19項權限案例仍未執行，也未啟動UAC。

修正六個失敗而不改歷史fixture／門檻：入口launch實作移至既有trading_runtime，desktop保留匯出與原七個定義；只明確提供隔離bootstrap時傳新增參數，保留舊CLI呼叫格式；新增desktop_research_runtime納入原文字掃描UI_MODULES（擴大覆蓋、不豁免）；診斷工具_write_json沿用既有replace_file的100ms同一次Windows原子取代重試，實際捕獲的PermissionError不再導致假失敗。未重跑任何交易、研究、預算或SQL交易。

額外補齊原選配網頁UI測試：獨立37個套件逐檔核對官方PyPI雜湊，紀錄ui-verified-wheels.json／ui-verified-windows.lock，保留既有Pillow13審核後覆寫。Windows網頁活動原案例60秒超時，堆疊顯示反覆spawn重載Streamlit；同原配置／960合成bars／15次試驗的CLI在30.545秒完成。新增tools/research_campaign.py重用原fixture CLI，先以admission pipe完成程序樹隔離，再允許工作，整體沿用配置預算，已知失敗正常收尾，未確認停止則保留輸入並阻止新工作。原研究引擎、G3八檔、producer profiles、OOS與不可逆預算皆未改。原網頁案例維持60秒與全部15次試驗／重開不消耗斷言；實際來源已通過。

獨立venv的Windows啟動器會增加一層父程序，原診斷所有權規則正確拒絕，因此保留原固定Python，僅透過隔離套件路徑執行選配UI profile；不改所有權規則。direct-runtime-paper-and-process-tests.log 35項36.191秒全過；final-unified-entry-web-regression.log 原網頁7項、新整合17項、入口／文字／安裝互斥共68項115.194秒全過；final-inventory-and-process-tests.log 18項6.287秒全過。新增程序案例驗證缺失admission、非零退出、超時與真實子程序清理、未確認停止保留輸入／禁止新工作、非法預算拒絕。

原生檢查發現小視窗助理送出區在畫面外，已調整自動捲動並驗證1000x700輸入與按鈕都在viewport內；保留原模型清單門檻，缺模型時改為具體提示，不冒充背景作業仍執行。DisabledHint明確綁定原研究host，避免內嵌後誤讀多市場外框；原三參數用法仍相容。原連線完成後只清除兩種舊generic running文字，實際失敗、未知結果與待對帳內容全部保留。literal-key-and-embedded-hints中發現原新測試使用self.config被R1識別成原服務observer，已改為專用campaign_options；沒有變更R1 fixture。新增文字掃描也捕獲原動態key，改為兩個literal ui_text呼叫，未放寬掃描。final-idle-status-and-model-hints.log 15項9.725秒通過。

實機來源UI已確認同一主視窗原登入自動恢復、連線／模型／額度管理、AI策略與助理入口、同工作區返回、輸入與送出區及正確缺模型提示。證據screens/final-source-*，最後final-source-assistant-model-prerequisite顯示ChatGPT已連線、就緒、官方模型清單前提，沒有送出實際推論。這是來源程式證據，不是新安裝包／正式CI。第三輪來源UI34852經UI正常關閉後，公開IPC確認LOCAL、0持倉、0委託並正常停止引擎；所有來源預覽已退出。state-final-ui-after.json再次核對原183研究檔僅診斷log正常追加，所有研究資料與設定逐位元組保留；v2僅兩個合法啟閉的SQLite日誌改變，未刪除／回滾資料。登入引用仍由原controller使用，沒有直接讀取或複製憑證。

下一步：固定來源，完整重跑普通權限分區及獨立選配UI profile。選配網頁框架會改寫__main__，分開完整模組執行，保留同一固定Python、來源及原案例／時限，避免影響後續spawn。不能把原條件skip當成通過；原始逐項理由與補測結果分別保存。正式安裝版仍是main159，本任務沒有遠端推送／合併／發布，沒有新的正式安裝包成功證據。

### 恢復後相容性修正（2026-10-26）

1816dd5完整普通分區3596項已跑完：3 failures、0 errors、42原適用性skip，來源未變；保留partition-regular-final-1816dd5.json/.log，不宣稱該輪通過。使用者說「繼續」後修正三個已定位問題：被動入口抽到根目錄trading_entry.py，避免匯入desktop即載入IPC；內嵌host與缺模型提示只在UnifiedResearch組裝時套用，原獨立研究介面四狀態語意保持不變；開發用網頁campaign adapter改為按下執行時才載入，保留原維護入口匯入契約。原測試門檻與歷史fixture未改，根目錄清單只增加新入口檔的明確項目。

passive-scoped-lazy-regression.log：129項57.673秒全部通過，包含原啟動、R7四狀態、T15維護與新整合案例。light-entry-real-worker-regression.log：55項146.551秒無失敗，含1項原適用性skip，涵蓋原桌面真實worker、smoke隔離、安裝互斥與多市場端到端UI。Ruff check通過、692檔format通過、659檔Python3.11 AST通過、quality 0 finding、architecture 0 violation。

整個quantlab/trading套件及G3八檔、歷史producer profiles均未改，避免入口重構改變研究來源身分。下一步保存本機提交、重新綁定完整來源指紋與測試清單，執行3596項完整普通分區及獨立原網頁UI7項。19項原生符號連結案例仍待權限，未啟動UAC；本次尚無新安裝包或遠端CI證據。

## 最新來源驗證結果與使用入口（2026-10-26）

程式來源提交 c809b8843c7e2a3c44296f06d34914abbf9e3539，完整來源 SHA256 為 1b2a50637df7055013a51f1d312dfb99e5236cb6fa94ffe265f4d7e3c8ec7068。後續只補文件，不改已驗證的程式、測試、依賴或封裝輸入。

| 驗證 | 實際結果 | 證據（工作樹旁 unified-ai-audit-20261026） |
|---|---|---|
| 完整一般權限分區 | 3596項，3554通過、42原條件略過，0失敗、0錯誤；1563.238秒，source_unchanged=true | partition-regular-final-c809b88.json / .log、逐項checkpoint |
| 原網頁UI＋Pillow相容性 | 7項全通過，32.415秒，無略過，來源指紋一致；覆蓋前列5項選配網頁略過 | optional-ui-final-c809b88.json / .log |
| Windows來源實際操作 | 原登入自動恢復、六工作區、原AI策略中心、研究助理、同工作區返回、輸入與送出可見、正確模型前提、正常關閉 | screens/c809b88-native-*.png / .json |
| 原資料保留 | 原183研究檔僅正常追加診斷log不同；研究資料、設定、workspace pointer逐位元組一致；v2僅正常啟閉的兩個SQLite日誌變化 | state-c809b88-after-native.json |
| 靜態檢查 | Ruff check / 692檔format通過，659檔Python3.11 AST通過；quality0、architecture0 | 恢復紀錄及本機檢查輸出 |

網頁補測工具最初誤將原test_ui的5項與獨立Pillow模組的2項當成同一模組，清單檢查在執行任何測試前拒絕；保留 optional-ui-preflight-v1.json 與原工具。改成完整載入兩個原模組後7項全過；沒有修改測試或60秒／15試驗門檻。這是工具清單錯誤，不是另一次程式修補。

來源原生預覽PID36488透過一般入口啟動，沿用原資料、原登入引用與深色偏好，未送出實際AI推論。實際連線管理仍標示「本機憑證具訂閱權限；實際推論尚未驗證」，沒有更改單次同意、模型發現、額度上限或帳戶。透過UI確認LOCAL、0持倉／0委託後正常停止引擎，畫面顯示「引擎已關閉」，再依原範圍確認正常關閉研究與外框；程序已退出，沒有遺留預覽視窗。原憑證於任何讀取／hash／複製之前排除。

使用入口：頂部「ChatGPT 已連線／連接 ChatGPT」開啟原登入、模型與額度管理；「策略」工作區提供「AI 策略研究」與「AI 研究助理」。研究工具列可切換原資料匯入、策略、回測、比較、紙上交易、行情、設定、登入與助理；按「返回多市場工作區」或再次點同一左側工作區即可返回。原研究取消與多市場停止新倉、關閉引擎、關閉介面各自保留責任。研究候選不會自動取得多市場部署資格，也不會觸發送單。

責任分層：Presentation保留純Qt研究面板與路由；根目錄desktop_research_runtime負責組裝既有研究session與多市場外框；原研究controller／SettingsStore／JobsManager仍是登入、偏好、作業與預算權威。新增EmbeddedSettings只阻止內嵌尺寸覆寫原獨立視窗幾何，明確偏好仍經原驗證保存。Domain、整個quantlab/trading引擎、G3八檔與歷史producer profiles均未改。

### 尚待驗證，不能宣稱全部通過

3615個不同案例中，最新一般分區通過3554個，獨立網頁補測再覆蓋5個不同案例，共3559個不同案例實際通過；Pillow2項是重覆覆核，不灌入不同案例數。其餘分類如下：

- 19個固定必測檔案連結案例未執行；另9個原案例因一般使用者無法建立符號連結而按原條件略過，合計28個需要Windows權限補測。沒有啟動UAC，不能沿用先前其他任務的一次性授權。
- 23個Linux／POSIX專屬案例在此Windows主機不適用，WSL未安裝；沒有宣稱Linux測試或新遠端CI成功。
- 5個原安裝／凍結程式harness專屬案例仍需新安裝包與隔離Windows環境。來源Qt檢查不能替代安裝版檢查。
- 真實ChatGPT推論仍需使用者核對官方帳戶、模型與單次同意後外部驗證；本次只證實原登入自動恢復及離線fixture行為，不宣稱真實推論成功。

正式封裝仍受packaging/build.ps1原完整回歸門檻保護，未繞過、不製造外部CI成功收據、不變更任何skip policy。原已安裝程式仍是main159；本次尚無新安裝包成功證據，不覆蓋原安裝或資料。後續遠端PR／合併／發布需另外明確授權。

已備妥僅28個原案例的一次性補測工具：audit/run_symlink_bundle_c809b88.py與permission-bundle-context-c809b88.json。原固定19項工具及manifest完整保留，沒有擅自擴大舊授權。新清單SHA256為919a507fbf216da08fa0289d9de7c0d53354dd859c973e1ee840b45b61a31a4a，工具SHA256為e5bf7250eaa1288046571e7d7f304b566de0baba37cde2d50e09e045095d7275。工具只接受privileged模式，先核對權限、固定案例、Python／SQLite與來源，再建立短路徑私有profile執行原案例，要求28項無略過通過並核對來源未變；不修改ACL、開發人員模式或防護設定。一般權限拒絕已實測，permission-bundle-ordinary-refusal.log，未建立任何fixture或啟動UAC。

下一個具體動作：取得這次28項UAC補測的明確授權，讓使用者親自在Windows提示核准，再執行固定清單並檢查逐項結果；未獲授權前維持待測。復原依工作樹旁RECOVERY.md與上述固定來源／清單接續，不重寫已完成工作，也不接觸Sitecore。

## 本機授權後的權限、封裝與安裝驗證

使用者先前暫不提升的決定，已由新的明確授權取代：允許一次UAC僅跑已備妥28項，且本機測試／建置／安裝通過後推送、合併本次整合到main，確認CI與最新安裝包後再做跨電腦交接包。UAC PID8160已結束；partition-privileged-approved-c809b88.json/.log記錄28項1.384秒全通過，0略過、0失敗、來源未變。未更改ACL、開發人員模式或防護設定，未擴大提升權限範圍。

本機凍結前獨立核對原packaging/desktop_regression.discover完整3615個ID與33個原適用性略過規則，合併實際一般分區、權限分區、獨立網頁補測後，3587個不同案例已實測通過，其餘28為原Linux／凍結harness適用性案例。local-build-regression-proof-c809b88.json是本機QA證據，不是CI收據，也不傳入工作流程收據驗證器。正式build.ps1原完整回歸與skip policy未放寬。最新封裝程式變更仍須PR與main完整CI對應確切提交驗證，不把先前來源指紋冒充新提交。

實際封裝smoke抓到QtCore載入失敗，17.17秒退出、未觸及原資料。比對DLL SHA及Analysis TOC確認：開發工具PATH讓PyInstaller誤收Codex內附Poppler的icuuc.dll／icudt78.dll，覆蓋Qt需用的Windows ICU介面；不是原登入或研究資料損毀。保留故障包至audit/frozen-failed-qt-path與MarkAuto-failed-qt-local-setup.exe，未刪除原安裝、Codex、Poppler或其他程式。修正只在PyInstaller分析時使用固定Python＋Windows的程序PATH，finally恢復原值；Qt授權排除與依賴鎖定皆照舊。另補trading_entry.py到build-manifest來源清單，原實際manifest測試增加該檔雜湊斷言，未改預期結果或降低門檻。

修正後：frozen-smoke-isolated-path-c809b88.json／receipt記錄真實凍結程式18.809秒完整通過；安裝後frozen-smoke-installed-local-c809b88.json／receipt記錄17.791秒完整通過，無開發工具PATH、無原資料或登入讀取，原7步、fixture、live disabled等條件成立。原smoke包含市場、歷史與walk-forward的額外證據，依原報告逐欄記錄，未把Linux或負面注入案例算成執行過。修正後原封裝／維護35項3.194秒通過，全部12個封裝PowerShell語法檢查通過；完整prepush以工作區內真實Python3.11編譯659檔、Ruff692檔、quality0通過。未安裝或替換原Python，未修改系統launcher。

本機安裝包SHA256 e53e25c0d3ec8732af677620082b5d942dc261224ad70d8f4ca2fe22a24eb353，以原Inno配方CURRENTUSER升級成功，exit0。實際payload為is-5OATL，local-installed-payload-verification.json逐檔核對1006個程式檔與清單完全一致；原is-C3E91執行檔仍在，SHA00876c7e0468a6bc7c85a73afa29440a7f8515eb3f9729764e1c5eee94cf7b96完全未變。沒有執行會移除原資料的乾淨主機／解除安裝harness，也沒有改其拒絕既有資料的保護；本機證據是保留資料的升級，乾淨安裝／解除安裝由真正的CI隔離環境驗證。

新安裝版PID35940完成原資料正常啟動、ChatGPT自動已連線、原帳戶與保存連線、深色偏好、策略AI入口、原AI策略中心、研究助理、同工作區返回、輸入／送出區與原模型前提的實際檢查，screens/installed-local-*保存PNG及UIA。沒有真實AI推論、模型刷新、同意勾選、額度變更或金融操作。確認LOCAL、0持倉／0委託後由UI正常關閉引擎，再正常關閉研究及外框。state-after-local-install-ui.json再次確認原183研究檔只有正常追加的desktop-events診斷log不同；所有原研究資料、設定與工作區指標逐位元組保留，v2仍只增加兩個正常引擎啟閉的SQLite日誌差異，未回滾或刪除。沒有直接讀取或複製登入憑證，Sitecore未碰。

下一步：保存封裝修正，推送本分支、建立PR並等待全部必要CI成功再合併；隨後核對main確切提交、完整CI與預覽發布安裝包，下載後驗證雜湊、安裝與功能，再整理交接包。現有主機登入必須留在原機；交接包不攜帶OS綁定憑證，目標電腦使用官方重新登入流程。

### PR98 第一輪 CI 與統一介面關閉契約修正

第一輪PR提交40ccc7f的35個Quantlab工作全部成功；Windows完整回歸實際跑完3615項，0失敗／0錯誤、33個原平台／選配略過，正式收據successful=true、validation_error=null。CI測試合併提交1aacd17的Git tree與分支40ccc7f完全相同。Windows安裝及升級smoke也成功，活動程式下升級／解除安裝正確拒絕；但後續生命週期收尾失敗，PR仍未合併。完整失敗證據保留於audit/pr98-failed-candidate與pr98-installer-failure.log。

根因是原生命週期假設關閉主視窗即結束全部程序；新版正常入口有獨立引擎與明確的關閉範圍確認，不能省略。原CloseMainWindow收尾遇到未確認視窗，再由清理階段WinError5覆蓋主要失敗。沒有以忽略WinError5、移除確認框、停止不明程序或增加時限修補。

原v1 test_installer.ps1及acceptance_process.ps1保留Git內容完全不變，歷史位元組鎖定測試全過。新增test_unified_installer.ps1及unified_acceptance_ui.ps1，安裝、smoke、活動升級／卸載拒絕、卸載與sentinel保護仍與原版一致，另以嚴格本機空帳戶範圍驗證正常UI操作：停止引擎、確認0持倉／0委託、關閉介面、確認引擎已關閉且0持倉，並等候所有建立時已證明所有權的子程序正常退出。整個流程合用原15秒，不增加任何預算；失敗前先保存主要診斷，後續清理仍會使整體失敗。這些UIA操作僅供隔離生命週期測試，未在使用者電腦執行；使用者電腦的實際畫面操作仍僅使用核准的computer-use工具。

新增的原生對話框查找只列舉保留之GUI程序的同一GUI執行緒，核對native owner鏈、Job與活躍程序身分；不搜尋桌面、不依PID採納程序、不注入鍵盤或強制停止。新增CI原生fixture驗證確切對話框可找、錯誤標題／owner／Job均拒絕，原15分鐘外層與每案10秒上限不變。純PowerShell政策測試實際驗證正常情況及LIVE、其他帳戶、非空持倉／委託、未停止引擎、未知階段均拒絕，不載入UIA或讀原資料。原生UI正向驗證仍待下一輪真實CI，未冒充本機已完成。

clean kit新增明確--unified模式，先核對candidate manifest中新版驗證器及UI extension雜湊，再產生既有穩定入口路徑的別名並記錄來源。原kit預設與所有既有預期值保留，沒有Python/Git需求或放寬完整性檢查。相關82項5.667秒全過、14個PowerShell腳本語法通過；接續保存修正並重新完整CI。此次只更動封裝驗證與測試，原應用程式、G3、研究／交易引擎、登入與使用者資料皆未變。沒有再次使用UAC、沒有在本機執行解除安裝，Sitecore未碰。
### 2026-10-26 CI lifecycle compatibility follow-up

PR98 head 4a86f4a exposed one shared original source-contract failure in five Quantlab lanes: `test_ci_retains_tls_and_unrelated_acceptance_gates` requires the preserved legacy lifecycle entry in the workflow. The legacy file itself was unchanged. Added a substantive pre-install CI step that executes all acceptance-process contract tests (including exact original/unified guard-section parity), then records SHA256 of both lifecycle scripts. No original test or expected value was changed. Targeted original AI-boundary 13 tests and acceptance-process 12 tests pass on the normal-user pinned runtime with isolated short TEMP. An initial tool-restricted TEMP attempt returned WinError 5; no application failure was inferred and no privileges, ACL or security settings were changed. Full pre-push and fresh complete CI follow; PR remains unmerged. Main and Sitecore are untouched.

The ff56fa4 Ubuntu 3.11 desktop-trading job exited 139 during the original `test_plan_campaign_uses_exact_provider_and_local_reconcile_never_enables_network` without a Python traceback. Its legacy test module, shared fixture and `desktop_app/shell/main_window.py` are unchanged from main, and prior same-runtime CI executions passed. Cause remains unproven; this is not counted as passed or fixed. Both workflows now enable standard Python fatal-fault stack diagnostics, preserving all tests, dependency locks, exact coverage and time limits. Fresh full CI is required rather than a failed-job-only retry. Evidence: `pr98-ff56-ubuntu311-desktop-job.log`, job 121542671283 / run 40314209485.

Strict coverage on 55dc3f1 correctly rejected the newly introduced Windows-only skip in the pure close-scope policy test. Downloaded all three UI producer inventories: all successful, with exactly this one unexpected skip; no legacy case failed. Removed only that NEW test's platform skip and execute the same 2-positive/7-negative policy cases through Windows PowerShell on Windows or PowerShell 7 on Linux. Historical skip fixtures and all original assertions remain unchanged. Windows PowerShell 12 acceptance tests pass; the same policy also passes under installed PowerShell 7 on Windows (engine compatibility only, not Linux evidence). Fresh full CI must prove Linux execution. The earlier Linux 3.11 crash did not recur in 55dc3f1's complete desktop-trading producer; diagnostics remain enabled and its original failure log is retained.

### Native snapshot performance within the original close deadline

Head 81d9121 passed all 35 Quantlab jobs and the complete Windows regression (3,619 cases, zero failures/errors, 33 unchanged applicability skips). Actual installation/launch/upgrade/refusal checks progressed to native close, where the first full descendant enumeration exhausted the original 15-second total close budget. The preserved worker trace identifies `Confirm-CloseIdentity` during `Get-OwnedCloseElements`, before settings selection; supervisor cleanup remained creation-owned and verified. Evidence is retained under audit `pr98-81d9121-candidate` and `pr98-81d9121-installer-failure.log`.

The unified fixture now requests one UI Automation property-cache snapshot for the bounded descendant inventory. Every descendant still has its cached PID checked; creation identity and the unchanged deadline remain checked during enumeration. Actions additionally recheck the selected live PID and enabled state. The 512-element cap, 15-second total including process drain, exact empty-LOCAL dialogs, original lifecycle guards and historical skip fixtures remain unchanged. Native CI extends its existing owned-dialog fixture with 128 real controls and executes the actual production collector, rather than a duplicate implementation. This native test is not executed on the personal host. Locally, related 82 tests pass (6.781s), 14 PowerShell parsers pass; complete fresh CI is required before merge. A test-runner importability preflight failed before executing cases; the corrected standard discovery run and both logs are preserved.

### Accessible navigation and early source Qt qualification

The b6542e1 installer still exhausted the original close deadline, but its preserved stack now reaches the shutdown-button lookup after successful settings selection. Qt 6.12.0's upstream accessibility implementation confirms that UIA Select selects a list cell without updating its current index. The application previously navigated only from current-row/click/activation events, so accessibility selection did not actually change the displayed workspace. A new behavioral regression reproduced the fault (`currentRow` 0 instead of 1) before the fix. Presentation now synchronizes a single selected workspace with current row and displayed page, including reselecting the workspace while an embedded AI tool is shown. It sends no financial commands and preserves the research session. All original assertions remain unchanged.

Validation: all 19 unified research tests pass (59.844s), all 42 trading UI/integration tests pass (48.011s), all 83 related packaging contracts pass (8.427s), and all 15 PowerShell scripts parse. Added an early ephemeral-CI gate using current source, the pinned private SQLite runtime, audited desktop dependencies, explicit private trading/research roots, and the same creation-owned UI close helper. Its 15-second close-and-drain budget and exact LOCAL scope remain unchanged; the new source-only supervisor is bounded to 120 seconds. It neither installs/uninstalls nor substitutes for the mandatory complete regression or actual frozen installer lifecycle. A cross-platform guard test verifies that this script refuses a personal host before loading runtime/GUI helpers. Current inventory is 3,621 cases; no original skip fixture or test expectation was changed. Full fresh CI remains required before merge.

Upstream evidence: https://raw.githubusercontent.com/qt/qtbase/v6.12.0/src/plugins/platforms/windows/uiautomation/qwindowsuiaselectionitemprovider.cpp and https://raw.githubusercontent.com/qt/qtbase/v6.12.0/src/widgets/accessible/itemviews.cpp (`Select`, `selectCell`). Prior failed reports and before/after behavior logs are retained in the audit directory. No UAC, credentials, system permission changes, old payload removal or Sitecore access was introduced.

### Visible dialog sequencing after early source qualification

The first early source-Qt run reached the second/interface confirmation, then failed while obtaining a current name from an invalidated UIA text element (HRESULT 0x80040201). Exact run 40327952587 and `pr98-caa4f18-source-ui` evidence are retained; no full regression/build ran after this failed early gate. The trace confirms progress beyond the previous settings-navigation failure. It does not establish a passed installer or a resolved native exception.

Qt's accessible button press uses asynchronous `animateClick`; a returned Invoke is not proof the previous modal has closed. The fixture now waits for that exact owned visible confirmation to disappear before continuing, without repeating the action. Native dialog discovery rejects hidden retired windows, preserves exact title/owner/thread/process proof, and still rejects ambiguity. Scope text comes from the same cached dialog snapshot, with a fresh native visible-dialog identity check immediately before confirmation. All waits remain within the existing 15-second total. The native CI fixture now retains a same-title hidden prior window, verifies only the visible dialog is found, then hides the active dialog and verifies no visible dialog is accepted. The early source gate also records whether its created application exited before cleanup and its numeric exit code on failure. No raw account text or credentials enter these diagnostics.

Locally, all 83 packaging tests pass (6.481s) and 15 PowerShell parsers pass. The native visibility/real Qt sequencing checks remain pending fresh CI. No original assertion, skip fixture, timeout, system permission or personal-host UI automation was changed.

### Separate navigation authority from the changing trading observation version

The caa4f18 Windows 3.11 real-IPC synthetic test found a genuine view-switch race: a source book observation could advance between the UI refresh and the legacy version-bound switch admission. An isolated diagnostic injected a real synthetic source-engine stop between those points and reproduced the unchanged original assertion. A proposed single UI retry was tested but remained insufficient under continuing updates; its uncommitted test draft is preserved in audit and was replaced before submission with tests of the typed boundary. No original test expectation was changed.

Added an immutable `ContextNavigationRequest` and a separate `ContextNavigationPort` in Application contracts. This request identifies the reviewed source context/epoch and explicit configured target context/environment/account. `CompositeFacade` admits it using the existing single selection lock, pending-mutation exclusion, epoch fence, target identity verification and durable metadata selection. Background journal revisions do not authorize or block this view-only operation. The historical `execute(UiCommand(SWITCH_CONTEXT,...))` path retains its exact version check; every financial action keeps its existing route, version, account and epoch admission. No retry or unknown-outcome replay is added. A stop during target opening still advances the epoch, cancels selection and remains on the original book. Presentation uses the new typed capability when present; compatibility facades retain the old route.

Actual evidence: the original three-environment IPC case now passes even with the same injected source-engine update (13.314s), without implicit connection or forbidden fake submit/cancel. Original Application context tests 8/8 and runtime client/registry tests 8/8 pass; trading UI/integration 42/42, original AI integration 19/19, source-profile/research worker/concurrency 12/12 and new typed-navigation UI cases 3/3 pass. The latter assert continuous version advancement, unchanged legacy stale-version rejection, exact source/epoch/target validation, no unknown retry and the original single financial-command route. All original assertions remain. The v2 producer digest naturally changes with these necessary Application source changes; its computation and historic result data are not rewritten. The eight G3 files, saved-candidate profile blocks, Domain risk/money code and database schemas remain unchanged.

The bcdd72f early Qt run reached both confirmations, then raced expected application/window destruction in a post-final-confirmation dialog query. After the final explicit validated interface confirmation, the fixture now returns to its caller's original zero-process-exit and owned-descendant-drain assertions. Intermediate confirmations still require the visible modal to disappear before any next action. The original 15-second total remains. Failure exit observations now use a separate artifact so the existing supervisor's failed-result summary cannot overwrite diagnostic facts. These native changes require fresh early source Qt and full frozen installer proof; none is claimed from component tests alone.


### Main integration and explicit-refusal cleanup race (2026-10-26)

PR #98 merged as c735234 after all PR gates and the exact candidate's local installation, original-profile GUI, smoke and TLS checks passed. The main tree exactly matches the tested candidate. Both retained prior payloads and the original 183 research / 4 trading files were byte-verified immediately after installation. Original settings, workspace pointer and research data remain unchanged after GUI use; only the ordinary research log and two local simulation journals changed. The main checkout fast-forward preserved the sole user-owned design draft byte-for-byte.

Fresh main CI then exposed an intermittent cleanup race in the existing real-IPC synthetic-context test: all behavior assertions passed, but background engine progress invalidated the teardown shutdown version. The engine correctly rejected the stale command; teardown recorded state_conflict and had to force-clean its owned test process. Failure log main-c735-windows312-trading-failed.log is retained. Windows aggregate checks correctly reject this matrix failure, including the 3.11 aggregate because its matrix dependency includes 3.12. No gate, expected result, skip list or timeout is relaxed.

The test-only cleanup now makes at most three fresh requests, exclusively after an explicit rejected state_conflict receipt and a new snapshot. Unknown transport outcomes, outcome_unknown, journal_failed and other refusals are never replayed; DomainError refusals are now recorded instead of being silently caught. Repeated conflicts remain failures. All original behavior assertions, the final empty cleanup-errors assertion and forced-cleanup failure remain unchanged. No application or financial-command implementation changes. Four added cases include a real local IPC host with an injected STOP_NEW between observation and shutdown: the original stale request must reject before a fresh request succeeds. All 12 module tests pass in 28.493s. Fresh complete CI remains required before merging this focused repair and publishing.


### Share the same cleanup policy with the second synthetic IPC fixture

PR #99 passed all 35 jobs and merged as 9c99999. Its fresh main run exposed the same observation/command race in a different original module: OwnedBrokerTagHostTests sent shutdown without checking its receipt, then asserted process exit. The preserved Windows 3.12 log reports exitcode None after the unchanged 10-second join. This is separate from the now-passing Qt client teardown.

Move the existing bounded, explicit-refusal-only test helper next to the shared synthetic host fixture in test_trading_runtime_context.py, and import it into the Qt client tests. Use it for this second fixture's ordinary shutdown/teardown. The existing stalled-query test already uses the same three-attempt explicit-conflict pattern. Preserve every original assertion and the original strict 3-second stalled-query/connection checks. Add an actual broker-tag synthetic IPC case that injects STOP_NEW before shutdown, requires the stale command to reject and the fresh one to succeed, and still requires zero exit within the original 10-second join. Production sources remain untouched. Fresh module tests and complete CI are required; prior failures remain retained.

Both related modules pass all 25 cases in 42.398s after the shared fixture correction; required prepush passes Ruff693 files, actual Python3.11 compilation660 files and static/credential0. A prior local attempt failed because a text-encoding error interrupted helper extraction before tests; both logs are preserved and it is not counted as acceptance.

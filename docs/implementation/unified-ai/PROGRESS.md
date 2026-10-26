# AI 與多市場單一介面整合

授權：2026-10-26，將原 AI 研究與 ChatGPT 登入完整整合多市場介面，保留原資料、設定、登入，不動 Sitecore；實作與測試到通過。

工作樹：`C:\Users\mark.tsai\Desktop\markauto\unified-ai`，分支 `feat/unified-ai-workspace`，基準 main `159f308181d8d84f4db8e0964d8ee3e95383bf3f`。原主工作樹設計文件未提交變更與其他工作樹保留。

## 驗收追蹤

- [x] 一個主視窗，六工作區；AI 研究、原資料／結果／助理、登入入口不再啟動第二套視窗。
- [x] 共用一個原研究 session、原工作區、設定、登入引用、控制日誌與工作管理器；不複製／重設金鑰或 OOS 預算。
- [x] ChatGPT 連線狀態在新版可見，可開啟原登入／模型／額度／助理功能；錯誤、登出及登入失效仍經原控制器。
- [x] 完整原研究工具、已存候選與回測入口可用；研究和多市場策略之間明確說明相容性，不把研究結果冒充三市場交易證據。
- [x] 原研究工作與 v2 引擎可並行；停止、取消與關閉依原保護收尾，重啟資料保留。
- [ ] 行為／故障／架構／lint／語法／回歸測試通過；實際原生 UI 檢查；可用時建置檢查。
- [ ] 最終核對資料保留、記錄測試與外部限制；未做真實金融操作，未動 Sitecore。

## 已確認

- 現況 `trading_runtime.show_legacy` 透過 `Popen` 另開整套研究介面；v2 自己不載入原登入狀態。
- 原研究的 `desktop.run_gui/prepare_workspace` 已有單寫入者鎖、復原、RuntimeGuard、原設定與 remembered login；應重用，不可自行用新 bootstrap 替代。
- 原程式自動恢復後畫面已確認 ChatGPT 已連線；本次不直接讀取／複製憑證。
- codebase-memory 技能已讀；索引工具 Transport closed，改採限縮來源核對，不宣稱圖索引完整。

## 目前階段與下一步

組裝已實作：`desktop_research_runtime.py` 共用原 prepare_workspace/MainWindow/session；`desktop_trading/research_panel.py` 在六工作區內呈現原頁面，ChatGPT 狀態使用原控制器，研究工作狀態常駐，原深淺色偏好同步新版。`desktop.py` 一般入口與 --platform-v2 同指統一介面，舊 smoke/TLS/worker 路徑保留；新增明確測試用 --research-bootstrap，不自動恢復使用者登入。

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

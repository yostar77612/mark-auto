# M1 自主決策紀錄

## 2026-11-01 03:34 +08:00 — CI 修復，M1-U

- 問題：上一輪只跑 changed-file prepush，漏掉完整基準鎖定測試。
  選項：放寬測試／修結構並精確重釘。依擁有者要求選後者；每分支完整 discover，
  與 origin/main 對照，最後讀遠端 CI，不把 changed-file 檢查當成完整驗收。
- 問題：四分支的全域字串 order 會碰撞。選項：保留獨立分支／改單一堆疊。
  依擁有者指定採 U→1→2→3，只用 merge，不重寫歷史。U 的十條新增記錄為2608–2617；
  catalog 註冊移至 `# Lane M1-U`，不改 ui_text 或 alias 規則。
- 問題：U1 的替代字元、U3/U5/U6/U9/U11 的真實畫面與樣式改變舊基準。
  選擇只重釘這些實際差異，保持舊 provenance 欄位、所有斷言與類別上限不變；
  基準更新另作 fixture-only commit，逐項說明。B11 實際是同一個新增 objectName，
  不需要調整類別限制。
- 檔案：strings/catalog.py、strings/m1_ui.py、08_REFACTOR_INVENTORY.md、
  desktop_catalog_main_6b78239.json、desktop_text_alias_map.json、
  download_auto_import_ui_delta.json、desktop_widget_names.json、
  ui_redesign_empty_presentation.json、test_desktop_catalog_split.py、test_b4_appearance.py。
- Graph：catalog.py upstream CRITICAL（129直接、162總參照），以全目錄、alias、
  畫面與完整測試驗證；unittest discovery 方法 UNKNOWN 由原始碼與 runner 引用確認，
  不當成沒人使用。沒有下載 FTS/vector 擴充。

## 2026-11-01 03:54 +08:00 — M1-U：完整基準相依項

- U9 將兩個紙上交易 advanced 勾選框改為 Qt 原生展開按鈕，tooltip 基準輸入數精確5→3；
  原五項 tooltip 測試、術語與可見性斷言全部保留。獨立 fixture-only 提交3ad742c。
- U5 的淨損益／夏普短表頭只改 table_values_e0e604f.json 第一張表兩個 header；
  cells、sort roles、其餘兩表不變。新增 saved_results_empty 另以明確一名稱 delta 准入；
  舊六個 download 名稱與原 historical digest 保持原值，未盲目重釘歷史 hash。
- 選項：重錄 r7_base／另加 U 專屬精確 delta。選後者，m1_u_ui_delta.json 逐列釘選焦點與
  四種 refresh 狀態；原 Counter 數量、八個結果快照、呼叫順序、錯誤與畫筆斷言不變。
  Windows 原像素比對實測通過，保留既有像素 pin，不改未觀察到的基準。
- 新增基準 import 使 R7 兩個 observer 定位72→73；原歷史投影及174筆 guard／hash 全留，
  tests/page_services_inventory.py 在整個投影之後套用完整列與數量的 M1 定位差異，
  test_page_services_r1 仍對全部 inventory 做精確相等。此 helper 在整合圖譜為HIGH，
  直接影響清冊測試與 replay 工具；已讀三個呼叫者並以原完整斷言驗證。
- 相關原閘門73項、相鄰47項通過。完整 discover 與遠端 CI 仍須完成，不能據此宣稱全綠。

## 2026-11-01 04:55 +08:00 — M1-U：第一輪完整測試的四項新失敗

- 第一輪完整 discover a210a99：3766項、1524.589秒，14 failures／27 errors／42 skips。
  相對 main 有四個新失敗，因此沒有推送，後續完整測試排程自動停止。
- U3 明確要求比較頁可見；U4 明確要求閒置狀態不重複。選擇獨立 baseline-only 提交b10ea42，
  精確更新兩項舊呈現期望，保留所有七頁身份、重排／快捷操作、原 ready 值、隱私、取消與提示斷言；
  另加 visible-idle／hidden-ready 的正反檢查。兩個原模組六項測試通過。
- 真實功能問題：install_page_help 把七個原先隱藏的設定說明全部移至標題，導致14按鈕超過8。
  選項：提高限制／恢復勾選框／單一說明入口。選第三個，不改8的上限，也不退回舊 advanced 元件。
  標題一個 InstantPopup 入口保留七個原 objectName、accessibleName、tooltip 與全部文字。
- 首版選單功能測試通過但截圖只有33px窄格；保留修復歷史，以後續提交修正，不改寫歷史。
  小問號維持原樣式，完整說明改用480px可換行 PlainText 標籤與 focus proxy；實際讀圖531×474，
  文字完整。新測試檢查幾何容納、七主題鍵盤巡覽、Escape 與可存取描述，不只檢查 text 值。
- 獨立 fixture-only 更新：settings_help_topics 一個新名稱、設定預設按鈕14→8、R7精確焦點／
  四狀態差異、PageIdentity 四個 observer 定位各+1。原 historical digest、r7_base、圖表像素、
  各種上限與斷言不變。修改後135個相關測試全部通過；接著重跑完整 discover。
- 來源在隔離 worktree 完成後 cherry-pick（1b8394f、db5538b），父層之間仍只用正常 merge。
  首次增量圖譜缺 UID 的 CRITICAL 寬泛結果保留為限制，強制離線重建後再完整偵測，不下載擴充。

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

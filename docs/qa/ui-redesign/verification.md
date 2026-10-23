# 最終驗證紀錄

## 環境與隔離

- 工作區：C:\Users\mark.tsai\Desktop\markauto\ui
- 分支：ui/simplify-desktop；基底：567dbb23d611303d5a26077360640563b794ae3f。
- Python：C:\Users\mark.tsai\Desktop\markauto\.repo\.venv\Scripts\python.exe，3.13.11。
- PySide6 6.12.0、SQLite 3.54.0、Ruff 0.16.10；未安裝或變更依賴。
- PYTHONUTF8=1、QT_QPA_PLATFORM=offscreen。
- LOCALAPPDATA／APPDATA／TEMP／TMP 指向工作區內新的 .tmp-ui 測試目錄；每項流程另建 disposable workspace。
- 未讀取使用者憑證或執行真實模型請求，未操作真正的 MarkAuto 工作區。

下列 `PY` 代表以上 Python 完整路徑。每個測試模組均使用
`PY -m unittest discover -s tests -p <檔名>` 執行；沒有刪除、略過或放寬安全測試。

## 本次驗證

| 指令／範圍 | 結果 |
| --- | --- |
| `PY -m unittest discover -s tests -p 'test_ui_redesign_*.py'` | 45 項通過：資料／結果 10、策略 12、紙上／設定 7、偏好 11、預覽／命令面板 5；44.374 秒。 |
| `test_backtest_summary_u4.py` | 8 項通過；已載入結果時條件收合，展開後仍能修改同一表單。 |
| `test_compare_table.py`／`test_compare_equity_f2.py` | 各 6 項通過。 |
| `test_data_gaps_f1.py` | 8 項通過。 |
| `test_accessibility_walk.py`／`test_scaled_layouts.py` | 13／4 項通過，包含真實鍵盤、獨占任務選取、焦點、1024 邊界與放大字型。 |
| `test_paper_stop_a1.py`／`test_paper_stop_u6.py` | 8／13 項通過。 |
| `test_replay_b13.py` | 12 項通過，期限與原有 pacing 不變。 |
| 其餘紙上／設定保護 | A2 撤單 10、B2 鎖單 16、C6 分頁 11、U9 時間軸 9、C3 面板 4、F5 備份 18、自動備份 8、設定 3、診斷 11 項通過。 |
| `test_preferences_u8.py` | 11 項通過；另新增的 11 項偏好測試確認掛載、legacy 還原與損毀容器均不寫檔。 |
| `test_desktop_text_aliases.py`／`test_desktop_strings.py` | 9／6 項通過；舊字串 UTF-8 位元組不變，新字串完整註冊且沒有未使用草稿鍵。 |
| `test_header_c1.py`／`test_page_services_r1.py` | 6／15 項通過；相同控制項搬移，單一狀態與服務契約保留。 |
| `test_function_lengths.py` | 2 項通過；G3 鎖定來源雜湊未改。 |
| `test_repo_layout.py` | 29 項通過；只新增已明列的 Preview UI.cmd 根目錄入口。 |
| 最終合併重驗：服務、文件分層、G3、文字 alias／catalog、倉庫結構 | 71 項通過；13.991 秒。 |
| `PY tools/ui_redesign_preview.py --capture .tmp-ui/audit-complete` | 有資料 120 組原生畫面，0 裁切／重疊／橫向捲動。 |
| 同上加 `--empty` | 空白 120 組，0 裁切／重疊／橫向捲動。 |
| `ruff check .` | 退出 0。 |
| `ruff format --check`（修改的 Python 檔） | 退出 0。 |
| Python 3.11 AST 語法掃描全部追蹤 Python | 508 檔、0 失敗；以 feature_version=(3,11) 檢查。實際 runtime 為 3.13，沒有冒充 3.11 runtime 測試。 |
| `PY tools/quality_gate.py` | 退出 0，0 finding。 |
| `git diff --check` | 退出 0。 |

完整流程的核心 UI operations 實際執行，包含未達資格仍拒絕紙上選用，以及真正 journal 的暫停、停止、重開保護。

## 失敗、環境限制與重驗

第一次完整 desktop shard 執行 429 項，結果為 9 failures、17 errors、8 skipped，沒有將此輪寫成通過。
本次造成的 widget inventory、字串註冊、任務按鈕 role 及新捲動行為斷言已修正並獨立通過。
其餘 WinError 5／10013 來自沙箱阻擋硬連結、junction 或 loopback TLS；以相同隔離資料在允許該本機操作的環境重驗：

- desktop_history_smoke、desktop_market_integration、desktop_market_smoke、desktop_smoke_isolation、desktop_tls_smoke、market_history_ui 全部通過。
- desktop_smoke_terminal 9 項通過，仍使用原 40 秒全域期限；失敗不能留下成功報告的斷言沒有變動。
- 安裝 mutex lifetime 仍失敗。全新 Python 在匯入專案前已探測到既有固定名稱 mutex；隨機 GUID 的對照 mutex 則能正常建立、關閉。直接載入 `567dbb23` 原測試也於同一行失敗，runtime／mutex 實作與測試三檔 Git blob 完全相同。未關閉其他程式、清除 mutex 或修改保護。

第二次以允許上述本機操作的環境完整重跑 desktop shard：429 項、402.510 秒，
420 通過、8 項原有條件略過，僅 installer mutex lifetime 1 項失敗，沒有其他 error。
未將這一輪記為全部通過，也未更改該測試或 runtime。

額外 registry parity 測試（6 項）最初重驗有 3 個失敗 subtest。
使用完整 `567dbb23` 快照、相同 Python／隔離環境／本機權限與同一 runner 對照：
基底 22.123 秒有 1 個失敗，改版 24.442 秒有 2 個失敗；改版這次 golden parity 本身通過。
失敗操作會游移，均觀察到既有原子檔案替換的 `WinError 5`，包括 campaign、history、
walk-forward 或還原的暫存檔替換。這證明不是改版獨有的乾淨基線，但不表示原先每個
subtest 都一一穩定重現。未改 registry 測試、golden、檔案核心或重試條件，仍記為本機限制。

原始紀錄保留於本機 `.tmp-ui/desktop-core-final.log`、`new-redesign-final.log`、
`final-gates-tests.log`、`mutex-current-diagnostic.log`、`mutex-baseline-567dbb23.log`、
`registry-final-unrestricted.log`、`registry-baseline567-unrestricted.log` 及
`registry-current-matched-unrestricted.log`。沒有將失敗包裝成通過。

`powershell -File tools/prepush.ps1` 被主機執行原則拒絕，未變更執行原則或繞過它；以上逐項執行其 lint、語法與 static gate。
完整 `ruff format --check .` 僅指出未修改的 docs/adr/0006-strategy-intent-pipeline.md，符合 CONTRIBUTING 已記錄的 Windows CRLF 限制；沒有正規化該文件。

真實 ChatGPT 推論、官方行情及實體螢幕／多螢幕的外部驗收未宣稱通過；本次明確以離線替身、合成資料與原生離屏元件驗證。
未建立 Release、標籤、安裝或合併 PR，正式驗收分數仍為 230/300。

## 結構與獨立審查

使用 codebase-memory 的 markauto-ui-redesign 索引，root 正是本工作區。
修改前 MainWindow 的 create_window／run_gui inbound 標示 CRITICAL，保留既有建構、作業與關閉入口並回歸。
提交前 detect_changes(scope=files) 完整列出 88 個變更檔，changed_has_more=false；seed_symbols=0，未把它稱為完整符號影響證明。
coverage 沒有記錄 UI Python 缺口，但 freshness=metadata_changed，所有修改的來源均另由主代理及分區代理閱讀核對。
其餘索引 partial 位於舊 HTML 與未修改的 packaging PowerShell；tools 子樹被排除，預覽與截圖工具均另行完整讀取、測試。未宣稱全倉圖完整。

三名分區代理交叉審查並追蹤修復 JSON 摘要覆蓋不一致、點子取消入口隱藏、初始偏好寫入、隱藏匯入焦點與預覽更新連網五類問題。
未發現資格、預算、OOS／holdout、停止或恢復語意放寬。原長路徑修復工作區的 35 項未提交變更保持原樣。

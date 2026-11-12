# M5 族群看盤 — 最終報告

日期：2026-11-09 ～ 2026-11-12（M5 無人值守一次做完；11-11 至 11-12 補上安裝驗證、自動連線與族群讀取修正）
規格書：[docs/design/m5-sector-board.md](../../design/m5-sector-board.md)（含每階段「實作決策」）

## 1. 一句話結論

「市場」頁新增「族群」分頁：產業＋17 個內建概念族群排行、成分股（領頭羊、量比、內外盤比）、個股 K 線／五檔／成交明細、
族群爆量警訊（A）與主動買賣持續警訊（B，自動監控前 3 名族群）、族群編輯、警訊參數設定。
全程只用唯讀「行情連線」，沒有任何下單／交易程式碼，M5 模組也不 import 交易模組。
**0.4.0 已安裝並在安裝後的程式上實測「族群」分頁、編輯族群、警訊設定（見 §4）。實機即時行情數字（訂閱上限、全市場快照耗時、`tick_type` 實際值）尚未實測，需你確認（見 §5）。**

## 2. 各階段 PR

| 階段 | PR | 內容 | 狀態 |
|---|---|---|---|
| 規格 | [#193](https://github.com/yostar77612/mark-auto/pull/193) | 規格書 | 已合併 |
| M5-0 | [#194](https://github.com/yostar77612/mark-auto/pull/194)、[#195](https://github.com/yostar77612/mark-auto/pull/195) | 實測工具 `tools/m5_market_probe.py`、保守預設值、inventory 修補 | 已合併 |
| M5-1 | [#196](https://github.com/yostar77612/mark-auto/pull/196) | 五檔／成交明細、`Tick.side` 內外盤、看盤分頁右側面板 | 已合併 |
| M5-2 | [#197](https://github.com/yostar77612/mark-auto/pull/197) | 目錄 v2（產業別）、快照輪詢、族群統計、「族群」分頁三欄 | 已合併 |
| M5-3 | [#198](https://github.com/yostar77612/mark-auto/pull/198) | 族群名單 JSON、編輯對話框、內建名單版本合併、壞檔退回 | 已合併 |
| M5-4 | [#199](https://github.com/yostar77612/mark-auto/pull/199) | 每分鐘統計、警訊 A、警訊條、警示紀錄整合、參數設定 | 已合併 |
| M5-5 | [#200](https://github.com/yostar77612/mark-auto/pull/200) | 監控名單（前 3＋5 分鐘保留）、訂閱預算、警訊 B | 已合併 |
| M5-6 | [#201](https://github.com/yostar77612/mark-auto/pull/201) | 版本 0.4.0、最終報告 | 已合併 |
| 穩定性 | [#203](https://github.com/yostar77612/mark-auto/pull/203) | 請求佇列改為純 Python（無模組層級 QObject）、M5 測試結束時刪除所有元件 | 已合併 |
| 自動連線 | [#204](https://github.com/yostar77612/mark-auto/pull/204)、[#205](https://github.com/yostar77612/mark-auto/pull/205) | 設定頁「啟動時自動連線（永豐模擬環境）」勾選（預設關）；修正測試留下可見視窗 | 已合併 |
| 族群讀取修正 | [#206](https://github.com/yostar77612/mark-auto/pull/206) | `ContextIpcFacade` 轉送 sector 請求（安裝後發現的真實缺陷，見 §4） | 已合併 |

每個階段都有獨立 QA subagent 依規格驗收（M5-1：1 輪；M5-2：2 輪；M5-3／4／5：各 1 輪，皆找出缺陷並已修復；修復皆附回歸測試）。
GitHub CI 全綠才合併（#194 例外，見 §6）。

## 3. 驗證

- 單元／整合測試：M5 新增測試檔 `test_m5_order_book`、`test_m5_sector`、`test_m5_groups`、`test_m5_alerts`、`test_m5_monitor`（共 170 個）。
- 警訊 A、B 都有 **golden-file 重播測試**（`tests/fixtures/m5_sector_replay_golden.json`、`m5_monitor_replay_golden.json`），預期觸發時間由人工推導，QA 另行獨立推導確認。
- 完整 `python -m unittest discover -s tests`：本機 6304 個，M5 相關無失敗；另有 12 個失敗在 M5 之前就存在（Windows 原生程序類測試，非本次變更）。
- ruff check／format、`tools/check_layers.py`（0 發現）、`tools/check_trading_architecture.py`、repin 後的 baseline 全部通過。
- 介面截圖（離線 fake facade、真實 `TradingWindow`）：
  - 五檔／明細：[1366×768](../m5-1-orderbook/1366x768.png)、[1920×1080](../m5-1-orderbook/1920x1080.png)
  - 族群分頁：[1366×768](../m5-2-sectors/sector-1366x768.png)、[1920×1080](../m5-2-sectors/sector-1920x1080.png)
  - 警訊條與列閃色：[1920×1080](../m5-4-alerts/sector-1920x1080.png)
  - 監控標記與內外盤比：[1366×768](../m5-5-monitor/sector-1366x768.png)、[1920×1080](../m5-5-monitor/sector-1920x1080.png)

## 4. 安裝狀態與安裝後實測

- **已安裝 0.4.0（commit `316e1d61`）**：預發佈 `desktop-preview-43215889664-2`，安裝檔 SHA256 與 `SHA256SUMS.txt` 相符，靜默安裝後以 `build-info.json` 確認版本與提交。
- **安裝後第一次實測就發現缺陷**（先前的 0.4.0 版本 `e0664a08`）：「族群」分頁每次重新整理都顯示「族群資料讀取失敗」。
  - 根因：桌面程式實際使用的 `ContextIpcFacade.request` 只接受 `series`、`alert`，不接受 `sector`、`sector_groups`、`sector_params`，所以看板、群組、設定三個呼叫在送到引擎前就丟出 `TypeError`。族群元件測試用的是假 facade，從來沒走過這一層，所以 CI 全綠仍漏掉。
  - 排查方式：對使用者實際運作中的引擎重播請求，確認引擎、線路編碼、dispatcher 都正常，只有桌面 facade 層失敗。
  - 修正（#206）：欄位改為整批轉送（`**optional`），日後 `IpcFacade` 新增欄位不會再被漏掉；新增三個經由 `ContextIpcFacade` ＋真實 dispatcher 的測試（沒修正時三個都以同一個 `TypeError` 失敗）。獨立 QA 確認變更最小、無其他呼叫受影響、也無同類漏洞。
- **修正後在安裝好的 0.4.0 上實測**（截圖在 [installed/](installed/)）：
  - 「族群」分頁離線時顯示正確提示「行情未連線；請先在『設定』連線行情」：[截圖](installed/sector-fixed.png)
  - 「編輯族群」列出內建概念族群與成分股：[截圖](installed/sector-edit-groups.png)
  - 「警訊設定」載入全部參數（快照 10 秒、A 倍數 3.0、冷卻 10 分鐘…）：[截圖](installed/sector-alert-settings2.png)
  - 設定頁「啟動時自動連線（永豐模擬環境）」存在於連線面板，預設未勾選：[截圖](installed/settings-autoconnect2.png)
  - 總覽、策略、市場、交易、績效、設定六頁走完無錯誤對話框（`tools/ui_smoke_installed.ps1`）。
- **尚未實測**：行情連線後的即時資料（見 §5）。測試期間沒有連線、沒有改任何設定。

### 發佈過程的 CI 事件（供日後參考）

- 發佈要求 main 同一提交的閘全部成功（跳過也算失敗）；用 `gh run rerun --failed` 會讓覆蓋率彙總找不到其他分片產物，一律改用完整重跑。
- 2026-11-11 GitHub 的 Ubuntu 26.04 映像曾連不上 Ubuntu 鏡像（apt DNS 失敗），所有 Linux 任務失敗約 2 小時，等恢復後重跑。
- Windows 分片多次碰到 15 分鐘上限或 PowerShell 啟動逾時，皆以完整重跑解決。
- 「安裝回歸」曾因 `test_auto_connect` 留下可見的 `TradingWindow` 而失敗（`QTest.mouseMove` 在真實桌面會移動真滑鼠，離屏平台看不到）；#205 改為每個測試一個視窗並在結束時刪除。
- #206 在 Windows 3.12 的 `remaining` 分片連續 5 次在第一個 `MarketTerminalWidget` 原生崩潰，而 main 能過；唯一差別是 PR 新增的測試檔。把測試搬進 `test_runtime_context_client_v2.py`（trading 分片）後一次就綠。這代表潛伏崩潰仍在（§7）。

## 5. 待你實機確認

1. **行情連線後看畫面**：開「市場 → 族群」，確認排行、成分股、五檔、成交明細在即時行情下正常；產業分類是否都有名稱（找不到的會顯示「產業 XX」）。
2. **實測數字**（M5-0 因規則禁止無人值守時讀取憑證而未連線）：執行 `python tools/m5_market_probe.py --mode live --rounds 3`，把 `build/m5_probe_result.json` 的
   訂閱上限、全市場快照每輪耗時、`tick_type` 實際值、`category` 分佈回報給我。目前採保守值：`subscription_limit`＝20、快照每 10 秒、B 類依剩餘額度降級。
3. **`tick_type` 方向**：規格假設 1＝外盤、2＝內盤（SDK 存根只說明為 int）。若實機相反，內外盤比與警訊 B 方向會顛倒，需調換 `tick_side()`。
4. **警訊門檻是否太吵／太鈍**：預設 A 3 倍且 ≥2,000 萬、B 連續 3 分鐘且 ≥1,000 萬與 2 倍；可在「警訊設定」調整，第一週依實際觸發數調。
5. **自動連線**：設定頁勾選「啟動時自動連線（永豐模擬環境）」後，下次開程式會自動連線。只會自動連**永豐模擬**目標；你目前存的連線環境是「正式環境」，會被略過（要用請先把目標改成模擬環境）。連線失敗只提示一次，不重試。
6. 「領頭羊」時間目前取「快照首次看到漲停」那一輪的最後成交時間，未接入掃描器漲停事件（規格已記為決策）。

## 6. 自主決策與理由（完整清單見規格書「實作決策」第 1–26 項）

遇到規格沒寫或互相矛盾時，一律依「唯讀、fail-closed、不影響既有功能」決定，並寫回規格書。主要決策：

- **M5-0 不連線**：規則禁止無人值守時讀取帳密，所以只提供唯讀探測工具與保守預設值（上限 20、快照 10 秒），不阻塞後續階段。
- **快照輪詢不疊加**：上一輪未完成就跳過，不超過行情查詢上限。
- **五檔佔訂閱名額**：名額不足時優先保留 Tick，五檔降級並顯示原因。
- **有效成分股＝快照有正成交價者**：SDK 沒有可靠的停牌旗標；族群只計 4 位數字普通股（排除 ETF、特別股、權證）。
- **領頭羊時間**取「首次在快照看到漲停」的那輪，隔日重置。
- **族群設定放在族群分頁的對話框**，不混入「管理規則」；警訊類型 `SECTOR_BURST`／`SECTOR_FLOW` 不可建立規則。
- **名單檔損毀**：原檔保留為 `.bad-<時間>`，改用內建名單並重建；寫檔失敗時記憶體維持原狀。
- **訂閱優先序**：指數 ＞ 選定個股 ＞ 自選 ＞ B 類監控；監控只釋放自己加的訂閱；共用個股只佔一檔。
- **非同步請求改為佇列傳遞**：CI 出現偶發 Qt 崩潰，改成純 Python 執行緒＋GUI 執行緒計時器取回結果，不在工作執行緒釋放 Qt 物件（見 §7）。
- **內聯樣式一律不用**（repo 掃描禁止）：閃色與警告色改用 QPalette。
- **舊版面檔相容**：只補齊選用面板 `orderbook`，其他缺漏或多餘面板仍整檔退回預設。
- **字型**：監控標記用「●」（微軟正黑體缺「◉」字形會顯示成方塊）。

## 7. 已知問題與未完成項目

- **偶發 Qt 崩潰（未找到根因）**：CI 的 Windows 3.11／3.12 與 Linux 分片曾偶發 access violation／segfault，位置不固定（`MarketTerminalWidget` 建立、`help.py`、`window.py` 等），本機無法重現（含 932 個測試、極積極垃圾回收）。已把請求結果改成佇列傳遞並刪除測試元件，但未能證明消除；#206 顯示改變分片內容就能讓它每次觸發或消失，建議之後專案另開一項處理（例如在 CI 加完整原生堆疊或逐模組二分）。
- **自動連線只涵蓋永豐模擬**；正式環境不會自動連線，這是刻意的（正式下單仍停用）。
- **測試覆蓋教訓**：族群元件只用假 facade 測試，漏掉真實 facade 層。之後凡是經由 `ContextIpcFacade` 的新操作，都要有一個走過它與真實 dispatcher 的測試。
- 冷卻狀態已跨重啟保存（2026-11-13 補上）：每個族群／方向當日最後一次警訊時間寫入 `sector_minutes.sqlite3` 的 `sector_alert_marks` 表，重啟後同一冷卻期內不會重複警訊；分鐘基準同樣從資料庫還原。資料庫無法開啟時退回只存在記憶體。
- 領頭羊時間未接掃描器事件；產業族群為官方分類（`Contract.category`），實際代號分佈待實機確認。
- 1366 寬時排行表與成分股表以橫向捲動避免欄位被截（1920 寬完整顯示）。
- 第二階段項目（熱力圖、5 日成交比重比較、族群歷史回放）依規格不在本次範圍。
- 本機 Windows 上極少數 `os.replace` 被掃毒／索引短暫占用（已加重試）。
- 過程中的失誤：#194 在 CI 完成前就合併（用管線時看不到失敗），導致 main 因缺少 inventory 列而短暫失敗，由 #195 修復；之後一律等所有檢查完成才合併。

# 桌面 UI 簡化改版驗證

本輪從已提交的 `567dbb23d611303d5a26077360640563b794ae3f` 建立
`ui/simplify-desktop`。獨立工作區為 `markauto/ui`；原 `.repo` 的
`fix/windows-long-path-storage` 分支及其 35 項未提交變更保持原樣。
正式驗收分數仍為 230/300，本文件僅記錄本輪工程驗證。

## 開啟新介面

在 UI 工作區雙擊 **Preview UI.cmd**。它會沿用原專案已安裝的 Python/PySide6，
建立新的暫存工作區，預載明確標示的合成資料和一份真實離線回測報告。
結束後移除這次預覽資料，不會取代安裝版。

亦可從此工作區執行：

```powershell
& '..\.repo\.venv\Scripts\python.exe' tools/ui_redesign_preview.py
```

加 `--empty` 可檢視無資料狀態。預覽會隔離 LOCALAPPDATA、APPDATA、TEMP、TMP
與工作區；帳號、模型、網路下載及 AI 作業在建立 worker 前拒絕，更新檢查與
版本連結也停用。預覽不自動登入、不發出付費請求。正式啟動入口仍為 desktop.py。

## 完成範圍

| 區域 | 改版後的操作 |
| --- | --- |
| 全域 | 精簡頂部、研究模式與實盤停用、真實作業和連線狀態；時鐘不常駐；主題／隱私集中設定。 |
| 導覽 | 資料 → 策略中心 → 回測結果 → 紙上交易；市場與設定保留入口。比較從結果頁與 Ctrl+4 進入，原七頁身分和 Ctrl+1–7、Ctrl+K、F5、Esc 保留。 |
| 資料 | 本機／官方行情與 Tick／下載／合成示範分區；必要合約與可選篩選分開；保留交易日曆，匯入結果顯示真實商品、週期、時間、筆數和警示。 |
| 策略 | 找點子／AI 研究／自行設定三種任務；模型與同意項目同步既有連線面板；JSON、手動回應、fixture、歷史進階收合；候選摘要與拒絕原因先行。 |
| 進階驗證 | Walk-forward 有獨立入口，沿用既有五步精靈、預覽、不可逆同意與資格證據。 |
| 回測 | 執行前顯示實際資料、策略、範圍及成本，摘要遵循與作業相同的 JSON 覆蓋規則；結果載入後先呈現指標與曲線，可展開條件再次執行。 |
| 結果／比較 | 成交、統計、圖層及完整資料收合；結果可加入比較、選用、重開及開啟已驗證報告資料夾。既有 CSV、結果 JSON 與 SOURCE.txt 不重算、不改格式。 |
| 紙上 | 集中策略、對帳、風控與覆蓋提示；執行、暫停、停止、重開、風控鎖定使用同一實際狀態；委託、撤單、恢復新委託與對帳語意不變。 |
| 市場 | 統一字級與留白，保留行情、八種週期、指標、圖層、畫圖、版面保存和彈出視窗。 |
| 設定 | 連線優先，常用通知／外觀／隱私／備份可直接找；日誌、診斷、維護、研究助理及還原收合；異常連線可直接展開處理。 |

## 完整離線流程

`tests/test_ui_redesign_data_results.py` 實際執行：

1. CSV 與明確日曆匯入，使用 fixture 研究產生候選。
2. 點擊採用已評估候選；未通過門檻的候選回測後仍被拒絕紙上資格。
3. 內建策略回測、真實報表比較、保存選用。
4. 政策、快照與明確對帳，歷史行情驅動紙上重播。
5. 暫停時 cursor 不動，繼續後前進。
6. 確認停止後 kill/manual_order_lock 持久化，持倉與成交保留。
7. 新建視窗重開結果與 journal，仍需對帳及明確解除鎖定。

只以同步離線 adapter 取代背景啟動及確認對話框互動，所有核心 UI operation
仍實際執行。沒有放寬門檻、延長期限、重置預算或偽造資格。

## 實際畫面

以下為 PySide6 元件原生 render 的 1366×768 畫面，全部使用隔離合成資料。

| 工作區 | 淺色 | 深色 |
| --- | --- | --- |
| 資料 | [畫面](screens/light-data.png) | [畫面](screens/dark-data.png) |
| 策略中心 | [畫面](screens/light-strategy.png) | [畫面](screens/dark-strategy.png) |
| 回測結果 | [畫面](screens/light-backtest.png) | [畫面](screens/dark-backtest.png) |
| 比較 | [畫面](screens/light-compare.png) | [畫面](screens/dark-compare.png) |
| 紙上交易 | [畫面](screens/light-paper.png) | [畫面](screens/dark-paper.png) |
| 市場總覽 | [畫面](screens/light-market.png) | [畫面](screens/dark-market.png) |
| 設定 | [畫面](screens/light-settings.png) | [畫面](screens/dark-settings.png) |

[AI 研究](screens/light-strategy-research.png)、[自行設定](screens/light-strategy-manual.png)、
[Walk-forward](screens/light-strategy-walk_forward.png)、[無資料](screens/light-empty-data.png)、
[紙上暫停](screens/paper-paused.png)、[停止](screens/paper-stopped.png)、[重開](screens/paper-reopened.png)。

畫面矩陣涵蓋兩種主題、1366×768／1920×1080、150%／200% 字型，另逐一切換四種
資料來源與四個策略工作區。空白與有資料各 120 個組合，紀錄於
[空白矩陣](layout-empty.json)／[有資料矩陣](layout-populated.json)。
兩者均為 0 個已檢出文字裁切、元件重疊或頁面橫向捲動。
策略 150% 字型另測四個工作區的外層捲動範圍為 0，只有內層工作區捲動。

## 保留與相容性

- G3 八個鎖定檔、saved_candidate_pool profile、引擎、預算、OOS／holdout 與期限未修改。
- 新文字均置於 desktop_strings.py 語意鍵，既有錯誤仍使用單一錯誤表。
- 不新增 controller 或資料狀態來源；搬移同一批表單與控制項。
- 明確支援舊摺疊偏好，初始掛載／重載不保存，真正切換才保存，未知與歷史鍵保留。
- 損毀的偏好容器回退，不自動修復或覆寫原檔。
- 隱藏操作不留下可誤導的停用提示；命令面板先顯示本機來源，再聚焦可見的匯入操作。

## 基準調整紀錄

沒有重錄數值或資格 golden。`desktop_pages_before` 原始畫面檔保留供歷史對照；
舊逐像素不變斷言改為新任務分區、唯一主要操作、欄位標籤及停用原因檢查，
另有 240 組原生畫面、鍵盤／生命週期及完整流程測試。

`desktop_widget_names.json` 只更新實際新增的來源、任務、導航、資格提示與摺疊控制項；
保留時鐘與來源標籤的隱藏相容性身分，舊編號 advanced_* 因新增語意分區而變動。
`page_services_inventory.json` 更新來源行號、消費模組與測試 patch 位置；
原服務／alias／state copy 數量與契約仍由原測試逐項固定。

詳細命令與最終結果見 [驗證紀錄](verification.md)。

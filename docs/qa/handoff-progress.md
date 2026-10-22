# 全功能測試與發布：交接進度

最後更新：2026-10-22（UTC 12:2x）。這份檔案在每個段落結束時更新，讓接手者（人或其他代理）知道目前狀態。

## 任務來源

擁有者指示的 6 個步驟：(1) PR #77、#78 全綠後依序 squash 合併；(2) main 的 Windows 安裝檔與 preview 發布；(3) 帳號實測（需 ready 狀態，且 reserved_unknown 只能用 PR #76 核准後的正規流程處理）；(4) 全功能測試；(5) 中文測試報告 PR；(6) 用量交接。

## 已完成

- PR #75（上網找策略點子）已 squash 合併：main `7db4ef8`，preview `desktop-preview-39694271951-1`。
- PR #77（ChatGPT 登入背景作業 model 欄位）已 squash 合併：main `41fb0d0`。CI 共 4 輪：第 1–3 輪皆為 CI 逾時或清理逾時（ui 跑滿 15 分鐘、smoke 40 秒、PowerShell 8 秒、Walk-forward smoke 清理、ubuntu 3.12 跑滿 15 分鐘），無測試斷言失敗；第 4 輪 24 項全綠，合併 head `37fa05d`。
- PR #78（深色／淺色分頁樣式）已 squash 合併：main `8c4c870`。CI 第 1 輪逾時、第 2 輪 24 項全綠，合併 head `344c369`。#77 合併後 GitHub 仍判定 CLEAN（無分支保護、檔案不重疊），未另行更新分支。
- `tools/ui_readability_audit.py`（QA 分支 `ce2a7e5`）：真實 Windows 視窗模式在 `7db4ef8` 重現深色分頁對比 1.41（AI 策略中心三個分頁、紙上交易四個分頁）。

## 進行中

| 項目 | 分支 | PR | 狀態 |
|---|---|---|---|
| main 安裝檔與 preview | main `8c4c870` | — | Windows desktop installer 執行中（`41fb0d0` 與 `8c4c870` 各一輪） |
| 本交接檔、稽核工具、測試報告 | `qa/full-function-test` | 尚未開 | 進行中 |
| 人工核對 reserved_unknown 設計 | `docs/chatgpt-unknown-request-reconciliation-design` | #76（草稿） | 待擁有者決定 D1–D4，未實作 |

## 下一步

1. 確認 `8c4c870` 的 Windows desktop installer 成功、新 preview 已發布，記下載點、安裝檔名與 SHA256SUMS.txt。
2. 帳號實測：PR #76 未核准實作 → 依指示跳過並記錄。
3. 在乾淨 main（`8c4c870`）跑 core（desktop、paper、remaining）與 research 分片；以臨時工作區與 bootstrap 逐頁操作（4 組功能區，Sonnet 代理），並以 `tools/ui_readability_audit.py`（offscreen 與真實視窗）驗證深色／淺色可讀性。
4. 修正可修的問題（各自分支與 PR），寫 `docs/qa/` 測試報告並開 PR。

## 已知問題

- 本機（Windows、無 symlink 權限）既有測試錯誤：`test_analysis_recovery`、`test_automatic_backup`、`test_chatgpt_auth`、`test_downloads`、`test_market`、`test_market_history`、`test_notice_collector`、`test_qt_licenses`、`test_reporting` 的 symlink／hardlink 測試（WinError 1314），以及 `test_windows_recovery_feasibility`、`test_test_group` 的原生程序測試；在乾淨 main 上同樣失敗。
- CI 的 `ui` 與 `offline (ubuntu-latest, *)` 工作長期跑 12–15 分鐘，貼近 `timeout-minutes: 15`，偶爾被取消（已提出任務卡，未處理）。
- 本機 cp950 地區設定下不開 UTF-8 模式時，`test_repo_layout` 讀取含中文檔名的 git 輸出會失敗；開 `PYTHONUTF8=1` 即通過，CI（英文環境）不受影響。
- `desktop.py --smoke-test` 會讀取 `%LOCALAPPDATA%\MarkAuto` 的工作區位置設定，依限制不直接執行；改以臨時 AppPaths 直接建立 MainWindow。
- 擁有者電腦的 ChatGPT 帳戶狀態為 `reserved_unknown`（先前研究請求中斷），在 PR #76 的人工核對流程實作前，所有 ChatGPT 請求都會被擋。

## 尚未測試的功能

全部（第 4 步尚未開始）：資料匯入與更新；AI 策略中心（策略設定、AI 研究、Walk-forward 驗證、上網找策略點子）；回測與結果；比較與策略選擇；紙上交易與復原；市場總覽；設定與備份（自動備份、還原、外觀主題、隱私模式、日誌）；說明、快速開始、通知。

## 硬性限制（摘要）

不改 G3 八檔與 `manual_exchange.py`、`walk_forward.py`、`saved_candidate_pool.py`；不放寬產品時限；不刪除、略過或削弱測試；不提高 ACCEPTANCE；不新增實盤路徑；不讀寫 `%LOCALAPPDATA%\MarkAuto`；不 force push、不改寫歷史、不刪除分支／tag／release。

# 研究與紙上模擬實機驗收（2026-10-23）

驗收安裝版：PR #87、a1bfe92632b3633e8cb569cb276814a8633f28e7、版本 0.2.2。使用者自行安裝；下載 SHA256、建置來源與安裝後 provider 雜湊已核對。PR 未合併；本文件不調整正式接受分數。

所有資料與紙上績效均為明確標示的 synthetic 測試，不代表市場績效。真實 ChatGPT 呼叫只透過既有 App 授權／傳輸；沒有讀取憑證、真實 MarkAuto 資料或操作其他專案。

| 功能 | 安裝版結果 | 保護行為與限制 |
|---|---|---|
| 資料匯入與驗證 | 6000 根合成 CSV／明示日曆成功；另建立 960 根合成資料 | 無效 CSV 回報 validation_failed；原資料 SHA256 前後相同 |
| 策略設定與候選採用 | 既有 fixture 不可變候選可套用於研究回測 | 真實研究本次未入選，未驗證真實入選候選採用正向路徑 |
| ChatGPT 模型／連線 | GPT-6.1-Sol 清單成功；少量連線有回應 | 連線更新後須重新取得模型；缺模型時正確拒絕研究 |
| GPT 網頁搜尋／點子 | 原始 TMF／5 分鐘／不指定方向案例完成；讀取 4、失敗 2；2 次模型呼叫、2 個候選 | needs_custom_rules 候選不可採用；不代表可回測或策略合格 |
| 固定來源 | fixed_sources 完成；搜尋查詢 0、讀取 5、blocked 2、failed 1；1 次模型呼叫、3 個候選 | 曾遇連線過期 idea_auth_refresh_required；App 明確更新、重新取得模型後完成；不可回測候選仍拒絕 |
| 真實完整研究 | 訂閱模式最多 1 次生成、0 次改進、1 次請求／30 秒；completed；train、validation 評估完成；receipt 1 筆 | 合成 validation 淨損益 -2990，未達原門檻 0；selected 0，holdout not_accessed；不宣稱模型市場績效已驗證 |
| 回測與結果 | 安裝版採用既有 fixture 不可變候選後回測成功保存 | 研究回測不授予樣本外或紙上資格；原始碼版已確認未合格候選的紙上啟用按鈕停用 |
| 比較 | 選取保存結果執行比較 | 保存／重開結果另記下方 |
| Walk-forward | 6000 根合成資料；start 2880、train 720、validation 360、oos 360、3 folds、step 360、holdout 5040..6000；completed；保留評估 30／上限 33、模型呼叫 0 | 重疊範圍正確 blocked_previously_consumed_range；資料改變使預覽失效；3 輪均無通過驗證門檻候選，evaluated_oos_folds 0；final holdout excluded_not_evaluated、paper_eligible false |
| 紙上模擬／恢復 | 載入合成參考快照、明確對帳、解除手動鎖定成功；政策相符資料成功重播 100 根；orders 5／fills 5 | 安裝後保留原手動鎖定；6000 根超出既有 4 天政策時送單前拒絕；成功結束後 kill_switch true、manual_order_lock false、reconciliation_required false |
| 取消與時限 | 原始碼版終止／取消／清理回歸 9 項通過，隔離 native smoke 通過 | Paper 30 秒、smoke 40 秒、研究工作 15 分鐘不變；安裝版未逐項重跑所有取消競態 |

## 已確認根因與修復

1. 原始萃取診斷 extraction_terminal_missing_event_text：前段已有完成文字項目，response.completed 卻沒有 output。相同離線事件在 main 重現 ambiguous_output，修復後通過。只接受有界、已完成、索引連續、ID 唯一及 response ID 相符的完整項目；不採用 delta、不覆蓋非空 terminal，不放寬 JSON／DSL／來源驗證。
2. 完整研究傳輸同樣離線重現 missing_output。修復僅用於計畫 provider，SSEParser 不變；追加 completed-items producer profile 與必要來源 pin，保留 23 個歷史 profile。安裝版真實研究已完成生成及訓練／驗證評估。
3. AuthError('refresh_required') 沒有 code 屬性，過去被隱藏成 remote_error。改用精確固定分類，不輸出原始例外、帳號、請求或回應。安裝版確實觸發並驗證正常 App 更新後恢復。
4. 紙上重播拒絕在隔離副本重現，堆疊止於 PaperBroker.quote_policy 的時段覆蓋檢查：鎖定政策 4 sessions、覆蓋 960／6000 根。屬正確保護，未改政策或檢查；切回符合政策的資料後實機成功。

## 回歸與建置

- 修復前失敗、修復後成功：點子事件 4 項、完整研究 2 項及安全反例。producer profile 67 項、傳輸／帳號／來源 107 項、錯誤與隱私 64 項、點子研究／搜尋／介面 44 項通過。107 項中沿用一項主機無法建立合成 symlink 的既有跳過，未新增跳過。
- 假網站測試在允許 localhost 的環境通過，沒有使用帳號。原始碼版 native smoke 曾遭既有 Windows PermissionError，另一次全新隔離目錄完整通過；未放寬時限或以 golden 掩蓋行為。
- 操作 golden 僅更新 9 個必要來源 digest；3 項 metadata 保護通過。原有 64 筆錯誤訊息 digest 與歷史 producer profile 不變。
- a1bfe92 Quantlab gates run 39904022339：success、24 jobs。Windows desktop installer run 39904019294：success；分支 release 步驟按規則略過，並非發布失敗。
- 安裝檔位於 Downloads/MarkAuto-preview-a1bfe92/installers/MarkAuto-0.2.2-windows-x64-setup.exe；SHA256 1c3928096711062c204a6eeffe19bfc2dba7c255ea500e8f010358f9cdc98588。
- GitNexus 更新至 a1bfe92。本文件修改前 impact UNKNOWN（文件節點無呼叫邊），另人工核對僅更新驗收事實。

沒有測試證明投資績效、正式排名、真實市場紙上資格或實盤能力；實盤永久停用。

## 保存與重開

安裝版正常關閉後再開啟：比較頁仍顯示 3 筆保存回測；隔離狀態保留 2 個 campaign、2 個 Walk-forward 紀錄與 960 根 synthetic 資料。紙上 5 筆成交保留；kill_switch true、manual_order_lock false、reconciliation_required true，重新要求對帳，沒有自動恢復委託。比較選取屬暫時狀態，重開後未選取。

此輪沒有新增程式修復：後續拒絕均確認為連線到期、來源失敗、未達候選門檻、已消耗樣本外或鎖定政策覆蓋不足。未宣稱真實候選入選／OOS／holdout 正向流程通過；安裝版所有取消競態亦未逐項驗證。

本機 prepush.ps1 被 Windows AuthorizationManager 擋下，未變更執行原則。分別執行 Ruff check（通過）、quality gate（0 findings）、498 個追蹤 Python 檔的 3.11 grammar scan（通過）。format check 僅既有 ADR 0006 例外，未修改該檔；正式 Python 3.11／3.12 測試以 CI 證據為準。

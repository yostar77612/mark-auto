# 研究與紙上模擬實機驗收（2026-10-23）

驗收安裝版：PR #87、a1bfe92632b3633e8cb569cb276814a8633f28e7、版本 0.2.2。使用者自行安裝；下載 SHA256、建置來源與安裝後 provider 雜湊已核對。PR 未合併；本文件不調整正式接受分數。

所有資料與紙上績效均為明確標示的 synthetic 測試，不代表市場績效。真實 ChatGPT 呼叫只透過既有 App 授權／傳輸；沒有擷取憑證或讀取真實研究資料，未操作其他專案。內建 smoke 的原工作區指標／非敏感偏好唯讀例外及授權，詳見下方續驗。

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

## 安裝版整輪與短路徑續驗

程式仍為已安裝的 a1bfe92／0.2.2，沒有修改安裝內容或增加帳號請求。1be4a83 文件提交的 Quantlab gates run 39935119661 全部 24 jobs 通過。這次僅補驗收事實。

前三輪安裝版離線 smoke 保留失敗紀錄：第一輪主要七步通過，手動匯出 ValidationError，隔離重現其 cause 為 os.link 的 PermissionError／WinError 5；第二輪回測 PermissionError；第三輪主要七步、手動匯出／匯入、歷史匯入與 Walk-forward 預覽通過，Walk-forward 執行遇 FileNotFoundError。三輪都沒有逾時，清理證明均成立。沒有刪除、略過或弱化任何測項。

原測試暫存根路徑長 112 字元，估算其巢狀 Walk-forward journal 路徑 262 字元。隔離 SQLite 對照：64 字元路徑可建立表並提交；259 字元路徑可連線，但建立表失敗，SQLITE_CANTOPEN（14）。安裝 EXE manifest 已宣告 longPathAware=true。這證實本機 SQLite 長路徑存在限制；不能僅憑此將所有 PermissionError 或 FileNotFoundError 都歸為同一原因。

內建 smoke 使用 Windows SHGetFolderPathW 取得 bootstrap，環境變數不會改變其唯讀載入的原工作區指標與非敏感偏好。先前誤以為該入口也完全隔離，發現後已停止並向使用者更正。使用者其後明確核准「允許這一次限定唯讀對照」，例外允許這兩項直接唯讀；不讀憑證、帳號或研究資料。此次授權只用於下面的一次對照，之後不沿用。smoke 程式本來即不啟動帳號自動還原；所有可寫資料仍在本專案內。

改用 repo 內較短的 TEMP／TMP（根路徑 76、估算 journal 路徑 226 字元），相同安裝程式與完整測項一次通過：exit 0、status passed、timed_out false、worker_cleanup verified，沒有清理錯誤。七個主要步驟、手動匯出／匯入、歷史匯入、Walk-forward preview／run／read、授權相依檢查與 frozen recovery helper 全部通過。先前長路徑失敗與此次成功對照支持測試暫存路徑是後段阻塞因素；沒有為此改程式、政策、閘門或時限。

安裝版 Walk-forward fixture 實際完成 2 折、22 次評估，兩折各有 3 筆樣本外平倉；重新讀取驗證成功，零成交候選仍排除，最終保留集維持 excluded_not_evaluated，模型呼叫 0、paper_eligible false。這是工程合成案例，並非真實研究候選或市場績效。另 5 項窄範圍原始碼回歸通過，包含巢狀 spawn 正向 OOS、唯讀 journal、損壞／缺失 journal 拒絕及無候選判定。

完整本機報告：`.tmp-acceptance/installed-short-smoke-report.json`（保留在 repo 內、未提交）；SHA256 `47e7d80e4c73c7c1b41498dd035e064d4a7fe00b94392c5bbdcace27dc784f0c`。先前失敗報告也保留。真實候選入選／OOS／holdout 的正向路徑與安裝版所有取消競態仍未逐項實測，不宣稱這些項目全數通過。實盤永久停用。

## 續驗：真實生成候選的正向資格與主表單同步

本節記錄本次提交時點；程式仍為使用者已安裝的 a1bfe92／0.2.2。下列
官方呼叫均透過 App，沒有直接擷取憑證或修改帳號控制紀錄。測試輸入、
研究、回測與診斷位於 repo 的 `.t/p` 與 `.tmp-acceptance`；沒有操作 Sitecore
或其他專案。這些都是 synthetic 工程資料，不代表真實市場績效。

- 第一個固定協定：5760 根單向合成資料，均線趨勢家族、1 次生成、0 次改進、
  1 次請求／30 秒，最低淨損益 0、最少成交 1。真實生成 completed，但
  train／validation 都沒有訊號或成交；正確不入選、holdout not_accessed。
  離線確認該家族要求均線交叉，單向資料不會觸發。候選、收據與失敗紀錄保留，
  沒有退款、改寫模型輸出或降低門檻。這個候選已在 App 成功採用供研究。
- 第二個協定先固定資料與雜湊，再僅以訓練段離線驗證交叉訊號覆蓋。8000 根
  合成資料切為四段各 2000 根；每段包含平盤、上升與下降，明確標示工程用途。
  維持前述門檻與請求上限，另一次真實生成完成；1 個候選入選，OOS 與 holdout
  各 evaluated 1 次、各有 1 筆平倉，淨損益均為合成數字 186676。
  selection_hash 與 holdout_selection_hash 相同；holdout reserved_consumed。
  收據 1 筆 completed，沒有重新產生或改善。兩次真實生成各自保留其消耗。
- 原有 candidate_record 驗證 paper_qualified／oos qualified／holdout qualified
  均為 true，source_type 仍為 synthetic。產品的 real_model_status 仍是
  not_verified，沒有更改此欄位或正式模型／投資接受分數。
- App 採用第二個真實候選，在 2026-07-01～2026-07-08 的訓練日期內回測保存，
  1 筆平倉、合成淨損益 170676；通過原資格檢查啟用為 research_and_paper_only。
  完成後按 Esc、正常關閉與重開，active candidate、selection、campaign JSON
  與 authoritative SQLite 四個檔案 SHA256 不變，沒有自動增加模型收據。
- 離線取消回歸 9 項通過，包括真實 Windows 子程序樹清理、完成／取消競態、
  中斷收據保留、WFO 不重跑與點子來源取消。安裝版離線研究在已保留嘗試後
  按 Esc 成功停止；重開同一研究回報 blocked_interrupted，保留 4 次嘗試
  （3 evaluated、1 interrupted）、不新增嘗試、不消耗 holdout、無帳號請求。

續驗也確認一個顯示錯誤：不可變參考與回測結果正確，但採用／重開後，停用的
策略主表單仍顯示內建預設參數。新增離線測試在五個家族及自訂規則共六個情境
都於修復前失敗。修復只同步已驗證候選的欄位並清空缺少的選填值；不修改候選、
規則、歷史、來源驗證或資格。修復後六個情境、既有完整採用／回測／保存恢復與
不合格候選拒絕三項測試通過；另 49 項表單、候選呈現、恢復與紙上停止回歸通過。
新版安裝版的參數同步驗證，以及進行中關閉、WFO／Paper 的後續實機取消驗證，
在此提交時仍待完成，不以原始碼測試代替。

第二個協定 SHA256：`e36e534183491906869c7ee952075e04dee19541481483f7e0762126d8b90f9f`；
資料檔 SHA256：`3e11444dbe1a9a46339f88cb4a777271ff034c14ba58e2f6a82a2cd80dc364cc`。
本機證據為 `.tmp-acceptance/positive-v2-train-only.json`、
`positive-checkpoint-before-reopen.json`、`positive-reopen-verification.json`；均未提交。

取消關閉續驗另重現頂列凍結：CloseWatcher 在 MainWindow 決定接受或拒絕關閉前
便停止 header timer，因此按 No 留下視窗時，時鐘、作業摘要與頂列時間提示不再更新。
主工作輪詢與持久研究結果仍正常；等待確認時已完成的離線研究，其正式結果保留。
新增 generic rejected-close 與真實 MainWindow busy-close No 兩個離線案例，修復前
都失敗。修復僅在原計時器曾啟用、視窗仍可見且非關閉流程時恢復 header timer；
原本停用者不會自動啟用，接受關閉仍立即停止。通知共用的 CloseWatcher、背景工作、
確認、清理、對帳與時限均不變。修復後 header 全套及新增整合共 8 項通過；參數同步
修改後的完整 NativeDesktopTests 另 27 項通過。頂列修復的新版安裝版實測仍待完成。

安裝版確認關閉的獨立離線案例（seed 44003）在背景工作中按 Yes，視窗已正常關閉；
保留 7／15 次嘗試（6 evaluated、1 running），未消耗 holdout、無模型請求。
其恢復與禁止續跑，以及 WFO／Paper 的後續實機取消結果，仍待下一階段核對。

# 研究與紙上模擬實機驗收（2026-10-23）

所有合成資料僅供功能驗證，不代表市場績效。未驗證不計為通過。

| 功能 | 正常流程 | 錯誤／取消 | 保存／重開 | 證據與限制 |
|---|---|---|---|---|
| 資料匯入與驗證 | 未驗證 | 未驗證 | 未驗證 | 使用隔離工作區及標示的合成資料 |
| 策略設定 | 未驗證 | 未驗證 | 未驗證 | |
| ChatGPT 模型清單 | f9aa397 實機通過 | 未驗證 | 未驗證 | 已顯示官方模型 |
| ChatGPT 少量連線 | f9aa397 有回應 | 未驗證 | 未驗證 | 不等於完整推論驗收 |
| GPT 網頁搜尋 | f9aa397 進入來源讀取及萃取 | 未驗證 | 未驗證 | TMF／5 分鐘／不指定方向 |
| 策略點子／完整研究 | 失敗 | 未驗證 | 未驗證 | 萃取階段 ambiguous_output，實際分支待安全診斷 |
| 固定來源 | 未驗證 | 未驗證 | 未驗證 | |
| 候選採用 | 未驗證 | 未驗證 | 未驗證 | |
| 回測與結果 | 未驗證 | 未驗證 | 未驗證 | |
| 比較 | 未驗證 | 未驗證 | 未驗證 | |
| Walk-forward | 未驗證 | 未驗證 | 未驗證 | OOS 一次性消耗不變 |
| 紙上模擬 | 未驗證 | 未驗證 | 未驗證 | 實盤永久停用 |

已確認根因：本機診斷版在原始案例回報 extraction_terminal_missing_event_text，表示前段已有文字事件，但結束事件沒有文字。舊版只解析結束事件，未使用已完成的輸出項目。原始修復案例仍在實機重測。

目前已安裝的 preview 為 f9aa397；修復後安裝版尚未驗收。診斷只容許固定錯誤碼、型別、數量及大小，不記錄帳號、憑證、原始請求或回應。

離線證據：研究流程 21 項、搜尋 14 項、點子介面 9 項通過；空 terminal 的離線案例在 main 基準失敗（ambiguous_output），修復後通過。操作清單測試在 main 基準與修改版均出現 PermissionError／時序失敗，未改寫 golden。Ruff check 通過；format check 僅 ADR 0006 既有例外，保留原檔。

第二個已確認問題：App 的「讀取本機連線（不連網）」顯示「需要明確更新連線」。AuthError 的 refresh_required 沒有 code 屬性，舊研究流程會顯示 remote_error；以離線例外重現並補上固定、不含原始文字的錯誤分類。已透過 App 明確更新連線成功，沒有自動重試或直接讀取憑證。

隔離原生 source App smoke：第一次 ui_backtest 遭 PermissionError，清理已證明完成；第二次全新隔離目錄通過（既定 40 秒限制不變），包含 ui_demo、ui_backtest、ui_select、fixture ui_campaign、ui_paper_reconcile、ui_paper_replay、ui_paper_kill，以及 history、market、Walk-forward preview/run/read。資料為 synthetic，不是市場資格或績效證據。smoke 終止／取消／清理 9 項測試亦通過。修復後安裝版尚未實測。

PR：#87，未合併。第一輪 CI 的錯誤表來源 hash 未重新釘選，屬本次漏項，已補上；不是 Windows 偶發失敗，未以重跑掩蓋。新的來源 pin 保留原有 64 筆訊息 digest。

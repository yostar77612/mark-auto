# mark-auto 原始功能總表與可重用性

<!-- CURRENT_STATUS_START -->
## 當前交付摘要（2026-10-10 05:02 UTC）

- **已發布：0.2.1 unsigned preview**，main `2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`；[正式下載與該版 manifest](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1)。已實際核對八項主要 assets／56 個來源輸入、EXE 與 kit SHA-256／ZIP CRC；postmerge Windows 與 Quantlab 全部 PASS。這是研究／Paper 預覽版，並非 clean-client 或投資合格證明。
- **正在修復：PR #5／候選 0.2.2，DRAFT／FAIL_REPAIR_IN_PROGRESS**。版本及功能分支不變；上次推送 head `d598b39` 的 Quantlab `38024116768` 為 8 jobs 中 7 PASS，Windows 3.12 在原 960-bar／30 秒 Paper case 再次逾時。診斷 worker 36.453 秒，其中 960 次 FULL cursor commit 31.587 秒；不能沿用較早 head 的 PASS。未合併、未發布，沒有 0.2.3 Release，也沒有已發布 0.2.2 baseline。
- **已整合但未推送：** WFO、PF／描述性 Sharpe／參考快照、普通回測繁中呈現與指南的 981 項全套，實際在 `/tmp/mark-auto-023-candidate` 執行：966 PASS＋15 個既有 native／PowerShell skips，271.745 秒。其後依 `root-integration-manifest.json` 逐檔核對，將 25 個相同 bytes 檔案複製至 root；這是該整合檢查點的來源等價候選證據，**不是最後整合 root 全套**。之後 CandidateSummary 與診斷新增不在這 981 項執行範圍內，最終全套／native CI 仍待。
- **後續呈現／診斷：** CandidateSummary 已套用至 root 並獨立審查：79 項 focused PASS；root 97 項＝96 PASS＋1 Windows-only skip，27.561 秒。Paper 顯示未改。diagnostic-only 新增另有 root 145 項＝140 PASS＋5 skips，8.223 秒；上述集合重疊，不相加，也不替代最後全套。原普通回測／footer 的 53 項獨立、139 項 focused 屬較早檢查點。
- **原生與診斷範圍：** 上次 head 的 Server run `38024116755` build／security PASS，773 項＝761 PASS＋12 profile skips，238.878 秒；native frozen、安裝、真 0.2.1 升級／復原 PASS，PR release job 正常 skip。完整矩陣仍因 Win312 Paper 預算失敗而未過。下一步僅做同一原生 host 的 C:／RUNNER_TEMP 與 DELETE／PERSIST fresh／held 有界比較；尚未改產品儲存、FULL 耐久或原 30 秒／10 秒 Gate。
- **研究仍有明確限制：** saved-pool 的 157 項獨立審查屬整合前證據，目前功能已在未發布工作樹；不是 adaptive AI 或正式排名認證。真實 Oct8 WFO 仍為 `BLOCKED_NO_RUN`，完整 guard 與既有 consumed coverage 重疊 170 bars；0 新評估／模型呼叫／reservation，不改 window 或另建 registry 繞過。
- **固定歷史驗收帳本：210/300＝70%，未接受 90 點**。原研究 100、桌面 70、市場 40；僅已取得證據的整項 PASS 計分。這不是剩餘工時、完整原需求或生產就緒百分比；後來重新確認的必要需求仍明列，分母／門檻不降低。
- **外部與安全邊界：** clean Win10 22H2 x64／Win11 x64 為 EXTERNAL_BLOCKED；實際 ChatGPT grant／訂閱推論 NOT_VERIFIED；TAIEX 盤中自動使用權限未核實；main protection 未啟用且管理 API 403；unsigned 不繞過安全警告；真資金交易固定 DISABLED。 05:02 環境重查列出兩台桌機，一台已連線但未授權執行工作，另一台離線；沒有 saved coding environment，仍無已授權的乾淨 Windows 驗收環境，未要求更改設定。


已推送身分對照：remote `d598b39` 對應 local `9c8708a`，tree `84978f8be8d4a2ced60e5b90a7ee746c2690acc0`。之後的未提交整合／呈現／診斷工作不包含在這個舊 remote tree。

### 原需求、設計提案與未驗證項目

- **本輪已明確必要的原需求：** Walk-forward，以及使用者原文 §5.1 的 Profit Factor／Sharpe、§3.4 的停損／停利／持倉成本參考線；工作樹整合及本地 PASS 不等於已發布交付。
- **尚未採用的完整目標設計延伸：** 04 §9.1 提出的 Average Trade、Sortino、Calmar、延伸分解與成本壓力測試保留為提案。02 歷史原文已明示「若最終採用該完整規格」；未取得使用者直接要求這些延伸的原始證據，因此不把設計表的「必須公開的計算與例外」升格為本輪新增驗收門檻，也不刪除提案。
- **尚未驗證的結果：** 最終 exact-head native／發布、clean client、真實授權與真實研究各依目前證據判定；未驗證不表示功能未實作，設計提案未採用也不等於本輪驗收失敗。

### 狀態怎麼讀

「已發布」只指 0.2.1 的指定能力；「候選已實作」仍受 PR #5 最終 gate 約束；「已整合未發布」指本地工作樹已接入、尚未經最後原生／發布核對；「隔離已審查」只適用仍獨立的歷史證據；「未提供」「未驗證」「外部阻塞」分開記錄。所有 PASS 均只適用其來源、平台與測試情境，後續缺陷可否決新發布。歷史記錄中的「目前／待發布／未實作」一律按該段日期解讀。

## 當前完整功能與狀態矩陣

以下完整列出原生桌面、研究與交付能力；詳細公式、呼叫路徑、固定原始碼 S01–S31，以及原系統 F01–F35 盤點保留於後方歷史原文。功能列數不是計分單位。

| 領域／功能 | 0.2.1 已發布能力 | 候選整合進度 | 必須保留的限制與相依 |
|---|---|---|---|
| 七頁桌面與共通操作 | 總覽、資料、策略、回測、比較、Paper、設定；繁中深色、進度／取消、錯誤顯示 | PR #5 補普通操作缺口 | Server／Linux Qt 證據不等於 clean Win10／11 DPI／鍵盤驗收；無已驗證深淺切換 |
| 市場總覽／自選／月份 | 四類商品摘要、自選增刪排序、實際到期月、來源／freshness | 現有流程保留 | 首次可為空；不預填假行情。Paper 表格不是券商帳戶 |
| 加權指數 TAIEX | 官方日 OHLC；日／週圖 | 五秒 endpoint 僅有來源調查 | 自動使用權限 EXTERNAL_BLOCKED；五秒值不是原生分鐘 OHLC，無量不補 0；不串接自動輪詢 |
| 大台 TX／小台 MXF | TAIFEX 日／時段行情；日／週圖；來源 MTX、顯示 MXF | PR #5 本機 CSV／RPT tick→分鐘匯入，3 商品×8 週期範圍已測 | 未發布分鐘入口；TX／MTX 不具研究／Paper 商品資格 |
| 微型 TMF | 日／時段行情；合格 TMF dataset 可供分鐘圖 | PR #5 同一受限市場分鐘匯入 | 核心限實際 TMF 月份、乘數 10、tick 1；market cache 不自動成研究資料 |
| 本機匯入／有界更新 | 研究 CSV／RPT／validated dataset、官方 daily JSON／CSV、明示 calendar；逐次同意的近 1–30 日下載 | PR #5 明示日期／session、來源 hash、cache quota／不可覆寫發布 | 來源 schema／hash 不證明檔案真偽、授權或多年完整覆蓋；沒有官方 calendar 自動維護器 |
| 資料品質／追溯 | contract／calendar／來源／manifest；缺口、重疊及非法欄位拒絕，保留警告 | 原品質標準不放寬 | 實際 13,680 分鐘／12 日與 24 盤 OHLC 只證有限樣本；Oct7 缺分鐘仍拒絕 |
| 八週期／圖表互動 | 合格分鐘源的 1／3／5／15／30／60 分、日、週；縮放、拖曳、十字線、鍵盤 | PR #5 TX／MTX／TMF 24 組合來源／GUI 證據 | 粗源不可製造細線；日夜盤以明示 session 聚合，gap／partial 不插補；M2 仍 PARTIAL |
| MA／EMA | 可改週期；SMA seed／warmup／缺值語義已測 | 無本次新增 | 依當前圖表 bar 重算，非任意歷史資料都完整 |
| RSI／KD | Wilder RSI、KD 9／3／3 等明示公式、因果／golden | 無本次新增 | warmup／缺值及平幅規則保留 |
| MACD | 12／26／9，histogram＝MACD−signal；真 host 圖例標 1× | M3 已完整接受 15 點 | 公式正確不等於策略獲利 |
| Bollinger／VWAP | 母體標準差 Bollinger；session-reset OHLCV typical-price VWAP | 無本次新增 | VWAP 是近似值，不是真逐筆成交 VWAP；無量／零量保留缺值 |
| 訊號／成交獨立圖層 | hash 綁定回測 signals／fills、獨立顯示、不同形狀 | M5 PASS | 非券商成交；未驗證 journal Paper 圖層。既有 5,748 markers 是回測證據 |
| 持倉成本／停損停利參考 | 尚未接上必要的正常結果顯示 | 已整合至未推送 0.2.2 工作樹；來源等價候選檢查點 981 項通過；後續變更另測 | 最多六個 final-event snapshot ticks；成本、MTM basis 與 margin 分開；非歷史路徑／真委託；最後 native／發布待驗 |
| 五策略／普通參數 | 趨勢、均值回歸、通道突破、動能、波動壓縮及有限 typed 參數 | 無本次改寫策略核心 | 有限家族；不同參數不必然是不同投資邏輯 |
| DSL／執行隔離 | JSON／AST allowlist，大小／深度／欄位限制；只輸出規格／intent | 原限制保留 | 不執行模型回傳 Python，不是任意程式安全沙箱 |
| 因果回測／帳本 | next-open 撮合、保守 stop/target 同棒、FIFO、費稅／滑價、equity／ledger | PR #5 增普通 expiry 輸入 | OHLC 假設；無 order-book／queue／市場衝擊認證 |
| 實際月份／到期／roll／MTM | 核心有明示到期、roll／settlement／成本與 margin schedule | PR #5 普通 expiry table，training-only 5,700 bars 兩次同 hash | 不替使用者推斷官方日期；進階事件仍無完整普通 GUI 編輯器；來源／日曆先備妥 |
| 單策略／批次回測 | 普通費用／資金等設定，五家族預設參數批次，equity／成交／結果 | PR #5 修正真實資料普通 expiry 配置 | 示範預設不是已認證市場成本；M4 尚未全滿 |
| 固定四段研究閉環 | generate→validate→train/validation→改善→freeze→OOS/holdout | 保留原版、非 WFO | 單次四段 split 不等於 rolling；工程成功不保證模型有效、去重或經濟結果 |
| 預算／不可變版本／holdout | 最多 15 trials、每家族 2 次改善；持久預算與所有失敗；共享 consumed guard | WFO 另有單一實驗上限，未替代原門檻 | 改名／搬工作區／還原舊備份不可重置未見資料；本地 hashes 不能抵抗完整自洽回滾 |
| 固定池 Walk-forward | 未發布 | rolling／expanding 2–20 folds、typed UI／journal／cancel／stop proof 已整合至候選工作樹；早期來源等價候選 981 項通過，非最後 root 全套 | 固定五候選、每 fold validation 凍結後才 OOS；最高 220 evaluations；無 adaptive AI；最後 native／發布待驗 |
| 已保存 AI 候選 WFO | 未發布 | 最多 15 既存候選、受限 producer tuples／來源與 registry 連續性已整合；整合前獨立 157 項及 早期來源等價候選 981 項證據分列 | 每 fold 不新呼叫模型；非完整 adaptive 生成式 WFO。raw/manual／不支援版本明確拒絕；Oct8 仍 BLOCKED_NO_RUN |
| 真實 WFO／未見性 | 無合格真實 WFO 成果 | 只讀 protocol 發現完整 guard 與 170 consumed bars 重疊 | 零新評估／reservation；不能縮 windows、換 registry 或稱 excluded holdout 全未碰；historical replay 仍 non-independent／non-rankable／non-paper |
| 現有績效／匯出 | PnL、成本、報酬、回撤、closed lots、win rate、日報酬；JSON／CSV 與防公式注入 | PF／Sharpe 與普通繁中摘要、未定義／未提供原因已整合；完整 IDs／巢狀紀錄留進階 | 未推送／未發布；開倉 PnL／無 closed lots 語義保留；無 PDF／投組最佳化／風險比率大全 |
| Profit Factor | 尚未提供必要欄位 | 手算／獨立審查後已整合至候選，含 root 全套；未發布 | 依已平倉 FIFO net PnL，含分攤費用；無 losses／無平倉明示 null；native final-head 待驗 |
| 描述性 Sharpe | 已發布為 None 並說明缺假設 | 候選已整合固定 252、rf=0、ddof=1／Decimal context，普通繁中假設／短樣本／缺日期標示 | return 可能跨日；不足 2 returns／零變異明示 null；不可當策略晉級或可靠性證明；未發布 |
| 比較／選擇／停用 | 既存結果並排、hash 綁定不可變選用、停用阻新單、重載 | 原行為保留 | 無相關性／portfolio weights／共變異數最佳化；選擇不是真下單 |
| Fixture AI | 預設離線固定候選 | 原標示保留 | 不是真模型，不改標 real_model_verified |
| 本機相容 HTTP | loopback、有限 schema／預算／明示同意 | 原流程保留 | 實際紀錄為 llama.cpp＋Qwen，非 Ollama 已驗證；應用不自動裝／啟模型 |
| 遠端相容 API | 明示 HTTPS endpoint／model／key reference／預算 | 無新增服務認證 | 預設關閉；目的地／資料／費用需同意；不可未授權 paid fallback |
| 手動 AI 交換 | 受限 training context 匯出／strict JSON 匯入、來源 hash | 原流程保留 | manual_unverified；不操作 ChatGPT 網站／cookies，不執行回傳程式 |
| 官方 ChatGPT 訂閱 | 自有 PKCE／OIDC、DPAPI／ACL、model discovery／Responses、跨 registration unknown barrier 已發布 | PR #5 補既有 CI interpreter 依賴目標／真正 preflight | 真 grant、資格、model discovery／inference 尚 NOT_VERIFIED；每次網路同意、不借其他 app token |
| 真本機模型結果 | 累計 14 次有界免費呼叫之技術證據；3 structured 候選完成研究 | 原負結果保留 | trend OOS −33,820、holdout −49,546 TWD；另 2 無交易。distinct improvement 非獲利改善，無可宣稱贏家 |
| Paper journal／冪等／故障 | SQLite journal、intent／order／fill identity、重放、quarantine／unknown 阻單、對帳 | PR #5 exact-byte 有界 memoization 與空 cursor 原子交易 | 模擬／事故 fixture 不等於真券商、硬體斷電／多機故障保證 |
| Paper 固定風控／摘要 | 1 口部位、1 口單筆、日損 1,000、報價 30 秒、連虧 3、60 秒 20 筆；0.2.1 普通頁可見 | 原硬限制不降低 | 不是可任意調高的一般設定；reservation、資金／margin／session 仍檢查 |
| Paper 普通 margin／重播 | 歷史 replay／持久 plan／cursor；舊 host 固定 margin 與合法 typed policy 可能衝突 | 候選以 broker pinned effective-date schedule 修補，120,000／跨交易日及 早期來源等價候選 981 項證據 | d598b39 的 Win312 原 960-bar／30 秒再次 FAIL，Server 原生流程 PASS 不替代矩陣；舊 ledger 保留／拒絕，無盤中 stop/target replay |
| 急停／睡眠／重啟 | 新單停止與對帳鎖、worker 停止／單例 | smoke 隔離和 terminal/cleanup proof 必須最終原生重驗 | 停止不等於平倉／撤全部單；整棵 worker tree 未停止不可當 terminal |
| Smoke 驗收隔離 | 後續已重現先前 smoke startup 改寫 broker／safety 的缺陷 | 全 startup temporary root／terminal／路徑修補已有 d598b39 Server frozen／安裝／升級／復原 PASS | 目前工作樹含 981 項檢查點之後的變更，最後完整／native 待驗；精確 no-write／全目錄／stop proof 標準不變 |
| 工作區／偏好 | per-user state、下次切 workspace、watchlist／圖層／geometry | 原 schema 與控制分離保留 | 不自動搬移／merge，切工作區不重置 budget／holdout；一次網路同意不保存 |
| 金鑰／日誌／通知 | Windows DPAPI、非 Windows fail closed；去敏本機事件／可選提示 | 既有 fixed dependencies／原生 preflight 持續驗證 | 不備份秘密，不保證遠端帳戶或真正 grant |
| 備份／還原 | manifest／hash／ZIP 上限、防 unsafe paths、staging rollback；還原後重新對帳 | 既有升級／恢復證據保留 | 無雲同步／排程／加密 ZIP；不回退 bootstrap authority；可能包含 state 內 market cache，權利需遵守 |
| 背景作業／資源界線 | allowlist、spawn、bounded IPC、mutex／Job Object、取消／關閉 | WFO owner marker／stop proof 已整合至未發布工作樹；早期來源等價候選 981 項，後續變更不涵蓋 | 非無人值守 daemon；memory bounds 按平台實證；新來源原生 gate 待驗 |
| 安裝／升級／移除 | bundled x64 runtime、per-user installer／捷徑、拒 active app 更新／移除、保留資料／復原 | PR #5 以真 0.2.1 為 upgrade baseline，最後完整 lifecycle 待驗 | clean client Win10／Win11 尚 EXTERNAL_BLOCKED；unsigned preview 不繞過警告 |
| 更新／供應鏈／main 保護 | 開官方 Releases，lock/hash／manifest／notices／scan；0.2.1 assets 已校驗 | d598b39 完整 CI 7/8 PASS，Server build/security PASS；新整合工作樹尚待 exact-head；正式 Win313 lock 不變 | 無背景自動更新或簽章；runtime audit 不包含 bootstrap 工具；main protected=false／403 未解除 |
| 真 broker／即時 feed／實盤 | 固定禁用，LiveBroker 拒絕 | 無啟用工作 | 無真帳戶／真委託／平倉／無人值守；可看行情不等於可交易 |
| 原系統能力與延後項 | 舊 CLI／股票／期權／通知等原碼仍保留，F01–F35 詳列於歷史 | 不重寫整個 legacy | 舊 Shioaji／Telegram／LINE／選股存在不代表新桌面已整合或安全；Average Trade／Sortino／Calmar／完整成本壓力測試屬尚未採用的設計延伸，提案照留，不自行加成本輪驗收門檻 |


### 04:24 整合來源 Gate 更新

- 候選修補完整 Linux root suite：773 項，758 PASS＋15 個既有 native Windows／PowerShell applicability skips，127.279 秒、exit 0；歷史掃描 0 findings。涵蓋 smoke 終態、canonical fixture 與 FULL 設定失敗關閉連線，SQLite mode／耐久邊界／既有門檻不變。此結果取代上文針對較早來源的「最終 root 待驗」，原生 exact-head CI 仍待。
- Qt CI-only 相容鎖及獨立 Linux311 套件稽核已納入 workflow；官方來源、完整 SHA-256、強制重新安裝及 pip report 保留。Windows 產品依賴鎖不變；套件 advisory audit 不等於所有 native library 已安全認證。
- 後續 WFO／報表 combined staging 完整 947 項：932 PASS＋15 既有 applicability skips，270.314 秒。再套用同一 Paper 連線小修補後 5 項 storage regression PASS；仍非已發布或 Windows／真實研究驗收。


驗證位置補註：981 項在隔離候選工作樹執行，25 檔複製當下的 bytes 由 root-integration-manifest.json 綁定；其後已加入 CandidateSummary 與 diagnostic-only 變更，不能把早期來源等價延伸為最終 root 全套通過。較早真正 root 全套 773 項、候選 981 項、後續 root 97／145 項各自保留範圍；最終完整／原生 CI 待驗。

<!-- CURRENT_STATUS_END -->

## 歷史原文與逐次證據（依原記錄保留）

以下完整保留本次整理前的內容、要求、來源、失敗與各時點判定。內文即使寫「目前／最新」，也只屬原有日期快照；現在的交付與下一步以本檔最上方有日期的摘要為準。原始基線盤點、固定驗收條款與年代順序均未被當成新版本成功證據。


本文件回答原始系統可在程式碼中找到哪些能力、哪些仍缺少，以及哪些適合用於 TMF 研究平台。基線已有行情、訂單、持倉、UI 與通知程式；沒有可供確認的完整歷史回測核心、AI 研究閉環或不可變策略庫。不能從交易程式存在推論交易安全、績效正確或可長期無人值守。

## 1 範圍與狀態定義

查核日期為 2026-10-09 UTC；所有原始碼連結固定在 `1cacce4ee4eef4ce7e8760f8153ef64a74852d22`。完整範圍為 47 檔、38 個 Python 檔；AST 語法解析通過。沒有執行原系統、安裝套件、登入 broker 或測試通知。

- **完成（程式層）**：實際找到可追蹤的處理路徑，不代表整合／執行已驗證。
- **部分完成**：存在一部分能力，但缺關鍵元件、適配或安全／正確性條件。
- **僅文件**：找到主張／範例，缺少能完成該功能的程式。
- **未實作**：在本次完整受追蹤樹未發現；不推論未公開或未受追蹤部署的內容。
- **Mock**：只有模擬替身且明確標示；基線未找到可宣稱為 AI／研究核心的 Mock 實作。
- **驗證未測試**：靜態存在已核對，runtime 沒有執行。**BLOCKED** 表示缺失元件或安全條件使該驗證目前不能成立。

下表把實作與驗證分欄。新增 `quantlab/` 與修補不回填到基線欄；當前成果請看 [ACCEPTANCE.json](../agent/ACCEPTANCE.json)，目標與驗收請看 [04](04_AI_QUANT_TARGET_DESIGN.md) 及 [05](05_IMPLEMENTATION_ROADMAP.md)。

## 2 完整主要功能表

### 2.1 操作與交易功能

| 功能與使用者用途 | 檔案 類別 主要函式與證據 | 實作狀態 | 驗證狀態 | 相依模組 | 問題與限制 | 沿用判斷 | 具體改進 |
|---|---|---|---|---|---|---|---|
| F01 CLI 任務選擇：執行選股、下載、訂閱或自動交易 | `run.parse_args`／`tasker.get_tasks`；[入口](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/run.py#L7-L26)、[派送表](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/tasker.py#L275-L275) | 完成（程式層） | 未測試 | trader／config／tasker | 參數解析前即匯入交易套件；預設 auto_trader | 保留舊入口，研究替換 | 新增離線 CLI，help 與 import 不碰 broker |
| F02 帳戶設定：建立、修改、刪除交易設定 | `gui.user_settings_form`／`update_user_settings`／`delete_user_settings`；[表單與設定寫入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L213-L309) | 完成（程式層） | 未測試 | Streamlit／SQL／UserSettings | 秘密與普通設定混存，未找到應用層登入保護 | 保留情境，修改 | 研究不需要真帳戶；未來秘密獨立保管、UI 有認證 |
| F03 程序控制：啟停、查看執行狀態 | `gui.start_trader`／`render_control_panel`；[啟動](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L96-L123)、[控制面板](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/gui.py#L319-L373) | 完成（程式層） | 未測試 | subprocess／runtime／run.py | 按鈕可能啟動交易；控制命令不等於執行已完成 | 修改 | 研究 UI 僅啟動離線任務；狀態與結果持久化 |
| F04 帳戶查詢：資金、庫存、已實現損益與配額 | `AccountInfo.query_all`／`get_account_margin`／`get_futures_positions`；[帳戶查詢路徑](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/accounts.py#L305-L460) | 完成（程式層） | 未測試 | Shioaji／SQL／pandas | 必須登入；查詢回傳不是本地研究帳本 | 保留 adapter 參考 | 區分唯讀帳戶 port 與送單 port，保存快照時間 |
| F05 股票與期貨委託：建立並送出買賣單 | `OrderTool.place_order`；[訂單與送單](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L800-L904) | 完成（程式層） | 未測試，LIVE 禁用 | API／合約／TradeData／帳戶 | broker-specific；模擬／正式依共享旗標選分支 | 保留隔離，未來抽 adapter | 寫入 intent 後送單；未知結果先對帳 |
| F06 選擇權與組合單：搜尋契約和組合建單 | `get_option_contract`／`OptionOrderFactory`／`place_combo_order`；[契約選取](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/options.py#L87-L127)、[組合委託](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L757-L799) | 完成（程式層） | 未測試 | Shioaji option 合約與回報 | 非 TMF MVP；多腿完整成交與風險未驗證 | 保留，延後整合 | 先完成單商品事件帳本；多腿另訂驗收 |
| F07 委託及成交回報：接收股票／期貨事件 | `StockOrder`／`StockDeal`／`FuturesOrder`／`FuturesDeal`；[回報處理](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L906-L1015) | 部分完成 | 未測試 | callback／TradeData／DB／通知 | 未有重複、亂序、timeout、cancel race 的測試證據 | 修改 | 唯一 event ID、持久 journal、重放與 quarantine |
| F08 持倉管理：策略部位、手工單與 watchlist 同步 | `WatchListTool.sync_strategy_position`／`TradeDataHandler.unify_monitor_data`／`Position`；[策略同步](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/positions.py#L368-L450)、[監控整併](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/positions.py#L640-L766) | 部分完成 | 未測試 | 全域狀態／broker／DB | 斷線及重啟後權威狀態、外部手工單處理未驗證 | 領域概念保留，核心替換 | broker／fills／cash 三方對帳；差異顯式阻單 |
| F09 交易額度與口數控制：防止超量開倉 | `AccountHandler._set_trade_risks`／`_set_margin_limit`、executor 檢查；[風險設定](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/accounts.py#L516-L558)、[持倉與數量檢查](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/executor.py#L652-L761) | 部分完成 | 未測試 | 帳戶／設定／報價／TradeData | 未證明為不可繞過的集中風控；無持久日損及故障矩陣 | 參考後替換 | 單一 RiskGate、日損／頻率／資金／行情年齡與 hard limits |
| F10 本地模擬記帳：不走部分真實送單分支 | `Simulator`／`OrderTool.place_order`；[模擬記帳](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/simulation.py#L10-L44)、[模式分支](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/orders.py#L843-L890) | 部分完成 | 未測試 | 全域模式／行情／持倉 | 模擬仍可能登入；不是歷史撮合引擎或持久 paper broker | 替換核心 | 全離線 PaperBroker、風控、事件重放與恢復 |
| F11 動態多策略 hook：按策略名稱呼叫進出場與口數 | `StrategyList`／`StrategyTool.mapFunction`／`mapQuantities`；[策略載入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L125-L150)、[映射](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/strategy.py#L29-L45) | 部分完成 | 未測試 | 私有 strategy 檔／DB／TradeData | 庫內未附正式策略；動態 Python 不安全隔離 | 保留概念，替換研究介面 | 受限 DSL＋不可變版本；策略只產生 intent |
| F12 Telegram 遠端控制：查部位、暫停／恢復／停止、改最大口數 | `TelegramBot`；[授權檢查](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/bot.py#L168-L195)、[控制指令](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/bot.py#L277-L438) | 部分完成 | 未測試，安全阻塞 | token／允許名單／executor | 空白名單放行；群組授權不是成員授權 | 修復後保留 | user 與 chat 雙重 stable ID、空白拒絕、敏感操作稽核 |
| F13 通知：成交、委託、帳戶及選股訊息 | `TelegramNotify`／`LineNotify`／`Notification`；[通知封裝](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/notify.py#L8-L84)、[業務通知](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/notify.py#L109-L233) | 完成（程式層） | 未測試 | 外部通知服務／設定 | 服務可用性、憑證、投遞確認未驗證；含帳戶資訊風險 | 修改後保留 | 明確選用、去敏、失敗計數與投遞狀態；研究預設關閉 |
| F14 runtime 與日誌檢視：看帳戶狀態和下達本機指令 | `write_status`／`write_command`／`command_is_expired`／`tail_lines`；[runtime](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/runtime.py#L24-L149) | 部分完成 | 未測試 | 本機檔案／GUI／bot | JSON 原子替換有用；缺失／無效命令時間未失敗關閉，非交易 journal | 抽取技巧，修改 | 嚴格識別碼與期限；狀態機、鎖定及帳本分離 |

### 2.2 資料與研究相關功能

| 功能與使用者用途 | 檔案 類別 主要函式與證據 | 實作狀態 | 驗證狀態 | 相依模組 | 問題與限制 | 沿用判斷 | 具體改進 |
|---|---|---|---|---|---|---|---|
| F15 即時行情訂閱：收標的與指數報價 | `Subscriber.update_quote_v1`／`subscribe_targets`／`subscribe_all`；[更新與訂閱](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/subscribe.py#L53-L142) | 完成（程式層） | 未測試 | broker callback／TradeData | 未驗證行情 gap、延遲、sequence 與重連補洞 | adapter 參考 | 事件／接收時間、stale gate、gap 停機 |
| F16 broker 歷史 K 線：載入與合併歷史 | `KBarTool._fetch_history_kbars`／`history_kbars`；[歷史資料](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/kbar.py#L110-L179) | 完成（程式層） | 未測試 | Shioaji／pandas／儲存 | 授權、回溯深度、修訂與完整性未驗證 | 改為 provider | 限速重試、schema／coverage 檢查、來源 manifest |
| F17 公開行情下載：期貨 tick、保證金及其他市場資料 | `CrawlFromHTML.get_FuturesTickData`／`get_IndexMargin`；[期貨資料與保證金](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L602-L638) | 部分完成 | 未測試，安全阻塞 | HTTP／ZIP／檔案系統 | verify=False、下載及壓縮檔驗證不足 | 重寫輸入邊界 | 先 local-only；白名單格式與大小、TLS、授權註記 |
| F18 Tick 轉 K 線與多頻聚合：1 分及多週期訊號資料 | `TickDataProcesser.preprocess_futures_tick`／`tick_2_kbar`、`KBarTool.convert_kbar`；[重採樣](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/kbar.py#L181-L195)、[tick 時段與聚合](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/kbar.py#L373-L454) | 部分完成 | 未測試 | pandas／日期設定／欄位假設 | 日夜盤粗分；night_only 未實際套篩選；資料缺漏與端點語義未驗證 | 公式參考，重建 | 以具版本 calendar 聚合；保留空分鐘與缺資料差異 |
| F19 技術指標：SMA、STD、MACD、RSI、KD、EMA、ATR 等 | `TechnicalSignals`；[均線與振盪指標](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/indicators/signals.py#L49-L192)、[其他指標](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/indicators/signals.py#L211-L378) | 完成（程式層） | 未測試 | pandas／NumPy／時間序列 | warmup、初始化、NaN 與 reference 一致性未測 | 可抽取後沿用 | 純函式、prefix 因果測試、逐筆人工 golden |
| F20 選股：載入選股腳本與篩選資料 | `SelectStock.set_select_scripts`／`pick`／`export`；[選股管線](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/select.py#L53-L139) | 部分完成 | 未測試 | 外部選股腳本／市場資料 | hooks 存在但未附正式選股策略；非 TMF 優先 | 保留，延後 | 不把股票特定邏輯帶入 TMF 研究根 |
| F21 其他市場資訊：除權息、PutCallRatio 等 | `runCrawlPutCallRatio`／`runCrawlExDividendList`、crawler 對應函式；[資料任務](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/tasker.py#L111-L128)、[抓取與匯出](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/crawler.py#L408-L481) | 完成（程式層） | 未測試 | 外部 HTML／檔案／SQL | 端點、欄位、授權與公告可用時間待驗證 | 保留參考 | 若當策略特徵，加入 published_at 與 revision，防未來資訊 |
| F22 資料存取：SQL／SQLite／Redis／檔案 | `SQLDatabase`、Redis 與 file handler；[SQL](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/sql.py#L17-L55)、[Redis 反序列化](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/database/redis.py#L78-L93)、[pickle 讀取](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/file.py#L61-L61) | 完成（程式層） | 未測試 | DB credentials／本機儲存 | import-time 連線、pickle 信任、無資料版本 | 替換研究儲存 | CSV／JSON／SQLite，拒絕 pickle；明確建構生命週期 |
| F23 績效數值：交易轉換、獲利與回撤統計 | `convert_statement`／`compute_profits`；[損益計算](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L69-L119)、[績效函式](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L122-L213) | 部分完成 | 未測試，正確性阻塞 | StrategyList／交易欄位／乘數 | actual 分支費用為 0；TMF margin 缺失；空單勝率符號順序問題 | 替換計算核心 | 用 ledger／equity 計算，固定 costs／multiplier／rounding |
| F24 圖表：K 線、線圖、交易標記與輸出 | `SuplotHandler.add_candlestick`／`add_line`／`add_marker`／`export_figure`；[圖表工具](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/charts.py#L19-L146) | 完成（程式層） | 未測試 | Plotly／資料欄位 | 圖表看起來合理不證明帳務正確 | 可保留呈現概念 | 圖表綁定 run hash、資料來源／OOS／成本標記 |
| F25 綜合報告入口：整理回測／交易報告 | `trader/performance/reports.py`；[報告匯入](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/reports.py#L9-L18) | 部分完成 | BLOCKED | 缺少 `.backtest.BacktestPerformance` | 靜態相對匯入唯一直接缺失模組；不能宣稱可產出完整報告 | 替換入口 | 新 reporting 只接受驗證過的 BacktestResult |
| F26 策略範例：示範資料與策略類別 | `docs/script samples/strategy_sample.py`；[佔位資料](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/docs/script%20samples/strategy_sample.py#L11-L20)、[Position 建構](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/docs/script%20samples/strategy_sample.py#L102-L109) | 僅文件／示意碼 | BLOCKED | 私有資料／Position | 類別定義時 Position() 缺必要參數；無法當標準驗收案例 | 替換示例 | 五個獨立、合成資料可重現、無 broker 的策略 |

### 2.3 目標需求但基線未提供的功能

以下缺失依完整固定[原始樹](https://github.com/yostar77612/mark-auto/tree/1cacce4ee4eef4ce7e8760f8153ef64a74852d22)及上述實際呼叫路徑判斷，沒有以 README 宣稱作為成功證據。

| 功能與使用者用途 | 路徑／證據或缺失邊界 | 實作狀態 | 驗證狀態 | 所需相依 | 問題與限制 | 沿用判斷 | 具體改進 |
|---|---|---|---|---|---|---|---|
| F27 歷史回測撮合：可重放的訊號、委託、成交與帳本 | [匯入缺少的 backtest](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/reports.py#L18-L18)；樹中無 BackTester／BacktestPerformance 實作 | 未實作核心 | BLOCKED | snapshots／calendar／cost／engine | 無法驗證歷史 fill 或重現績效 | 新建 | 因果 next-event 撮合與 golden corpus |
| F28 TMF 完整市場模型：契約、時段、到期、成本與換月 | [僅有費用參數線索](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L92-L92)、[非 TMF margin 映射](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L77-L81) | 部分完成的泛期貨支援 | 未測試／缺資料 | 官方規格／歷史 calendar／費稅 | 商品參數出現不等於 TMF 驗收 | 新建模型 | 顯式實際月份；禁止用連續價格結算 |
| F29 資料快照庫：追蹤來源、授權、品質與 hash | 全樹未發現相應 manifest／registry | 未實作 | 無法驗證 | 匯入器／schema／calendar | 檔名不足以識別資料修訂 | 新建 | 不可變 Dataset＋品質報告＋license_note |
| F30 AI 行情分析及策略產生：候選與理由 | 全樹未發現 AI provider、受限 DSL 或候選生成流程 | 未實作 | 無法驗證 | DSL／provider boundary／budget | 不存在可證明的真實模型連線 | 新建 | FixtureGenerator 預設離線；真模型另記 NOT_VERIFIED |
| F31 AI 最佳化與批次研究：改善、比較與停止 | 全樹未發現 campaign、trial store、預算帳本 | 未實作 | 無法驗證 | 因果 engine／DSL／結果儲存 | 任意參數搜索不等於可靠改善證據 | 新建 | generate→evaluate→improve；15 trials 上限與全部嘗試記錄 |
| F32 OOS／walk-forward／holdout：防洩漏與過度擬合 | 全樹未發現 split manifest、purge／embargo、holdout 存取紀錄 | 未實作 | 無法驗證 | 時序資料與 campaign policy | 未見樣本不足不能以合成績效補足 | 新建 | 凍結邊界；生成器不見 OOS／holdout；使用標記持久化 |
| F33 策略版本庫與比較選擇：保存多策略並人工決策 | 動態 Python hooks 不構成 immutable registry；全樹未發現對應功能 | 未實作 | 無法驗證 | spec／data／engine hash 與結果 | 沒有可追溯排名、核準或多策略相關性分析 | 新建 | 內容定址版本、成本後排名、風險相關性、選擇不啟動交易 |
| F34 可驗證 paper 恢復與正式就緒：事故後不重複單 | 模擬記帳見 F10；無完整故障重放 corpus | 未實作完整能力 | BLOCKED | durable journal／risk／adapter contracts | 未知委託不可盲重送；真 broker 未認證 | 新建並隔離 | 故障矩陣、對帳、kill switch；LiveBroker 永遠拒絕 |
| F35 自動化品質門檻：離線測試、CI 與可重現部署 | 全樹無 tests／workflow／lock；[基線忽略規則](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/.gitignore#L133-L146) | 未實作 | 無法驗證 | 測試資料／受控依賴／CI | `*test*.py` 被忽略；無執行證據 | 新建 | 純離線測試、拒網路／broker、fresh checkout 驗證 |

## 3 盤點數量與解讀

上述 35 個功能單位覆蓋本次主要使用者功能，並非函式數或通過測試數。F01–F26 為程式／範例可定位的現有能力；F27–F35 為目標缺口與部分泛期貨適配。個別現有能力的下單、通知、帳戶操作均未執行，不能用「找到 26 項」換算「26 項已測試」。

本基線沒有任何可據本次查核宣稱 runtime PASS 的主要功能。AST 解析通過只回答語法是否可被解析；回測 correctness、broker compatibility、UI 操作與無人值守均須各自的驗收證據。

## 4 重用清單與成本控制

- **保留不動：** LICENSE／既有來源標示、非 TMF 的股票與選擇權領域程式，避免為研究 MVP 大幅改寫無關能力。
- **保留設計知識：** 帳戶快照、委託／成交／庫存概念、圖表構成、Streamlit 使用方式、操作狀態顯示。
- **抽取後重用：** 指標公式、可純化的資料轉換、JSON 原子替換技巧。抽取必須建立新測試與明確輸入型別，不能直接把 `trader` 匯入依賴帶過來。
- **新增必要核心：** calendar、TMF contract／cost、data snapshot、事件帳本回測、受限 DSL、campaign、immutable registry、durable paper journal。
- **暫不整合：** 真實券商、通知帳戶、外部資料訂閱、付費模型、完整策略投資組合最佳化。它們不應成為離線研究閉環的前置依賴。

## 5 驗證計畫與不可誤用的證據

原有程式碼的回歸應在 broker／資料庫／HTTP／通知全部替換或不可到達的環境進行；「設定 Simulation」不足以保證離線。新研究核心的 smoke test 必須不匯入 `trader` 或 `shioaji`，不讀取真憑證，失敗時明確輸出原因。

新功能最低驗證分三層：

1. **單元與 golden：** 手算 TMF 多空損益、費稅、次根成交、時段、訊號因果、無效 DSL 與資料拒絕。
2. **跨模組整合：** local data→quality→strategy→backtest→ledger→report→persistent registry；同輸入三次 hash 一致。
3. **操作與恢復：** UI 空資料、錯誤、重複點擊、重啟；paper partial fill、timeout、重複／亂序、對帳與 stale quote。模型與 broker 實際整合驗證另行處理。

完成新測試後應留下命令、環境、版本、退出碼與逐項結果；不得在本表基線行號上覆寫成「已修好」。原有缺陷與修補證據應分列，讓讀者能分清是原始能力、目標能力或已交付變更。


## 桌面後續交付對照

原始表仍對應固定基線，不把新增模組倒填成原本具備。現有新增桌面提供繁中總覽／資料匯入下載／策略與生成候選版本／日期與參數批次回測／報表比較選擇／Paper對帳重播急停／模型設定與安全備份。主要計算、下載、研究與備份在受控程序執行；大型本機資料或結果的顯示解析仍有同步部分，需用基準決定是否優化。

來源證據為 `desktop_ui.py`、`quantlab/desktop_runtime.py`、`desktop.py` 及 `tests/test_desktop_ui.py`／`tests/test_desktop_runtime.py`。真券商、真模型語義、正式策略績效及乾淨Win10/11驗收並未因此變成已驗證；完整狀態只依ACCEPTANCE.json。GUI的fixture模式與loopback協定測試不冒充外部AI研究成功。

## 0.1.2 功能與驗收對照（接續驗收）

| 功能 | 實作狀態 | 實際證據／仍有限制 |
|---|---|---|
| 原生繁中桌面、總覽、設定 | 已實作 | Qt功能回歸；clean Win10/11未驗證 |
| 免費行情下載、匯入與品質 | 已實作並用真官方資料驗證 | 30 ZIP校驗；12日13,680分鐘+24盤OHLC；缺盤首/尾/整盤拒絕；無自動補造 |
| 因果回測、成本、資金曲線、CSV | 已實作 | 固定Golden與真資料技術回測；費用/流動性仍需正式參數 |
| 真AI策略生成 | 已窄範圍整合驗證 | 官方1.5B受限schema產3候選；一般JSON模式失敗保留，不冒充自由程式創造 |
| OOS、holdout、多策略比較 | 已技術驗證 | 真生成候選完成分割；1虧損2零交易，無正式排名/投資資格 |
| Paper、持倉、對帳、風控、急停 | 已實作並故障回歸 | 61focused tests；新單在不確定狀態保持封鎖；不等於真券商重連 |
| 機密、備份／還原、工作區 | 已實作，新增目的地保護 | DPAPI；備份不含credentials/不可回退controls，拒絕覆寫內部路徑 |
| 安裝、更新、移除 | 已實作新版versioned payload | 必須待Windows CI真升級／中斷恢復；unsigned；不自動下載執行更新 |
| 無開發工具的Win10／Win11完整驗收 | 工具/程序已備，未實測 | kit使用內建PowerShell，EXTERNAL BLOCKED，不能以Server當PASS |
| 實盤與券商 | 固定停用／未驗證 | 無真資金送單或帳戶資格宣稱 |


## 附錄 A：當前產品完整功能與驗收對照（2026-10-10 UTC）

狀態快照更新至 2026-10-10 02:23 UTC。本附錄為有日期的實證快照；後續狀態補記於 A.11，不能以先前PASS覆蓋新來源。

本附錄補充前文固定於 `1cacce4e` 的原始系統盤點，不回寫歷史事實。前文的「原始功能存在／缺失」與此處後續新增的 `quantlab`／原生桌面能力是不同版本；舊 `trader` 程式存在，也不表示新桌面提供該項交易功能。

### A.1 交付身分與閱讀方法

**目前可下載的是 0.2.0 未簽章（unsigned）preview；現有驗收帳本記錄 195/300＝65%，不是正式投資或生產就緒。** 本次另確認 walk-forward 必要研究規範仍未實作及兩個普通操作缺口；帳本既有分數不可被擴張成完整需求已全部接受，新增發現須由整合者依原條款重新核對，不能自行改分母或補分。

| 版本／工作範圍 | 身分與已知證據 | 可以宣稱的狀態 | 不得混同 |
|---|---|---|---|
| 已發布桌面 0.2.0 | `main fc2dfacbf297004095e971ec10cf3620307417a2`，tree `853300ac530a88f58790562232a3de2a31ab5467`；[Release](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38013204925-1) 的 EXE／clean-client kit 已實際下載核對 | 可下載、原生研究／Paper 預覽版；M1、M5 已按固定條款通過 | Release 存在不等於乾淨 Win10／Win11 或所有新增市場功能驗收通過 |
| 已合併 0.2.1，發布品驗證中 | PR #4 已合併為 `main 2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`，tree `12804de7477ce6ca2da5d11d474240a795bd9025`，與最後 head `f11e2ef`／本地 `fea95b2` 相同 | 最終 head 七個 Quantlab jobs PASS；[Windows 38016153320](https://github.com/yostar77612/mark-auto/actions/runs/38016153320) build／security PASS，644 tests＝633 PASS＋11 明示 skips；frozen auth、安裝、真 0.2.0 升級與恢復 PASS。跨 registration barrier 修正已包含 | **發布／下載完整性尚未完成驗證**：postmerge 0.2.1 Release 流程進行中，不把 merge 或 CI artifact 冒充已校驗發布品；實際 user grant／inference 及 clean client 仍未測 |
| 下一個歷史行情模組 | 獨立 staging；`market_history.py` 與 UI／測試等六檔修改；最終獨立審查 159 測試 PASS，實際私有 CSV／RPT 各重跑成功 | 已完成受限本機匯入的來源／Linux Qt 工程證據；尚待整合、最終原生 Windows／frozen 驗證 | 不在已發布 0.2.0，也不因 staging 完成就算進 0.2.1；900 實際 bars 不等於發布產品已具 TX/MXF 分鐘匯入 |
| 後續到期表單／Paper margin 修復 | 同一後續 staging；到期表單9新測試及實際 training-only GUI 回歸獨立 PASS；Paper margin 另有20獨立 adversarial＋75 broker/replay/policy tests PASS | 普通 expiry 輸入及 pinned effective-date margin replay 已有受限工程證據 | 皆尚未合併到 `2ed1e3e`／0.2.1；需最後整合、全套／native／frozen gate。不能把新舊測試重疊相加成不重複功能數 |
| 必要 walk-forward 後續模組 | 已核准 built-in fixed-pool rolling evaluator，零 AI calls 的有界實作方向 | 開發規劃／後續實作，尚未完成 | 目前 released/main/staging 僅 fixed four-way split；不能稱已具 rolling walk-forward |

狀態用語：**已發布功能**只指 0.2.0 程式與對應工程證據；**已合併待發布**指 0.2.1 來源及指定 gate 成立但發布品仍待核對；**staging 實作**指後續模組尚未合併；**驗證有限**指只有所述來源／平台／情境成立；**未實作／未驗證／外部阻塞**各自保持原意。表格中的功能數量不是驗收計分單位。

以下 `[S01]` 等為本附錄末尾的固定原始碼連結；S01–S25 指向已發布 `fc2dfac`；S26–S31 明確指向已合併待發布的 `2ed1e3e`。函式名稱是可追蹤的實際路徑，不以 README 自述代替程式證據。報告中保留的公開 CI／Release 連結可直接核對；私有市場原始檔、帳本和研究輸入不隨本附錄重新散布。

### A.2 一般使用者實際可操作的七個頁面

| 編號／頁面 | 已發布 0.2.0 的操作與結果 | 實際程式證據 | 驗收與重要限制 |
|---|---|---|---|
| A01 市場總覽 | 四類商品摘要卡、自選新增／刪除／排序、商品及真實到期月切換；K 線、指標與持倉／委託／成交表；來源細節可展開 | `MainWindow._dashboard`、`MarketDashboard`、`load_market_cache`；[S01][S02][S03] | 首次未有來源可顯示「尚無資料」；不預載假市場行情。帳戶表是本地 Paper 狀態，不是券商帳戶 |
| A02 資料匯入與更新 | 檔案選擇、官方 daily JSON／CSV 市場匯入；研究 CSV／RPT／validated dataset 匯入；指定版本化 calendar 檔；建立明示合成示範；逐次同意後下載近 1–30 日公開檔 | `_data_page`、`execute_ui_operation(ui_import/ui_refresh/ui_market_refresh)`、`import_taifex`；[S01][S04][S05] | 下載不自動成為研究資料；選入檔案不等於已驗證其授權或完整性。研究匯入需已有合法來源及明示 calendar，沒有長歷史一鍵補齊／官方日曆自動維護 |
| A03 策略與版本 | 五家族與型別化參數；研究 split、次數、時間與排名條件；Fixture／相容 HTTP／手動 AI 交換；查閱候選、歷次嘗試及 OOS／holdout；選不可變候選供研究 | `_strategy_page`、`StrategyForm`、`CampaignForm`、`candidate_record`；[S01][S06][S07] | 預設 Fixture 不是真 AI。沒有任意 Python 編輯執行器。自訂 DSL 候選是唯讀版本，不會悄悄轉成可編輯內建策略 |
| A04 回測與結果 | 日期篩選、資金／費用／稅率／滑價／保證金／seed 表單；單策略或五家族預設參數批次；資金曲線、摘要、成交表、已保存報告；回測 signal／fill 各自開關 | `_backtest_page`、`BacktestForm`、`ui_backtest`、`EquityPlot`；[S01][S06][S08] | 預設費率及保證金是合成假設。**0.2.0 實際資料必要到期日仍無普通表單欄位**；後續 staging 已修且獨立重現通過，見 A.10；尚不能說已發布真實資料全流程已不需 JSON |
| A05 比較與策略選擇 | 多選既存結果比較；保存具 hash 的選定策略；停用策略並禁止 Paper 新委託；結果可重載 | `_compare_page`、`comparison_rows`、`save_selection/load_selection`；[S01][S09] | 是個別結果並排，沒有自動投資組合權重、跨策略相關性／共變異數、組合風險最佳化。選擇不是送出真實委託 |
| A06 紙上交易與復原 | 明示時段及保證金政策表；帳戶快照、完整參考快照對帳、急停、分批歷史重播；委託／報價／撤单操作；讀取帳本與狀態 | `_paper_page`、`PaperPolicyForm/IntentForm/QuoteForm/SnapshotForm`、`ui_paper_*`；[S01][S06][S10][S11] | 沒有即時 feed 或券商。重啟後需明確對帳；停止是禁止新單，不會自動平倉。固定風控值在 0.2.0 正常頁面缺少完整顯示，0.2.1 已合併修正，發布品待核對 |
| A07 設定與備份 | 下次啟動工作區、相容模型 endpoint／model／預算、Windows 金鑰儲存、本機精簡日誌／提示、偏好保存、本機備份還原、開啟 Releases | `_settings_page`、`WorkspaceLocator`、`CredentialVault`、`BackupManager`；[S01][S12] | 開啟 Release 網頁不是自動更新檢查、下載或安裝；非 Windows 不以明文 fallback 儲存金鑰。工作區變更不自動搬移現有資料 |
| A08 共通操作 | 繁中深色、狀態／錯誤、背景作業進度、取消；一次一工作；主頁不必顯示技術 JSON，診斷可收合 | `MainWindow`、`JobManager`、`RuntimeGuard`；[S01][S12] | 原生 Qt 工程／Linux 截圖與 Server 包裝測試已做；最終 client OS 的鍵盤、DPI、短視窗全流程仍未完成。深色是目前實作的主題，沒有已驗證的深／淺主題切換 |

CLI 與選用 Streamlit 研究入口仍存在，使用同一核心與序列化契約；它們不是取代原生 Windows 安裝驗收的理由。新桌面不匯入舊 `trader`、不要求 broker 登入。舊選股、期權組合單、Telegram 遠控、LINE 通知與真帳戶交易不是這份桌面預覽版的已整合功能。

### A.3 商品、來源、時間週期與資料完整性

| 商品／能力 | 已發布可用來源及粒度 | 可用圖表週期 | 研究／Paper 資格與限制 |
|---|---|---|---|
| 加權指數 TAIEX | TWSE 公開 `MI_5MINS_HIST` 原始 JSON，**實際 schema 為日 OHLC**；無成交量則保留缺值 | 日、週；不能由此製造任何分鐘線 | 唯讀市場；沒有已驗證的指數分鐘資料來源、即時 entitlement 或指數研究撮合 |
| 大台 TX | TAIFEX 原始每日／時段行情 JSON 或 CSV；保留每個實際合約月份／weekly identity | 日、週；0.2.0 沒有產品級 TX 分鐘匯入入口 | 市場可看不等於回測可交易；研究核心不接受 TX |
| 小台 MXF | TAIFEX 原始代碼 **MTX**，UI 顯示 **MXF**；實際 contract identity 仍保留 MTX | 日、週；0.2.0 沒有產品級 MTX/MXF 分鐘匯入入口 | 不能把顯示別名當來源原始代碼；研究核心不接受 MTX/MXF |
| 微型 TMF | 官方每日／時段行情；另可將合格 TMF 研究分鐘 dataset 及其明示 calendar 適配為市场圖表 | 有合格分鐘源時為 1／3／5／15／30／60 分、日、週；daily source 僅日／週 | 核心只接受 `TAIFEX:TMF:YYYYMM`、乘數 10、tick 1；資料品質、到期／成本／日曆仍各自驗證 |
| 後續本機歷史模組 | staging 支援明示 TX／MTX／TMF 到期月及日期時段的官方格式 CSV／RPT tick→分鐘 cache | 已有來源實驗 3 商品×8 週期、各 300 分鐘，共 900 bars | 尚未發布；它只寫市場 history cache，不寫研究 dataset，不取得研究／交易資格；仍沒有 TAIEX 分鐘線 |

程式證據：`quantlab/market_providers.py` 的 `parse_twse_daily`、`parse_taifex_daily`；`market.py` 的 `InstrumentRef/MarketBar/SourceProvenance/QuoteSnapshot`；`desktop_ui.dataset_market_series`；核心 `validate_contract/Instrument`；[S03][S13][S14][S15]。

**來源與 freshness 的實際行為**

- 官方更新由使用者明確觸發，使用限定 HTTPS 端點、大小／列數／時間限制及正常 TLS 驗證；無自動交易或背景付費訂閱。
- 每組市場資料保留來源 URL、SHA-256、歸屬／license URL、實际合約、exchange trade date、接收 UTC 時間及時間缺失原因。來源沒提供逐筆 exchange event time 時，明示未知，不把本機接收時間冒充交易所時間。
- 新啟動載入 cache 時先標 stale；更新失敗保留最後已知資料並顯示失敗／過期。歷史／EOD 快照沒有已驗證即時延遲，不能顯示為 realtime。
- 漲跌採前一筆**日盤收盤**參照；結算價獨立保存，不偷換計算基準。不足前收則顯示不足，不填 0。
- 本機檔案匯入保留 local-import 性質。符合官方 schema 或計算出 hash，不能單独證明任意輸入檔的真偽與授權。
- TAIFEX 無完整 OHLC 的列及不支援價差契約會被省略並計數／警告；不從結算價或隔日資料補造。原始 outright 成交量與每日含價差合計量口徑可能不同。

**聚合契約**（`chart_data.aggregate_bars`，`TIMEFRAMES`，`desktop_charts.CandlestickChart`；[S16][S17]）

- 分鐘以明示 session-open 錨定，不跨日／夜盤中斷；目標週期必須是來源分鐘數的整倍數。日線按 exchange trade date 合併日夜時段；週線採 ISO 交易日週。
- 對 exact duplicates 去重並提示；衝突 duplicate、混解析度、重疊、未知時段、較粗來源下採樣為細線均拒絕；亂序排序可追蹤。
- 缺 bar、未完成 bar、缺認證 calendar 或週尚未結束，保留 partial／完整性未知；不插值、不製造零量分鐘。正常 dashboard 未取得完整 calendar／as-of 證據時，日週聚合可以顯示，但不宣稱 coverage 已完整。
- 支援 OHLC／量、十字線逐根細節、滑鼠縮放與拖曳、鍵盤平移／縮放／復位。歷史交互不代表即時行情服務。

**實際資料證據，與產品取得能力分開**

1. 已核對一個 TMF202610、2026-09-17 至 2026-10-06 的 12 個連續公布交易日，共 **13,680 真實一分鐘 bars**；24 組日／夜盤 OHLC 與獨立每日來源吻合。這是有限技術樣本，並非多年完整資料庫或投資排名合格資料。
2. 2026-10-08 的 TMF **1,140 bars** 是獨立完整一天。2026-10-07 少一分鐘而拒絕；未以無交易猜測補齊，也未跨過缺口假裝連續。
3. 2025 年官方日／時段資料已下載：243 個交易日、6,483 筆 TMF 列；尚未完成所需 schema／契約／歷史 calendar 驗收，不是 2025 分鐘資料已可研究。
4. 下一模組真實檔驗證為 2026-10-08 白盤來源：34,363,020 bytes、677,441 列，TX／MTX／TMF 各 300 分鐘，合計 900；CSV／RPT 名稱路徑各測。各合約 OHLC 與日期相符的獨立 daily reference 吻合；outright volume 與 daily inclusive volume 的差異被保留。
5. 上述來源／衍生檔保留為私有研究證據，沒有因公開下載就宣告可重新散布。沒有以 synthetic fixture 替代任一「真實資料」數字。

### A.4 技術指標與圖層

| 指標 | 已實作公式／預設與缺值語義 | 產品／驗收狀態 |
|---|---|---|
| MA | SMA；預設 MA5／10／20／60；滿 n 根才有值 | UI 可開關／改週期；按圖表 bar 數計算 |
| EMA | n 個有效值的 SMA seed，再以 α＝2/(n+1) 更新 | 缺值會重置 warmup，不以 0 補值 |
| RSI | Wilder，預設 14；n 個價差 seed；全平 50、只有上漲 100 | 未成熟為缺值；prefix 因果／golden 已測 |
| MACD | 12／26／9，EMA 差與 signal；histogram＝MACD−signal，倍率 **1×** | 0.2.0 公式／柱狀圖存在，但實際 host 圖例未標倍率，故 M3 仍 PARTIAL；0.2.1 已合併修正，把實際圖例改為 `MACD histogram 1×` |
| KD | 9／3／3；K/D seed 50／50，區間高低，平幅 RSV 50 | 可改期數；以完整有效視窗計算 |
| Bollinger | 20／2；固定母體標準差 | UI 可改 period／deviations，非混用樣本標準差 |
| VWAP | 每個明示交易時段重置；以 `(H+L+C)/3 × volume` 累計估計；累計量 0 或缺量為缺值 | UI 明示 OHLCV typical-price approximation，**不是真實逐筆成交 VWAP** |
| 訊號／成交圖層 | signal：發生時間、target position、reason；fill：成交時間、價格、方向、量、費稅；菱形／三角形、各自可關閉 | M5 已 PASS；限定 hash 與實際合約一致的回測結果，不是券商成交，也未驗證 Paper journal→chart 圖層 |

證據：`quantlab/indicators.py` 及 `tests/test_indicators.py`；`MarketDashboard._apply_indicators`；`ChartTrace/ChartMarker`、`bind_result_layers`；[S02][S17][S18][S19]。切換圖表週期會重算，不把原分鐘指標直接搬到日線；來源 gap 會中斷連續指標狀態，未完成 K 線指標標示暫定。

實際歷史訓練區間圖層證據為 6,839 bars、1,917 signals、3,831 fills、5,748 形狀分開的 markers。這是回測及來源綁定證據；未因產圖重開 OOS／holdout，也不代表 5,748 筆真實成交。

### A.5 策略、回測、AI 研究與比較

| 編號／能力 | 目前實際提供 | 程式證據 | 必須保留的限制 |
|---|---|---|---|
| A09 五種策略家族 | 趨勢、均值回歸、通道突破、動能、波動壓縮；各自有參數及因果信號；quantity／stop_ticks／target_ticks 可填 | `builtin_strategies`、`validate_strategy`、`generate_signals`；`StrategyForm`；[S06][S20] | 是有限家族，不是不限型態的 AI 策略平台；不同參數不必然是不同投資邏輯 |
| A10 受限 DSL | JSON schema／AST 白名單、深度／大小／數值／欄位限制；只產生策略規格與 intent | `validate_dsl`、`_node/_bounded_json`；[S07] | 不執行模型回傳 Python、檔案／網路工具或任意程式 |
| A11 因果歷史撮合 | signal 在 bar close 才可用，下一可交易 open 撮合；不利滑價；同棒停損停利衝突採保守規則；多空、FIFO lot、費稅、逐筆 ledger／equity | `backtest._run`、`calculate_costs`；[S08] | OHLC 模型假設價格可成交；無 order book／queue／真實部分成交／市場衝擊。最後訊號沒下一棒時不捏造成交 |
| A12 契約／結算／換月 | 明示實際月份、到期日與截止檢查；支援显式 roll schedule、日 MTM／final settlement、歷史成本／保證金 schedule 與追溯版本 | `BacktestConfig`、`_cost_at/_margin_at`、`_run`；[S08][S15] | 要有同時可交易真實月份資料及明示事件；不以連續回溯調整價格當實際成交。進階事件目前不是完整普通 GUI 編輯器；沒有自動官方 roll／settlement／margin 服務 |
| A13 研究閉環 | generate→validate→train/validation 回測→最多两次改善→按 validation 凍結每家族候選→OOS／holdout；保留輸出、失敗與 parent 關係 | `run_campaign`、`Generator`、`candidate_fingerprint`；[S07] | 工程閉環成立不等於模型每次產生有效／不同／更佳策略；重命名同一策略會依語義 fingerprint 拒絕重測 |
| A14 固定資源／預算 | 最多 15 trials、每家族最多 2 improvements；data 上限 100,000 bars，runtime 1–7,200 秒；子程序 deadline、bounded IPC；provider calls／tokens／spend 先保留 | `_campaign_config`、`_run_bounded`、`CompatibleProvider`；[S07][S21] | 不是 GPU／分散式搜尋；worker address-space cap 只在支援的平台強制，明示 unsupported 不假稱所有 Windows memory hard limit。token／spend 估算不是服務商帳單保證 |
| A15 研究資料隔離 | 四段 train／validation／OOS／holdout、依索引和時間驗證不重疊，purge、各段獨立 warmup 與 flat start；生成器只看受限訓練摘要、validation 身分與 prior train/validation feedback | `_campaign_config`、`training_summary`、`run_campaign`；[S07] | 目前是**固定四段切分**，沒有 rolling walk-forward fold 排程；此為已確認的必要研究規範缺口，不是把名稱換掉就完成。也沒有多重測試校正或保證統計顯著性 |
| A16 不可變歷史／重啟 | config／data／source／provider 身分綁定 campaign；所有 attempt 持久記錄；中斷消耗額度不隱式重試；holdout registry 防 sibling campaign 重用重疊區间 | `run_campaign`、`_reserve_holdout`、`research_controls`；[S01][S07][S12] | 不能靠改名字、切工作區、還原舊備份把已看資料叫未見。刪除／複製全部權威本機控制資料不是可信重置流程，也不是抵禦惡意同使用者的安全沙箱 |
| A17 績效報表 | net／gross／unrealized PnL、cost／slippage、return、drawdown、closed lots／fill count、win rate、持倉、每日報酬；JSON result／manifest／ledger／metrics 和 CSV fills／equity；CSV 公式注入防護 | `backtest._run`、`export_report`、`comparison_rows`；[S08][S09] | net PnL 可含未平倉損益；無 closed lots 時勝率未知。Sharpe 明確 None，因未指定年化／無風險率；沒有完整風險比率大全或 PDF 報告產生器 |
| A18 不可變策略選用 | 保存 strategy/result hash；候選原 data／spec 驗證；AI 候選須既有 OOS／holdout 條件通過才准 Paper 選用；停用存檔不抹歷史 | `candidate_record`、`ui_select/ui_disable`、`save_selection/load_selection`；[S01][S09] | 內建策略的研究/Paper 選用不是經濟績效認證；目前實驗沒有合格獲利贏家；選用不連券商 |

### A.6 Paper、風控、帳本與故障復原

| 能力 | 已發布程式與已測範圍 | 限制／不得聲稱 |
|---|---|---|
| 持久事件帳本 | `PaperBroker` SQLite journal、materialized state、intent／order／fill identity、事件重放與精確對帳；策略及帳戶政策固定 | 本地模擬帳本，不是 broker confirmation；對帳快照須明確完整，不將未知外部部位自動覆寫本地 |
| 單一風控檢查 | 帳戶／合約／策略身分、max position、max order、日損、報價年齡、頻率、連虧、資金與 pinned margin／session；未成單的風險 reservation 一併計算 | 桌面目前固定：部位 1 口、單筆 1 口、日損 1,000 TWD、報價最大 30 秒、連虧 3 次、60 秒最多 20 筆。不是可自行調高的普通表單；0.2.1 已補完整唯讀摘要，發行驗證中 |
| 急停／重啟／睡眠 | kill switch 阻新委託；新啟／睡眠或時鐘異常後鎖對帳；每次手動下單／重播明確確認快照；關閉先停背景工作 | 急停不代表平掉持倉或取消所有既有單；本機程序停止不能證明任何遠端請求未完成 |
| Partial／duplicate／cancel race | unit/fault corpus 包含重複 fill、衝突 duplicate、乱序／gap、過量成交、partial、撤單與晚到成交、unknown order | 這是對本地事件規約的測試，不能從而宣稱實際券商 callback 全相容 |
| 不確定與隔離 | malformed／conflicting event 保留 quarantine；送出至 ACK 之間模擬 timeout 留 unresolved；SQLite 寫入／commit／open 失敗 rollback 並 latch 對帳要求 | quarantine 不因回送同一快照就自動解除；沒有自動反向補單、盲重送或“恢復即继续” |
| 歷史 Paper 重播 | `PaperReplay` 以已選策略和 dataset 綁 cursor／durable plan／穩定 ID；分批 next-bar execution；程序中止及 cursor 寫入失敗重試不重複 fill | **不支援盤中 stop/target replay**；不是長時間在線前瞻模擬。Desktop replay 費率為示範假設；host 另硬設 100,000 margin，與普通表單的其他有效值會衝突，見 A.10 |
| 實單隔離 | `LiveBroker` 建構及 submit 直接拒絕；新研究模組與 legacy broker 分離 | 沒有真帳戶認證、下單、平倉或正式 LIVE 切換；無人值守真金交易固定停用 |

證據：[S10][S11][S12]，`tests/test_paper.py`／`test_paper_replay.py`；`paper-recovery-v2.md` 保留最初失敗和修正後完整 61 項 focused PASS。实际 `os._exit`／SQLite trigger 事故测试可證特定本地恢復，不等於實際行情斷線重連、硬體斷電／壞碟、多主機 failover 或前瞻觀察期驗收。

### A.7 AI 路徑、授權邊界與實際模型成果

「提供合規路徑」指使用明示官方／本機介面、權限與資料邊界；不是對所有服務方案、帳戶資格、資料權利或司法管轄作法律保證。

| 路徑 | 產品能力與目前證據 | 需要的使用者操作／限制 |
|---|---|---|
| Fixture | 0.2.0 預設，離線固定候選，完整工程流程可重現；來源一直標 fixture | 不是免費雲端 AI、不是實際模型回應，不得改標 `real_model_verified` |
| 本機相容 HTTP | 0.2.0 `CompatibleProvider`＋`HTTPTransport`；允許 loopback HTTP；可以不用遠端 key；一般 JSON 或 built-in registry JSON Schema | 使用者先自行備妥服務／模型、核對來源及每次同意；應用没有自動下載／安裝／啟動模型。實際成功紀錄是官方 **llama.cpp／llama-server＋Qwen**，不是 Ollama 已驗證 |
| 遠端相容 API | 0.2.0 顯式 HTTPS endpoint／model、金鑰參考、calls／token／runtime／費用限制；遠端零費率假設拒絕 | 預設關閉；傳送範圍、目的地與費用需明确同意；不得未授權改 paid fallback。未對任意供應商作真服務認證 |
| 手動 export/import | 0.2.0 匯出受限 training context、回應 schema 及來源／config／data hash；用戶自行傳送／貼回或選檔；strict JSON／DSL 驗證後成 immutable candidate | 應用不自動操作 ChatGPT 網站、不讀 cookies；人工貼回的來源無法由本機證明，持續 `manual_unverified`；不執行任意程式 |
| 官方 ChatGPT 訂閱整合 | **0.2.1 已合併，待發布品驗證**新增本應用自己的 PKCE／OIDC registration、官方 authorize URL、loopback callback、nonce／issuer／audience／RS256/JWKS 驗證、Windows DPAPI＋ACL；模型發現、Responses parser、typed 狀態及持久 receipt | 尚無实际使用者 grant、訂閱資格／model discovery／inference。授權必須使用者完成官方流程；不借用其他軟體 token 或 cookies。曾重現跨 registration unknown-call bypass，現已在最後 head 修復並通過指定 native／完整 gate；不把離線工程驗證當真帳戶資格 |

已發布程式證據：`quantlab.provider.HTTPTransport`、`research.CompatibleProvider`、`manual_exchange`；[S07][S21][S22]。已合併 0.2.1 程式證據是 `desktop_chatgpt_auth.py` 的 `AuthSession/IdentityValidator/DPAPIVault` [S26]、`desktop_chatgpt_provider.py` 的 `ChatGPTPlanProvider`／持久 controls [S27]、`desktop_chatgpt_ui.py` [S28]、實際 host [S29]、研究 receipt reconciliation [S30] 與 worker [S31]；皆固定至 `2ed1e3e`，不引用早期受缺陷影響 head 作最終證據。

**已合併訂閱安全要求與驗證邊界**：啟動只讀本機狀態，不自動授權／發現／refresh／推論；每次網路及 included-usage policy 確認不持久化。auth／inference 共用受管理 worker；取消／關閉／睡眠／帳戶切換須確認整個子程序樹停止。未知結果消耗 reservation、不退額度、不自动重試；controls 缺失／損毀不得當新帳戶。新的 registration 也必須受同一安裝的未知／paused barrier 約束。最後 head 已含上述 barrier 修補及指定工程 gate；實際服務的授權、計費、配額及未知遠端結果仍不可由本機測試保證。

**真實免費本機模型的技術結論**

- 前兩次有界實驗：0.5B free JSON 3 次、1.5B free JSON 3 次；前者無有效 DSL，後者僅 1 個有效候選且初次因缺必要到期設定被拒絕；失敗及原始回應保留，未手改回應或替換 fixture。
- 第三次 1.5B registry schema 3 次：3 個有效候選，完成 train／validation／OOS／holdout 及比較，使用上列 13,680 個真實 TMF 分鐘 bars。這只證明受限家族參數生成及 HTTP→研究管線。
- 經濟結果：trend 的 OOS **−33,820 TWD**、holdout **−49,546 TWD**；另兩個家族為零交易。費率／margin 是明示試驗假設，資料期短。**沒有可稱為獲利贏家的策略。**
- 額外 2 次 synthetic improvement-loop 真推論證明第二次請求確實含 prior train／validation feedback；模型只改 ID、仍重複 fast=2／slow=4，去重機制正確拒絕。
- v3 另外兩次不同候選嘗試仍失敗；v4 預先限定 1 次、隔離副本加入通用不重複提醒後得到 fast=2／slow=6，技術 distinctness 成功。共 **14 次有界實際免費本機推論**；v4 沒有新回測、OOS／holdout 或績效改善證据，提示修改亦未因此自動整合到產品。
- 模型／runtime pin、revision、hash、license、actual HTTP、usage／失敗與 budget 有留證；没有 paid API、broker 或真正 ChatGPT grant。這些特定試驗不驗證所有模型、seed、家族與未來服務可靠性。

### A.8 設定、安全、備份、安裝與更新

| 編號／能力 | 實際行為及證據 | 交付限制 |
|---|---|---|
| A19 工作區及偏好 | `%LOCALAPPDATA%` 的 per-user app data 與安裝目錄分開；可指定下次工作區但不搬／merge／覆寫；market watchlist／商品／週期／指標／dark theme／window geometry 保存，離屏修正 | 使用既有 schema；舊或非法設定保留並拒絕／安全提示。一次性網路同意不保存；切工作區不重置 bootstrap controls |
| A20 秘密與本機診斷 | 模型金鑰 Windows DPAPI；不寫普通 settings／日誌／backup；精簡事件日誌只存操作與結果類型；可選本機通知 | 輸入框遮蔽不是唯一防護；非 Windows vault fail closed。新訂閱 credential／ACL 屬已合併 0.2.1 及其實際平台證據；不等於實際 grant 已測 |
| A21 備份／還原 | 停工後建立有 manifest、SHA-256 的 state ZIP；上限 512 MiB／10,000 檔；拒絕 unsafe path、duplicate、symlink/reparse、reserved names；staging＋rollback journal 恢復 | 還原替換 state 須明確確認並重新對帳。排除 credentials、bootstrap control ledger、一般 cache/log；備份不是完整電腦映像。位於 state 內的官方 market cache 可能隨 state 進備份，資料權利仍由用戶遵守 |
| A22 備份安全邊界 | 備份輸出不得在工作區或 bootstrap 內，防覆蓋／遞迴；未知中斷狀態保留供診斷；還原不重置 provider budget／seen holdout | 沒有雲端同步、加密 ZIP、排程備份或跨機憑證移轉；DPAPI 不是可跨使用者還原的帳密包 |
| A23 背景生命週期 | allowlisted operation、spawn worker、bounded IPC、single-instance mutex／鎖、取消／關閉／睡眠 freeze；已合併 0.2.1 再强化 receipt audit 与 subtree join | 沒有 production daemon／多使用者服務；memory cap、time bounds 必須按實測平台說明，不能稱任意生成程式的 sandbox |
| A24 Windows 安裝器 | PyInstaller bundled runtime＋Inno Setup per-user 安裝、桌面／Start Menu 捷徑、x64／最低 build 檢查；全新 version payload，inventory/hash 成功才切捷徑；app 正在執行則拒安裝／解除安裝 | 目标 Win10 22H2 x64／Win11 x64；目前原生 Server2022 測試通過，乾淨 client 無 Python／Git 的要求未解除。未簽章 preview，不繞過 SmartScreen／安全警告 |
| A25 升級／移除／恢復 | 真已發布 0.1.2→0.2.0 與最後 head 的 0.2.0→0.2.1 的 manifest／version／source digest 各自驗證；中斷 payload 不啟用；資料與 owned settings 保留；uninstall 不刪 per-user data | 安裝測試使用具開發工具的 Server runner。PATH 隔離及 synthetic smoke 不能代替乾淨 client 使用情境；未達成普遍 RPO／RTO 或硬體斷電承諾 |
| A26 更新與供應鏈 | UI 顯示本版並只開官方 repo Releases；locked/hash 依賴、build/source manifests、license／third-party notices、quality／secret scan／dependency audit；Release 下載後另驗 digest | 沒有自動最新版本 feed、背景下載／自動安裝或商用 code signing。main 保護設定曾因 administration API 403 而 EXTERNAL_BLOCKED，未確認已啟用；不繞過權限。未簽章是信任／安全聲譽限制，沒有因此新設「必須購買憑證」驗收點。SHA-256 完整性不是可信發行者簽章 |

證據：[S12][S23][S24][S25]，`packaging/test_installer.ps1`、`test_update_recovery.ps1`、`clean_windows_acceptance.ps1` 及對應測試。0.2.0 已發布 EXE SHA-256：`be1c749e9fc83ede8c9a0e18d9be99a3c7e3104b4798dda6ccb1834f29471f29`；clean-client kit SHA-256：`6aef9b3fe5a81913528fee9436a98c4e85edd3fa46a69f5e78a2f4dd058be3f3`。請核對該 Release 自己的 manifest，不把前版／候選 digest 混用。

### A.9 固定驗收分數，與可用功能數量分開

| 範圍／條款 | 權重 | 帳本記錄得分（非本次重新核准） | 尚未完成的條件 |
|---|---:|---:|---|
| 原研究 Phase 0–5 | 100 | 100 | 舊 ledger 記錄維持；本次確認必要 walk-forward 尚缺，不能據此稱所有原研究規範皆已完成。沒有模型獲利／broker／正式交易 readiness |
| 原桌面 D0–D9 | 100 | 70 | D5 乾淨無開發環境、D7 Win10、D8 Win11 各 10 點仍 EXTERNAL_BLOCKED；Server 結果不補點 |
| M1 真實商品／來源／首頁／自選 | 20 | 20 | 接受已明示歷史／EOD 的範圍，不代表即時授權 |
| M2 多週期互動 K 線 | 20 | 0 | 已發布 TX/MXF 分鐘匯入缺失；下一模組尚未完成整合／native/frozen gate；指數分鐘不可捏造 |
| M3 技術指標 | 15 | 0 | 0.2.0 實際 host MACD 倍率標示缺口；0.2.1 修正已合併／指定 gate PASS，仍待發布品及 ledger 最終重審，本附錄不自行授分 |
| M4 普通研究／回測／Paper 表單 | 20 | 0 | 固定 Paper risk summary 的 0.2.1 修正之外，**expiry 普通輸入**僅 staging 修復，**Paper margin host binding**亦僅 staging 修復；main／發布品尚未包含；見 A.10 |
| M5 訊號與成交独立圖層 | 5 | 5 | 僅通過已限定的回測來源／hash 綁定，不加碼宣稱 live 或 journal Paper 圖層 |
| M6 合規 AI 操作模式 | 10 | 0 | 已採路徑的完整 gate 未閉合；實際 Ollama 流程未測；官方 ChatGPT 無 user grant／真 inference；0.2.1 安全修補已合併，發布品尚待核對；不能事後改成 manual-only 就補分 |
| M7 繁中深色／DPI／偏好 | 10 | 0 | 乾淨 Win10/11 的最終 build、1366×768／1920×1080、125／150% DPI、鍵盤與主要流程未實測 |
| **總計** | **300** | **195＝65%** | **105 點／35% 未接受**；不代表還剩 35% 工時 |

`ACCEPTANCE.json` 的二元整項規則不變，沒有為已完成局部事後造新權重。新增必要市場/UI 範圍使分母從 200 成為 300，原先 170/200 的成果沒有消失。任何來源假標、未授權傳輸、秘密外洩、保留集／風控繞過或真交易開啟仍獨立 veto 發布，不能用總分抵銷。

### A.10 本次另確認的缺口與最小閉合條件

以下分開「既有必要條款的真缺口」與「尚未提供的擴展能力」，不把新期待偷加進固定分母。優先順序為安全 veto→正常使用阻塞→必要研究規範→整合與平台 gate；不以外部授權問題為由忽略可自行修復的工程缺口。

| 項目 | 本次證據／判斷 | 最小後續驗收 |
|---|---|---|
| **必要 M4：真實資料到期日不能由普通表單完成** | `BacktestForm` 欄位沒有 expiry；其 default config 的 `instrument_expiries={}`；`run_backtest/run_campaign` 正常按鈕把此 config 交核心。`backtest._run` 對任何 official/proxy data 強制每合約明确 expiry。使用現有 13,680 真實 bars 及普通表單重現：`ValidationError: explicit instrument expiry required for real/proxy data`。核心正確拒絕，沒有被放寬；目前只能用進階 JSON／外部程式配置跨過此步 | **staging 已加型別化實際合約／到期日表格**，不推算日期或驗證來源，保留官方自行核對提示。9 新測試由本附錄查核者獨立重跑 PASS；以既有 training-only 5,700 bars、正常 Qt 輸入／回測按鈕兩次得到相同 hash，Campaign 只驗 config 且與 backtest 相同。尚需整合後完整 native/frozen gate；不提前為 M4 授分 |
| **必要 M4：普通 Paper margin 與 replay host 衝突** | `PaperPolicyForm` 可輸入 120,000 之類有效金額，但 `desktop_ui.ui_paper_replay` 固定傳 `margin_per_contract=100000`／`synthetic-assumption-v1`；`PaperReplay.step` 比對實際 pinned policy 後拒絕。已在純 synthetic 臨時工作區重現 `Replay margin does not match pinned broker policy`，原政策 120,000 正確保留 | **staging 已修復並經獨立審查 PASS**：host 送既有 pinned schedule；按 quote_policy 交易日取值，完整版本／future rows／session source／broker config 綁 identity；missing coverage preflight。20 外部 adversarial＋75 broker/replay/policy tests 全 PASS。舊 scalar ledger 不自動遷移、不覆寫／另開帳本；匹配 scalar API 保持可重播。尚待最後整合／native／frozen gate，核心風控未放寬 |
| **必要 M4／實際資料上手：calendar 必須外部備妥** | 資料頁有選擇 calendar JSON，但沒有版本化研究 session calendar 編輯／官方日期維護器。Paper policy 有 typed rows，不等於 research calendar 編輯器 | 誠實提供已核對檔與來源／覆蓋範圍或另外實作非 JSON 工作流；不要寫「下載後即可直接真實回測」。此项当前为上手依賴，是否另扩充功能须依原條款判定 |
| **已修復 release veto：訂閱跨 registration 未確定呼叫** | 較早控制只按 registration 查詢，A 未確定後 B 可 reserve；原失敗仍保留。最後 head `f11e2ef`／main `2ed1e3e` 已修復，644 項 native suite 與全七-job gate PASS | 修補後所有 registration 共用事務 barrier；status／preflight／model discovery 同樣阻擋，不隱式清其他帳戶 row、重置／退回額度。發布品仍须與此 exact tree 核對；實際 grant／server 行為另驗 |
| **必要發布：最終來源／二進位必須再綁定** | provider 修補已合併 `2ed1e3e`；最後 head 是 644 tests，不是先前受缺陷影響的 635-test head。Postmerge Release 尚在進行 | 等最終發布完成，核對 manifest／tree／notices，實際下載 installer／kit 並驗 digest；不能只以已合併或 CI artifact 稱交付完成 |
| **必要外部 D5/D7/D8/M7** | 無已授權／可用的乾淨 Win10 22H2 x64 或 Win11 x64 執行紀錄；kit 已準備／下載不等於執行 | 合法已授權 clean client、無 developer prerequisites，跑安裝／正常七頁／保存／重啟／升級／卸載／DPI／鍵盤并保留 OS／source／digest 證據；不得以 Server／ARM 模擬替代 |
| **必要研究規範：walk-forward 尚未實作** | `04_AI_QUANT_TARGET_DESIGN.md` §8 明示每個 walk-forward fold 的 training fit／validation 改善及理由化 purge／embargo；實際 `_campaign_config` 僅固定四段，`run_campaign` 一次選擇及一次 OOS／holdout。released/head/staging 無 fold orchestrator 或相關 tests | 凍結 bounded fold manifest／source／data／config；每 fold 以既有 train/validation 生成評估，再凍結才看該 fold OOS；持久全程预算及 fold ledgers；OOS 不回饋改善；共享 consumed-range guard 與獨立 final holdout 一次預留。不可直接反覆呼叫原 campaign 而重置預算／每輪消耗同個 holdout；加 typed plan、purge/embargo、restart/cancel／範圍冲突測試。已核准另個後續模組採 built-in fixed-pool rolling evaluator，零 AI 呼叫；目前尚未實作完成，不能視為現有功能 |
| **報告規格需核對：統計／分解／壓力測試** | 目標 §9.1 的「必須公開的計算與例外」列 PF／Average Trade、Sharpe／Sortino／Calmar；目前無 PF／average／Sortino／Calmar 欄位，Sharpe 僅有未配置原因；無 cost-stress orchestrator。沒有多重測試校正 | 若最終採用該完整規格，應實作有明確定義、null 原因與測試的指標／分解，或保留缺失；DSR／PBO 原文是補充選項，不自動變硬門檻。不因畫出曲線就宣稱完整統計報表 |
| **產品限制，不冒稱已提供：比較／交易** | 比較是 metrics rows；無相關性矩陣、組合配置、TX/MXF/指數回測／Paper、真 broker/live feed | 分別另立資料／乘數／tick／成本／風險／帳本與真整合 gate；不得因市場图可看就接受交易能力 |
| **研究未就緒，不全部歸因外部授權** | 短資料、模型有效性／重複偏好、負 OOS／holdout、零交易、假設費率都仍是研究本身限制 | 需充分合法資料、預先固定研究評估與所有失敗披露；不得承諾補登入／換大模型就有獲利策略 |

最初 expiry 重現只在現有 Linux/offscreen Qt 中建構普通表單，讀取既有真實 dataset 並走到核心前置驗證，未進撮合。後續對 staging 修正獨立執行有界現有 training-only 回測，不重新使用 validation／OOS／holdout。全部額外查核沒有新模型／網路呼叫。第一次誤將非 envelope 的研究證據 JSON 交 `load_dataset` 而被拒絕；第二次使用既有正式 envelope 成功重現上述到期缺口。這兩類拒絕都不是「資料來源缺失所以推測」的結果。

**到期表單 staging 的獨立複驗（非發布認證）：** `desktop_forms.py` SHA-256 `6714b2a9d647def22a1fe7bafaa54ba9784da7c940cd8b7bcb8ef2c266ce77f1`；9 項新增測試全 PASS。既有 2026-09-17 至 09-23 的 5,700 bars 完全落在預先宣告 training 範圍，普通 GUI worker 兩次結果均等於 direct-engine reference hash `81d5bf95bd100acd6ad4922f22da78bcf0b841d1e145ee4b48de2f249e7eae8b`。Campaign launch 僅攔截配置並驗證，0 model／0 OOS／0 holdout；原始四個輸入檔 hash 不變。已視覺核對表單圖片中可讀的普通合約／到期欄與來源限制提示；不是 Windows DPI acceptance。

**Paper margin staging 的獨立複驗（由另位 reviewer 完成，本附錄已讀其完整報告）：** 20 外部 adversarial tests 加 fresh 75 項 broker/replay/policy 測試，共95次 test executions PASS，沒有 skips。普通 Qt table 的120,000經隔離worker完成重播，重複完成不增加 orders／fills；多日期120,000／180,000／240,000及跨UTC日期夜盤以exchange trade date選值。原先失敗的 scalar desktop ledger 重開會維持拒絕且 bytes／cursor／plan／路徑／帳本數不變，不偷偷新建帳本。修改來源 `desktop_ui.py` SHA-256 `e468c5aa9b24c4a00b55c26401f457542ad02359f58976510212088b32cb6a70`、`paper_replay.py` `6c537af0395dd139384bea82a15872beec32ac2b7d6d3930506e186ce6ff9be3`；broker `paper.py` 未修改。全部為Linux/offscreen、synthetic、temp workspace；0 network／model／broker／OOS／holdout，無原生Windows／frozen／release認證。

### A.11 原始碼與驗證索引

固定 released code：

- [S01 原生頁面與實際 worker operation](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/desktop_ui.py)：`execute_ui_operation` 175–383、頁面 563–747、普通 backtest/campaign、候選及選擇、Paper。
- [S02 市場首頁及指標實際接線](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/desktop_market.py)：`MarketDashboard` 74–408，`_apply_indicators` 327–349。
- [S03 真實來源／cache／daily import](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/market_providers.py)：`parse_twse_daily`、`parse_taifex_daily`、`fetch_official`、`load_cached`、`import_daily/refresh_daily`。
- [S04 研究資料／calendar／quality](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/data.py)：`SessionCalendar` 46–117、full-session coverage 124–159、`import_taifex` 292–434。
- [S05 公開檔下載及 archive 檢查](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/downloads.py)。
- [S06 普通表單](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/desktop_forms.py)：`StrategyForm` 103–139、`BacktestForm` 142–189、`CampaignForm` 192–239、Paper forms 242–420。
- [S07 DSL／生成／研究／holdout](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/research.py)：DSL 171–191、Provider 256–374、split 473–526、holdout 562–602、campaign 605–814。
- [S08 因果 engine／metrics／manifest](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/backtest.py)：`_run` 73–320；real/proxy expiry gate 151–152。
- [S09 結果／比較／匯出／選擇](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/reporting.py)：比較 137–145、匯出 166–187、default config 214–218、選擇 221–243。
- [S10 Paper journal／RiskGate／LiveDisabled](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/paper.py)：`RiskLimits` 93–110、`PaperBroker` 245–728、`LiveBroker` 731–739。
- [S11 歷史 Paper replay](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/paper_replay.py)。
- [S12 工作區／vault／備份／worker](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/desktop_runtime.py)：controls 97–103、backup 414–591、JobManager 688–851。
- [S13 唯讀市場資料型別](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/market.py)。
- [S14 TMF dataset→市場圖表 adapter](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/desktop_ui.py#L409-L435)。
- [S15 核心 TMF-only 合約及配置](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/core.py)：`validate_contract` 79–85、`Instrument` 142–155、`BacktestConfig` 277–316。
- [S16 八週期聚合](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/chart_data.py)。
- [S17 原生 chart／交互／圖層](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/desktop_charts.py)。
- [S18 指標純函式](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/indicators.py)。
- [S19 真實 host 圖層身分驗證](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/desktop_ui.py#L1065-L1110)。
- [S20 五策略與因果信號](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/strategies.py)。
- [S21 有界相容 HTTP transport](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/provider.py)。
- [S22 手動 AI 交換](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/quantlab/manual_exchange.py)。
- [S23 Inno 安裝／新 payload／保留資料](https://github.com/yostar77612/mark-auto/blob/fc2dfacbf297004095e971ec10cf3620307417a2/packaging/markauto.iss)。
- [S24 Build／frozen／runtime provenance](https://github.com/yostar77612/mark-auto/tree/fc2dfacbf297004095e971ec10cf3620307417a2/packaging)。
- [S25 最終測試與 quality workflows](https://github.com/yostar77612/mark-auto/tree/fc2dfacbf297004095e971ec10cf3620307417a2/.github/workflows)。

已合併待發布 0.2.1 的固定新增來源（`2ed1e3e`）：

- [S26 官方授權／OIDC／Windows vault](https://github.com/yostar77612/mark-auto/blob/2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8/desktop_chatgpt_auth.py)。
- [S27 Responses／持久 receipts／跨 registration barrier](https://github.com/yostar77612/mark-auto/blob/2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8/desktop_chatgpt_provider.py)。
- [S28 普通訂閱操作／狀態面板](https://github.com/yostar77612/mark-auto/blob/2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8/desktop_chatgpt_ui.py)。
- [S29 實際 host 整合／固定 Paper 風控摘要](https://github.com/yostar77612/mark-auto/blob/2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8/desktop_ui.py)。
- [S30 不可變 provider provenance／中斷 receipt reconciliation](https://github.com/yostar77612/mark-auto/blob/2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8/quantlab/research.py)。
- [S31 工作樹停止／IPC／恢復順序](https://github.com/yostar77612/mark-auto/blob/2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8/quantlab/desktop_runtime.py)。

驗證資料範圍：

- 0.2.0 candidate [Windows 38012730927](https://github.com/yostar77612/mark-auto/actions/runs/38012730927)：465 tests／456 PASS／9 skips、真官方 HTTP VERIFIED、實際 0.1.2 升級與恢復。七-job [Quantlab 38012730935](https://github.com/yostar77612/mark-auto/actions/runs/38012730935) PASS；postmerge [Windows 38013204925](https://github.com/yostar77612/mark-auto/actions/runs/38013204925) 完成上述 Release。
- 0.2.1 舊候選 [Windows 38014802079](https://github.com/yostar77612/mark-auto/actions/runs/38014802079)：635 run／624 PASS／11 skips，保留歷史、不代替修補後證據。**修補後最後 head** [Windows 38016153320](https://github.com/yostar77612/mark-auto/actions/runs/38016153320)：644 run／633 PASS／11 skips，明示 Server2022，frozen auth／install／真 0.2.0 upgrade／recovery PASS；七-job Quantlab 亦 PASS。Main `2ed1e3e` 的 tree 相同，postmerge Release 尚待終態／實際下載校驗。
- 留存工程報告：`market-acceptance-review.md`（早期建議與限制；最新 M1/M5 授分以現有 ledger 為準）、`official-history-v2/README.md`、`real-ai-v2/VALIDATION_REPORT.md`、`ai-improvement-v3/REPORT.md`／`ai-improvement-v4/REPORT.md`、`paper-recovery-v2.md`、`market-history-review/review-report.md`、`market-history-module/DELIVERY.md`、`chatgpt-installation-barrier/reproduction-and-contract.md`、`paper-margin-binding/review.md`／`independent-review-hashes.json`。
- 本次額外證據：`final-feature-matrix-expiry-reproduction.txt`、`final-feature-matrix-paper-margin-reproduction.txt`、`typed-contract-expiry/independent-tests.log`、`typed-contract-expiry/independent/actual-data-smoke.json` 與表單圖片。本附錄為讀碼／既有證據核對、普通操作缺陷重現、staging 有界訓練區間回歸；不宣稱重跑全套、授權帳戶、呼叫真模型或完成 clean client acceptance。

**交付時的最短準確描述：**「可下載的原生 Windows 研究／Paper preview，已有真實歷史來源、市場圖表、有限策略、可追溯回測與 OOS、事件帳本／恢復及安裝更新防護。現有驗收帳本 65%；0.2.1 發布品核對、下一歷史匯入模組、普通真資料設定／Paper margin、必要 walk-forward、實際訂閱授權及乾淨 Win10/11 驗證尚未全部閉合。沒有已驗證可獲利策略或實單能力。」


### A.11 本輪整合補記（02:25 UTC）

後續行情、expiry及Paper margin已整合至同一功能分支 `agent/market-history-acceptance-v1`、候選0.2.2，未合併main。組合來源完整724tests709PASS15原生Windows/PowerShellskip（107.128s），sourcehistorysmoke保留原流程與24新chartviews。現在仍須等真0.2.1安裝檔發布/校验後鎖定升級baseline，及本版完整原生WindowsGate；不得把此處本地組合結果說成已下載產品功能。前述0.2.0/0.2.1固定blob證據保留歷史身分，本輪新程式位置為quantlab/market_history.py、desktop_market.py、desktop_forms.py、desktop_ui.py、quantlab/paper_replay.py與相應tests。


A.11續：02:36 UTC上述0.2.1已發布並實際校驗EXE/kit/manifest，下載入口 https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1 。M3完整通過後固定清單210/300＝70%，餘30%；0.2.2仍為待原生Gate候選。原文§5.1明列ProfitFactor/Sharpe，§3.4停損/停利/持倉成本參考線，已追加為必須補齊的工程項，不能因chart ReferenceLine元件存在就聲稱已接正常結果。既有Sharpe明示缺年化假設、PF缺欄位；下一模組只補必要公式/接線，沒有擴張至Sortino/Calmar/portfolio optimizer。

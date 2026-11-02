# M3 自主決策紀錄

## 2026-11-02 09:56 UTC — M3-2：保留同一個 v1 執行與 AST 准入

- 問題：M3-1 的 JSON 欄位只是不可變字串，不代表規格已經經過 v1 驗證；其單元測試的任意 JSON 不能充當有效研究候選。
- 選項：重建一個 v2 規則解譯器、只建構 `StrategySpec`、或使用既有研究准入。
- 決定：`v1_signal_source.validated_spec` 使用 `strict_json.loads` 與既有 `research.validate_dsl`，
  指紋使用既有 `candidate_fingerprint`，信號直接呼叫同一個 `strategies.generate_signals` 函式物件。
  不補造 strategy ID、不把 null rules 換成空物件、不修改參數。時間僅對映為 UTC；整數價格／TMF 契約由原 v1 邊界拒絕。
- 影響：兩個 runtime 新檔與身分測試；M3-1/G3/歷史 producer profile 完全不動。

## 2026-11-02 09:56 UTC — M3-2：現行研究持久層沒有權威 E1 摘要

- 問題：設計稿假定已有可唯讀取得的、單一候選 `statistical_edge` 資格摘要。實際程式並非如此。
- 原始碼證據（未讀取任何真實研究或 OOS／保留資料）：
  `walk_forward` 的持久 state 包含完整評估 payload；`_state_summary` 明列 `strategy_qualification='not_assessed'`。
  `research_core/application/walk_forward_projection.oos_statistics_data` 會由 OOS 報酬重算顯示用 verdict，
  `verdict.py` 明定該結論只供顯示；walk-forward fold 可能選不同候選，不能把合併結論授予其中一個候選。
  保存候選池的 provenance admission 只證明本機成品一致性與事件界限，並非單一候選 E1 統計資格。
- 排除：不讀原始 OOS 來重算、不把 UI／JSON sidecar 自述當資格、不擅改 G3 producer、不虛構完成時間／資料家族。
- 決定：預設 `ResearchWorkspaceCandidateCatalog(workspace)` 一律以 `candidate_unavailable` 安全拒絕。
  保留最小 keyword-only `read_validated_summaries` 主機組裝注入點，僅接受已經由權威研究 reader 驗證來源綁定、
  一次性消耗與必要鎖定狀態的固定 `CandidateEvidence` tuple；目錄再檢查指紋、標準化規格、唯一參照與本機鎖。
  此注入點不是 UI／IPC／AI 輸入；合成 fixture 驗證不代表現行研究工作區已可建成。
- 明確限制：**現行持久層的可建成候選目錄尚未實作**。後續須先定義／實作權威的單一候選 E1 摘要 producer/reader，
  必要 G3 變更另取擁有者授權；不得降低 E1 或 OOS 隔離。資料家族字面值亦須隨該來源契約確定。
- 影響：`runtime/candidate_catalog.py`、`test_m3_candidate_catalog.py`；不改研究資料格式或鎖行為。

## 2026-11-02 09:56 UTC — M3-2：交付與驗證邊界

- 依擁有者最新指示，獨立分支直接對 main 開正式 PR，取代原設計稿的整合分支堆疊。
- 工作樹沒有 `AGENTS.md`、`.agents/skills` 或 `.gitnexus/run.cjs`，GitNexus impact/detect-changes 無法執行；
  使用精確符號／import 搜尋、受影響測試工具與兩個 AST 分層閘門替代。不把 unavailable 宣稱為低風險。
- 本項僅新增 composition 邊界，無 desktop/引擎接線，故不宣稱真實視窗或券商驗收；完整測試留 CI。
- 估計 6 小時、收斂上限 9 小時；未以時間上限作為省略檢查的理由。

## M3-3（2026-11-02 09:51 UTC 起）

1. **交付與範圍**：以最新擁有者指示為準，`dot/m3-3-application` 直接對 main 的正式 PR；不堆疊、不合併。估計 12 小時、上限 18 小時。只新增五個 application 模組與相關測試；既有領域／port、M2、G3、UI、引擎接線不修改。
2. **安全候選來源缺口**：目前主線沒有可供目錄安全直接讀取、且與候選綁定的完整 E1 摘要。`TMF`／`1d` 是本服務明確接受的資格契約與合成 fixture 慣例，不是假稱已找到的生產欄位；真實目錄必須 fail closed。此 PR 不創造 E1、生產回測成績或候選通過結論。
3. **M2 重用界線**：既有 `research`／`research_minutes` 只處理固定方向與 `StrategyRecord` 規則，沒有 `SignalSource` 注入點。沒有複製 v1 信號／成本引擎或修改 M2；新增薄的目標部位遍歷，重用 `SignalExecutor`、`ResearchTrade`、`FeeSchedule`、`InstrumentSpec` 與 `TradingCalendar`／`MinuteResearchSettings`。反手先平後開並分別計費；停損採不利跳空／跳數。
4. **分母與行為證據**：M3-1 固定口數規格沒有配置金額欄位，不能在此改領域契約。因此配置金額保存在不可變 E2 證據且進入 dataset／behavior hash；同版本重放不能改配置。回撤使用扣成本的已實現加逐棒收盤未實現損益。`behavior_hash` 額外包含估值軌跡與期望，避免交易明細相同但回撤算法改變仍被誤當成相同行為；`source_digest` 只影響 `result_hash`。
5. **歷史適用性**：分鐘路徑要求完整顯式日盤網格與供應者的適用區間參照。`HistoricalContractEvidence.covers` 只驗證參照覆蓋，不認證來源真偽；可信主機須負責來源核實。`FixedModelMinuteSettings` 的未知歷史模型不產生此可供晉級的 E2。13:35 強平沿用 M2 固定模型。資料取得／回補、15 分鐘研究工作者 deadline／取消與資源排程接線仍屬 M3-4／7；此同步純函式不宣稱自己提供程序隔離或來源認證。
6. **單寫入者**：服務使用既有 Journal、expected sequence 與 codec；不能與引擎另開競爭寫入者。每次狀態變更先成功持久化再更新投影，重放後執行中策略先寫 RESTART 暫停。模擬觀察由可信主機提供，需匹配恢復日 epoch；LOCAL／LIVE 不產生晉級事件。M3-4／6 尚需整合對帳、行情、完整日與真實 preopen 判斷。
7. **同商品與正式安全**：TMF 別名歸一為 `TAIFEX:TMF:YYYYMM`，防止 `TMF_NEAR`／具體別名繞過同帳戶商品互斥。`LIVE_APPROVED` 不授權本服務新倉；沒有 `approve_live`、擁有者核准入口或任何 broker 呼叫。暫停只封新倉，保護性出場責任仍保留給 M2；不聲稱此 PR 已接通自動出場。
8. **影響分析**：checkout 無 GitNexus／AGENTS／`.agents/skills`；以 grep、import 圖、`affected_tests.py` 與分層閘門替代。全部產品檔是新增；不改 CRITICAL 的 AppState／UiAction／IPC。文件與盤點表為唯一既有檔案追加。
9. **證據解讀**：單元測試／前綴測試／guard 變異只使用合成 TRAINING fixture 或 fake ports，沒有讀取真實 OOS／保留資料、金鑰或市場網路。測試通過不代表生產候選已可取得、桌面已接線或已完成券商驗收。

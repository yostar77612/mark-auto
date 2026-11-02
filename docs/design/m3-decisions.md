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

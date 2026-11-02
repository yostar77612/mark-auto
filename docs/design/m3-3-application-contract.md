# M3-3 應用服務介面

2026-11-02；分支 `dot/m3-3-application`；只相依已合併的 M3-1。
規格估計 12 小時，上限 18 小時；起點 09:51 UTC。

## 預定檔案與責任

- `application/candidate_intake.py`：`AutoBuildRequest`、`build_auto_strategy`；E1、F5、D6、執行資料與同帳戶商品互斥驗證；全部通過才追加建成事件。
- `application/signal_executor.py`：注入 `SignalSource` 與已解析契約的 `SignalExecutor.decide`；只回傳 `TargetIntent`，不接收閘道、不送單。
- `application/signal_research.py`：`ExecutionEvidence`、`research_auto_strategy`；訓練分段 E2、具來源與行為指紋，沿用 M2 成本／價格與成交資料型別。
- `application/promotion_service.py`：單寫入者 `Journal` 事件、重放、冪等評估、漂移、暫停／恢復／停用與證據更新。
- `application/auto_strategy_views.py`：唯讀且無任意 payload 的檢視 DTO；不新增 AI 介面。
- 測試：`test_m3_candidate_intake.py`、`test_m3_prefix_consistency.py`、`test_m3_signal_research.py`、`test_m3_promotion_service.py`、`test_m3_stage_matrix.py`。

## 邊界與保守預設

- M3-1 領域與 port 不修改；不匯入尚未合併的 M3-2 實作。測試透過 fake port；前綴性質可在測試直接對照既有 v1 函式。
- 所有送單、engine／state／codec registry／IPC／UI 接線留給 M3-4、M3-6。服務不持有 broker gateway。
- 不實作 `approve_live` 或正式核准入口；LIVE 永久不可用，包括 `LIVE_APPROVED`。
- 門檻固定釘住 `m3-thresholds-v1`。方向、視窗與轉移使用 M3-1 純函式。
- `TMF_NEAR` 只接受組裝端已解析的具體 TMF 契約；股票、CUSTOM 與不支援的週期拒絕。
- 候選 JSON 只讀取 F5／quantity 欄位作拒絕檢查，不另實作 AST 驗證器；有效性仍交給注入的 `SignalSource`。
- 新錯誤碼預定：`candidate_not_passed`、`candidate_unavailable`、`candidate_spec_unsupported`、`candidate_data_mismatch`、`auto_instrument_not_allowed`、`auto_instrument_busy`、`auto_execution_data_insufficient`、`auto_evidence_changed`。沿用領域 `validation_failed`、`stage_transition_denied`。錯誤 UI 對照表屬 M3-4，不在此修改。
- GitNexus 與 AGENTS／.agents 在本 checkout 不存在；使用文字搜尋與 import 圖確認影響。新增檔案不修改既有函式。
- 每個新增拒絕守衛以獨立測試與實際刪除守衛變異驗證；最終結果附於 PR。

基準在功能完成後以 `repin_baselines.py` 預覽、選擇性更新，獨立 `test(baseline)` commit。不新增桌面文字。

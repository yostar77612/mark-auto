# M3-2 v1 橋接介面與檔案清單

日期：2026-11-02。基線：`0b7606658947c48457d23f3bd25e0f8dde33c3a7`。
本項目依擁有者最新決定獨立對 main 開正式 PR，不採設計稿的整合分支堆疊。

## 固定介面

- `V1SignalSource.signals(contract_ref: str, bars: tuple[SignalBar, ...], signal_spec_json: str) -> tuple[SignalPoint, ...]`。
  直接使用 v1 `generate_signals` 同一函式物件；只對映型別，不翻譯規則。
- `ResearchWorkspaceCandidateCatalog(workspace: Path)`，`passed() -> tuple[CandidateSummary, ...]`、
  `resolve(candidate_ref: str) -> CandidateEvidence`。唯讀、只投影 E1 資格摘要；缺失、鎖定或不符一律拒絕。
- M3-1 的四個 domain/port 檔案不變；不新增公開 DTO、AI 工具、日誌、UI 或下單入口。
- 凍結與新版本沿用 `AutoStrategy`；此橋接不修改任何既有策略。

## 檔案與錯誤碼預先登記

新增原始碼：`quantlab/trading/runtime/v1_signal_source.py`、`quantlab/trading/runtime/candidate_catalog.py`。
新增測試：`tests/test_m3_signal_identity.py`、`tests/test_m3_candidate_catalog.py`（不與 M3-3 的 intake 測試重疊）。
文件：本介面清單、`docs/design/m3-decisions.md`、`docs/agent/IMPLEMENTATION_CONTRACTS.md` 追加。
功能完成後以獨立 baseline commit 登記 `docs/analysis/08_REFACTOR_INVENTORY.md`，其餘機械基準僅依 preview 選取必要部分。

錯誤碼：`candidate_unavailable`（目錄不可讀／缺失／鎖定／證據不符）、
`candidate_spec_unsupported`（v1 規格／AST 不合法）、`validation_failed`（不支援的契約或價格／K 棒）。
無新增 UI 字串；錯誤文字表接線屬 M3-4，本項不改動。

驗證：五家族與 AST 身分／逐筆對等、無 OOS 序列投影、唯讀與鎖定拒絕、G3 bytes 不變、
focused unittest、compileall、分層／架構／品質閘門。完整套件與視窗啟動由整合 CI／後續接線驗收；本項不宣稱已完成。

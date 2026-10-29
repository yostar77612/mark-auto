# T16 part A decisions

- P3-03 is a pure presentation mapping in desktop_app/features/assistant/states.py. Fixed codes
  map to four outcomes; unknown values are generic_failure without inspecting
  exception prose. Quota/rate-limit codes offer no retry-now action; credential
  expiry offers the existing sign-in flow with explicit reauthorization intent.
- Refresh results/errors, local panel failures and subscription campaign notices
  use catalog copy. Campaign receipt status is examined because provider failure
  can be returned in a successful worker packet. No failed receipt is called a
  successful inference. The worker only adds sanitized error_code metadata.
- P3-07 uses one shell-level JobProgress for all four job views. It preserves
  cancel_job and progress/cancel aliases, uses allowlisted stage labels, and
  shows numeric finite progress only (clamped, bool excluded). Unknown progress
  is indeterminate. The existing freeze/recover/cancel path is unchanged.
- JobFeedback owns duplicate-terminal suppression per submitted ID. A click is
  not a terminal result: cancellation/finish races use the manager's first
  authoritative terminal packet. Consumed quota is explicitly not refunded.
- MainWindow: 393 lines (limit 400); ChatGPTConnectionPanel: 421 (limit 500).
  Seven-page metrics are byte-identical and all 14 baseline PNGs pixel-identical
  under tools/ui_snapshot.py with the existing test-only sandbox ACL/vault shim.
  ObjectName inventory is identical; no baseline or name-fixture edits needed.
- G3 and optimization-plan diffs must remain empty. No timeout constants,
  cancellation engine, fail-closed validation, quotas, OOS or trading changes.
- Real-account inference is environment-blocked: this is the user's own
  operation. No real credentials, network requests or quota were used here.
- GitNexus pre-edit: shared ui_text catalog CRITICAL (269 direct users, 54
  processes); start_job/_busy HIGH (startup, polling and close flows). Only
  additive catalog/presentation wiring changed. UNKNOWN dynamic Qt callers were
  confirmed by direct source/test searches. Refresh attempt failed with sandbox
  spawn EPERM. Stale-index detect_changes reports 28 symbols/3 affected flows,
  medium risk, no partial/truncated flag; it cannot establish new-module coverage
  and is not claimed as a fresh whole-graph check.
- Verification details are recorded below after final focused checks. The full
  existing suite is controller-owned outside sandbox, as explicitly instructed.


## Final verification

- Focused offscreen unittest run: 55 tests, 8.918 seconds, zero skips, exit 0.
  Includes test_t16_presentation (15 new tests), test_job_stages, test_import_graph,
  test_no_hardcoded_ui_text, test_no_inline_stylesheet,
  test_desktop_ui_p0_correctness, test_primary_sign_in_host, the existing five
  saved-login/refresh/join/cancel tests, PageBoundaryTests and PageSnapshotTests.
  Existing sandbox_ui confines empty fixture ACL/vault setup; no real profile is
  touched. Slowest new test: 0.418 seconds; no sleeps or network.
- All 64 P0-05 error codes resolve to one of the four states; injected refresh
  errors, fake provider failures and receipt-based worker results are covered.
  All eight stage codes plus unknown values, four job kinds, both progress modes,
  clamp/invalid numeric values, stale packets, repeated cancellation, authoritative
  finish after cancel and cancel-after-complete are covered.
- Cancellation still abandons a queued sign-in in the joined-worker gap. Fixed
  import context notices remain in the status line alongside the shared stage.
  Existing P0 panel expectations now assert the exact outcome text and absence
  of diagnostic codes; existing fixed-code redacted-log assertions remain intact.
- `.venv/Scripts/ruff.exe check`: exit 0. `ruff format --check`: exit 0,
  326 files already formatted. `tools/quality_gate.py`: exit 0, zero findings.
- `py -3.11` compiles all 335 tracked/new Python files read as utf-8-sig: exit 0.
  No generated compile files or debug print calls were added. `git diff --check`:
  exit 0. G3 files and optimization plan have empty diffs.
- Runtime AST is identical to HEAD after removing only the added fixed error-code
  import/packet field, confirming no timeout or cancellation-engine changes.
- Default snapshot metrics JSON is byte-identical; all seven full-page and seven
  viewport PNGs are pixel-identical. Existing exact snapshot assertions pass.
  Widget objectName set is exactly the existing fixture; no additive entries.
- All changes remain uncommitted. Full-suite execution remains assigned to the
  outside-sandbox controller; real-account inference remains user-operated and
  environment-blocked. No acceptance score increase is claimed.

## T16 part B：市場空白狀態與最終量測

- P3-09 完成：沿用離線 synthetic_dataset，記憶體行情卡／圖表均標示合成範例；官方按鈕沿用預設否的同意流程；快取有日期及非即時標示。無網路自動啟動、無檔案覆寫。
- P3-13 已驗證無缺口：真實結果表／display_number 處理 30 位小數、NaN、inf；四段時間軸仍存在。未修改格式器或研究引擎。
- 新增 test_market_empty_ui.py，5 tests／0.852 s PASS；import graph 4 tests／0.814 s PASS；Part A presentation 15 tests／0.618 s PASS。新增圖形測試無 sleeps、無網路、無 skipTest；通知淡出以訊號觸發，不縮短產品逾時。
- GitNexus：MarketDashboard MEDIUM（13 upstream）、MarketPage LOW（7）；_render_chart HIGH（8，含 selection／preferences／smoke）、_render_cards HIGH（7，含 series setters／smoke）。已於修改前警告；閱讀實際來源／測試後只改呈現。索引重建被 sandbox spawn EPERM 阻擋，舊圖僅供導航，非完整證明。
- 初次擴充 import scan 發現既有 local import 未註明延後原因；已加註原因，沒有移動或改變 import 行為，原測試未放寬。新測試初次誤用 Timeline 名稱已修正為既有 WindowTimeline。
- 最終目標數字詳見 t16_final_targets.md（tooltip 與全大寫詞彙已於 Part C 補齊）。普通 snapshot 命令 ACL exit 1；既有 sandbox_ui 執行限定 shim 下 capture 成功。最終測試 fixture 僅市場頁變更，其他六頁 metrics／PNG 不變；四個 objectName 只增不減。
- 不改計畫文件：本次要求前文要追加 section 5.1，最後 checklist 卻禁止編輯，遵循最後規則，以下提供 controller 可直接追加的列。舊列全部保留。

### Section 5.1 去重結果與待追加列

已有對應列，**不重複追加**：P1-10 真實高 DPI、乾淨 Windows 10、P1-08 日曆未內建、P3-01 GitHub runner timing、P3-12 ISRG Root X2 機器 TLS、P3-05 真實更新 manifest、P3-04 真實升級安裝目錄、P3-06 簽署憑證；P1-16 另已有實際升級／解除安裝驗證。唯一缺少的環境阻塞是使用者帳號真實推論，併入下方 P3-03 新狀態列，不再另加重複列。

| 項目 | 已完成的自動化替代 | 需要使用者做的檢查 |
|---|---|---|
| P3-03 狀態更新：介面完成，真實帳號推論仍阻塞 | 固定錯誤代碼映射成功／額度不足／授權失效／一般失敗；離線假 worker 與 receipt 測試通過（test_t16_presentation.py），無秘密字串洩漏 | 由使用者本人以自己的帳號與額度執行一次真實研究推論，核對三種狀態與授權恢復；本次未登入、未消耗真實額度 |
| P3-07 狀態更新：完成共用進度介面 | 回測／研究／前推／下載共用階段、數值或不定進度、既有取消語意；四類工作各三種終態只通知一次（15 tests PASS） | 可在實機觀察長工作；已消耗額度不退、取消等待權威終態，不以點擊自行宣告完成 |
| P3-09 狀態更新：完成市場空白狀態 | 離線合成範例、官方下載明確同意、快取資料日／非即時；test_market_empty_ui.py 驗證同意前零網路與 sample／cached 狀態 | 在可連線機器同意後下載近期官方資料，核對來源日期；未同意不啟動連線 |
| P3-13 狀態更新：既有格式器無缺口 | 真實結果表輸入 30 位小數、NaN、inf，數字至多四位小數，缺值無原始 repr，四段時間軸測試通過 | 無額外環境阻塞；可在真實長期研究結果確認可讀性 |

### Part B 最後核對

- 最後新測試 5／0.767 s、import graph 4／0.710 s、Part A presentation 15／0.501 s：皆 exit 0，無 skips。另加快取缺失但留有舊選擇時仍可顯示合成範例的覆蓋。
- Ruff check／format --check 皆 exit 0（328 files already formatted）；quality_gate exit 0、0 findings；Python 3.11 對 336 個 tracked＋new Python 檔以 utf-8-sig compile，exit 0；git diff --check exit 0。八個 G3 檔與計畫文件 diff 皆空。
- detect_changes(scope=all)：21 個舊索引 symbol、10 個流程、HIGH；無 partial／truncated 標示。索引仍舊，新增 sample 方法不在圖中，行號位移亦會造成多餘對應，不當作完整新圖。既有 selection／indicator／restore／binding 路徑已以 source diff 核對：只改呈現與 local import 註解，綁定引擎不變。
- 最終 snapshot 的額外副本保留在 docs/analysis/t16_final_snapshot_1366x768；自動批准審查拒絕刪除冗餘副本，因此保留為可檢閱的最終產物，非暫存工作區。沒有 commit、push、切分支或 PR。

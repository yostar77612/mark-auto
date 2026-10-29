# T16 part B：最終目標量測

SHA：**2296916**（量測所用程式碼提交；其後只修改本文件）。離屏 Windows／Qt Fusion、1366×768、空白暫存工作區；不讀取使用者資料。
原始數字：[t16_final_metrics.json](t16_final_metrics.json)、[tooltip 探測](t16_tooltip_metrics.json)。
最終 14 張截圖及七頁 metrics 位於 [desktop_pages_before](../../tests/fixtures/desktop_pages_before/metrics.json)。
此為驗收目標的實測結果，不宣稱所有產品目標皆已完成。

| 目標 | 量測值 | 命令／測試證據 | git SHA | 結果 |
|---|---|---|---|---|
| 最高頁面 ≤1600 px | 1377 px（紙上交易）；七頁皆 ≤1600 | `tools/ui_snapshot.py --out tests/fixtures/desktop_pages_before --size 1366x768`，`page_height` 最大值 | 2296916 | PASS |
| 每頁 primary ≤1 | 最大 1 | 同上，`primary_button_count` 最大值 | 2296916 | PASS |
| 未標示輸入欄 0 | 0／7 頁 | 同上，`unlabeled_inputs` 長度總和 | 2296916 | PASS |
| 每頁標籤減少 ≥50% | 最小 60.00%，最大 89.35% | 同上與 `docs/analysis/baseline/ui_snapshot_1366x768/metrics.json`；`100*(1-after/before)`，逐頁見下表 | 2296916 | PASS |
| 禁用工程用語 0 | 0 | 依 `desktop_app.strings.catalog.FORBIDDEN_DEFAULT_TERMS` 與 `tests/test_t9_onboarding.py` 相同正規式，掃描七頁 `visible_text + combo_items + table_headers` | 2296916 | PASS |
| 狀態列原始例外 0 | 固定錯誤代碼對照測試 64／64；秘密字串外洩 0 | `test_t16_presentation.py` 的 fixed-code、worker failure、campaign outcome 測試（本次 15 tests PASS） | 2296916 | PASS |
| MainWindow ≤400 行 | 393 行 | Python AST：`end_lineno-lineno+1` | 2296916 | PASS |
| 每個非自明欄位皆有 tooltip | 非自明且無 tooltip 的輸入 0（30 個有 tooltip、11 個自明控制項已列入清單） | `tests/test_t16_tooltips.py`（建立視窗逐頁檢查） | 2296916 | PASS |
| >4 位小數 0 | 預設畫面 0；長小數／NaN／±inf 測試通過 | 七頁文字掃描 `\d+\.\d{5,}`；`test_market_empty_ui.py` 真實結果表與 `display_number` | 2296916 | PASS |
| hash／全大寫內部代碼 0（進階除外） | hash 0；內部代碼 0；10 種全大寫詞彙皆為檔案格式／商品代號／交易所／幣別／時區 | `tests/test_t16_tooltips.py` 要求預設可見文字的全大寫詞彙集合恰等於清單 | 2296916 | PASS（詞彙清單見 Part C） |
| 無原因停用按鈕 0 | 0 | snapshot `disabled_buttons` 的 tooltip／hint 非空檢查 | 2296916 | PASS |
| 每作業完成通知 1，成功自動消失 | 4 類作業 ×3 終態，每次 1；成功 5000 ms 啟動淡出並隱藏 | `test_t16_presentation.py::test_each_job_notifies_once_and_cancel_after_complete_is_noop`；`test_market_empty_ui.py::test_completion_success_arms_timer_and_fade_hides_without_waiting`（直接發出 timeout／finished，不等待） | 2296916 | PASS |

| 頁面 | 基準標籤字數 | 最終字數 | 減少 |
|---|---:|---:|---:|
| 資料匯入與更新 | 75 | 30 | 60.00% |
| AI 策略中心 | 940 | 119 | 87.34% |
| 回測與結果 | 460 | 91 | 80.22% |
| 比較與策略選擇 | 216 | 45 | 79.17% |
| 紙上交易與復原 | 636 | 201 | 68.40% |
| 市場總覽 | 233 | 74 | 68.24% |
| 設定與備份 | 648 | 69 | 89.35% |

P3-09：兩個空白行情按鈕；合成範例沿用 `quantlab.reporting.synthetic_dataset(960)`，僅在記憶體轉成四根日線，卡片與圖表皆標明非官方範例。無檔案寫入、無下載、無研究資料覆寫。有資料後隱藏兩個按鈕，改用原刷新按鈕。官方下載沿用預設「否」的明確同意對話框；未同意不提交工作。卡片顯示資料日期與非即時，詳細來源也使用日期。

P3-13 **no-gap evidence**：`display_result_rows → ResultTable.set_rows → shown → display_number` 的實際路徑已能顯示 30 位小數為 `7.9825`，NaN／inf 顯示缺值文案；來源資料與精確 tooltip 保留。另測試 `display_number` 的 30 位小數及 NaN／±inf，時間軸仍有訓練／驗證／前推／保留集四段。無需修改格式器或引擎。

執行方式與限制：普通 snapshot CLI 因 sandbox 暫存目錄 ACL 而 exit 1；以既有 `tests.test_t9_onboarding.sandbox_ui()` 包覆 `tools.ui_snapshot.main([...])` 後 exit 0，沒有改產品或 snapshot 工具。shim 僅影響空白暫存 profile 的 ACL／vault 準備，與 Part A 相同。七頁中六頁 metrics 與所有非市場 PNG 不變，只有市場兩張 PNG／metrics 合理更新；widget 名稱只新增四個（兩按鈕及其 prerequisite）。完整既有 suite、真實硬體與外部環境仍由 controller 驗證。本次依最後 sandbox 指示只執行新／變更的 focused modules 與 quality gate。

計畫文件依最後「不得編輯」指示保留零差異；供 controller 追加的狀態列與缺項去重結果見 `t16_p3_notes.md` Part B。

Part C：非自明欄位 tooltip 與全大寫詞彙（`tests/test_t16_tooltips.py`，4 個測試）。

測試建立視窗、逐頁走過預設可見的輸入元件，要求每個元件不是已有非空 tooltip，就是列在下方「自明控制項」清單（以目錄標籤鍵為準，並要求清單沒有過期或過寬的例外）。41 個預設可見輸入中 30 個已有 tooltip、11 個為自明控制項，非自明且沒有 tooltip 的輸入為 0。下方 JSON 是測試實際讀取的政策（清單內容即為各項的理由）。

<!-- t16-input-policy -->
```json
{
  "obvious_controls": {
    "ui._data_page.text_14": "整句即說明的同意核取方塊，勾選意義完全寫在標籤中",
    "ui._backtest_page.text_5": "整句即說明的開關：批次執行五個家族的預設參數",
    "ui._backtest_page.text_7": "整句即說明的顯示開關（圖表訊號）",
    "ui._backtest_page.text_8": "整句即說明的顯示開關（圖表成交）",
    "ui._paper_page.text_14": "整句即說明的對帳同意核取方塊",
    "ui._settings_page.text_8": "整句即說明的日誌開關，括號內已寫明不含的內容",
    "ui._settings_page.text_9": "整句即說明的通知開關",
    "settings.manage_connection": "展開／收合按鈕，標籤即動作",
    "settings.backup_advanced": "展開／收合按鈕，標籤即動作",
    "maintenance.options": "展開／收合按鈕，標籤即動作",
    "logs.errors_only": "篩選核取方塊，標籤即行為"
  },
  "domain_terms": {
    "CSV": "檔案格式名稱",
    "JSON": "檔案格式名稱",
    "RPT": "期交所公開下載檔的格式名稱（使用者在檔案選擇時看到的副檔名類型，非內部代碼）",
    "MTX": "商品代號（小型臺指期貨）",
    "MXF": "商品代號（期交所資料中的小型臺指期貨代號）",
    "TMF": "商品代號（微型臺指期貨）",
    "TAIFEX": "交易所名稱（臺灣期貨交易所）",
    "TWSE": "交易所名稱（臺灣證券交易所）",
    "TWD": "幣別（新臺幣）",
    "UTC": "時區名稱"
  }
}
```

全大寫詞彙：預設畫面共 10 種（CSV、JSON、RPT、MTX、MXF、TMF、TAIFEX、TWSE、TWD、UTC），全部是檔案格式、商品代號、交易所、幣別或時區，屬於使用者看得懂的領域名詞，不是內部代碼。測試要求預設可見文字中的全大寫詞彙集合恰等於此清單，因此新增任何內部代碼都會使測試失敗；hash 為 0。

驗證指令與結束碼（SHA 2296916，Windows 10、Python 3.13.11；Python 3.11 僅做編譯檢查）：

| 檢查 | 結束碼 |
|---|---:|
| `ruff check` | 0 |
| `ruff format --check` | 0 |
| `tools/quality_gate.py` | 0 |
| `py -3.11 -m py_compile`（所有追蹤的 .py） | 0 |
| `unittest discover -p test_t16_presentation.py`（15）／`test_t16_tooltips.py`（4）／`test_market_empty_ui.py`（5） | 0 |
| `test_desktop_pages.py`（14）／`test_desktop_strings.py`（8）／`test_ui_operations_registry.py`（6）／`test_import_graph.py`（4）／`test_function_lengths.py`（2） | 0 |

這是聚焦測試；完整測試套件由 CI 執行。

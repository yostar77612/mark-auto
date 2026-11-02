# M2-3c 獨立審查修正與驗證紀錄

狀態：本文件記錄本輪離線驗證；完整 CI 以 [PR155](https://github.com/yostar77612/mark-auto/pull/155) 最終 head 的 checks 為準，不把本機單項結果當成完整 CI。CI 全綠後仍須等 Claude 審查，不自行合併。

範圍：修正已合併 #147 的審查項目，起點 `c69d459`、分支 `codex/m2-3c-review-fixes`。只用 fake SDK、記憶體／SQLite fixture 及公開資料；不使用真實金鑰、不啟用 CA、不建立 LIVE 送單途徑。既有斷言與完整日誌保留，完整測試交給 CI。

## 1. 第一個契約 commit：`a63ca4c`

- 新 `UiAction.DECLARE_DAILY_NOT_SENT`。
- 新 `DailyNotSentForm(intent_key, confirmed=False)`；`UiCommand.daily_not_sent: DailyNotSentForm | None = None`。
- `DailyIntentView.intent_key` 追加空字串預設，讓 IPC 能指定原意圖；UI 不提供對帳事實、帳戶餘額或「未送出」證據。
- 四個新錯誤碼：`daily_not_sent_confirmation_required`、`daily_not_sent_unproven`、`daily_not_sent_order_found`、`daily_declared_not_sent`。

以上是擁有者明確結案的契約，並非重送或恢復交易的開關。`desktop_app/` 畫面與字串不在本輪引擎修改範圍。

## 2. F1：可證明未送出的日 K 意圖，提供明確結案出口

原問題是 `daily_dispatch_claimed` 已持久化、`order_submitting` 尚未持久化時當機；重啟把意圖保留為 UNKNOWN，但沒有本機訂單列，所有後續啟用都會被未解決意圖阻擋。

`declare_daily_not_sent` 要求擁有者確認，並完整重放已驗證的 journal：序號與完整 `AppState` 必須一致、環境須為 BROKER_SIMULATION、原意圖身分不能改寫，且只能有一次已授權的 READY → CLAIMED 轉移。任何歷史快照曾出現相同語意 key 的 canonical 訂單都拒絕，即使該列之後被移除；「目前沒有訂單列」本身不能證明未送出。

完整歷史證明之後，才進入目前 owner 的減倉級讀取鎖並重新檢查全部配置帳戶的新鮮、健康、同 owner 對帳，以及手動操作沒有未知結果。對帳內同商品、同方向的未明確歸屬券商單仍視為候選：意圖沒有保存昨日價格／數量，不用猜出的經濟欄位縮小比對。精確對應其他已知 canonical 訂單者可以區別，包括已知 TMF 診斷單；其餘可能相符者拒絕宣告。

成功只把原意圖設為 `KNOWN_NO_ORDER`，記錄 `daily_declared_not_sent`、撤銷 run 授權並保持停止。保留資金、訂單、風險鎖與既有未知問題；不重評、不重送、不自動恢復。原 `AUTO_RECONCILE` 仍是對帳操作，不會靜默丟棄未知 dispatch。LIVE 在入口及既有底層金融閘門維持拒絕。

**新鮮度與 owner 檢查必須在完整 journal 證明之後執行。** F3 已證明重放可能耗時數秒以上，不能沿用長掃描開始前的「新鮮」快照。若掃描後快照已過期，應拒絕並等待正常查詢工作者提供新資料，不放寬時間門檻。

F1 專屬測試 **28/28 PASS**，**63/63** 獨立變異由同一個單項測試的 body 攔截（49 個 assertion failure、14 個測試本體錯誤；不把後者宣稱為 assertion-only）。每個變異先在獨立程序跑未變異 baseline；沒有 setup／teardown／cleanup／loader／skip 誤殺，來源 SHA 全部一致。包含實際 native stock／TMF 操作、LIVE 及選錯帳戶反例。

長日誌另有明確可用性限制：目前公開操作在 bundle／engine／owner 鎖內完成 journal 證明，查詢工作者不能在證明途中更新快取。因此若證明本身超過30秒，最後的新鮮度檢查會持續拒絕，保持停機。clock 前進31秒的真實 proof 測試保護這個拒絕；本輪不放寬門檻，也未實作分階段證明／新鮮觀察接續。F3 的23.199秒是既有純評估 recovery 的量測，不能冒充本 F1 helper 的獨立耗時。

## 3. F2：裁剪可丟棄的日 K 投影，保留審計與對帳能力

具名設定 `DAILY_RETENTION_TRADE_DAYS = 20`，年齡只取既有已驗證 DAY，不推測假日或補造交易日。

- 新封存列用 `closing_quote_refs` 參照同帳戶／日期的真實 `ClosingQuote`，不再內嵌第二份完整報價；委託證明改存 `order_digest`／`order_count`。
- 只有已消費、超過保留窗口、未失效、相關委託皆終態的收盤列才可裁剪。尚未消費、缺日曆、失效或仍有未完成／未知委託者保留。
- 每帳戶保留 `DailyCloseArchive` 錨點。摘要仍能偵測舊成交量、均價、費用、缺失訂單及後來出現的回溯日期委託；經濟差異使證據失效並停止新風險。後續新日交易、其他帳戶及 tuple 重排不冒充舊日變更。
- 意圖只有終態、deadline 已過且超過窗口、相關 canonical 訂單可安全確認時才移出投影。READY、CLAIMED、UNKNOWN、活動委託或 canonical 證據缺失者不能藉裁剪消失。
- 委託、部位、保留金與 append-only journal 不刪除；舊完整快照仍在歷史中。這是狀態投影保留策略，不是 journal 壓縮。

### 大小與舊 schema 驗證

`tests/test_m2_daily_retention.py` 模擬 **250 個已驗證 DAY × 30 商品**，已通過下列界線；沒有另存實際最大／最終 byte 數，因此不虛構精確值：

| 已驗證項目 | 斷言界線 |
| --- | --- |
| 每日序列化 `AppState` 的最大值 | 小於 2,097,152 bytes（`MAX_BYTES // 2`） |
| 最後 100 天大小的最大值減最小值 | 小於 1,000 bytes |
| 最終 `ClosingQuote`／`DailyIntent` 數 | 各不超過 600（20 × 30） |
| 該單帳戶 fixture 的 archive 數 | 1 |
| 舊資料可追溯性 | 首日報價已離開目前投影，但仍存在 journal 快照；目前狀態 codec roundtrip 相同 |

測試沒有獨立斷言最終 `DailyAccountClose` 的精確列數，不把程式窗口值當成額外實測結果。

新增欄位有空預設，舊 payload 可依既有 codec 載入；舊 `closing_quotes`／`order_fingerprints` 也保留解讀路徑。啟動先以純 `compact_daily_projection` 處理 restored state，再做第一次 `startup_reconciliation_required` 寫入，避免關閉中的舊狀態必須先寫入未裁剪投影。實際 `TradingEngine` 啟動 fixture 涵蓋舊欄位缺省與新 schema 兩種 payload，皆保持停止、未對帳、automatic 暫停，且不查詢 SDK。這不表示會放寬 codec 上限載入本來就超限的歷史 payload。

F2 最終專屬測試 **29/29 PASS**、獨立變異 **54/54**；每項先在獨立新程序跑同一未變異測試通過，再在另一新程序只替換實際函式守衛，54項均為測試本體 assertion failure，0 errors／skips／setup或cleanup誤殺，來源及測試SHA全部一致。包含實際Engine兩schema的首次startup、250×30、舊UTC／+08語意key及EXIT後綴仍有ACCEPTED／UNKNOWN canonical委託時保留意圖，以及不同策略／版本／商品／時間不誤綁的反例。完整journal、訂單與金融對帳沒有被裁剪。

最後交叉檢查先以新測試重現時區相同key卻誤裁的失敗，再將associated比較換成既有 `evaluation_key_matches`，保守保留整個close batch仍待處理的委託意圖。證據摘要隨 [JSON](m2-3c-review-fixes-verification.json) 交付，含case、單項測試、實際守衛變異與最終來源SHA；原始run logs保留在本機ignored verification目錄。

## 4. E29／E23／C1／LIVE：新增守衛測試

新 `tests/test_m2_daily_review_guards.py`：**13/13 PASS，0.397 秒**；**19/19** 獨立變異被殺死，4.951 秒。每個變異先跑同一測試的未變異 baseline；只計 assertion failure，setup／import／cleanup 或測試錯誤不算擊殺。變異只在子程序記憶體替換實際函式，不改磁碟產品檔。

- **E29**：使用實際 `TradingEngine._persist` 與 journal，在 `daily_signals_saved` append 注入失敗。當前與 durable state 都保留 CLAIMED、沒有意圖，storage failure 阻止重播；成功時在同一筆 durable event 保存 COMPLETED 與唯一 ENTRY，再送相同完成 K 不重複。分別插入「先寫完成」與「先寫意圖」的非原子變異都被攔截。
- **E23**：已有該版本持倉時，即使進場信號為真，保存階段的 `_make_actions` 不產生 ENTRY。
- **C1**：實際整張股票 sizing 不足一張時，明確回傳 `strategy_size_insufficient`，不只斷言「任意錯誤」。
- **LIVE**：新增 ExecutionService commit 的 state／plan 閘門、gateway 金融操作閘門，以及 SDK facade 下單／改單／刪單各自的拒絕測試與變異。檢查進入 validate、journal、gateway 或 raw fake native mutation 之前已拒絕，既有測試未削弱。

證據：`.gitnexus/verification/daily-review-guards-mutation-results.json`、`daily-review-guards-evidence.json`。

## 5. S1：官方日 K、分鐘合成與價格基準的實際限制

### 收盤集合競價不是普通非空交易分鐘

TWSE 普通交易的連續撮合到 13:25，13:25–13:30 不撮合，13:30 收盤集合競價；部分商品可能延後到 13:33。要求 09:00–13:29 每分鐘都有成交才能合成日 K，不能一般性重現股票官方日 K，問題不只出現在流動性差的股票。[TWSE 交易說明](https://shl.twse.com.tw/page/library/trade/2.html)、[TWSE 交易制度](https://www.twse.com.tw/zh/products/system/trading.html)。

目前 `compose_minute` 把正好 13:30 的 tick 放入 `[13:30, 13:31)`；`complete_buckets` 不把它納入 13:30 結束的 DAY。13:24 後自然無成交的間隔也會使新分鐘被標示 incomplete。永豐官方 SDK 文件的 2330 範例 tick 為 13:24:56.011886、13:24:57.008306、13:30:00、14:30:00；集合競價量 4,606，前兩筆量總和只有 8。該範例最後盤中價與競價價恰好相同，所以只能證明競價資料被排除，不能聲稱觀察到不同收盤價。[永豐歷史資料文件](https://sinotrade.github.io/tutor/market_data/historical/)。

股票自動路徑的實際接線也有限制：`MarketTerminalService._accept` 的 `on_tick` 與 `poll` 的 `on_bars` 使用 `_live` tick-minute buffer，`_retain` 會丟掉 incomplete bars。圖表 `series()` 另外讀取 persisted/history bars，不代表自動 callback 已得到官方日 K 或補妥收盤缺口。SDK 文件的歷史 Kbar timestamp 是結束標記（股票首根範例為 09:01），不能當 tick-minute 的開始時間；M2-7 的 TMF minute-history adapter 已明確減一分鐘。本次不修改它，也不把股票 live callback 的問題套到該歷史接線。

### 流動性差股票：6225，2025-06-27

保存的 TWSE 月資料列為 **7 筆成交、11,000 股、收盤 11.40**。即使反事實地把每筆交易放在不同分鐘，仍不可能供應 270 個非空成交分鐘。原月資料統計涵蓋一般、零股、盤後定價與鉅額交易；若限縮成普通 DAY，只可能降低這個成交筆數上界。分鐘 tape 與官方日量還必須對齊交易範圍。[官方公開資料端點](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20250601&stockNo=6225&response=json)。

測試中的七個分鐘位置只是上界探針，沒有從日資料捏造成交時間、分鐘價格或真實 tape。

### 除權息日：2330，2025-06-12

官方記錄的 2025-06-11 收盤為 **1,065.00**、2025-06-12 收盤 **1,045.00**；當日除權息計算列的前收為 1,065.00、參考價為 **1,060.49**。[日價資料](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20250601&stockNo=2330&response=json)、[當日除權息計算](https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20250612&endDate=20250612&response=json)、[TWSE 參考價公式](https://www.twse.com.tw/zh/announcement/ex-right/twt49u.html)。

M2-9 `price_series` 在 as-of 範圍包含該事件時，把前一天的還原收盤調整為 1,060.49，並保留原始成交／執行價格。事件前歷史直接接 raw 日價的價格差為 **20.00**；按事件當日重建完整還原窗口後，差為 **15.49**。這些是價格差，不是已含權息權益的經濟損益，也不是已證明某策略產生假信號。

### 目前 typed engine 尚無可信的官方／還原資料 bridge

GitNexus 與原始碼查證：`StockResearchService.run` 呼叫 `backtest_stock`，其 runtime wrapper 用獨立 journal，不回填交易引擎，而且明確拒絕 typed strategy parameters。該 producer 的信號窗口使用還原價格、執行使用 raw 價格。

相對地，`TradingEngine.history` 接受呼叫者提供的 `CompletedBar`，沒有 source、basis 或 as-of 欄位。LOCAL `SimulationControl` 放入 synthetic history；native `ManualRuntime._materialize` 未提供歷史 mapping；`automatic._history` 只做篩選與拼接。因此不能聲稱目前券商自動交易已使用官方還原歷史，也沒有在除權息日 append 時隱式重建還原窗口。

**本輪尚未接上官方日 K／價格基準 bridge，也未新增完整 source／basis envelope 的進場驗證。** 以下一致性要求是尚待實作的驗收條件，不宣稱目前已具備該守衛。最保守方向是：來源、普通交易／量的範圍、RAW／ADJUSTED、還原方法、公司行動 digest 與 as-of 日期無法和研究證據一致時，不授權股票日 K 新倉。維持缺分鐘 fail-closed，不能補零成交分鐘、把試撮當成交、拿過時最後價冒充官方收盤，或靜默拼接不同價格基準；保留既有保護性／合法減倉控制。本輪 fixture 沒有新增可信 source port，也不能當成已完成接線或真實分鐘回測。

未來 source envelope 應帶商品、完成交易日、source identity／digest、完整 session 狀態、RAW／ADJUSTED、還原方法、公司行動 digest；除權息日按該 as-of 重建整個信號窗口，另用當前 raw quote 執行，重用 M2-9 官方儲存與還原語意。這是尚待實作的接口方向，不是本輪新增的授權開關。

### S1 fixture 與證據界線

`tests/fixtures/m2_daily_review/manifest.json` 記錄每檔官方 URL、時間、列數與 SHA-256；取得時間為 `2026-11-02T12:06:08.810722+00:00`。三份交易所 JSON 是逐 byte 保存的公開 HTTP 回應：6225 月資料 21 列、2330 月資料 21 列、當日除權息計算 12 列。SDK closing-tick 範例是有標籤的官方文件轉錄（4 列），不是獨立錄製的交易所盤中 tape。

SDK轉錄採單行、無結尾換行的JSON並同步記錄SHA，避免Git在Windows checkout轉換CRLF而破壞其byte核對；內容不變，三份原始交易所HTTP bytes未改。manifest本身按JSON解析，不削弱原始資料的逐byte SHA斷言。

`tests/test_m2_daily_price_basis.py` **7/7 PASS，0.009 秒**；**6/6** source guards 被獨立殺死：完整分鐘、收盤 session 邊界、套用還原、事件 as-of 範圍、不調整 ex-date 本身的價格、拒絕把舊式還原研究當作 typed execution 授權。各自為 fresh process、同一測試 baseline PASS 後 mutant body failure，不修改磁碟產品檔。詳細紀錄為 `.gitnexus/verification/m2-3c-s1-audit.md`、`m2-3c-price-basis-mutations.json`。

S1 曾嘗試可見 Chat 委派，但 `experience.open(chat)` 在發送 prompt 前以 `recoverable:false`／`CDP operation exceeded its deadline before command dispatch` 結束，turn count 為 0，沒有盲目重送；事實依據是上述官方 HTTP／文件來源與本機 fixture，不是委派推論。

## 6. F4：一般日 K 出場的驗證層級維持現狀

已保存的普通 EXIT 與 ENTRY 都呼叫進場級 `_entry_proofs`；前置 DomainError 保留 READY、暫停 run，不送單。成功普通 EXIT 維持 `protective=False`，產生的委託仍為 `reduce_only=True`。本輪**不改預設**。

獨立的減倉級路徑可能在進場級資金／單日虧損或全帳戶 proof 不可用時提高減曝險可用性，但必須保留當前 owner、可信已知持倉與新鮮對帳、可執行行情／session、最短持有／可賣數量、既有退出單容量、冪等及 UNKNOWN 隔離。不能為了繞過進場檢查，把普通 EXIT 改成 `protective=True`。這也會改變目前停止新倉後的普通策略出場行為，需要另行明確設計；本輪不放寬。

## 7. S3：共享手動帳本隔日 ready 是有意行為

舊 `APP_VIRTUAL_SIMULATION` book 在 BROKER_SIMULATION 下，若存在 typed 共享策略，且已提交 `DailyBaselineEvidence` 與所有當日每帳戶 baseline 的 source、前收 PnL 完全一致，可在隔日 `manual_day_ready=True`，不要求重設 opening seed。

新增測試確認缺 evidence／baseline、錯 source／金額／日期、LOCAL、broker-labeled book、沒有 typed strategy 都不放行；原同日純手動 book 不需要 automatic evidence。`manual_day_ready` 是讀取判斷，不配置資金、不改 opening_day、不清風險鎖、不恢復 automatic run。這個隔日共享帳本資格確實會影響手動新倉可用性，PR 必須明確列出，不把它隱藏成純 UI 或純自動交易修改。

## 8. F3：大日誌實測，journal 仍會成長

量測用正式 SQLite `Ledger.append` 建立完整 hash chain，再呼叫實際 `daily_recovery`。每個完整 snapshot 有 30 策略、30 個 open lots、30 筆 canonical orders，平均約 125,153 bytes；這是 synthetic 效能 fixture，cache owner validator 為 fake，不聲稱券商帳務證據。使用暖 filesystem、各規模一次量測，建置時間另列，無 SDK 查詢或下單。

| journal 事件數 | 總 payload／SQLite bytes | 建置秒數（不含恢復） | 未追蹤記憶體的 replay＋provenance 秒數 | 記憶體追蹤下完整 recovery 秒數 | 追蹤峰值 bytes |
| --- | --- | --- | --- | --- | --- |
| 1,000 | 125,152,810／127,131,648 | 4.064 | 4.385 | 25.132 | 126,466,694 |
| 5,000 | 625,764,810／635,072,512 | 20.728 | 23.199 | 131.556 | 628,907,188 |

`tracemalloc` 的時間包含追蹤成本，不能當作正常 production latency；未追蹤欄是完整 hash 驗證與 DTO 解碼的 replay＋provenance，不宣稱為整個 UI 操作的耗時。兩次完整 recovery 都只完成純評估捨棄、保持暫停，沒有 SDK 呼叫。量測期間 helper／來源 SHA 穩定；大 SQLite fixture 已刪除，可由 ignored runner 重建。

F2 讓每日**目前狀態**的投影有界，**不讓 append-only journal 有界**。重放仍讀取完整歷史，F3 在本輪只查證回報，未改成索引／checkpoint，也未外推其他規模或硬體的效能。長掃描後仍須重新檢查新鮮對帳與 owner；不得以效能為理由拿掉歷史證明或延長新鮮度門檻。

證據：`.gitnexus/verification/f3-daily-recovery-benchmark.json`、`daily_recovery_benchmark.py`，含 fixture 規模、原始秒數、記憶體、來源 SHA 與穩定性。

## 9. 尚待補齊與審查重點

1. [PR155](https://github.com/yostar77612/mark-auto/pull/155) 直接對 main，第一個小契約 commit 為 `a63ca4c`；本輪不自行合併。F1 專屬測試28項、變異63項已完成，整合驗證另列。
2. R8 工具選出196個相關模組，初輪執行2394項（1121.748秒）：2382通過、9項依既有條件skip、3失敗。GUI子程序1項已在正確Qt環境重跑通過，另2項是下述main同樣失敗的主機全域鎖。最後時區裁剪修正後，R8清單內17個直接相關模組與靜態／登記gate共 **324/324 PASS（67.949秒）**，另有retention29項專屬測試及54個變異完成。原始 `_run_window` 最終在 **LOCAL7.591秒／fake BROKER_SIMULATION4.863秒** 實際顯示視窗、返回0且完成研究資源與自有端點清理，沒有匯入真SDK；兩模式均保持停止／待對帳語意。Ruff／format、Python3.11語法、品質與分層檢查均通過，完整CI以PR最終head為準。
3. 官方股票日 K、收盤集合競價與研究同基準 source bridge 尚未接上；上述實例證明現有分鐘合成與無來源 `CompletedBar` 不能替代這份證據。保留 fail-closed，不把人工 fixture 的可用性寫成全商品可用。
4. F1 再審完整 journal proof 後的 fresh observation／owner 鎖順序，以及「有歷史送單列／可能相符券商單」不能宣告未送出；未知結果不重送、不退款、不自動恢復。
5. F2 再審所有未消費／未知／活動資料的保留、舊摘要對 late fill／fee 的失效能力，以及第一次 startup append 前的 compaction；不能只看 byte 數通過。
6. F3 完整 journal 的時間與記憶體成長仍存在；F1 超過30秒的鎖內證明可能無法取得新鮮觀察而持續拒絕。F4 普通 EXIT 仍受進場級驗證阻擋。這些限制已揭露，未在本輪靜默改變策略政策。

### 本機環境差異的查證

初輪相關模組使用原生 Python 程序驗證程序 ID 與 IPC，但該解譯器的獨立 GUI 子程序沒有共享 venv 的 PySide6 路徑，`test_first_parent_registrar_lookup_cannot_poison_real_mainwindow_or_public_aliases` 因此報 `ModuleNotFoundError: PySide6`。main 完整原始碼快照可重現相同錯誤；改以具備 Qt 的既有共享 venv 跑同一未修改測試，目前分支1.759秒與 main3.636秒皆通過。沒有改產品或測試斷言。

兩個 WindowsInstallerGuardLifetimeTests（原生guard生命週期、UI例外清理）在目前開著使用者程式的主機上，於既有 `A preexisting app lifetime must not be disturbed` 斷言失敗；main 原始碼快照也在同一斷言失敗。保留這兩個結果，不關閉使用者程式、不略過或放寬測試，交由隔離的完整 CI 執行。這不是包裝或安裝程式修改。

## 10. 新檔案、影響與交付

新增產品模組 `quantlab/trading/application/daily_resolution.py`、`daily_retention.py`；新增四個測試模組 `test_m2_daily_not_sent`、`test_m2_daily_retention`、`test_m2_daily_review_guards`、`test_m2_daily_price_basis`（共77個方法），與 `tests/fixtures/m2_daily_review/` 五份fixture／manifest。本文件及相鄰JSON保存最終來源SHA、142個獨立變異結果與本機證據，決策與行為契約同步追加。

GitNexus針對此工作樹更新索引。原共用契約CRITICAL110 upstream、engine HIGH94、AppState HIGH96、registry MEDIUM24；最後裁剪函式CRITICAL262 upstream，涉及37processes／17modules。啟動、close-provider、IPC、runtime及codec納入驗證；圖的UNKNOWN與受限flow不當成無影響。提交前以完整 `detect_changes(all/compare origin/main)` 檢查，摘要隨JSON保存，拒絕partial／truncated結果。

`tools/repin_baselines.py` 在最後功能收斂後集中產生兩個產品模組登記，放獨立baseline commit。既有close測試改為同等或更嚴格的quote引用及物件身分檢查，沒有降低金融斷言。未改desktop_app/、G3、SDK版本、PROJECT_STATE、成本實作、workflow、打包或分層規則。LIVE持續硬關閉。

未完成／外部驗收：官方股票日K與同基準source bridge、長日誌分階段證明與新鮮觀察接續仍為後續工作；畫面接線與真實券商自動交易由相應車道／擁有者驗收。F4普通EXIT維持原政策。完整CI全綠後仍留PR開啟等待Claude，不啟用自動合併。

# ADR 0007: 股票信號研究的有限擴充

日期: 2026-11-03
狀態: Accepted（擁有者核准 G3 最小變更；股票資格與交易建成仍未開放）

## 背景

[M3-9](../design/m3-ai-strategy-to-auto-trading.md) 需要同一個信號函式接受股票小數價格。
擁有者明確同意在必要最小範圍修改 `core.py`、`strategies.py`、`backtest.py`，
先新增 ADR 並保留日 K 行為及安全驗證。本次只需修改前述第一及第三個檔案；
信號演算法不必改寫。其他 G3 檔案不在授權內。

## 決策

- `Bar` 與 `Signal` 新增明確 `TWSE:dddd`／`TPEX:dddd`（四至六位數）股票信號身分。
  股票研究價為正且有限的 `Decimal`，可包含除權息調整後不在交易跳動上的價格。
  這不是委託價驗證；原 TMF 合約格式、整數價格與日夜盤規則不變，股票只收日盤。
- `validate_contract`、`Instrument`、`Fill`、Paper 及原期貨回測仍限 TMF。
  原回測在進入任何期貨帳務前明確拒絕股票，避免套用每點 10 元、保證金與期貨稅。
- 股票資料集只從主機端既有、唯讀的官方日線驗證來源建立。保留原始成交資料；
  信號依每個已完成日期重建從固定起點開始的調整歷史，不能把最後一天的還原價
  回填較早決策。沿用來源位元組、完整日曆與除權息負證據驗證，不推算缺失資料。
- 同一 `generate_signals` 產生狀態信號；股票的目標部位投影固定為 LONG_ONLY。
  此階段只交付有界 TRAINING 信號研究，不產生 PnL、E1、E2、OOS 或自動交易資格。
  不新增 AI 工具、提示、外部請求、憑證、執行或 journal 寫入路徑。
- M2-9 的官方負證據目前只有 TWSE 路徑；TPEx 官方來源未知就拒絕。
  型別可表示 TPEx 不表示資料可通過。官方形狀的合成測試不得稱為正式市場驗證。

## 後果

### 相容性與來源指紋

[ADR 0003](0003-tmf-research-scope.md) 對帳務與 Paper 的限制保留；只放寬上述信號資料。
既有序列化欄位、策略 AST、候選 fingerprint、TMF 信號、成交與帳務均不變。
舊結果與全部歷史 producer profile 原文保留，不重釘歷史來源雜湊。
依 CONTRIBUTING 的要求新增獨立 current profile，明確記錄本次來源身分。
新執行的來源指紋必須改變；把改過的檔案宣稱為舊雜湊會破壞證據鏈。
回歸比較區分「來源改變」及「研究行為改變」，不偽造相同的新 run hash。

### 未完成前置與驗證

目前 `candidate_catalog` 沒有權威的逐候選 E1 producer，股票完整多年資料與公司行動
經濟權益也不能由介面推定。短波／長波建成與 UI 選項保持停用；完整 M3-9 未完成。
後續須有獨立 E1 來源、股票 E2 成本／停損／持有期與權益驗證後才可解鎖，
正式委託仍硬性關閉。此次不變更 OOS 一次性消耗、不可逆預算或 15 分鐘上限。

驗證包含五家族與 AST 小數價／前綴一致性、逐日還原無前視、交易帳務拒絕股票、
日 K TMF 行為與候選指紋固定基準、歷史 profile 原文、目前來源身分、資料缺漏、
未知負證據與非 TRAINING 拒絕。完整 G3 測試由整合負責分支執行。

### 安全邊界

沿用擁有者 2026-11-01 決策 D1：production orders disabled by default。
日後任何正式委託啟用仍需另外明確授權；本次不新增啟用路徑，LIVE 保持硬性關閉，
v1 研究／Paper 的真實委託禁令不變。OOS 一次性消耗、不可逆預算、受限 AST、
fail-closed 驗證及不隱式重試全部保留；Paper 30 s、smoke 40 s、每 job 15 min
上限不放寬。

## 審查後續（PR #170 cloud review）

- 逐日決策的結果不變（位元相同），但實作改為每個「除權息進入視野」的區段只重建一次調整後價格、
  `Bar` 與累進資料雜湊，並對該區段執行一次共用 `generate_signals`（其因果性已由前綴測試固定）。
  任一決策日仍只使用當日以前已進入視野的事件；調整算術由 `stock_history.adjust_bars` 與
  `price_series` 共用。`stock_signal_dataset` 保留為逐日定義，測試以它作 oracle。
- `Bar` 接受股票身分後，期貨入口不能再以建構 `Bar` 當作 TMF 閘門。新增 `quantlab/futures_gate.py`，
  由 `reporting.load_dataset`、`walk_forward._validate_source`（任何預留之前）與研究作業的 campaign
  入口呼叫。
- 擁有者已核准（本次審查，2026-11）對 G3 鎖定檔 `data.py`、`research.py` 各加入一個最小檢查：
  `validate_dataset` 逐根 bar 呼叫 `validate_contract`，`_campaign_config` 對每個不同的合約身分呼叫
  `validate_contract`（均在任何預留或寫入之前）。行為只收緊，TMF 路徑不變。依 CONTRIBUTING 新增獨立
  current profile `STOCK_SIGNAL_PROFILE_V2`（僅協定名、`research.py` 引擎雜湊與 `data.py` 結果雜湊
  不同於 V1）；V1 與其餘 30 個歷史字面區塊逐位元組保留，歷史測試改用封存的審查前位元組
  （`tests/fixtures/pr170_review_prior_sources.json.gz`）。`test_m3_signal_identity` 的核准 blob 清單
  新增這兩個檔案的精確 blob，並不放寬其他任何鎖定檔。

# TMF AI 量化研究與模擬交易目標設計

目標是形成可追溯、有限預算的研究閉環：合規行情 → 候選策略 → 因果回測 → 改善假設 → 新版本 → 樣本外驗證 → 比較與選擇。第一版先證明流程、帳務與隔離正確；沒有策略通過績效門檻也是有效研究結論。AI、回測或 paper 成功都不代表核準真實交易。

本文件為 2026-10-09 的目標與工程契約說明。原始碼事實固定於 `1cacce4ee4eef4ce7e8760f8153ef64a74852d22`；新增能力的實際驗收以 [ACCEPTANCE.json](../agent/ACCEPTANCE.json) 為準，介面以 [IMPLEMENTATION_CONTRACTS.md](../agent/IMPLEMENTATION_CONTRACTS.md) 為準。設計要求不得被誤讀為每項已實作或測試通過。

## 1 目標架構與執行邊界

保留 Python 與 Streamlit，在 `trader/` 旁建立 `quantlab/`，不把研究放進 `trader` 子套件。核心以 Python 3.11+ 標準函式庫為主；Windows 應確認時區資料可用，必要時在可重現 UI 環境安裝 `tzdata`。UI 為選用層，無 UI 也能執行研究及測試。

```text
本機合法資料 + 版本化 calendar + instrument/cost
                     │
          匯入驗證 → 不可變 Dataset／品質報告
                     │
              鎖定研究 campaign config
                     │
  Fixture／模型 provider → 有限 DSL → 驗證器
                     │                 │ 拒絕與原因
           因果訊號 → 回測／帳本       └→ all-trial log
                     │
        train／validation → 有界 improve
                     │
        凍結候選 → OOS → 一次 final holdout
                     │
          不可變策略庫／比較報告／使用者選擇
                     │
          paper 核準 → RiskGate → PaperBroker journal
                     │
          新單阻擋／故障恢復／對帳／人工停止

真券商執行為另一道邊界
目前 LiveBroker 只能明確拒絕 不讀秘密 不建立連線
```

研究與交易不能共用一個「simulation」旗標來切換能力。它們應有不同依賴、資料根、端點、權限及核準流程。策略只能輸出目標部位／intent，不能取得 broker port、帳戶秘密或任意 shell。

| 模組 | 主要輸入與輸出 | 禁止責任 |
|---|---|---|
| `core.py` | Instrument、Bar、Dataset、CostSpec、StrategySpec、Signal、Fill、Result；canonical JSON／hash | 不做網路／broker／UI 初始化 |
| `data.py` | 本機官方格式／合成檔、明確 session calendar → dataset／quality／manifest | 不補造分鐘價，不自動載入 pickle，不默默猜歷史時段 |
| `strategies.py` | bars＋策略規格 → 因果訊號 | 不下單、不讀未來、不自改 hard risk |
| `backtest.py` | dataset＋spec＋config → fills／ledger／equity／metrics／rejects | 不登入，不把連續調整價當真成交價 |
| `research.py` | 鎖定 campaign＋generator → 全部 trials／版本關係／選定候選 | 不讓生成器讀 holdout，不無限優化 |
| `reporting.py` | 結果與版本識別 → 比較、JSON／CSV 及可追溯圖表 | 不把不可算指標變成無限大，不自動啟用策略 |
| `paper.py` | intent＋quote＋risk limits → 持久事件、帳戶與對帳狀態 | 不包裝真 SDK、不隱藏真下單、不在 unknown 時重送 |
| `research_app.py`／`__main__.py` | 薄 UI／CLI，呼叫相同服務層 | 不載入 `gui.py`／`run.py` 舊交易入口 |

## 2 官方 TMF 規則與版本化模型

### 2.1 契約要素

以下是查核日官方可見規格的摘要，執行時仍應依適用日期公告及契約主檔驗證。

| 項目 | 已核實內容 | 工程處理 |
|---|---|---|
| 商品 | 微型臺指期貨，代碼 TMF，標的為臺灣加權股價指數 | 正規 ID 用 `TAIFEX:TMF:YYYYMM`，不以「近月」當可交易契約 |
| 乘數與 tick | 每點 NT$10；最小跳動 1 點 | 成交／委託價格必須是合法整 tick；小數結算參考另有型別 |
| 一般盤 | 08:45–13:45；到期月份最後交易日到 13:30 | 依 contract 與日期建立 session，非到期月不可誤縮短 |
| 夜盤 | 15:00–次日 05:00；到期契約最後交易日無夜盤 | calendar 明訂端點語義，保留交易資料來源的收盤事件 |
| 掛牌／到期 | 連續三個月及三個接續季月；月契約第三個星期三，假日等情形依規定順延 | 實際契約主檔優先於公式，新月份依官方生效時點 |
| 結算 | 日結算沿用對應 TX；最後結算是指定現貨指數平均，現金交割 | 最後一筆成交不可冒充結算價，最後結算事件獨立入帳 |
| 價格限制 | 以前一一般盤每日結算價上下 10% 為基準 | 版本化參考價，缺少所需基準則不宣稱完整撮合有效 |

來源：[TAIFEX TMF 契約規格](https://www.taifex.com.tw/cht/2/tMF)。規格變動與特殊公告需保存 `effective_at`、`retrieved_at`、來源及 hash。

### 2.2 日夜盤 交易日與到期

夜盤歸屬次一一般交易時段，ROD 只對當盤有效。日期不能用 midnight 或無條件 `date + 1` 切割；週五夜盤、長假、臨時休市須透過版本化 calendar 找實際歸屬日。[盤後交易介紹](https://www.taifex.com.tw/cht/4/aHIntroduction)與[日行情下载說明](https://www.taifex.com.tw/cht/3/futDailyMarketView)提供不同欄位日期的官方語義。

`SessionCalendar` 儲存明確 interval：開／收時間、交易日、盤別、適用契約與來源。內部時間 UTC、顯示 Asia/Taipei，另保存來源原字串與精度；資料不足以判定時拒絕，不拿執行當天日期代替歷史。年度 calendar 以 [TAIFEX 行事曆](https://www.taifex.com.tw/cht/4/calendar)及 [2026 官方 PDF](https://www.taifex.com.tw/file/taifex/CHINESE/4/2026Calendar.pdf)為來源，另外支援颱風、提前收盤與臨時公告覆蓋。

換月是實際兩腿事件：平舊月、開新月，各自費稅滑價，可能部分成交或失敗。連續契約只供特徵研究；其調整因子、roll rule、所用價格及生效時點都必須版本化。禁止用當日最終成交量決定當日開盤應交易何月；只能用當時已知資訊。MVP 若某種 roll／expiry／settlement 行為未支援，明確拒絕該資料範圍，不能靜默拼接。

## 3 資料來源 成本與授權

### 3.1 資料取得分層

| 來源 | 已核實範圍 | 使用方式與限制 |
|---|---|---|
| 官方近期每筆成交 | 前 30 個交易日 CSV／RPT，頁面明示不含鉅額 | 可驗證 parser 與合成聚合；不是委託簿，不能證明限價排隊成交 |
| 官方日行情 | 日期／契約查詢、月內區間下載及歷史年度資料 | 留存盤別與月份；不能從日 OHLC 製造 1 分鐘 OHLC |
| TAIFEX OpenAPI | OAS 列有日行情、TimeAndSalesData、最後結算價等端點 | API 確實存在；歷史深度、參數、保留期、SLA／限流仍待驗證 |
| 付費歷史資料 | 官方申購目錄有成交簡檔／成交檔／委託與揭示資料等 | 格式須依實際官方樣本確認，購買與使用範圍另行授權 |
| 合成測試資料 | 工程自己建構且明確標為 synthetic | 可證明邏輯正確，不能證明真市場獲利或流動性 |
| 上市前 TX／MTX proxy | TMF 2024-07-29 前並無真實 TMF 上市歷史 | 只能標 proxy；不可將其他商品歷史改標 TMF |

來源：[每筆成交](https://www.taifex.com.tw/cht/3/futPrevious30DaysSalesData)、[日行情](https://www.taifex.com.tw/cht/3/futDailyMarketView)、[OpenAPI](https://openapi.taifex.com.tw/)／[OAS JSON](https://openapi.taifex.com.tw/swagger.json)、[申購及格式目錄](https://www.taifex.com.tw/cht/3/hisAppForm)、[官方上市文宣](https://www.taifex.com.tw/file/taifex/CHINESE/10/moth_all/202410_all.pdf)。

查核日「期貨成交簡檔」商品頁標價 NT$1,000／半年；「TMF 百分秒成交簡檔」標價 NT$9,000／月，後者範圍從 2024-08 起至申購前一完整月份。這是資料商品價格，不是已批準支出，也不能將全市場商品起始年月當成 TMF 的歷史。[成交簡檔商品](https://edatashop.taifex.com.tw/zh/product/detail/40283ab7890b3664018920782ec40004)、[TMF 百分秒商品](https://edatashop.taifex.com.tw/zh/product/detail/40282eb79a37dc5e019a37e8cfe40000)。

上述付費頁明列單人單機與禁止重製、傳輸、散布第三人等限制。付費原始資料不進公開 repository、CI artifact 或多人雲端。雲端單機、備份、衍生 K 線與模型產物是否允許分享，須取得適用授權確認。公開下載也不自動等於可任意重散布；repository 內預設只用合成或明確允許再散布的小型 fixture。

### 3.2 資料品質與 manifest

每個 dataset 保存：schema version、source type／URL／檔名、原始 hash、encoding、下載／匯入時間、商品及實際月份、coverage、timezone、calendar／aggregation version、license note、品質與驗證狀態。`synthetic`、`proxy`、`official_local` 在 CLI、圖表、報表及比較表始終可見。

匯入時檢查：

- 欄位、編碼與檔案大小／列數；Big5／UTF-8 明確處理，不無限容忍壞字元。
- 有限價格、tick／OHLC 邊界、非負 volume、month 合法性、timezone 與 session coverage。
- 穩定排序與原始序號。同 timestamp 的不同成交不得單靠時間去重；重複檔案或相同行的識別規則要公開。
- 缺檔、缺區間、無成交分鐘、休市區間分開標示；不能 forward fill 成可成交價。
- tick→1m→5m／day 的 OHLCV 與同口徑官方資料比對。價差交易拆腿、是否含鉅額、盤別／單雙邊量與修正版差異要有歸因。
- 每次匯入輸出 accepted／rejected rows、警告與理由；有阻斷性錯誤時不產出「有效回測」。

最新實際匯入樣本只能證明該日期與該 schema 的處理，不能外推成所有歷史格式或長期 coverage 已驗收。

## 4 費稅 資金與回測帳務

TMF 查核日表列期交稅率為契約金額的 0.00002；交易所經手費／結算費／交割費表列每口 NT$4.8／3.2／3.2。券商客戶手續費另議，不可把交易所費用直接當最終費用，亦不可與已含費的券商佣金重複扣除。[TAIFEX 費率表](https://www.taifex.com.tw/cht/4/feeSchedules)、[財政部期交稅說明](https://www.etax.nat.gov.tw/etwmain/tax-info/understanding/tax-q-and-a/national/future-transaction-tax/filing-payment-and-collection-reward/jDxbO8a)。

保證金與券商加成是有生效日期的資金需求，不是固定的交易損失。TMF 基準依 TX 的 1/20 訂定；期貨商不可低於適用原始／維持標準。[保證金制度](https://www.taifex.com.tw/cht/5/margingReqIndexFut?menuid1=12)。不把查核日金額硬編碼成所有歷史要求。

`CostSpec` 至少含每邊 all-inclusive commission、tax rate、稅額 rounding、slippage ticks、effective date、version。當沖、交割與保證金另有 schedule。實際逐筆／合併計稅及進位規則仍需用官方或券商對帳範例核實；未核實前必須在結果標示假設，不能聲稱券商逐筆對帳一致。

帳務不變量：

1. 一口 TMF 買 20,000 賣 20,010，未扣費為 NT$100；反向空單由方向及開平價決定，成本兩邊均扣。
2. 期貨不是買進時扣除完整名目本金；equity＝cash＋未實現損益。margin 限制可用資金，不直接當虧損。
3. 部分平倉、多口、翻向與換月使用明確 lot matching；每腿各有成本，round-trip 分組規則固定。
4. 日結算 MTM 更新基準與 cash；平倉後不得再把之前已入 cash 的 MTM 算一次。
5. Slippage 反映在不利成交價，若另列 attribution 不能再次從損益扣除。
6. 未平倉部位保留並按可用價格標記；不在回測結束時默默假設免費平倉。
7. 未實作或資料不足的維持保證金／追繳／強平情境，要明確拒絕或標為排除範圍。強平不可假定觸發價零滑價成交。

## 5 因果回測核心

### 5.1 時序契約

bar.timestamp 表示區間開始，bar.end 表示資訊最早完整可見時間。每根 bar 依序處理前次決策留下的委託、成交／停損停利、帳務及風控，再讓策略看見已完成 bar 並產生新訊號。收盤訊號最早下一可交易事件成交，不在同根已知 close 回填較有利價格。

成交模型必須揭露 OHLC 限制：gap 穿過 stop 用可取得價格；同 bar 同碰 stop 和 target 採 conservative 並標記 ambiguous，或要求 tick 級資料。限價碰價不能當作必成交；缺少 queue／bid-ask 的資料不得聲稱模擬完整市場微結構。成交量參與上限與流動性若未建模，也需列在適用範圍。

### 5.2 Golden 與因果測試

必要 corpus 涵蓋多／空、部分平倉、費稅進位、日夜盤／跨午夜、到期早收、換月兩腿、日結算／最終結算、next-bar lag、gap stop、同根衝突、非法半 tick、missing data、資金／margin 不足。預期帳本須人工獨立計算，不能直接把引擎第一次輸出當 expected。

對任意歷史前綴，新增未來 bars 不得改變過去訊號或已產生的成交；測試 warmup 不填零、負 lag 拒絕與特徵 cutoff。相同 dataset／spec／config／seed 三次的 canonical ledger hash 必須完全相同。hash 排除 wall-clock 耗時，但保留 deterministic execution assumptions；保存 metadata 不等於允許任意變動價格或成本。

## 6 五種策略家族與受限 DSL

| 家族 | 獨立交易假設 | 最小因果實作 | 必需不同觸發 fixture |
|---|---|---|---|
| 趨勢 | 中期方向可延續 | fast／slow average crossing，warmup 後進出 | 先盤整後單向變化；不同於單根跳價 |
| 均值回歸 | 價格偏離局部均值後回歸 | deviation band entry、mean exit | 過度偏離後收斂，並檢查趨勢市停損 |
| 通道突破 | 已知區間的突破形成新方向 | 前 N 根 high／low，排除當根 | 當根創高需突破歷史通道，不讓當根抬高門檻 |
| 動能 | N-bar return 超過閾值後短期延續 | lagged return threshold、bounded holding | 平滑加速／減速，持有期到時退出 |
| 波動壓縮擴張 | 先收斂後突破代表新波段 | 過去 quiet-range 條件＋因果突破 | 同樣突破但無壓縮先決條件不能觸發 |

這五類是本次凍結的最小家族，不能把同一均線的五組參數充數。開盤區間、多因子、ML 訊號與自適應組合可作後續研究，避免第一版引入需額外資料或難解釋的模型。

策略規格包含名稱與不可變 hash、商品、timeframe、family、typed parameters、進出場 AST、停損停利、最大口數／持有時間／頻率、session、schema version、適用環境、AI 理由與假設。使用者顯示名稱不是版本身分；理由文字不能覆蓋規則或 hard risk。

DSL 是有限 JSON AST：常數、白名單 OHLCV 欄位／指標、非負 lag、比較與布林運算。驗證包括未知欄位、型別、值域、參數依賴、warmup、bytes／depth／node／lookback 上限。拒絕任意 Python、eval、import、function call、檔案路徑、URL、負向位移與無界迴圈。正規表達式掃描只能輔助，不是 AST 驗證器。

## 7 AI 產生 評估與改善閉環

`Generator.generate(context)` 產出初始 candidate；`Generator.improve(context)` 根據受限的 train／validation 摘要提出單一可檢驗假設及新版本。預設 `FixtureGenerator` 是可重現的離線替身。相容模型 provider 只在明確 endpoint、網路 opt-in、注入 transport、timeout／token／call／spend budget 已設定時可運作；預設不呼叫付費 endpoint。

每次迭代：

1. 固定 campaign ID、資料與 split、五家族、成本／撮合假設、風險與排名、資源上限。
2. 生成候選並保存原始模型輸出、provider／model／prompt-template version、parent ID。
3. 驗證 DSL。拒絕、例外、取消與逾時都記 trial 並消耗額度。
4. 只在 training／validation 計算與分析交易紀錄；改善需說明「何種原因、改哪個規則、預期哪個指標改善及可能代價」。
5. 產生新 hash 版本，重跑同一成本／風險／資料協定，比較新舊而非只展示較好的結果。
6. 到固定停止條件後凍結候選，執行 OOS，再由隔離評估者讀 final holdout。
7. 存入策略庫，顯示通過／拒絕原因。使用者選擇不等於正式啟用。

固定最小上限為五家族、每家族最多三個候選，合計 15 trials；每家族最多兩次 improve。其餘 wall time、每 trial timeout、平行度、記憶體、token／spend 必須在 campaign 啟動前落入 config。預算耗盡即保存並停止，不改名稱重開以繞過上限；重啟由持久帳本恢復預算。

真實 provider 沒有經授權連線驗證前，狀態永遠是 `NOT_VERIFIED`；fixture 通過只證明協定與控制流程。保存 DSL 才是可重放的研究主體，不能因 LLM 有 seed 就保證再次生成同一答案。

## 8 研究切割與績效可靠性

- 以時間切 training、validation、OOS 與 final holdout。每個 walk-forward fold 僅使用該輪 training fit scaler、特徵選擇與模型；validation 供有界改善。
- 因標籤或持有期跨界造成重疊時 purge；embargo 按最大持有期、特徵可用時間與資料延遲設計，不能套無理由固定比例。
- 在訓練末端做為 test 指標 warmup 的已知價格可使用，但不得把 test future 反向 fit；warmup 範圍與 cutoff 必須記錄。
- 生成器不得取得 OOS／holdout bars、結果或摘要。凍結候選集合後 final holdout 一次評估，使用紀錄持久化；重新啟動或新 campaign 名稱不能讓已看過區間再被稱作 untouched。
- 全部人工／自動嘗試、早停、失敗都計入搜尋歷史，揭露試驗總數與相關性。期貨亦有 survivorship 類偏誤：只留下活躍月份、忽略已下市合約或事後選最高流動性月份都會失真。
- DSR 可做多重測試與非正態調整；PBO／CSCV 可補充排名不穩定診斷，但都不能取代時間 OOS 或解讀為未來獲利保證。公式輸入、有效獨立 trials 假設與樣本不足需揭露。[DSR 原始論文](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)、[PBO 原始論文](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)。

資料洩漏會讓跨領域研究的泛化估計失真，切割、前處理及評估均需可稽核；參考 [Kapoor 與 Narayanan 原始研究](https://doi.org/10.1016/j.patter.2023.100804)。

績效接受門檻必須在看結果前固定。研究平台能完成資料→生成→改善→比較，即為流程能力；策略是否 RESEARCH_PASS 是另一个判定。樣本太短、沒有足夠交易、holdout 已污染或成本未知時，保持 `BLOCKED`／`REJECTED`，不可降低門檻換成功標籤。

## 9 報告 策略庫與使用者介面

### 9.1 指標定義

| 指標 | 必須公開的計算與例外 |
|---|---|
| Net Profit／Return | 分開已實現、未實現、費、稅、slippage；報酬分母為明訂初始 equity，非含糊 margin |
| Max Drawdown | equity 峰谷差及百分比、區間與恢復時間；持倉浮虧不能忽略 |
| Win Rate／Trade Count | 以明訂 round-trip／lot 配對計數，部分平倉規則固定，不用 fills 數冒充策略交易數 |
| Profit Factor／Average Trade | 正／負淨損益及每筆平均；無虧損／無交易時標 null＋原因，不用 infinity 排第一 |
| Sharpe／Sortino | 交易日 equity returns、無交易日處理、年化係數、risk-free／target return 與 downside 定義 |
| Calmar | 年化報酬與最大回撤關係；短資料、不足一年或零回撤須揭露不可算／年化假設 |
| Equity Curve | 與 ledger 的逐日／逐事件對帳、開放部位及費用影響 |

另提供日／夜盤、年份、波動環境、IS／OOS／holdout、最大連續虧損、交易頻率、成本壓力測試。跨盤持倉的損益歸因先固定，例如按 mark-to-market 時段分配，不能把全部浮盈任意歸入勝出盤別。相關性用相同交易日對齊的成本後策略報酬，保留零交易日，不以不同樣本的成交序列直接相除。

排名至少同時展示淨報酬、drawdown、樣本數、OOS、成本敏感性與不確定性。基準可包含不交易與明確的簡單策略；期貨 buy-and-hold 需要 roll／margin／成本模型，不可直接拿指數點數當可投資報酬。

### 9.2 版本與狀態

StrategySpec hash 定義不可變版本，連結資料／engine／cost／calendar／split／prompt version 和全部 trials。研究、選擇、paper 核準與正式核準分離。建議生命週期：DRAFT → VALIDATED → RESEARCH_PASS → PAPER_APPROVED → PAPER_PASS → LIVE_APPROVED → ACTIVE；另有 REJECTED／SUSPENDED／RETIRED。

本次實作即使先只覆蓋其中前段，也須清楚表示未支援狀態。更動任何參數／資料／引擎／風險或成本會建立新版本，原驗收不自動繼承。AI 不能自行把版本提升至正式狀態。

### 9.3 Streamlit 頁面

1. 本機資料匯入與品質：來源、license、coverage、schema／calendar、拒絕列、synthetic／proxy 警示。
2. 五家族策略：原理、參數、warmup、風險與可用資料。
3. 回測：可編輯但版本化 config、逐筆 ledger、equity、成本及限制。
4. 研究歷史：generate／improve 親子版本、all trials、預算、來源與停止原因。
5. 比較與選擇：多指標、盤別／年份／OOS、相關性與不可變版本識別。
6. Paper：風控、帳戶、journal、pending／UNKNOWN、對帳與 kill switch。

畫面清楚標示離線研究／模擬，沒有一鍵啟動真實交易。重複按鈕、頁面 rerun／重新載入不得新增重複 trials 或訂單；重啟從已驗證的持久結果恢復。匯出 JSON／CSV 使用安全輸出根，文字欄位防 spreadsheet formula injection，錯誤訊息不暴露秘密。

## 10 Paper 與券商 Adapter

### 10.1 Paper 狀態與風控

持久 intent 在執行前寫入 SQLite transaction；相同 `client_order_id`＋相同 payload 冪等，payload 不同則衝突。event ID 相同且內容相同可忽略；內容不同為異常。ACK、fill、cancel、reject 分事件，允許部分成交與取消競速，但不能破壞已成交帳務。

風控包括商品／時段、報價 age、價格範圍、最大口數／單筆量、資金／margin、日最大虧損、連敗停機、頻率與重複 intent。尚未實作的風控項不可勾選成通過。kill switch 阻止新單；撤單與市價平倉為不同操作，不暗藏於停止按鈕。

UNKNOWN 必須阻新單，先查詢／對帳，不自動重送。恢復時以持久 journal replay 與 snapshot 交叉核對，再比對未結單／成交／部位／cash。外部手工交易、缺回報與費用差額形成 reconciliation exception，不默默覆寫舊歷史。

### 10.2 Adapter ports 與真實就緒

拆分 `MarketDataPort`、`HistoricalDataPort`、`ReadOnlyAccountPort`、`OrderExecutionPort`。各 adapter 提供 capability matrix：商品／order type／partial fill／cancel／query／reconnect／限流／paper 支援，不以空 dict 假裝成功。broker symbol 由版本化映射轉 canonical contract ID，未知即拒絕。

| 券商官方資料 | 已核實 | 不得推論與後續問題 |
|---|---|---|
| 兆豐期貨 API 入口 | 期貨官方入口連至 API；專頁有期權同意書、風險文件、測試報告與 Windows／.NET 元件；測試環境與固定 IP 流程說明 | 新版證券 Python FAQ 不等同所有期貨帳號可用；TMF symbol、期貨 SDK／架構、歷史資料、費用、IP 與恢復須正式確認 |
| 台新期貨既有 API | 官方下載頁有 API 版本與 ClickOnce／.NET 資源 | 不能猜為 REST／跨平台；OS、驗證、paper fills 與權限待確認 |
| 台新證券 Core／Nova | 官方提供 Python／C#、期貨相關文件、簽署／驗證與數位憑證；Nova 有期權行情文件 | 不同法人／品牌與舊帳號不可混接；期貨下單驗證不等於完整模擬撮合 |

來源：[兆豐官方入口](https://www.megafutures.com.tw/emegaFutures/sitemap.do)、[兆豐 API](https://project.emega.com.tw/project/megaapi/)、[新版 FAQ](https://www.emega.com.tw/emega/upload/megaapi/faq.html)、[台新期貨 API](https://vipws.tsfutures.com.tw/API/)、[台新 Core](https://mlapi.tssco.com.tw/web_api/service/home)、[Nova 期權行情](https://ml-fugle-api.tssco.com.tw/FugleSDK/docs/market-data-future/http-api/getting-started/)。

當前只設 stub／replay／paper；`LiveBroker` 固定 raise `LiveTradingDisabled`，不讀 credentials、不 import SDK、不連線。未取得適用正式文件及帳戶資格前，broker certification 為 BLOCKED。未來若 SDK 僅 Windows，再設單獨 Windows bridge，不能先為推測需求建立持久權限。

## 11 故障恢復 可觀測性與運行邊界

必測事件：接受後 ACK 逾時、fill 早於 ACK、部分成交後取消、取消與成交競速、重複／亂序回報、行情 gap、重連缺訊、手工外部交易、每個 journal crash point 與重啟。網路送單不宣稱 exactly-once；只有券商確認的冪等協定才能支持對應語義。

log／metrics 共用 data batch、run、strategy hash、signal、intent、broker order、fill 與 reconciliation ID；保留 event time／received time、拒絕理由、budget、queue lag、stale age、未決單與差異數，不含 token／帳戶秘密。critical alert 需要投遞結果與處置說明，而非只呼叫通知函式。

離線核心可指定 RPO 為已提交 journal 事件零丟失並以 crash tests 驗證。真 broker RPO／RTO、觀察期與最低事件數需依實際環境預先固定；未量測前不承諾無人值守。還原需要驗證檔案／版本 hash、事件重放、cash／position 一致；資料或對帳不足即維持停機。

最終核準必須同時綁定策略版本、資料與成本、風險限額、執行環境、broker capability 與明確操作者。金融帳戶條款、憑證與真實交易另有授權與人工操作要求；開發完成度不包含真實獲利或交易權限。


## 必要桌面產品形態增補

最終一般使用者下載安裝檔、安裝、雙擊捷徑即可進入原生繁中Qt介面，不須Python／pip／Git，不另啟後端。UI與quantlab核心分離；模型僅產受限DSL，選用HTTP provider在隔離子程序以固定DPAPI resolver讀取金鑰，端點／費用／Token與呼叫上限及本次網路同意明確呈現。預設Fixture，外部模型仍需配置及驗證。

候選picker重用不可變StrategySpec，不要求手動複製程式；產生、改善、凍結、OOS／holdout與研究歷史依既有服務。模型輸出無任意程式執行／檔案／券商權限。真正市場環境適用性与策略推薦必須有足夠資料與研究證據，不能把UI排序當投資建議。

設定與資料在使用者應用資料區；可選工作區於下次重啟才切換，不自動搬移或覆寫。機密與研究不可回退帳本留固定bootstrap，不隨資料備份還原回退。預览安裝器、發版條件、未簽章及乾淨Win10/11外部Gate詳見Roadmap與packaging說明。

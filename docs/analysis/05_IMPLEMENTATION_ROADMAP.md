# TMF AI 研究平台實作路線與固定驗收

建議採方案 C 的有界版本：保留 Python、Streamlit、既有授權、操作經驗與可抽取公式，新增與舊交易樹隔離的最小研究核心。先完成本機行情到策略比較的可重現閉環，再驗證 paper 恢復；真實模型、真券商與實盤各自設外部就緒條件。

本路線提供可交給工程 Agent 接續的工作契約與停止標準。原始基線為 `1cacce4ee4eef4ce7e8760f8153ef64a74852d22`，查核日期 2026-10-09。原始分析已完成，後續自主實作進行中；本文的要求不是對未完成項目的成功宣告。

## 1 目前狀態與不可混用的進度

截至 2026-10-09 16:18 UTC，固定開發清單 Phase 0–4 已登記 PASS，合計 **85%，剩餘 15%**。唯一計分來源為 [ACCEPTANCE.json](../agent/ACCEPTANCE.json)，本段為時間快照。

- 完整本地測試 176 PASS、0 SKIP，包括 5 個 Streamlit AppTest；真模型、實盤與長期無人值守不在此結論內。
- 舊交易入口刻意停用；新研究、版本比較及 Paper 故障測試已實作，最終交付 Gate 待 fresh-checkout、安全複掃與遠端 CI。
- 官方 2026-10-08 CSV／RPT 已匯入 1140 根分鐘 K 並比對 OHLC；成交量差異保留價差單口徑限制，原始行情不提交公開 Git。
- 新增安全 refresh CLI，已實際下載官方公布的下一交易日期 2026-10-12 檔案；標記 provisional_unverified，不能當完整盤或正式排名依據。
- GitHub 新授權已驗證 Git 物件／分支／PR 寫入；[PR #1](https://github.com/yostar77612/mark-auto/pull/1) 尚未合併。Git CLI 無登入，支援的 GitHub 連線採同 tree 的新提交映射發布，保留所有原本本地提交。
- wheel／sdist 建置曾通過，需重驗最終版本；Windows CI、實際模型、券商認證與完整歷史資料均分別驗收。

原分析任務的六階段權重為 25／25／15／15／15／5，只衡量調查與文件；目前開發 Phase 0–5 採 15／15／25／20／10／15。兩者是不同分母，不合併、不挪用原分析進度當新功能完成率。測試個數與投入時間都不能直接換成百分比。

## 2 原始系統到目標的差距

| 領域 | 原始基線 | 必要新成果 | 優先度 |
|---|---|---|---|
| 安全開發 | 匯入連動 broker／DB，TLS、Telegram、log 有已確認缺陷 | 舊危險路徑停用／修復，研究不具交易能力 | P0 |
| 市場資料 | generic KBar／crawler，缺歷史 calendar／manifest | TMF 明確月份、日夜盤、品質與授權、不可變快照 | P1 |
| 回測 | `reports.py` 匯入不存在的 backtest | causal engine、ledger、cost／margin／expiry／roll golden | P1 |
| AI 研究 | 無 provider、DSL、campaign | 五家族、有限 DSL、generate／improve、預算與全部 trials | P2 |
| 可靠評估 | 無 walk-forward／OOS／holdout 控制 | 凍結 split、purge／embargo、一次 holdout、版本化結果 | P2 |
| 策略庫與 UI | 動態 Python hooks 與交易操作 GUI | immutable registry、可追溯報表、比較與人工選擇 | P3 |
| Paper 恢復 | 局部模擬記帳，共享可變狀態 | durable journal、冪等、風控、unknown 阻單、故障對帳 | P4 |
| 正式執行 | 舊 Shioaji 路徑，無台新／兆豐適用性認證 | 正式 broker capability、權限、恢復演練與獨立核準 | P4 外部 readiness |

關鍵證據：[broker 預設](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L14-L16)、[匯入副作用](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/__init__.py#L16-L26)、[缺少回測核心](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/reports.py#L18-L18)、[成本／TMF 問題](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L69-L81)、[動態策略耦合](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/strategy.py#L6-L45)。完整對應見 [02 功能表](02_EXISTING_FEATURES.md)及 [03 風險表](03_CODE_QUALITY_AND_RISKS.md)。

## 3 方案 A B C 比較與決策

| 方案 | 優點 | 缺點及主要風險 | 開發成本 | 維護成本 | 重做範圍 | 適合程度 |
|---|---|---|---|---|---|---|
| A 保留原架構直接擴充 | 早期 UI／下單範例多，短期改檔少 | 研究依賴 broker／DB 與共享狀態；缺失 engine 仍得新增；容易以模擬旗標誤當隔離 | 表面低，後期耦合排除高 | 高，跨模組回歸難 | 在原樹補 calendar／回測／AI／版本管理 | 不建議作研究主架構 |
| B 保留核心局部重構 | 沿用更多類別，逐段抽介面 | 需先對 live-oriented 基底大量拆依賴；無測試使「保持原行為」難證明 | 中高，先重構再產出閉環 | 中，取決於是否真正消除父套件副作用 | 修改 config／executor／state／storage，同時新增研究 | 未來 adapter 抽取可用，本次不是最短路 |
| C 保留可重用功能並建立必要核心 | 清楚安全邊界，可離線 fixture 驗收；不必先恢復所有股票／broker 功能 | 需維護新舊邊界、部分概念暫重複；若範圍失控會變全面重寫 | 中，新增範圍可限在缺失核心 | 研究低至中；legacy 另有負擔 | sibling quantlab、data／engine／DSL／registry／paper，薄 UI | **本次建議** |

選 C 的原因是原基線沒有可直接保留的完整研究核心。新增 engine 並非替換一套已經驗收的 engine；隔離能省去先修完整 broker stack 的成本。保留 `trader` 作來源參考與可控遺留區，保留 Apache 標示、Python／Streamlit、公式與操作知識；純化後的小型函式可逐步重用。

明確不做：為了新架構整庫改名、重寫全部股票／選擇權、另造前端／API 微服務、為可能的效能問題換語言、先建分散式研究平台。所有新增技術需由可測瓶頸或已確認功能需求支持。

## 4 第一版 MVP 的可交付閉環

### 4.1 必備內容

1. 本機已合法取得的官方格式資料與合成 fixture，明確 calendar、contract、cost／margin；匯入品質報告與不可變 hash。
2. 因果 bar 回測：多空、日夜盤／跨日、明確 roll／settlement、next-event 成交、費稅／滑價、風控與逐筆 ledger；不支援情境失敗關閉。
3. 五個真正不同的策略家族及 trigger fixtures：趨勢、均值回歸、通道突破、動能、波動壓縮擴張。
4. 受限 DSL 與離線 FixtureGenerator，完整 generate→validate→evaluate→improve→freeze→OOS／holdout 流程；真模型另有可配置但預設停用的 provider boundary。
5. 15-trial 上限、兩次改善上限、持久預算與所有嘗試紀錄；重啟不重開預算，不反覆使用同一未見測試區間。
6. Streamlit／CLI 同服務層，能看品質、策略、帳本、成本、比較與選擇不可變版本；保留資料及模型來源標示。
7. 離線單元／golden／整合／安全測試、操作文件及版本 manifest。

這定義的是**研究 MVP**。合成／fixture 路徑可證明工程闭環，不能被改稱「真實 AI 已找出可獲利 TMF 策略」。真模型呼叫與足夠、授權完整的市場資料未驗證時，該部分維持 NOT_VERIFIED／BLOCKED。零候選達績效門檻不代表平台實作失敗。

### 4.2 MVP 後立即相接的交付

PaperBroker 持久恢復是本次整體開發的後段，與研究 MVP 分開驗收。加入 intents、事件 journal、risk／stale／margin、kill switch、對帳及故障回放後，才有資格討論前瞻模擬觀察。真實 broker 開通、帳戶簽署、付費資料／模型與真金交易不包含在工程百分比，也不能自動啟用。

### 4.3 明確延後

完整 tick order-book／queue 模擬、機器學習／深度學習訊號、自動投資組合配置、分散式搜尋、遠端多使用者角色系統、即時付費行情、向量資料庫、Kubernetes、broker Windows bridge 與無人值守生產服務，均等核心資料／帳務／恢復及需求明確後再評估。

## 5 最小工作包與依賴

以六個可交付模組工作包安排，不拆數百個微任務。優先度 P0–P4 指產品順序；Phase 是固定計分階段，兩者不混用。

| 包與優先度 | 用途／為何需要 | 基線與可重用內容 | 修改範圍 | 依賴與風險 | 固定交付與驗收 |
|---|---|---|---|---|---|
| W0 安全基底 P0 | 讓開發不會觸及真交易／秘密，建立可測邊界 | 舊 runtime 技巧、風險發現；沒有可信離線入口 | 安全封鎖、`quantlab` 純入口、tests／CI／packaging | 無前置；風險是遺留入口仍可繞過 | R01–R05 關閉或停用；拒 broker／網路／秘密；測試可追蹤；CI 最小權限 |
| W1 資料與契約 P1 | 同一策略用同一資料與歷史規則 | 原聚合／欄位僅參考 | `core.py`、`data.py`、data／core tests | W0；calendar、schema、license 不完整 | 本機官方格式＋quality；session／expiry；hash 不變；缺覆蓋拒絕 |
| W2 回測與帳務 P1 | 可信計算先於策略搜尋 | 指標／圖表概念可抽取；backtest 缺失 | `strategies.py`、`backtest.py`、golden tests | W1；時間與費稅錯誤會污染所有研究 | 五家族因果觸發、long／short／cost／roll／MTM／expiry golden；三次同 hash |
| W3 AI 研究 P2 | 把生成與改善變成有限可追溯實驗 | 基線無對等能力 | `research.py`、DSL／campaign／provider tests | W1–W2；洩漏、過擬合、超預算 | 15 trials、schema 拒絕 corpus、generate／improve、all attempts、隔離 OOS／holdout、真模型來源誠實 |
| W4 報表與版本選擇 P3 | 使用者能理解並選擇多策略 | Streamlit／Plotly 使用概念 | `reporting.py`、`research_app.py`、`__main__.py`、UI／CLI tests | W1–W3；指標誤導、重複按鈕與版本覆寫 | ledger 可追溯、不可變 registry、empty／error／rerun、restart；選擇不下單 |
| W5 Paper 與交付 P4 | 故障時不重複單且能恢復 | 舊訂單／部位概念，僅參考 | `paper.py`、risk／recovery tests、文件、最終驗收 | W0–W4；unknown、資金差異、偽實盤就緒 | 持久 journal、fault matrix、stale／margin／daily-loss、disabled live、完整最後版本驗證 |

最短依賴鏈是 W0→W1→W2→W3→W4。W5 的 pure risk／journal 可在 W1 interface 凍結後平行開發，最終整合須等待策略／report identity 穩定。文件與官規研究可平行，但不能以文件完成補足 code gate。

## 6 固定 Phase 0 至 5 驗收

每個 Phase 有五個等權子項。只有帶可重現證據的 PASS 得分；FAILED、BLOCKED、NOT_RUN 為零。Phase 全部強制子項通過才能宣告該階段完成；安全失敗獨立否決 release。不得因績效不好、花費超時或測試難寫而降低原門檻。

| Phase 權重 | 五個固定子項 | 必留證據 |
|---|---|---|
| 0 審查與架構 15% | 來源與 SHA；完整可達歷史安全掃描；依賴／入口；模組責任契約；固定驗收清單 | 固定程式連結、掃描範圍、限制、contracts／acceptance |
| 1 安全工程 15% | 舊路徑修復／封鎖；純匯入無秘密／網路；獨立測試入口；離線 CI 設定；防護回歸 | 測試命令／結果、source diff、CI permission 與語法；遠端 CI 狀態另列 |
| 2 資料與回測 25% | 官方 local schema／quality；calendar／expiry；因果 engine／ledger；cost／獨立 golden；manifest／三次重現 | schema 樣本來源、品質差異與口徑、手算 expected、結果 hash、因果負向測試 |
| 3 五策略與 AI 20% | 五種不同因果策略；DSL 拒絕 corpus；generate／evaluate／improve 與 provider provenance；持久預算及 all trials；OOS／holdout 隔離與 consumed marker | 所有候選／失敗、budget counters、注入與timeout測試、split hash、禁止存取證據 |
| 4 UI 與版本庫 10% | Streamlit import→run；不可變比較／選擇；指標與匯出追溯；empty／error／重複操作；重啟持久化 | AppTest／操作路徑、檔案 hash、CSV 安全、結果重載、選擇未觸發交易 |
| 5 Paper 與交付 15% | journal／冪等／恢復；故障及風控；實盤停用／安全複掃；五文件／操作維護；最終全測試／UI／fresh-checkout／CI 重現 | fault traces、持久對帳、最終 commit／env、實際測試與發布限制 |

明確分開四種判定：

- **工程 gate：** 正確完成規格與保護，無候選勝出也可通過。
- **研究 gate：** 預先固定的成本後 OOS／風險／統計標準；目前不能擅自填入獲利目標。
- **Paper gate：** 正確性故障測試與前瞻模擬觀察各有證據，後者期間／事件數需先固定。
- **正式就緒 gate：** broker／帳戶資格、行情 license、認證、風險限額、恢復、操作人與核準。即使達到，也不賦予工程 Agent 真實交易權限。

## 7 測試與重現的最低證據格式

每次可驗收變更附：目標版本、修改檔案、接受條款 ID、測試命令、Python／OS／依賴版本、退出碼、PASS／FAIL／SKIP 個別原因、input／expected／output hashes、未驗證範圍與回退方式。不能只寫「測試正常」。SKIP 的強制驗收項不得得分。

Golden 覆蓋：多空／部分成交／費稅、signal lag、gap／同根衝突、跨夜／到期／假日、roll／每日與最終結算、缺資料／半 tick／margin 拒絕、三次重現。風控不變量與非法狀態轉移需負向測試；每個已確認缺陷先有 regression fixture。變更 expected 必須寫清原因，不能批量更新以掩蓋錯誤。

外部資源全禁止的核心 test 與需要本機選用 Streamlit 套件的 UI test 分層；UI 套件有無安裝不應影響核心匯入。CI 不登入 broker、不持有交易 secrets、不下載付費資料、不呼叫模型；下載安裝依賴與「測試執行時無網路」是不同階段，需在 runner 明確區分。

最終版本需要重新跑完整 suite、CLI demo、合成 campaign、結果重載、UI empty／error／rerun、paper restart；另外從乾淨 checkout 在宣告支援環境重跑。已通過的較早版本測試不自動涵蓋其後修正。Windows 是目標環境，Linux 通過不能直接標示 Windows PASS。

## 8 效能 資源與成本

### 8.1 初步量測與正式基準

開發期間已有 Linux Python 3.12、synthetic 1,000 bars、trend、5 次執行的初步結果：中位約 0.522 秒、`tracemalloc` peak 約 2.68 MB、輸出 hash 相同。這是小型特定工作負載，不是 Windows、1 百萬 bars、RSS、p95 或整個 campaign 的服務保證；後續程式變更需重測，不能把該數字當最終 release 指標。

正式 benchmark 需記錄 CPU／RAM／OS／Python／版本／fixture hash，區分冷暖啟動；至少 5 次，固定 quantile 算法，報告 p50／p95、peak RSS、Python allocation、CPU、磁碟與 queue lag。採階梯 workload：1,000 bars golden、100,000 bars 壓力、目標 1,000,000 bars 與固定 trial 集合。超過可接受資源時停止並保留失敗，不任意放寬。

相對 gate 建議在首個目標 Windows baseline 量測後凍結為中位耗時不退化超過 10%、RSS 不退化超過 15%；現在尚未量測 Windows，不能宣稱已達到。絕對吞吐／時延 SLO 應基於資料頻率、CPU／memory 與 UX 需求訂定，而非隨意承諾毫秒級。benchmark 耗時不得進 deterministic result hash。

### 8.2 研究預算

固定硬上限為五家族 × 每家族最多三候選＝15 trials，最多兩次改善；所有 attempts 包含拒絕／錯誤／取消。模型支出預設 0；真實呼叫須先有明確 provider、endpoint、data disclosure 與費用權限。

每次 campaign 另外鎖定：max runtime、trial timeout、max calls／tokens／spend、parallel workers、memory、輸出容量、retry／early-stop 規則。可用於首次非付費研究的保守資源提案為每 trial 300 秒、campaign 120 分鐘、最多 2 worker、每 worker 4 GiB；這是待適用環境確認的運行設定，不修改已凍結的功能驗收。實際值須寫入 manifest，實作未具強制限制者列為未通過，不靠提示文字冒充限制。

同樣基礎設施錯誤重複到預設上限即停止該工作；安全／帳務／因果違規立即停止。無 validation 改善採固定 early-stop，不為尋找贏家擴大 trial 數。預算耗盡後 checkpoint 並停止，重啟不重置，也不能換 campaign 名繞過。

### 8.3 提高效率而不犧牲可驗證性

- 先 profiling 再優化；將反覆載入資料與 hash 的成本區分於策略計算。
- 可快取純特徵，但 cache key 必須含 data／calendar／indicator version、lookback、split boundary，不跨 fold 洩漏。
- 使用局部最小 diff 與共享固定介面降低整合返工；重用已確認的官方資料與授權說明，不反覆下載大檔。
- 研究核心不安裝整套 legacy broker／Web dependencies。UI 選用環境獨立、可重現並掃描，不把一次無已知漏洞回報擴張成全系統保證。
- 沒有實測瓶頸前不導入 GPU／distributed queue／多 Agent 市場辯論，也不將複雜 infra 當作研究成果。

## 9 Agent 與 Git 工作流程

每個工作包先有目標、允許修改檔案、禁止範圍、依賴、固定測試／golden、時間／費用上限、可交付證據與停止條件。可以自主修復已授權範圍的問題；不得自行提高交易權限、讀秘密、加入付費服務、改接受標準或啟用實盤。

### 9.1 分工與介面

- 單一檔案只有一位負責者，避免並行覆寫；共享 core、packaging、CI 與合約由整合者協調。
- 先凍結 value schema，再由 engine／campaign／paper／UI 依公共介面開發；不可倚賴另一模組的 private field。
- 若介面需改，先記錄理由與新驗收／相容策略，再同步 caller；不讓各自猜測參數格式。
- 工作報告先給可使用結果與阻塞，再附修改、測試與限制。任何安全或授權問題立刻停止受影響路徑，獨立工作可繼續。

### 9.2 Git 與發布

使用一個主分支、短命功能分支與小型可審查 commit；無獨立發版需求不增長期 release branch。不以每個 AI 候選建立 Git 分支，策略版本由 registry 管理。禁止把 raw paid data、帳戶資訊、tokens、runtime journal 或下載 cache 納入 commit。

每個 commit 對應一個可驗收成果，附測試與回退。進入 PR 前檢查 diff、秘密、LICENSE／修改標示、文件與結果來源；CI 採最小權限，外部 PR 不提供 secrets。無權限、遠端測試未執行或 required check 失敗時，發布保持 BLOCKED，不能繞過存取拒絕或以本地測試替代遠端結果。

合併前最終版本重跑完整驗證，記錄 commit 與 artifact hash；合併後確認主分支內容與 CI terminal 狀態。若發生問題，回退程式與 config／schema 按既定步驟處理，保留歷史資料與 journal；不以破壞式 reset 或刪除失敗 trial 美化成果。

## 10 操作接續與故障處理

先閱讀 [IMPLEMENTATION_CONTRACTS.md](../agent/IMPLEMENTATION_CONTRACTS.md)、[ACCEPTANCE.json](../agent/ACCEPTANCE.json)及實際檔案狀態，確認最新工作是否仍在修改。以下是新離線入口的操作範例，使用已準備好的研究環境；不能換成舊 `run.py`／`gui.py`。

```text
python -m unittest discover -s tests -v
python -m quantlab --help
python -m quantlab demo --output quantlab-output/demo
python -m quantlab campaign quantlab-output/demo/dataset.json --output quantlab-output/campaign
python -m streamlit run research_app.py
```

`demo` 與未另行指定的 campaign 使用合成資料／fixture 與標示假設的成本，不能當真實研究結果。真實檔案 `import` 需提供明確 `--calendar`、`--kind`、輸入路徑與輸出；依資料來源選 supported schema，不猜欄位。真市場 backtest 應提供核實的成本／margin config，不能沿用 demo 假設後把結果標成正式。

| 異常 | 立即行為 | 恢復條件 |
|---|---|---|
| schema／hash／calendar 不符 | 不產生有效 run，保留品質錯誤 | 正確來源與版本確認後新 dataset／run |
| ledger／golden 不一致 | 停止候選排名與 paper 晉級 | 修正、獨立 expected 審查、完整回歸 |
| provider timeout／預算耗盡 | 記 failed attempt 與已消耗額度，停止或按固定規則重試 | 不超出既有 budget，未授權不得換付費服務 |
| holdout 已使用 | 標示 consumed，不再提供改善 feedback | 新未見資料或已預先定義前瞻觀察 |
| paper UNKNOWN／cash／position 差異 | 阻新單，不盲重送、不自動反向補單 | journal／快照對帳一致，明確恢復操作 |
| secrets 疑似洩漏 | 停受影響路徑，不公開值／logs | 擁有者確認、必要時撤銷輪替與稽核 |
| 不具真 broker／資料授權 | 維持 mock／paper 或停止相關來源 | 官方資格、文件與授權證據完成，仍需獨立交易核準 |

備份包含研究 config／registry、manifest、結果與 paper journal，按其 license 與敏感性放在適當私有儲存。還原必測 content hash、事件重放與cash／positions；不要只檢查「檔案存在」。本機離線 RPO／RTO 先以測試證明，真實服務則需實際環境演練才能承諾。

## 11 尚存阻塞與下一步

1. **資料完整性與授權：** 長期 TMF coverage、歷史 margin／tax rounding、假日／臨時公告及價差量精確口徑還需對應證據；一日樣本不是完整市場驗收。
2. **模型：** 真實 HTTP／provider 與付費使用尚未核準／驗證；离線 transport 測試不能代替真服務穩定性。
3. **目標環境：** Windows 原生性能、時區、檔案鎖定及 UI 操作仍需實測；Linux 結果只能限定使用。
4. **發布：** 最終版本、乾淨安裝、遠端 CI 與授權發布需完成後才宣稱交付，不以「已開始」當成功。
5. **正式金融整合：** 台新／兆豐適用 API、帳戶資格、行情權利、憑證、故障查詢與限流需正式確認；真實交易固定停用。

接續順序是完成 Phase 3 的安全研究與來源標示、Phase 4 的可追溯 UI／registry、Phase 5 的故障恢復與最終驗收。不能為了報告 100% 把尚未驗證的外部整合加上 Mock 後視作通過。最終交付需同時清楚列出：工程完成百分比、未通過條款、真模型／市場績效／broker／實盤 readiness，以及使用者仍需決定或操作的事項。

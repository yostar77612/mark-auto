# M3 自主決策紀錄

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

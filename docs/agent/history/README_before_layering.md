# README before documentation layering

Origin: README.md working tree after T12 parts A/B; 2026-10-19.
The following literal block preserves the complete original text; historical links are not current instructions.

~~~~~markdown
# mark-auto 台股期貨研究平台

本專案新增獨立的 `quantlab` 離線研究核心與 `research_app.py` 操作介面。研究、模擬與正式券商交易分離；**真實交易固定停用**。原 AutoTradingPlatform 程式保留為來源與後續 Adapter 參考，其舊入口已停用。這不是獲利保證，也不是已驗證的實盤系統。

## Windows 桌面版（必要產品交付，驗收中）

原生 PySide6／Qt 桌面入口為 `desktop.py`，沿用同一個 `quantlab` 核心，不需要另啟 Web 服務。桌面安裝程式建置流程在 [packaging/README.md](packaging/README.md)。可下載安裝檔以 [GitHub Releases](https://github.com/yostar77612/mark-auto/releases) 實際發布的資產為準；沒有資產時不可把原始碼當安裝版。預覽版不代表 Windows 10／11 最終驗收已通過。

**已核驗的修補前基線下載：** [0.2.2 unsigned preview](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38096213180-1) 的實際 installer／kit／manifest 已下載校驗。後續候選或原始碼版本不是已發布安裝檔，只有發布與資產核對完成後才更新此入口。乾淨 Win10／Win11 仍為 EXTERNAL_BLOCKED；main 分支保護未啟用，管理 API 403 限制未解除。未簽章不繞過 Windows 安全警告，真實 ChatGPT 授權／推論仍未驗證，實盤固定停用。

### 一般使用者操作

1. 下載對應版本的 Windows x64 setup EXE，先核對同版 SHA256SUMS 與發布限制。
2. 安裝至個人程式目錄；安裝器建立桌面／開始功能表捷徑。一般使用者不需要 Python、pip、Git。
3. 雙擊 MarkAuto，先看資料、模型及風控狀態。初次使用可建立明確標示的合成範例，熟悉操作，不能把其績效當真實投資結果。
4. 在「資料匯入與更新」取得免費官方近期檔案，選擇明確契約／時段與已查核行情。下載成功不等於歷史完整或可正式排名。
5. 在策略、回測及比較頁設定版本、日期與成本／風控，查看資金曲線及成交，匯出報告。研究候選沒過門檻時可全部淘汰。
6. 0.2.2 預覽版的 AI 主路線為官方 ChatGPT 訂閱登入，不需 API Key 或本地模型。首次由本人在官方頁面授權；研究前確認僅使用方案內額度及本次請求上限。離線示範明確標為 Fixture，不冒充真實 AI。登入介面與離線測試不代表真實帳戶授權及訂閱推論已通過驗收。
7. Paper 重啟、睡眠或異常後需明確對帳。未知狀態不會自動补單；緊急停止會凍結新工作，不假裝已成交／平倉。實盤在本版固定停用。
8. 關閉時處理尚在執行的工作。下一次開啟保留設定與資料；更新前先備份，關閉舊程式後安裝新版本。

程式安裝在 `%LOCALAPPDATA%\Programs\MarkAuto`；使用者資料在 `%LOCALAPPDATA%\MarkAuto`，不得混用 Program Files。Windows「設定 → 應用程式」可解除安裝；預設保留資料，避免誤刪歷史。備份／還原排除機密及不可回退的研究控制帳本、檢查版本與hash，還原前停止工作；遇版本不相容不覆寫原資料，可回裝相容舊版並還原已驗證備份。

安裝器尚無正式程式碼簽章；若 Windows 顯示安全警告，不應停用或繞過安全機制。乾淨 Windows10 22H2 x64／Windows11 x64實測、標準使用者權限與長時間運作仍需獨立證據；Windows Server CI 不等同 client OS 測試。所有最新狀態以 [固定驗收](docs/agent/ACCEPTANCE.json) 為準。

### 0.2.2 預覽版：Walk-forward、績效與圖表參考

以下功能已整合至上述核驗的 0.2.2 預覽版，具備離線功能、Windows Server CI 與發布品核對證據；乾淨 Windows 10／11 與真實 ChatGPT 訂閱推論仍待驗收。一般操作不需手寫 JSON，完整來源及設定可展開「進階」查看。

#### 固定候選池 Walk-forward

1. 在「資料匯入與更新」建立合成示範，或匯入已驗證的研究資料。唯讀市場快取不等於研究 dataset。先到「回測與結果」核對費用、資金、保證金及實際合約到期日；WFO 共用這些設定，但**以完整來源列索引切分，不套用回測頁的日期篩選**。
2. 在「AI 策略中心」的「固定候選池 Walk-forward（技術驗證）」選一種候選池：
   - 「五個精確內建規格（預設）」：固定五份內建規格，不採用上方任意編輯的策略參數。
   - 「已保存 AI 研究的固定候選池」：明確選取「唯一來源研究」，再用「選取本機原始資料檔」提供該研究當時的**完整原始資料**。來源紀錄、版本、候選與既有控制帳本必須一致；原來源所有事件須嚴格早於本次首折訓練。不接受任意候選 JSON；不支援的手動來源／版本會拒絕，不另造帳本繞過。來源模型的「尚未驗證」狀態不會升級。
3. 選「固定寬度」或「固定起點」窗口，填入 2–20 折、訓練／驗證／前推寬度、步進、間隙與排除的最終保留集。索引自 0 起、起點含而終點不含；保留集終點須等於完整資料根數。預設「僅合成驗證」拒絕真實／代理來源；使用合格歷史來源時須自行選「歷史重播，資料暴露未驗證」。
4. 按「預覽精確切分、風險門檻與一次性額度」，逐折核對索引／時間、全部固定候選、費用與三項驗證門檻。預設門檻為淨損益至少 0 TWD、至少 1 個已平倉 lot、最大回撤 10%；這是工程護欄。完整計畫最多「折數 ×（2 × 候選數＋1）」次評估，內建池最多 220 次、最多 15 個候選的保存池最多 620 次，總時間 1–7200 秒。額度含失敗／中斷，不自動增加；若預覽要求調整，自行修改後重新預覽。預覽本身不消耗新範圍，開始時仍會重查來源與既有消耗紀錄；改資料或設定會使預覽及同意失效。
5. 確認所有計畫前推 OOS 範圍將在評分前**一次不可逆消耗**後，勾選同意，再按「執行／讀取同一計畫（不重試 OOS）」。取消、失敗、逾時或中斷均不退還已用範圍／額度，不會暗中重試；停止須等背景程序真正結束。最終保留集僅排除、不評估，不能據此宣稱從未被人或模型接觸。
6. 逐折查看候選的訓練／驗證淨損益、已平倉 lot 與回撤，以及贏家的前推結果。訓練僅描述；通過驗證門檻後依驗證淨損益選單一贏家，再凍結評估 OOS，OOS 不回饋改善。沒有候選通過可以沒有贏家。用「唯讀重開已保存 Walk-forward 結果」查舊結果，不會重跑 OOS。

兩種候選池都不發起新模型呼叫；已保存池不是逐折重新生成／改善策略。此功能**不產生正式策略排名或 Paper 資格**；歷史重播仍是資料暴露未驗證、非獨立 OOS。既有 Oct8 真實資料 protocol 因完整保護範圍重疊已消耗的 170 bars，保持 `BLOCKED_NO_RUN`，沒有新回測、模型呼叫或 reservation。不要改窗口、搬工作區、刪除或替換控制帳本來規避拒絕。

#### 回測結果：PF 與描述性 Sharpe

在「回測與結果」選取已保存結果，先看「獲利因子」「夏普值（描述性）」、觀測期數、有效報酬期數及未定義原因。已有欄位但無法計算時顯示「未定義」；舊結果根本沒有該欄位時顯示「未提供」，兩者都不是 0。年化假設與短樣本限制須一併閱讀；完整紀錄／識別碼留在「進階診斷 JSON（一般操作不需要）」。新指標不改變成交、候選選擇或 Paper 資格。

- **獲利因子（Profit Factor／PF）**：已平倉 FIFO 配對 lot 的正淨損益合計／負淨損益絕對合計，已含分攤的進出場費用，不含未平倉損益。沒有已平倉 lot，或沒有虧損 lot 時顯示不可計算及原因，不以無限大排名；全部虧損可為 0。
- **夏普值（描述性 Sharpe）**：依每個已提供交易日的最後 equity 計算報酬，首筆相對初始資金；假設每年 252 期、無風險率 0、樣本標準差。少於兩筆報酬、零變異、缺漏／非有限／非正 equity 時保留不可計算原因，不刪壞資料換數字。缺日期不插補，跨缺口報酬可能橫跨多日；兩筆只是數學最低要求，短樣本及 252 期假設都不構成可靠性或獲利證明。

#### 市場圖表：期末持倉與保護參考

在「回測與結果」選好結果，再到「市場總覽」選同一研究資料對應的實際合約。來源／完整資料身分、策略、成交與剩餘部位須全數核對；只有圖表末端時間能精確對應結果最後事件時，才會自動顯示最多六個「期末快照」參考點：成交均價（未含費用）、MTM 基準（非保證金），以及策略已有的停損／停利門檻或上下緣。

這些是實際回測剩餘部位的期末快照，**不是掛單、真實持倉或歷史保護線路徑**。保護門檻沿用多批次觸發時取不利值、全倉退出及跳空規則，不用平均成本猜測成交。平倉、舊結果缺證據、來源不符或聚合 K 線末端不相符時可以不顯示；移到較早的圖表視窗時會隱藏快照，避免把期末資訊畫回過去。訊號／成交圖層仍可各自切換，不影響上述核對。

## 開發者／研究入口

## 快速開始

需求：Python 3.11 以上。離線核心使用標準函式庫；Windows 可安裝 `tzdata` 以載入時區資料。

```bash
python -m unittest discover -s tests -v
python -m quantlab demo --output ./quantlab-output/demo
```

`demo` 僅產生明確標示的 SYNTHETIC 行情，執行五種不同策略並匯出結果。不能把展示損益當作真實市場績效。

### 本機研究介面

使用獨立虛擬環境，不安裝舊券商套件清單：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-ui.lock
streamlit run research_app.py --server.address 127.0.0.1
```

介面提供本機資料匯入與品質檢查、五種策略、回測與報表、研究試驗、策略比較／選擇、Paper 帳本與歷史行情重播。不要公開暴露此本機檔案操作介面；本版本沒有多使用者身分驗證。

### 明確資料與成本

```bash
python -m quantlab import examples/synthetic_bars.csv --kind synthetic_bars --calendar examples/synthetic_calendar.json --output ./quantlab-output/dataset.json
python -m quantlab backtest ./quantlab-output/dataset.json --config examples/synthetic_config.json --output ./quantlab-output/reports
python -m quantlab campaign ./quantlab-output/dataset.json --output ./quantlab-output/campaign
```

`examples` 的時段、價格、保證金與成本均為測試假設。正式研究需換成已查核的資料、有效日期化成本／保證金與交易所日曆。官方格式僅支援實際觀察並測試的欄位；未知格式、未覆蓋日期或缺漏資料須拒絕，不能猜測補值。付費行情與帳戶資訊不得提交 Git。

### 官方免費資料更新

```bash
python -m quantlab refresh --cache ./quantlab-output/official --days 1 --format csv
```

僅從期交所已公布連結取得最近最多 30 個交易日期的 CSV／RPT ZIP。更新保留 SHA 版本、檢查 TLS、大小與解壓安全，不把重複下載當作新資料。下載結果先標為 provisional_unverified／ranking_eligible=false；夜盤檔案日期可能屬下一交易日，必須經明確交易日曆及匯入品質驗證才能研究。資料不足時不產生正式策略排名。原始行情與快取不得提交 Git。

## 重要安全與驗證界線

- `quantlab` 不匯入 `archives/legacy_autotrading/trader/` 或券商 SDK，匯入本身不連線或建立帳戶。
- 舊 `archives/legacy_autotrading/run.py`、`archives/legacy_autotrading/gui.py`、`archives/legacy_autotrading/trader/` 啟動、pickle／Redis反序列化及舊下載流程刻意停用；不應嘗試用憑證啟動。
- Paper 使用可稽核 SQLite 事件帳本；重啟／未知委託先凍結新單，完整對帳後才可恢复。停止不會偷偷平倉。
- 預設策略研究使用明確標示的 fixture generator；它驗證工程流程，**不代表真實模型已完成驗證**。選用 HTTP 相容模型時必須明確開啟、提供端點及預算；本次未呼叫外部付費模型。
- 五種策略家族為趨勢、均值回歸、通道突破、動能與波動壓縮突破。參數、資料及成本版本綁定每個結果；通過工程測試不代表策略通過投資績效門檻。
- 回測提供下一根開盤成交、成本、保證金、雙邊換月及顯式結算事件；OHLC不能證明真實排隊／流動性。缺少必要換月或结算輸入時失敗封鎖。
- Paper 重播是有限批次歷史事件處理，沒有實際即時行情；尚未支援的盤中停損／停利規則會拒絕，不會默默忽略。
- 遠端 Windows/CI、實際模型、券商認證、完整歷史日曆及長時間真實運行狀態請看接續文件，不得由 Linux 合成測試推論通過。

## 文件與開發接續

- [目前狀態及下一步](docs/agent/PROJECT_STATE.md)
- [固定驗收清單](docs/agent/ACCEPTANCE.json)
- [介面合約及工作責任](docs/agent/IMPLEMENTATION_CONTRACTS.md)
- [專案架構](docs/analysis/01_PROJECT_ARCHITECTURE.md)
- [既有功能盤點](docs/analysis/02_EXISTING_FEATURES.md)
- [程式品質與風險](docs/analysis/03_CODE_QUALITY_AND_RISKS.md)
- [AI量化目標設計](docs/analysis/04_AI_QUANT_TARGET_DESIGN.md)
- [MVP與開發Roadmap](docs/analysis/05_IMPLEMENTATION_ROADMAP.md)

For the current MarkAuto desktop application, use the hashed
[`requirements-desktop.lock`](requirements-desktop.lock) and the pinned Python/SQLite
installation and build procedure in [`packaging/build.ps1`](packaging/build.ps1).
See also the [desktop installation guide](packaging/README.md) and
[`packaging/clean_windows_README.md`](packaging/clean_windows_README.md).

## Provenance

MarkAuto derives from Li Kuei-Wei's Apache-2.0 AutoTradingPlatform. Disabled upstream code, provenance and copyright details are preserved in the [legacy archive](archives/legacy_autotrading/); the product never imports or bundles this code.

## 0.1.2 接續驗收更新

- 新版使用完整版本化payload，校驗全部檔案後才更新捷徑，避免新舊DLL混合；異常更新可保留舊版並重跑安裝，詳見 `packaging/update_recovery.md`。保留/中斷payload會占用磁碟，不自動刪除任意資料。
- 備份必須存於工作區與固定MarkAuto應用資料夾之外，避免覆寫機密、帳本、鎖定與不可回退研究控制。
- 模型設定新增『JSON Schema：內建家族參數生成』。服务须支援該協定，不支援直接失敗，不偷偷改用fixture。預設相容模式與既有budget綁定保留。
- 已完成官方免費模型與真實12日行情的有限技術整合：一個策略虧損，兩個零交易，沒有可宣稱正式晉級的策略。完整失敗/限制列於 `docs/analysis/03_CODE_QUALITY_AND_RISKS.md`。
- Windows Release附無Python/Git需求的clean-client验收kit；詳見 `packaging/clean_windows_README.md`。無已授權乾淨Win10/11環境時依然EXTERNAL BLOCKED。
- 最新可下載版本以GitHub Release的實際資產與SHA256為準；此原始碼分支的變更不代表新安裝檔已發布。實盤繼續停用。

## 0.2.0 市場優先桌面（歷史紀錄，AI 選項已由下節取代）

沿用原生Windows桌面及既有TMF研究核心，增加加權指數/TX/MXF(MTX)/TMF真實日行情、本機歷史與明確時效、自選/蠟燭/成交量/多週期/技術指標、可讀表單與交易紀錄。一般模式不必手寫JSON；來源與hash保留在進階診斷。

- 官方更新需要使用者明確同意本次連線，離線可匯入官方格式檔；本機檔來源未經連線核實會標示，沒有假即時價。
- 新行情商品不代表已支援該商品下單/回測；研究交易核心仍限定TMF，實單停用。
- ChatGPT手動交換可匯出研究要求及匯入受限策略；來源記為manual_unverified，不冒充API實測。相容本機模型與付費API設定維持明確同意/預算/安全儲存，付費預設關閉。官方訂閱登入另行驗證，不複製Cookie或其他工具憑證。
- 新版需通過Windows打包與全部既有安全回歸才發布；clean Win10/11仍須獨立環境。

### ChatGPT 訂閱 AI（0.2.2 已發布介面，真實授權驗收中）

本節依 2026-10-10 11:16 UTC 的正式需求修正，取代前述舊版本的相容端點、本地模型及付費 API 選項。歷史測試與版本紀錄保留，不算作 ChatGPT 真實推論證據。

- AI 主要入口為官方 **Sign in with ChatGPT**。不下載 Qwen、Ollama、GGUF 或本地推論引擎，不提供自動付費 API／Credits fallback。
- 身分登入與訂閱用量授權分開；必須取得所需權限及官方實際可用模型，才可開始明確核准的研究。Windows 使用系統保護儲存憑證；不把 Token 寫入一般設定、日誌、備份或安裝檔。
- 官方帳戶可另外允許 App 使用 Credits。本程式不開啟該選項、不購買 Credits，也沒有已公開的介面可讀取或強制設定此帳戶政策。每次研究前須確認已停用 App Credits，或 MarkAuto 的 App 用量上限低於 100%；未確認即停止。這是使用者確認，不是伺服器政策驗證或金額上限保證。詳見 [官方用量設定說明](https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites)。
- 研究只傳送明示的策略及訓練／驗證資料，不讓 AI 控制下單或風控。策略需通過獨立回測；額度不足、授權失效、未知請求結果均停止，不無限重試或重設已用額度。
- 舊模型快取、設定與歷史研究不會在升級時任意刪除。0.2.2 不再載入或啟動本地模型；舊候選操作說明可查 Git 歷史。

官方流程參考 [OpenAI SIWC quickstart](https://developers.openai.com/siwc/quickstart)。實際帳戶授權／完整訂閱回應、乾淨 Windows 10／11 安裝操作仍須各自驗證；離線 OAuth 或 parser 測試不能取代。最新驗收及尚缺的 AI 分析功能以 [Roadmap](docs/analysis/05_IMPLEMENTATION_ROADMAP.md) 與固定驗收表為準。

~~~~~

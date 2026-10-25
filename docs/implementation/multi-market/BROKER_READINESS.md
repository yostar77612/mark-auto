# 永豐連接器接入與驗證紀錄

2026-10-25。本文件區分本機故障替身、真 SDK 型別檢查與券商實際連線。
本次沒有建立真實 SDK client、登入、讀取真憑證或操作真實委託；Sitecore 不在範圍內。

## 本次可執行內容

`quantlab/trading/ports` 定義連線、能力、商品、行情、帳務、交割、部位、委託與事件
的 Protocol 及不可變 DTO。共用領域只接收 Decimal、明確股／口單位和帶時區時間。
SDK 物件、浮點數、未遮蔽帳號和金鑰留在 `adapters/shioaji` 內；交易帳戶必須明確指定，
不採 SDK 預設帳戶。`ShioajiAdapter` 預設 disconnected、read_only、execution disabled。
正式與券商模擬是不同 Environment，不能當成本機模擬使用。

本機 `SimulatedBroker` 有獨立 remote state，可在應用程序重啟後補查。FaultPlan 可注入
拒單、送出前斷線、已收單但確認遺失、部分成交、重複／遺漏／亂序回報和取消成交競態；
`external_position` 模擬手機／外部持倉。這些行為沒有網路或 SDK 呼叫。成交不得超過限價；
費用預設使用同一 Domain FeeSchedule 的累計委託成本差額（本機每筆委託最低費假設），
remote state 保存已收費用；部分成交不重複收最低費。也可明確傳入已核算費用。股票同日新買在無當沖
資格時可退出量為零；交易日推進需明確日期。賣款先列未交割應收，只有使用明確交割日
排程並到期後才轉可用現金。替身沒有自行推算休市日或把當沖政策當成資格。

## SDK 鎖定與實際檢查

唯一正式選用 SDK 匯入位於
`quantlab/trading/adapters/shioaji/sdk_loader.py` 的 `load_pinned_sdk()`；函數內
明示 `import shioaji` 並核對精確版本，沒有隱藏動態載入。匯入 loader 模組本身
不匯入 SDK、不建立 client。只有明確 read-only 連線流程才呼叫此函數；設定檢查、
UI 啟動及 LOCAL 模擬不呼叫。這是 v2 的極窄工程契約，既有研究禁令與 v1 實盤
永久停用防護不變；缺少 SDK 或版本不符時會明確拒絕，不自動安裝或換用其他版本。

鎖定 Shioaji **1.7.9**。官方 Windows CPython abi3 wheel：

`shioaji-1.7.9-cp37-abi3-win_amd64.whl`

SHA256：`77c864aa5bcd0f873746cb10a55a484c7a38723df432a7778f328d5fb7f57be4`。

`requirements-shioaji-v2.lock` 為獨立、可重現的 Windows 選用 runtime lock，未加入 v1
研究或預設安裝依賴。官方套件 metadata 沒有必要 runtime dependencies；speed/test extras
未安裝。官方 wheel 已下載至工作區外層隔離稽核資料夾，逐位元核對 SHA256 後解壓。
在 Python 3.13.11 實際 import 該 wheel，使用合成帳號物件構造三市場各一進一出的六個
真 SDK Order，確認股轉張、Cash/Common、不使用 daytrade_short、期貨 New/Cover、明確帳戶；
另外核對 19 個 SDK 方法存在。**沒有建立 Shioaji client，也沒有執行 login、CA、送單、改單或撤單。**

原始證據位於工作區外層 `multi-market-audit-20261025/sdk/`：

- `pypi-1.7.9.json`：官方版本、wheel URL、digest 與依賴 metadata。
- `contract-no-login.json`：真 SDK 版本、六個模型案例、方法清單與未呼叫的操作。
- `verify_sdk_no_login.py`：可重做的純型別構造檢查。
- 官方 wheel 與 `site/`：只有隔離解壓，未修改既有 Python 環境。

這項檢查只證明 SDK 型別與轉換可運作，不能取代帳戶、行情、回報及實際券商驗證。
一般離線回歸：`python -m unittest discover -s tests -p test_trading_adapters.py -v`。
該測試使用明確 SDK 形狀的故障替身，不能宣稱券商模擬通過。

## 映射與保守缺口

| 項目 | 本機實作及限制 |
|---|---|
| 股票數量 | Domain 使用股；Common 除以 1000 後進 SDK；零股獨立資格且使用 IntradayOdd，不用於繞過當沖限制。 |
| 期貨數量與月份 | Domain 使用口；明確 sdk_code 綁定實際月份；拒 R1/R2，核對 info 的月份、到期日、乘數與 tick。 |
| 倉別 | 新增曝險 New，減倉 Cover；不從 INTRADAY 推導 DayTrade 或減收保證金。 |
| 金額 | SDK 原生數字只在 adapter 以 Decimal(str(value)) 正規化；輸入價格轉 SDK float 前須能十進位往返一致。 |
| 帳務 | 股票查 bank balance、trading_available、settlements、持倉與新鮮估值；期貨以 today_balance、equity、initial_margin、available_margin 分列，避免把可用保證金當總現金再重複扣除。 |
| 股票可退出量 | SDK yd_quantity 不能單獨證明未被保留／質押；缺少可靠可賣證據時回傳 0，UI 必須清楚顯示待核對，不能假設新買可賣。 |
| 來源日曆 | latest 行情必須注入 TradeDateResolver 的已驗證交易日／時段；沒有映射就拒絕，夜盤不使用機器日期推算。 |
| 歷史資料 | kbars 每批最多 30 日，欄長一致且最多 50,000 筆；以資料發布時間作 available_at，不能用完整棒在同棒開盤成交。空回應明確 no_data。完整性仍需 Domain 日曆與來源品質檢查。 |
| 委託 | 明確單一帳戶；本機命令不盲目重送。已收單逾時維持 UNKNOWN；未能唯一綁定的遠端單隔離並待接管。 |
| 回報與對帳 | update_status 明確帳戶；list_trades 雖跨帳戶，正規化前逐項帳戶過濾；累計成交倒退、未知狀態、未接管外部單都拒絕清除。 |
| 取消／改量 | API 命令回傳不等同交易所完成；取消先 CANCEL_PENDING，改量只准減量且不得低於已成交量。 |
| CA 與交易資格 | API 登入、signed、CA、market、day_trade、odd_lot、can_trade、時間有效性各自檢查；CA activation 回傳不會自動改能力證據。 |
| 密鑰引用 | WindowsSecretResolver 只讀明確 `MarkAuto/v2/broker/<alias>` 或 `MarkAuto/v2/certificate/<alias>` Credential Manager reference，不列舉、不讀 .env、不搜尋憑證；測試只用注入 backend。 |

## 權限開通後的具體步驟

### 已完成的設定與本機檢查入口

六工作區「設定」中的連接器設定使用 `BrokerSettings`，只保存環境、帳戶別名及文件／密鑰
引用，進階欄位預設收合。非空 credential reference 必須符合上述命名空間，文件引用必須為
絕對路徑；誤貼實際密鑰會在建立 DTO 時拒絕，不能先寫入再提示錯誤。儲存與檢查經共用
Application use case 寫入原 v2 journal；重啟仍能回讀，不改 v1 研究資料。

「檢查設定就緒」只針對明確提供的本機文件做規則版本、大小及 SHA256 檢查，不列舉目錄、
讀 Credential Manager、初始化 SDK、登入或呼叫券商。JSON 參照須有整數 `schema_version: 2`；
重複鍵、NaN、超過 1 MiB、不存在／重解析點／網路 UNC 路徑都不通過。通過的檔案 SHA256
與版本保存在 BrokerReadiness.references，可供後續接入核對。這些只代表**本機設定文件齊備**，
不把文件存在當成其內容已經過券商證實；帳戶、交易資格、CA 與券商模擬驗證各自保持待外部驗證。

`runtime.broker.build_broker_runtime` 接受明確 SDK factory、帳戶物件對應、商品／能力 DTO、
資金配置及注入時鐘，構造與共用引擎相同 AccountGateway 的 ShioajiAdapter；建構後維持
disconnected/read_only/execution disabled。只有另行明確呼叫 `connect_read_only` 才會讀指定
credential reference 並登入。本次純型別測試沒有呼叫真實 client constructor 或連線。

已以嚴格 SDK 形狀替身測試這個 factory 及同一 TradingEngine 的只查對帳路徑、錯誤與交易拒絕，
也驗證設定儲存、metadata 檢查及重啟回讀。SDK module 由明確呼叫端注入，研究核心不隱藏第三方
import；版本與 QuoteVersion.v1 enum 映射也已用官方 wheel 的實際型別核對。

### 新增的標準啟動與環境切換

**包裝差異：預設離線安裝包刻意排除 Shioaji。** 在其他 venv 安裝 SDK 不會讓已凍結的
EXE 使用它。需要含 SDK 的同引擎版本時，使用獨立、明確 opt-in 的本機 broker-enabled
portable 建置；操作契約與兩階段命令見 `packaging/BROKER_BUILD.md`。
依賴準備或來源版 import 不代表 frozen 包已驗收；必須保存該候選 EXE 的
`--broker-sdk-probe` 真載入證據。兩種包都不會因啟動而建構券商 client 或登入。

以下是來源版 CLI。凍結版本以 `MarkAuto.exe` 取代 `python -X utf8 desktop.py`，旗標相同。
路徑是明確選擇的 **v2 隔離目錄**，不使用原 v1 workspace 或 Sitecore 目錄。

```powershell
python -X utf8 desktop.py --platform-v2 --trading-root "C:\MarkAutoExample\local"
```

尚未配置券商資源時也可明確開啟待設定環境；`pending-stock` 只是本機選取用別名，
不是已確認帳戶或資格。此時沒有商品日曆、資產或持倉的替代假資料：

```powershell
python -X utf8 desktop.py --platform-v2 --trading-root "C:\MarkAutoExample\broker" --trading-environment LIVE --trading-account pending-stock
```

已有有效 profile 時：

```powershell
python -X utf8 desktop.py --platform-v2 --trading-root "C:\MarkAutoExample\broker" --trading-environment BROKER_SIMULATION --trading-account user-stock --trading-profile "C:\MarkAutoExample\bundle\profile.json"
```

`--trading-environment` 只接受 `LOCAL`、`BROKER_SIMULATION`、`LIVE`。非 LOCAL 必須提供
明確帳戶別名；有 profile 時必須在其 stock/futures 映射中。`--trading-engine <絕對路徑>`
是相同協議的無介面 host 入口，仍需明示 environment/account/profile，不會暗中切回 LOCAL。

UI 設定頁可登錄 profile、選取環境與帳戶。登錄清單也可由
`--trading-contexts "C:\MarkAutoExample\contexts-v2.json"` 指定，格式固定為：

```json
{
  "schema_version": 1,
  "selected_context": "paper",
  "selected_account": "local-stock",
  "contexts": [
    {"context_id":"paper","label":"本機模擬","root":"C:/MarkAutoExample/local","environment":"LOCAL","account_ref":"local-stock","profile_path":null},
    {"context_id":"broker-query","label":"券商模擬待連線","root":"C:/MarkAutoExample/broker-query","environment":"BROKER_SIMULATION","account_ref":"user-stock","profile_path":"C:/MarkAutoExample/bundle/profile.json"}
  ]
}
```

每個 context 使用不同 engine root；同一 host 內證券、期貨仍共用總預算與持倉帳本。
切帳戶是顯示投影，不能把策略、持倉或委託移到另一帳戶。客戶端固定驗證環境、別名與
profile SHA256，設定不符時保留目前 context 並拒絕，不附掛另一環境，也不覆蓋仍在執行的 host。

### Profile 與資源文件格式

`runtime/config.py` 的 `RuntimeLaunch` 是版本 1 的 typed 入口：
`root / environment / profile_path / account_ref / schema_version`。
`load_profile` 與 `load_resources` 不建構 SDK、不讀 Credential Manager、不呼叫網路。

Profile 的欄位必須完整且不得增加未知欄位：

```json
{
  "schema_version": 1,
  "profile_alias": "sinopac",
  "environment": "BROKER_SIMULATION",
  "stock_account_ref": "user-stock",
  "futures_account_ref": "",
  "stock_allocation": "100000",
  "futures_allocation": "0",
  "settings_payload": "<codec.dumps(BrokerSettings) 產生的字串>",
  "resources": [
    {"kind":"catalog","path":"C:/MarkAutoExample/bundle/catalog.json","sha256":"<該文件完整64字元SHA256>"},
    {"kind":"calendar","path":"C:/MarkAutoExample/bundle/calendar.json","sha256":"<SHA256>"},
    {"kind":"fees","path":"C:/MarkAutoExample/bundle/fees.json","sha256":"<SHA256>"},
    {"kind":"accounts","path":"C:/MarkAutoExample/bundle/accounts.json","sha256":"<SHA256>"},
    {"kind":"capabilities","path":"C:/MarkAutoExample/bundle/capabilities.json","sha256":"<SHA256>"}
  ]
}
```

這是欄位示意，含佔位字串，**不是可用券商證據或可直接連線的範例帳戶**。
金額使用十進位字串；兩帳戶配置合計不可超過 100,000 元，未配置的帳戶額度必須為零。
這是計畫預算，不能當成已查證餘額。`BrokerSettings` 的環境、別名、readonly 旗標與五個
文件引用必須和 profile 完全一致；禁止 read_only=False 或 execution_enabled=True。

每份資源使用以下 envelope；`payload` 也是共用 codec 的 JSON **字串**，不能填 Python
repr、可執行程式碼或任意 SDK 物件：

```json
{"schema_version":2,"kind":"calendar","payload":"<codec.dumps(TradingCalendar) 產生的字串>"}
```

| kind | payload 的明確型別與來源要求 |
|---|---|
| catalog | `tuple[InstrumentMapping(spec: InstrumentSpec, sdk_code: str, stock_grid: StockGridEvidence\|None), ...]`；明確真月份代碼、規格版本與來源，不從顯示名稱猜合約，拒 R1/R2。`spec.calendar_id` 必須等於指定日曆。價格帶由完整 `PriceBand` DTO 保留，不挑掉欄位。券商股票需明確 stock_grid，不能用 None 或舊 scalar tick 通過。 |
| calendar | `TradingCalendar`；由有來源的交易日與日夜盤區間建立，不能使用本機模擬日曆或由星期推定官方休市。 |
| fees | `FeeSchedule`；版本化的費稅、最低費與滑價設定，共用 Domain 權威，不能把本機範例費率宣稱為券商實際費率。 |
| accounts | `tuple[AccountMapping(account_ref, sdk_account_id, kind), ...]`；kind 僅 `STOCK` 或 `FUTURES`，每個配置帳戶恰有一項；SDK ID 只在本機對應文件內。 |
| capabilities | `tuple[CapabilitySnapshot, ...]`；每個配置帳戶的市場、環境、證據來源、檢查及失效時間；文件存在不代表資格已獲券商證實。 |
| history（選用） | `tuple[(instrument_id, tuple[CompletedBar, ...]), ...]`；每商品最多 10,000 根，保留發佈時間及來源，不能填當棒未完成資料。 |

Typed 資源應由整合程式呼叫 `application.codec.dumps` 產生；`tests/test_trading_runtime_context.py`
的 builder 只示範**合成替身**格式，不得複用其中日曆、帳號、行情或資格作真證據。
所有引用都是 profile 同一 bundle 範圍內的絕對本機路徑；拒 UNC、重解析點、重複 JSON 鍵、
NaN、未知欄位、錯誤版本及 hash 改變。runtime 每份文件最多 4 MiB；既有 metadata 就緒檢查
仍維持 1 MiB 門檻，沒有為新功能放寬。變更 profile 必須明確重新登錄並重啟其隔離 host，
不能在持倉時暗中更換規格或身分。

股票 `StockGridEvidence` 包含 `sdk_code / exchange / product_class / isin / cfi_code /
source_uri / source_version / source_sha256 / as_of`。目前明確支援來源核對的普通股與一般
TWD ETF 分類，使用 `stock_grid.py` 的完整交易所價格帶與版本，不由商品代碼前綴或 SDK
產業分類猜測。分類快照需在七日內，來源為明確 TWSE/TPEX ISIN 公開表；缺失、未來日期、
不明分類或不完整價格帶，會在建立 SDK client 或讀 secret 前拒絕。參考
[上市 ISIN 表](https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2)、
[上櫃 ISIN 表](https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=4)。
本機 SDK 形狀測試明示使用合成來源雜湊，不能當成已下載並驗證的真實分類快照。

### 只讀連線與 host 復原行為

啟動、開設定頁、登錄 profile、檢查就緒都只進入 durable `ReadinessSession`；
金融事實保持未知，沒有假日曆、假權限或「資產／持倉為零」的宣稱。
`CONNECT_READ_ONLY` 是獨立明確操作：只有此入口才可載入選用 SDK、讀指定 secret reference、
登入、核對登入回報的帳戶 ID／種類、核對完整合約規格及組裝共用 `TradingEngine`。
它保持 read_only、兩個執行旗標關閉，沒有 CA 啟用，也不送單、改單、撤單或平倉。

連線在獨立 owned worker 執行，立即回報 `connection_pending`，不把開始連線當成成功。
8 秒內未確認、停止或關閉引擎會使該 attempt 失效；晚到結果只清理自己的候選資源，
不能回頭取代目前 context。SDK 的 login、contracts lazy lookup、logout 沒有官方 timeout
參數，因此不能宣稱同步 API 可被硬取消。支援 timeout 的 query 預設 2,500 ms，可注入；
只讀 host 的 control、decision、query worker 分開，query 不持有核心 writer lock。
查詢錯誤保留未知並退避；一般帳戶更新至少間隔 5 秒、行情請求至少 1 秒，rate-limit
至少退避 30 秒，並保留來源時點檢查，不能以新收到時間替舊資料續期。

非 LOCAL 公開版本在獨立 `runtime-control-v2.sqlite` 先保存高水位，再回應給客戶端。
promotion、重啟不重用先前已公開版本；舊排隊命令會拒絕。control stamp 故障會明示未確認、
停止新曝險並拒新命令；健康的交易 journal 不會被假標成損壞而阻斷獨立保護處理。
原 LOCAL 的明確 STEP、v1 永久停用防護與既有研究/OOS 儲存均保持獨立。

本輪已實際通過新 runtime/context/cache/broker **25 項**、既有 broker/runtime **23 項**、
control-stamp 故障後重啟擴充案例與自動分層檢查。測試使用 Python 3.13.16、SQLite 3.54.0、
一般使用者 token（admin=False），含真獨立程序與 HMAC IPC、合成 SDK 形狀故障替身；
**不是券商測試**。記錄在工作區 `t/runtime-context-functional-final.log`、
`t/runtime-broker-legacy-functional.log`、`t/runtime-context-stamp-restart.log`、
`t/runtime-context-architecture.log`。獨立審查新增的來源時點補強已完成：快取發布前與每個
讀取入口都共用 `validate_account_observation`，同時核對 envelope 與 nested account 的
as_of；新 received/observed 時間不能替舊來源續期。舊 nested account、新外殼／舊內容、
任一未來時間、重複舊快照及 naive clock 的 **9 項 cache suite** 通過；修補前五個失敗與
一個未分類例外的紅燈紀錄保留在 `t/runtime-cache-freshness-red.log`，綠燈在
`t/runtime-cache-freshness-green.log`。最後跨模組全回歸仍以整合驗收紀錄為準。

### 外部接入順序

1. 來源版可在隔離 broker runtime 用 hash lock 安裝 1.7.9；凍結版須選擇由同一份來源產生、
   明確含 SDK 的 broker-enabled portable，而非期待另一個 venv 改變既有 EXE。
   SDK 升版另做完整回歸，不能在持倉時自動切換。先正常關閉舊 host，再開新包和既有 v2
   隔離目錄；不搬移 v1 原資料，不自動偷換仍在執行的程序。
2. 使用 Windows Credential Manager 的 Generic Credential 手動保存本機提供的 API credential；target
   `MarkAuto/v2/broker/<alias>`，密碼內容為 JSON 的 api_key、secret_key 兩欄。
   Windows UI 儲存的 UTF-16LE 與明確 API enrollment 的 UTF-8 皆有嚴格解析。
   憑證則使用另一個 `MarkAuto/v2/certificate/<alias>`，欄位 ca_path、ca_password、person_id；
   憑證檔留在一般研究／備份目錄之外。不把任何值放入 Git、診斷或 AI。
3. 設定 environment、遮蔽帳戶參照與 SDK 實際帳戶明確映射、配置金額、版本化商品／日曆／成本
   規則及能力證據來源／失效時間。API 資格與當沖資格不能由任意勾選自行通過。
4. 先保持 read_only=True、execution_enabled=False，人工安排一次無交易副作用的登入與查詢，
   核對帳戶、股口、交割、行情時間、現有持倉／委託與可賣量。L02 需要實際帳戶權限，尚待外部驗證。
5. 另在 BROKER_SIMULATION 取得相應 API key，驗證各市場支援的委託、回報、取消與部分成交；
   不支援情境仍跑本機故障替身並記缺口。L03 尚待外部驗證，不能用本機替身代替。
6. 完成至少五個實際交易日的觀察與一次重啟對帳。L04 本機交易日重播與券商觀察分開記錄。
7. 正式帳戶、CA、資格、商品費稅與風控驗收完成後，再由使用者另行安排受控正式範圍。
   本次沒有任何正式試單；L06 尚待外部驗證，不能以設定開關宣告驗收完成。

## 官方依據

查閱日 2026-10-25，轉換與能力需在實際接入時重核：

- [官方 PyPI 1.7.9 metadata](https://pypi.org/pypi/shioaji/1.7.9/json)
- [SDK 登入與帳戶](https://sinotrade.github.io/zh/tutor/login/)
- [商品合約與 info](https://sinotrade.github.io/zh/tutor/contract/)
- [股票委託及成交範例](https://sinotrade.github.io/zh/tutor/order/Stock/)
- [期貨委託](https://sinotrade.github.io/zh/tutor/order/FutureOption/)
- [狀態補查](https://sinotrade.github.io/zh/tutor/order/UpdateStatus/)
- [部位與 Share 單位](https://sinotrade.github.io/zh/tutor/accounting/position/)
- [交割款](https://sinotrade.github.io/zh/tutor/accounting/settlements/)
- [銀行餘額](https://sinotrade.github.io/zh/tutor/accounting/account_balance/)
- [交易額度](https://sinotrade.github.io/zh/tutor/accounting/trading_limits/)
- [保證金](https://sinotrade.github.io/zh/tutor/accounting/margin/)
- [歷史行情](https://sinotrade.github.io/zh/tutor/market_data/historical/)
- [模擬模式限制](https://sinotrade.github.io/zh/tutor/simulation/)

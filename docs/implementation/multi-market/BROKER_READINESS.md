# 永豐連接器接入與驗證紀錄

2026-10-25。本文件區分本機故障替身、真 SDK 型別檢查與券商實際連線。
本次沒有建立 SDK client、登入、讀取真憑證或操作真實委託；Sitecore 不在範圍內。

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

### 外部接入順序

1. 在隔離 broker runtime 用 hash lock 安裝 1.7.9；SDK 升版另做完整回歸，不能在持倉時自動切換。
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

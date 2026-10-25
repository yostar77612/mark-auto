# 現股價格帶來源與驗證界線

核對日期：2026-10-25。本文件記錄現股規格的工程依據，不代表券商登入、資料查詢、資格或交易已通過實測。

## 官方規則

| 適用商品 | 本機規則識別 | 已核對官方來源 |
| --- | --- | --- |
| 支持的普通股 | `twse-tpex-common-stock-20260924-v1` | [TWSE 營業細則第62條](https://twse-regulation.twse.com.tw/TW/law/DAT07.aspx?FLCODE=FL007116&FLNO=62)（法規頁所示版本2026-09-24）；[TPEx 上櫃交易制度第四節](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html) |
| 支持的新臺幣普通ETF分類 | `twse-tpex-twd-etf-20261025-v1` | [TWSE ETF交易規則](https://www.twse.com.tw/zh/products/securities/etf/overview/rules.html)；同上TPEx交易制度；版本日期為本次來源核對日期，並非虛構官方生效日 |

普通股為六個半開價格帶：`[0,10):0.01`、`[10,50):0.05`、`[50,100):0.1`、`[100,500):0.5`、`[500,1000):1`、`[1000,∞):5`。新臺幣ETF為`[0,50):0.01`及`[50,∞):0.05`。

此表與期貨價格帶不同；股票期貨以SDK的明確實月規格及完整價格帶比對，不能套用現股千元以上的區間。

## 商品分類來源

分類資源必須明確提供代碼、交易所、商品分類、ISIN、CFI、來源網址、來源版本、來源SHA256及具時區的紀錄時間。可選來源為證交所公開ISIN名錄：[上市](https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2)、[上櫃](https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=4)。分類與來源市場必須一致。

本輪只支持經核對的普通股CFI `ESVUFR`，以及普通ETF的 `CEOGEU`／`CEOIEU`。公開名錄可見2330為ISIN `TW0002330008`、CFI `ESVUFR`；0050為ISIN `TW0000050004`、ETF分類 `CEOGEU`。這些例子用於核對分類意義，不會從代碼長度、前綴或名稱猜測其他商品。其他分類、外幣ETF、權證等均拒絕，未擴充為所有台股商品。

`StockGridEvidence` 屬於使用者明確選定且由資源雜湊綁定的來源聲明；欄位格式與雜湊本身不能證明資料已由真服務取得或分類已經券商查核。資料供應者、實際快照SHA、來源更新與真券商回傳的聯調仍待外部驗證。測試的`a...a`來源雜湊明確只是合成控制，不是官方快照雜湊。配置資源的SHA檢查用於防止已選資料被替換，不會把這個層級升格為官方簽章驗證。

## 執行守衛與相容性

非LOCAL的現股必須同時符合：已支持分類與CFI、正確代碼與市場、七日內的具日期來源紀錄、完整官方價格帶與精確版本識別、SDK確認的新臺幣幣別、交易單位及非暫停交易。缺少分類、舊固定`0.01`、過期或互相矛盾的資料均在SDK委託建構前拒絕。設定正確也不會自動授予交易權限；正式執行仍預設停用。

Shioaji 1.7.9的`StockInfo`沒有`tick_basis`、`tick_rule`或`tick`；`category`是產業分類，不能可靠取代商品分類。官方[Contract V2文件](https://sinotrade.github.io/tutor/contract/#tick-bands)的`tick_bands`適用期貨與選擇權。本實作不對現股虛構這些欄位或呼叫。

LOCAL合成商品保留原固定跳動規格與結果，不改既有研究／績效預期。新增現股來源守衛只作用於券商連接器；三市場價格驗證、跨帶移動、費用、滑價與風險預留仍共用Domain的Decimal權威實作。

## 證據

2026-10-25實際公開來源抓取保存在相鄰審計目錄`multi-market-audit-20261025/stock-grid-sources/`。兩份完整HTML均超過原定8MiB界線，因此`capture.json`保留`CAPTURE_FAILED`，原始前綴保留，沒有提高界線或冒稱完整名錄下載成功。從已取得前綴只擷取完整表格列，`samples.json`保存原始位元組偏移、長度及雜湊；這些短證據不是可供交易的完整分類快照。

| 已核對公開列 | 原始完整列SHA256 |
| --- | --- |
| 2330／TW0002330008／ESVUFR | `773e2eafa5ed65594f57eb70f582c3b9f1c5df425cc2925066f46df667cb275a` |
| 0050／TW0000050004／CEOGEU | `d66857ed03453eba0fac0deec8719fd0d904c96e282aedc1580b529e22a14dac` |
| 00402A／TW00000402A9／CEOIEU | `54ea0a35f6de652b67bb8d4dda6823ed73fad0364233d51a7b40a4ae9f2f774a` |

`tests/test_trading_stock_grid.py`驗證六段／兩段邊界、分類／CFI／版本／來源／幣別不符、過期、拒絕固定scalar及SDK送出前守衛，並以千元股價計算實際價格帶滑價預留，防止使用0.01低估。既有SDK測試只補充明確ETF規格與合成來源聲明，不更改原有行為斷言。最終整合回歸另由總驗收紀錄綁定實際來源版本；單次焦點測試不可替代真服務驗證。

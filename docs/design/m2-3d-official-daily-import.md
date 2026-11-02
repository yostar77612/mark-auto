# 官方日 K 的明確下載與匯入

`tools/import_official_daily.py` 將官方 RAW 日 K 與完整 TWT49U 事件回應寫入既有
SQLite 行情快取。這是使用者明確執行的工具；行情輪詢、自動策略週期與畫面快照
均不會下載。工具不登入券商、不讀金鑰、不啟用 CA，也沒有下單或恢復自動交易功能。
目前只支援具有已驗證 TWT49U schema 的 TWSE；不把櫃買資料當成上市資料使用。

## 使用前

在專案根目錄以專案支援的 Python／修補版 SQLite 執行。`--cache` 要指向實際
執行個體資料目錄的 `market/klines.sqlite3`；不要把另一個環境的資料目錄誤當成
目前執行個體。範例路徑 `C:/MarkAutoData` 是使用者自行指定的資料目錄，不是
程式會自動選擇的預設目錄。

`--start` 包含當日，`--end` 不包含當日。工具只接受已過的台北日期；例如要匯入
2025-06-12，最早須在台北 2025-06-13 執行。若要讓該日訊號在下一個已驗證開盤
送出，必須在開盤前完成官方資料匯入、保留原本仍有效的自動執行授權，並通過當前
連線、對帳、行情與風控。資料開盤後才抵達時，不補造開盤訊號、不追價補送。
程式重啟、斷線或使用者停止後仍須依既有流程對帳並明確恢復；匯入不是恢復操作。

## 明確同意下載

每次下載都必須給 `--consent-download`，且 `--archive` 必須是尚不存在的新目錄：

```powershell
python -m tools.import_official_daily --cache C:/MarkAutoData/market/klines.sqlite3 --instrument TWSE:6225 --start 2025-06-02 --end 2025-06-13 --consent-download --archive C:/MarkAutoData/official-recordings/6225-20250613
```

此指令使用原有官方 HTTP 邊界：官方 HTTPS 精確端點、禁止重新導向、原有回應大小與
期限限制。新增的 TWT49U 使用全市場日期區間，不加 `stockNo` 變成未驗證的另一種
查詢。TWT49U 網址的末日是包含式；工具會把排除式 `--end` 減一天。上市月報仍使用
既有 STOCK_DAY parser，並獨立核對回應中的股票名稱標題／代號。

只有整個請求區間的月報與事件回應全部通過，才一次發布 RAW 日 K、事件及來源。
原始 JSON 與 manifest 保存在新封存目錄，包含官方網址、SHA256 與實際取得時間。
任何月報、schema、來源或事件區間不通過，舊快取不會被這一批部分覆寫。

## 離線重建與封存復原

```powershell
python -m tools.import_official_daily --cache C:/MarkAutoData/market/klines.sqlite3 --instrument TWSE:6225 --start 2025-06-02 --end 2025-06-13 --manifest C:/MarkAutoData/official-recordings/6225-20250613/manifest.json
```

離線模式完全不呼叫網路。manifest 的 `documents` 每筆有 `file`、`url`、`sha256`；
JSON 原檔須在 manifest 同一層，不能用父目錄、子目錄或符號連結借讀其他檔案。
每個所需月份與完整事件區間都必須有唯一、明確的輸入，缺資料或互相矛盾／不明確時
拒絕，而非任意挑一份。相同區間的修正只按既有交易式匯入規則發布；歷史原始 payload
依既有儲存規則保留。若既有 KlineStore 偵測到損壞而保留 `.bad-*` 備份，工具回報
`cache_warning`；原始封存可用來重新匯入，不刪除保留檔、不捏造缺失資料。

`IMPORTED` 表示這批官方回應已驗證並入庫，不表示已證明所有交易日皆有行情，或策略
可以部署／送單。缺少交易日、停牌或研究範圍不足，仍由官方日 K source 與研究守衛
拒絕。不補零成交日、不合成分鐘、不用月報推測休市日，不拿現價回填歷史日 K。

## 資料與時序邊界

- 儲存的是 RAW OHLCV；訊號端使用既有官方事件調整規則，不改動原始成交價格。
- 即使該股票沒有事件列，也必須保留日期範圍、stat 與 schema 完整通過的全市場事件
  回應。沒有事件檔或不完整的事件區間，不能宣稱「沒有除權息」。
- 官方來源使用儲存層實際接收時間，不能把 manifest 的日期或稍後讀取時間冒充到達
  時間。封存重建是一次新的實際匯入，不倒填成先前曾在開盤前取得。
- 此工具不產生現金股利支付／權利入帳證明；參考價調整資訊不是券商現金結算事實。

本輪測試只用錄製的官方回應及 fake SDK。新錄製的 TWT49U 2025 年 6 月回應來源、
實際取得時間與 SHA 保存在 `tests/fixtures/daily_basis_import/manifest.json`；測試不連網。

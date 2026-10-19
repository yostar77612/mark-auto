# ADR 0005: Decimal 與內容雜湊策略（content-hash strategy）

日期: 2026-10-19
狀態: Accepted（記錄既有決策）

## 背景

二進位浮點金額會引入難以審核的誤差；可變策略與僅靠顯示名稱辨識的結果，無法可靠判斷兩次執行是否使用相同內容。

## 決策

價格與金額計算維持 Decimal，成本與捨入政策明確記錄；JSON 將 Decimal 表為字串。共享 canonical JSON 以排序鍵、UTF-8 及明確時間表示正規化，再以 SHA-256 產生內容雜湊。策略規格為不可變內容版本，顯示 ID 不足以代替內容身分；結果需綁定適用的策略、資料、設定與政策身分。

選擇嚴格序列化與驗證成本，放棄浮點金額及可原地覆寫版本的便利。內容雜湊證明內容相符，不證明來源真實、資料權利或策略有效；實盤永久停用（live trading permanently disabled）。

## 後果

修改策略內容形成不同修訂，舊結果仍屬原修訂。重現比較依各紀錄的雜湊契約排除非決定性的執行時間資訊；不能為取得相同結果改寫既有 golden 預期值，也不能把 hash 相符當成外部驗收通過。

依據：[共享值與序列化](../../quantlab/core.py)、[回測](../../quantlab/backtest.py)、[工程契約](../agent/IMPLEMENTATION_CONTRACTS.md)。詞義見[術語表](../GLOSSARY.md)。

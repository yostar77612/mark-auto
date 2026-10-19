# ADR 0004: 有限 AST 規則取代任意程式碼

日期: 2026-10-19
狀態: Accepted（記錄既有決策）

## 背景

AI 或使用者提供的策略內容是不可信輸入。任意程式碼雖能擴充指標與行為，也會破壞資料邊界、資源限制與可重現性。

## 決策

策略使用有限 JSON AST／DSL：驗證允許的欄位、運算、參數、節點深度及大小，只接受既有策略語意。禁止 eval、exec、new Function 等動態執行；不把策略文字當程式載入。未知規則 fail closed，而非猜測或修補成可執行內容。

選擇可驗證且有界的表達能力，放棄任意腳本的自由度。策略產生訊號而非券商委託；實盤永久停用（live trading permanently disabled）。

## 後果

新語法與策略能力須透過受審查的實作和測試擴充，不能用外部腳本繞過限制。通過語法驗證不等於取得研究資格、紙上資格或獲利證據；OOS 與預算限制仍有效。

依據：[DSL 驗證](../../quantlab/research.py)、[策略規則](../../quantlab/strategies.py)、[工程契約](../agent/IMPLEMENTATION_CONTRACTS.md)。詞義見[術語表](../GLOSSARY.md)。

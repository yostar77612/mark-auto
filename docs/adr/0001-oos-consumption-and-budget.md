# ADR 0001: OOS 一次性消耗與不可逆預算

日期: 2026-10-19
狀態: Accepted（記錄既有決策）

## 背景

反覆觀看 OOS 或 holdout 再修改策略，會把評估資料變成訓練資料。失敗後免費重試也會隱藏實際搜尋成本，讓研究結果失去可追溯性。

## 決策

候選只依 train／validation 選定並凍結，再進行 OOS／holdout 評估。OOS 一次性消耗；holdout 在評估前先持久化 consumed guard，同工作區重疊保留區間也視為已見。預算採先保留、不可逆消耗；中斷、失敗或結果未知不退還額度，也不隱式重試。刪除或複製研究目錄不能使資料重新成為未見資料。

這優先保護評估獨立性，放棄失敗後自動重跑的便利。實盤永久停用（live trading permanently disabled）；本決策不授予下單能力。

## 後果

中斷後只能依既有對帳流程確認狀態，不能清除控制紀錄換取額度。已消耗與未完成可以同時成立；文件不宣稱外部驗收通過，正式驗收仍為 230/300。期限維持 Paper 30 s、smoke 40 s、每 job 15 min，不以延長期限解決失敗。

依據：[研究核心](../../quantlab/research.py)、[工程契約](../agent/IMPLEMENTATION_CONTRACTS.md)、[目前狀態](../agent/PROJECT_STATE.md)。詞義見[術語表](../GLOSSARY.md)。

# ADR 0002: Paper 是 journal，不是券商模擬

日期: 2026-10-19
狀態: Accepted（記錄既有決策）

## 背景

紙上委託容易被誤解為券商測試環境或完整撮合市場。僅有委託與成交畫面，不能證明排隊、流動性、真實成交或券商連線行為。

## 決策

Paper 以持久化 journal 作為帳戶事件的權威紀錄，快照由事件重建；重啟與未知結果依既有對帳規則處理。接受離線合成帳務的有限範圍，放棄模仿券商端點與完整委託簿。實盤永久停用（live trading permanently disabled），不存在以 Paper 資格解鎖實盤的階段。

Replay 是歷史行情驅動的有界紙上執行：綁定策略、資料、journal 與政策，採 next-bar market 語意；不等同回測的停損／停利模型，不能重播不支援的保護規則。

## 後果

回測結果與 Paper／Replay 不可直接互當成交證據。停止新委託不代表平倉；未知結果不能假定成功或盲目重送。研究資格不等於紙上資格；風控、資料與政策條件仍各自驗證。

依據：[Paper](../../quantlab/paper.py)、[Replay](../../quantlab/paper_replay.py)、[工程契約](../agent/IMPLEMENTATION_CONTRACTS.md)。詞義見[術語表](../GLOSSARY.md)。

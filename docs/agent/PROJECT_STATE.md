# mark-auto 開發接續狀態

更新：2026-10-09 UTC。唯一來源：https://github.com/yostar77612/mark-auto。

## 目前狀態

- 分支：agent/quantlab-v1
- 原始 main 基準：1cacce4ee4eef4ce7e8760f8153ef64a74852d22
- Phase 0 已完成；固定工程完成率 15%，剩餘85%。計算依 ACCEPTANCE.json，不以測試數或耗時估算。
- 已查47個現行檔案、38個Python檔案皆AST解析成功；不是runtime驗證。
- 掃描完整可達2個Commit、48個不同blob；未發現高可信度密鑰，仍有第三方CDN路徑常值歸屬待核實。
- 已確認舊回測核心缺失、舊程式啟動涉及券商／DB副作用，以及TLS、Telegram和Log風險。
- 進入Phase1安全修復，同步開發不依賴舊trader的quantlab研究模組。

## 固定決策

保留Apache授權及舊程式參考。Python標準庫研究核心、Decimal帳務、SQLite實驗／模擬持久化；使用獨立Streamlit research_app.py及CLI。不可從quantlab匯入trader或券商SDK。AI僅受限DSL；fixture、真模型、合成資料、官方資料驗證分別記錄。至少五種不同交易邏輯。詳見IMPLEMENTATION_CONTRACTS.md。

## 驗收與限制

使用ACCEPTANCE.json的六階段固定分母。任何未通過安全、交易正確性、因果資料或回測Gate均不得宣稱完成。模擬與真實交易分開；LiveBroker固定停用，沒有環境變數捷徑。不得呼叫付費API或使用真實帳戶。

## 下個工作

1. 完成獨立核心與明確資料schema，執行離線單元及Golden測試。
2. 完成舊路徑的安全封鎖及回歸測試。
3. 整合研究、報告UI及paper恢復；完成五份分析文件。
4. 對最終Commit跑完整測試與安全複掃，再推送、PR與合併。

## 執行入口

正式離線入口將為 python -m unittest discover -s tests -v 及 python -m quantlab。尚在建置，未宣稱可執行。禁止以run.py或gui.py作為研究測試入口。接手前先讀本檔、ACCEPTANCE.json、IMPLEMENTATION_CONTRACTS.md，再git status確認其他工作。

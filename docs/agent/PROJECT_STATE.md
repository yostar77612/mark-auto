# mark-auto 開發接續狀態

更新：2026-10-09 16:18 UTC。唯一來源：https://github.com/yostar77612/mark-auto。

## 目前狀態

- 分支 agent/quantlab-v1；原始 main 基準 1cacce4ee4eef4ce7e8760f8153ef64a74852d22。
- Phase 0–4 已完成，原研究範圍工程完成率 85%，剩餘 15%。使用者於16:25 UTC新增必要桌面交付後，總分由100擴為200點，原標準不變；目前整體42.5%，剩餘57.5%。唯一計分來源 ACCEPTANCE.json。
- 完整本地測試 176 PASS、0 SKIP，39.239 秒；Linux Python 3.12，包含 5 個 Streamlit AppTest。最終 fresh-checkout、遠端 CI 與安全複掃仍待驗收。
- 原本本地提交 0430a74、5bcfbe5、2110016 均保留。GitHub App 新授權已可建立 Git 物件、開發分支與 PR；CLI 本身尚無登入。連線發布採相同 Git tree、新 Commit SHA，映射另列，不重寫原歷史。
- PR：https://github.com/yostar77612/mark-auto/pull/1，尚未合併。

## 已有功能與證據

獨立 quantlab 核心、版本化交易時段／到期、官方 CSV／RPT／日報匯入、因果回測與 Decimal 帳務、五種策略、受限 DSL、持久研究預算與保留集使用登記、報表版本選擇、Streamlit／CLI、Paper 日誌對帳與風控均已實作並本地測試。研究與券商 SDK 隔離；舊 trader 啟動與危險 legacy 路徑刻意停用。

實際 2026-10-08 官方資料匯入 1140 根分鐘 K，日夜 OHLC 比對一致。成交量差異與排除價差單口徑相符，但正式分配語義仍待確認。這不是完整歷史或實際撮合認證。

2026-10-09 已實際使用新 refresh CLI 取得期交所公布的 2026-10-12 CSV ZIP；來源檔屬下一交易日期，保留 provisional_unverified／ranking_eligible=false。下載不代表盤別完成或可排名。原始行情不放入 Git。

## 固定決策與安全界線

保留 Apache 授權及舊程式來源參考。標準庫研究核心、Decimal、SQLite、薄 Streamlit／CLI。AI 只產受限 DSL；預設 fixture generator，不冒充真模型。LiveBroker 固定停用，無環境旗標捷徑；禁止真實資金與付費服務。不能依合成回測聲稱真實市場獲利。

Paper 重播為有限歷史批次，沒有實際行情串流；尚不支援的盤中停損／停利明確拒絕。持倉／委託未知時先凍結，不以補單猜測恢復。Windows 桌面打包、長期無人值守、真模型、完整歷史與券商認證尚非已完成狀態。

## 下一步

1. 保存最終模組提交並完成 fresh-checkout、建置、安全複掃。
2. 發布相同 tree 至現有 PR，驗證 Linux／Windows CI；失敗修正，不降低標準。
3. 必要 Gate 通過後合併 main，核對遠端；保留未合併的原始本地 SHA 歷史。
4. 交付五份分析文件及外部就緒限制。

## 執行入口

python -m unittest discover -s tests -v

python -m quantlab --help

streamlit run research_app.py --server.address 127.0.0.1

研究 UI 依 requirements-ui.lock 安裝於獨立環境；不可用舊 run.py／gui.py 啟動研究。接手先讀本檔、ACCEPTANCE.json、IMPLEMENTATION_CONTRACTS.md，再 git status 保留既有成果。


## 必要桌面交付（新增範圍，2026-10-09 16:25 UTC）

Windows10 22H2 x64與Windows11 x64原生桌面、免裝Python、每使用者安裝程式與捷徑、繁中主要功能、背景工作／取消、單例與睡眠恢复、安全設定／備份還原、版本升級及GitHub Release已納入必要驗收。選用PySide6原生Qt與既有quantlab核心，保留Streamlit研究入口作輔助；不重寫帳務或策略引擎。

桌面D0–D9每项10點，與原研究100點合計200點。分母增加來自使用者新增需求，不降低舊Gate，不把EXE建置當乾淨Windows10/11驗收。

環境查核：無已儲存coding environment；可見Windows電腦均未授權此任務，不能使用。GitHub windows-latest實際為Windows Server，能做安裝／啟動自動測試但不能替代Win10/11。D7/D8先標BLOCKED，繼續其餘開發。

main保護尚未啟用：branch metadata顯示protected=false，rulesets清單空；讀取管理級branch protection API回403 Resource not accessible by integration。這是缺administration權限，非Code/PR新授權失效；寫入分支與PR成功。不得聲稱保護生效，也不為此重新建立環境或索取Token。


## 原研究版整合驗證（2026-10-09 16:32 UTC）

原Phase0–5研究範圍100點通過，新增桌面0/100，整體100/200＝50%，剩餘50%。這不是最終桌面產品完成。

研究修復提交76ad3a5對應遠端8cea2729fa5f0acca1d1ff947b08d173ffddcd71；本地180tests通過，GitHub run37959451997的Linux／Windows Server、Python3.11/3.12及UI共5jobs全成功。Windows曾實際揭露來源編碼、SQLite連線未close與短路徑比較問題，已修復並重驗。平台限定RLIMIT_AS／fork與選用UI的skip有明確原因，由Linux UI完整suite覆蓋；不可當Win10/11或Windows資源硬限制證明。研究wheel／sdist重新建置成功。

正式下載最近30個官方CSV ZIP完成，仍provisional且未完成全部歷史日曆／逐盤品質驗證，不得產生正式策略排名。首次批次遇HTTP逾時失敗；一次有界重試成功，快取與原始檔不提交公開Git。

原始0430a74與遠端eeccb3296e47e84fe8d0f68446dda6cae58976a0的Git tree均為df167ff071331a6eb75007a72c0d3637e4fc899a，檔案路徑／內容／模式完全一致。所有本地原始提交與新增未提交桌面工作均保留，未forcepush或reset。

新桌面與新增CI安全／品質工作尚在開發，main尚未合併；之後以最終head全部必要Gate重新判定。

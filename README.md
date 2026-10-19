# MarkAuto

MarkAuto 是台灣股價指數期貨 TX／MTX／TMF 的離線研究與紙上交易桌面工具。市場總覽可查看三種商品；目前研究與紙上資格仍限已驗證 TMF。桌面版為產品入口，Streamlit 僅供開發研究。

> **安全聲明**：僅研究／紙上模擬，實盤交易永久停用。示範資料與預設成本不是實際行情或獲利保證；樣本外（OOS）與保留集依明確同意使用一次，取消或失敗不退還已消耗額度。停止新委託不會平倉。

## 安裝

1. Windows 10／11 x64 使用者從 [GitHub Releases](https://github.com/yostar77612/mark-auto/releases) 下載相同版本的安裝程式與 SHA256SUMS。
2. 使用 PowerShell `Get-FileHash .\下載的安裝程式.exe -Algorithm SHA256`，逐字核對 SHA256 後安裝。
3. 目前未簽章，SmartScreen 可能顯示警告；先核對來源，不要停用 Windows 安全防護。乾淨 Win10／Win11 驗收仍待完成。
4. 從捷徑啟動；一般使用不需 Python 或 Git。

## 開發環境

執行 [tools/dev_setup.ps1](tools/dev_setup.ps1)，在專案內建立私有 SQLite runtime 與虛擬環境。
使用 [requirements-desktop.lock](requirements-desktop.lock)；建置入口為 [packaging/build.ps1](packaging/build.ps1)。
完整操作見 [packaging/README.md](packaging/README.md)。

## 快速開始

1. **資料**：在「資料匯入與更新」匯入核對資料，或建立明示合成示範。
2. **策略**：在「AI 策略中心」選家族與參數，再視需要研究或 Walk-forward。
3. **回測**：在「回測與結果」核對日期、費率與資金後執行。
4. **比較**：在「比較與策略選擇」勾選保存結果，核對資格並啟用研究／紙上策略。
5. **紙上交易**：在「紙上交易與復原」核對政策與快照、明確對帳，再重播。

## 文件索引

設定頁提供手動「檢查更新」與「檢查舊程式版本」；清理須確認，保留目前版與最近舊版。更新檢查只核對版本資訊，不下載或安裝。詳見 [維護契約與待驗證證據](docs/analysis/t15_p3_notes.md)。

- [使用手冊（七頁截圖）](docs/user/使用手冊.md)
- [Display compatibility checklist — EXTERNAL / UNVERIFIED](docs/qa/display-compatibility.md)
- [Release notes document template — no publication](docs/release/RELEASE_NOTES_TEMPLATE.md)
- [Contributor guide and PR verification](docs/CONTRIBUTING.md)
- [目前狀態](docs/agent/PROJECT_STATE.md)、[實作契約](docs/agent/IMPLEMENTATION_CONTRACTS.md)、[正式驗收](docs/agent/ACCEPTANCE.json)
- [架構](docs/analysis/01_PROJECT_ARCHITECTURE.md)、[既有功能](docs/analysis/02_EXISTING_FEATURES.md)、[目前品質與風險](docs/analysis/03_CODE_QUALITY_AND_RISKS.md)
- [AI 目標設計](docs/analysis/04_AI_QUANT_TARGET_DESIGN.md)、[路線圖](docs/analysis/05_IMPLEMENTATION_ROADMAP.md)、[優化計畫](docs/analysis/06_PRODUCT_OPTIMIZATION_PLAN.md)
- [封裝指南](packaging/README.md)、[分層前 README 全文](docs/agent/history/README_before_layering.md)
- [舊碼來源與封存說明](archives/legacy_autotrading/README.md)

## Provenance

MarkAuto derives from Li Kuei-Wei's Apache-2.0 AutoTradingPlatform. Disabled upstream code, provenance and copyright details are preserved in the [legacy archive](archives/legacy_autotrading/); the product never imports or bundles this code.

## 授權

[Apache License 2.0](LICENSE)；[第三方授權](packaging/THIRD_PARTY_NOTICES.md)。

# mark-auto 台股期貨研究平台

本專案新增獨立的 `quantlab` 離線研究核心與 `research_app.py` 操作介面。研究、模擬與正式券商交易分離；**真實交易固定停用**。原 AutoTradingPlatform 程式保留為來源與後續 Adapter 參考，其舊入口已停用。這不是獲利保證，也不是已驗證的實盤系統。

## Windows 桌面版（必要產品交付，驗收中）

原生 PySide6／Qt 桌面入口為 `desktop.py`，沿用同一個 `quantlab` 核心，不需要另啟 Web 服務。桌面安裝程式建置流程在 [packaging/README.md](packaging/README.md)。可下載安裝檔以 [GitHub Releases](https://github.com/yostar77612/mark-auto/releases) 實際發布的資產為準；沒有資產時不可把原始碼當安裝版。預覽版不代表 Windows 10／11 最終驗收已通過。

### 一般使用者操作

1. 下載對應版本的 Windows x64 setup EXE，先核對同版 SHA256SUMS 與發布限制。
2. 安裝至個人程式目錄；安裝器建立桌面／開始功能表捷徑。一般使用者不需要 Python、pip、Git。
3. 雙擊 MarkAuto，先看資料、模型及風控狀態。初次使用可建立明確標示的合成範例，熟悉操作，不能把其績效當真實投資結果。
4. 在「資料匯入與更新」取得免費官方近期檔案，選擇明確契約／時段與已查核行情。下載成功不等於歷史完整或可正式排名。
5. 在策略、回測及比較頁設定版本、日期與成本／風控，查看資金曲線及成交，匯出報告。研究候選沒過門檻時可全部淘汰。
6. AI 預設 Fixture；需要外部相容模型時先設定模型／端點、預算及網路／可能費用同意。機密由使用者在桌面設定中輸入，Windows 系統保護保存，不放 Git 或備份。
7. Paper 重啟、睡眠或異常後需明確對帳。未知狀態不會自動补單；緊急停止會凍結新工作，不假裝已成交／平倉。實盤在本版固定停用。
8. 關閉時處理尚在執行的工作。下一次開啟保留設定與資料；更新前先備份，關閉舊程式後安裝新版本。

程式安裝在 `%LOCALAPPDATA%\Programs\MarkAuto`；使用者資料在 `%LOCALAPPDATA%\MarkAuto`，不得混用 Program Files。Windows「設定 → 應用程式」可解除安裝；預設保留資料，避免誤刪歷史。備份／還原排除機密及不可回退的研究控制帳本、檢查版本與hash，還原前停止工作；遇版本不相容不覆寫原資料，可回裝相容舊版並還原已驗證備份。

安裝器尚無正式程式碼簽章；若 Windows 顯示安全警告，不應停用或繞過安全機制。乾淨 Windows10 22H2 x64／Windows11 x64實測、標準使用者權限與長時間運作仍需獨立證據；Windows Server CI 不等同 client OS 測試。所有最新狀態以 [固定驗收](docs/agent/ACCEPTANCE.json) 為準。

## 開發者／研究入口

## 快速開始

需求：Python 3.11 以上。離線核心使用標準函式庫；Windows 可安裝 `tzdata` 以載入時區資料。

```bash
python -m unittest discover -s tests -v
python -m quantlab demo --output ./quantlab-output/demo
```

`demo` 僅產生明確標示的 SYNTHETIC 行情，執行五種不同策略並匯出結果。不能把展示損益當作真實市場績效。

### 本機研究介面

使用獨立虛擬環境，不安裝舊券商套件清單：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-ui.lock
streamlit run research_app.py --server.address 127.0.0.1
```

介面提供本機資料匯入與品質檢查、五種策略、回測與報表、研究試驗、策略比較／選擇、Paper 帳本與歷史行情重播。不要公開暴露此本機檔案操作介面；本版本沒有多使用者身分驗證。

### 明確資料與成本

```bash
python -m quantlab import examples/synthetic_bars.csv --kind synthetic_bars --calendar examples/synthetic_calendar.json --output ./quantlab-output/dataset.json
python -m quantlab backtest ./quantlab-output/dataset.json --config examples/synthetic_config.json --output ./quantlab-output/reports
python -m quantlab campaign ./quantlab-output/dataset.json --output ./quantlab-output/campaign
```

`examples` 的時段、價格、保證金與成本均為測試假設。正式研究需換成已查核的資料、有效日期化成本／保證金與交易所日曆。官方格式僅支援實際觀察並測試的欄位；未知格式、未覆蓋日期或缺漏資料須拒絕，不能猜測補值。付費行情與帳戶資訊不得提交 Git。

### 官方免費資料更新

```bash
python -m quantlab refresh --cache ./quantlab-output/official --days 1 --format csv
```

僅從期交所已公布連結取得最近最多 30 個交易日期的 CSV／RPT ZIP。更新保留 SHA 版本、檢查 TLS、大小與解壓安全，不把重複下載當作新資料。下載結果先標為 provisional_unverified／ranking_eligible=false；夜盤檔案日期可能屬下一交易日，必須經明確交易日曆及匯入品質驗證才能研究。資料不足時不產生正式策略排名。原始行情與快取不得提交 Git。

## 重要安全與驗證界線

- `quantlab` 不匯入 `trader` 或券商 SDK，匯入本身不連線或建立帳戶。
- 舊 `run.py`、`gui.py`、`trader` 啟動、pickle／Redis反序列化及舊下載流程刻意停用；不應嘗試用憑證啟動。
- Paper 使用可稽核 SQLite 事件帳本；重啟／未知委託先凍結新單，完整對帳後才可恢复。停止不會偷偷平倉。
- 預設策略研究使用明確標示的 fixture generator；它驗證工程流程，**不代表真實模型已完成驗證**。選用 HTTP 相容模型時必須明確開啟、提供端點及預算；本次未呼叫外部付費模型。
- 五種策略家族為趨勢、均值回歸、通道突破、動能與波動壓縮突破。參數、資料及成本版本綁定每個結果；通過工程測試不代表策略通過投資績效門檻。
- 回測提供下一根開盤成交、成本、保證金、雙邊換月及顯式結算事件；OHLC不能證明真實排隊／流動性。缺少必要換月或结算輸入時失敗封鎖。
- Paper 重播是有限批次歷史事件處理，沒有實際即時行情；尚未支援的盤中停損／停利規則會拒絕，不會默默忽略。
- 遠端 Windows/CI、實際模型、券商認證、完整歷史日曆及長時間真實運行狀態請看接續文件，不得由 Linux 合成測試推論通過。

## 文件與開發接續

- [目前狀態及下一步](docs/agent/PROJECT_STATE.md)
- [固定驗收清單](docs/agent/ACCEPTANCE.json)
- [介面合約及工作責任](docs/agent/IMPLEMENTATION_CONTRACTS.md)
- [專案架構](docs/analysis/01_PROJECT_ARCHITECTURE.md)
- [既有功能盤點](docs/analysis/02_EXISTING_FEATURES.md)
- [程式品質與風險](docs/analysis/03_CODE_QUALITY_AND_RISKS.md)
- [AI量化目標設計](docs/analysis/04_AI_QUANT_TARGET_DESIGN.md)
- [MVP與開發Roadmap](docs/analysis/05_IMPLEMENTATION_ROADMAP.md)

## 授權與原始來源

保留原 Apache-2.0 LICENSE 與 Li Kuei-Wei 2023 著作權聲明。2026-10-09 起的修改包含獨立研究模組、安全封鎖、測試及文件。原始 upstream 精確提交版本尚未核實；以下保留原專案說明作歷史參考，其功能聲稱不代表目前功能驗證。

---

# AutoTradingPlatform

[![PyPI - Status](https://img.shields.io/pypi/v/shioaji.svg?style=for-the-badge)](https://pypi.org/project/shioaji)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/shioaji.svg?style=for-the-badge)]()

AutoTradingPlatform is a *trading framework* built on top of the [Shioaji API](https://sinotrade.github.io/) and supports **Shioaji 1.5+**. It can trade **stocks, futures, and options**, including single-leg option orders and option combo orders. The framework streamlines the use of the API, making it easy for users to start trading without being familiar with the API's interface specifications. With just two simple steps, users can start trading:

1. Develop a trading strategy.
2. Set the risk tolerance.

When using AutoTradingPlatform, users can execute trades with multiple strategies on a single account, or even on multiple accounts. The platform also supports multi-frequency intraday monitoring, runtime strategy controls such as updating `max_qty`, and position synchronization between broker-side positions and local monitoring records.


- [AutoTradingPlatform](#autotradingplatform)
  - [What AutoTradingPlatform is capable of?](#what-autotradingplatform-is-capable-of)
    - [1. Position control](#1-position-control)
    - [2. Multi-frequency K-bars and technical indicators](#2-multi-frequency-k-bars-and-technical-indicators)
    - [3. Real-time notification](#3-real-time-notification)
    - [4. Stock selection](#4-stock-selection)
    - [5. Historical backtesting](#5-historical-backtesting)
    - [6. Full automation](#6-full-automation)
    - [7. Telegram Bot interactions](#7-telegram-bot-interactions)
    - [8. Stocks, futures, and options orders](#8-stocks-futures-and-options-orders)
    - [9. Runtime position synchronization](#9-runtime-position-synchronization)
  - [Required packages](#required-packages)
  - [Project Structure](#project-structure)
  - [Preparation](#preparation)
    - [Step 1: Create system settings (config.ini)](#step-1-create-system-settings-configini)
    - [Step 2: Create user settings (user env settings)](#step-2-create-user-settings-user-env-settings)
    - [Step 3: Create strategy scripts](#step-3-create-strategy-scripts)
  - [Execute Commands](#execute-commands)
      - [0. GUI control panel](#0-gui-control-panel)
      - [1. Auto trader](#1-auto-trader)
      - [2. Stock selection](#2-stock-selection)
  - [Releases and Contributing](#releases-and-contributing)
  
## What AutoTradingPlatform is capable of?

#### 1. Position control
The system monitors order amount, position size, strategy-level quantity limits, and batch exits. Multiple strategies can run on the same account while each strategy keeps its own position state and `max_qty` controls.

#### 2. Multi-frequency K-bars and technical indicators
In addition to traditional indicators such as MACD, KD, RSI, you can customize indicators based on technical, chip, and fundamental information. Intraday monitoring stores K-bars by frequency in `TradeData.KBars.Freq`, and strategies can monitor multiple frequencies such as `1T`, `5T`, `15T`, `30T`, `60T`, and `1D`.

#### 3. Real-time notification
Receive real-time order/deal messages through Telegram or LINE Notify.

#### 4. Stock selection
By customizing the selection criterias, the stock selection program can be seamlessly integrated with the trading system to place orders. There is no limit to the number of strategies.

#### 5. Historical backtesting
Using historical data and customizable strategy functions, the backtesting framework supports single-frequency and multi-frequency K-bar strategies. Futures-style strategies can prepare all configured `kbarScales` in advance and receive aligned multi-frequency data in strategy callbacks through `**kwargs`.

#### 6. Full automation
Once everything is set up, you can schedule and achieve fully automated trading.

#### 7. Telegram Bot interactions
Read [TelegramBot.md](./TelegramBot.md) for more instructions. Telegram commands can be used to check and update strategy `max_qty` while the monitor is running.

#### 8. Stocks, futures, and options orders
The order layer supports stock, futures, single-option, and option-combo order workflows for Shioaji 1.5+. Option helpers normalize option contract lookup and order creation so strategy code can focus on trading logic.

#### 9. Runtime position synchronization
AutoTradingPlatform can synchronize broker-side positions into local monitoring records. This helps recover monitoring state after manual orders, restarts, fills from outside the strategy loop, or changes made while the bot is running.

## Required packages
Install Shioaji 1.5+ and other packages at a time. The current requirements pin Shioaji to `1.5.3`.
```ini
pip install -r requirements.txt
```

## Project Structure
```lua
.  
  |-- templates
  |-- trader                         (Python trading modules, details as below:)
    |-- indicators                   (trading indicators)
    |-- scripts                      (folder for putting CUSTOMIZED TRADING SCRIPTS)
      |-- ...
    |-- ...
  |-- lib                            (keys, settings, ..., etc)
    |-- ckey                         (has public/private keys to encrypt/decrypt password text)  
    |-- ekey                         (Sinopac ca files for placing orders)  
      |-- 551  
        |--...  
    |-- envs                         (AutoTradingPlatform user settings)  
    |-- schedules                    (schedule task files, ex: *.bat)
    |-- config.ini                   (AutoTradingPlatform system settings)
    |-- 政府行政機關辦公日曆表.csv
    ...
  |--data
    |-- Kbars                        (stores any kinds of stock/futures/options/indexes data)  
    |-- selections                   (selected stocks)  
    |-- stock_pool                   (stores watchlist, order list files for AutoTradingPlatform)  
    |-- ticks                        (futures tick data from TAIFEX)
  |-- archives                       (legacy tools kept for reference)
  |-- gui.py                         (local GUI control panel and dashboard)
  |-- tasker.py                      (AutoTradingPlatform task execution file)
  ...
```


## Preparation
#### Step 1: Create system settings (config.ini)
Go to ```./lib``` and create a ```config.ini``` file, which has 6 main sections: 

```ini
[ACCOUNT] # user names
USERS = your_env_file_name
LOG_LEVEL = DEBUG

[COST] # Account trading costs for stocks/futures/options
STOCK_FEE_RATE = 0.001425
FUTURES_FEE_TXF = 100
FUTURES_FEE_MXF = 100
FUTURES_FEE_TMF = 100
FUTURES_FEE_TXO = 100

[DATA]
DATA_PATH = your/path/to/save/datasets

[DB] # optional, can be left blank
DB_ENGINE = mysql+pymysql/postgresql
REDIS_HOST = your_redis_host
REDIS_PORT = your_redis_port
REDIS_PWD = your_redis_password
DB_HOST = your_DB_host
DB_PORT = your_DB_port
DB_USER = your_DB_user_name
DB_PWD = your_DB_password
DB_NAME = your_DB_schema_name

[NOTIFY] # optional, can be left blank, PLATFORM = Telegram/Line
PLATFORM = Telegram
TELEGRAM_TOKEN = {"user_name": "your_Telegram_Notify_token"}
TELEGRAM_CHAT_ID = {"user_name": "your_Telegram_Chat_ID"}
LINE_TOKEN = your_LINE_Notify_token

[STRATEGY]
MonitorFreq = 5      # monitor frequency (seconds per loop)

[CRAWLER] # determine what K-bar frequency data you want for monitor/backtest
SCALES = 1T, 5T, 15T, 30T, 60T, 1D
```

#### Step 2: Create user settings (user env settings)
It is necessary to create user settings for each trading account before starting the auto trader. Start the local GUI:

```bash
streamlit run gui.py
```

Then open the Streamlit URL shown in the terminal, usually http://localhost:8501, and go to the `使用者專區` tab. You can add, edit, or delete account settings there. The settings will be saved to the `user_settings` database table.

The old `python run.py -TASK create_env` Flask setup page has been archived under `archives/legacy_create_env_app`. Use the GUI `使用者專區` for new account setup and maintenance.

#### Step 3: Create strategy scripts
Go to ```./trader/scripts``` and follow the [instructions](./trader/scripts/README.md) to create your own trading strategy before starting the auto-trader. Strategy modules can define:

```python
scale = '1T'
kbarScales = ['1T', '15T']

def add_features(df, scale='1T'):
    ...

def examineOpen(trade, price=None, **kwargs):
    K15min = kwargs.get('K15T')
    ...
```

During backtesting, `scale` is the main loop frequency and `kbarScales` determines which frequencies are prepared and aligned. During intraday monitoring, `TradeData.KBars.Freq[scale]` remains a pandas DataFrame for each frequency.

## Execute Commands
Open a terminal and execute the following task command type:

#### 0. GUI control panel
Start the local GUI dashboard and control panel:

```bash
streamlit run gui.py
```

The GUI supports per-account trader startup, pause/resume/stop commands, status monitoring, recent log display, current position display, runtime `max_qty` updates, and `UserSettings` maintenance.

If you need to bind the server explicitly, for example on Windows local use:

```bash
streamlit run gui.py --server.address 127.0.0.1 --server.port 8501
```

To stop the GUI, go back to the terminal running Streamlit and press `Ctrl+C`. If the GUI was started in the background, stop the Streamlit process from Task Manager, or terminate the corresponding Python/Streamlit PID.

#### 1. Auto trader  
parameter ACCT: account_name defined by users
```
python run.py -TASK auto_trader -ACCT YourAccountName
```

#### 2. Stock selection  
This task will run stock data crawler (using API) and then select stock. Details of establishing selection scripts see the [instructions](./trader/scripts/README.md).
```
python run.py -TASK update_and_select_stock
```

## Releases and Contributing
AutoTradingPlatform has a 7-day release cycle, any updates will be committed by each Friday (git commits are not included).


研究控制帳本固定保留在bootstrap/control-v1，不隨state-v1回退；因此還原舊資料不會重新取得已消耗的模型預算／保留集。整機移轉或重建仍需保留並查核控制紀錄，不能把一個新空工作區／機器當作從未研究過的樣本。舊版本帳本需要明確相容處理時會阻擋，不會偷偷重置。


## 0.1.2 接續驗收更新

- 新版使用完整版本化payload，校驗全部檔案後才更新捷徑，避免新舊DLL混合；異常更新可保留舊版並重跑安裝，詳見 `packaging/update_recovery.md`。保留/中斷payload會占用磁碟，不自動刪除任意資料。
- 備份必須存於工作區與固定MarkAuto應用資料夾之外，避免覆寫機密、帳本、鎖定與不可回退研究控制。
- 模型設定新增『JSON Schema：內建家族參數生成』。服务须支援該協定，不支援直接失敗，不偷偷改用fixture。預設相容模式與既有budget綁定保留。
- 已完成官方免費模型與真實12日行情的有限技術整合：一個策略虧損，兩個零交易，沒有可宣稱正式晉級的策略。完整失敗/限制列於 `docs/analysis/03_CODE_QUALITY_AND_RISKS.md`。
- Windows Release附無Python/Git需求的clean-client验收kit；詳見 `packaging/clean_windows_README.md`。無已授權乾淨Win10/11環境時依然EXTERNAL BLOCKED。
- 最新可下載版本以GitHub Release的實際資產與SHA256為準；此原始碼分支的變更不代表新安裝檔已發布。實盤繼續停用。

## 0.2.0 市場優先桌面（候選，驗收狀態見docs/agent/ACCEPTANCE.json）

沿用原生Windows桌面及既有TMF研究核心，增加加權指數/TX/MXF(MTX)/TMF真實日行情、本機歷史與明確時效、自選/蠟燭/成交量/多週期/技術指標、可讀表單與交易紀錄。一般模式不必手寫JSON；來源與hash保留在進階診斷。

- 官方更新需要使用者明確同意本次連線，離線可匯入官方格式檔；本機檔來源未經連線核實會標示，沒有假即時價。
- 新行情商品不代表已支援該商品下單/回測；研究交易核心仍限定TMF，實單停用。
- ChatGPT手動交換可匯出研究要求及匯入受限策略；來源記為manual_unverified，不冒充API實測。相容本機模型與付費API設定維持明確同意/預算/安全儲存，付費預設關閉。官方訂閱登入另行驗證，不複製Cookie或其他工具憑證。
- 新版需通過Windows打包與全部既有安全回歸才發布；clean Win10/11仍須獨立環境。

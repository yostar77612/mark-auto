# 多市場 v2 驗收證據

目前42項由本機測試快照驗證，A02/U03環境修補與U06原生驗收仍待完成，另5項需外部驗證。正式驗收維持 **230/300**。完整 test ID、來源位置、環境、資料/規則、預期與實際結果見 [ACCEPTANCE.json](ACCEPTANCE.json)。

## 證據範圍與版本

- 工作樹：C:/Users/mark.tsai/Desktop/markauto/multi-market-v2；分支 feat/multi-market-v2-local；基準 4095c3e9fdd2e91f1423d6d1bf76466834cdb417。
- 證據根目錄：C:/Users/mark.tsai/Desktop/markauto/multi-market-audit-20261025。JSON的artifact均相對此目錄。
- 初次本機完整輪次：185/185，failure/error/skip均0，Python 3.13.11、SQLite 3.54.0，執行期間source manifest不變。
- E07/少量UI後續有整合變更，上述歷史輪次已保存在trading-suite-185.json/.log，不是最終來源全通過的證明。其後202項來源快照已完成，但新發現的非LOCAL環境修補仍待下一輪exact-source驗證。
- 原v1 Paper22、Replay18全過，八來源、歷史profile與凍結journal對4095基準逐位元與Git blob相同。
- SDK1.7.9真正Order型別三市場進/退建構過，wheel SHA256為77c864aa5bcd0f873746cb10a55a484c7a38723df432a7778f328d5fb7f57be4。沒有初始化client、登入、CA或交易操作。

## 故障與專項

- combination-e06-native.log：父程序真正Popen.kill兩自有child；立即被原lease拒絕，未改DB或注入未來時鐘，自然等32.631秒才恢復。送前remote0保持UNKNOWN，收單後remote1經query為ACCEPTED；cash9870/risk668保留、重送0。
- combination-r02-native.log：UNKNOWN股票斷線且不能取消時，合法期貨保護仍ACCEPTED/真本機FILLED；日停與UNKNOWN預留保持。此組合曾抓出無關帳戶查詢擋保護的bug，修後單項通過。
- A03/H04新專項已單項過；E07真差異UI/commit scopeguards、U07三類真持倉同表、研究child慢退出案例均已加入最終runner，尚未取得完成報告，不先標通過。

## 50項逐列狀態

| ID | 狀態 | 實際結果與限制 |
|---|---|---|
| A01 | 已通過 / passed_tested_snapshot | 零禁止依賴；別名、動態匯入與TYPE_CHECKING反例會被拒絕，組裝例外明確限Runtime。 |
| A02 | 待實作 / nonlocal_fix_and_baseline_standalone_passed_final_source_pending | 共用三市場DTO、嚴格SDK形狀及只查核心通過；另真SDK1.7.9 Order型別建構不含session。 |
| A03 | 已通過 / passed_pre_environment_202_snapshot | 新增2412股期只供應Spec/歷史/quote資料，經原Facade建立→研究→部署→真本機進場成交→持有三交易日→退出；共用risk/fee及UI市場列無特殊分支。202輪具體案例通過。 |
| A04 | 已通過 / passed_tested_snapshot | 八來源、歷史profile與凍結journal對4095逐位元/Git blob相同；原Paper22/Replay18全過。 |
| A05 | 已通過 / passed_tested_snapshot | float/NaN/Infinity/naive時間/bool數量/錯單位與非法wire欄位均拒，沒有默默轉型。 |
| H01 | 已通過 / passed_tested_snapshot | 23日週五day0、26日day1，27日是測試休市，29日day3、11/2 day5；缺日曆拒絕。 |
| H02 | 已通過 / passed_tested_snapshot | 無當沖資格可現股跨日做多；當沖/先賣拒絕且未改原選擇。 |
| H03 | 已通過 / passed_tested_snapshot | 今日新買無合法退出時停新倉/告警；舊庫存可賣量不挪給今日新買，合法保護不受min阻擋。 |
| H04 | 已通過 / passed_pre_environment_202_snapshot | 同一期貨帳戶以明示本機margin1萬同持INTRADAY與SWING，收盤時當沖平倉、SWING仍1口，退出單只關聯當沖lot；202輪通過。 |
| H05 | 已通過 / passed_tested_snapshot | 新版本清研究資格，舊lot原政策；目的版本須驗證且對帳/無衝突單才可明確移交。 |
| H06 | 已通過 / passed_tested_snapshot | 拆股、股利應收、乘數/margin按生效版本重建；order hash不動，stop/riskbasis與歷史成本分開。 |
| H07 | 已通過 / passed_tested_snapshot | 實約月份/expiry必須吻合，adapter/UI未解析月份就拒絕，沒有猜近月。 |
| H08 | 已通過 / passed_tested_snapshot | 兩期貨市場close FILLED後才新版本研究/open；雙腿成本/UNKNOWN/崩潰可恢復，holding origin不延長。 |
| S01 | 已通過 / passed_tested_snapshot | 受限JSON經schema/白名單/型別/資源限制，才進隔離TRAINING研究與本機部署。 |
| S02 | 已通過 / passed_tested_snapshot | 程式碼/讀憑證/直接下單等多餘欄位及惡意草案拒絕，沒有副作用。 |
| S03 | 已通過 / passed_tested_snapshot | 規則或週期變更新版本/清證據；不能拿舊指紋跳階或改舊lot政策。 |
| S04 | 已通過 / passed_tested_snapshot | Domain及真研究child拒未可得bar，同根開盤偷看拒絕。 |
| S05 | 已通過 / passed_tested_snapshot | 無AI金鑰的確定性規則/停損/日停照常，優先停止不受研究阻塞；未宣稱真AI聯調。 |
| S06 | 已通過 / passed_tested_snapshot | AI摘要只來自策略DTO，無行情/帳戶/設定；OOS/FINAL_HOLDOUT context拒絕，v1來源隔離保持。 |
| R01 | 已通過 / passed_tested_snapshot | 單筆2%兩千包含雙腿費稅/滑價，按合法單位縮量或拒；3%只在明選後採用。 |
| R02 | 已通過 / passed_tested_snapshot | UNKNOWN股票斷線也不壓掉期貨合法保護；修後單項通過，UNKNOWN cash/risk仍保留。 |
| R03 | 已通過 / passed_tested_snapshot | 股票/期貨並行共用十萬，帳戶與策略cap分算，四萬現金不能負兩筆兩萬margin加成本。 |
| R04 | 已通過 / passed_tested_snapshot | UNKNOWN全額預留；partial取消僅放餘單、非線性最低費重算；退出不放未成交進場cash。 |
| R05 | 已通過 / passed_tested_snapshot | 未交割賣款不當cash；五合成交易日及重啟後，僅明示T+2轉已交割cash。 |
| R06 | 已通過 / passed_tested_snapshot | 2330股票與股期共用underlying額度，不以估計相關性互抵。 |
| R07 | 已通過 / passed_tested_snapshot | 缺margin、過期資格或估值不新鮮拒新倉；必須有版本FeeSchedule，不回退零成本。 |
| R08 | 已通過 / passed_tested_snapshot | 日停日期持久，重啟/改設定/盈利不清當日鎖；提交前重估既有虧損。 |
| E01 | 已通過 / passed_tested_snapshot | 同key同內容回原單、不同內容衝突，UNKNOWN不假設遠端沒收單。 |
| E02 | 已通過 / passed_tested_snapshot | 收單後斷線重建UNKNOWN、保留cash/risk，query後ACCEPTED且無重送。 |
| E03 | 已通過 / passed_tested_snapshot | 按帳戶去重；同id不同economics、終態復活、亂序/缺口隔離，補查不重算成交。 |
| E04 | 已通過 / passed_tested_snapshot | partial/取消/餘量成交競態保留真數量，取消不把lot清零。 |
| E05 | 已通過 / passed_tested_snapshot | 期限與保護同時觸發僅剩餘退出一單，已有預留不反向新開。 |
| E06 | 已通過 / passed_tested_snapshot | 父Popen.kill兩child，原lease自然等32.631秒；送前remote0仍UNKNOWN、收單後remote1查成ACCEPTED，均不重送。 |
| E07 | 已通過 / passed_pre_environment_202_snapshot | 真Facade/Qt顯local0、broker+2000股、sellable2000及外部SELL1口委託ref；不造managed lot、不准外部平倉；手機long→short差異與commit前未觀測反向也拒增加曝險。202輪通過。 |
| E08 | 已通過 / passed_tested_snapshot | 第二程序拒奪權，舊owner恢復仍被fence，無broker submit。 |
| E09 | 已通過 / passed_tested_snapshot | heartbeat/append故障停新倉；送前不碰broker，收單後保留SUBMITTING供重啟query。 |
| E10 | 已通過 / passed_tested_snapshot | 真還原舊SUBMITTING備份後強制對帳，遠端ledger不回退，舊隊列不補送。 |
| U01 | 待外部驗證 / passed_tested_snapshot | 六步精靈至真本機研究/部署/持有/退出/績效通過；真人理解測試未做。 |
| U02 | 已通過 / passed_tested_snapshot | 無當沖資格顯示原因/跨日選項，當沖選擇未偷偷改變。 |
| U03 | 待實作 / nonlocal_fix_and_baseline_standalone_passed_final_source_pending | 環境/帳戶明示，不可用外部環境不換別帳戶；交易能力拒絕與績效環境標籤分開。 |
| U04 | 已通過 / passed_tested_snapshot | stop/cancel/flatten/關UI/關engine命令不同；client退出engine存活，shutdown釋放handles。 |
| U05 | 已通過 / passed_tested_snapshot | 無資料不是零價，過期/斷線保留部位與影響，失敗訊息不被poll抹除。 |
| U06 | 待實作 / native_focus_harness_failed_replacement_and_dpi_pending | 1800秒負載在32.092秒因另一QA視窗使F5 WindowShortcut inactive而終止；3210/3210 quotes、p95 89.48ms、source不變及乾淨shutdown。待所有QA完成後獨占前景重做1800秒與native DPI，不改任何門檻。 |
| U07 | 已通過 / passed_pre_environment_202_snapshot | 真同時持有INTRADAY期貨空1口、SWING現股多、POSITION另一現股多；Qt三列逐一核對方向、單位、帳戶、day0與0/0、3/5、20/60退出窗。202輪通過。 |
| L01 | 已通過 / passed_tested_snapshot | 無API金鑰的三市場App/adapter循環通過，明示LOCAL synthetic。 |
| L02 | 待外部驗證 / passed_tested_snapshot | 本機只查拒交易與真SDK型別過，沒有真永豐帳戶查詢。 |
| L03 | 待外部驗證 / passed_tested_snapshot | 三市場欄位/事件本機與SDK型別過，沒有券商模擬session。 |
| L04 | 待外部驗證 / passed_tested_snapshot | 本機五日+重啟/交割/保護過，沒有真券商五日觀察。 |
| L05 | 已通過 / passed_tested_snapshot | metadata存在不授予當沖/CA/交易/正式能力，各條件獨立/有期限且預設拒。 |
| L06 | 待外部驗證 / passed_tested_snapshot | 預設不執行真交易、升級不自動啟用，本次沒有真實資產操作。 |

## 尚待外部驗證

- U01：三位獨立使用者或本人三新情境，確認模式、週期、資金與停止效果；自動操作不能代替理解。
- L02/L03：真正永豐唯讀查詢及券商模擬需使用者提供且授權的帳戶/API；替身與SDK型別不能代替。
- L04：本機五日已過，真正券商五交易日與重啟觀察另驗。
- L06：本次禁止真實資產操作；設定文件或開關不自行授予正式交易權限。
- U06：邏輯縮放/離屏不能冒稱native DPI；第一次30分鐘負載被中斷，舊RUNNING報告不是通過證據，需全新完整負載與實際畫面檢查。

接入欄位、資格來源、CA、版本與只查/模擬步驟見 [BROKER_READINESS.md](BROKER_READINESS.md)。

## 最新 native 負載節點（未通過）

- native-load-final-30m.json 已在32.092秒結束為FAIL；F5未派送到自己的Qt window，3210筆皆確認、p95 89.48ms、source不變、exit0與shutdown verified。
- 這是工具輸入焦點條件失敗，不能用3210筆短結果當180000筆/1800秒驗收；root會先修正工具或前景條件再建立新的完整負載證據。
- 只讀審核期間沒有修改任何production或測試來源。

## 202項快照完成，仍不是最終來源

- trading-suite-202.json/.log（已封存快照）：202/202，0 failure/error/skip，source unchanged，Python3.13.16、SQLite3.54.0；UTC 2026-10-24 23:45:49至23:52:09。報告SHA256 4b7f44f26638954ebc7cd4fd030a6b78ac7e8db71bea661a6c7d96f36d207d97。
- A03/H04新增組合、E07真Qt差異/反向scopeguards、U07三類真持倉、新成本/來源研究失效守衛與研究child慢退出全包含在這輪實際結果。
- 隨後review又找到非LOCAL exit/view硬編環境與獨立ports DTO registry缺口；A02/U03保持待修驗。新的controlled-nonlocal測試只有本機可故障port翻譯，不接真SDK，也不能代替L02/L03/L06。
- 必須保留這份202快照，再把環境修補後的exact-source全回歸接成下一輪，不能覆寫歷史報告後沿用舊hash。
- native負載失敗確認為root操作另一QA視窗致F5不活躍；下一輪會先完成其他畫面QA，再讓負載視窗獨占前景1800秒，所有時間/行情數/延遲門檻不變。

## 非LOCAL交易日與日風險基準（16項本機測試通過）

- broker-sessions-final.log：16/16，3.792秒。依版本日曆的已開DAY/明示NIGHT選交易日；UTC與市場時區同一時點得到同一結果，休市不猜weekday，夜盤預設關閉。
- 新交易日或基準缺失時保留原日dated locks、舊PnL與舊base，停止新風險並要求fresh對帳，沒有把未知前收盤或持倉估值當0。無基準時已知scope的合法保護依然可實際送出及本機成交。
- DailyBaselineEvidence綁環境、全configured accounts、前一明示交易日/目前交易日、calendar版本、fees版本及真值hash、精確前收盤as-of、可信source identity與固定v2 ledger net-mark估值軸；不是券商lifetime PnL、現金或一個metadata checkbox。
- 確認會再讀fresh account事實且要求持倉行情可估值，來源須由可信backend/provider白名單背書；public mutation以engine.lock序列化。確認後仍stopped，必須另外明確resume，不能清掉同日風控鎖。
- **真券商前收盤供應者及正規化尚待外部驗證**：本次沒有查真帳戶/前收行情/券商statement。不能因文件存在或metadata格式正確就宣稱日風險基準成立。取得實際唯讀權限後需證明同一v2已管理部位/費用/滑價軸的前收盤淨估值；未取得時保持nonLOCAL新倉停用。
- 本機16項與controlled nonLOCAL port測試通過，不等於券商唯讀/模擬/正式交易已驗證；L02/L03/L04/L06仍外部待驗。最終整合來源回歸仍由root接續。

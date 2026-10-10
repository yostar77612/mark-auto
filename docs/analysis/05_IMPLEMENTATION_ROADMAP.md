# TMF AI 研究平台實作路線與固定驗收

<!-- CURRENT_STATUS_START -->
## 當前整合狀態與最後已驗證基線（2026-10-10 10:33 UTC）

**以下分開記錄「最後已受測來源」與「其後未提交整合」。** remote `e68b33019a9ad21efa4b0786ca1020b9f12e862f`／local `46f6e04728caf08a9e94ed598c1e426b0121e944`為同tree `7227e0142b0520441e510c69a79dcaddabe7c411`。e68b3301兩個Windows core與原Paper30秒／generic40秒均PASS，但Quantlab仍有Linux312 FAIL與Win311 research CANCELLED，installer在AI下載階段FAIL；新WFO／observer／diagnostic／Qt打包整合尚未原生驗證。

- **公開下載仍只有0.2.1 unsigned preview。** [已核驗安裝檔與證據](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1)，release main `2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`；PR5已合併main94aca467，但候選0.2.2／PR6仍Draft、未合併／未發布。
- **最新Quantlab38042425646：8 PASS／1 Linux312 FAIL／1 Win311 research CANCELLED。** Windows311／312 core各1029項＝1014 PASS／15 skips、406.239／339.883秒；UI1256項＝1243 PASS／13 skips、290.850秒；Linux3111256項＝1238 PASS／18 skips、426.842秒。Linux3121256項＝1237 PASS／18 skips／1 failure、417.872秒，為test-only process observer的cleanup=false；另已真實觀測Linux X dead state並修補X/x契約，但原CI未留process-state artifact，exact cause仍NOT_PROVEN。Win312 research227項＝223 PASS／4 skips、764.237秒；Win311在原15分鐘cap前完成222項＝218 PASS／4 skips，第223項被中斷、4項未開始，不記整套PASS。
- **最新installer38042425591已FAIL，但已完成native全套與建置。** 原生1256項＝1237 PASS／19 skips、832.716秒，PyInstaller與兩個installer編譯PASS；AI download child於0.616秒exit1、非timeout、cleanup=true，未進frozen phase／0 model calls，其後install／lifecycle skipped。artifact11666369640 ZIP 83,451,533 bytes／SHA256 `b62c4e04edd9a3483f41f9a6d3701b83f7e6d8d8c320c4b04841af47e66c1d31`已下載核hash／CRC，5 members；0.2.2 installer 42,248,905 bytes／SHA256 `f7512490e8a7f5c07f456c7919ceb3b4e9db09f01325a172ca73127c75a8fd7a`，未發布。controller的`7600d5e8…672aaf6`是frozen app EXE hash，不能稱installer hash。證據：`quant-audit/ci-e68b3301/`。
- **新整合的本機證據分開記錄。** WFO single-normalization保留相同hash bytes、全部原COMMIT與SQLite語義；當次root全套1263項＝1248 PASS／15 skips、290.403秒，source manifest `quant-audit/wfo-single-normalization-root-source-20261010.json`固定該次來源，不認證其後host／observer／Qt delta。其後Linux observer focused31 PASS／66.977秒；AI child失敗證據保留修補focused107 PASS／1.293秒，只修parent讀取／去敏順序，底層download cause仍未知。KVM opt-in query程式43 PASS＋partition9 PASS，但無實際sudo／KVM query；錯拼test module的44項／1 import error原log保留。所有重疊集合不相加，原300／660／10／120／135秒、15／35分鐘cap與單次嘗試不變。
- **已知native元件風險與Qt打包修補尚待新產物。** e68b3301實際126個PE的audit確認Qt另名`-x64` OpenSSL3.5.5，涉及[官方2026-09-29公告](https://openssl-library.org/news/secadv/20260929.txt)的CVE-2026-35189（TLS記憶體DoS）與CVE-2026-84782（DTLS）。Python `_ssl`／`_hashlib`使用不同basename的3.5.9；未找到app QtNetwork／QSsl呼叫，不宣稱Python HTTPS受此漏洞影響或已遭利用。root已套用精確移除qopensslbackend／3.5.5 pair與unused VirtualKeyboard／PDF的打包規則，保留Python3.5.9、qwindows、Schannel／cert backend，補完整GPL／LGPL與固定native notices／source links。新frozen payload未建置，不能宣稱已移除、已完成授權交付或pip-audit PASS等於native安全。Qt root初次65項＝63 PASS／1 failure／1 skip、0.757秒，是6個新build inputs尚未Git追蹤的guard；僅stage後原樣重驗65項＝64 PASS／1 PowerShell skip、0.780秒（`quant-audit/qt-packaging-root-tracked-20261010.log`），未改test／product來消除該失敗。獨立126-PE審查無blocker、static／history0 findings；最後整合root Linux全套1311項＝1296 PASS／15 applicability skips、288.641秒、exit0（`quant-audit/integrated-root-full-20261010.log`）；`quant-audit/integrated-root-source-20261010.json`所列來源hash已核對一致。這是Python3.12.14／SQLite3.53.1／Qt6.12.0的完整本機證據，新exact-head native CI仍NOT_RUN，不認證新Windows frozen payload或clean client。
- **歷史0088b505／Quantlab38032142094為9/10 PASS、整體FAIL。** Windows3.11 core806項＝790 PASS／15 skips／1 failure、433.599秒，唯一失敗仍是原960-bar Paper30秒。Windows3.12 core806項＝791 PASS／15 skips、339.431秒；UI1026項＝1013 PASS／13 skips、366.894秒；其他Linux／research／security通過。窄Linux ESRCH與Windows nested cleanup已有此來源驗證，不能冒稱新WAL／runtime／AI整合已通過。
- **歷史0088b505／Server38032142096 build／security及安裝流程PASS。** Server2022完整1026項＝1007 PASS／19 skips、808.047秒，該profile原Paper30秒／SystemExit40秒、frozen/history/WFO、真0.2.1升級／中斷恢復／移除保存通過；PR release skipped。實際候選artifact11663227244、PR merge703686e2、60個source inputs及EXE／kit／ZIP hashes已驗證，與0088b505同tree；這不是Release，也不能抵銷Windows311失敗或替代clean client。
- **歷史16974db3／Quantlab38040818017已終態：7 PASS／2 Windows core FAIL／1 Windows311 research CANCELLED。** Windows311 core1023項＝993 PASS／15 skips／7 failures／8 errors、546.573秒；Windows312 core1023項＝994 PASS／15 skips／6 failures／8 errors、399.402秒。UI1250項＝1237 PASS／13 skips、331.067秒；Linux311／312各1250項＝1232 PASS／18 skips、422.830／421.385秒；Windows312 research227項＝223 PASS／4 skips、636.478秒。Windows311 research達原15分鐘累計job上限，被取消時stack在WFO `_save_state` 的 `db.commit()`，數秒前測試仍在推進；不據此宣稱單一commit死鎖或任意加時。
- **歷史16974db3／installer38040817985在freeze前FAIL，沒有新installer或frozen AI呼叫。** 完整1250項＝1217 PASS／19 skips／6 failures／8 errors、874.196秒，與Windows312 core共14個相容性反例；Windows311 core另有一個terminal-cleanup測試失敗。build未進入freeze／實際單次AI／安裝驗證，這些保持NOT_RUN；不能沿用0088b505舊artifact的PASS。原生日誌與終態證據保留於`quant-audit/ci-16974db3/`。
- **歷史16974db3後的11檔相容性修補與failure-only WFO timing診斷已root套用。** Linux Python3.12.14／SQLite3.53.1／Qt6.12.0整合focused183項全PASS、0 skip、51.275秒（`quant-audit/windows-repair-integrated-focused-20261010.log`），static／完整可達history為0 findings，diff check PASS。這是修補後focused，沒有第二次root完整全套或新native PASS；WFO尚未做效能優化，原30／40／10秒、15／35分鐘job及所有驗收門檻不變，接續同PR新exact-head CI。
- **先前本機證據與負面結果按來源保留。** pre-AI root完整1096項＝1081 PASS／15 applicability skips、291.408秒，log `quant-audit/pre-ai-wal-integrated-full-20261010.log`與source manifest `quant-audit/pre-ai-wal-integrated-source-20261010.json`固定該次來源。其後本機AI focused153項＝152 PASS／1 skip、5.866秒；自動備份初次focused21項全PASS、0.966秒；offline-drive設定恢復修補後23項全PASS、0.962秒。focused logs見`local-ai-integrated-focused-20261010.log`、`automatic-backup-integrated-20261010.log`及`automatic-backup-integrated-final-20261010.log`。該次root venv實測為Linux Python3.12.14／SQLite3.53.1／Qt6.12.0，見`quant-audit/integrated-final-source-20261010.json`；早先手記Qt版本不作獨立量測證據。最終combined suite本次FAIL：1243項＝1225 PASS／15 skips／2 failures／1 error、300.720秒（`quant-audit/integrated-final-full-20261010.log`）。三項均為saved-candidate producer來源綁定未涵蓋provider hook變更後的source hash；現有fail-closed防線正確拒絕未匹配來源。兩個新的literal 0_2_2 transport-verifier profiles已獨立審查並root套用；原三個literal profiles與historical exact-hash測試未改，只將三個真正current-generated identity assertions移至新profile，tamper／mixed-source拒絕保留。修補後root focused150／150 PASS、0 skip、30.760秒（`quant-audit/provenance-integrated-focused-20261010.log`）；隔離54與138項PASS為重疊範圍，不相加。本次1243項FAIL保留，沒有第二次root完整重跑；其後16974db3原生終態另列於上方；不追溯改寫本次1243項FAIL。另`/usr/bin/python3`私有SQLite3.54.0載入probe及Paper111項＝110 PASS／1 skip、5.172秒屬獨立Linux範圍，見`/tmp/markauto-sqlite354-verified-setup.log`、`/tmp/sqlite354-paper-tests.log`。各集合不相加、不互相認證；目前root全套不是3.54或Windows證據。
- **免費本機AI已接入普通GUI，實際新推論仍NOT_RUN。** 可選llama.cpp／Qwen2.5-1.5B路徑使用官方固定hash runtime／model／support DLL來源；無付費fallback，official API預設off。localAI licenses與三個Microsoft DLL來源通知已補入packaging；實際frozen bytes／未修改DLL另行再散布依據仍REVIEW_PENDING，未作非法判定或全部授權已清結論。e68b3301 supervisor已執行，但download child失敗使frozen phase／模型呼叫未執行；mock、歷史14次呼叫或focused PASS均不能替代新路徑證據。
- **每日自動備份與審查修補已root套用，最終驗證仍待。** 預設off，開啟後app運作且所有manager閒置才嘗試，每UTC日最多一次；7份／2 GiB上限、連結保護、不自動刪檔或還原。獨立審查指出舊共用備份可經regular-file hardlink納入外部內容；共用BackupManager的hardlink拒絕已套用並包含於21項focused PASS。移除式磁碟離線時停用／更換目的地的設定恢復亦已修補，root focused23 PASS；最終combined／native未驗，不能宣稱漏洞或整項已完整閉合。
- **耐久與門檻不降級。** 舊來源同960 bars診斷worker35.562622秒，960次FULL cursor commits30.6026735秒，UI35.937秒；瓶頸位於耐久寫入路徑，物理原因未知。16974db3及最新e68b3301使用實際SQLite3.54.0／WAL／FULL，原960 bars／30秒測試已在Windows311／312 PASS；host為Windows Server2025，不能當clean client PASS。仍保留原per-bar耐久／帳本identity／風控與30秒、40秒、process-death10秒、job預算，不減bar／commit、不搬TEMP。不再無變更重跑湊綠，但經審查的新實作必須原生重驗。
- **執行責任與AI優先順序已更新。** 依使用者最新授權，assistant承擔工程、環境調查、可合法執行的設定與驗證，不預設把VM、測試或GitHub設定交給使用者。免費本機AI為主；官方API只是可選路徑、預設不呼叫，不暗中使用付費或借用其他工具帳戶。零費用、零真資金交易及原驗收門檻保持。不可代行的帳戶、license、明示條款或持久權限，只提出精確最小確認，不包裝成整套技術作業。
- **外部證據如實保留。** 目前没有已驗證且已授權的零費用clean Win10/11 x64完整路徑；Win10／Win11官方EnterpriseEval x64媒體均可達，actual bundled EULA已以bounded ranges取出並核對檔案digest；full ISO hash、hosted-use涵蓋、registration／activation及owner接受尚未闭合，沒有Windows安裝／執行。opt-in KVM query只查API／capabilities、不create VM或改權限，程式已套用但真query仍NOT_RUN；offline CI設計是提案，不是授權。GitHub nested guest仍待資源／license／執行證據。SignPath僅可準備免付費申請材料，尚未獲接納。08:18只讀查核rulesets=[]、main保護仍未啟用；GitHub App無Administration scope，先前403未解除，換CLI／GraphQL／workflow token不會增加權限。實際服務、TAIEX盤中權利、clean client不以mock／Server替代。
- **原始匯入來源已有範圍明確的證據。** 原import `1cacce4ee4eef4ce7e8760f8153ef64a74852d22` 的47檔，其Git mode／type／blob全部與官方upstream `chrisli-kw/AutoTradingPlatform@a0ecf8895716bf5883184fdd27a52023f9700bf3`相同；upstream共49檔，另有`trader/APItest.py`與`trader/performance/backtest.py`未在該import。這證明47檔內容對應，不證明整棵tree／完整history相同，也不是維護者owner attestation；Apache LICENSE與Li Kuei-Wei署名保留。
- **210/300＝70%、M4 PARTIAL不變。** e68b3301兩個Windows core／原Paper30秒PASS，但Linux observer失敗、Windows311 research取消、AI下載失敗及native payload風險閉合仍阻交付；其餘外部條件分開列示，不能把餘項全說成external。Oct8 WFO仍BLOCKED_NO_RUN，170 consumed bars、0新評估／model calls／reservation；不改window／registry。原需求、權重、失敗與歷史不重寫。

### 原需求、設計提案與未驗證項目

- **本輪已明確必要的原需求：** Walk-forward，以及使用者原文 §5.1 的 Profit Factor／Sharpe、§3.4 的停損／停利／持倉成本參考線；已合併及PR階段PASS不等於postmerge／已發布交付。
- **尚未採用的完整目標設計延伸：** 04 §9.1 提出的 Average Trade、Sortino、Calmar、延伸分解與成本壓力測試保留為提案。02 歷史原文已明示「若最終採用該完整規格」；未取得使用者直接要求這些延伸的原始證據，因此不把設計表的「必須公開的計算與例外」升格為本輪新增驗收門檻，也不刪除提案。
- **尚未驗證的結果：** 修補後完整CI／發布、clean client、真實授權與真實研究各依目前證據判定；未驗證不表示功能未實作，設計提案未採用也不等於本輪驗收失敗。

## 目前接續順序與依賴

| 步驟 | 要完成的結果 | 前置／保持不變 | 完成判準與未達成時處理 |
|---|---|---|---|
| 1 關閉已知native元件與整合gate | Qt3.5.5 advisory／unused Qt排除與完整notices已root套用；WFO single-normalization、observer及AI診斷各有本機證據 | 全部COMMIT、hash bytes、原960bars／30秒、40／10秒及job cap不變 | 新exact-head full／native，檢查actual frozen payload／retained TLS與source資產；沒有新產物前不宣稱移除或安全閉合 |
| 2 驗證免費本機AI與備份普通流程 | GUI本機AI與預設off每日備份已套用；focused153／23各自通過 | 官方固定hash、loopback、有限budget；備份全manager閒置、連結拒絕、7份／2 GiB；零費用、無實單 | e68 download child失敗、0 calls；保留去敏診斷，接續新exact-head實際單次AI／lifecycle，不用mock／歷史結果補PASS |
| 3 自主準備環境／權限路徑 | assistant持續承擔host調查、合法client方案、SignPath與protection方案 | 無已驗證免費Win10/11 x64；App無admin；provider／license／條款各有不可代行邊界 | 僅需帳戶持有人決定時精確確認，不把整套VM／測試／GitHub設定丟給使用者；不繞權限、不新增費用 |
| 4 處理真實資料研究限制 | 保留 Oct8 BLOCKED_NO_RUN 與既有負／零交易結果 | 原 protocol、完整 guard、170 consumed bars、既有 authoritative registry | 不執行被阻擋研究；不改 windows／fresh registry。只有另有符合原規範的資料及預宣告才可另開研究，零新呼叫是目前正確停止結果 |
| 5 完成合法外部驗收 | clean Win10／Win11／DPI、實際 ChatGPT grant／推論、TAIEX 盤中權限 | 使用者授權、合法環境與來源，無付費／權限／警告繞過 | 各項單獨提供真證據；未提供時保持 EXTERNAL_BLOCKED／NOT_VERIFIED，不用 Server 或 mock 補分 |
| 6 最終交付／同步 | exact commit／tree／CI／Release／asset hashes 與功能狀態一致 | 保留原始 Git 歷史、需求／權重及失敗；發布須在授權範圍 | 解除postmerge失敗後核對真正Release／實際下載；更新本頁摘要、02／03、PROJECT_STATE 與 ACCEPTANCE 當前區段，歷史不反向改寫 |

0088b505的Paper30秒失敗照原來源保留；16974db3兩個Windows core的原960 bars／30秒均PASS。接續同hash bytes／全COMMIT的WFO single-normalization與observer／AI診斷／Qt打包之新exact-head原生驗證，不改CI gates，不以單項成功抵銷整體FAIL／CANCELLED。

### 最後已驗證0088b505的CI分項（不認證當前整合）

| Profile／run38032142094 | Total | PASS | SKIP | FAIL | 秒 |
|---|---:|---:|---:|---:|---:|
| Windows3.11 core | 806 | 790 | 15 | 1（原Paper30秒） | 433.599 |
| Windows3.12 core | 806 | 791 | 15 | 0 | 339.431 |
| Windows3.11 research | 220 | 216 | 4 | 0 | 755.447 |
| Windows3.12 research | 220 | 216 | 4 | 0 | 592.822 |
| Linux3.11 | 1026 | 1008 | 18 | 0 | 327.405 |
| Linux3.12 | 1026 | 1008 | 18 | 0 | 394.240 |
| UI | 1026 | 1013 | 13 | 0 | 366.894 |

Static／security／audit jobs亦通過。全部10個required jobs中9個PASS；Server38032142096另列，不把Server的1007 PASS／19 skips拿來抵銷Windows3.11失敗。

### 自主接續計畫與不可代行的邊界

1. **固定整合來源後重驗原gates：** e68b3301兩個Windows core已PASS；Linux312 observer失敗、Win311 research取消及AI download child失敗仍保留。root已整合WFO single-normalization、test-only observer、失敗證據診斷、opt-in KVM query及Qt notices／精確payload exclusions。1263項全套只屬WFO delta當時來源，後續focused不相加；新exact-head完整CI、frozen AI與installer lifecycle仍待，所有原gates不變。
2. **保留原持久語義：** WAL候選需逐個原邊界COMMIT＋FULL、無外包整段transaction／降級NORMAL或OFF，既有mutex、cursor／pending plan／stable IDs不變；broker DELETE／FULL仍分開。SQLite版本／官方hash／native載入來源、local filesystem、舊版本workspace拒絕及DB／WAL／SHM備份恢复都須有實證；guard已用精確0.2.1 source fixture證明startup／schema2 archive拒絕；實際舊EXE拒絕測試程式已加入但尚NOT_RUN，仍需原生結果。備份hardlink修補與移除式磁碟離線設定恢復須完成最終整合回歸。這是必要待驗證清單，不是完成宣告。
3. **驗證免費本機AI普通流程：** GUI管理的可選llama.cpp／Qwen2.5-1.5B已整合，官方runtime／model／support DLLs固定hash，loopback、有限budget與輸出驗證保持；一般使用者不需手寫JSON或自行架服務。下一證據為同來源native frozen實際單次呼叫及乾淨終止，不以153項focused、mock或歷史llama.cpp／Qwen呼叫代替；e68b3301在download phase失敗，因此此新模型呼叫仍NOT_RUN；新增diagnostic不代表底層cause已修好。官方API可選、預設off，不設付費fallback；M6與其餘原權重／狀態本次不改。
4. **Windows驗證由assistant持續承擔：** 已授權標準public GitHub runner可提供Server證據；先做只讀host能力／磁碟調查。Nested x64 guest在GitHub官方文件中是實驗性、無保證路徑；需實際可用加速／資源、合法精確Win10 22H2／Win11媒體及所需license／條款確認。此cloud shell目前無現成KVM／VM工具，不代表免費虛擬化普遍不可能。Win10／Win11官方EnterpriseEval x64媒體均可達，actual bundled EULA已以bounded ranges取出並核對檔案digest；full ISO hash、hosted-use涵蓋、registration／activation及owner接受尚未闭合，沒有Windows安裝／執行。opt-in KVM query只查API／capabilities、不create VM或改權限，程式已套用但真query仍NOT_RUN；offline CI設計是提案，不是授權。退役evaluation landing page不等於媒體撤回；Windows11 ARM、Server或未授權Azure試用均不可冒充目標client；不繞TPM／Secure Boot／啟用限制、不預設使用者需準備VM或跑測試。
5. **保護與簽章保持誠實：** assistant準備main protection精確所需scope／規則與可行路徑，現有連線缺Administration則只停在該操作，不反覆撞403、不換transport冒充授權，也不索取聊天中的token。SignPath可先準備真實申請草稿；47檔upstream內容對應已驗，但完整lineage／維護者權利陳述、打包界線與metadata／政策仍需分別補證；OSI授權、MFA／角色、來源到binary及每次release核准仍待確認。外部提交、帳戶／條款、GitHub App或簽章persistent access須個別具備所需授權；不買付費簽章、不保證免SmartScreen。
6. **保留每次結果：** 舊0088b505的806core／220research、9/10與同工作量diagnostic作為固定比較；新來源完整清單與依賴另行記錄。全部PASS／FAIL／ERROR／SKIP、elapsed、source／runtime hashes、OS／volume、cursor／orders／fills與清理／恢復證據保留；不按結果追加無變更重跑，不將別台host PASS寫成失敗CI已通過。

本計畫亦依據`windows-eval-terms-and-offline-ci-20261010.md`、`openssl-security-e68b3301/payload-pe-tls-inventory.json`與`qt-notice-proposal/REVIEW.md`；其餘既有查核：`windows-environment-options-20261010.md`、`signpath-eligibility-20261010.md`、`github-protection-options-20261010.json`。可用方案、授權缺口與推論分開；不新增權重、不把準備材料算成外部已通過。

## 固定驗收與必要需求對照

| 清單／必要工作 | 現存記錄 | 當前應如何解讀 |
|---|---|---|
| Phase 0–5 | 100/100，按當時固定工程子項證據 | 原條款全文保留；不外推至其後重核的完整 WFO／統計規格或真市場 readiness |
| D0–D9 | 70/100；D5／D7／D8 各 10 未接受 | clean client 門檻原封保留，不因 toolkit／Server 可執行而 PASS |
| M1／M3／M5 | 20＋15＋5＝40/100 | 只接受原限定功能與證據；不補 M2／M4／M6／M7 |
| M2／M4 | PARTIAL，0 分 | 原完整市場／普通流程要求保留；已合併／候選實作不等於交付；最新仍有Linux312失敗／research取消／AI下載失敗／lifecycle未驗，M4不加分，M2完整TAIEX分鐘範圍仍未閉合 |
| M6／M7 | PARTIAL，0 分 | 官方訂閱 source/native 工程已交付，但實際 grant／inference 未測；最終 clean Windows DPI 未測 |
| WFO 重新核對要求 | 已合併未發布；e68 Linux311／UI／Windows312research通過，Linux312失敗、Windows311research取消，WFO修補待新native | 一次四段 OOS 不是 WFO；固定／保存池仍非 adaptive 生成／改善，也不證明真實未見性；設計提案界線不變 |
| PF／Sharpe／停損停利／成本參考 | 已合併未發布；普通繁中呈現與參考快照已涵蓋PR完整1016，postmerge失敗待修 | 使用者原文§5.1／§3.4要求；定義／null原因／普通接線已經PR原生驗證，但postmerge與發布尚未通過；不因此自稱研究獲利 |
| 完整報表設計延伸 | Average Trade／Sortino／Calmar／延伸分解／成本壓力測試尚未採用 | 來源為 04 §9.1 設計提案；02 舊文有條件採用說明。保留提案及未提供狀態；無使用者直接要求證據，不加成本輪驗收阻塞，也不自稱已完成 |
| 歷史總帳 | **210/300＝70%，90 點未接受** | 非工時、投資認證或完整需求證書；不新增權重、不更換分母來美化結果，必要缺口仍阻交付 |

### 每次狀態更新只改這些當前欄位

記錄 UTC 時間、released main/version/tag、candidate remote/local/tree、每個必要 job 的真正終態、完整 suite 的 total/pass/fail/skip 與環境、release-blocking 反例是否對最後 bytes 重測、隔離模組是否實際整合、外部阻塞及原固定分數。下方歷史只新增真正新證據，不再整段複製前頁摘要；ACCEPTANCE 的舊 gate／失敗證據不能用舊整份副本覆蓋。


### 歷史檢查點：04:24 整合來源 Gate（當時狀態，不是目前待辦）

- 候選修補完整 Linux root suite：773 項，758 PASS＋15 個既有 native Windows／PowerShell applicability skips，127.279 秒、exit 0；歷史掃描 0 findings。涵蓋 smoke 終態、canonical fixture 與 FULL 設定失敗關閉連線，SQLite mode／耐久邊界／既有門檻不變。此結果取代上文針對較早來源的「最終 root 待驗」，原生 exact-head CI 仍待。
- Qt CI-only 相容鎖及獨立 Linux311 套件稽核已納入 workflow；官方來源、完整 SHA-256、強制重新安裝及 pip report 保留。Windows 產品依賴鎖不變；套件 advisory audit 不等於所有 native library 已安全認證。
- 後續 WFO／報表 combined staging 完整 947 項：932 PASS＋15 既有 applicability skips，270.314 秒。再套用同一 Paper 連線小修補後 5 項 storage regression PASS；仍非已發布或 Windows／真實研究驗收。


歷史驗證位置補註：較早981項在隔離候選執行，25檔按manifest複製；不是最後root全套。12e088f的1000項失敗／cancelled與05:32局部18／33／85項屬先前checkpoint；其後06bcc3a的完整PR1016已通過，但94aca467 postmerge又出現上列兩種timeout。所有來源、平台及計數分開，不相加或追溯改寫。


最後受測PR #6 head e68b3301／local46f6e047／tree7227e014整體未過；兩個Windows core及原Paper30秒／generic40秒PASS。其後整合只有各自來源的Linux full／focused證據，新native仍待；0088b505、16974db3、1243項root與e68失敗均保留，210/300不變。

<!-- CURRENT_STATUS_END -->

## 歷史原文與逐次證據（依原記錄保留）

以下完整保留本次整理前的內容、要求、來源、失敗與各時點判定。內文即使寫「目前／最新」，也只屬原有日期快照；現在的交付與下一步以本檔最上方有日期的摘要為準。原始基線盤點、固定驗收條款與年代順序均未被當成新版本成功證據。


建議採方案 C 的有界版本：保留 Python、Streamlit、既有授權、操作經驗與可抽取公式，新增與舊交易樹隔離的最小研究核心。先完成本機行情到策略比較的可重現閉環，再驗證 paper 恢復；真實模型、真券商與實盤各自設外部就緒條件。

本路線提供可交給工程 Agent 接續的工作契約與停止標準。原始基線為 `1cacce4ee4eef4ce7e8760f8153ef64a74852d22`，查核日期 2026-10-09。原始分析已完成，後續自主實作進行中；本文的要求不是對未完成項目的成功宣告。

## 1 目前狀態與不可混用的進度

截至 2026-10-09 16:18 UTC，固定開發清單 Phase 0–4 已登記 PASS，合計 **85%，剩餘 15%**。唯一計分來源為 [ACCEPTANCE.json](../agent/ACCEPTANCE.json)，本段為時間快照。

- 完整本地測試 176 PASS、0 SKIP，包括 5 個 Streamlit AppTest；真模型、實盤與長期無人值守不在此結論內。
- 舊交易入口刻意停用；新研究、版本比較及 Paper 故障測試已實作，最終交付 Gate 待 fresh-checkout、安全複掃與遠端 CI。
- 官方 2026-10-08 CSV／RPT 已匯入 1140 根分鐘 K 並比對 OHLC；成交量差異保留價差單口徑限制，原始行情不提交公開 Git。
- 新增安全 refresh CLI，已實際下載官方公布的下一交易日期 2026-10-12 檔案；標記 provisional_unverified，不能當完整盤或正式排名依據。
- GitHub 新授權已驗證 Git 物件／分支／PR 寫入；[PR #1](https://github.com/yostar77612/mark-auto/pull/1) 尚未合併。Git CLI 無登入，支援的 GitHub 連線採同 tree 的新提交映射發布，保留所有原本本地提交。
- wheel／sdist 建置曾通過，需重驗最終版本；Windows CI、實際模型、券商認證與完整歷史資料均分別驗收。

原分析任務的六階段權重為 25／25／15／15／15／5，只衡量調查與文件；目前開發 Phase 0–5 採 15／15／25／20／10／15。兩者是不同分母，不合併、不挪用原分析進度當新功能完成率。測試個數與投入時間都不能直接換成百分比。

## 2 原始系統到目標的差距

| 領域 | 原始基線 | 必要新成果 | 優先度 |
|---|---|---|---|
| 安全開發 | 匯入連動 broker／DB，TLS、Telegram、log 有已確認缺陷 | 舊危險路徑停用／修復，研究不具交易能力 | P0 |
| 市場資料 | generic KBar／crawler，缺歷史 calendar／manifest | TMF 明確月份、日夜盤、品質與授權、不可變快照 | P1 |
| 回測 | `reports.py` 匯入不存在的 backtest | causal engine、ledger、cost／margin／expiry／roll golden | P1 |
| AI 研究 | 無 provider、DSL、campaign | 五家族、有限 DSL、generate／improve、預算與全部 trials | P2 |
| 可靠評估 | 無 walk-forward／OOS／holdout 控制 | 凍結 split、purge／embargo、一次 holdout、版本化結果 | P2 |
| 策略庫與 UI | 動態 Python hooks 與交易操作 GUI | immutable registry、可追溯報表、比較與人工選擇 | P3 |
| Paper 恢復 | 局部模擬記帳，共享可變狀態 | durable journal、冪等、風控、unknown 阻單、故障對帳 | P4 |
| 正式執行 | 舊 Shioaji 路徑，無台新／兆豐適用性認證 | 正式 broker capability、權限、恢復演練與獨立核準 | P4 外部 readiness |

關鍵證據：[broker 預設](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/config.py#L14-L16)、[匯入副作用](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/__init__.py#L16-L26)、[缺少回測核心](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/reports.py#L18-L18)、[成本／TMF 問題](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/performance/base.py#L69-L81)、[動態策略耦合](https://github.com/yostar77612/mark-auto/blob/1cacce4ee4eef4ce7e8760f8153ef64a74852d22/trader/utils/strategy.py#L6-L45)。完整對應見 [02 功能表](02_EXISTING_FEATURES.md)及 [03 風險表](03_CODE_QUALITY_AND_RISKS.md)。

## 3 方案 A B C 比較與決策

| 方案 | 優點 | 缺點及主要風險 | 開發成本 | 維護成本 | 重做範圍 | 適合程度 |
|---|---|---|---|---|---|---|
| A 保留原架構直接擴充 | 早期 UI／下單範例多，短期改檔少 | 研究依賴 broker／DB 與共享狀態；缺失 engine 仍得新增；容易以模擬旗標誤當隔離 | 表面低，後期耦合排除高 | 高，跨模組回歸難 | 在原樹補 calendar／回測／AI／版本管理 | 不建議作研究主架構 |
| B 保留核心局部重構 | 沿用更多類別，逐段抽介面 | 需先對 live-oriented 基底大量拆依賴；無測試使「保持原行為」難證明 | 中高，先重構再產出閉環 | 中，取決於是否真正消除父套件副作用 | 修改 config／executor／state／storage，同時新增研究 | 未來 adapter 抽取可用，本次不是最短路 |
| C 保留可重用功能並建立必要核心 | 清楚安全邊界，可離線 fixture 驗收；不必先恢復所有股票／broker 功能 | 需維護新舊邊界、部分概念暫重複；若範圍失控會變全面重寫 | 中，新增範圍可限在缺失核心 | 研究低至中；legacy 另有負擔 | sibling quantlab、data／engine／DSL／registry／paper，薄 UI | **本次建議** |

選 C 的原因是原基線沒有可直接保留的完整研究核心。新增 engine 並非替換一套已經驗收的 engine；隔離能省去先修完整 broker stack 的成本。保留 `trader` 作來源參考與可控遺留區，保留 Apache 標示、Python／Streamlit、公式與操作知識；純化後的小型函式可逐步重用。

明確不做：為了新架構整庫改名、重寫全部股票／選擇權、另造前端／API 微服務、為可能的效能問題換語言、先建分散式研究平台。所有新增技術需由可測瓶頸或已確認功能需求支持。

## 4 第一版 MVP 的可交付閉環

### 4.1 必備內容

1. 本機已合法取得的官方格式資料與合成 fixture，明確 calendar、contract、cost／margin；匯入品質報告與不可變 hash。
2. 因果 bar 回測：多空、日夜盤／跨日、明確 roll／settlement、next-event 成交、費稅／滑價、風控與逐筆 ledger；不支援情境失敗關閉。
3. 五個真正不同的策略家族及 trigger fixtures：趨勢、均值回歸、通道突破、動能、波動壓縮擴張。
4. 受限 DSL 與離線 FixtureGenerator，完整 generate→validate→evaluate→improve→freeze→OOS／holdout 流程；真模型另有可配置但預設停用的 provider boundary。
5. 15-trial 上限、兩次改善上限、持久預算與所有嘗試紀錄；重啟不重開預算，不反覆使用同一未見測試區間。
6. Streamlit／CLI 同服務層，能看品質、策略、帳本、成本、比較與選擇不可變版本；保留資料及模型來源標示。
7. 離線單元／golden／整合／安全測試、操作文件及版本 manifest。

這定義的是**研究 MVP**。合成／fixture 路徑可證明工程闭環，不能被改稱「真實 AI 已找出可獲利 TMF 策略」。真模型呼叫與足夠、授權完整的市場資料未驗證時，該部分維持 NOT_VERIFIED／BLOCKED。零候選達績效門檻不代表平台實作失敗。

### 4.2 MVP 後立即相接的交付

PaperBroker 持久恢復是本次整體開發的後段，與研究 MVP 分開驗收。加入 intents、事件 journal、risk／stale／margin、kill switch、對帳及故障回放後，才有資格討論前瞻模擬觀察。真實 broker 開通、帳戶簽署、付費資料／模型與真金交易不包含在工程百分比，也不能自動啟用。

### 4.3 明確延後

完整 tick order-book／queue 模擬、機器學習／深度學習訊號、自動投資組合配置、分散式搜尋、遠端多使用者角色系統、即時付費行情、向量資料庫、Kubernetes、broker Windows bridge 與無人值守生產服務，均等核心資料／帳務／恢復及需求明確後再評估。

## 5 最小工作包與依賴

以六個可交付模組工作包安排，不拆數百個微任務。優先度 P0–P4 指產品順序；Phase 是固定計分階段，兩者不混用。

| 包與優先度 | 用途／為何需要 | 基線與可重用內容 | 修改範圍 | 依賴與風險 | 固定交付與驗收 |
|---|---|---|---|---|---|
| W0 安全基底 P0 | 讓開發不會觸及真交易／秘密，建立可測邊界 | 舊 runtime 技巧、風險發現；沒有可信離線入口 | 安全封鎖、`quantlab` 純入口、tests／CI／packaging | 無前置；風險是遺留入口仍可繞過 | R01–R05 關閉或停用；拒 broker／網路／秘密；測試可追蹤；CI 最小權限 |
| W1 資料與契約 P1 | 同一策略用同一資料與歷史規則 | 原聚合／欄位僅參考 | `core.py`、`data.py`、data／core tests | W0；calendar、schema、license 不完整 | 本機官方格式＋quality；session／expiry；hash 不變；缺覆蓋拒絕 |
| W2 回測與帳務 P1 | 可信計算先於策略搜尋 | 指標／圖表概念可抽取；backtest 缺失 | `strategies.py`、`backtest.py`、golden tests | W1；時間與費稅錯誤會污染所有研究 | 五家族因果觸發、long／short／cost／roll／MTM／expiry golden；三次同 hash |
| W3 AI 研究 P2 | 把生成與改善變成有限可追溯實驗 | 基線無對等能力 | `research.py`、DSL／campaign／provider tests | W1–W2；洩漏、過擬合、超預算 | 15 trials、schema 拒絕 corpus、generate／improve、all attempts、隔離 OOS／holdout、真模型來源誠實 |
| W4 報表與版本選擇 P3 | 使用者能理解並選擇多策略 | Streamlit／Plotly 使用概念 | `reporting.py`、`research_app.py`、`__main__.py`、UI／CLI tests | W1–W3；指標誤導、重複按鈕與版本覆寫 | ledger 可追溯、不可變 registry、empty／error／rerun、restart；選擇不下單 |
| W5 Paper 與交付 P4 | 故障時不重複單且能恢復 | 舊訂單／部位概念，僅參考 | `paper.py`、risk／recovery tests、文件、最終驗收 | W0–W4；unknown、資金差異、偽實盤就緒 | 持久 journal、fault matrix、stale／margin／daily-loss、disabled live、完整最後版本驗證 |

最短依賴鏈是 W0→W1→W2→W3→W4。W5 的 pure risk／journal 可在 W1 interface 凍結後平行開發，最終整合須等待策略／report identity 穩定。文件與官規研究可平行，但不能以文件完成補足 code gate。

## 6 固定 Phase 0 至 5 驗收

每個 Phase 有五個等權子項。只有帶可重現證據的 PASS 得分；FAILED、BLOCKED、NOT_RUN 為零。Phase 全部強制子項通過才能宣告該階段完成；安全失敗獨立否決 release。不得因績效不好、花費超時或測試難寫而降低原門檻。

| Phase 權重 | 五個固定子項 | 必留證據 |
|---|---|---|
| 0 審查與架構 15% | 來源與 SHA；完整可達歷史安全掃描；依賴／入口；模組責任契約；固定驗收清單 | 固定程式連結、掃描範圍、限制、contracts／acceptance |
| 1 安全工程 15% | 舊路徑修復／封鎖；純匯入無秘密／網路；獨立測試入口；離線 CI 設定；防護回歸 | 測試命令／結果、source diff、CI permission 與語法；遠端 CI 狀態另列 |
| 2 資料與回測 25% | 官方 local schema／quality；calendar／expiry；因果 engine／ledger；cost／獨立 golden；manifest／三次重現 | schema 樣本來源、品質差異與口徑、手算 expected、結果 hash、因果負向測試 |
| 3 五策略與 AI 20% | 五種不同因果策略；DSL 拒絕 corpus；generate／evaluate／improve 與 provider provenance；持久預算及 all trials；OOS／holdout 隔離與 consumed marker | 所有候選／失敗、budget counters、注入與timeout測試、split hash、禁止存取證據 |
| 4 UI 與版本庫 10% | Streamlit import→run；不可變比較／選擇；指標與匯出追溯；empty／error／重複操作；重啟持久化 | AppTest／操作路徑、檔案 hash、CSV 安全、結果重載、選擇未觸發交易 |
| 5 Paper 與交付 15% | journal／冪等／恢復；故障及風控；實盤停用／安全複掃；五文件／操作維護；最終全測試／UI／fresh-checkout／CI 重現 | fault traces、持久對帳、最終 commit／env、實際測試與發布限制 |

明確分開四種判定：

- **工程 gate：** 正確完成規格與保護，無候選勝出也可通過。
- **研究 gate：** 預先固定的成本後 OOS／風險／統計標準；目前不能擅自填入獲利目標。
- **Paper gate：** 正確性故障測試與前瞻模擬觀察各有證據，後者期間／事件數需先固定。
- **正式就緒 gate：** broker／帳戶資格、行情 license、認證、風險限額、恢復、操作人與核準。即使達到，也不賦予工程 Agent 真實交易權限。

## 7 測試與重現的最低證據格式

每次可驗收變更附：目標版本、修改檔案、接受條款 ID、測試命令、Python／OS／依賴版本、退出碼、PASS／FAIL／SKIP 個別原因、input／expected／output hashes、未驗證範圍與回退方式。不能只寫「測試正常」。SKIP 的強制驗收項不得得分。

Golden 覆蓋：多空／部分成交／費稅、signal lag、gap／同根衝突、跨夜／到期／假日、roll／每日與最終結算、缺資料／半 tick／margin 拒絕、三次重現。風控不變量與非法狀態轉移需負向測試；每個已確認缺陷先有 regression fixture。變更 expected 必須寫清原因，不能批量更新以掩蓋錯誤。

外部資源全禁止的核心 test 與需要本機選用 Streamlit 套件的 UI test 分層；UI 套件有無安裝不應影響核心匯入。CI 不登入 broker、不持有交易 secrets、不下載付費資料、不呼叫模型；下載安裝依賴與「測試執行時無網路」是不同階段，需在 runner 明確區分。

最終版本需要重新跑完整 suite、CLI demo、合成 campaign、結果重載、UI empty／error／rerun、paper restart；另外從乾淨 checkout 在宣告支援環境重跑。已通過的較早版本測試不自動涵蓋其後修正。Windows 是目標環境，Linux 通過不能直接標示 Windows PASS。

## 8 效能 資源與成本

### 8.1 初步量測與正式基準

開發期間已有 Linux Python 3.12、synthetic 1,000 bars、trend、5 次執行的初步結果：中位約 0.522 秒、`tracemalloc` peak 約 2.68 MB、輸出 hash 相同。這是小型特定工作負載，不是 Windows、1 百萬 bars、RSS、p95 或整個 campaign 的服務保證；後續程式變更需重測，不能把該數字當最終 release 指標。

正式 benchmark 需記錄 CPU／RAM／OS／Python／版本／fixture hash，區分冷暖啟動；至少 5 次，固定 quantile 算法，報告 p50／p95、peak RSS、Python allocation、CPU、磁碟與 queue lag。採階梯 workload：1,000 bars golden、100,000 bars 壓力、目標 1,000,000 bars 與固定 trial 集合。超過可接受資源時停止並保留失敗，不任意放寬。

相對 gate 建議在首個目標 Windows baseline 量測後凍結為中位耗時不退化超過 10%、RSS 不退化超過 15%；現在尚未量測 Windows，不能宣稱已達到。絕對吞吐／時延 SLO 應基於資料頻率、CPU／memory 與 UX 需求訂定，而非隨意承諾毫秒級。benchmark 耗時不得進 deterministic result hash。

### 8.2 研究預算

固定硬上限為五家族 × 每家族最多三候選＝15 trials，最多兩次改善；所有 attempts 包含拒絕／錯誤／取消。模型支出預設 0；真實呼叫須先有明確 provider、endpoint、data disclosure 與費用權限。

每次 campaign 另外鎖定：max runtime、trial timeout、max calls／tokens／spend、parallel workers、memory、輸出容量、retry／early-stop 規則。可用於首次非付費研究的保守資源提案為每 trial 300 秒、campaign 120 分鐘、最多 2 worker、每 worker 4 GiB；這是待適用環境確認的運行設定，不修改已凍結的功能驗收。實際值須寫入 manifest，實作未具強制限制者列為未通過，不靠提示文字冒充限制。

同樣基礎設施錯誤重複到預設上限即停止該工作；安全／帳務／因果違規立即停止。無 validation 改善採固定 early-stop，不為尋找贏家擴大 trial 數。預算耗盡後 checkpoint 並停止，重啟不重置，也不能換 campaign 名繞過。

### 8.3 提高效率而不犧牲可驗證性

- 先 profiling 再優化；將反覆載入資料與 hash 的成本區分於策略計算。
- 可快取純特徵，但 cache key 必須含 data／calendar／indicator version、lookback、split boundary，不跨 fold 洩漏。
- 使用局部最小 diff 與共享固定介面降低整合返工；重用已確認的官方資料與授權說明，不反覆下載大檔。
- 研究核心不安裝整套 legacy broker／Web dependencies。UI 選用環境獨立、可重現並掃描，不把一次無已知漏洞回報擴張成全系統保證。
- 沒有實測瓶頸前不導入 GPU／distributed queue／多 Agent 市場辯論，也不將複雜 infra 當作研究成果。

## 9 Agent 與 Git 工作流程

每個工作包先有目標、允許修改檔案、禁止範圍、依賴、固定測試／golden、時間／費用上限、可交付證據與停止條件。可以自主修復已授權範圍的問題；不得自行提高交易權限、讀秘密、加入付費服務、改接受標準或啟用實盤。

### 9.1 分工與介面

- 單一檔案只有一位負責者，避免並行覆寫；共享 core、packaging、CI 與合約由整合者協調。
- 先凍結 value schema，再由 engine／campaign／paper／UI 依公共介面開發；不可倚賴另一模組的 private field。
- 若介面需改，先記錄理由與新驗收／相容策略，再同步 caller；不讓各自猜測參數格式。
- 工作報告先給可使用結果與阻塞，再附修改、測試與限制。任何安全或授權問題立刻停止受影響路徑，獨立工作可繼續。

### 9.2 Git 與發布

使用一個主分支、短命功能分支與小型可審查 commit；無獨立發版需求不增長期 release branch。不以每個 AI 候選建立 Git 分支，策略版本由 registry 管理。禁止把 raw paid data、帳戶資訊、tokens、runtime journal 或下載 cache 納入 commit。

每個 commit 對應一個可驗收成果，附測試與回退。進入 PR 前檢查 diff、秘密、LICENSE／修改標示、文件與結果來源；CI 採最小權限，外部 PR 不提供 secrets。無權限、遠端測試未執行或 required check 失敗時，發布保持 BLOCKED，不能繞過存取拒絕或以本地測試替代遠端結果。

合併前最終版本重跑完整驗證，記錄 commit 與 artifact hash；合併後確認主分支內容與 CI terminal 狀態。若發生問題，回退程式與 config／schema 按既定步驟處理，保留歷史資料與 journal；不以破壞式 reset 或刪除失敗 trial 美化成果。

## 10 操作接續與故障處理

先閱讀 [IMPLEMENTATION_CONTRACTS.md](../agent/IMPLEMENTATION_CONTRACTS.md)、[ACCEPTANCE.json](../agent/ACCEPTANCE.json)及實際檔案狀態，確認最新工作是否仍在修改。以下是新離線入口的操作範例，使用已準備好的研究環境；不能換成舊 `run.py`／`gui.py`。

```text
python -m unittest discover -s tests -v
python -m quantlab --help
python -m quantlab demo --output quantlab-output/demo
python -m quantlab campaign quantlab-output/demo/dataset.json --output quantlab-output/campaign
python -m streamlit run research_app.py
```

`demo` 與未另行指定的 campaign 使用合成資料／fixture 與標示假設的成本，不能當真實研究結果。真實檔案 `import` 需提供明確 `--calendar`、`--kind`、輸入路徑與輸出；依資料來源選 supported schema，不猜欄位。真市場 backtest 應提供核實的成本／margin config，不能沿用 demo 假設後把結果標成正式。

| 異常 | 立即行為 | 恢復條件 |
|---|---|---|
| schema／hash／calendar 不符 | 不產生有效 run，保留品質錯誤 | 正確來源與版本確認後新 dataset／run |
| ledger／golden 不一致 | 停止候選排名與 paper 晉級 | 修正、獨立 expected 審查、完整回歸 |
| provider timeout／預算耗盡 | 記 failed attempt 與已消耗額度，停止或按固定規則重試 | 不超出既有 budget，未授權不得換付費服務 |
| holdout 已使用 | 標示 consumed，不再提供改善 feedback | 新未見資料或已預先定義前瞻觀察 |
| paper UNKNOWN／cash／position 差異 | 阻新單，不盲重送、不自動反向補單 | journal／快照對帳一致，明確恢復操作 |
| secrets 疑似洩漏 | 停受影響路徑，不公開值／logs | 擁有者確認、必要時撤銷輪替與稽核 |
| 不具真 broker／資料授權 | 維持 mock／paper 或停止相關來源 | 官方資格、文件與授權證據完成，仍需獨立交易核準 |

備份包含研究 config／registry、manifest、結果與 paper journal，按其 license 與敏感性放在適當私有儲存。還原必測 content hash、事件重放與cash／positions；不要只檢查「檔案存在」。本機離線 RPO／RTO 先以測試證明，真實服務則需實際環境演練才能承諾。

## 11 尚存阻塞與下一步

1. **資料完整性與授權：** 長期 TMF coverage、歷史 margin／tax rounding、假日／臨時公告及價差量精確口徑還需對應證據；一日樣本不是完整市場驗收。
2. **模型：** 真實 HTTP／provider 與付費使用尚未核準／驗證；离線 transport 測試不能代替真服務穩定性。
3. **目標環境：** Windows 原生性能、時區、檔案鎖定及 UI 操作仍需實測；Linux 結果只能限定使用。
4. **發布：** 最終版本、乾淨安裝、遠端 CI 與授權發布需完成後才宣稱交付，不以「已開始」當成功。
5. **正式金融整合：** 台新／兆豐適用 API、帳戶資格、行情權利、憑證、故障查詢與限流需正式確認；真實交易固定停用。

接續順序是完成 Phase 3 的安全研究與來源標示、Phase 4 的可追溯 UI／registry、Phase 5 的故障恢復與最終驗收。不能為了報告 100% 把尚未驗證的外部整合加上 Mock 後視作通過。最終交付需同時清楚列出：工程完成百分比、未通過條款、真模型／市場績效／broker／實盤 readiness，以及使用者仍需決定或操作的事項。


## 16 必要 Windows 桌面產品交付增補

使用者於2026-10-09新增最終產品要求：Windows10 22H2 x64／Windows11 x64安裝後雙擊捷徑，無Python、pip、Git前置需求。這是必要驗收，不是未來可選功能。先前研究MVP完成率不得再稱整體產品完成率。

### 架構決策

舊gui.py為交易耦合的Streamlit介面，含舊憑證／啟動路徑；直接包一個瀏覽器不足以解決責任隔離。採PySide6原生Qt視窗搭配既有quantlab核心，背景程序執行有界研究工作；核心策略、資料、Decimal帳務、Paper恢復沿用。比較Tauri需要額外Rust／Webview與跨程序合約；直接延伸舊GUI保留高風險耦合；PySide6在本Python核心下新增技術最少。Qt版本與Windows支援需以官方表驗證並鎖版，不追逐不支援Win10的新版本。

### 工作包與固定新增 Gate

D0可啟動桌面骨架→D1繁中六大功能區→D2背景工作／取消／單例／睡眠與關閉安全；D3設定、系統機密保存與安全備份還原並行；D4 Windows固定輸入建置→D5免開發環境安裝／升級／移除與資料保留→D6可下載Release／hash；D7乾淨Win10與D8乾淨Win11完整情境；D9操作維護、授權、供應鏈、安全與效能證據。

每個新增Gate10點，共100；原Phase0–5的100點及門檻保持不變。整體=(已通過研究點數+桌面點數)/200×100。此增補時研究85分、桌面0分，整體42.5%，剩餘57.5%；最新值讀ACCEPTANCE.json。

### 桌面安全與驗收

主要功能包括總覽、資料管理、AI策略及版本、日期／參數批次回測、資金曲線／績效／成交匯出、樣本外比较與啟停、Paper持倉／風控／急停／對帳、設定與備份。介面必須誠實標記fixture、官方資料未完整、模型未連線、實盤停用；不以裝飾面板冒充功能。

資料與設定在每使用者應用資料區，與程式安裝目錄隔離；一般使用不需管理員。機密以Windows系統機制保存、備份預設排除；不得由Agent代填真實憑證。外部模型呼叫在介面明確顯示網路與可能費用並要求使用者主動配置，預設停用。更新不自動替換使用中程式或破壞資料；安裝器及備份恢復需保留回退路徑。

必要Win10／Win11流程：乾淨環境安裝、無Python啟動、UI、行情管理、回測、策略管理、Paper、重啟持久化、升級與移除保留資料。GitHub Windows Server runner只能證明其實際OS上的測試；不可推論Win10／Win11通過。現有環境無已授權乾淨client OS，D7/D8標BLOCKED，繼續完成可驗證的build／安裝功能。無簽章時清楚揭露，不停用或繞過SmartScreen。

GitHub main規則需防直接推送、要求必要checks、禁止force-push與刪除。現有App無administration能力，尚無保護已啟用證據；記為外部管理阻塞，人工／Agent流程仍堅持所有必要Gate通過再整合。保護規則、Win10/11實測或正式签章均不能被文件與PR存在替代。


### 16.1 增補後研究模組進度

2026-10-09 16:32 UTC，研究範圍最後Windows資源關閉修復已通過[GitHub CI](https://github.com/yostar77612/mark-auto/actions/runs/37959451997)，五個job成功，本地180tests。原研究100/100；新增桌面尚未計分，因此總體50%，剩餘50%。新桌面、強化品質／供應鏈CI及真正client OS驗證仍必須完成，不能以研究CI成功取代。已下載30個最近官方CSV檔，但完整歷史品質／正式排名仍未核准。

### 16.2 桌面整合與改善優先順序（2026-10-09 17:09 UTC）

| 順序 | 工作與理由 | 相依與完成證據 | 狀態 |
|---|---|---|---|
| 1 | 修復 Windows IPC EOF 與 canonical path 回歸；避免完成工作遺失 | `desktop_runtime.py`、固定測試；新 head 全平台 CI | 修復中，合併阻擋 |
| 2 | 驗證還原中斷不損資料、預算／holdout 不可回退、DPAPI／單例／取消 | runtime fault injection、Windows integration、UI tests | 已實作，最終 Gate 待驗 |
| 3 | 實際 frozen backtest／campaign／Paper 及安裝升級移除 | Windows installer job、source hash、manifest；不能只看 EXE 是否存在 | 待 1 通過 |
| 4 | 相同來源品質／安全／UI／回歸全成功後整合、發布 preview | PR exact-head checks、合併 SHA、Release 資產 SHA256／授權來源 | 待 1–3；沿用既有 PR |
| 5 | main 強制保護與 clean Win10／Win11 全流程 | 管理權限與可用已授權標準使用者 VM；禁止假報 | 外部 BLOCKED，可與 1–4 平行準備 |
| 6 | 真實免費模型與完整歷史品質驗證 | 已批准免費來源、實際端點、來源／日期／完整性及未見 holdout | 不阻礙離線開發；未完成不得正式策略排名 |
| 7 | 券商與即時行情適配、長時間故障演練 | 官方 API／資格／授權／測試帳戶；UNKNOWN 對帳後才恢復 | 外部條件；實盘另行授權 |
| 8 | 以量測改善 GUI 載入、批次吞吐與記憶體 | 固定 dataset／環境／seed，p50/p95、RSS、耗時、成本對照 | 與後續功能一起完成，不盲目大重構 |

暫緩：微服務化、全面換語言、多 Agent 每微任務一分支、未量測先導入分散式回測、大型依賴注入框架、策略任意 Python 執行、自動下載執行更新器。這些會增加安全與維護面，現有桌面＋獨立核心＋有界 worker 足以支持已核定範圍。

桌面控制帳本在固定 bootstrap/control-v1，備份還原刻意不回退模型支出預留及 holdout 消耗。跨機移轉不能只拷貝 state-v1 就宣稱研究紀錄完整；版本不相容或舊控制帳本無法確認時必須阻擋新研究並保留原件。這補充取代前文一般性「registry 隨備份回退」描述，避免資料恢复改寫研究事實。

整合驗證可重用相同 source tree／lockfile／test config 的證據，不為文件調整重跑無關大型實驗；但 PR 合併與發布仍由 exact-head 必要 checks 強制把關。未完成工作不得清理。GitHub connector 的不同 commit metadata 以完整 Git tree 等價核對；保存原始本地 Git 歷史，不能只保留遠端新 SHA。

### 16.3 已通過桌面工程 Gate（17:21 UTC）

來源 `3246cdc`／`b62803a` 的全部必要 PR jobs 已成功：Quantlab run37964547136、installer run37964547102。16.2 的第1–3項已完成其 Windows Server 工程驗證；下一步更新現有 PR、exact-head 通過後整合與發布預覽。桌面D0–D4及D9計60點，合計160/200＝80%，剩餘20%；D6 Release待發布，D5／D7／D8仍須乾淨client OS。固定權重不變。

Linux fresh checkout263 tests（257 PASS、6 platform/tool skips）；Windows installer263 tests（256 PASS、7 Linux／Streamlit skips），各適用平台的專用 jobs 補足，未刪除失敗測試。通過安裝器生命週期並不代表無開發環境clean Win10／11通過。所有主要功能使用合成fixture的端到端測試都有明確標示，真模型／長期歷史／正式市場評估另列未驗證。

## 17 接續正式產品驗收：0.1.2（新增必要驗證，非重做專案）

基準main5943b6e已發布0.1.1 preview，D6計分修正為已完成，原固定總分170/200＝85%，剩15%。D5無開發環境clean機、D7 Win10 22H2 x64、D8 Win11 x64保持EXTERNAL BLOCKED。準備驗收工具不能換算為作業系統實測PASS；新發現安全缺陷會否決新版發布，即使歷史計分未歸零。

本輪順序與完成證據：
1. 修正備份控制帳本、Paper uncertainty及官方資料完整性缺陷；先凍結案例，再修實作，保留失敗before證據。資料12日／13,680 bars真實驗證，Oct7缺分鐘拒絕。
2. 以免費官方本地模型驗證實際生成／回測／樣本外／比較；自由JSON失敗如實保留，structured mode只限制輸出合約，不手填答案、不放寬原DSL validator。虧損和零交易均揭露，不能把流程PASS當策略投資PASS。
3. Windows installer轉為完整分版本payload，保持先前可執行版本；真已發布0.1.1→新版及實際安裝程序中斷由Windows CI驗收，不以相同payload的0.0.0 fixture替代。構造的split-shortcut情境獨立標記，不冒充真斷電。
4. 發布zip型clean-client kit：兩版EXE、各自manifest、內建PowerShell程序及完整人工檢核。目標端不需要Python/Git；拒絕Server、ARM、錯誤build、開發工具、既有資料/安裝、提權或非互動工作階段，不刪資料製造clean。完整操作／真AI/行情／歷史state migration另保留證據要求。
5. 全部必要exact-head回歸、品質、相依漏洞、Windows實際build/install/recovery通過才合併本輪唯一分支；Release再檢查main可達及7個named gates。實際下載校驗新版EXE及kit，不以建置開始當交付。
6. 更新原有文件與功能矩陣，交付新版預覽及外部限制；未具clean Win10/11證據仍不得宣稱正式完成。

免費合法環境調查與可重現程序在`packaging/clean_windows_README.md`；更新復原/保留payload磁碟影響在`packaging/update_recovery.md`。兩者是可執行交付的操作附件，03/05仍集中記錄風險與Roadmap，不拆出大量重複規範。

### 未完成條款的處理

- clean Windows授權/VM：EXTERNAL BLOCKED。Microsoft官方評估媒體或使用者既有合規授權可作後續路徑；不能擅自接受協議/啟用或購買資源。
- main強制保護：EXTERNAL BLOCKED，管理API403；本地/CI流程不能代替GitHub規則。
- 真券商、即時行情斷線重連：NOT VERIFIED／需要官方權限資格；已有Paper模擬故障測試不是實際外部連線證明。
- 正式策略晉級：NOT QUALIFIED，短資料、假設成本、實際虧損/零交易，不能建立可信正式排行榜。這是資料/研究證據不足，不可謊稱只是API授權缺失。
- 自由AST可靠生成：實驗FAILED／PARTIAL；受限家族參數structured方式已技術驗證。保持模式名稱與能力界線，不以新架構掩蓋限制。

## 18 新增正式產品範圍：市場優先桌面（2026-10-09 22:52 UTC）

使用者新增專業交易儀表板、加權指數/TX/MXF/TMF實際契約、合法真行情與時效標籤、自選清單、互動蠟燭/成交量/十字游標/縮放拖曳、1/3/5/15/30/60分與日週K、MA5/10/20/60及EMA/RSI/MACD/KD/Bollinger/VWAP、訊號與成交分開圖示。AI研究/回測/比較/Paper/風控改為一般使用者表單與圖表，原始JSON移進階診斷；深色繁中、台灣漲紅跌綠且文字符號並用、DPI與小視窗、偏好持久化。核心及已驗證安全機制沿用，新增UI必須打包至Windows桌面。

本輪0.1.2安全/安裝修復先完成其固定Gate與整合，再依序盤點→真行情儀表板→K線/指標→AI/回測表單→比較/Paper/風控→UI回歸→Win10/11驗收。AI優先官方允許的訂閱途徑、免費本機或手動交換；ChatGPT訂閱不得視為API額度，付費API預設停用，不使用Cookie/未授權自動化。真即時資料權限不足時提供真歷史功能並明示來源/時間，禁止假行情。

原固定範圍85%仍僅代表170/200歷史Gate；新增範圍尚待盤點凍結權重，未驗收不計分；新版整體完成率待新分母凍結後重算，不能宣稱仍85%。各項門檻維持；第二/第三優先進階功能先列評估，不拖延必要行情/UI。真AI有效改善候選目前FAILED，工程迴路通過不等於模型品質通過，後續修復須預先限制實驗預算及避免反覆使用holdout。

## 19 新市場與易用性固定驗收（新增100點）


以下由使用者自主工程授權下凍結，實作前生效（2026-10-10 00:15 UTC）。每項 PASS 必須有指定 commit + 測試／實際資料／平台證據；BLOCKED/FAIL/NOT_RUN 不得給分。必要時先拆成固定子項，每個子項二元通過，不事後主觀打折。

- **M1 真實商品與來源，20 點**：首頁可見加權指數與 TX/MXF/TMF 真實合約月份；watchlist 新增刪除排序；每筆來源、exchange timestamp、receive timestamp、timezone、延遲值／未知原因。Realtime、delayed、EOD、history、offline 為明確狀態；過期／離線不得繼續以 realtime 呈現；未知 entitlement 不可推斷 realtime。漲跌參照為前收或結算必須標明，二者不可混用。
- **M2 K 線及時段，20 點**：1/3/5/15/30/60 分、日、週；OHLC/量、crosshair、zoom/pan、同商品選擇同步；分鐘聚合以明示 session-open 錨定，不跨日／夜盘間斷；日依 exchange trade_date 組合交易日，週依明示交易日週規則。測試夜盤跨午夜、假期、短日、到期、重複／亂序／缺資料、最後部分 bar。日週本身依定義聚合多個 session，不能簡化成一律禁止跨 session。不得用日線製造分線。
- **M3 指標正確性，15 點**：MA5/10/20/60、EMA、RSI、MACD、KD、Bollinger、VWAP，各有周期／平滑／seed／warmup／缺值規則。固定 SMA；EMA alpha=2/(n+1) 與明示 seed；RSI Wilder14；MACD12/26/9且 histogram 倍數標示；KD9/3/3 seed50、high/low範圍；Bollinger20/2與母體或樣本標準差固定；VWAP以明示session重設、零量回傳缺值。只有 OHLCV 時使用 typical-price volume approximation 並標為估計，若要求真實成交 VWAP 則必須用 tick 成交加權。參數按 bar 數而非鐘錶分鐘；切週期重算。禁止未成熟指標填0或未來資料滲入。
- **M4 人可操作表單，20 點**：AI 研究（split、预算、選擇條件）、策略參數、回測（日期／資金／費用／保證金）、比較表、紙上委託／對帳／風控均不必手寫JSON；欄位型別、範圍、單位、錯誤原因與空態；保留所有現有審核、策略hash、holdout與帳本驗證。操作結果以表格／摘要可讀，JSON僅進階檢視。
- **M5 研究與成交圖層，5 點**：signal 使用 signal timestamp、target position、reason；fill 使用 fill timestamp、實際模擬成交價、方向、量、成本。形狀／圖例不同且可各自關閉，不能把訊號畫成成交；以 contract、data hash、strategy hash 綁定，禁止跨版本錯配。畫面一律標明回測／紙上，不暗示實盤。
- **M6 合規 AI 模式，10 點**：官方文件確認的 ChatGPT 訂閱模式若存在才提供；否則有清楚替代路徑。付費 API 默認關閉、明示目的地與預算；Ollama 真實 loopback 流程；manual export/import 用受限上下文與 validate_dsl，保留候選來源與雜湊，永不執行任意程式。依採用路徑凍結可驗收子項，不能假定所有替代路徑必須全部同時存在，也不能以不可用官方訂閱阻止已批准替代路徑完成。
- **M7 桌面呈現與持久化，10 點**：專業繁中深色首屏、台灣紅漲綠跌並有+/−文字、focus／鍵盤和對比；1366×768與1920×1080在125/150% DPI主要流程可用，短視窗以合理捲動不遮必要控制；保存 watchlist、選定商品／周期／指標／主題／窗體位置，重啟還原並修正離屏位置。不得保存一次性的網路同意或秘密到一般設定。

額外 release veto：實單始終停用；舊 trader 不可被新桌面匯入；來源／freshness假標、跨商品價格錯配、未授權傳輸、秘密外洩、因新UI绕過風控或保留集保護，任一未解決即不可發佈。效能可先建議 10,000 根歷史 bar 下游標／拖曳 p95<100ms、一般操作主執行緒不阻塞>250ms；需指定參考硬體與可重現腳本後才凍結，不能只寫「流暢」。


原200點保持不變；新增100點初始0PASS。原85%、新增0%、整體170/300=56.67%，剩43.33%。分母在實作前固定，不按已完成程度倒推權重；此為驗收加權而非工時估計。

### 原範圍0.1.2整合完成與新版0.2.0進行中

原本安全/安裝修復已通過exact-head Gate並整合main28c9f902；合併後[38009150044](https://github.com/yostar77612/mark-auto/actions/runs/38009150044)完成Release及實際下載校驗，仍unsigned preview。保留所有原始分支歷史，本地ccb74d2與remote9008522僅metadata不同。

新版使用單一功能分支agent/market-desktop-v1：獨立readonly多商品市場模型與官方daily/cache/import、session-safe多週期/Decimal指標、原生Qt行情/K線、typedforms及manual策略交換，沿用原核心；市場商品與交易支援分開（交易研究仍TMF）。正常首屏繁中、technicalsource置收合診斷，圖表顯示台北時間但底層UTC。OAuth/訂閱provider另階段驗證，不把offline單元測試說成真帳戶驗證。

原始市場來源真實bytes及TMF訓練區間重播已確認；雲端直接官方HTTP因DNS解析失敗，明示BLOCKED，不放寬TLS或proxy限制。Windows建置另產生public-market-download.json，VERIFIED才可作線上來源證據；診斷工具成功寫出BLOCKED報告不代表市場Gate PASS。完整新增驗收尚未計分。

## 20 官方 ChatGPT 訂閱桌面整合：0.2.1 固定交付範圍

承接0.2.0市場介面，不重寫既有交易核心。01:00 UTC前已凍結合約於IMPLEMENTATION_CONTRACTS.md；M6權重及其餘既有權重不變。工程次序：官方PKCE/OIDC與Windows DPAPI→訂閱Responses協定與持久帳戶/研究次數→同一桌面worker生命週期→受限策略產生/改善與研究憑證→封裝/原生相依檢查→exact-head CI→正式版本升級與preview交付。真帳戶登入與模型呼叫需要使用者在官方流程授權，不能以fixture取代。

- 啟動只讀本機狀態；首次初始化、授權、開啟官方網址、模型發現、refresh、推論均須明確操作。本應用自己的host/client/registration與DPAPI儲存，不讀其他軟體cookies/token，不提供貼上token欄位。一般API付費回退仍關閉。
- auth/inference共用既有JobManager；取消、關閉、睡眠、工作區或帳戶切換前，確認整個子程序樹停止。Linux檢查活動程序而不把不可執行zombie誤判為正在推論；Windows保留Job handle直到active count歸零，未知則繼續阻擋。
- run_campaign增加可選descriptor與嚴格receipt snapshot介面，研究核心保持stdlib-only。支出先預留、未知不退還；中斷後只有相同manager的已停止工作證明與不可變啟動快照可發起本機對帳，不呼叫模型、不重新選策略或使用holdout。
- source/dependency manifest綁定真實root auth/provider來源與四個固定desktop-only套件；打包保留來源及distribution metadata。engine source變動必然產生新身分，舊研究可讀但原身分重跑會被拒絕；禁止冒用舊hash。
- 既有真本機模型改善的v3兩次重複候選失敗保留；v4預先限一次呼叫，以最小提示補充產生fast=2/slow=6不同候選，技術去重通過。沒有新回測、OOS或holdout，因此不得稱為獲利改善或正式策略晉級；累計14次真免費本機推論，不追加無限制搜尋。
- 版本發佈前必須通過原生RS256/JWK/nonce/audience、CFFI/parser、依賴漏洞、Windows DPAPI/鎖/程序樹及完整桌面/升級Gate。這些工程證據仍不代表真訂閱資格、額外credit設定或伺服器token上限已可控。

外部仍待：使用者官方帳戶授權/明確有界呼叫、clean Win10 22H2 x64與Win11 x64、main管理權限、合規簽章。正式投資策略可信度則另取決於充分合法歷史與研究驗證，不能全部歸因外部授權。未達正式驗收前安裝檔保持preview標示。

### 已合併0.2.0的固定項目計分（2026-10-10 01:33 UTC）

mainfc2dfac／PR#3，head655f47df與本地e62d897完整tree853300ac一致，原本地成果保留。Quantlab38012730935七jobs及Windows38012730927全部必要Gate PASS；Windows465項456PASS9適用其他profile skip，真0.1.2升級／中斷恢復／設定保留通過，實際官方日來源HTTP VERIFIED。main後續安裝檔仍需發布並下載驗digest，不能僅以合併當交付。

獨立逐項審查及exact-main UI重拍後，M1真實商品/來源20點與M5訊號/成交5點完成：新增25/100，原170/200保持，整體195/300＝65%，剩35%。此百分比因使用者增加100點必要市場/UI範圍而重算，並非把原85%已完成成果刪掉。M2保守保留PARTIAL（TX/MXF分鐘檔尚無產品匯入入口）；M3／M4缺口已於下一版修復但未完成新版Gate，M6正式選定路徑/實際帳戶證據未全滿，M7乾淨WindowsDPI仍BLOCKED。每個整項未全通過即0點，不因局部實作提高分數。

0.2.0交付已完成：postmerge38013204925通過並發布[安裝檔及clean-client kit](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38013204925-1)，兩者實際下載hash與ZIPCRC核對PASS。這是可下載preview交付，不解除Win10/11乾淨實測限制。0.2.1驗收改以這份真實0.2.0為固定升級baseline，保留舊版本和原紀錄。


## 21 行情／普通表單收尾與研究重驗

0.2.1已在完整exact-head Gate後透過PR4合併main2ed1e3e5；644項Windows測試633PASS11平台/profile skip，Linux629PASS15平台skip，跨registration safety獨立151項通過，真0.2.0升級/中斷復原PASS。Postmerge安裝檔仍需核對完成，真帳戶授權與乾淨Win10/11不因此通過。

依風險、效益及依賴順序：
1. 已封堵跨授權unknown-call、ledger遺失/回退及lateerror降級，保持復原不重試不確定請求。
2. 本模組把TX/MTX/TMF分鐘檔匯入、真資料到期表單與effective-dated Paper margin接入正常GUI；沿用既有模組，不放寬資料與風控。完整品質/Windows打包升級通過再發布0.2.2。
3. 補齊真正Walk-forward。單次四切分不能替代rolling多fold；先凍結固定pool/chronology/全程budget/持久selection/consumedrange規範，舊研究與暴露資料不能冒充fresh。此工程缺口可自主處理，不推給使用者。
4. 真實ChatGPT由使用者官方流程授權；沒有授權不實際呼叫，paidAPI仍停用，accountcredit與server token限制不可冒充可控。
5. cleanWin10 22H2x64/Win11x64用同版本無開發工具kit實際完成GUI/安裝/升級/移除/保存/DPI驗收，缺環境明示EXTERNALBLOCKED；mainadmin403同理。簽章為目前unsigned與Windowsreputation限制，不自行新增購買憑證的驗收權重或繞過安全提示。

M2、M3、M4按完整項目證據評分，不因多幾個測試先加分。M6真實所選AI路徑與M7clientDPI尚未全滿。原200+新增100分母維持，並額外誠實列出完整需求重驗缺口，不能以195/300已記錄的65%當所有規範再認證。暫緩非必要portfolio optimizer、自動靜默更新、新背景服務及大規模效能重構；先完成既定普通操作和安全Gate。


### 02:36 UTC發布與分數核對

0.2.1 [Release](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1)已實際下載核對：EXE41,583,381bytes／SHA256cce3f6242068affa91ab5c242f6ac655bbb59c677e4abda8b85065b97e48e0b1；clean-kit77,401,239bytes／SHA256850e2157d8b6652bc5d269bcd6dc76eba88f0ec7f81c29a75bc7e5b5a91768d4，8entriesCRC PASS；manifest7,247bytes／SHA2564c6c6b0a0ddff170c5394b7b04f03f3575c29b54087c9e042a60c3fb38bc5639綁main2ed1e3e。PostmergeWindows38016622951三jobs與Quantlab38016622996七jobsPASS。獨立重核全部8下載asset及56source inputs，Windows CRLF hash差與Git LF的確切轉換相符，沒有假定hash相同。更新復原保留929舊檔、5sentinel、真設定與lifecycle副本。Server單次啟動1.0279063s/RSS103309312bytes，非clientSLO。

M3完整15點可驗證，新增40/100，原170/200保留，已記錄總210/300＝70%，剩30%。M2/M4仍待候選0.2.2完整Gate，TAIEX分線能力/來源權限未解，M6真授權、M7cleanDPI仍未滿。重新比對使用者原文另確認ProfitFactor/Sharpe實作與停損/停利/成本參考線接線待補，連同Walk-forward列工程工作，不能拿既有窄項分數掩蓋。不得用新權重或移除需求美化百分比。

0.2.2沿用上述真正已發布0.2.1baseline，hash及測試固定fixture依實際下載更新。曾不必要修改recovery腳本舊default導致一項相容性測試失敗，已還原原default而非改門檻；工作流/kit仍明示0.2.1。後續40packaging測試36PASS4PowerShellskip，失敗log保留。另Qt對話框exec被原AST dynamic-call Gate同名拒絕，改用Qt正式非同步open/accepted/finished流程，加重複開啟／取消／关闭期间不啟動工作檢查，54相關測試PASS，原Gate不改，沒有改名或getattr隱藏呼叫。


### 2026-10-10 02:52 UTC：當前整合順序

1. 先修復 PR #5 首輪 CI 的 UTF-8、Qt 測試依賴及 Paper replay 逾時根因；同一分支繼續，必要完整 Gate 全數通過前不合併。保持原 30 秒測試工作預算、原 960-bar 測試與原驗收斷言。
2. Paper 效能改善先依 03 報告的量測，僅局部優化。任何快取必須每個交易讀取並比較完整 journal / materialized snapshot，外部下單、kill、篡改、截斷與 rollback 不可被快取掩蓋；回傳 detached state，限制保留記憶體。空計畫優化仍要確保 durable cursor 與 restart idempotency。
3. 此批整合完成後才整合已隔離開發的固定候選池 Walk-forward、必要 PF / Sharpe 及持倉／風控參考線。AI 候選 Walk-forward 的來源與先前資料暴露必須另外驗證，不能以 built-in 版本宣稱全部 AI 研究要求完成。
4. TAIEX 五秒來源已找到，但自動使用權限未證实；詳見 03 的官方來源與限制。保留 EXTERNAL BLOCKED，不擅自接入、偽造分線或延用每日資料授權。

當前已發布版本仍為 0.2.1，既有固定清單 210/300（70%），待修項不提前加分。乾淨 Windows 10 / 11、真實所選 AI 授權、即時行情與 main 管理權限限制仍分別保留。


### 2026-10-10 03:34 UTC：原生逾時已定位，完整 Gate 仍未通過

同一 PR #5 head `71f8feb73f4f73d09f9ffe14d1f8e6970ab63ecc` 的 Windows Server 2022 run 38020197303 / build 114119289481 再次通過 build、安全、安裝、真 0.2.1 升級、移除保存及中斷復原。Quantlab Windows 3.11 通過，但 Windows 3.12 job 114119289510 仍未達原 30 秒 Paper 門檻，不合併、不發布。Linux Qt 系統函式庫問題已解除，完整 source smoke 接著揭露四個 auth runtime 缺失；工作流補齊既有固定 PyJWT/cryptography/cffi/pycparser 版本，先做原本離線驗證，再跑完整套件，不跳過失敗。

Windows Server 2025 / Python 3.12.10 / SQLite 3.49.1 的相同 960-bar 診斷：worker 29.718 秒，其中 960 次 cursor commit 25.713 秒；所有 replay connection 0.376 秒、broker connection 0.253 秒，故不能把重用連線當主要解法。兩個原 process-death fixture 本次 0.281/0.297 秒，皆 exit 73，先前 10 秒逾時未重現，門檻保持不變。診斷有界且完成 worker 清理，不取代原測試 FAILED。

下一步先在原生 runner 的 disposable 檔案測 DELETE/TRUNCATE/PERSIST + FULL，保留每個既有耐久邊界。尚未改產品 journal mode。[SQLite 官方 WAL 說明](https://sqlite.org/wal.html#walreset)與[3.51.3 修復說明](https://sqlite.org/releaselog/3_51_3.html)指出現有 3.49.1 屬 WAL-reset 問題版本範圍；不得為效能直接開啟未審核 WAL。若採 rollback-journal 模式改善，仍須真實 process-death、備份還原、legacy pending plan、外部 kill 與完整 native 原門檻。


### Smoke 驗收寫入使用者狀態：已重現、修復中

独立反例在隔離的既有模擬帳戶副本執行原 `desktop.py --smoke-test`：exit 0/status passed，但 `state-v1/desktop_safety.json` 與 `state-v1/paper.sqlite3` bytes 改變，kill switch 變 true。原因為合成 worker 雖隔離，主視窗仍先用正式 workspace 啟動並執行 `freeze_paper`。只有 settings 檔不變的既有測試不足以涵蓋此缺陷。這是當前 release blocker；正常啟動的安全停止仍必要，不可刪除。修復須在主視窗/lock/guard 建立前隔離整個 smoke workspace，原設定只讀快照，並以成功與注入失敗測試證明正式目錄、broker、safety、settings、recovery 記錄皆不變。保留原安裝路徑檢查語意，明示 report 的被檢查位置與真正暫存執行位置；最終 exact-head 安裝／升級／復原 Gate 需重跑。


### 03:53 UTC：Smoke 只讀隔離與 CI 固定依賴目標修復

主視窗 smoke startup 現在先建立暫存 root，原設定 workspace 僅透過 `WorkspaceLocator.load(probe=False)` 驗證後讀取；正常 startup 的探測、復原、mutex、停止／對帳規則不變。report.data_dir 保留被檢查設定位置，smoke_data_dir 明示真正暫存執行位置。七項來源測試覆蓋 default/redirected/不存在 root、broker/safety/settings/recovery 全目錄 bytes/names 與 transient write audit hook；Linux PASS。Windows來源測試只把 known-folder discovery 指向測試fixture，native mutex/Qt/spawn 保留真實，非 clean-client 或 known-folder API 的替代驗證。

新增依賴後，原 matrix 的 Win3.11/3.12/Linux3.11 被既有嚴格來源驗證以 unsupported_dependency_target 拒絕（run38021395788），並未執行套件或取得 native benchmark；Linux3.12和UI完整套件已通過。修復明示新增這三個既有CI目標，不刪矩陣／測試。原 Win3.13/Linux3.12 target records 與正式 Windows lock 不變；從官方 PyPI 實際下載九個不同wheel逐一驗hash。共享manifest解析留在已hash綁定的 provider.py，CI-only installer採binary-only、require-hashes、isolated PyPI、force-reinstall並逐一核對pip report的closure/version/digest。真Linux3.12 fresh及已有套件重裝、原OpenSSL4.0.3離線驗證通過；新增native目標仍待CI。

Root完整759 tests：744PASS、15既有Windows/PowerShell平台skip，103.709秒；quality及全Git歷史0finding。四個auth runtime套件的獨立供應鏈audit無已知漏洞；bootstrap pip工具自身的掃描發現另記錄，不能用runtime結果認證工具。原30秒Paper與10秒process-death門檻不變。仍待原生磁碟模式量測、最終timer/cleanup錯誤terminal-proof與exact-head完整Gate，未合併。

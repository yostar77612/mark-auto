# mark-auto 開發接續狀態

<!-- CURRENT_STATUS_START -->

## 原 300 分正式驗收恢復／Win11 仍待外部證據（2026-10-12 21:12:31 +08:00／13:12:31 UTC）

使用者最新明示「請以原本固定的 300 分驗收標準作為正式完成依據。」並要求 Win11 獨立驗證，取代先前 D8 暫緩決定。原 47 項 ID／權重／狀態／證據不改；目前 **230/300＝76.67%，剩餘 70/300＝23.33%**。D8 恢復 10 點、EXTERNAL BLOCKED，未實測／非 PASS；D5／M7 的原 Win11 共用條件一併恢復。剩餘 D5／D7／D8／M2／M6／M7＝10／10／10／20／10／10，沒有新增得分。先前 230/290＝79.31% 及取消時間序保留為歷史，不能繼續當目前完成率。

- **工程實作另報：** 未獨立量化百分比。既有文件沒有全專案另一套固定工程分母，不能以 CI 通過率／測試數或驗收分數換算。既有窄範圍驗收為研究 100/100、桌面 70/100、市場 60/100；它們不是新增的工程完成百分比。最新 source 已有下列 CI／preview 證據；安裝測試所有權修補及實機驗證準備另行進行，未以此宣稱工程全部完成。
- **目前 Win10 實體主機：** 原生盤點為 Win10 Pro 22H2／19045.6466、Ryzen 5600X、RAM 32 GiB／可用 20.15 GiB、C: 可用 357.05 GiB；這僅是環境證據，尚未執行產品測試。使用者已准許本機 MarkAuto 安裝／UI／lifecycle，須先核對精確影響、備份與隔離，且只用正常必要的專屬安裝位置。已使用主機不能直接算 clean Win10 PASS；其他程式／資料／系統仍受保護。
- **權限／外部限制：** 可唯讀確認是否有其他合法且已授權的 Win11 環境；未有可驗證環境／實測前 D8 保持 EXTERNAL BLOCKED。操作另一台電腦、新 VM、系統元件、管理員權限或全域設定，仍需明確授權；無新增 broker／live AI 授權。原 clean-client、DPI、合法完整分鐘資料與正式 SIWC 證據要求不降。
- **已核驗發布基線：** main `f202c47bad061967edba2e6f8a0b8be81a37ffba`／tree `1a40456616a811ed22181046416c72d5340aa2b3`；[Quantlab 38199994180](https://github.com/yostar77612/mark-auto/actions/runs/38199994180) 全 14 jobs、[Windows 38199994183](https://github.com/yostar77612/mark-auto/actions/runs/38199994183) build／security／release 全通過，Server native 1,636 PASS／33 skips。[0.2.2 unsigned preview](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38199994183-1) 公開 bytes 已核驗；installer SHA-256 `5a3e6fbecbe1f4780b4945e9fb2419aa589ebb88a173835e4c0852b391930e6c`。本次重讀來源／GitHub 終態／公開 digest；不冒稱重新執行 installer、clean-client 或 OAuth 驗收。簽章／main 保護仍另列限制，正式發佈仍未達門檻。

<!-- CURRENT_STATUS_END -->

## 以下為本次恢復前的歷史狀態（保留原文）

舊 230/290、Win11 延後、唯讀／全面本機停止及舊來源待 CI／未發布說法按原時間解讀；目前範圍、權限及基線以上節為準。

<!-- PRE_RESTORATION_CURRENT_STATUS_START -->

## PR #14 SQLite fixture 收尾待驗（2026-10-12 11:00 +08:00／03:00 UTC）

`4e5043a1` premerge Quantlab 全 14 jobs、Windows 38195954546／artifact 核驗 PASS；合併前另查 16 個 SQLite ResourceWarnings。隔離 CPython 3.13 tracemalloc 證實兩個 fixture allocation：test_windows_recovery_diagnostics.py:56 記憶體 DB；test_restart_availability_contract.py:193 analysis.lock.sqlite3（RecoveryUI 共用）。未發現產品 leak，亦未逐一歸因全部 16 個 Windows 警告。

兩處 closing 保留原 transaction，既有 ID 內增 use-after-close ProgrammingError 檢查，獨立審查 PASS。CP3.13 forced-GC／tracemalloc 兩路各 1→0 warnings，未改 restore 對照仍 0；owned Qt CP3.11 定向 49 PASS／3 原 Windows skips、14.819 秒。須新 exact-head CI，不能沿用前次 PASS。原失敗保留；目前 230/290、原 230/300、D8 延後非 PASS 不變，無新增分數或根因修復宣稱。


## PR #13 合併後 helper 啟動失敗；原次觀測候選待驗（2026-10-12 10:26 +08:00／02:26 UTC）

- PR #13 必要 premerge Gate 全通過後合併 main `746c0d77`（同 tree `011a08e2`）；[Quantlab 38194001676](https://github.com/yostar77612/mark-auto/actions/runs/38194001676) postmerge 為 13 SUCCESS／1 FAIL。Win3.12 既有 helper-death-before-GUI case 的 helper 約 1.41 秒於 helper-ready barrier 前退出；1,415＝1,387 PASS／27 skips／1 FAIL、547.155 秒。不是原 18 秒期限或 Paper 逾時重現；stderr 原為 DEVNULL，退出原因未知。
- 兩邊原 Paper 960 cursor commits／WAL／FULL(2)、cleanup 無 child；3.11 replay／repeat 6.188／0.766 秒，3.12 6.625／0.907 秒，均 PASS。research 各 243＝237 PASS／6 原 skips；不以這些 PASS 抵銷 helper 失敗或推定歷史 timeout 根因。
- 三檔 TEST_ONLY 候選觀察原 child 的固定 phase／error code／return code／cleanup 前 barrier；不改程序生命週期、handle、期限、assertion、workflow 或產品，不宣稱因果修復。獨立審查無 blocker，原 assertions／watchdog／4 Popen／期限保留。同一凍結來源 Linux CPython 3.11 完整 1,669＝1,641 PASS／28 原 applicability skips，451.962 秒、exit 0；原 1,658 IDs／順序／28 skip 不變，新增 11 core、research 243 不變。各結果不相加，新 Windows native 尚未執行，helper 原因仍未知。
- [Windows 38194001655](https://github.com/yostar77612/mark-auto/actions/runs/38194001655) build／security／lifecycle 通過，artifact 來源／CRC／frozen／TLS 獨立核驗 PASS。release guard FAIL 明確拒絕發布，預期 tag 查詢 404，僅 CI artifact。最後核驗公開版仍 `3ef9a740`；目前 230/290、D8 延後非 PASS、原 230/300 rubric／失敗原文全保留，未宣稱正式完成。


## PR #13 診斷 helper 原生崩潰修補待驗（2026-10-12 09:26 +08:00／01:26 UTC）

- `42ad7f77` 的 [Quantlab 38190178113](https://github.com/yostar77612/mark-auto/actions/runs/38190178113) 為 13 SUCCESS／1 FAIL：Linux 3.11 exit 139。CPython 3.11.17／Qt 6.11.2 的 HistoryUI→cleanup reproducer／faulthandler 定位新 observer 的 app.allWidgets 崩潰。
- 三檔 helper／test 候選改採 owned-valid fixture 指標，避開全域 Qt registry；保留 OS process 指標，補 deleted validity guard／正確 WAL 前後 metadata。獨立 39 PASS／2 Windows-only skips；新增 3 core tests，discovery 1,658／core 1,415／research 243，原 IDs／六個 research skips 不變。
- 本來源 Windows cores 各 1,385 PASS／27 skips，444.346／510.130 秒；原 Paper 6.281／6.234 秒、960 FULL cursor commits、cleanup 無 child。research 各 237 PASS／6 skips，239.953／309.500 秒。這些 PASS 不證明舊 Windows timeout 根因；原 960 bars／30 秒／FULL 不改。
- [Windows 38190177996](https://github.com/yostar77612/mark-auto/actions/runs/38190177996) 已 build／static security SUCCESS、PR release SKIPPED；artifact 來源獨立核驗仍待。root 01:25:51 UTC 啟動完整 Linux Gate：CPython 3.11.17／SQLite 3.54.0／Qt 6.11.2，locked-auth proof 通過，原順序選定 1,658 tests／900 秒 outer cap；full 結果 PENDING。uv 3.53 loader 拒絕紀錄保留，未宣稱新 CI 通過／可發佈；原失敗、230/300 歷史、目前 230/290 與 D8 延後非 PASS 均保留。


## PR #13 Paper 原門檻失敗；fixture 保留修補與原次診斷待原生再驗（2026-10-12 08:57 +08:00／00:57 UTC）

- **保留原次失敗：** 來源 `13ebd0f700b65b13436d4f0e2dc581db64d93d7d`／tree `817984a0c44815377f656860765c7c7fc81c4cc3` 的 [Quantlab 38187882846](https://github.com/yostar77612/mark-auto/actions/runs/38187882846) 終態 13 SUCCESS／1 FAIL：Windows 3.12 既有 typed Paper case 在原 960 bars／30 秒第一次 wait 仍見 jobs.active／Working 而失敗。research 兩 profile 均通過；後續 fresh-process observer 通過不抵銷原失敗，也未證明原生阻塞階段。[Windows 38187882886](https://github.com/yostar77612/mark-auto/actions/runs/38187882886) build／security SUCCESS，release SKIPPED；必要 Quantlab 尚未全通過，不是公開發佈或正式完成。
- **已證明的缺陷限於測試保留：** discovery／alternate suites 的別名保留已完成 TestCase；原 NativeDesktop fixture close 未銷毀窗口／子 widgets／backup timer。八檔 test-harness／diagnostic 候選僅釋放非選中 suite，並在原 close 流程成功且 owned job 不活動時，向該 fixture 發送定向 DeferredDelete；不改產品 closeEvent、不全域刪除、拒絕關閉／仍有工作時不刪除。Linux 八-fixture、未強制 GC 的對照為 RSS 291,082,240→129,163,264 bytes，舊 case 保留 7→0、MainWindow 8→1；證明 fixture 保留修補，不能推論它造成原 Windows timeout 或 Windows 效能已修好。
- **同一次失敗觀測，不替代驗收：** decorator 保留原 typed test body，在原 deadline、fixture cleanup 前採集有界／去敏的 UI、owned child／IPC、phase／SQLite commit／heartbeat 證據。worker 必須先成功通過原 gate.wait(15) 才啟用診斷；不重跑失敗案例、不以 fresh process 替代、不增加 gate 預算。原 30 秒／960 bars／FULL、耐久邊界、repeat／安全 assertions 均保留；診斷有額外開銷，其未來 PASS 本身不能證明原根因。
- **候選審查／測試分開列示：** 八檔獨立審查 PASS，獨立 36 PASS／2 原 Windows-only skips。discovery 為 1,655／core 1,412／research 243，僅新增 18 core tests；全部原 ID／相對順序及六個 research skip ID／reason 不變。root 同一凍結來源六模組組合為 73 PASS／0 skips、30.487 秒，使用 owned Qt runtime／offscreen Linux CPython 3.12；與前述獨立 36 PASS／2 skips 分開且重疊，不相加。新 exact-head Windows／完整必要 CI 尚待，不預填 native 通過數。
- **範圍／發布界線不變：** 原 230/300 rubric 與全部失敗歷史保留；目前 230/290＝79.31%、剩餘 60/290＝20.69%，D8 延後非 PASS。最後已核驗公開 preview 仍為 `3ef9a740`／`desktop-preview-38169393012-1`。本輪不改產品或降低 30 秒原 Gate，不宣稱 Win10／OAuth 驗收、Windows 性能修復或正式發佈就緒；下方依日期保留各階段紀錄。


## PR #13 原生測試新失敗；最小測試修補／觀測接續（2026-10-12 08:22 +08:00／00:22 UTC）

- **本次必要 CI 未通過：** PR #13 來源 `d4e81e09976ce1d61000cc66190e211f8221d29f`／tree `e546f69de710ece06b4561fa327a3a8e1eea719b` 的 [Quantlab 38186610247](https://github.com/yostar77612/mark-auto/actions/runs/38186610247) 終態 12 SUCCESS／2 FAIL。Windows core 3.11：1,365 PASS／27 skips／2 ERROR、598.452 秒；3.12：1,366 PASS／27 skips／1 ERROR、552.350 秒。兩個 research profiles 各 237 PASS／6 原 skips，347.203／217.906 秒；前次 10／40 秒案例本輪通過，但未觸發其 failure diagnostics，不能據此宣稱已找到或修好先前效能根因。
- **編碼錯誤已定位，僅測試修補：** 新增 AST 檢查 `test_active_writer_timeout_diagnostics.py:141` 以預設 cp1252 讀 UTF-8 來源，兩個 core 與 installer native 均發生 UnicodeDecodeError。實際 bytes 已重現 red；候選改明示 UTF-8，並在同一 test ID 要求顯式 encoding，獨立審查 PASS／11 focused PASS；移除 encoding 參數的 mutation 亦 red，原 test ID／assertions 不變。新原生 CI 尚待，不把局部結果認作完整 PASS。
- **另一原生失敗仍待定位：** 3.11 既有 observer-failure test 因 result 缺 `error_type` 而 KeyError，runtime 10.300 秒；controller timeout 分支與 observer failure 的確切原生階段尚無證據。新增有界、去敏的 phase／commit／child-start 測試診斷已通過 root diagnostics-only 審查。三個本機控制分支分別為：正常 120／FULL、RuntimeError、0.115 秒；延遲 probe 10.019 秒、未到 observer／無 error_type；停滯 observer 8.083 秒、120 全完成但無 error_type（原 min(8, remaining) cap）。所有 children 均 reap，僅 owned fixture；這些對照仍未證明本次原生失敗階段。原 120／FULL／10 秒與原 assertions 不變，不改產品、不降工作量。root 最終合併定向 52 PASS、20.989 秒（33 diagnostics＋19 Paper）；新 exact-head native 尚待，不聲稱性能修復，後續原生結果由同一 PR 按來源補記。
- **沒有新安裝檔：** [Windows 38186610245](https://github.com/yostar77612/mark-auto/actions/runs/38186610245) 終態 FAIL，native 1,603 PASS／33 skips／1 ERROR、835.234 秒，唯一 ERROR 為上述新 AST 編碼錯誤。尚未進入 frozen／lifecycle／installer，release SKIPPED，只有 1,715-byte partial evidence artifact，不能當作 installer 交付。
- **歷史／範圍不變：** 本節接續下方 08:00 快照，所有舊失敗及各階段結果保留。已核驗公開版仍 `3ef9a740`／`desktop-preview-38169393012-1`；目前 230/290＝79.31%、剩餘 60/290＝20.69%，D8 owner-deferred 非 PASS，原 230/300 rubric 保留。clean Win10／實際 OAuth 未因此通過，產品與原安全／驗收門檻不變。


## PR #12 合併後必要 Gate 失敗；測試觀測候選待驗（2026-10-12 08:00 +08:00／2026-10-12 00:00 UTC）

- **合併與失敗分開記錄：** 範圍 PR #12 已合併 main `185513f03bb9a52bb7ad80da1a508db03c3bcd52`／tree `638f2f1b402deb11b01096ef43368e0fa0b2abab`，產品／測試／工作流未變。[Quantlab 38185218807 的 Windows 3.11 research](https://github.com/yostar77612/mark-auto/actions/runs/38185218807/job/114605969432) 終態為 13 SUCCESS／1 FAIL，失敗僅 3.11 research：原 243 cases＝235 PASS／6 原 skips／2 ERROR，parent 377.109 秒。3.12 為 237 PASS／6 skips，224.672 秒；不能替代 3.11 的必要 Gate。
- **已知失敗與證據界線：** active-writer case 完成 reader assertions、release.set() 後，future.result 的原 10 秒等待逾時，未建立 writer 完成／後續 33-call assertion。join-failure smoke 在原 40 秒 subprocess 等待逾時，尚未到最終 report／retention／cleanup assertions；上傳證據沒有 inner smoke report。兩 worker exit 1、cleanup_confirmed=true；natural_exit_and_quiescent=false 不足以單獨證明清理前仍有活動。原生內部阻塞階段與產品根因尚未證明，不能只因來源未變就歸因環境。
- **下一候選僅 TEST_ONLY：** 補足失敗階段觀測；中間版本 root 30 PASS／15.440 秒、7 個新增 core tests 保留為階段證據。初次獨立審查發現 artifact Path.resolve 在 guard 外可能遮蔽原 TimeoutError，以及 stack 函式名稱長度未設上限；兩個診斷缺陷已修正並加入回歸。最終候選 root 33 PASS／15.426 秒、獨立 11 focused PASS；新增 core tests 共 10 個（active-writer 7、terminal 3），原 243 research cases 不變。首次指令誤在 baseline 目錄執行，因缺新 test module 而 ImportError；保留為本機 harness 錯誤，不是產品回歸，改到候選目錄後通過。新 exact-head 原生 CI 尚待，不聲稱性能修復或 native PASS。原 10／40 秒、33 evaluations／93 FULL saves、原 243 tests／6 skips、15 分鐘 job cap 及 Paper 960／30 秒保留，不改產品或工作流、不放寬 assertions、不以未變來源重跑洗掉失敗。最終原生結果由對應 PR 依來源另列，不預填 native 通過數。
- **範圍與發布：** 目前 230/290＝79.31%、剩餘 60/290＝20.69%，D8 延後非 PASS，原 230/300／全部 rubric／歷史失敗均不變。最後已核驗公開版仍為 `3ef9a740`／[unsigned preview](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38169393012-1)；main `185513f0` 的必要工程驗證尚未全通過，不以舊 PASS 宣稱新發布或正式完成。main Windows native／lifecycle 已通過，recovery／artifact 核驗／release guard 終態於本檢查點仍待完成；release guard 必須拒絕必要 Gate 失敗，尚不宣稱已執行拒絕或發布。以下 07:07 範圍決策保留原時間，其「本次文件後續」以本節新工程狀態接續。


## 目前驗收範圍：Windows 10（2026-10-12 07:07:46 +08:00／2026-10-11 23:07:46 UTC）

使用者最新明確指示：「我之後也不會在win11系統上使用 所以win11的實測可以先移調不計入」。此指示取代先前保留 Win10／Win11 雙平台的要求；僅調整本輪驗收範圍，不改產品、工作流、測試或安全門檻。

- **D8 延後、不計本輪：** 原 Windows 11 專屬 10 點自目前分母排除，狀態為 USER_DEFERRED_OUT_OF_CURRENT_SCOPE，未實測、非 PASS、未得分。原 ID／權重 10／BLOCKED／證據在 ACCEPTANCE.json 原表完整保留；未宣稱 Windows 11 技術上不支援。
- **目前進度：** 230/290＝79.31%，尚餘 60/290＝20.69%；分母＝原 300−D8 10，已通過點數仍為 230。原 230/300＝76.67%、尚餘 70/300＝23.33% 是保留的歷史基線，沒有新增 PASS。
- **剩餘原門檻：** D5 10 點（乾淨 Win10、無開發環境的安裝／啟動／升級／移除／資料保存）、D7 10 點（Win10 22H2 x64 完整流程）、M2 20 點（原完整合法分鐘行情）、M6 10 點（owner 正式 SIWC 真實授權／有界推論）、M7 10 點（乾淨 Win10 DPI／可用性／持久化）。共 60 點，原實質測試不變；M7 仍包括 1366×768／1920×1080、125／150% DPI 與原鍵盤、focus、對比、偏好重啟測試。D5／M7 共用條件中的 Win11 執行亦延後，本輪不要求，不能當已完成。
- **已發布工程基線：** main `3ef9a740f4523d50fda3bb36ad119aedcd015895`／tree `173faea2dd6c84f84c7fbfecf45512faac24c5fa`；[Quantlab 38169393007](https://github.com/yostar77612/mark-auto/actions/runs/38169393007) 全 14 jobs SUCCESS，[Windows 38169393012](https://github.com/yostar77612/mark-auto/actions/runs/38169393012) build／security／release 全 3 jobs SUCCESS。[0.2.2 unsigned preview](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38169393012-1) 已發布，installer SHA-256 `aa26ef78afdc923569c53bd7e63a4e59f850336af19d695cc8d527819e67a909`。本次重新讀取 GitHub 的來源／終態／公開 asset digest；既有發布核驗沿用原證據，不把這次文件更新當成重新執行安裝或 client 驗收。
- **仍有效的界線：** Server／Linux／fixture 不替代 clean Win10 或真實 OAuth。main 保護仍未建立、簽章仍外部受限，preview 不等於正式驗收。個人 PC／admin／UAC／VM STOP；券商 API USER_DEFERRED；無新增 live AI 或實盤授權。
- **本次文件後續：** 僅依上述範圍對帳，交由既有必要 exact-head CI／審查確認；產品來源、工作流、測試不變。詳細歷史來源／失敗保留在下方；其舊 Win11 必要、300 分母與待發布說法均按原日期解讀。

<!-- PRE_RESTORATION_CURRENT_STATUS_END -->

## 以下為本次範圍變更前的歷史快照

下方原文及失敗證據完整保留，不代表目前平台範圍、進度或發布終態。

<!-- PRIOR_CURRENT_SNAPSHOT_START -->

## 已審查來源的最終工程對帳（2026-10-11 19:11 UTC；候選已核驗、尚待整合發布）

本節僅認證已審查來源 `3c721f79db6c0f938b9a0a9383e81a61b32c9b86`／tree `ba8ecb2dfbcd799c9a63cef4c25a4c38503ba893`。[PR #11](https://github.com/yostar77612/mark-auto/pull/11) 保留其後整合／發布終態，文件不追逐未來 commit SHA；下方舊快照及失敗原文保留。

- **實作範圍：** 原始 GUI 死亡且原 helper 保有 Job Object、確認全部原 job 停止並提交匹配 receipt 後，可明確執行本機 reconciliation；不重送 AI／退還 consumed budget。helper 同亡、整機重啟或無有效 receipt 仍 fail closed；已存結果、比較、非 AI 回測及安全 Paper 操作不因此一律鎖死。這不是任意重啟復原保證。
- **已通過的來源 Gate：** [Quantlab 38165405165](https://github.com/yostar77612/mark-auto/actions/runs/38165405165) 全 14 jobs PASS。Windows research 3.11／3.12 各 237 PASS＋6 skips，195.937／234.125 秒；cores 各 1,384＝1,357 PASS＋27 skips，558.215／387.231 秒；兩個 cores 的 40 項 native WAL／初始化／workspace cases PASS。Linux 各 1,627＝1,601 PASS＋26 skips，457.198／342.191 秒；UI 1,606 PASS＋21 skips，423.982 秒。各 profile 分開列示，不累計成獨立驗收總數。
- **持久化／相容性：** 只對新 WFO journal 使用 WAL/FULL，每次原 save／commit／export 不減；既有 DELETE DB 不遷移，舊 bytes／mode 保留。每個 WFO 入口開啟前要求 patched SQLite ≥3.51.3 與 local filesystem；舊 SQLite／network path 拒絕是明示相容性限制，bundled Windows 3.54 受測。WAL 前先持久化 workspace guard，支援 replay／WFO／兩者與 guarded backup v2／restore rollback union；實際初始化 crash 與 guards 測試通過，不推論完整硬體斷電認證。
- **候選安裝包已核驗、公開發布仍待：** [Windows 38165405175](https://github.com/yostar77612/mark-auto/actions/runs/38165405175) build/security SUCCESS，原生 1,627＝1,594 PASS／33 skips，768.849 秒；80 source inputs（73 CRLF／7 raw）、41 outer files／8 nested kit entries、安全路徑／CRC／digest 均獨立相符。5 個 actual frozen helper proofs（1.355–1.463 秒）、TLS／安裝／升級／移除／設定保存及 released 0.2.1 中斷安裝復原 PASS。候選 installer 39,415,360 bytes，SHA-256 `1dafb15b208ebe0d157c0d555c00ec80a5c2ff8949d6cd42514c7b15fd01bdad`，artifact `11711923023`。PR release SKIPPED，不是公開發布；最後核驗公開版仍為 `60da0e3b`。native WFO crash／backup 是 real SQLite SOURCE tests；released EXE guard 為 fixture sentinel，不能稱完整 clean-client／OAuth／任意斷電證明。文件對帳後仍需最後 exact-head 必要 CI，通過才整合，再核驗 postmerge CI／公開安裝檔。
- **固定驗收與外部條件：** 230/300＝76.67%，尚餘 70/300＝23.33%，不因工程修補加分。D5／D7／D8 共 30 點：原 clean Win10 22H2 x64／Win11 x64 安裝生命週期；M2 20 點：完整合法分鐘行情；M6 10 點：owner 官方 SIWC 真實授權／推論；M7 10 點：clean-client DPI／可用性。每個原 ID／權重／狀態保留。main 管理保護／受信任簽章是另列未閉合限制，不創造新分數。個人 PC/admin/UAC/VM STOP；券商 API USER_DEFERRED，實盤／付費 AI／本地模型皆停用。
- **下一步有界：** 除已排定安裝驗證、文件整合及發佈查核，這次獨立複核未發現另一個有具體證據的 AUTO 功能缺口；不為增加任務而擴充功能，也不把真正外部驗收當成已通過。若新測試發現缺陷，保存失敗並修復實作，原 Gate 不降。


### PR #11 原生 research 再次取消／量測支持的新 WFO WAL 候選（2026-10-11 18:41 UTC）

- 前候選 `7f0fe6a8` 的 [Quantlab 38163211643](https://github.com/yostar77612/mark-auto/actions/runs/38163211643) 為 **13 SUCCESS＋Windows 3.12 research 在原 15 分鐘取消**；3.11 的 243 cases PASS，639.781 秒。3.12 不完整執行 863.062 秒，原 2 秒 deadline 案例先通過，其後 state INSERT 遭中斷，沒有完整 coverage 證據；不宣稱整體 PASS。cores／Linux／UI 均通過；[Windows 38163211577](https://github.com/yostar77612/mark-auto/actions/runs/38163211577) 安裝產物仍待 worker 核驗。舊失敗全保留。
- **現有量測支持且 root 已批准的產品候選：** 僅新建 WFO journal 採 WAL/FULL，不迁移舊 DB；所有原 `_save_state`／commit／export 均保留。所有 WFO 入口在開啟前無條件執行 Paper-style patched SQLite ≥3.51.3 與 local-filesystem guard。明確相容性限制：舊版 SQLite 或 network filesystem 的 WFO 存取現在拒絕；支援的 bundled Windows SQLite 3.54／local 路徑與舊 DELETE DB bytes／mode 保留，不假稱所有環境仍相容。
- Desktop workspace flags 接受 replay／WFO／兩者，WAL 前先持久化相容性 guard；guarded backup v2 與 restore rollback 使用 union。獨立來源／安全審查 PASS（36 WFO tests＋25 workspace tests），owner 125 related tests＝120 PASS／5 個既有 Windows skips。diagnostic 最終 journal mode 讀回修正仍在進行；**native Windows crash／效能尚未執行**，不得以局部測試認證。
- 研究邏輯／producer profiles 未變，原 Gate／逐次持久化／230/300 不變；不執行個人 PC／VM／券商操作。需完成最終診斷、原生 crash／性能及全部必要 exact-head Gate 後才能整合發布。


### PR #11 研究 Gate 通過／三個新 fixture 失敗，僅測試修補待提交（2026-10-11 18:12 UTC）

- 候選 `bbc63fab` 的 [Quantlab 38161825621](https://github.com/yostar77612/mark-auto/actions/runs/38161825621) 兩個 Windows research profiles 均 243＝237 PASS／6 skips，3.11 為 605.672 秒、3.12 為 531.453 秒；exact inventories／owned jobs 已核驗，第三階段實際原 deadline 案例 1.141 秒 PASS。這不抵銷 core 失敗：兩個 cores 各 1,362＝1,332 PASS／27 skips／3 個新 fixture caller FAIL，644.392／644.862 秒，原因為 path alias 未匹配、fake clock 未攔截而維持 0；全部實際新增 WFO crash tests PASS。Linux 各 1,579 PASS／26 skips，445.652／333.436 秒；UI 1,584 PASS／21 skips，507.094 秒。
- **待提交修補僅 TEST_ONLY：** 兩端 registry path canonicalization、斷言恰好一次攔截及 portable alias regression 已獨立審查 PASS；15 focused PASS，1.379 秒。`tests/test_holdout_registry_deadline.py` SHA-256 `7ef52ee099f28e6e66ea9897cd622eb7f61e26a9a3ae9a450644497c038ffc07`。產品程式、producer profiles 與原 WFO test 逐位元不變，不降低 deadline 或品質門檻。
- [Windows 38161825616](https://github.com/yostar77612/mark-auto/actions/runs/38161825616) 尚在執行；root 等待原工作終態保存證據後，才發布兩檔候選，不自動取消。Draft PR11 尚未全通過／合併；原 230/300 與全部舊失敗歷史保留。


### PR #11 原生 deadline 失敗保留／產品修補待驗（2026-10-11 17:52 UTC）

- head `56d20fed35de5df0e763cb4e610080259dd7cd34`／tree `1163f5a89c194645634c8dbc8f263828a5d8ad73` 的 [Quantlab 38159820993](https://github.com/yostar77612/mark-auto/actions/runs/38159820993) 終態 **13 SUCCESS／1 FAIL**。Windows 3.12 原有 registry 2 秒期限案例耗時 2.375 秒而失敗；research 3.11 為 243＝237 PASS／6 skips，662.922 秒，3.12 為 243＝236 PASS／6 skips／1 FAIL，627.719 秒。兩邊 inventory 完整，Job 正確 fail closed；cores 各 1,308 PASS／27 skips，真實 nested Job tests PASS。[Windows 38159821001](https://github.com/yostar77612/mark-auto/actions/runs/38159821001) 產物核驗仍待負責 worker 回報，不推定成功或發布。
- **未提交產品修補，獨立審查已通過：** 每個 pre-transaction statement 前刷新剩餘 SQLite busy budget；剩餘不足 1ms 時嚴格處理 SQLITE_BUSY、不重試，保留原 2 秒 Gate。deterministic red/green 及原 deadline 本機測試 PASS，**native timing NOT_PROVEN**。WFO 僅新檔 schema 加入既有 initial snapshot commit；不刪 `_save_state`／commit／export，既有檔案路徑不變，7 項 crash／compatibility tests PASS。
- 追加 2 個精確 producer profiles，完整保留原 13 個；profile／diagnostic tests 仍在進行。沒有採用產品 WAL、沒有修改原 Gate／工作量／持久化要求或 230/300 分數。必須取得最終新來源測試與原生 exact-head 證據後才能認證；以下舊失敗與快照完整保留。


### 本輪候選：研究測試排程修補，原 Gate 不變（2026-10-11 17:23 UTC）

- main `1619788a` 的 postmerge [Quantlab 38156717394](https://github.com/yostar77612/mark-auto/actions/runs/38156717394) 仍為 12 SUCCESS＋Windows 3.11 research 在原 15 分鐘取消；[Windows 38156717521](https://github.com/yostar77612/mark-auto/actions/runs/38156717521) 原生 1,528 PASS／33 skips、artifact 已核驗，但既有 release guard 正確拒絕發布。最後公開預覽版仍為 `60da0e3b`；建置成功不能抵銷必要 Gate 取消。
- **AUTO 修補僅限測試排程：** 相同 243 個 research cases 於兩個明確歸屬的 Windows worker processes 中各執行恰好一次；原 15 分鐘 job cap、6 個 applicability skips、序列 Paper 960 bars／30 秒 Gate 與產品持久化均不變。目前實作／本機測試進行中，native 尚待，不能稱 PASS。Root 待六檔候選審查完成才發布。
- 已完成並獨立核對的 8-round FULL storage diagnostic 只作觀察證據，不是產品 journal-mode 變更或 WAL 採用批准。230/300、原 rubric 與所有舊失敗／快照保留；clean Win10／Win11 仍待外部驗收，個人 PC/admin/UAC/VM STOP。


### main 合併後 research 再次取消／發布阻塞（2026-10-11 17:07 UTC）

- main `1619788a7ac4107f6ea84b375664bf3c384ac0ce`／tree `dbfa3b7d489cef30d36c5b3f71752beec7073141` 與 PR10 已全通過來源相同；但 [postmerge Quantlab 38156717394](https://github.com/yostar77612/mark-auto/actions/runs/38156717394) 為 **12 jobs SUCCESS＋Windows 3.11 research CANCELLED**，再次達原 15 分鐘上限，最後紀錄位於 risk/trade-gates INSERT，不能稱 PASS、也不能據此斷定唯一根因。3.12 research 237 PASS／6 skips，604.694 秒。負面原始證據留存 `quant-audit/ci-1619788a/windows311-research.log`，不未改來源重跑。
- [Windows 38156717521](https://github.com/yostar77612/mark-auto/actions/runs/38156717521) 打包仍在執行；既有 `packaging/wait_for_gates.py` 對目前 CANCELLED 的拒絕發布已獨立驗證，尚不能宣稱 release job 已執行或新版已發布。最後完整核驗的公開預覽版仍是 main `60da0e3b`／`desktop-preview-38141626727-1`。PR10 body 已於 17:06 補上合併後阻塞，先前 PR PASS 與所有舊失敗保留。
- **仍有 AUTO 工程調查：** 既有 WFO diagnostic 的 opt-in DELETE/FULL 與 WAL/FULL 固定 ABBA、完整 63-state stream 實驗正在準備；使用實際 C: `tempfile.gettempdir()`、180 秒上限、精確 durability counts／checkpoint／reopen。先前 D: RUNNER_TEMP 觀察不是 research 實際資料卷。這只是受控量測，**未修改產品 journal mode、FULL、commit boundaries、原 job／workload／15 分鐘 Gate**；不能把效能問題列為純外部授權阻塞。
- 原 300 分 rubric／230 分不變；clean Win10 與 Win11 仍 EXTERNAL BLOCKED，個人 PC/admin/UAC/VM STOP。完成實驗及獨立審查後，僅以有證據的新候選進行必要 CI；全部 Gate 通過且核驗公開安裝檔之前，不宣稱正式交付。

以下為依來源日期保留的舊快照，不代表本次 postmerge 終態。


### PR #10 c2 原生建置通過／必要 research 取消；新候選待 exact-head CI（2026-10-11 15:53 UTC）

- **已測來源：** [Draft PR #10](https://github.com/yostar77612/mark-auto/pull/10) head `c2efd0c65d112c76f46aac4b0420d8db266509bf`／tree `c6834f0d92b828a3702c6e52857d4ba92cfd7263`。[Quantlab 38150836667](https://github.com/yostar77612/mark-auto/actions/runs/38150836667) 終態 **CANCELLED，11/12 jobs SUCCESS**；Windows 3.11 research 原 243 cases 完成 242，最後一項在原 15 分鐘 job cap 被中斷，不能稱 PASS 或未改來源重跑。3.12 research＝237 PASS／6 skips，513.134 秒；兩個 Windows cores 各 1,282 PASS／27 skips，先前 8 個 fixture errors 已修復，但舊失敗全保留。
- **安裝候選不是發布：** [Windows 38150836751](https://github.com/yostar77612/mark-auto/actions/runs/38150836751) build/security PASS、release SKIPPED；原生 1,552＝1,519 PASS／33 skips，845.197 秒。artifact `11706932283` 已獨立核對 80 source inputs，5 個真實 frozen helper proofs 全 PASS。候選 installer SHA-256 `bd22911ac8f719e73575c53a1cf4fe352ef8186a4555f1bb850cec92a54fdb47`；尚未公開發布／合併，不抵銷必要 research 取消。主線仍為已發布 `60da0e3b`。
- **未提交新候選：** WFO 每次呼叫預計算 pool hashes 的三行修補；局部 20 次 authoritative reads 約 0.46→0.18 秒、約 60% 改善，不是完整 CI 或 Windows 效能已復原證明。WFO 34 PASS、另外不重疊 70 PASS、獨立 6 PASS，分開列示。新增 observation-only Windows 3.11 phase 診斷，150 秒觀察上限、沿用既有工作量／TEMP；9 項 contract tests 與獨立 9 項 PASS，原生尚未執行。兩組工作已凍結且審查 PASS。
- **最後 root 定向證據：** WFO 34＋diagnostic 9＝43/43 PASS，21.092 秒（與前述數字重疊，不重複相加）；`research-timeout-analysis/root-final-focused.log` 留存雲端。static 268 files／0 findings；local history NOT_RUN，仍需 native CI。`quantlab/core.py`、`quantlab/research_analysis.py`、`quantlab/desktop_runtime.py` 與 c2 逐位元相同。
- **固定界線及下一步：** 原有 required jobs／workloads／15 分鐘 cap／FULL／commit boundaries／驗收 ID、權重及 300 分母不變；原 230/300 不加分。保留原 clean Win10／Win11 EXTERNAL BLOCKED 及個人 PC/admin/UAC/VM STOP。針對新 exact head 執行完整必要 CI，全部 Gate 通過才整合；不能把局部量測或額外觀察診斷當作原 Gate PASS。雲端原始證據 `quant-audit/ci-c2efd0c6`、`research-timeout-analysis` 留存，非 repository 檔案。

以下日期較早的快照原文完整保留，不能用作本次候選的最新終態。

### PR #10 保留原生失敗／修補待重新驗證（2026-10-11 15:17 UTC）

[Draft PR #10](https://github.com/yostar77612/mark-auto/pull/10) head `d7a295799f27ffcb9c655d2d032296771c1510bc`／tree `6437608765ecb360e8f84c31c770b2c3d1deee02`：NATIVE_FAILED_FIX_IN_PROGRESS。[Quantlab 38149301471](https://github.com/yostar77612/mark-auto/actions/runs/38149301471) 的 Linux 3.11／3.12 各 1,549＝1,525 PASS／24 skips，340.258／482.437 秒；UI 1,549＝1,530 PASS／19 skips，497.412 秒。Windows core 3.11／3.12 各 1,306＝1,271 PASS／27 skips／8 ERROR，610.317／590.896 秒；5 項 ledger SQLite test connection cleanup、1 項 integration SQLite cleanup、1 項 absent setsid test patch、1 項 fake Process／real Job Object fixture，修補已通過下列定向與獨立審查，仍不能宣稱完整原生 CI 通過。兩個 cores 的真實 production helper 3 個 native cases 均 PASS，但不能抵銷整體 FAIL。[Windows build 38149301429](https://github.com/yostar77612/mark-auto/actions/runs/38149301429) 終態 FAIL：CPython 3.13.16 原生 1,549＝1,508 PASS／33 skips／相同 8 ERROR，916.171 秒；production helper 3 cases 與 prototype 3 cases 均 PASS。尚未進入 frozen／installer／TLS／lifecycle，release SKIPPED，security PASS，沒有新安裝檔。原發布基線與下方 precommit full 失敗均保留。Quantlab 終態 FAIL，10/12 jobs PASS；Windows research 3.11／3.12 各 243＝237 PASS／6 skips，687.587／785.762 秒。

**修補 READY_FOR_NATIVE_REVALIDATION：** 獨立稽核另發現產品 `_connect` setup exception 的 SQLite handle leak，與上述 fixtures 分開；真實 valid-header／corrupt-Btree 與 injected-setup regressions 已 red-before／green-after。最小 close＋reraise 保留 PRAGMAs／FULL／deadlines；最終 3 個 source/test files 已凍結，root 42 focused PASS（26 ledger＋14 integration＋2 real-spawn），13.726 秒；獨立 40 PASS，8.506 秒，各自列示。未修改 native helper file，Windows 再驗仍待；原完整 candidate aggregate 仍 FAILED，不以 focused PASS 改寫。

有界真實行情證據：TAIFEX [dataset 20668](https://data.gov.tw/dataset/20668) 的 [政府資料開放授權條款](https://data.gov.tw/license) 已有特定資料集來源對應；兩份官方檔案選定契約／時段共 684,015 genuine ticks，34 個空分鐘未填補，不推論為 feed 遺漏。結果仍 provisional_unverified／non-rankable，不能取代全歷史／TAIEX minute 權利或 M2 PASS，不增加原 230/300。完整 raw provenance 與稽核留存雲端 `quant-audit/legal-minute-sources/sample-validation/RESULT.md`（非 repository 檔案）。

## 原始 Job 停止證據復原候選（2026-10-11 14:28 UTC；提交前來源快照）

- **最後已發布基線不變：** [PR #9 最終證據](https://github.com/yostar77612/mark-auto/pull/9) 已確認合併 main `60da0e3b4f5c230f529a99e8ba5794fd2b232bfb`／tree `a04dddae25781b94d4759a13c77a36e319b4730c`；[Quantlab 38141626721](https://github.com/yostar77612/mark-auto/actions/runs/38141626721) 全 12 jobs SUCCESS，[Windows 38141626727](https://github.com/yostar77612/mark-auto/actions/runs/38141626727) build/security/release SUCCESS。Server 2022 原生 1,450＝1,417 PASS／33 skips，不能替代 clean Win10。[已核驗 unsigned preview](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38141626727-1) installer 39,355,463 bytes，SHA-256 `917d39c5d73bb70160b7e3771c5fb11d4297904119ac4e9a8fe85021b342a47e`。以下舊 PR #9 Draft／待 CI 字樣只屬保留歷史，不代表目前狀態；後續終態以對應 PR 證據為準，不為追逐文件 SHA 重建相同產品。
- **新候選 FOCUSED_TESTS_IN_PROGRESS：** `analysis_recovery.py` 原始 launch／stop ledger、`analysis_recovery_windows.py` helper、runtime／UI 衝突操作 guards 及 frozen hook 工作中；尚未新 exact-head CI、發布或取得 production／native Windows PASS。前次完成分支已刪除，預計重用 `agent/windows-release-validation` 名稱；新 PR 尚未建立。當前定向測試進行中，不列未完成的總數。
- **狹義能力界線：** 僅針對原 GUI 死亡而 helper 仍持有原 Job Object 並確認全部原 job 停止、提交匹配 stop receipt 後的明確本機 reconciliation；不得以 PID／Job 缺席或 journal completed 推定停止。helper 與 GUI 同亡、reboot 或缺 receipt 仍未知並限制衝突操作；不重送 AI、不退還／重設 consumed budget，不聲稱任意整機重啟復原。
- **可用性與可信界線：** incomplete／corrupt controls 對分析、來源變更、備份／還原等衝突操作 fail closed，不一律封鎖保存結果、比較與非 AI 回測；已有雲端 Qt 非 AI 可用性測試，但目前來源最終測試與實際 client 均未核驗。ledger hashes 是一致性檢查，不認證同使用者竄改或整體 rollback；ownership／registration／workspace／restore epoch／原 receipt Gate 不能省略。
- **14:46 UTC 最新原範圍／安全指令：** 保留原 Windows 10 與 Windows 11 驗收需求，除非使用者再次明確變更；目前兩者均 EXTERNAL BLOCKED，先前 Win11 取消指令僅保留為歷史。券商 API 仍 USER_DEFERRED；個人電腦所有 admin／UAC／VM 工作停止，TestLab 保留。實際 SIWC／OAuth、完整資料權利及 signing／protection 仍未閉合。原 ID／權重／300 分母與 230/300 歷史基線不變，復原工程不因此加點。
- **目前狀態分列（14:50 UTC）：** 實作＝原始 Job 復原候選與後續修正進行中；已驗證＝前述 PR #9 已發布基線，不能沿用為新候選 PASS；外部阻塞＝原 clean Win10／Win11、真實 OAuth 等；發布準備＝最終定向／獨立審查／新 exact-head native CI 尚待，未發布。
- **中間來源完整回歸保留：** tree `1f804e8861201512fc957df747f7cd82bf116edb` 的 full56372 終態 exit 1，1,548 項＝1,520 PASS／26 SKIP／2 FAIL，694.999 秒；兩項失敗均為 TEST_ONLY `_busy` adapter 不接受新增 `refresh_recovery` keyword。UI worker 修正 adapter，不更改 assertions；後續來源尚有獨立修補，最終 focused／native CI 仍待。此中間來源失敗不刪除、不追溯改 PASS，不代表已通過 production recovery。


### 以下為保留的舊來源快照與原始失敗；不得用於認證本候選

### PR #9 保留原生失敗，修正 READY_FOR_NATIVE_REVALIDATION（2026-10-11 12:27 UTC）

- Draft PR #9 head `2459ad62` 的 [Quantlab 38138317785](https://github.com/yostar77612/mark-auto/actions/runs/38138317785) 終態 FAIL。Linux 3.11：1,448 PASS／21 skips、425.277 秒；Linux 3.12：1,448 PASS／21 skips、447.131 秒；UI：1,448 PASS／16 skips、323.886 秒，7 個新增 Qt 測試實際 PASS。Windows research 3.11：243 PASS／6 skips、720.942 秒；3.12：243 PASS／6 skips、510.297 秒。各 job 分開列示，不相加。
- Windows core 3.12：1,205 PASS／27 skips／1 FAIL、398.629 秒，新 prototype helper-before-GUI cleanup 回報 Errno 5。core 3.11：1,205 PASS／27 skips／同一 FAIL＋1 ERROR、550.315 秒；既有 wrong-commit-count 測試於原 10 秒期限下耗時 10.124 秒且缺 returncode。舊失敗保留，不以未變更來源重跑洗掉，不能從原 log 指定唯一慢階段。
- test-only termination 修補已獨立審查，SHA-256 `5bb6ed2bec7ca515b7810ac318f5945b42fa90145add0b4a62a2b532bdef50ef`；要求 exact handle 在原 7 秒 cleanup 內 signal，1 個 deterministic PASS／3 Windows SKIP，真實 Windows 再驗仍待。`tools/diagnose_paper_replay.py` 狀態修補改報真正 reap 的 exit／未知 None，明確拒絕認證 timeout／error；原 120／FULL／delete-reopen／10 秒及 assertions 均保留。此為證據狀態修正，未證明效能已修復；診斷修補最終獨立審查 PASS，另有 4 個 targeted PASS（含真實 120／FULL／10 秒）；root 合併 `tests.test_paper_diagnostics`＋`tests.test_windows_recovery_feasibility` 23 項＝20 PASS／3 native Windows SKIP、5.096 秒（留存雲端 `quant-audit/ci-fix-focused.log`，非 repository 檔案）。修補 READY_FOR_NATIVE_REVALIDATION，待新 exact head CI；不宣稱效能修復。
- [Windows installer 38138317766](https://github.com/yostar77612/mark-auto/actions/runs/38138317766) 終態 FAILED：CPython 3.13.16／Qt 6.12 原生 1,448 項＝1,414 PASS／33 skips／1 FAIL、845.457 秒，同一 helper-before-GUI cleanup Errno 5，其餘 2 個 prototype cases PASS。7 個新增 Qt cases 實際 PASS，但 frozen／installer／lifecycle 尚未執行、release skipped，未產生新 installer；log 留存雲端 `quant-audit/ci-2459ad62/build.log`（非 repository 檔案）。PR #9 維持 Draft，main `f2eb4aaf` 與最後發布版不變；以下 READY_FOR_NATIVE_CI 為本 candidate 前次提交前狀態，現為修正／再驗待完成，沒有新增驗收點數或完整重啟復原。


## 最新發布基線與重啟復原界線（2026-10-11 11:49 UTC）

- **PR #8 已交付：** main `f2eb4aafba161ea89fd0457c20e21a06bea5918c`，tree `9566cffc6018650bd8133778f783f41e73509e2a`。[Quantlab 38134959143](https://github.com/yostar77612/mark-auto/actions/runs/38134959143) 全 12 jobs PASS；[Windows 38134959133](https://github.com/yostar77612/mark-auto/actions/runs/38134959133) build/security/release PASS，原生 1,425 項＝1,392 PASS／33 applicability skips。這是 Windows Server 2022 證據，不能替代 clean Win10。
- **已核验 unsigned preview：** [0.2.2 Release](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38134959133-1)，installer 39,355,004 bytes，SHA-256 `7aaf832869ba0d12a6f07a93acda7d9c36e1fa5fa34c6248d0942c012d391587`；77 個 source inputs 相符，公開 installer 已獨立下載核對。留存雲端診斷檔（非 repository 檔案）：`quant-audit/ci-f2eb4aaf/independent-installer-assessment.json`；可公開檢索證據見上述 Release／CI 與 [PR #8](https://github.com/yostar77612/mark-auto/pull/8)。TLS 僅 ephemeral loopback；安裝器中斷復原不等同分析 GUI 重啟復原。
- **新修補 READY_FOR_NATIVE_CI（未發布）：** `tests.test_desktop_analysis_discovery`＋`tests.test_reporting` 根整合 29 項＝22 PASS／7 native Qt SKIP，0.685 秒；雲端診斷 log `quant-audit/checkpoint-discovery-focused.log` 並非 repository 檔案。worker 另跑 7 項既有 strict-reader／recovery PASS，分開列示、不合併為同一 suite。變更僅 `desktop_ui.py`、`quantlab/reporting.py` 與新增 `tests/test_desktop_analysis_discovery.py`；research analysis／runtime／producer profiles 不變。初次 root＋獨立審查發現舊 checkpoint 選擇會遮蔽非同步 completed 結果，已改先選取返回的 analysis identity 再顯示並新增 native Qt 回歸，保留此初次診斷；最終獨立審查 PASS，獨立測試另為 22 PASS／7 Qt SKIP，strict worker adapter 字節不變；root 另跑完整 `tests.test_research_analysis` 31 PASS／0 skip，9.902 秒（留存雲端診斷 `quant-audit/checkpoint-analysis-regression.log`，非 repository 檔案），不與其他 suite 加總。原 `quality_gate.scan` 掃描遠端 255 檔 manifest＋2 個新測試共 257 檔，0 findings；本機 history scan NOT_RUN，待原生 CI。native Qt、Windows 實驗執行、exact-head CI 與發布仍待，不降低 Gate。journal-only 部分僅列出存在性 metadata，不讀取內容、不宣稱有效或 completed 結果；明示未核驗／unreconciled，不授予修復、重試、候選使用或重新推論權限。
- **完整 GUI 非正常重啟復原＝ENGINEERING BLOCKED：** 原 host 的程序樹停止證明不耐久；新 manager 的 proof 為空，不能用 PID 消失、QLockFile、completed journal 或逾時推定停止。這是工程缺口，不能歸因於 Win10 授權或要求使用者恢復本機管理員操作。固定發布來源：[proof 初始化](https://github.com/yostar77612/mark-auto/blob/f2eb4aafba161ea89fd0457c20e21a06bea5918c/quantlab/desktop_runtime.py#L940-L946)、[原 manager／registration admission](https://github.com/yostar77612/mark-auto/blob/f2eb4aafba161ea89fd0457c20e21a06bea5918c/quantlab/desktop_runtime.py#L1088-L1091)、[原 host tree join](https://github.com/yostar77612/mark-auto/blob/f2eb4aafba161ea89fd0457c20e21a06bea5918c/quantlab/desktop_runtime.py#L1252-L1253)。詳細評估與 probe 留存於雲端診斷檔 `quant-audit/restart-recovery-assessment/assessment.md`，非 repository 檔案，未聲稱 probe 已公開提交。Linux 真實 worker 曾在 supervisor abrupt exit 後仍存活；Windows restart 限制為來源分析，尚非真實平台重啟實驗。
- **未來固定復原 Gate：** 分離原／重啟 supervisor，含存活 descendants；驗證精確 ownership、PID reuse／copied或restored authority拒絕；真實 Windows Job Object 與 Linux process group；於 proof publication／reconciliation 中途終止；原 provider／receipt／request／exclusive lock 均不放寬，復原零 AI transport、零 budget reset、零重送。未實作或通過此 Gate，不聲稱完整復原。
- **範圍／安全不變：** Win11 USER_CANCELLED、券商 API USER_DEFERRED，皆非 PASS；所有個人電腦 admin／UAC／VM 操作停止，TestLab 保留。clean Win10、實際 SIWC／OAuth 及原其他外部限制維持。230/300 僅原固定範圍歷史參考，不增加點數或重算新分母。

- **待執行的有界 Windows 可行性實驗：** 僅新增 `tests/test_windows_recovery_feasibility.py`，不修改產品 supervisor。以 synthetic GUI stub／task-bound helper／單一 owned Job Object 驗證：GUI 先死亡而 helper 保留原 handle、觀察原 job 歸零後才寫 TEST-ONLY receipt；helper 在 GUI 死亡前或 GUI 死亡後／quiescence 前死亡，均不得寫 receipt。最多 4 children、temp files、90 秒硬 watchdog，正常流程用快速 barriers。三個 Windows cases 已撰寫，compile PASS、本 Linux 環境 3 SKIP；setup ownership／未發布 handle／watchdog 的初次審查缺口已修正，最終獨立 static review PASS 僅准備供雲端 Windows CI 執行，測試檔 SHA-256 `4dfdd7b7dad9fdfdf70ab0ffd9cc9b8d50319adab2d6d78a568f7dae8332e261`。未改產品程序管理或復原。Windows 尚未執行，可由既有 Windows Server CI 執行；這是 investigation，不是復原實作或 PASS，clean Win10／非提升權限／copy-restore／security／admission 均尚未核驗，不增加分數。

### 以下保留先前來源與檢查點；其待 CI／未發布狀態不代表上述已發布 PR #8

### 10:39 UTC 新修補的定向驗證（未合併／未發布）

Paper replay 的 quarantined fill 不再消耗 pending plan/cursor，duplicate 需核對真實已保存成交；backtest 的 roll_close 被拒絕即停止，不切新合約或猜測補償下單；SIWC 串流所有已提供的 response ID 各自驗證，不能用另一欄遮蔽矛盾。根目錄整合定向 159/159 PASS（26.157 秒），獨立 review 及 11 項抽驗 PASS。新版本精確來源 profiles 去重後 78 項回歸 PASS（63.123 秒、0 skip），獨立 6 項 PASS；11 個已發布 literals 字節不改，只新增兩個 exact tuples。初次測試撰寫的 setup error 與重複 discovery 保留為診斷，不冒稱通過。新 exact-head 完整 CI 仍待執行，原持久化/效能 Gate 不變；這不是正式推論、clean client 或已發布來源的驗收。

## 現行雲端接續與本機限制（2026-10-11 10:31 UTC）

- **已核對的發布基線：** main `958df3229b1d075e3799b8856ccffb34aec5f056`，tree `4ba142f9ad190bf5c9889a243d74af95a1ce2760`；PR #7 已合併。Quantlab [38105610595](https://github.com/yostar77612/mark-auto/actions/runs/38105610595) 全 12 jobs 成功，Windows [38105610623](https://github.com/yostar77612/mark-auto/actions/runs/38105610623) build/security/release 成功，沒有本來源尚未修復的 CI 失敗。Windows Server 2022 原生測試 1,408 項：1,375 PASS、33 applicability skips；不能替代乾淨 Win10。
- **已核驗預覽版：** [0.2.2 unsigned preview](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38105610623-1)。公開 installer 39,367,658 bytes，SHA-256 `ad89b652662516f02d1abeb6f648fd5b6e34e4263ed416254fdb04914a6c18ea`；公開檔案獨立下載核驗，77 個 source inputs 相符。這是以下新工作之前的發布基線，新修補不得冒用此 PASS。
- **使用者範圍修正：** 07:25 UTC 明確取消 Windows 11 驗收，只保留 Windows 10 22H2 x64。Win11 記為 USER_CANCELLED，不是 PASS。券商 API 於 03:05 UTC 由使用者暫緩，不能再要求申請券商權限作為目前工程前提；免費公開行情的完整性及合法使用、SIWC 真實授權仍各自判斷。
- **歷史分數：** 原固定表最後核驗 230/300（76.67%）；保留其原 ID、權重與證據。這是修改範圍前的可比較基線，不是新 Win10-only 範圍重算的完成率。未自行扣分母或把取消的 Win11 項目補為 PASS；新的範圍對應尚未定案前不聲稱更高百分比。
- **Hyper-V 變更來源：** 新主機初查為 Disabled。08:44 UTC 使用者在已告知元件、服務、開機狀態及重開機影響後批准啟用；08:48 UTC 官方 `Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All -NoRestart` 成功，結果 Enabled、RestartNeeded=true、exit 3010。不是既有已啟用狀態，也不是 10:31 接續輪新增安裝。使用者 09:53 UTC 自行回報重開機；普通查詢確認 vmms Running 及模組可載入。
- **管理員查詢證據缺口：** 後续固定唯讀 launcher 在 RunAs 返回後才寫入啟動紀錄，工具 session 失效且無結果，不能證明該 Windows 程序已退出，也不能認定一定卡在 UAC。未核實的 boot time / HypervisorPresent 等保持未知，不盲目殺程序或重試。原本啟用成功證據與後续查詢失敗分開記錄。
- **最新安全界線：** 10:31 UTC 使用者要求停止所有管理員命令、UAC、Hyper-V 排查及 VM 建立/啟動/修改。TestLab 既有檔案與證據保留；不重裝、不自行重開機、不關閉歸屬不明程序。凡需管理員或 VM 的後续驗收標為 EXTERNAL BLOCKED，不以此停止雲端工程。
- **環境分界：** 新 Win10 主機曾測得可用 RAM 約 19.74 GiB，不能沿用舊筆電記憶體不足的數據，也不代表未來起測仍足夠。Win10 乾淨客體合法授權尚無，Sandbox 專屬停止/報告保存/20 分鐘期限未獲實證；不在主要使用者環境直接安裝替代。原 4 GiB guest、host 起測至少 6 GiB、20 分鐘與零實盤規則不變。
- **本轮 AUTO：** 依實際 reproducer 修復 Paper replay、研究串流身分與換月正確性；先定向回歸及獨立審查，再對新 exact head 執行必要 CI。已通過的舊來源不無意義重跑，歷史失敗不刪除；新增工作尚未驗收或發布，完整結果以同一工作 PR/後续 checkpoint 為準。

### 以下為保留的前次檢查點，不代表本輪最新終態

## 雲端接續修復／提交前檢查點（01:53快照；02:09修正見下節）

- **基線核對：** main `b04545b6caacf9ee2f3f1c8016e11cfcaeab5451`，tree `eb7372d0f3004655053e79c0c0d6736518003a09`；PR #6 已合併。Quantlab `38096213220` 與 Windows `38096213180` 全部成功。最新核驗的 [0.2.2 unsigned preview](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38096213180-1) installer 為39,358,670 bytes，SHA256 `44eb59834f641342105d3511c440348c6d02fd16b95e6eee1e797cb2bbd0c15d`。此下載是修復前基線，不能代表以下新變更已發布。
- **AUTO／實際缺陷修復：** 分析資料庫已提交但 JSON 匯出中斷時，原本嚴格讀取連同明確復原皆失敗；現將完整驗證的 journal 讀取與 projection 比對分離，只有明確停止子程序且持鎖、原 provider／receipt／request 一致後才可修復缺少或精確舊 running projection。普通讀取仍嚴格；不重送模型請求、不退還額度。另拒絕同一契約／交易日／時段的矛盾邊界，防止重疊聚合 candles；官方正常匯入路徑未發現已受影響。
- **復原範圍限制：** 本修補處理原 host 仍存活、已證明 worker 子程序樹停止的復原。整個 GUI／host 重啟後，記憶體中的 stop proof 不存在，缺少 JSON 的 journal 也未列入保存選單；不得宣稱本修補已完成整機／完整應用重啟復原。既有 QLockFile 與 WFO ownership 記錄均不能重建原子程序樹停止證據；維持保守 BLOCKED，不能藉放寬 descendants-stopped Gate、持鎖即當停止或偽造 proof 解決。另開 completed-only projection 寫入屬新 admission class，未在本修補暗中啟用。
- **本批工程狀態：** 行情／chart focused74項、分析／桌面focused61項及獨立審查通過。完整雲端回歸1392項＝1371 PASS／20原有平台或環境skips／1 FAIL，830.836秒；失敗為WFO最終holdout變動隔離測試，其中一次評估為ValueError，正在定位，失敗紀錄保留於 `quant-audit/resumed-full-tests.log`。新來源CI尚未啟動；本批修補不能計為已交付。全專案沒有另一份固定工程功能分母，不捏造工程百分比；正式驗收仍230/300＝76.67%，剩餘23.33%，原ID／權重／門檻不變。
- **新增可重現的 cleanup 缺陷：** 原始WFO失敗在7次定向診斷（462次真實 worker 評估，含Qt parent）未重現，因此不聲稱已證明原失敗原因。但 delayed-reap 測試證明 `_run_bounded` 會對尚存活的 owned worker 呼叫 `close()`，拋 ValueError，campaign 可能繼續保留下一個評估額度。新修補僅在原 global deadline 剩餘時間內等待 owned child 終止，未證明停止即 ResourceTimeout 封鎖後續工作，不關閉 live handle、不捏造 subtree proof、不提高原 timeout。歷史 producer literals 保留，待新完整 Gate。
- **修補後驗證：** cleanup／研究／WFO focused82項、provenance focused72項通過；分析61項、行情74項通過，範圍各自列示，不當作完整suite加總。獨立審查與static／history secret gate通過。第二次完整回歸正針對實質修補後來源執行；Draft PR與exact-head native CI接續，最終終態和發布來源記錄於該PR，不能以本提交前快照宣稱CI已通過。原失敗與資料／timeout／權重均保留。
- **本機暫停：** 依使用者最新指令，停止 Sandbox 啟動、RAM 輪詢及本機驗收；只保留已準備檔案，不關閉其他程式。Windows 11 Sandbox 安裝驗收與乾淨 Windows 10 22H2 驗收均 BLOCKED；真實本人 ChatGPT OAuth／訂閱推論、券商行情授權均 EXTERNAL BLOCKED。雲端工作不依賴上述授權；不在主使用者環境安裝替代。
- **隔離停止研究結論：** `.wsb`／`LogonCommand` 可設定客體與保存專屬輸出，但舊 client 未有經驗證的專屬 session 識別及20分鐘 outer teardown。客體 `shutdown.exe` 不等同已證明釋放 host Sandbox；`CloseMainWindow` 可能要求確認或拒絕。保持原20分鐘與記憶體限制，無全域 taskkill／批次 VM 停止。官方參考見品質風險文件。
- **接續入口：** 同一雲端 checkout 保留原本歷史與未提交成果，先完成以下修復的完整測試、獨立審查、Draft PR、exact-head CI；通過適用工程 Gate 才整合及重建 preview。正式發布仍須所有原始外部驗收，不以 Server 或 fixture 冒充。

### 02:09 UTC 修正後定向驗證

- 恢復原cleanup allowance後，research50項與WFO34項通過，Qt parent相鄰hang checks3項通過；額外保留舊0.55秒delayed-reap workload為明確拒絕案例，全部11個cleanup tests通過。原1秒／4秒與no-child測試本體未改。新profile72項通過，九個歷史profile來源字節不變，僅更新兩個尚未發布的candidate pins。獨立review與static/history gate通過。
- 最終來源仍待同一PR #7的新完整原生CI；未合併／未發布，不把定向PASS取代完整Gate。原candidate4167b8a4及下列失敗保留在Git／CI，不force push。

### 02:07 UTC 原生回歸修正（不刪除前述失敗）

- PR #7 candidate `4167b8a4`：第二次雲端完整1405項＝1384 PASS／20 skips／1 FAIL，763.944秒。Linux3.11、Linux3.12與UI原生CI均在原本 `test_hanging_generator_is_killed_and_budget_consumed` 失敗：測試開始時的舊PID在結束時消失，指出前一個timeout測試留下尚未回收的子程序。Windows3.11 core/research及Windows3.12 core當時通過，不能抵銷Linux失敗。原生日誌及第二次log SHA256 `34cbba0461ee329d8ae68e5fcc9c2e648a143e7939f743d157280685dc70f1eb` 保留。
- 根因：candidate 把所有cleanup joins限制為 evaluation deadline 剩餘時間，期限已到時變為零，移除了原實作既有的terminate0.2秒＋kill0.2秒回收餘裕。修正恢復原有bounded cleanup allowance，evaluation admission deadline、1秒workload／4秒no-orphan測試與所有正式效能門檻不變；仍須證明停止，不以送出kill視為完成。
- 本輪採分層驗證：先重現相鄰 hanging-backtest／generator 流程及定向 regressions，再用新exact-head完整Windows／Linux CI驗收。不把舊1405失敗改成PASS，也不為相同來源額外重跑第三套雲端完整矩陣；最終完整Gate由CI原有全部測試提供。

### 前一輪已完成交付的證據（保留）

## 目前交付與驗收對帳（2026-10-10 23:42 UTC）

- **已發布0.2.2 unsigned preview：** [已核驗的 Release](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38094283911-1)。產品來源固定為 main `9d35c7d760acc88720f3379b2413423a0991152f`、tree `79c319746fa19e19b19a8b8ed51f3b6b09806216`；PR #6已合併。Quantlab `38094283558` 全12 jobs PASS；Windows `38094283911` 原生1384項＝1353 PASS／31個原平台或profile skips，frozen／TLS／安裝升級復原與資料保留 PASS，公開安裝檔本體已獨立下載核對。
- **M4完整20點現已PASS：** 依Roadmap §19原定表單標準，普通研究split／預算／選擇、策略／回測／比較／Paper／對帳與風控均有型別表單和可讀結果；實際Windows Qt與真實worker、PF／描述性Sharpe及假設／未定義原因、正常報告接線及停損／停利／持倉成本參考快照已驗證。不是只憑mock加分；先前條件式postmerge與實際Release門檻現已滿足。
- **現行固定分數230/300＝76.67%，剩70點／23.33%：** 研究100、桌面70、市場60；只增加原M4的20點，其他ID／權重／門檻／狀態不變。D5／D7／D8仍需clean Win10/11（30點）；M2完整市場分鐘資料／合法自動使用權限（20點）、M6真實owner授權SIWC訂閱呼叫（10點）、M7clean-client DPI／易用性（10點）仍未通過。OAuth不是M4表單Gate的額外隱藏依賴，也不因M4 PASS而取得M6證明。
- **已交付範圍與界線：** 固定／saved候選WFO及必要PF／Sharpe／參考線已實作、原生驗證並隨preview交付；frozen WFO為合成2-fold／22次評估與重新讀取，非獨立真實市場研究或Paper資格。原Oct8 protocol仍因170 consumed bars而BLOCKED_NO_RUN，不改window／registry。main保護管理權限、可信簽章及非委託的實際帳戶／client驗收仍受限；實單停用，禁止本機AI及paid API／credits fallback。
- **前一輪僅文件：** 此checkpoint不是安裝檔的新build／簽章／CI結果，不更換上述產品來源或manifest。當時AUTO只剩文件審核／發布；審查未找到可直接補做的M4／PF／Sharpe／參考線／WFO程式或授權驗證缺口，不新增功能或主動重跑未變更大套測試；自動觸發的工作流仍依其實際結果判定。完整證據見 `ACCEPTANCE.json` current_snapshot及 `quant-audit/ci-9d35c7d7/independent-main-release-assessment.md`。

<!-- PRIOR_CURRENT_SNAPSHOT_END -->

## 以下為保留的歷史契約、決策與檢查點

截至本次對帳以前的210/300、M4 PARTIAL、IMPLEMENTATION_PENDING、失敗／取消／尚未發布等文字保留其原時間與來源；不代表目前終態。原需求、未解除安全底線及非本次明示更新的gate仍有效；歷史失敗不刪除、不追溯改為PASS。

<!-- HISTORICAL_STATUS_START -->
## 最新接續檢查點（2026-10-10 22:42 UTC）

- **來源保全：** 同一分支 `agent/windows-release-validation`／PR #6。遠端 `80042d00e7c7cdea3b7765550ce5c4b180ff44e1` 與本機 `e97a404` 同 tree `e1184e7f76bed0b6d94dd8dad2f9d130066f079d`，已 fetch／diff 核對；原 commits／bundles 保留、未 force push。下列後續修補正準備更新同一 PR，尚無新來源原生 PASS。
- **最後原生結果：** [Quantlab 38090502554](https://github.com/yostar77612/mark-auto/actions/runs/38090502554) 11 jobs PASS／Win311 core FAIL。Paper960根／30秒在兩個 Windows core 均 PASS；research311／312 各227項＝223 PASS／4 skips，551.047／612.548秒。Win311 core1131項＝1103 PASS／27 skips／1 FAIL、728.778秒，唯一失敗為完整 smoke 的原40秒期限，尚未證明原逾時原因。Win312 core1104 PASS／27 skips、305.666秒；Linux311／312各1340 PASS／18 skips、280.395／438.174秒；UI1345 PASS／13 skips、455.144秒。受測 PR merge `87940c7b7ce4b82a30ff50fcd292a6bf62d437d9`；不是後續修補來源的結果。
- **安裝阻塞：** [Windows 38090502547](https://github.com/yostar77612/mark-auto/actions/runs/38090502547) 原生1358項＝1327 PASS／31 skips、1089.435秒，EXE compile PASS，frozen TLS FAIL，後續安裝／升級／移除未執行、Release skipped。artifact11684142251、77,672,343 bytes、SHA256 `7f61657d4bc00085b00b45cc9a59077810da3ce89f0cbc8aca7d182d246330dc`、CRC核對；TLS report在runtime validation前置失敗，不是外網下載失敗。
- **AUTO修補已保存：** `a53f11f` 指標超限的controls／preferences／曲線原子一致性與逐一修復；`6c77739` 僅9行exact builtin scalar快路徑，保留574次COMMIT／export、637個歷史snapshot bytes／hash與7個歷史producer literals；`4d77e7b` 正確OpenSSL tuple `(3,5,0,9,0)`、原DLL／TLS安全pins不變，以及保留PIPE EOF條件的bounded timeout輸出擷取。舊file-backed草案因可能弱化未登錄子程序的EOF Gate而捨棄，未套入產品。
- **本機修補驗證：** 指標21＋12 PASS；scalar首次定向命令15 PASS／1錯拼module import ERROR，原log保留，正確後續39 PASS。scalar階段受影響research227 PASS、322.035秒，來源hash核對不變；其後診斷擷取修補按下述定向驗證分列，不追溯算入此227項。最終diagnostics21 PASS／15.964秒，TLS＋完整terminal28 PASS／105.701秒。static/history0 findings。最終pinned環境discovery1384＝1157core＋227research，只是清單，不宣稱完整新來源全套PASS。Linux單次固定case無profile順序比較12.690→8.926秒，29.66%較低；Linux3.12.14／SQLite3.53.1，不當成Windows改善量測。
- **量測排除：** WFO Windows診斷5個完整63-state rounds均核對，PERSIST commit均值73.662ms反而高於DELETE71.727ms；總round差約11.355ms，不足以支持改持久化模式。保留DELETE／FULL及既有Paper WAL／FULL。診斷在D: temp、研究default temp／不同VM，不能宣稱物理volume等價或證明原CI磁碟原因。
- **EXTERNAL BLOCKED：** 真實ChatGPT owner grant／訂閱推論；clean Win10 22H2 x64／Win11 x64；main protection目前仍protected=false、rulesets=[]，現有App無Administration；可信簽章未成立。KVM已真正執行固定5-byte自撰payload、2次KVM_RUN／cleanup／exit0，但不是Windows驗收。官方Win11 Eval媒體實際EULA已取出，允許虛擬device與remote-only限制並存，未能確認hosted CI適用權利；不是技術上沒有VM，也不假稱全部CI皆禁止。未註冊、接受條款、啟動Windows或操作使用者電腦。
- **進度與下一步：** 固定210/300＝70%，剩餘30%；main仍94aca467，公開版本仍0.2.1 unsigned preview。依序更新此分支 → 新exact-head完整CI／frozen TLS／安裝生命週期 → 審查產物與失敗 → 必要Gate通過才整合。不得因上述外部項目停止其餘AUTO工程，也不將Mock或Server算成實際訂閱／clean client。最新CI終態集中於[PR #6](https://github.com/yostar77612/mark-auto/pull/6)，本文件保留本次推送前來源界線，不因報告更新重跑無變更大套測試。

### 較早12:14檢查點（以下保留歷史，不能取代上方最新狀態）

## 當前整合狀態與最後已驗證基線（2026-10-10 12:14 UTC）

### 11:16 使用者更正：官方訂閱為必要 AI 路徑（取代先前選路）

官方 **Sign in with ChatGPT（SIWC）訂閱整合為必要需求**，第一階段已root套用：AI策略中心單一登入入口沿用既有官方PKCE/OIDC／受管worker，補齊帳戶／模型顯示、明示included-only確認及取消／關閉保護。本機模型UI、設定、runtime、下載器、打包與舊CI推論要求已移除；paid API／自訂endpoint入口亦關閉，無credits fallback；獨立TLS證據與歷史producer／研究紀錄保留。此更正只替換AI選路，不降低其他驗收；M4／M6仍PARTIAL、210/300＝70%，原研究隔離、耐久、工作量／deadline、安全、安裝及clean-client gates不變。

included-only確認與ChatGPT Settings > Usage指引已實作，仍是使用者自述，不是server credits設定查證或金額上限保證。官方能力邊界見[Help Center](https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites)及IMPLEMENTATION_CONTRACTS同日更正。實際OAuth grant／模型呼叫仍NOT_RUN、EXTERNAL_BLOCKED，須owner授權；mock不代替此證據。

**第一階段來源／回歸：** full來源index tree `96ceacdf62224f39522bdccdbbd2b97d0e37cd06`，246個來源hash於終態核對不變（`quant-audit/subscription-phase1-source.json`／`subscription-phase1-source-verification.json`）。 1292項＝1271 PASS／20 skips／1 ERROR、1250.240秒、exit1；唯一ERROR為restart test仍引用已移除的`ai_opt_in`。20 skips為15個platform／PowerShell及5個此環境未裝Streamlit的optional UI tests，CI UI仍安裝它。原FAIL log保留於`quant-audit/subscription-phase1-full.log`。終態後才套用精確producer profile及test-only consent修補，root delta19項全PASS、0 skip、16.203秒、exit0（完整market14項＋profile5項；`quant-audit/subscription-phase1-root-delta.log`）。未重跑full，不追溯改寫FAIL。 獨立組合273 PASS／1 PowerShell skip、登入面板127 PASS、host43 PASS、精確producer profile8 PASS各按來源記錄，不相加。這是本機功能證據；實際環境Python3.12.14／SQLite3.53.1／Qt6.12.0，私有3.54載入probe被正確拒絕，未改產品runtime或CI的3.54要求。新native／frozen TLS／lifecycle及clean Win10／11仍NOT_RUN，未merge／未發布。按需策略評論／比較另列第二階段證據，不追溯算入此第一階段full。

**第二階段按需評論／比較亦已root套用。** 基於第一階段checkpoint `695c25c5006e1fe04fb49ade50288f759a963546`／tree `e10b49af26629ca2e6f323c82b966c737cef4352`，加入本機重新計算的training／validation、SMA／RSI／MACD證據預覽及明示同意後的單次官方訂閱分析；排除holdout／OOS，獨立耐久receipt、精確快取與offline重開不重打模型，取消／死亡先join原worker再對帳。AI文字為未受信解讀，數值按candidate／split由本機證據顯示，不覆寫策略、排名或下單。新增ledger亦納入first-use host guard；兩代精確producer profiles與歷史identities保留。

root backend **141 PASS／29.688秒**；host／runtime／packaging等 **152項＝151 PASS／1 PowerShell skip、78.542秒**，static／history 0 findings、diff check PASS。證據為`quant-audit/subscription-phase2-root-backend.log`、`subscription-phase2-root-host.log`及`subscription-phase2-docs/source-inventory.json`；isolated 1440×1000／1366×768視覺檢查僅synthetic fixture。沒有最終來源whole-suite／新native／實際grant PASS；待同一PR合併更新後的exact-head CI，不是已merge main或Release，也不改70%。

### 更正前來源與歷史證據（保留原結果，不認證第一階段SIWC-only）

恢復來源`f57ac5f39d86187945f9891b5cb7a16f5c674044`與未推送`d81ecb55`同tree `48ad5a1b6f8a813f2069b344c0629d48a3f090a6`；下列17db及其後更正前結果保留全部失敗，不追溯改寫。

**最後受測來源與後續root delta分開。** remote `17db263a87f4df39a82bfa9b80d7694afcf28879`／local `1673d676a507373720a9f83485046f588a22f143`為同tree `27a571aebcf21b1842d584127f0814e1abcce7e1`。Quantlab9 PASS／Win312 research CANCELLED；Windows build／Qt gate PASS但AI model_download FAIL，未進inference／lifecycle。其後exact-host／typed診斷／TLS／storage診斷／KVM修補已有本機full／focused證據，依來源分列，新native仍NOT_RUN。

- **公開下載仍只有0.2.1 unsigned preview。** [已核驗安裝檔與證據](https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38016622951-1)，release main `2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`；PR5已合併main94aca467，但候選0.2.2／PR6仍Draft、未合併／未發布。
- **最新Quantlab38045449459終態：9 PASS／Win312 research CANCELLED。** UI1311項＝1298 PASS／13 skips、435.974秒；Linux311／312各1311項＝1293 PASS／18 skips、407.321／285.459秒；Windows311／312 core各1084項＝1067 PASS／17 skips、345.736／577.560秒。Win311 research227項＝223 PASS／4 skips、653.687秒；Win312於原15分鐘cap完成208項＝204 PASS／4 skips，第209項在`db.commit()`被中斷、18項未開始。storage診斷已套用、native量測待，沒有已修好或放寬cap的結論；e68取消與Linux312 observer原cause未知紀錄保留。
- **最新Windows38045449411已FAIL；建置成功不等於AI或安裝通過。** Installer環境Windows Server2022／CPython3.13.16／Qt6.12.0原生1311項＝1290 PASS／21 skips、765.646秒，build／Qt payload gate PASS。model_download於1.031秒失敗、category=`local_ai_network`、child exit1、無numeric HTTP status、非timeout、cleanup=true；0 model calls，frozen inference／install／lifecycle NOT_RUN。此category不能推論DNS、TLS、HTTP狀態或服務中斷；後續exact-host發現與原生歸因分界見下。Quantlab Windows cores為Server2025，兩種Server證據均不取代clean client。
- **實際17db263a installer靜態payload已獨立核驗。** artifact11667554811 ZIP 77,720,491 bytes／SHA256 `97bfa4f2a0660730f44f6c14581bc2084e43984de0ace5c50a6db2ca01c6a49b`，6 members，download hash／CRC PASS；0.2.2 installer 39,383,283 bytes／SHA256 `c2efa3f64424eaf24e6acec699bc1e3579927669d97dc52a36ad81046f398b58`。119個PE／982 payload entries證明原7項精確移除、無新增PE，retained DLL/PYD hashes全不變，依賴不引用已移除檔；Python3.5.9、qwindows／Schannel／cert backend與5份Qt notices均核對。這關閉該產物的靜態排除／notice-integrity證据，尚不認證loaded TLS、frozen HTTPS、IME、完整legal clearance、source-release交付或client。證據：`quant-audit/ci-17db263a/terminal-assessment.md`；app EXE hash是`7b383ca4…66b688aa`，非installer hash。未merge／未Release。
- **下載相容性缺口已證明並窄修，原生歸因仍待。** 固定model URL的TLS-verified HEAD為Hugging Face302→`us.aws.cdn.hf.co`200，Content-Length 1,117,320,736、linkedETag符合model SHA，0 body bytes；官方metadata列出此exact host，舊allowlist確實拒絕。只新增此host及有限typed network-cause診斷，TLS／size／hash／no-auth／proxy限制不變。17db失敗artifact未記rejected host，對該次失敗的歸因仍是inference。root combined151 PASS／2.367秒（`quant-audit/followon-integrated-targeted-20261010.log`）；其中TLS包含真owned-loopback HTTPS及憑證拒絕測試，Windows DLL載入證據仍mock。六檔synthetic storage診斷已套用，獨立CI job已實作、native量測未跑；product storage／COMMIT／原cap不變，未宣稱效能修復。HEAD與官方來源證據：`quant-audit/ci-17db263a/model-head-metadata.json`、`model-cdn-official-provenance.json`。
- **最新root full與其後diagnostic-only delta分開。** Linux1372項＝1357 PASS／15既有skips、291.628秒、exit0（`quant-audit/followon-root-full-20261010.log`），`followon-root-source-20261010.json`的219個pre-run hashes於完成後核對不變。其後才套用exclusive mkstemp report修補／3 regressions及獨立Windows3.12 storage job／7 offline contracts，故不算入該full來源。final focused初次70項＝68 PASS／1 skip／1 import error（錯拼module、2.440秒）保留；只改命令後78項＝77 PASS／1既有PowerShell skip、2.962秒、exit0（`quant-audit/followon-final-delta-corrected-20261010.log`），static／history0 findings、diff check PASS。未重跑full；新native仍NOT_RUN。storage job已實作，180秒量測／6分鐘job且保存INCOMPLETE；product storage mode／原COMMIT／原gates不變，量測COMPLETE也不等於產品驗收。
- **後續root測試與KVM證據分界。** TLS5檔focused70 PASS／0.299秒、quality boundary2檔14 PASS／0.027秒，KVM C／test／job3檔combined69 PASS／0.952秒，TLS含真owned-loopback HTTPS、Windows DLL證據則mock；quality／KVM為contract／mock，沒有Windows loaded TLS或VM執行。既有1311項root全套只屬17db263a前的來源。實際read-only KVM API12 query已成功（USER_MEMORY=1、IRQCHIP=1、recommended vCPUs=4、max=4096），artifact11667623060 SHA256 `d605336efdef16003e0d17e8133666f0952044642d8abd4dc0d14248a2eb6f40`；未create VM／run guest。新固定自撰payload execution self-test尚未原生執行，不涉及Windows OS映像。
- **歷史e68b3301／Quantlab38042425646：8 PASS／1 Linux312 FAIL／1 Win311 research CANCELLED。** Windows311／312 core各1029項＝1014 PASS／15 skips、406.239／339.883秒；UI1256項＝1243 PASS／13 skips、290.850秒；Linux3111256項＝1238 PASS／18 skips、426.842秒。Linux3121256項＝1237 PASS／18 skips／1 failure、417.872秒，為test-only process observer的cleanup=false；另已真實觀測Linux X dead state並修補X/x契約，但原CI未留process-state artifact，exact cause仍NOT_PROVEN。Win312 research227項＝223 PASS／4 skips、764.237秒；Win311在原15分鐘cap前完成222項＝218 PASS／4 skips，第223項被中斷、4項未開始，不記整套PASS。
- **歷史e68b3301／installer38042425591已FAIL，但已完成native全套與建置。** 原生1256項＝1237 PASS／19 skips、832.716秒，PyInstaller與兩個installer編譯PASS；AI download child於0.616秒exit1、非timeout、cleanup=true，未進frozen phase／0 model calls，其後install／lifecycle skipped。artifact11666369640 ZIP 83,451,533 bytes／SHA256 `b62c4e04edd9a3483f41f9a6d3701b83f7e6d8d8c320c4b04841af47e66c1d31`已下載核hash／CRC，5 members；0.2.2 installer 42,248,905 bytes／SHA256 `f7512490e8a7f5c07f456c7919ceb3b4e9db09f01325a172ca73127c75a8fd7a`，未發布。controller的`7600d5e8…672aaf6`是frozen app EXE hash，不能稱installer hash。證據：`quant-audit/ci-e68b3301/`。
- **歷史17db263a前整合的本機證據分開記錄。** WFO single-normalization保留相同hash bytes、全部原COMMIT與SQLite語義；當次root全套1263項＝1248 PASS／15 skips、290.403秒，source manifest `quant-audit/wfo-single-normalization-root-source-20261010.json`固定該次來源，不認證其後host／observer／Qt delta。其後Linux observer focused31 PASS／66.977秒；AI child失敗證據保留修補focused107 PASS／1.293秒，只修parent讀取／去敏順序，底層download cause仍未知。KVM opt-in query程式43 PASS＋partition9 PASS，但無實際sudo／KVM query；錯拼test module的44項／1 import error原log保留。所有重疊集合不相加，原300／660／10／120／135秒、15／35分鐘cap與單次嘗試不變。
- **歷史e68b3301 native風險與修補證據（後續17db靜態核驗如上）。** e68b3301實際126個PE的audit確認Qt另名`-x64` OpenSSL3.5.5，涉及[官方2026-09-29公告](https://openssl-library.org/news/secadv/20260929.txt)的CVE-2026-35189（TLS記憶體DoS）與CVE-2026-84782（DTLS）。Python `_ssl`／`_hashlib`使用不同basename的3.5.9；未找到app QtNetwork／QSsl呼叫，不宣稱Python HTTPS受此漏洞影響或已遭利用。root已套用精確移除qopensslbackend／3.5.5 pair與unused VirtualKeyboard／PDF的打包規則，保留Python3.5.9、qwindows、Schannel／cert backend，補完整GPL／LGPL與固定native notices／source links。新frozen payload未建置，不能宣稱已移除、已完成授權交付或pip-audit PASS等於native安全。Qt root初次65項＝63 PASS／1 failure／1 skip、0.757秒，是6個新build inputs尚未Git追蹤的guard；僅stage後原樣重驗65項＝64 PASS／1 PowerShell skip、0.780秒（`quant-audit/qt-packaging-root-tracked-20261010.log`），未改test／product來消除該失敗。獨立126-PE審查無blocker、static／history0 findings；最後整合root Linux全套1311項＝1296 PASS／15 applicability skips、288.641秒、exit0（`quant-audit/integrated-root-full-20261010.log`）；`quant-audit/integrated-root-source-20261010.json`所列來源hash已核對一致。這是Python3.12.14／SQLite3.53.1／Qt6.12.0的完整本機證據，新exact-head native CI仍NOT_RUN，不認證新Windows frozen payload或clean client。
- **歷史0088b505／Quantlab38032142094為9/10 PASS、整體FAIL。** Windows3.11 core806項＝790 PASS／15 skips／1 failure、433.599秒，唯一失敗仍是原960-bar Paper30秒。Windows3.12 core806項＝791 PASS／15 skips、339.431秒；UI1026項＝1013 PASS／13 skips、366.894秒；其他Linux／research／security通過。窄Linux ESRCH與Windows nested cleanup已有此來源驗證，不能冒稱新WAL／runtime／AI整合已通過。
- **歷史0088b505／Server38032142096 build／security及安裝流程PASS。** Server2022完整1026項＝1007 PASS／19 skips、808.047秒，該profile原Paper30秒／SystemExit40秒、frozen/history/WFO、真0.2.1升級／中斷恢復／移除保存通過；PR release skipped。實際候選artifact11663227244、PR merge703686e2、60個source inputs及EXE／kit／ZIP hashes已驗證，與0088b505同tree；這不是Release，也不能抵銷Windows311失敗或替代clean client。
- **歷史16974db3／Quantlab38040818017已終態：7 PASS／2 Windows core FAIL／1 Windows311 research CANCELLED。** Windows311 core1023項＝993 PASS／15 skips／7 failures／8 errors、546.573秒；Windows312 core1023項＝994 PASS／15 skips／6 failures／8 errors、399.402秒。UI1250項＝1237 PASS／13 skips、331.067秒；Linux311／312各1250項＝1232 PASS／18 skips、422.830／421.385秒；Windows312 research227項＝223 PASS／4 skips、636.478秒。Windows311 research達原15分鐘累計job上限，被取消時stack在WFO `_save_state` 的 `db.commit()`，數秒前測試仍在推進；不據此宣稱單一commit死鎖或任意加時。
- **歷史16974db3／installer38040817985在freeze前FAIL，沒有新installer或frozen AI呼叫。** 完整1250項＝1217 PASS／19 skips／6 failures／8 errors、874.196秒，與Windows312 core共14個相容性反例；Windows311 core另有一個terminal-cleanup測試失敗。build未進入freeze／實際單次AI／安裝驗證，這些保持NOT_RUN；不能沿用0088b505舊artifact的PASS。原生日誌與終態證據保留於`quant-audit/ci-16974db3/`。
- **歷史16974db3後的11檔相容性修補與failure-only WFO timing診斷已root套用。** Linux Python3.12.14／SQLite3.53.1／Qt6.12.0整合focused183項全PASS、0 skip、51.275秒（`quant-audit/windows-repair-integrated-focused-20261010.log`），static／完整可達history為0 findings，diff check PASS。這是修補後focused，沒有第二次root完整全套或新native PASS；WFO尚未做效能優化，原30／40／10秒、15／35分鐘job及所有驗收門檻不變，接續同PR新exact-head CI。
- **先前本機證據與負面結果按來源保留。** pre-AI root完整1096項＝1081 PASS／15 applicability skips、291.408秒，log `quant-audit/pre-ai-wal-integrated-full-20261010.log`與source manifest `quant-audit/pre-ai-wal-integrated-source-20261010.json`固定該次來源。其後本機AI focused153項＝152 PASS／1 skip、5.866秒；自動備份初次focused21項全PASS、0.966秒；offline-drive設定恢復修補後23項全PASS、0.962秒。focused logs見`local-ai-integrated-focused-20261010.log`、`automatic-backup-integrated-20261010.log`及`automatic-backup-integrated-final-20261010.log`。該次root venv實測為Linux Python3.12.14／SQLite3.53.1／Qt6.12.0，見`quant-audit/integrated-final-source-20261010.json`；早先手記Qt版本不作獨立量測證據。最終combined suite本次FAIL：1243項＝1225 PASS／15 skips／2 failures／1 error、300.720秒（`quant-audit/integrated-final-full-20261010.log`）。三項均為saved-candidate producer來源綁定未涵蓋provider hook變更後的source hash；現有fail-closed防線正確拒絕未匹配來源。兩個新的literal 0_2_2 transport-verifier profiles已獨立審查並root套用；原三個literal profiles與historical exact-hash測試未改，只將三個真正current-generated identity assertions移至新profile，tamper／mixed-source拒絕保留。修補後root focused150／150 PASS、0 skip、30.760秒（`quant-audit/provenance-integrated-focused-20261010.log`）；隔離54與138項PASS為重疊範圍，不相加。本次1243項FAIL保留，沒有第二次root完整重跑；其後16974db3原生終態另列於上方；不追溯改寫本次1243項FAIL。另`/usr/bin/python3`私有SQLite3.54.0載入probe及Paper111項＝110 PASS／1 skip、5.172秒屬獨立Linux範圍，見`/tmp/markauto-sqlite354-verified-setup.log`、`/tmp/sqlite354-paper-tests.log`。各集合不相加、不互相認證；目前root全套不是3.54或Windows證據。
- **歷史AI選路（11:16已被使用者更正取代，不再是目前交付要求）。** 可選llama.cpp／Qwen2.5-1.5B路徑使用官方固定hash runtime／model／support DLL來源；無付費fallback，official API預設off。localAI licenses與三個Microsoft DLL來源通知已補入packaging；實際新payload bytes／notices已靜態核驗；Microsoft downstream protective-terms充分性仍未定，未有demonstrated breach，也沒有強制付費license／新EULA／collector的依據，不自行增加這些驗收gate。17db263a supervisor的model_download仍失敗，category local_ai_network而無HTTP status；frozen phase／模型呼叫未執行；上述exact-host修補尚待新native，不能追溯確認舊失敗cause；mock、歷史14次呼叫或focused PASS均不能替代新路徑證據。
- **每日自動備份與審查修補已root套用，最終驗證仍待。** 預設off，開啟後app運作且所有manager閒置才嘗試，每UTC日最多一次；7份／2 GiB上限、連結保護、不自動刪檔或還原。獨立審查指出舊共用備份可經regular-file hardlink納入外部內容；共用BackupManager的hardlink拒絕已套用並包含於21項focused PASS。移除式磁碟離線時停用／更換目的地的設定恢復亦已修補，root focused23 PASS；最終combined／native未驗，不能宣稱漏洞或整項已完整閉合。
- **耐久與門檻不降級。** 舊來源同960 bars診斷worker35.562622秒，960次FULL cursor commits30.6026735秒，UI35.937秒；瓶頸位於耐久寫入路徑，物理原因未知。16974db3及最新e68b3301使用實際SQLite3.54.0／WAL／FULL，原960 bars／30秒測試已在Windows311／312 PASS；host為Windows Server2025，不能當clean client PASS。仍保留原per-bar耐久／帳本identity／風控與30秒、40秒、process-death10秒、job預算，不減bar／commit、不搬TEMP。不再無變更重跑湊綠，但經審查的新實作必須原生重驗。
- **執行責任與AI優先順序已更新。** 依使用者最新授權，assistant承擔工程、環境調查、可合法執行的設定與驗證，不預設把VM、測試或GitHub設定交給使用者。官方SIWC訂閱為必要路徑；本機模型與付費API／credits fallback禁止，不借用其他工具帳戶。零費用、零真資金交易及原驗收門檻保持。不可代行的帳戶、license、明示條款或持久權限，只提出精確最小確認，不包裝成整套技術作業。
- **外部證據如實保留。** 目前没有已驗證且已授權的零費用clean Win10/11 x64完整路徑；Win10／Win11官方EnterpriseEval x64媒體均可達，actual bundled EULA已以bounded ranges取出並核對檔案digest；full ISO hash、hosted-use涵蓋、registration／activation及owner接受尚未闭合，沒有Windows安裝／執行。opt-in KVM API12實際query已成功且close完成，沒有create VM或改權限；固定自撰payload execution self-test只有mock PASS、尚未執行；offline CI設計是提案，不是授權。KVM query成功不等於guest execution；Windows guest仍待資源／license／執行證據。SignPath僅可準備免付費申請材料，尚未獲接納。08:18只讀查核rulesets=[]、main保護仍未啟用；GitHub App無Administration scope，先前403未解除，換CLI／GraphQL／workflow token不會增加權限。實際服務、TAIEX盤中權利、clean client不以mock／Server替代。
- **原始匯入來源已有範圍明確的證據。** 原import `1cacce4ee4eef4ce7e8760f8153ef64a74852d22` 的47檔，其Git mode／type／blob全部與官方upstream `chrisli-kw/AutoTradingPlatform@a0ecf8895716bf5883184fdd27a52023f9700bf3`相同；upstream共49檔，另有`trader/APItest.py`與`trader/performance/backtest.py`未在該import。這證明47檔內容對應，不證明整棵tree／完整history相同，也不是維護者owner attestation；Apache LICENSE與Li Kuei-Wei署名保留。
- **210/300＝70%、M4 PARTIAL不變。** 17db263a兩個Windows core／Linux／UI PASS，但Windows312 research取消、SIWC第一階段已套用且有來源限定回歸，但新native／lifecycle未驗及loaded TLS／IME等範圍仍阻交付（原model_download失敗歷史保留）；其餘外部條件分開列示，不能把餘項全說成external。Oct8 WFO仍BLOCKED_NO_RUN，170 consumed bars、0新評估／model calls／reservation；不改window／registry。除上述使用者AI選路更正外，原需求、權重、失敗與歷史不重寫。

### 原需求、設計提案與未驗證項目

- **本輪已明確必要的原需求：** Walk-forward，以及使用者原文 §5.1 的 Profit Factor／Sharpe、§3.4 的停損／停利／持倉成本參考線；已合併及PR階段PASS不等於postmerge／已發布交付。
- **尚未採用的完整目標設計延伸：** 04 §9.1 提出的 Average Trade、Sortino、Calmar、延伸分解與成本壓力測試保留為提案。02 歷史原文已明示「若最終採用該完整規格」；未取得使用者直接要求這些延伸的原始證據，因此不把設計表的「必須公開的計算與例外」升格為本輪新增驗收門檻，也不刪除提案。
- **尚未驗證的結果：** 修補後完整CI／發布、clean client、真實授權與真實研究各依目前證據判定；未驗證不表示功能未實作，設計提案未採用也不等於本輪驗收失敗。

## 現在應接續的工作

1. PR #6最後受測17db263a／local1673d676／tree27a571ae：Quantlab9 PASS／Win312 research CANCELLED。Windows native1311／build／Qt gate PASS，model_download FAIL，0 calls／lifecycle NOT_RUN；未merge／未發布。
2. 17db實際119-PE／982-entry installer audit確認7項移除及retained DLL/PYD／Qt notices精確hash；loaded TLS、HTTPS、IME與source-release仍未驗。後續TLS含真loopback HTTPS；DLL／KVM證據為mock，combined151 PASS只屬本機，新native待。
3. 實際KVM API12 query已通過，沒有VM／guest run；新固定自撰payload execution self-test尚未執行。exact-host缺口已修，舊native歸因仍inference；storage診斷已套用、獨立CI job已實作。全部原deadline／COMMIT及既有負面結果保持。
4. 固定210/300＝70%、M4 PARTIAL保持。Assistant承擔工程與環境準備，不預設要求使用者搭VM、跑測試或處理GitHub技術設定；僅對無法代行的帳戶／license／條款／persistent access精確確認。官方SIWC訂閱必要，本機AI／paid API／credits fallback禁止，零新增費用／零實單。
5. Oct8 WFO仍BLOCKED_NO_RUN／170 consumed bars，0新evaluation／model／reservation，不改window／registry。clean client、真grant與TAIEX盤中權限保持外部狀態。
6. 保留全部Git歷史、0088b505候選artifact及歷次失敗；目前文件同步補第一階段來源限定工程證據及待驗範圍。後續CI終態由其新head記錄，不預填PASS，不改原權重／門檻。

### 自主接續計畫與不可代行的邊界

1. **固定更正後來源並重驗：** 11:16只替換AI選路；既有research、storage、security、Windows build／lifecycle與clean-client原gates不變。歷史17db失敗及1372／78來源證據保留，SIWC第一階段已套用，本機回歸終態及後續delta按上方來源分列，新native仍NOT_RUN；不再安排已禁止的本機模型下載／推論。官方真grant／請求仍須owner授權。
2. **保留原持久語義：** WAL候選需逐個原邊界COMMIT＋FULL、無外包整段transaction／降級NORMAL或OFF，既有mutex、cursor／pending plan／stable IDs不變；broker DELETE／FULL仍分開。SQLite版本／官方hash／native載入來源、local filesystem、舊版本workspace拒絕及DB／WAL／SHM備份恢复都須有實證；guard已用精確0.2.1 source fixture證明startup／schema2 archive拒絕；實際舊EXE拒絕測試程式已加入但尚NOT_RUN，仍需原生結果。備份hardlink修補與移除式磁碟離線設定恢復須完成最終整合回歸。這是必要待驗證清單，不是完成宣告。
3. **重驗已整合官方SIWC訂閱流程：** 移除本機模型功能及其下載／推論交付要求，保留舊證據；改接既有官方PKCE/OIDC、DPAPI、subscription provider與同一worker生命週期。included-only前置為owner自述確認與Usage指引，不假稱程式能查證credits設定或有server monetary cap；無付費fallback。官方流程與產品移除已有本機工程證據，尚無新native／真grant；bounded模型呼叫仍EXTERNAL_BLOCKED，不以mock補PASS。M6與其餘權重不變。
4. **Windows驗證由assistant持續承擔：** 已授權標準public GitHub runner可提供Server證據；先做只讀host能力／磁碟調查。Nested x64 guest在GitHub官方文件中是實驗性、無保證路徑；需實際可用加速／資源、合法精確Win10 22H2／Win11媒體及所需license／條款確認。此cloud shell目前無現成KVM／VM工具，不代表免費虛擬化普遍不可能。Win10／Win11官方EnterpriseEval x64媒體均可達，actual bundled EULA已以bounded ranges取出並核對檔案digest；full ISO hash、hosted-use涵蓋、registration／activation及owner接受尚未闭合，沒有Windows安裝／執行。opt-in KVM API12實際query已成功且close完成，沒有create VM或改權限；固定自撰payload execution self-test只有mock PASS、尚未執行；offline CI設計是提案，不是授權。退役evaluation landing page不等於媒體撤回；Windows11 ARM、Server或未授權Azure試用均不可冒充目標client；不繞TPM／Secure Boot／啟用限制、不預設使用者需準備VM或跑測試。
5. **保護與簽章保持誠實：** assistant準備main protection精確所需scope／規則與可行路徑，現有連線缺Administration則只停在該操作，不反覆撞403、不換transport冒充授權，也不索取聊天中的token。SignPath可先準備真實申請草稿；47檔upstream內容對應已驗，但完整lineage／維護者權利陳述、打包界線與metadata／政策仍需分別補證；OSI授權、MFA／角色、來源到binary及每次release核准仍待確認。外部提交、帳戶／條款、GitHub App或簽章persistent access須個別具備所需授權；不買付費簽章、不保證免SmartScreen。
6. **保留每次結果：** 舊0088b505的806core／220research、9/10與同工作量diagnostic作為固定比較；新來源完整清單與依賴另行記錄。全部PASS／FAIL／ERROR／SKIP、elapsed、source／runtime hashes、OS／volume、cursor／orders／fills與清理／恢復證據保留；不按結果追加無變更重跑，不將別台host PASS寫成失敗CI已通過。

本計畫亦依據`windows-eval-terms-and-offline-ci-20261010.md`、`openssl-security-e68b3301/payload-pe-tls-inventory.json`與`qt-notice-proposal/REVIEW.md`；其餘既有查核：`windows-environment-options-20261010.md`、`signpath-eligibility-20261010.md`、`github-protection-options-20261010.json`。可用方案、授權缺口與推論分開；不新增權重、不把準備材料算成外部已通過。

### 導覽與單一事實來源

- [功能矩陣](../analysis/02_EXISTING_FEATURES.md)：已發布／候選工作樹整合進度分欄，以及原 F01–F35 與所有歷史證據。
- [風險與發布否決](../analysis/03_CODE_QUALITY_AND_RISKS.md)：當前優先風險、negative results、必要閉合證據。
- [依賴與固定驗收](../analysis/05_IMPLEMENTATION_ROADMAP.md)：下一步順序，Phase／D／M 原門檻及需求對照。
- [機器可讀帳本](ACCEPTANCE.json)：原 gate 與權重保留；current_snapshot 為有日期的摘要，candidate_022_ci 由整合者持續更新，不用舊副本覆蓋。

開發命令仍為 `python -m unittest discover -s tests -v` 與 `python tools/quality_gate.py --history`。使用者開已發布 installer／捷徑；舊 `run.py`／`gui.py` 不作研究入口。未授權的帳戶、電腦、付費服務或真資金交易一律不因接續工作而開啟。


### 歷史檢查點：04:24 整合來源 Gate（當時狀態，不是目前待辦）

- 候選修補完整 Linux root suite：773 項，758 PASS＋15 個既有 native Windows／PowerShell applicability skips，127.279 秒、exit 0；歷史掃描 0 findings。涵蓋 smoke 終態、canonical fixture 與 FULL 設定失敗關閉連線，SQLite mode／耐久邊界／既有門檻不變。此結果取代上文針對較早來源的「最終 root 待驗」，原生 exact-head CI 仍待。
- Qt CI-only 相容鎖及獨立 Linux311 套件稽核已納入 workflow；官方來源、完整 SHA-256、強制重新安裝及 pip report 保留。Windows 產品依賴鎖不變；套件 advisory audit 不等於所有 native library 已安全認證。
- 後續 WFO／報表 combined staging 完整 947 項：932 PASS＋15 既有 applicability skips，270.314 秒。再套用同一 Paper 連線小修補後 5 項 storage regression PASS；仍非已發布或 Windows／真實研究驗收。


歷史驗證位置補註：較早981項在隔離候選執行，25檔按manifest複製；不是最後root全套。12e088f的1000項失敗／cancelled與05:32局部18／33／85項屬先前checkpoint；其後06bcc3a的完整PR1016已通過，但94aca467 postmerge又出現上列兩種timeout。所有來源、平台及計數分開，不相加或追溯改寫。


最後原生受測PR #6 head17db263a／local1673d676／tree27a571ae：Quantlab9 PASS／Win312 research CANCELLED，Windows AI下載FAIL；119-PE靜態排除與notice核驗PASS。其後下載／TLS／storage／KVM delta已有本機full／focused證據，依來源分列，下一native待；全部歷史負面結果及210/300不變。

<!-- HISTORICAL_STATUS_END -->

## 歷史原文與逐次證據（依原記錄保留）

以下完整保留本次整理前的內容、要求、來源、失敗與各時點判定。內文即使寫「目前／最新」，也只屬原有日期快照；現在的交付與下一步以本檔最上方有日期的摘要為準。原始基線盤點、固定驗收條款與年代順序均未被當成新版本成功證據。


更新：2026-10-10 02:36 UTC。唯一正式來源：https://github.com/yostar77612/mark-auto。

## 最新接續：02:36 UTC

0.2.1 main2ed1e3e postmerge雙CI全部PASS，Release desktop-preview-38016622951-1八個主要assets已下載驗hash，kitCRC PASS；基線EXE cce3f6242068affa91ab5c242f6ac655bbb59c677e4abda8b85065b97e48e0b1、41583381bytes，manifest4c6c6b0a0ddff170c5394b7b04f03f3575c29b54087c9e042a60c3fb38bc5639、7247bytes。獨立證據接受M3，總210/300=70%，餘30%，不能解讀為所有重新核對需求已認證。

本分支候選0.2.2 history/expiry/Paper margin已合併到工作樹，724完整測試709PASS15skip；後續async對話框54PASS，實際baseline更新40packaging tests36PASS4skip，quality/history0。最終exact-head原生Windows/發布尚待。其他隔離工作：WFO固定pool與明示historical replay；必要PF/Sharpe/持倉保護參考線；TAIEX intraday合法來源研究。不能刪任何原始本地branch，先保存Git bundle/tree映射再清理。

## 02:25 UTC 接續狀態（以下較早快照保留）

PR4已合併main `2ed1e3e5fa8f6140e7305858e59a58555dcbc3e8`，headf11e2ef／localfea95b2 tree12804de7477ce6ca2da5d11d474240a795bd9025完全相同。Windows38016153320已PASS644tests633PASS11skip、frozencrypto/真0.2.0upgrade/recovery，Quantlab38016153246七jobsPASS。postmergeWindows38016622951與Quantlab38016622996進行中，尚未校驗新Release。

現在唯一新功能分支agent/market-history-acceptance-v1，候選0.2.2，沿用已合併main並接入已獨立review的history/expiry/Paper margin及historyfrozen smoke。完整724測試709PASS15平台skip。不能在實際0.2.1Release可下載前編造新baselinehash；nextheadWindows尚未跑。mandatoryWalk-forward確認缺失，另隔離最小固定poolrolling evaluator開發中，不把單次OOS當完成。詳細完整功能與限制新增至02分析附錄，原47檔盤點保留。

## 最新狀態與計分

- PR #3 已整合 main `fc2dfacbf297004095e971ec10cf3620307417a2`；0.2.0 unsigned preview 與 no-Python clean-client kit 已發布並實際下載校驗SHA256／ZIP CRC。Release：https://github.com/yostar77612/mark-auto/releases/tag/desktop-preview-38013204925-1 。
- 原200點170 PASS＝85%；新增市場範圍M1/M5共25/100 PASS；合计195/300＝65%，剩35%，是固定驗收權重，不是工時估計。M2/M3/M4尚待相應版本完整Gate，M6/M7未全滿，不能提前給分。
- 現有PR #4／`agent/chatgpt-desktop-v1`候選0.2.1，remote `7dc3536f`與本地`797f3cd`完整tree相同。Quantlab `38014802083`七jobs與Windows `38014802079` build/security全通過；635 tests624PASS11適用profile skip，原生加密／DPAPI／安裝／真0.2.0升級／中斷復原PASS。Server runner不等於clean Win10/11。
- PR4合併暫緩：offline反例發現新增OAuth registration能繞過另一registration尚未確認的呼叫屏障；修復已通過獨立151項檢查及完整644測試629PASS15平台skip；最終head原生Windows仍須重驗。沒有真帳戶授權或訂閱模型呼叫，不能以工程fixture冒充。
- 下一個行情分鐘匯入模組僅在隔離staging：TX/MTX/TMF真CSV/RPT900bars、24商品/周期組合及159項獨立組合測試通過；另source smoke保留原7步＋manual2步＋auth並新增24圖表組合。尚未整合、未原生Windows/frozen驗證，不能當已發布。
- 真AI：免費Qwen1.5B實際生成3候選並完成回測/OOS/holdout/比較，1個虧損、2個零交易，不合投資晉級。v3兩次duplicate失敗保留；v4固定1次實際改善產生不同參數，技術去重PASS，沒有新回測/OOS/holdout或獲利改善證據。累計14次真免費呼叫，不追加無限制搜尋。
- 真行情：12連續交易日13,680分鐘、24盤獨立官方OHLC；Oct7缺分鐘拒絕。0.2.0 Windows實際官方HTTP診斷VERIFIED，來源皆EOD非realtime；雲端直接HTTP的DNS限制保留，不把另一环境成功改寫舊失敗。
- 圖表真訓練區間重播淨損益−143,590 TWD、1,917訊號、3,831成交；非新模型/OOS/holdout或真交易。Linux截圖檢視通過，非Windows DPI實測。
- clean Win10 22H2 x64／Win11 x64仍EXTERNAL BLOCKED；main管理級保護403／未啟用，簽章及使用者官方授權未取得。真資金交易固定停用。

## 已保留的原始成果與 Git 映射

GitHub App 可正常讀寫 Git 物件、分支與 PR；CLI 無登入不阻礙連接器發布。連接器建立新 commit metadata，因此 SHA 不同，但逐次驗證完整 tree 相同。

| 本地原始提交 | 遠端提交 |
|---|---|
| 0430a74 | eeccb3296e47e84fe8d0f68446dda6cae58976a0 |
| 5bcfbe5 | a90fcb846c358b6867cf3cdf902db858200b1766 |
| 2110016 | b3ad661309d0a514a0889be5cbb214ad0a843933 |
| e5e56bb（含 cde65fb） | 8597dd6e6a0f6f95337e2a17ca98798da9ca2252 |
| 76ad3a5 | 8cea2729fa5f0acca1d1ff947b08d173ffddcd71 |
| 1f78a52 | 8b1f007abdb325c6ddc97707e1e2ab8c6211e5ca |
| 468b86c | 4def6c8907bb00ee975e38912b029648eee97ad0 |
| 8bc19e1 | d0665e1417a6c31d0978e93a9bf2d2194eba913d |
| 3246cdc | b62803a529994f114cb4a4be301e0c62a757ac7e |

`0430a74` 與 `eeccb329` 的 tree 均為 `df167ff071331a6eb75007a72c0d3637e4fc899a`：所有檔案路徑、內容、模式完全相同。原本本地歷史全部保留；本地原始 commit 不在遠端新 metadata 圖的祖先鏈，不能僅憑 PR 合併就刪掉本地分支。

## 目前實作

研究核心：標準庫 quantlab、版本化日夜盤與到期、官方資料匯入／有界免費下載、Decimal 因果回測、五種策略、受限 DSL、持久研究預算、樣本外與保留集隔離、報表／版本選擇、Paper 持久帳本／對帳／風控／故障恢復。

桌面：PySide6 原生繁中介面，既有核心不重寫；七個頁面涵蓋總覽、資料、策略、回測、比較、Paper、設定。工作採 allowlist 子程序、進度／取消、Windows Job Object、單例與睡眠凍結。DPAPI 機密、每使用者 AppData、工作區切換、備份恢復、不可回退研究預算／holdout 控制已實作。

打包：鎖定 CPython 3.13.16、PySide6 6.12.0、PyInstaller 6.22.3、Inno Setup 6.4.3；每使用者安裝與捷徑、保留使用者資料、拒絕更新／移除正在運作的 app。Windows Server CI 必须實際完成 frozen research／Paper 流程與安裝升級移除，並附來源／依賴／授權／hash 證據。未簽章，Release 僅能標 preview。

## 已驗證與尚未驗證的界線

- 原研究來源 `76ad3a5`／`8cea2729`：本地 180 tests 通過，GitHub run `37959451997` 的 Linux／Windows Server Python3.11/3.12 和 UI 五 jobs 全成功。這不取代新增桌面的最終 head 回歸。
- 真實 2026-10-08 TAIFEX CSV／RPT／日報匯入 1140 根分鐘 K，OHLC 一致；價差成交量口徑仍待正式證據。最近 30 官方 ZIP 已下載，保持 `provisional_unverified`／`ranking_eligible=false`，原始行情不提交 Git。
- 預設AI使用明示Fixture；本輪另以實際免費本地Qwen推論驗證受限家族參數生成與整體研究流程，未呼叫付費模型。早期有效新改善候選FAILED（只改名），去重拒絕成功；後續v4限1call產生不同參數，技術去重PASS，累計14真calls，全部舊失敗保留；沒有改善獲利證據。
- Paper 是有限歷史重播，沒有正式即時行情串流。盤中停損／停利未支援即拒絕。未知委託／部位先凍結，禁止猜測補單。
- 實盤固定停用。真券商資格、行情授權、憑證、完整歷史品質與真市場策略績效尚未驗證。
- Windows10 22H2／Windows11 乾淨環境實測 **BLOCKED**：目前無已授權可用 client OS；Windows Server 不能冒充通過。未使用使用者未授權電腦。
- main 保護 **未啟用**：metadata `protected=false`，rulesets 空，管理級 protection API 403 `Resource not accessible by integration`。Code／PR 授權有效；缺管理權限不是證明需重新登入。不可宣稱有防護，也不自行擴權。

## 接續順序與命令

1. 先 `git status`，保留所有未提交修改；閱讀固定合約與驗收清單。
2. 修復並獨立驗證PR4跨registration安全屏障，在原功能分支更新；exact-head完整Gate後才整合。其後接續已保留的行情匯入模組，不覆蓋新修正。
3. 最終 head 的研究／UI／品質／依賴／installer 全通過才可整合 main，並驗證 post-merge build 與 preview Release。
4. 保存原始 Git 歷史與五份分析文件；清理分支前確認保存、已合併與無競態，不具安全刪除條件就保留並說明。
5. 剩餘真 client OS、外部服務與權限阻塞誠實記錄，不降低門檻或以 mock 代替。

開發測試：`python -m unittest discover -s tests -v`、`python tools/quality_gate.py --history`。
桌面開發入口：`python desktop.py`。最終使用者使用安裝檔與捷徑，不需上述指令。
舊 `run.py`／`gui.py` 不得作研究啟動入口。Streamlit 僅保留輔助介面。

## 新增產品範圍

22:52 UTC使用者正式加入市場優先儀表板、真行情/K線/技術指標及無JSON的專業研究交易介面，詳05 Roadmap第18節。原85%只限原範圍；新增及新版整體百分比待盤點凍結權重，不沿用85%。本輪安全修復先驗收整合，再接續市場/UI模組，不以0.1.2預覽當全部完成。

00:15 UTC新增市場範圍100點已實作前凍結（M1–M7），原170/200=85%，新增0/100=0%，整體170/300=56.67%、剩43.33%。採二元證據Gate非工時估计，安全否決與clean Windows門檻不變。0.1.2修復本地203b4af/遠端48a0d833完整tree982a8d2相同，PR#2必要CI正在驗證；市場新檔及其合約為下一批未提交變更，未包含於該驗證head。

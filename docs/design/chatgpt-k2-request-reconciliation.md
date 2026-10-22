# R2：人工核對已結束但結果未知的 ChatGPT 請求（K2）

Status: PROPOSED / NOT IMPLEMENTED. Verification: NOT RUN.
擁有者核准前，不修改任何 G3 檔案、不動 saved-candidate profile 區塊，也不合併。
前一版設計 R1（K1）見 [PR #76](https://github.com/yostar77612/mark-auto/pull/76)，已在 #81、#82 實作。
行號以 `fdd09eb`（origin/main）為準。

## Problem

R1 讓使用者人工核對 **K1**：行程在請求中途被強制結束，receipt 停在 `reserved_unknown`，
`plan_accounts.owner` 等於 ledger 的 binding。R1 的決策 D1 刻意排除了 **K2**：
請求在同一次執行內結束，但結果代碼既不是 `completed`，也不是 7 個已知的 `ERROR_STATES` 值。

### 擁有者實際遇到的情況（以下不含任何識別碼）

證據：2026-10-23 把安裝目錄 `control-v1` 的兩個 SQLite 檔複製到暫存區，用程式碼 `1239769`（與 `fdd09eb` 的
provider 相同）對**副本**執行 `read_account_status` 和 `inspect_unknown_request`，並用離線畫面驅動按下按鈕；
原始檔案未寫入（修改時間不變）。結果：

- 只有一個 registration、一個 ledger（共 1 次請求）。
- 那一次請求的狀態是 `invalid_content_type`，收到 0 位元組，耗時約 3 秒。
- `read_account_status` 回 `{'state':'reserved_unknown','pending':True}`；`inspect_unknown_request` 回 `k2_unresolvable`；
  `clear_account_pause` 回 `active_or_unknown_request`。
- 畫面顯示「這筆請求已經結束，但結果未知，目前版本無法人工核對。」，不會開啟確認框。
- `invalid_content_type` 是在 HTTP 2xx 但 Content-Type 不對時丟出的
  （[desktop_chatgpt_provider.py](../../desktop_chatgpt_provider.py:296)），也就是請求已經到達伺服器，
  **可能**已經計入官方用量。

### 程式碼觀察

- `_finish`（[desktop_chatgpt_provider.py](../../desktop_chatgpt_provider.py:880)）在 `_execute` 的例外路徑
  （[第 1027 行](../../desktop_chatgpt_provider.py:1027)）於同一個交易寫入：
  receipt `status=<代碼>`、`usage="unknown"`、`response_hash=NULL`；`plan_budget.blocked=<代碼>`；
  以及 `plan_accounts SET state=<代碼>, owner=NULL WHERE registration=? AND owner=<binding>`（第 892–896 行）。
- `_installation_barrier`（[第 466 行](../../desktop_chatgpt_provider.py:466)）把任何不是 `completed`、
  也不在 `ERROR_STATES`（[第 41 行](../../desktop_chatgpt_provider.py:41)）的 receipt 當成未知（第 502–503 行），
  對整個安裝回傳 `{'state':'reserved_unknown','pending':True}`，**永久**如此。
- `clear_account_pause`（[第 1057 行](../../desktop_chatgpt_provider.py:1057)）回 `active_or_unknown_request`；
  `inspect_unknown_request`（[第 649 行](../../desktop_chatgpt_provider.py:649)）回 `k2_unresolvable`；
  `resolve_unknown_request` 回 `no_resolvable_unknown_request`。這個拒絕被
  [tests/test_chatgpt_plan.py](../../tests/test_chatgpt_plan.py:1290) 的
  `test_other_registration_and_k2_cannot_be_resolved` 釘住。
- 常見的 K2 來源：`remote_error`（[`_remote_error`](../../desktop_chatgpt_provider.py:102) 在沒有已知遠端代碼時使用：
  例如單純的 429 或 500 這類非 2xx 回應，或串流中沒有已知代碼的 `response.failed`／`error` 事件；3xx 則是 `redirect_rejected`）、
  `invalid_content_type`、`http_transport_failed`、
  `cancelled`、`deadline_exceeded`，以及所有非 `PlanError` 的例外（記成 `failed_or_interrupted`）。

### 修正 R1 文件的說法

R1 說「K2 無法對應回 registration」，只對了一半：

- **不能**：沒有任何明文欄位把 ledger 連到 registration。`plan_ledgers` 沒有 registration 欄位
  （[第 429 行](../../desktop_chatgpt_provider.py:429)）。binding 是 `content_hash(provider_descriptor())`，描述內雖然含 registration，
  但也含當時的原始碼 provenance、model、campaign 等，升級後無法重算，所以不能拿來反推。
- **可以推得**：`plan_accounts` 以 registration 為主鍵，`_finish` 只會把 K2 代碼寫進**預留那個 registration**
  的那一列。目前的程式又有三個不變條件：
  1. 整個安裝同時最多一個進行中的請求（`_reserve` 只在屏障為 `ready` 時、在 `BEGIN IMMEDIATE` 內放行，
     [第 851 行](../../desktop_chatgpt_provider.py:851)）；
  2. `_finish` 跨兩個資料庫原子寫入（delete journal、`synchronous=FULL`）；
  3. 只有 `_finish` 會寫入非已知狀態，之後沒有人能覆寫它
     （[`_persist_account_pause`](../../desktop_chatgpt_provider.py:447) 會跳過 K2）。
- 所以「恰好一筆 K2 receipt + 恰好一列 `state` 等於同一代碼、`owner IS NULL` 的帳號列」可以唯一推得
  registration。這是**由不變條件推論**，不是儲存的事實；代碼相同只是一致性檢查，不是證明。
- 推不出來、必須拒絕的情況：K2 receipt 但沒有對應帳號列；兩筆以上 K2；代碼不一致；K2 不是最後一筆或前面有未完成的；
  同時有 K1；有帳號列但沒有 receipt；沒有稽核的 `user_confirmed_consumed`；未知狀態字串；超過 1024 列；
  ledger 缺少或是連結；以及 receipt 狀態不在 research 白名單（見下方二次 `_finish` 與 D7）。
- 舊版 `f985f91`（2026-10-10）的資料可能違反上述不變條件：當時放行是以單一 registration 判斷，
  `_pause_account` 會無條件覆寫帳號列狀態，清除也只看那一列（依該版原始碼判讀）。因此可能出現
  (a) K2 帳號列被覆寫成已知暫停甚至清除，留下沒有對應列的 K2 receipt；(b) 另一個 registration 在 K2 存在時預留後被中斷，
  形成 K2 與 K1 並存。(a) 由 M10 拒絕；(b) 由 M2 拒絕，而 R1 的 `_unknown_request_snapshot` 看到 K2 receipt 也會拒絕，
  所以**兩個入口都永久拒絕**。結果是 fail-closed（不放行、不誤歸屬），但仍然卡住，列為非目標。
- 二次 `_finish`：成功路徑的 `_finish(sequence,'completed',...)`（[第 1024 行](../../desktop_chatgpt_provider.py:1024)）若在 commit 前
  丟出 `PlanError`（例如 `campaign_controls_unavailable`），例外路徑（第 1028 行）會再用那個代碼呼叫 `_finish`；
  若第二次成功，receipt 會帶著不在 research 白名單的代碼。這條路徑未經測試重現（UNVERIFIED），D7 處理。
- 即使對應唯一，`failed_or_interrupted`、`cancelled`、`http_transport_failed` 等代碼仍**無法分辨**是送出前還是送出後失敗；
  HTTP 狀態和失敗位置都沒有保存。

## Goals/Non-goals

目標：

- 使用者自行到官方用量頁核對、明確確認後，**一筆可唯一對應**的 K2 receipt 從原代碼轉成既有的
  `user_confirmed_consumed`，並留下不可修改的稽核紀錄。
- 安裝進入**已知暫停**，不會直接變成 ready；使用者再用現有的「核對額度後申請解除已知暫停」恢復（兩步，同 R1）。
- 偽造、沒有稽核或不一致的資料一律維持 pending；舊版程式讀到新資料一律 fail-closed。

非目標，也是禁止事項：

- 不退還、不重設：`plan_budget.calls`、`plan_ledgers.calls` 不變，原 campaign／analysis 永久停止。
- 不刪除 receipt，不改寫 `request_hash`、`request_bytes`、`response_hash`、`usage`、`received_bytes`、`elapsed_seconds`。
- 不新增「預留時記錄 registration」的對應紀錄，不改 `_reserve`／`_finish` 熱路徑（D1）。
- 不依時間、登出、重新啟動、新 registration 或任何自動流程轉換；不連網、不讀官方頁面、不讀憑證或 vault。
- 不處理模稜兩可或舊版資料、不跨 registration 解除。單獨的 K1 仍由 R1 處理；
  K2 與 K1 並存（`f985f91` 時期可能產生）兩個入口都拒絕，維持卡住。
- **不防止未來再卡住**：之後任何取消、單純的 429／5xx 或傳輸失敗，仍會再次封鎖整個安裝，每次都要走這個人工流程。
  例如「確定在送出前就取消」的情況如何在不放寬閘門下歸類，留給後續設計（D10）。

## Design

### 白話版：實作並安裝後，你會怎麼操作

以你目前的紀錄為例（一個帳號、一次 `invalid_content_type` 請求）：

1. 先用瀏覽器開 ChatGPT／OpenAI 官方用量頁，看 10/16 早上那段時間有沒有多出用量。App 不會幫你開，也讀不到那個頁面。
2. 開 App →「設定與備份」→「ChatGPT 連線」→「展開 ChatGPT 完整連線管理」。上方連線選單要選到你平常用的那個連線（D0）。
3. 按「核對未知請求…」。App 只讀本機紀錄、不連網，接著跳出確認框，內容是：
   「第 1／1 次請求已經結束，但沒有正常完成……（App 內部結果代碼：`invalid_content_type`）」，
   並提醒「即使這次可能沒有送達伺服器，也會記錄為已消耗」。
4. 確認框有三個勾選項，每次打開都是空的，三個都勾才能按「記錄為已消耗」：
   ① 我已經在官方用量頁核對過；② 我了解不會退還次數，這次研究批次會停止；
   ③ 我了解官方用量頁也包含 App 以外工具送出的請求，App 無法替我分辨。預設焦點在「取消」，按 Esc 或關閉都不會寫入。
5. 按下後面板顯示「已記錄為使用者確認消耗。帳號目前處於已知暫停……」。這時**還不能**做研究。
6. 再到「進階連線管理」按「核對額度後申請解除已知暫停」。成功後帳號恢復可用；舊的研究批次永遠停止，要開新的研究批次。
7. 帳號恢復後，才做原計畫第 14 節的真實帳號實測（那時才需要你登入）。

如果第 3 步顯示的是別的訊息，就表示你的紀錄不符合下方的安全規則，App 不會讓你核對，紀錄保持原樣：
「另一個本機連線送出的」→ 切換連線再試；「無法唯一對應」→ 需要後續版本；「請至少等待 5 分鐘」→ 稍後再試。

### 狀態轉換（只有這一條是合法的）

```
K2: plan_calls[n].status      <代碼 ∈ K2 集合>      -> user_confirmed_consumed
    plan_calls[n] 其他 7 欄                          不變
    plan_budget.blocked        <代碼>                 不變（保留證據；仍為 truthy，campaign 永久暫停）
    plan_budget.calls / plan_ledgers.*                不變（不退還）
    plan_accounts[R]           (<代碼>, NULL)        -> ('user_confirmed_consumed', NULL)
    plan_finished_resolutions  (無或 n 列)           -> +1 append-only 稽核列，previous_status=<代碼>
    plan_resolutions（R1）                            不寫入，也不由 R2 建立
```

之後屏障看到有效稽核的 consumed receipt，把 R 放進 `resolved_registrations`，回傳 `pending: False`，
`state` 是所有非 NULL 帳號列狀態中字母序最小的那個（只有 R 一列時就是 `user_confirmed_consumed`；
若還有別的已知暫停列，例如 `quota_paused`，會顯示那個）。不論哪一種都不是 ready。使用者按現有的清除按鈕後，
`clear_account_pause` 照現有檢查只清除 R 那一列。

### 固定常數（G3：provider）

- `_FINISHED_UNKNOWN_STATUSES`：**字面寫死**的 40 個代碼，等於 research 白名單
  （[quantlab/research.py](../../quantlab/research.py:736)）扣掉 `completed`、`reserved_unknown`、
  `user_confirmed_consumed` 和 7 個 `ERROR_STATES` 值。新增一個 drift 測試確保兩者**以集合**相等
  （research 的字面清單把 `ambiguous_terminal` 寫了兩次：51 個字面、50 個不重複，不能用數量或清單比較）。
  稽核表的 CHECK 也用這份字面清單，建立後就凍結；未來 research 白名單若新增代碼，需要新表或新版本，
  這是刻意的代價（D5）。完整清單：

  `ambiguous_candidate`、`ambiguous_event_type`、`ambiguous_terminal`、`cancelled`、`candidate_byte_limit`、
  `candidate_family_mismatch`、`compressed_response`、`deadline_exceeded`、`done_without_completion`、
  `duplicate_event_type`、`duplicate_json_key`、`eof_without_completion`、`event_byte_limit`、`event_count`、
  `failed_or_interrupted`、`http_transport_failed`、`incomplete_message`、`invalid_content_type`、`invalid_credential`、
  `invalid_event`、`invalid_json`、`invalid_output`、`invalid_response_id`、`invalid_stream_chunk`、
  `invalid_terminal_status`、`invalid_utf8`、`json_depth`、`json_object_required`、`missing_output`、`nonfinite_json`、
  `redirect_rejected`、`refusal_or_tool_event`、`refusal_or_unknown_content`、`remote_error`、`request_byte_limit`、
  `response_id_mismatch`、`response_incomplete`、`stream_byte_limit`、`tools_or_unknown_output`、`truncated_event`。
- `FINISHED_ACKNOWLEDGEMENT_VERSION = 1`，已儲存的列以凍結集合 `frozenset({1})` 驗證。
  R1 的 `ACKNOWLEDGEMENT_VERSION` **不動**，否則所有既有 K1 稽核列會失效。`control_identity` 維持 1。

### 對應與資格規則（`_finished_request_snapshot`）

在呼叫者的 account controls 交易內判斷：檢查用唯讀 `BEGIN`，解除用 `BEGIN IMMEDIATE`。
ledger 用獨立的 `?mode=ro` 連線、5 秒總期限讀取，與 R1 相同。

| # | 規則 | 不符時：inspector kind／resolver 錯誤 |
|---|---|---|
| M0 | controls 存在（marker、`control_identity`=1），不存在時**不初始化** | `none`／`no_resolvable_unknown_request` |
| M1 | 屏障評估成功且 `pending=True`；屏障自己的 `PlanError`（ledger 缺少、損壞、非白名單狀態、超過 1024 列）原樣傳出 | 非 pending：`none`／`no_resolvable_unknown_request` |
| M2 | 沒有 `owner` 不是 NULL 或 `state='reserved_unknown'` 的帳號列（K1 優先交給 R1） | `k2_unresolvable`／`finished_request_unmappable` |
| M3 | 每筆 receipt 只能是 `completed`、已知代碼、有效稽核的 consumed，或在 K2 集合內 | `k2_unresolvable`／`finished_request_unmappable` |
| M4 | 全安裝恰好一筆 K2 receipt *r*（在 ledger *L*） | `k2_unresolvable`／`finished_request_unmappable` |
| M5–M8 | *r* 是最後一筆（`sequence == budget.calls == plan_ledgers.calls`）；前面都是 `completed`；`blocked == r.status`；`response_hash IS NULL` 且 `usage == '"unknown"'` | 同 M4 |
| M9 | 每列 consumed 帳號列都屬於有稽核的 registration | `k2_unresolvable`／`finished_request_unmappable` |
| M10 | 已知、NULL、有效 consumed 以外，恰好一列帳號列 *a*，且 `a.state == r.status`；其他已知暫停列允許存在 | `k2_unresolvable`／`finished_request_unmappable` |
| M11 | `a.registration` 等於目前選取的 registration | `k2_other_registration`／`unknown_request_owned_by_another_registration` |
| M12 | ledger mtime 至少 300 秒前（D3） | `max_age_ok=False`／`unknown_request_too_recent` |

M2、M3、M9 的解除錯誤不沿用 `active_or_unknown_request`，因為它的 B1 文字是「無法解除暫停」，在這裡會誤導。
帳號列超過 1024 列時，S1 先執行的 R1 inspector（`_unknown_request_snapshot` 計算所有列）會先丟出
`account_controls_invalid`，畫面顯示這個錯誤，K2 inspector 不會被呼叫；不另立代碼。
檢查結果不揭露是哪一條規則失敗；`k2_other_registration` 不帶序號、次數、檔名、代碼或 registration，
維持 R1 合約（[IMPLEMENTATION_CONTRACTS.md](../agent/IMPLEMENTATION_CONTRACTS.md)）。

### 新增 provider 函式（G3），R1 函式不變

```python
def inspect_finished_unknown_request(credential_reference, controls_path) -> dict
    # {'kind': 'k2_resolvable'|'k2_other_registration'|'k2_unresolvable'|'none',
    #  'sequence': int|None, 'calls': int|None, 'max_age_ok': bool, 'outcome': str|None}
    # 只有 k2_resolvable 帶數字與 outcome（固定的本機代碼，見 D6）。
    # 唯讀：?mode=ro + BEGIN、不建表、不改 mtime；sqlite3.Error/OSError -> account_controls_unavailable。

def resolve_finished_unknown_request(credential_reference, controls_path, *, user_confirmed=False,
                                     acknowledgement_version=None, expected_sequence=None,
                                     expected_calls=None, expected_outcome=None) -> None
```

`expected_outcome` 是對話框顯示的那個代碼。只綁 `(sequence, calls)` 不夠：新的 campaign 或 analysis 出現 K2 時幾乎都是 `(1, 1)`，
一個還開著的舊對話框可能在中間有人解除、清除、又出現新 K2 之後送出。綁上代碼後，不符就拒絕。

`inspect_unknown_request`、`resolve_unknown_request`、`_reserve`、`_finish`、`_persist_account_pause`、
`clear_account_pause`、`read_account_status`、`ERROR_STATES`、`ACKNOWLEDGEMENT_VERSION`、`_create_resolution_audit`
的行為都不變。

### 解除交易（一個交易，全部成功或全部不做）

交易骨架沿用 R1（[第 689 行](../../desktop_chatgpt_provider.py:689)：delete journal、`synchronous=FULL`、`BEGIN IMMEDIATE`、
ATTACH ledger、先算 provenance），但寫入內容**刻意不同**：R1 把 `plan_budget.blocked` 改成 `user_confirmed_consumed`，
R2 保留原代碼；R1 的 `plan_accounts` UPDATE 沒有 state／owner 條件並會設 `owner=NULL`，R2 要求 `state=<代碼> AND owner IS NULL`；
R1 更新 `plan_calls` 沒有 status 條件，R2 要求 `status=<代碼>`；R2 的兩個 UPDATE 都檢查 rowcount。

1. 任何 I/O 之前：`user_confirmed is True`、版本是 int 且等於 `FINISHED_ACKNOWLEDGEMENT_VERSION`
   （`True`、`1.0`、`'1'` 都拒絕），`expected_sequence`／`expected_calls` 是 1..100 的 int，
   `expected_outcome` 在 K2 集合內；否則 `resolution_confirmation_required`。再用 `_resolution_controls` 檢查參數與連結。
2. `_open_account_controls(readonly=False)`；`journal_mode` 必須是 `delete`（WAL 直接拒絕，不重設）；
   `synchronous=FULL`；`BEGIN IMMEDIATE`（全安裝寫入鎖）。
3. 在鎖內重新完整計算 M0–M12；結果的 `(sequence, calls, r.status)` 必須等於三個 expected 值，否則
   `no_resolvable_unknown_request`（使用者看到的狀態已變更）。
4. ATTACH ledger（rw），附加的資料庫也要 `delete`／`synchronous=2`；用 `_checked_campaign_rows` 重讀，
   budget 與整列 receipt 必須和快照相同；兩張稽核表都不能已有 `(filename, sequence)` 的列；
   否則 `campaign_controls_inconsistent`。
5. 任何寫入前先算 `content_hash(implementation_provenance())`，失敗就零寫入。
6. 用 `execute`（不是 `executescript`，避免隱含 commit）建立或驗證稽核表：
   **表的 CREATE SQL 和兩個觸發器**都要正規化後完全相符，既有的寬鬆表或 no-op 觸發器不會被沿用
   （`account_controls_invalid`）。
7. 寫入：INSERT 稽核列；`UPDATE plan_calls SET status='user_confirmed_consumed' WHERE sequence=? AND status=<代碼>`；
   `UPDATE plan_accounts SET state='user_confirmed_consumed' WHERE registration=? AND state=<代碼> AND owner IS NULL`；
   兩個 UPDATE 的 rowcount 都必須是 1（比 R1 嚴格）。`plan_budget`、`plan_ledgers` 不寫。
8. `with db:` 結束時 commit；任何例外回滾所有附加資料庫，包括第一次的 CREATE TABLE。
   跨兩個檔案的原子性依賴 SQLite 的 super-journal；行程在交易中被殺的情況和 R1 一樣 UNVERIFIED。
   如果真的只寫入一半（例如有稽核列但 receipt 仍是原代碼，或 receipt 已是 consumed 卻沒有稽核），
   屏障會一律視為未知，兩個 inspector 都拒絕：這是 fail-closed，但會**永久卡住**，需要另一份設計，沒有重試或還原路徑。

`receipt_hash` 由單一 helper `_receipt_digest(row)` 計算，輸入固定為 `_checked_campaign_rows` 回傳的原始 8 欄 tuple
（`usage` 是 JSON 字串 `'"unknown"'`，`elapsed_seconds` 是 SQLite REAL），不是 `_rows_to_receipts` 的 dict。
寫入端和屏障驗證端都只呼叫這個 helper，避免兩邊算法不同導致「成功寫入卻永遠驗證失敗」。

### 稽核表（account controls DB）

```sql
CREATE TABLE IF NOT EXISTS plan_finished_resolutions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT NOT NULL, sequence INTEGER NOT NULL, request_hash TEXT NOT NULL,
  receipt_hash TEXT NOT NULL,            -- _receipt_digest(轉換前的 8 欄 receipt)
  registration TEXT NOT NULL,
  previous_status TEXT NOT NULL CHECK(previous_status IN (<40 個字面代碼>)),
  new_status TEXT NOT NULL CHECK(new_status='user_confirmed_consumed'),
  acknowledgement_version INTEGER NOT NULL,
  official_usage_checked INTEGER NOT NULL CHECK(official_usage_checked=1),
  no_refund_acknowledged INTEGER NOT NULL CHECK(no_refund_acknowledged=1),
  other_usage_acknowledged INTEGER NOT NULL CHECK(other_usage_acknowledged=1),
  confirmed_at_utc TEXT NOT NULL, implementation_hash TEXT NOT NULL,
  UNIQUE(filename, sequence));
-- 另加 plan_finished_resolutions_no_update / _no_delete，內容 RAISE(ABORT,'append_only')
```

為什麼不沿用 R1 的 `plan_resolutions`：它有 `CHECK(previous_status='reserved_unknown')`
（[第 673 行](../../desktop_chatgpt_provider.py:673)），無法用 ALTER 放寬；重建表會改寫稽核歷史；
寫入假的 `reserved_unknown` 會偽造證據，而且 R1 版本會把它當成真的 K1 稽核。
也不建立跨表觸發器：擁有者的安裝沒有 `plan_resolutions`，那種觸發器會讓每次 INSERT 失敗。
不記錄 token、email、帳號名稱、遠端內容、官方頁面上的數字、截圖或 URL。

### 屏障驗證（`_confirmed_registration`）

[`_resolution_registration`](../../desktop_chatgpt_provider.py:525) 目前在觸發器檢查失敗時回 None，
而「表不存在」也算失敗。新的組合函式 `_confirmed_registration(db, schema, filename, receipt, budget)`：

- `schema` 和 R1 一樣只接受 `'main'`、`'account_controls'`，所有查詢都要加 schema 前綴
  （`<schema>.sqlite_master`、`<schema>.plan_finished_resolutions`）。屏障也會在 `_reserve` 內執行，那時 `main` 是 campaign ledger、
  controls 掛在 `account_controls`；沒加前綴會查到 ledger，導致已解除的 receipt 被當成未知，或把 ledger 裡同名的假表當成證據。
- 表不存在 → 0 列；表存在但觸發器（K2 表另加表 SQL）驗證不過 → 該 receipt 回 None（fail-closed）；
  `sqlite3.Error` → None。
- 兩張表合計必須**恰好 1 列**；兩張表都有 → None。
- R1 列：先呼叫現在的 `_resolution_registration`（本身不改，R1 行為與測試不變），再額外要求 `budget.blocked == 'user_confirmed_consumed'`。
  合法的 R1 解除一定會把 `blocked` 改成 consumed；`blocked` 仍是 K2 代碼卻配一筆 R1 形狀的稽核列，代表有人偽造，維持 pending。
  R1 版本的程式偵測不到這種組合（見降版表）。
- K2 列：`request_hash` 相符；registration 為 32 位 hex；`previous_status` 在 K2 集合內**且**等於 `budget.blocked`；
  `new_status` 為 consumed；`receipt.sequence == budget.calls`；`response_hash` 為 NULL、`usage` 為 `"unknown"`；
  版本在凍結集合內；三個旗標都是 int 1；UTC ISO 時間；64 位 hex 實作 hash；
  `receipt_hash` 等於「把目前 receipt 的 status 換回 previous_status」後的 `_receipt_digest`（事後改 bytes／usage／elapsed 會被抓到）。

呼叫點：`_installation_barrier`（[第 496–503 行](../../desktop_chatgpt_provider.py:496)，第 496 行的 `_checked_campaign_rows` 提供 `budget`）
和 R1 的 `_unknown_request_snapshot`（[第 600 行](../../desktop_chatgpt_provider.py:600)，第 623–638 行的迴圈）都改用組合函式並傳入 `budget`。
後者也要改，否則解除過一次 K2 之後，R1 會拒絕所有之後的 K1。這會碰到 R1 的程式路徑，
以所有 R1 測試原封不動通過作為保證。

### 畫面流程（非 G3；沿用 R1 的按鈕與對話框，不新增 widget）

1. **S0**：K2 安裝回報 `reserved_unknown`/pending，現有「核對未知請求…」按鈕已經依 R1 條件顯示
   （[desktop_chatgpt_ui.py](../../desktop_chatgpt_ui.py)）。
2. **S1**：worker 在同一個 `inspect_unknown` 請求內先呼叫 R1 `inspect_unknown_request`；**只有**回 `k2_unresolvable`
   時才再呼叫 K2 inspector。`k1_*`、`none` 原樣回傳。K2 inspector 若丟出 `PlanError`，經 `_safe_error_code`
   顯示錯誤，不改寫成別的 kind。`ReconciliationEvent` 新增 kind `k2_resolvable`（數字規則同 `k1_resolvable`）
   和 `k2_other_registration`（不帶數字）；`('k2_unresolvable',1,1,False)` 仍然無效；
   新增選填欄位 `inspection_outcome`，只允許搭配 `k2_resolvable`，值必須在 UI 端的凍結代碼集合內（D6）。
3. **S2 對話框**（[desktop_pages/chatgpt_reconciliation.py](../../desktop_pages/chatgpt_reconciliation.py)）：
   `ReconciliationDialog(..., finished=False)`，文字鍵用字面分支的三元式；objectName 全部不變。
   摘要用新鍵；說明沿用 R1，後面接一句「即使這次可能沒有送達伺服器，也會記錄為已消耗」；
   勾選框 ③ 的物件不變，只把文字鍵換成新鍵（官方用量頁也包含 App 以外工具的請求，App 無法分辨）。
   `_show` 對 `k1_resolvable` 或 `k2_resolvable` 且 `max_age_ok is True` 才開啟；
   `_submit` 依 kind 送出 `resolve_unknown`（K1）或 **`resolve_finished_unknown`**（K2，帶上檢查時看到的 sequence、calls 和代碼），
   不會互相 fallback。
4. **S3**：沿用 R1 的 `resolved`（已寫明到「進階連線管理」按「核對額度後申請解除已知暫停」）、
   `pending`、`resolved_unverified`、`resolved_ready`。

新動作 `resolve_finished_unknown`：加入 `ACTIONS`、`RECONCILIATION_ACTIONS`（因此在 `LOCAL_ACTIONS`，不會中止其他工作）
和需要 registration 的清單；確認版本規則改成依動作各自精確比對。

`ConnectionRequest` 是 dataclass，`payload()` 就是 `asdict(self)`。新增三個選填欄位 `expected_sequence`、`expected_calls`、
`expected_outcome`，**附加在 `acknowledgement_version` 之後**、預設 None，維持既有的位置參數順序。因為 `asdict` 會序列化所有欄位，
**每個動作**的 payload 都會多出這三個鍵（非 K2 解除時都是 None），所以：

- UI 端建構檢查：只有 `resolve_finished_unknown` 可以（而且必須）帶這三個值；其他動作帶任何非 None 值都拒絕。
- [quantlab/desktop_runtime.py](../../quantlab/desktop_runtime.py:1426) 第 1426 行的 `allowed` 鍵集合：把三個鍵加進選填集合
  （和 `model`、`acknowledgement_version` 同一層）。第 1438–1447 行的版本與 registration 檢查改成依動作分支：
  新動作要求 `user_confirmed is True`、版本 int 1、兩個數字是 1..100 的 int、`expected_outcome` 是 1..64 字元的小寫代碼字串；
  32 位 hex registration 規則涵蓋三個核對動作；其他動作帶版本或任一 expected 值仍然拒絕。
- 少了這兩處修改，舊的 runtime 會把新 payload 當成 `Invalid authentication request` 拒絕；
  `test_chatgpt_auth_job_payload` 的 payload 形狀因此會改變，列為核准的 baseline 變更。
[desktop_pages/settings.py](../../desktop_pages/settings.py:66)（第 66、193 行）改為引用 `RECONCILIATION_ACTIONS`。

文字草案（[desktop_strings.py](../../desktop_strings.py:2375) 新的尾端區塊
`# Lane R2: ChatGPT finished-unknown reconciliation`，放在 `RETAINED_CATALOG_KEYS` 之前，不重複鍵）：

- `chatgpt_reconciliation_k2.summary`：「第 {0}／{1} 次請求已經結束，但沒有正常完成。App 無法判斷它是否已送達或已計入官方用量。（App 內部結果代碼：{2}，可提供給維護者；你不需要看懂它）」
- `chatgpt_reconciliation_k2.other_usage`：「我了解官方用量頁也包含 App 以外工具（例如命令列程式）送出的請求，App 無法替我分辨」
- `chatgpt_reconciliation_k2.too_recent`：「這筆請求剛結束不久，請至少等待 5 分鐘，讓官方用量頁有時間更新後再核對。」
- `chatgpt_reconciliation_k2.other_registration`（給 `k2_other_registration`）：「這筆請求是用另一個本機連線送出的。請在上方連線選單切換到那個連線後再核對；如果選單裡找不到它，目前版本無法人工核對。」
  R1 的 `other_registration` 文字假設另一個帳號仍在登入中，K2 的情況不一定成立，所以另立一個鍵。
- `chatgpt_reconciliation_k2.unmappable`（給 `k2_unresolvable`）：「這筆請求已經結束但結果未知，而且本機紀錄無法唯一對應到一個帳號，目前版本無法人工核對。請保留本機紀錄，不要手動修改，等待後續版本處理。」
  R1 區塊已合併的 `chatgpt_reconciliation.k2` **不就地改寫**（desktop_strings 只能在尾端 Lane 區塊新增）；
  改由訊息對應改用新鍵。如果 `test_desktop_text_aliases` 因此判定舊鍵未使用，就在 R2-B 中刪除舊鍵，作為需核准的變更（只刪除，不改文字）。

錯誤（[quantlab/errors.py](../../quantlab/errors.py:60) B1 `ERROR_TABLE`）：新增 `finished_request_unmappable`
（「已結束但結果未知的請求，無法從本機紀錄唯一對應到一個帳號。」／「請保留本機紀錄，不要手動修改；這個情況需要後續版本處理。」）；
`no_resolvable_unknown_request` 的提示改成「請重新按「核對未知請求…」。」（D8）。
worker 只會顯示在 `ERROR_LABELS`（由 `ERROR_TABLE` 產生，[errors.py](../../quantlab/errors.py:148)）裡的代碼，其他一律顯示
`operation_failed_plan`；所以 R2 用到的每個 `PlanError` 代碼（包括 `finished_request_unmappable`）都必須在表內，並加測試確認。

### research、saved-candidate pool、命令列工具

- [quantlab/research.py](../../quantlab/research.py)（G3）：**不改**。K2 代碼和 `user_confirmed_consumed` 都已在白名單；
  非 `completed` 的 receipt 照舊擋住選擇、OOS 和 holdout。
- [quantlab/saved_candidate_pool.py](../../quantlab/saved_candidate_pool.py)（受保護 profile 區塊）：provider 位元組一改，
  `implementation_provenance` 的 LF/CRLF sha 就變，之後的 `chatgpt_plan` campaign 都會在 implementation tuple 被拒。
  需附加一個凍結的 `FINISHED_UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1`（引擎 hash 同 R1 的 SIWC，只換 provider sha），
  `SUPPORTED_PRODUCERS` 21 → 22；不需要 TRANSPORT profile，歷史 profile 不動，只收 `completed` 的規則不變。
  說明「只換 provider sha」的精確意思：`engine_source_hashes['provider.py']` 指的是 `quantlab/provider.py`，**不變**；
  變的是 `chatgpt_plan_implementations[*].source_sha256['desktop_chatgpt_provider.py']`（LF 與 CRLF 各一筆）。
- [tools/validate_web_search.py](../../tools/validate_web_search.py)：**不改**。未解除時仍是 `account_not_ready`/pending；
  解除後顯示既有的 `user_confirmed_consumed` 提示。

### 降版與回滾

| 讀取 R2 已解除資料的版本 | 結果 |
|---|---|
| R1（`fdd09eb`） | 找不到 R1 稽核列 → receipt 視為未知 → pending；檢查回 `k2_unresolvable`，解除與清除都拒絕；**fail-closed、不寫入**。注意：R1 版偵測不到「K2 代碼的 `blocked` 配偽造的 R1 稽核列」，這個檢查只存在於 R2 |
| R1 之前（`066a4a1`） | 白名單沒有 `user_confirmed_consumed` → 每個狀態讀取都丟 `campaign_controls_invalid`；fail-closed（較吵，與 R1 資料在該版相同） |
| revert R2 後再升級 | revert 期間同 R1 列；K2 表保留且無害，再升級時用凍結規則重新驗證 |

已解除且已清除暫停的安裝，降回 R1 版會重新被封鎖（pending）。沒有任何路徑把紀錄改回 `reserved_unknown`。

### 考慮過但不採用的方案

- 修改 R1 的入口讓它接受 K2：反轉被釘住的測試，也混淆意圖。
- 預留時寫入 registration 對應紀錄：在目前不變條件下是多餘的，卻要改每次請求都會走的 `_reserve`，
  而且永遠不能變成必要條件（舊版預留沒有紀錄），還多一種封鎖模式。
- 列出所有 K2 讓使用者挑選：會揭露其他 registration 的序號、次數和代碼，違反 R1 合約；
  在嚴格規則下最多只有一筆可選，等於只是更大的 UI。讓使用者在同代碼多筆中挑選會產生無法驗證的錯誤歸屬。
- 保留 K2 代碼、只加稽核：等於第二條放行路徑，正是 R1 F1 拒絕的方向。
- 新的最終代碼：要改 research（G3）、新 TRANSPORT profile，而且 R1 版會丟 `campaign_controls_invalid`。
- 調高 `ACKNOWLEDGEMENT_VERSION`：所有 K1 稽核列失效。

### 要修改的檔案

| 檔案 | G3／受保護 | 內容 |
|---|---|---|
| [desktop_chatgpt_provider.py](../../desktop_chatgpt_provider.py) | **G3** | 常數、`_confirmed_registration`、K2 驗證、`_finished_request_snapshot`、兩個新公開函式、K2 稽核建立與驗證、屏障與 R1 snapshot 的呼叫點；D7 另開 commit |
| [quantlab/saved_candidate_pool.py](../../quantlab/saved_candidate_pool.py) | **受保護 profile 區塊** | 附加一個 SIWC profile 和 `SUPPORTED_PRODUCERS` 項目 |
| [desktop_chatgpt_ui.py](../../desktop_chatgpt_ui.py) | 否 | 新動作、版本常數、event kind 與欄位、訊息對應、worker 串接與路由 |
| [desktop_pages/chatgpt_reconciliation.py](../../desktop_pages/chatgpt_reconciliation.py) | 否 | `finished` 旗標、依 kind 開啟與送出 |
| [desktop_pages/settings.py](../../desktop_pages/settings.py) | 否 | 閒置檢查與用量刷新排除涵蓋新動作 |
| [quantlab/desktop_runtime.py](../../quantlab/desktop_runtime.py) | 否 | 新動作的 payload 檢查 |
| [desktop_ui.py](../../desktop_ui.py) | 否 | 只確認 event 解碼可處理新欄位 |
| [desktop_strings.py](../../desktop_strings.py) | 否 | R2 尾端區塊（不改寫 R1 鍵；`chatgpt_reconciliation.k2` 若未使用則刪除） |
| [quantlab/errors.py](../../quantlab/errors.py) | 否（位元組被釘住） | `finished_request_unmappable`；改寫提示 |
| [docs/agent/IMPLEMENTATION_CONTRACTS.md](../agent/IMPLEMENTATION_CONTRACTS.md) | 否 | 附加 R2-A／R2-B，限定（不刪除）R1 的「Historical K2 and unknown states are unchanged」 |

影響範圍（撰寫設計時在**較舊的** GitNexus 索引上查詢，未在最新索引重跑，不能當成結論）：`_installation_barrier` 為 MEDIUM
（所有 ChatGPT 入口都經過），`_resolution_registration`、`_unknown_request_snapshot` 為 LOW，`run_connection_request` 的 LOW 只是下限。
實作者必須先重新索引、重跑 impact 並用 grep 確認呼叫者。research 的 `_validated_receipt_snapshot`（CRITICAL）不動。

## Safety constraints (live trading disabled, G3, OOS/budget)

真實交易永久停用，不新增任何下單路徑。只有一個 G3 檔（`desktop_chatgpt_provider.py`）要改，而且要擁有者明確核准；
另外六個 G3 檔、`quantlab/research.py` 和所有既有 profile 都不動，profile 只附加一個（同樣需核准），清單見
[contributor guide](../CONTRIBUTING.md)。次數不退還、不重設，receipt 不刪除；失敗、取消和結果未知都算已消耗。
fail-closed 閘門沒有放寬：沒有任何既有狀態會自己變成可放行，只有經人工確認、有稽核、可唯一對應的轉換能放行，
而且還要再經過一次已知暫停的解除。OOS 一次性消耗不變，OOS／final-holdout 資料不進入任何 AI 對話、工具回傳或 prompt；
所有 timeout 不變（Paper 30 秒、smoke 40 秒、每個研究工作 15 分鐘）；AI 輸出仍是不受信任的輸入，照現有 AST 規則驗證；
不使用 eval／exec 或其他動態執行，不新增 `compile`／`re.compile`；金額計算仍用 `Decimal`；
不連網、不讀取、儲存或顯示憑證，worker 不建立 `AuthSession` 或 vault；不用擁有者帳號做真實呼叫。

## Test plan

全部離線，使用現有的 `MockTransport`／`provider()` fixture。以下是需求，尚未執行。

必須原封不動並通過：

- [tests/test_chatgpt_plan.py](../../tests/test_chatgpt_plan.py)：`PlanTests` 的 P3–P6、屏障與跨 registration 測試、
  `test_delayed_metadata_error_cannot_downgrade_unknown_inference`；`UnknownRequestResolutionTests` 全部，
  特別是 `test_other_registration_and_k2_cannot_be_resolved`、稽核欄位、唯讀、偽造、觸發器、回滾和多行程測試。
- [tests/test_chatgpt_reconciliation_ui.py](../../tests/test_chatgpt_reconciliation_ui.py) 全部，
  包括 `test_worker_inspection_and_resolution_never_construct_auth_or_vault`、
  `test_nonresolvable_recent_error_and_lost_terminal_never_open_confirmation` 和對話框 objectName 集合。
- [tests/test_chatgpt_research.py](../../tests/test_chatgpt_research.py)、
  [tests/test_web_search_reconciliation.py](../../tests/test_web_search_reconciliation.py)、
  [tests/test_chatgpt_auth_job_payload.py](../../tests/test_chatgpt_auth_job_payload.py)（若 expected 欄位改變 payload，列為核准的 baseline 變更）、
  [tests/test_desktop_text_aliases.py](../../tests/test_desktop_text_aliases.py)、
  [tests/test_unknown_reconciliation_producer_profile.py](../../tests/test_unknown_reconciliation_producer_profile.py) 的行為測試、widget 與 R7 fixture。

新增 provider 測試（新類別 `FinishedRequestResolutionTests`）：

1. 擁有者形狀：`_reserve` 後 `_finish(1,'invalid_content_type', received_bytes=0, elapsed_seconds=3.1)`，mtime 調前 301 秒；
   檢查回 `k2_resolvable`(1,1,True)，authorizer 拒絕寫入、只用 `mode=ro`、不建表、位元組與 mtime 不變。
2. 解除：receipt 只有 status 改變；`blocked`、兩個 calls 不變；帳號列 `(user_confirmed_consumed, NULL)`；稽核欄位精確；
   沒有建立 `plan_resolutions`；狀態 `{'state':'user_confirmed_consumed','pending':False}`；`_reserve`、`discover_models`
   被拒且 `MockTransport.requests == []`。接著 `clear_account_pause` → ready，新 campaign 可 generate，舊的仍 `campaign_paused`。
3. 40 個代碼逐一 subTest 都能解除；字面集合等於 research 推導集合。
4. 拒絕且位元組不變：確認與版本變體、expected 不符、太新（299、0、負值）、其他 registration、沒有 controls、K1 並存、
   模稜兩可情況（零帳號列、兩筆 K2、代碼不符、非最後一筆、`blocked` 不符、`response_hash` 或 usage 形狀不符）、
   超過 1024 列、ledger 缺少或連結、WAL、provenance 失敗、每一個寫入失敗都回滾全部資料庫，且第一次失敗不留下 K2 表。
5. 偽造維持 pending：沒有稽核的 consumed；K2 稽核任一欄位錯誤（含 `receipt_hash` 和事後修改 bytes／usage／elapsed）；
   兩張表都有列；R1 列配壞掉的 K2 表、K2 列配壞掉的 R1 表；缺少或 no-op 觸發器；預先建立的寬鬆 K2 表不被沿用；
   UPDATE／DELETE 觸發 `append_only`。
6. R1 互動：K1 已解除並清除的 ledger 旁邊解除 K2；之後新的 K1 仍可由 R1 解除；R1 驗證器對 K2 列回 None（證明降版 fail-closed）。
7. 交易：journal 為 `[('delete',2),('delete',2)]`；多行程同時解除只有一個 commit；過期的 `_finish` 回
   `invalid_receipt_transition`；延遲的 `quota_paused` 不會取代 consumed；登出、新 registration、換工作區或還原舊副本都不會變成 ready。
8. 綁定：`expected_outcome` 與目前代碼不符時拒絕且位元組不變（模擬舊對話框在新的 `(1,1)` K2 出現後送出）。
9. Schema：解除並清除後，經由 `_reserve`（`main` 是 ledger）執行的屏障必須放行；ledger 檔內放一張同名的假
   `plan_finished_resolutions` 必須被忽略。
10. `_receipt_digest`：含 `elapsed_seconds=3.1` 的往返測試，寫入端與驗證端結果相同；手動建立兩種「只寫一半」的狀態都維持 pending、
    兩個 inspector 都拒絕、位元組不變。
11. 交叉偽造：K2 receipt 改成 consumed、`blocked` 仍是 K2 代碼、配一筆看似合法的 R1 稽核列（含觸發器），必須維持 pending。
12. `f985f91` 形狀：K2 receipt 的帳號列被覆寫成 `quota_paused`（保留或已清除）→ `finished_request_unmappable`、位元組不變；
    K2 加上另一個 registration 的 K1 → 兩個 inspector 都拒絕、位元組不變。
13. 錯誤代碼：R2 用到的每個 `PlanError` 代碼都在 `ERROR_LABELS` 內。

新增 UI 測試：新動作在 UI 與 runtime 兩端只接受版本 1，三個 expected 欄位只在新動作出現且型別正確、其他動作帶值被拒；
`k2_other_registration` 與 `k2_unresolvable` 顯示新的 R2 文字鍵；新 kind 的 event 驗證；worker 只在 `k2_unresolvable` 後呼叫 K2 inspector、
兩個 inspector 都被 patch、K2 inspector 錯誤不被吞掉、不建立 auth／vault／socket；`k2_resolvable` 開啟對話框且 objectName 不變，
太新、其他帳號、無法核對都不開啟；host race 拒絕不取消其他工作；無障礙走查與 snapshot 比對（沒有新 widget）。
新增 future 檔案 `tests/test_finished_reconciliation_producer_profile.py`：新 profile 唯一相符、混合 tuple 被拒、consumed 永不被收錄。

需擁有者核准、另開 commit 的 re-pin（不弱化任何測試）：
[tests/test_function_lengths.py](../../tests/test_function_lengths.py) 的 provider `LOCKED_HASHES`（該檔不為新 provider 函式提供長度預算）；
provider sha 與 profile 數量 21 → 22 的測試（`test_unknown_reconciliation_producer_profile`、`test_campaign_catalog_producer_profile`、
`test_subscription_producer_profile`、`test_models_limit_producer_profile`、`test_tls_anchor_producer_profile`、`test_fail_closed_producer_profile`）；
`tests/fixtures/ui_operations_golden.json` 的 pool hash 與 `test_golden_metadata` BASELINE；
`test_error_catalog_b1`（數量運算與改寫的提示）、`test_error_guidance_u7`（原始碼 sha）。
清單是否完整要靠改完後的完整 test discovery 確認。推送前執行 `powershell -File tools/prepush.ps1 -Tests`，並做文件連結檢查。
另附離線腳本：用 `fdd09eb` 的暫時 worktree 對已解除 fixture 的副本執行 `read_account_status`，預期 pending。

## 擁有者需要決定的事項

- **D0（先決檢查，不是選項）**：核准前請在 App 確認，擁有那一列帳號紀錄的 registration 仍能在帳號選單中選取並設為目前帳號。
  登出會保留 vault 項目，理論上仍可選（UNVERIFIED）。如果選不到，R2 只會顯示「另一個本機連線送出的」，你仍會卡住，需要另一份設計。
  這一步可以由我用唯讀方式在副本上比對（不讀 vault 內容就無法完全確認，所以最後仍以你在 App 看到的選單為準）。
- **D1：範圍。** 建議只處理可由現有資料唯一對應的 K2，所有模稜兩可的情況都拒絕，不新增預留對應紀錄。
- **D2：最終狀態。** 建議沿用 `user_confirmed_consumed`，原代碼保留在稽核 `previous_status` 和不變的 `plan_budget.blocked`；兩步恢復。
- **D3：時間防護。** 建議保留 300 秒（ledger mtime），配 K2 專用文字說明要等多久、為什麼。它對 K2 不是本機一致性防護，
  只是讓官方用量頁有時間更新；你的紀錄已經好幾天，不受影響。替代：K2 不設。
- **D4：入口。** 建議新增 `inspect_/resolve_finished_unknown_request` 和 UI 動作 `resolve_finished_unknown`，R1 API 和它的 K2 測試不變；
  解除時帶 expected sequence、calls 和結果代碼，綁定你看到的那一筆。
- **D5：稽核。** 建議獨立的 append-only `plan_finished_resolutions`，字面 40 代碼 CHECK（未來新增代碼需新表）、`receipt_hash`、
  表 SQL 與觸發器都驗證；K2 確認版本獨立；R1 版本與 `control_identity` 都維持 1。
- **D6：顯示原結果代碼。** 建議在對話框顯示固定的本機代碼（例如 `invalid_content_type`），標明「App 內部結果代碼，可提供給維護者」，
  不逐一翻譯 40 個代碼；透過選填欄位傳遞，4 欄 tuple 不變，有 drift 測試。本機紀錄時間暫不顯示。替代：完全不顯示代碼。
- **D7：`_finish` 加固。** 建議另開 commit、另行核准：`_finish` 永遠不寫入白名單外的代碼（改成 `failed_or_interrupted`），
  關閉 UNVERIFIED 的二次 `_finish` 情況；這會動到 `_finish` 熱路徑，所以分開核准。
- **D8：錯誤與文字。** 建議新增 `finished_request_unmappable`，M2／M3／M9 也用它；改寫 `no_resolvable_unknown_request` 的提示；
  R2 的文字全部放在新的尾端區塊，**不改寫** R1 已合併的 `chatgpt_reconciliation.k2`（若被判定未使用則刪除）；需要兩個錯誤目錄 re-pin。
- **D9：核准清單。** 建議一次核准以下全部，實作時若發現清單外的變更就停下來另外問你：provider G3 修改；附加一個 SIWC profile（21 → 22）；
  上面列出的所有 re-pin；IMPLEMENTATION_CONTRACTS 的 R2-A／R2-B。
- **D10：未來再卡住。** 建議另開後續項目，研究如何在不放寬閘門的前提下，把「確定送出前」的取消或逾時分類為已知狀態；R2 不處理。

## Rollout/Verification status

建議順序：(1) 擁有者確認 D0，核准這份設計與 D1–D10；(2) PR A：provider、profile、provider 與 profile 測試、
re-pin（另一個 commit）、R2-A 合約；(3) PR B（依賴 A）：UI、對話框、settings、runtime、文字、錯誤表、UI 測試、錯誤 re-pin、R2-B。
每個 PR 都要擁有者審查後才能合併；實作前重新索引 GitNexus、重跑 impact，commit 前跑 `detect_changes`。
真正的解除由擁有者在合併後於 App 內自行操作。
回滾方式：revert 程式碼；已解除的紀錄在 R1 版變成 pending（fail-closed），再升級時重新驗證。不提供改回 `reserved_unknown` 的路徑。
R2 的解除不可逆：只寫入一半或驗證不過的紀錄會永久卡住（fail-closed），要另一份設計才能處理。
仍為 UNVERIFIED：`invalid_content_type` 是否真的消耗用量；是否有安裝的資料來自 `f985f91` 時期；交易中被殺時 super-journal 的原子性；
二次 `_finish` 路徑；D0 的可選性。
Implementation: NOT IMPLEMENTED. Automated verification: NOT RUN.
Real-App visual check: PENDING USER FINAL CONFIRMATION.
[PROJECT_STATE](../agent/PROJECT_STATE.md) 和驗收分數不變（正式驗收仍為 230/300）；這份設計不包含任何 Release 或 tag。

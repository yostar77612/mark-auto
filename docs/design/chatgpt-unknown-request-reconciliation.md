# R1：人工核對未知 ChatGPT 請求

Status: PROPOSED / NOT IMPLEMENTED. Verification: NOT RUN.
擁有者核准前，不修改任何 G3 檔案，也不合併。

## Problem

PR #75（上網找策略點子）的帳號實測，在第一步
`tools/validate_web_search.py --list-models --i-consent` 就停住了，回報
`account_not_ready`、`account_state: reserved_unknown`、`pending_request: true`。
原因是先前有一次 ChatGPT 訂閱請求已經送出，但中途被打斷，留下一筆「結果未知」的紀錄。
這筆紀錄依設計會封鎖整個安裝的所有 ChatGPT 呼叫，連模型清單也包括在內。
目前沒有任何正規的方法可以解除它。

以下是我看程式碼觀察到的（版本 `493dc96`）：

- [desktop_chatgpt_provider.py](../../desktop_chatgpt_provider.py) 的 `_reserve`（第 629–656 行）在送出前，會在同一個交易裡寫入三樣東西：
  `plan_calls.status='reserved_unknown'`、`plan_accounts(state='reserved_unknown', owner=<binding>)`，以及 `plan_ledgers.calls+1`。
  只有同一次執行裡的 `_finish`（第 658–674 行）會把它改成最終狀態。
  如果行程被強制結束（例如取消、逾時、關閉視窗或當機），這三樣東西就會一直停在原狀。
- `_installation_barrier`（第 462–509 行）只要看到下列任一情況，就對整個安裝回傳
  `{'state':'reserved_unknown','pending':True}`：
  - 有一筆 receipt 的狀態不是 `completed`，也不在 `ERROR_STATES.values()` 裡；
  - `plan_accounts` 裡有 `owner` 不是 NULL 的列，或有 `state='reserved_unknown'` 的列。
- `clear_account_pause`（第 835–860 行）遇到 `pending` 會回 `active_or_unknown_request`；
  遇到不是已知遠端代碼的狀態，會回 `unknown_outcome_requires_manual_resolution`。
- [quantlab/research.py](../../quantlab/research.py) 的 `reconcile_interrupted_campaign` 只會把
  campaign 標成 `blocked_interrupted`，不會改動 provider 的 receipt。
- [quantlab/errors.py](../../quantlab/errors.py) 第 86 行寫著「須另行核對」，但程式裡並沒有提供核對的操作路徑。

### 設計前必須知道的三個發現

**F1：`failed_or_interrupted` 本身也被屏障當成「未知」。**
`ERROR_STATES.values()` 只有 7 個遠端已知代碼，例如 `quota_paused`、`grant_blocked`。
`_execute` 在送出之後失敗時，`_finish` 會寫入 `failed_or_interrupted`、`cancelled`、
`deadline_exceeded`、`eof_without_completion`、`invalid_output` 等代碼（第 806 行）。
這些都不在上述集合裡，所以屏障一樣會回報 `reserved_unknown`/pending，`plan_accounts.state`
也會變成屏障不認得的值，結果是 `blocked`/pending。
也就是說：**沿用 `failed_or_interrupted` 解不開封鎖**。
而如果改成讓屏障接受 `failed_or_interrupted`，所有歷史上已經存在的這類紀錄會在沒有人確認的情況下
一起被自動放行，這等於放寬了 fail-closed 閘門，所以不採用。
結論：需要新增一個**只能由人工路徑產生**的固定代碼。

**F2：卡住的紀錄有兩種，畫面上看起來一模一樣。**

| 類型 | `plan_calls.status` | `plan_accounts` | `plan_budget.blocked` | 能否把 receipt 對應回 registration |
|---|---|---|---|---|
| K1 孤兒預留（行程被強制結束） | `reserved_unknown` | `state='reserved_unknown'`, `owner=<binding>` | NULL | 可以：用 `owner` 等於 `plan_ledgers.binding` 對應 |
| K2 已結束但結果未知（同一次執行內發生例外） | 例如 `failed_or_interrupted`、`cancelled` | `state=<該代碼>`, `owner=NULL` | `<該代碼>` | 不能可靠對應：`plan_ledgers` 沒有記錄 registration，binding 也無法反推 |

**F3：資料本身無法分辨「孤兒預留」和「正在進行中的請求」。**
兩者都是 `reserved_unknown` 而且 `owner` 不是 NULL。
桌面 App 有單一實例鎖（[desktop.py](../../desktop.py) 的 `acquire_instance_lock`），也只有一個 worker，
但命令列工具（例如 `tools/validate_web_search.py`）可以在 App 之外同時執行。

## Goals/Non-goals

目標：

- 使用者先到 OpenAI 官方用量頁自行核對，再明確確認。確認後，**一筆** K1 receipt 會從
  `reserved_unknown` 轉成最終狀態 `user_confirmed_consumed`，意思是「已消耗，結果由使用者確認」。
- 轉換之後，安裝不會直接變成 ready，而是進入一個**已知暫停**。
  使用者核對額度後，再用現有的「核對額度後申請解除已知暫停」（`clear_pause`）恢復。總共兩步。
- 每次轉換都留下不可修改的稽核紀錄。屏障會檢查稽核紀錄，沒有稽核的
  `user_confirmed_consumed` 一律視為未知。

非目標，也是禁止事項：

- 不退還、不重設次數：`plan_budget.calls`、`plan_ledgers.calls` 都不變，該 campaign 或 analysis 永久停止。
- 不刪除 receipt，也不改寫 `request_hash`、`request_bytes`、`usage`、`received_bytes`。
- 不用經過的時間、登出、新增授權、備份還原、換工作區、重新啟動，或任何自動流程來觸發轉換。
- 不連網，不讀取官方頁面內容，不保存截圖、遠端文字或 token。
  應用程式不能也不會宣稱已經驗證過使用者看到的內容。
- 不用擁有者的帳號做任何真實呼叫。
- v1 不處理 K2（見決策 D1）。

## Design

### 狀態轉換（只有這一條是合法的）

```
K1: plan_calls[n].status       reserved_unknown        -> user_confirmed_consumed
    plan_budget.blocked        NULL                    -> 'user_confirmed_consumed'
    plan_accounts[R]           (reserved_unknown, B)   -> ('user_confirmed_consumed', NULL)
    plan_resolutions           (none)                  -> +1 append-only audit row
    plan_budget.calls / plan_ledgers.calls             unchanged (no refund)
```

之後：

1. 屏障看到 `user_confirmed_consumed` 的 receipt，而且有對應的稽核紀錄 → 不再視為未知。
2. 屏障看到 `plan_accounts.state='user_confirmed_consumed'`、`owner=NULL` → 視為已知暫停，回傳
   `{'state':'user_confirmed_consumed','pending':False}`。這時仍然不是 ready，`_reserve` 和模型清單都會被拒。
3. 使用者核對額度後按「恢復」→ 走現有的 `clear_account_pause`，它的檢查全部保留：
   不能有任何 pending、只能清除自己 registration 的那一列、不退還次數。
   允許清除的集合會多加 `user_confirmed_consumed`。
4. 原本那個 campaign 會因為 `plan_budget.blocked`，加上 research 端看到 receipt 不是 `completed`，
   停在 `blocked_provider_outcome`，永久不再送出。

### 新增 host-only 函式（G3：`desktop_chatgpt_provider.py`）

```python
def inspect_unknown_request(credential_reference, controls_path) -> dict
    # 唯讀，不連網。回傳固定欄位：
    # {'kind': 'k1_resolvable'|'k1_other_registration'|'k2_unresolvable'|'none',
    #  'sequence': int|None, 'calls': int|None, 'max_age_ok': bool}
    # 不揭露其他 registration 的身分、檔名或 hash。

def resolve_unknown_request(credential_reference, controls_path, *,
                            user_confirmed=False, acknowledgement_version=None) -> None
```

`resolve_unknown_request` 的前置條件。任何一項不符合，就回傳固定錯誤代碼並且不寫入任何東西：

1. `user_confirmed is True`，而且 `acknowledgement_version` 等於目前的確認文字版本常數。
   否則回 `resolution_confirmation_required`。
2. 參數型別與 `controls_path` 的檢查，和 `clear_account_pause` 一樣（`oauth_reference_required`、
   `installation_controls_path_required`），並拒絕符號連結。
3. 對 account controls 執行 `BEGIN IMMEDIATE`，取得全域寫入鎖；在同一個交易裡 ATTACH 目標 ledger（rw）。
4. `plan_accounts` 裡 `registration == 目前的 registration` 的那一列必須是
   `state='reserved_unknown'` 而且 `owner=B`；`plan_ledgers` 裡 `binding=B` 的列必須**恰好一列**。
   如果找不到自己的 K1，但安裝仍然 pending → 回 `unknown_request_owned_by_another_registration`。
   如果完全沒有 K1 → 回 `no_resolvable_unknown_request`。
5. 該 ledger 要通過 `_checked_campaign_rows`。最後一筆的序號必須等於 `calls`，狀態必須是
   `reserved_unknown`，前面每一筆都必須已經是最終狀態。
6. 在整個安裝範圍內，除了這一筆之外，不能有其他未知的 receipt，也不能有其他 owner 不是 NULL 的列。
   否則回 `active_or_unknown_request`。一次只處理一筆，處理完再重新檢查。
7. 時間防護：ledger 檔案的 mtime 距離現在必須至少 300 秒，也就是單次請求最長 120 秒的期限加上餘裕。
   否則回 `unknown_request_too_recent`。這只是補強 F3 的防線，不是安全邊界。
8. 寫入上面那四項，然後 commit。所有附加的資料庫都維持 `journal_mode=delete`、`synchronous=FULL`。

如果請求其實還在進行中（命令列工具在 App 外面跑），而使用者仍然確認了：
那個請求的 `_finish` 會因為 receipt 已經不是 `reserved_unknown`，而回 `invalid_receipt_transition`
並丟出例外（第 664–665 行），所以候選結果不會被採用；account 那一列因為 owner 已經清掉，也不會被覆寫。
結果仍然是 fail-closed，不會產生多算或少算。

### 稽核紀錄（account controls DB 新增資料表）

第一次解除時，在同一個交易裡建立下面這張表；`control_identity` 的版本維持 1。
`_open_account_controls` 只會檢查既有的資料表，所以多一張表不影響相容性。

```sql
CREATE TABLE plan_resolutions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT NOT NULL, sequence INTEGER NOT NULL, request_hash TEXT NOT NULL,
  registration TEXT NOT NULL,            -- 既有的 opaque registration，不是身分
  previous_status TEXT NOT NULL CHECK(previous_status='reserved_unknown'),
  new_status TEXT NOT NULL CHECK(new_status='user_confirmed_consumed'),
  acknowledgement_version INTEGER NOT NULL,
  official_usage_checked INTEGER NOT NULL CHECK(official_usage_checked=1),
  no_refund_acknowledged INTEGER NOT NULL CHECK(no_refund_acknowledged=1),
  no_other_tool_acknowledged INTEGER NOT NULL CHECK(no_other_tool_acknowledged=1),
  confirmed_at_utc TEXT NOT NULL,        -- ISO-8601 UTC，只做紀錄用
  implementation_hash TEXT NOT NULL,     -- content_hash(implementation_provenance())
  UNIQUE(filename, sequence));
CREATE TRIGGER plan_resolutions_no_update BEFORE UPDATE ON plan_resolutions
  BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER plan_resolutions_no_delete BEFORE DELETE ON plan_resolutions
  BEGIN SELECT RAISE(ABORT,'append_only'); END;
```

不記錄的資料：token、email、帳號名稱、遠端回應、使用者在官方頁面看到的數字、截圖、URL。

屏障新增的檢查：每一筆 `user_confirmed_consumed` 的 receipt，必須有一列稽核紀錄，而且
`(filename, sequence, request_hash)` 三者都相符；否則視為未知，也就是 pending。
`plan_accounts.state='user_confirmed_consumed'` 只有在至少有一列屬於該 registration 的稽核紀錄時，
才算已知暫停；否則算 `blocked`/pending。
這樣可以避免有人直接改 SQLite，偽造出「已確認」的狀態。

### 繞過分析

| 途徑 | 結果 |
|---|---|
| 登出或新增授權 | registration 必須和 `plan_accounts` 那一列相同；新的 registration 只會拿到 `unknown_request_owned_by_another_registration`，屏障維持 pending。 |
| 換另一個 registration 來核對別人的紀錄 | 同上。v1 不提供跨 registration 的解除（符合合約「不得解除別人的 pause」）。 |
| 備份還原或換工作區 | controls 放在 bootstrap 底下，不在工作區，流程完全不讀備份。如果還原成舊的 controls DB，會由既有的 ledger count 回退檢查（`campaign_controls_inconsistent`）擋下。稽核紀錄和 controls DB 綁在一起。 |
| 等時間過去或重新啟動 | 從來不會自動觸發；300 秒只是讓按鈕可以使用的下限，不會自己執行。 |
| 直接修改資料庫 | 有稽核表交叉檢查，加上 append-only 觸發器。這是加強防護，不宣稱能抵擋擁有本機管理權限的人。 |

### 畫面流程（`desktop_chatgpt_ui.py`，非 G3）

文字放在 [desktop_strings.py](../../desktop_strings.py) 的 `ui_text` 鍵，錯誤放在 B1
[ERROR_TABLE](../../quantlab/errors.py)。下面的文字是草案。

1. **S0 狀態列**：當 `account_state=='reserved_unknown'` 而且 `pending` 時，在現有「恢復」按鈕旁邊顯示
   「核對未知請求…」。這個按鈕只有在已選取 registration、worker 閒置、沒有任何工作在跑的時候才能按。
   `clear_pause` 按鈕維持停用。
2. **S1 唯讀診斷**：新增 ConnectionRequest 動作 `inspect_unknown`，在 worker 內執行，不連網。
   依結果顯示：
   - `k1_resolvable`：「第 n／N 次請求已送出，但 App 沒有收到完成結果。這一次可能已經計入官方用量。」→ 進入 S2。
   - `k1_other_registration`：「未知請求屬於另一個已登入的帳號，請切換到該帳號再核對。」
   - `k2_unresolvable`：「這筆請求已經結束，但結果未知，目前版本無法人工核對。」（依 D1 決定）
   - `max_age_ok=false`：「請求剛送出不久，請至少等待 5 分鐘，並確認沒有其他工具正在執行。」
3. **S2 核對與確認**（對話框）：
   - 說明：「請自行用瀏覽器開啟 OpenAI 官方用量頁，確認這段時間的用量。App 不會開啟或讀取這個頁面，
     也無法驗證你看到的內容。無論官方頁面顯示什麼，這一次都會記錄為**已消耗**，不退還次數，
     而這次研究批次會永久停止。」
   - 三個勾選框，每次都要重新勾選，不會被記住：
     ①「我已經在官方用量頁核對過」
     ②「我了解不會退還次數，這次研究批次會停止」
     ③「目前沒有其他工具或命令列程式正在送出 ChatGPT 請求」
   - 「記錄為已消耗」按鈕要三個都勾選才能按，預設焦點在「取消」。
     按下後送出 `resolve_unknown` 動作，帶上 `user_confirmed=True` 和確認文字版本。
4. **S3 結果**：「已記錄為使用者確認消耗。帳號目前處於已知暫停。」並提示使用者核對額度後，
   再按現有的「核對額度後申請解除已知暫停」。如果還有下一筆未知紀錄，就回到 S1。

`RECOVERABLE_PAUSES`、`set_account_status`、`set_usage` 的允許集合，以及 `clear_pause`
的前置條件（第 366–372 行），都要加入 `user_confirmed_consumed`。`ConnectionRequest`
的動作白名單（第 23、153、375、871 行）要加入 `inspect_unknown` 和 `resolve_unknown`。

### 考慮過但不採用的方案

- 沿用 `failed_or_interrupted`：根據 F1 解不開封鎖；如果改成讓屏障接受它，等於自動放行歷史紀錄。
- 一步完成（解除未知的同時清掉暫停）：步驟比較少，但會讓「核對單次請求」和「確認額度可以繼續用」
  混在同一次確認裡，而且繞過了 `clear_account_pause` 現有的全域檢查。
- 在 `plan_calls` 新增預留時間欄位，取代 mtime：需要遷移 schema，而且 `_checked_campaign_rows`
  會嚴格比對 8 個欄位。影響範圍比較大，留待以後。

## 受影響檔案與 GitNexus impact

GitNexus 索引：`C:\Users\Mark\Desktop\Mark auto`，lastCommit `493dc96`，和這個分支的基底相同；
「behind 5」是相對於主 checkout 目前所在的功能分支。callgraph 模式，只看 upstream。

| 符號 | risk | 直接（d=1） | d=2 | 備註 |
|---|---|---|---|---|
| `_installation_barrier` | LOW（11） | `clear_account_pause`、`read_account_status`、`_account_state`、`_reserve` | `discover_models`、`_execute`、`_preflight`、`run_connection_request`、`_chatgpt_reply`、`_handle_ui_analysis_preview`、`_handle_ui_chatgpt_usage` | 所有 ChatGPT 進入點都經過這裡，回歸測試要全部覆蓋 |
| `clear_account_pause` | LOW（2） | `run_connection_request` | `_handle_ui_chatgpt_auth` | 只放寬允許清除的集合 |
| `_validated_receipt_snapshot`（research） | **CRITICAL**（29，d1=6） | 5 個流程：`replay_and_compare`、`analyze`、`execute`、`admit_saved_campaign_pool`、`run_analysis` | | 只在 `statuses` 白名單加一個值；任何非 `completed` 的值在這些流程裡本來就會被停住 |

| 檔案 | G3 | 修改內容 |
|---|---|---|
| [desktop_chatgpt_provider.py](../../desktop_chatgpt_provider.py) | **是** | 新代碼、`inspect_unknown_request`、`resolve_unknown_request`、稽核表、屏障交叉檢查、`clear_account_pause` 允許集合 |
| [quantlab/research.py](../../quantlab/research.py) | **是** | `_validated_receipt_snapshot` 的 `statuses` 加入 `user_confirmed_consumed` |
| [desktop_chatgpt_ui.py](../../desktop_chatgpt_ui.py) | 否 | 新動作、允許狀態集合、S0–S3 |
| [desktop_ui.py](../../desktop_ui.py) | 否 | 如果需要，把新動作接到 `_handle_ui_chatgpt_auth` |
| [desktop_strings.py](../../desktop_strings.py) | 否 | 新的 `ui_text` 鍵 |
| [quantlab/errors.py](../../quantlab/errors.py) | 否 | 新錯誤代碼；第 86 行的提示改成指向新流程 |
| `tools/validate_web_search.py`（PR #75，尚未合併） | 否 | 遇到 `user_confirmed_consumed` 時顯示「已知暫停，請先在 App 恢復」 |
| 新測試（見下方） | 否 | |

## Safety constraints (live trading disabled, G3, OOS/budget)

真實交易永久停用，不新增任何下單路徑。兩個 G3 檔（`desktop_chatgpt_provider.py`、
`quantlab/research.py`）要等擁有者明確核准後才能修改；其他六個 G3 檔和 saved-candidate
profile 區塊都不動，清單見 [contributor guide](../CONTRIBUTING.md)。
次數不退還、不重設，receipt 不刪除；失敗、取消和結果未知都算已消耗。
fail-closed 閘門沒有放寬：既有的任何狀態都不會因為這次修改自動變成可以放行，只有經過人工確認、
而且有稽核紀錄的新代碼可以放行，而且還要再經過一次已知暫停的解除。
OOS/final-holdout 資料不會進入任何 AI 對話。不使用動態執行。
不讀取、儲存或顯示 ChatGPT 憑證。不用擁有者帳號做真實呼叫。

## Test plan

全部離線，使用現有的 `MockTransport`/`provider()` fixture。預期結果是需求，尚未執行。

[tests/test_chatgpt_plan.py](../../tests/test_chatgpt_plan.py) 新增：

1. K1 解除：先 `_reserve`，模擬行程結束，把 mtime 往前調 301 秒，再 `resolve_unknown_request(user_confirmed=True)`。
   預期：receipt 是 `user_confirmed_consumed`，calls 不變，`read_account_status` 回傳
   `{'state':'user_confirmed_consumed','pending':False}`，`_reserve` 和 `discover_models` 都被拒，`MockTransport.requests == []`。
2. 兩步恢復：接著 `clear_account_pause(user_confirmed=True)`，另一個 campaign 可以 generate；
   原 campaign 仍然 `campaign_paused`，次數沒有退還。
3. 拒絕路徑，每一條都要確認資料庫的位元組沒有變：未確認、版本不符、mtime 不足 300 秒、
   另一個 registration、K2、同時有兩筆未知、ledger 缺少或不一致、符號連結、`controls_path` 不符。
4. 偽造防護：直接把 receipt 改成 `user_confirmed_consumed` 但沒有稽核紀錄 → 屏障回報 pending；
   對稽核表執行 UPDATE 或 DELETE → 觸發器 ABORT。
5. 進行中衝突：先解除，再對原本的 provider 呼叫 `_finish(sequence,'completed',…)` → 回
   `invalid_receipt_transition`，receipt 和 account 那一列都不變。
6. 不能繞過：登出、新增 registration、換工作區路徑、還原舊的 controls 副本，都無法讓狀態變成 ready。
7. 多行程：在兩個行程裡同時呼叫 `resolve_unknown_request` → 只有一個成功，比照 `test_p5_multiprocess_atomic_pending_barrier`。

[tests/test_chatgpt_research.py](../../tests/test_chatgpt_research.py)：`user_confirmed_consumed`
的 receipt 會被接受為合法快照，campaign 停在 `blocked_provider_outcome`；
`reconcile_interrupted_campaign` 不會重新開啟它。

[tests/test_desktop_chatgpt_ui.py](../../tests/test_desktop_chatgpt_ui.py)：S0 按鈕只在 pending
而且閒置時可以按；三個勾選框沒有全部勾選時，確認按鈕停用；勾選狀態不會被保存；`clear_pause` 在
`user_confirmed_consumed` 時可以按，在 pending 時仍然停用；新動作的白名單和 IPC 錯誤只傳安全代碼。
新增 UI 需要做無障礙走查和 snapshot 比對，baseline 另開 commit 更新。

既有回歸測試一律不刪、不弱化，特別是 `test_p5_crash_barrier`、`test_p5_account_unknown_cross_campaign`、
`test_cross_registration_*`、`test_delayed_metadata_error_cannot_downgrade_unknown_inference`。
推送前執行 `powershell -File tools/prepush.ps1 -Tests`。

## 擁有者需要決定的事項

- **D1：K2 的範圍。** 建議 v1 只處理 K1。K2 的 receipt 無法可靠對應回 registration，要處理就得增加對應紀錄，
  或改成「由使用者從清單中選擇 ledger」。另外，K2 目前同樣會永久封鎖整個安裝，所以送出之後的取消也會卡住；
  如果你實際遇到的是 K2，就需要第二階段設計。
- **D2：** 兩步恢復（建議）還是一步完成。
- **D3：** 時間防護要用 300 秒（建議），還是不設。
- **D4：** 代碼名稱 `user_confirmed_consumed`；畫面文字用「已由使用者確認消耗」。

你目前卡住的是 K1 還是 K2，可以等實作後用唯讀的 `inspect_unknown` 判斷，不需要連網，也不會修改任何資料。

## Rollout/Verification status

建議順序：(1) 擁有者核准這份設計和兩個 G3 檔的修改；(2) 一個 PR 包含 provider、research
和測試；(3) 另一個 PR 處理 UI、文字和錯誤表；(4) PR #75 的工具在 (2) 合併後補上對應的狀態訊息。
回滾方式：不提供把狀態改回 `reserved_unknown` 的路徑；revert 程式碼後，`user_confirmed_consumed`
會被舊版屏障視為未知，結果仍是 fail-closed。
Implementation: NOT IMPLEMENTED. Automated verification: NOT RUN.
Real-App visual check: PENDING USER FINAL CONFIRMATION.
[PROJECT_STATE](../agent/PROJECT_STATE.md) 和驗收分數不變；這份設計不包含任何 Release 或 tag。

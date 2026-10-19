# T12 part A: legacy move decisions and verification

Scope: P2-B7 only. P2-B8/P2-B9 remain for subsequent runs. The optimization plan is unchanged.

## Decisions

All 39 files below were moved with `git mv` using a temporary Git index. Root `.git/index.lock` writes are denied by this sandbox. The original index is untouched; the controller must stage the deletions/new paths together. Git will detect these history-preserving renames. Temporary index/objects are outside the repository (`%TEMP%/markauto-t12-index`, `%TEMP%/markauto-t12-objects`); no commit, push, branch switch or stash was performed.

| Original tracked path | Decision / destination |
| --- | --- |
| `TelegramBot.md` | Only documents the legacy TelegramBot in archives/legacy_autotrading/trader/utils/bot.py; no product caller; `archives/legacy_autotrading/TelegramBot.md` |
| `archives/legacy_autotrading/gui.py` | Disabled upstream Streamlit entry; `archives/legacy_autotrading/gui.py` |
| `archives/legacy_autotrading/run.py` | Disabled upstream CLI entry; `archives/legacy_autotrading/run.py` |
| `archives/legacy_autotrading/trader/__init__.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/__init__.py` |
| `archives/legacy_autotrading/trader/config.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/config.py` |
| `archives/legacy_autotrading/trader/executor.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/executor.py` |
| `archives/legacy_autotrading/trader/indicators/signals.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/indicators/signals.py` |
| `archives/legacy_autotrading/trader/performance/__init__.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/performance/__init__.py` |
| `archives/legacy_autotrading/trader/performance/base.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/performance/base.py` |
| `archives/legacy_autotrading/trader/performance/charts.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/performance/charts.py` |
| `archives/legacy_autotrading/trader/performance/readme.md` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/performance/readme.md` |
| `archives/legacy_autotrading/trader/performance/reports.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/performance/reports.py` |
| `archives/legacy_autotrading/trader/scripts/README.md` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/scripts/README.md` |
| `archives/legacy_autotrading/trader/tasker.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/tasker.py` |
| `archives/legacy_autotrading/trader/utils/__init__.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/__init__.py` |
| `archives/legacy_autotrading/trader/utils/accounts.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/accounts.py` |
| `archives/legacy_autotrading/trader/utils/bot.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/bot.py` |
| `archives/legacy_autotrading/trader/utils/callback.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/callback.py` |
| `archives/legacy_autotrading/trader/utils/cipher.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/cipher.py` |
| `archives/legacy_autotrading/trader/utils/crawler.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/crawler.py` |
| `archives/legacy_autotrading/trader/utils/database/__init__.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/database/__init__.py` |
| `archives/legacy_autotrading/trader/utils/database/redis.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/database/redis.py` |
| `archives/legacy_autotrading/trader/utils/database/sql.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/database/sql.py` |
| `archives/legacy_autotrading/trader/utils/database/tables.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/database/tables.py` |
| `archives/legacy_autotrading/trader/utils/file.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/file.py` |
| `archives/legacy_autotrading/trader/utils/kbar.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/kbar.py` |
| `archives/legacy_autotrading/trader/utils/notify.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/notify.py` |
| `archives/legacy_autotrading/trader/utils/objects/__init__.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/objects/__init__.py` |
| `archives/legacy_autotrading/trader/utils/objects/data.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/objects/data.py` |
| `archives/legacy_autotrading/trader/utils/objects/env.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/objects/env.py` |
| `archives/legacy_autotrading/trader/utils/options.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/options.py` |
| `archives/legacy_autotrading/trader/utils/orders.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/orders.py` |
| `archives/legacy_autotrading/trader/utils/positions.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/positions.py` |
| `archives/legacy_autotrading/trader/utils/runtime.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/runtime.py` |
| `archives/legacy_autotrading/trader/utils/select.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/select.py` |
| `archives/legacy_autotrading/trader/utils/simulation.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/simulation.py` |
| `archives/legacy_autotrading/trader/utils/strategy.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/strategy.py` |
| `archives/legacy_autotrading/trader/utils/subscribe.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/subscribe.py` |
| `archives/legacy_autotrading/trader/utils/time.py` | Disabled upstream package; preserve source and headers; `archives/legacy_autotrading/trader/utils/time.py` |

Other root candidates were reviewed against `git ls-files`, the original 47-file import and reference searches:

- `LICENSE`: retain at root unchanged; installer input, Apache-2.0 and Copyright (C) 2023 Li Kuei-Wei. Archive README links to the full text; source headers remain intact.
- `README.md`: retain product instructions and later MarkAuto release sections; replace upstream description/commands with one provenance paragraph and relative archive link. Preserve the current desktop lock/build/install paragraph that had been embedded in the upstream section.
- `.gitignore`: retain current repository policy; move only legacy custom-strategy ignore/README exception paths.
- `.streamlit/config.toml`: retain; the active `research_app.py` still imports Streamlit and uses repository-local server/privacy settings. Not legacy-only.
- `archives/legacy_autotrading/requirements.txt`: already archived in P0-15; unchanged. No legacy configs (`lib/config.ini`, accounts or secrets) are tracked at root.
- All remaining tracked root Python modules, dependency files, `pyproject.toml` and directories belong to the current product, packaging, CI, examples, tests or documentation; retain. User-local untracked and ignored items were not modified.
- `archives/legacy_create_env_app/` and `docs/script samples/strategy_sample.py` retain historical imports/commands as archived or instructional reference. They are not product imports or root candidates, and are not installer inputs.

The only changed content among moved files is the relative strategy sample link in archived `archives/legacy_autotrading/trader/scripts/README.md` (now four levels to root). The other 38 files match their original Git blobs after normal text filtering, including every moved Python file. Historic internal paths/commands remain reference only; the archive README explicitly says they are unsupported and disabled.

## References and safety

- Updated all source/CLI paths in `tests/test_legacy_security.py`; 13 tests and 39 assertion calls before and after. Every changed line is recorded in `t12_test_edits.json`. No other existing test was edited.
- `tools/quality_gate.py` still scans every tracked archived Python file for syntax and credentials, and now checks archived import gates and API order-submission calls. Product import boundary also rejects `archives` so a qualified archived import cannot evade the previous `trader` restriction. Existing legacy tests still prove disabled CLI, inert broker, order gates and security behavior.
- PyInstaller excludes `archives` and `archives.legacy_autotrading` in addition to retaining `trader`/broker exclusions; setuptools explicitly excludes `archives*` and still includes only `quantlab*`.
- `packaging/build_manifest.py`, packaging tests, installer PowerShell, workflow filters/steps and other tool scanners contained no old filesystem paths requiring edits. Their recipe allow lists never included legacy. The existing inventory module `tests/test_payload_inventory.py` is absent.
- Audited documentation links: analysis references to old files are commit-pinned remote history or historical prose, so preserved per task instructions. No live relative analysis link to the moved files required an edit. Contracts now identify current archived entry paths and explain historical source locations; ACCEPTANCE.json records the new layout/evidence. Upstream omission paths in provenance remain original upstream paths, not local file claims.
- Product AST imports and text searches show no imports of `trader`, `gui`, `run` or archive modules in root product Python, `quantlab/` or `desktop_pages/`. Historical imports occur only in disabled/archive/example sources. G3 files and the optimization plan have empty diffs.

## Verification

- Native focused run initially hit Windows sandbox temporary-directory ACL errors. Execution-only shim changes `os.mkdir` mode 0700 to inherited ACL mode 0777; no repository test/assertion is patched. Final focused run (`tests.test_repo_layout`, `tests.test_legacy_security`, `tests.test_quality_gate`, `tests.test_packaging`): 47 tests, 1.534 s, exit 0, one existing skip because `pwsh` is unavailable. An intermediate quality fixture run inherited GIT_INDEX_FILE and failed; rerun removed that environment variable and passed.
- New tests independently without shim: 5 passed in 0.449 s, exit 0; slowest 0.427 s. No network, platform-dependent imports, cwd dependence, prints or heavyweight subprocesses were added.
- Stash-free `git archive HEAD` comparison executes real freezer spec with inert PyInstaller/third-party hooks and real manifest main with intercepted output. Expanded explicit data inventory (25 entries), script/runtime hook/hidden import lists and manifest input paths (108) are exactly equal. Detailed before/after inventories in `t12_payload_inventory.json`. Source hashes for intentionally edited recipe/gate files change; inventory membership does not. No native installer rebuild or dynamic freezer dependency analysis was claimed.
- `tools/quality_gate.py`: exit 0, zero findings, including all 36 tracked archived Python files. Used the temporary index/object database to represent moved/new files because the main Git metadata is read-only. A bare main-index scan before the controller stages renames will report missing old tracked paths; stage renames together before running CI.
- `py -3.11` utf-8-sig in-memory compile of all existing tracked plus new/moved Python files: 313 files passed, exit 0. No bytecode artifacts generated by that check.
- `git diff --check`: exit 0. Existing Git handling is `core.autocrlf=true`; modified text working copies normalized to CRLF, G3 and pinned raw-byte files untouched.
- No PowerShell files edited; edited-script parser checks therefore not applicable. Full unittest suite, architecture and T11 suites are controller-owned and not rerun per the explicit sandbox-only-focused instruction. Native installer execution remains unverified.

## GitNexus

Bound repository/worktree: `C:/Users/Mark/Desktop/Mark auto`. Index a95eab7 was 13 commits behind. Status checked and `analyze --index-only` attempted; refresh failed with sandbox spawn EPERM, no FTS download/install attempted. Pre-edit impact: archives/legacy_autotrading/trader/__init__.py MEDIUM (6 direct archived importers, 10 total; no reported processes); scan/python_findings LOW (gate main/scan and tests). File-only UNKNOWN results for GUI/CLI/tests were confirmed with direct source and reference searches rather than treated as safe. Change analysis on the main index reports CRITICAL (866 symbols, 144 affected, 47 files) as the entire legacy tree appears deleted before staging its new paths. This is not a clean updated-graph claim; controller should refresh after staging. Blob identity, complete archived security tests, import boundary and inventory evidence provide independent verification. No commit was made.

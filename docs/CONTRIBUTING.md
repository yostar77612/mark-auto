# Contributing

Keep each PR focused and use the [PR template](../.github/pull_request_template.md).
Read the [implementation contracts](agent/IMPLEMENTATION_CONTRACTS.md),
[project state](agent/PROJECT_STATE.md), [ADRs](adr/) and [glossary](GLOSSARY.md).
Feature PRs must not edit `docs/agent/PROJECT_STATE.md`. Append the item's behavior
contract to `docs/agent/IMPLEMENTATION_CONTRACTS.md`; do not change acceptance scores
or present unverified work as passed. Formal acceptance remains 230/300 in
[ACCEPTANCE.json](agent/ACCEPTANCE.json).

## Safety and ownership

Live trading is permanently disabled. Do not add a real order-placing path or
broker import. Never loosen fail-closed gates, OOS one-time consumption,
irreversible budgets or timeouts (Paper 30 s, smoke 40 s, 15 min per research job).
Failures, cancellation and unknown outcomes do not refund consumed budget.
OUT-OF-SAMPLE and FINAL-HOLDOUT data must never enter AI conversations, tool
returns or prompts. Treat AI output as untrusted input validated by the existing
AST rules; do not add dynamic execution. Money calculations stay `Decimal`.
Do not read, store or display ChatGPT credentials.

The G3 locked file set is exactly these eight files. They must not be edited
without owner approval:

- `quantlab/research.py`
- `quantlab/provider.py`
- `quantlab/core.py`
- `quantlab/strategies.py`
- `quantlab/backtest.py`
- `quantlab/data.py`
- `desktop_chatgpt_auth.py`
- `desktop_chatgpt_provider.py`

Also preserve the profile blocks in `quantlab/saved_candidate_pool.py`.
New UI strings go through [desktop_strings.py](../desktop_strings.py) with literal
`ui_text` keys; no hardcoded CJK literals in desktop modules or pages. Error text
uses the single B1 `ERROR_TABLE` in [quantlab/errors.py](../quantlab/errors.py).
Do not weaken, skip or delete existing tests or rewrite baseline fixtures to
conceal behavior changes.

## Local verification

Run from the repository root in PowerShell. Use Python 3.11 (`py -3.11`). Ruff
**0.16.10** is pinned with hashes in
[requirements-ruff.lock](../requirements-ruff.lock); configuration is in
[pyproject.toml](../pyproject.toml). For developer environment setup, see
[tools/dev_setup.ps1](../tools/dev_setup.ps1).

For the controller's Windows lane environment, the shared tools below are already
provisioned. These commands use that environment and do not install dependencies:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe' --version
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe' check .
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe' format --check .
py -3.11 -m compileall -q quantlab desktop_pages tools tests desktop.py research_app.py
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe' tools/quality_gate.py
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe' -m unittest discover -s tests -p test_docs_layering.py
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe' -m unittest discover -s tests -p test_repo_layout.py
```

Each check must exit 0, including [tools/quality_gate.py](../tools/quality_gate.py).
Record the exact commands and exit codes in the PR, including any failures.
In Windows worktrees, a known CRLF checkout issue may cause repo-wide formatting
to flag only `docs/adr/0006-strategy-intent-pipeline.md`. Do not normalize that
design document for this item; report the failure and separately check
changed files. This exception is not a claim that the repo-wide check passed.

Unit tests live under [tests/](../tests/). Run each affected module separately
using the discovery form above; dotted test names can be shadowed by an installed
package. Add the modules relevant to the change and record which modules ran.
These two documentation checks alone do not verify runtime behavior or full CI.
Keep new tests offline, deterministic and cheap; do not extend timeouts.

CI definitions are [quantlab.yml](../.github/workflows/quantlab.yml)
(Quantlab offline gates) and
[windows-desktop.yml](../.github/workflows/windows-desktop.yml)
(Windows desktop installer). Inspect their actual jobs when reporting CI
evidence; a local check does not establish that a workflow passed.
This documentation task does not publish a GitHub Release or create a git tag.

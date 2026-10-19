## Change

Describe the problem, resulting behavior, scope and linked issue or requirement.
See the [contributor guide](../docs/CONTRIBUTING.md).

## Verification

Check only completed checks; record failures and unverified work explicitly.

- [ ] Ruff 0.16.10 `ruff check .`
- [ ] Ruff 0.16.10 `ruff format --check .`
- [ ] `py -3.11` compile check
- [ ] `tools/quality_gate.py` exits 0
- [ ] Unit tests run (list each module under `tests/`)

Exact commands and exit codes (include interpreter/tool paths, environment,
tested commit and scope; attach evidence):

| Check | Exact command | Exit code / evidence |
| --- | --- | --- |
| Ruff check | | |
| Ruff format | | |
| Python 3.11 compile | | |
| Quality gate | | |
| Unit tests (one row per module) | | |

## Risk

Check each after reviewing the diff; explain any affected area below.

- [ ] G3 locked files reviewed: unchanged, or explicit owner approval linked.
- [ ] Gate, OOS one-time consumption, irreversible budget and timeout changes reviewed; none loosened.
- [ ] Live-trading path reviewed: live trading remains permanently disabled; no real order path added.
- [ ] ACCEPTANCE score change reviewed: score remains 230/300; no higher score claimed.

Affected areas, owner approval evidence, remaining risks and unverified work:

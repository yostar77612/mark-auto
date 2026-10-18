from pathlib import Path
import json
p=Path('docs/agent/IMPLEMENTATION_CONTRACTS.md')
s=p.read_text(encoding='utf-8')
s+='''

## T5 — Desktop theme and style module

- `desktop_theme.py` owns colour tokens (`COLORS`, `STATUS_COLORS`), pixel font sizes,
  spacing and the complete application QSS. `build_app_stylesheet()` resolves these
  tokens; `apply_theme()` installs it on the QApplication, leaving widget QSS empty.
- Existing objectNames and `role=primary|secondary|danger` remain stable. Runtime
  status colours use `status=success|warning|danger|neutral`; `set_status()` validates
  the state and unpolishes/polishes the widget. Market rise/fall and notification
  colours retain their original scoped palette. Form feedback uses a temporary
  `feedback` property and restores its previous value after 1800 ms.
- No desktop or tools module may call `setStyleSheet` outside the theme module.
  The AST and runtime allowlists in `tests/test_no_inline_stylesheet.py` are empty:
  QPainter chart drawing needs no QSS exception. Tests cover every button role,
  empty widget stylesheets, live status palette refresh, and existing feedback.
- Visual parity is checked against a `git archive HEAD` copy with
  `tools/ui_snapshot.py --size 1366x768` on both trees using identical Qt settings.
  `tools/ui_theme_diff.py BEFORE AFTER` requires identical metrics, PNG sets and
  dimensions, with at most 0.1% of pixels having any RGB channel delta above 8.
  T5 evidence: `docs/analysis/baseline/t5_theme_1366x768.json` (all 14 PNGs: 0%).
- Presentation only: desktop strings, account decisions, safety validation, quotas,
  OOS consumption and pinned producer sources are unchanged.
'''
p.write_text(s,encoding='utf-8')
p=Path('docs/agent/ACCEPTANCE.json'); s=p.read_text(encoding='utf-8'); data=json.loads(s)
entry={'contract':'docs/agent/IMPLEMENTATION_CONTRACTS.md#t5--desktop-theme-and-style-module', 'regressions':['tests/test_desktop_theme.py','tests/test_no_inline_stylesheet.py','tests/test_desktop_feedback_p0.py'], 'visual_evidence':'docs/analysis/baseline/t5_theme_1366x768.json','scope':'Presentation-only centralized QSS; existing widget names, text and business logic preserved. Full suite is run by the controller outside the sandbox.'}
s=s.rstrip(); s=s[:-1].rstrip()+',\n  "t5_desktop_theme": '+json.dumps(entry,ensure_ascii=False,indent=2).replace('\n','\n  ')+'\n}\n'
json.loads(s); p.write_text(s,encoding='utf-8')

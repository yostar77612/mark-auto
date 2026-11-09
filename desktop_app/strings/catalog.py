"""Desktop UI catalog. Domain error/feedback tables remain in quantlab.

Semantic keys describe scope, function and meaning in lowercase snake_case.
Historical positional keys resolve through TEXT_ALIASES, without stored text.
Dynamic messages use str.format templates; callers supply values after lookup.
"""

from .catalog_data import ZH_TW_CHUNKS as _ZH_TW_CHUNKS, TEXT_ALIASES as _TEXT_ALIASES

DEFAULT_LOCALE = 'zh-TW'


ZH_TW = _ZH_TW_CHUNKS[0].copy()

ZH_TW.update(_ZH_TW_CHUNKS[1])

ZH_TW.update(_ZH_TW_CHUNKS[2])

ZH_TW.update(_ZH_TW_CHUNKS[3])


# P1-05: technical spelling is documented here; default labels use plain wording.
GLOSSARY = {
    'bar': 'K棒',
    'OOS': '樣本外',
    'fixture': '離線示範',
    'validated_dataset': '已驗證資料',
    'SHA-256': '驗證碼',
    'hash': '驗證碼',
    'synthetic-assumption-v1': '合成資料假設',
    'TAIFEX:TMF:YYYYMM': '微臺指合約年月',
    '排除最終保留集起點': '最終保留資料起點',
    'bar 數': 'K棒數',
}
FORBIDDEN_DEFAULT_TERMS = tuple(GLOSSARY) + ('SHA256', 'TAIFEX:TMF:')
# Proper names, not engineering implementation codes. No forbidden-term exemptions.
DEFAULT_TERM_ALLOWLIST = ('Walk-forward', 'TMF', 'AI', 'ChatGPT', 'UTC')

ZH_TW.update(_ZH_TW_CHUNKS[4])

ZH_TW.update(_ZH_TW_CHUNKS[5])


ZH_TW.update(_ZH_TW_CHUNKS[6])

# Explicit fixed-code tables; tests compare their keys against the runtime sets.
LOG_OPERATION_NAMES = {key.removeprefix('logs.operation.'): key for key in ZH_TW if key.startswith('logs.operation.')}
LOG_EVENT_NAMES = {key.removeprefix('logs.event.'): key for key in ZH_TW if key.startswith('logs.event.')}

ZH_TW.update(_ZH_TW_CHUNKS[7])

ZH_TW.update(_ZH_TW_CHUNKS[8])

ZH_TW.update(_ZH_TW_CHUNKS[9])

ZH_TW.update(_ZH_TW_CHUNKS[10])

ZH_TW.update(_ZH_TW_CHUNKS[11])

ZH_TW.update(_ZH_TW_CHUNKS[12])

ZH_TW.update(_ZH_TW_CHUNKS[13])

ZH_TW.update(_ZH_TW_CHUNKS[14])

ZH_TW.update(_ZH_TW_CHUNKS[15])

LOCALES = {DEFAULT_LOCALE: ZH_TW}


ZH_TW.update(_ZH_TW_CHUNKS[16])


def ui_text(key, locale=None):
    """Look up a key at call time, falling back to zh-TW.

    Historical aliases resolve once before locale selection. An omitted locale
    uses DEFAULT_LOCALE. An unknown locale or a missing key
    in a partial locale falls back to the default catalog. Unknown keys raise
    KeyError, including when absent from the default catalog; no key is shown
    to the user as a substitute message.
    """
    key = TEXT_ALIASES.get(key, key)
    default = LOCALES[DEFAULT_LOCALE]
    catalog = LOCALES.get(locale or DEFAULT_LOCALE, default)
    if key in catalog:
        return catalog[key]
    return default[key]


ZH_TW.update(_ZH_TW_CHUNKS[17])


ZH_TW.update(_ZH_TW_CHUNKS[18])

ZH_TW.update(_ZH_TW_CHUNKS[19])


ZH_TW.update(_ZH_TW_CHUNKS[20])


ZH_TW.update(_ZH_TW_CHUNKS[21])

ZH_TW.update(_ZH_TW_CHUNKS[22])


ZH_TW.update(_ZH_TW_CHUNKS[23])


ZH_TW.update(_ZH_TW_CHUNKS[24])

ZH_TW.update(_ZH_TW_CHUNKS[25])
ZH_TW.update(_ZH_TW_CHUNKS[26])
ZH_TW['keyboard.help'] += '\uff1bCtrl+K \u958b\u555f\u547d\u4ee4\u9762\u677f\u3002'


ZH_TW.update(_ZH_TW_CHUNKS[27])
ZH_TW['keyboard.help'] += '\uff1bCtrl+Shift+N \u901a\u77e5\u4e2d\u5fc3\uff1bCtrl+Shift+D \u95dc\u9589\u63d0\u793a\u3002'

ZH_TW.update(_ZH_TW_CHUNKS[28])
# F1: rejected-import gap report (append-only catalogue extension).
ZH_TW.update(_ZH_TW_CHUNKS[29])

# F2: saved-result overlay (append-only catalogue extension).
ZH_TW.update(_ZH_TW_CHUNKS[30])
# F3: advisory copy wraps only the shared B1 catalogue.
ZH_TW.update(_ZH_TW_CHUNKS[31])

ZH_TW.update(_ZH_TW_CHUNKS[32])

ZH_TW.update(_ZH_TW_CHUNKS[33])

ZH_TW.update(_ZH_TW_CHUNKS[34])

ZH_TW.update(_ZH_TW_CHUNKS[35])

ZH_TW.update(_ZH_TW_CHUNKS[36])


ZH_TW.update(_ZH_TW_CHUNKS[37])


ZH_TW.update(_ZH_TW_CHUNKS[38])

ZH_TW.update(_ZH_TW_CHUNKS[39])

ZH_TW.update(_ZH_TW_CHUNKS[40])


# Lane P
ZH_TW.update(_ZH_TW_CHUNKS[41])


# Lane P
ZH_TW.update(_ZH_TW_CHUNKS[42])
LOG_OPERATION_NAMES['ui_paper_cancel_all'] = 'logs.operation.ui_paper_cancel_all'

# Lane V
ZH_TW.update(_ZH_TW_CHUNKS[43])
LOG_OPERATION_NAMES['ui_capital_scenario'] = 'logs.operation.ui_capital_scenario'

# Lane I: strategy idea research
ZH_TW.update(_ZH_TW_CHUNKS[44])
LOG_OPERATION_NAMES['ui_idea_research'] = 'logs.operation.ui_idea_research'
LOG_OPERATION_NAMES['ui_idea_adopt'] = 'logs.operation.ui_idea_adopt'

# Lane R
ZH_TW.update(_ZH_TW_CHUNKS[45])

# Lane R
ZH_TW.update(_ZH_TW_CHUNKS[46])

# Retained non-generic catalog API entries from earlier UI implementations.
# Current pages use AsyncStatus / the explicit restore-consent message instead.
# Lane R
ZH_TW.update(_ZH_TW_CHUNKS[47])

# Lane R
ZH_TW.update(_ZH_TW_CHUNKS[48])

# Lane R1: ChatGPT unknown-request reconciliation (PR #76, owner approved)
ZH_TW.update(_ZH_TW_CHUNKS[49])

# Lane R2: ChatGPT finished-unknown (K2) reconciliation (PR #83, owner approved)
ZH_TW.update(_ZH_TW_CHUNKS[50])

# Lane UI redesign: task workspaces and isolated preview
ZH_TW.update(_ZH_TW_CHUNKS[51])


# Lane download/import: automatic strict research import.
ZH_TW.update(_ZH_TW_CHUNKS[52])

# Lane multi-market-v2: separate local platform, preserving all legacy text.
ZH_TW.update(_ZH_TW_CHUNKS[53])

# Lane LM1 market watch
ZH_TW.update(_ZH_TW_CHUNKS[54])


# Lane LM1 dashboard
ZH_TW.update(_ZH_TW_CHUNKS[55])

# Lane M1-U: reviewed presentation corrections.
ZH_TW.update(_ZH_TW_CHUNKS[60])

# Lane M1-1: independent market connection.
ZH_TW.update(_ZH_TW_CHUNKS[57])

# Lane M1-2: market terminal.
ZH_TW.update(_ZH_TW_CHUNKS[56])

# Lane M1-3: typed alert controls.
ZH_TW.update(_ZH_TW_CHUNKS[58])

# Lane M2-6: trading-page environment and plain-language controls.
ZH_TW.update(_ZH_TW_CHUNKS[61])

# Lane M2-1: one reference-only Sinopac connection.
ZH_TW.update(_ZH_TW_CHUNKS[62])

# Lane M2-2: explicitly confirmed manual simulation intents.
ZH_TW.update(_ZH_TW_CHUNKS[63])

# Lane U1: read-only account readiness next steps.
ZH_TW.update(_ZH_TW_CHUNKS[64])

# Lane M2-9: date-only key expiry guidance.
ZH_TW.update(_ZH_TW_CHUNKS[65])

# Lane U2: manual recovery and exact exit preview.
ZH_TW.update(_ZH_TW_CHUNKS[66])

# Lane U3: typed strategy management.
ZH_TW.update(_ZH_TW_CHUNKS[67])

# Lane U4: account risk and explicitly resumed automatic execution.
ZH_TW.update(_ZH_TW_CHUNKS[68])

# Lane M4a: manual update and optional autostart.
ZH_TW.update(_ZH_TW_CHUNKS[69])

# Lane A: an empty strategy market needs a next step.
ZH_TW.update(_ZH_TW_CHUNKS[70])

# Lane B: sanitized login, initialization and subscription failure copy.
ZH_TW.update(_ZH_TW_CHUNKS[71])

# Lane research feedback: visible progress, evidence and explicit next steps.
ZH_TW.update(_ZH_TW_CHUNKS[72])

# Lane M3: frozen signal strategies and owner-only promotion intent.
ZH_TW.update(_ZH_TW_CHUNKS[73])

# Lane wizard risk hint: stock size limited by the isolated risk budget.
ZH_TW.update(_ZH_TW_CHUNKS[74])

# Lane Claude Code assistant: optional inference through the locally installed Claude Code.
ZH_TW.update(_ZH_TW_CHUNKS[75])

# Lane manual connection guidance: say what to do while the broker simulation is not connected.
ZH_TW.update(_ZH_TW_CHUNKS[76])

# Lane AI explain: the question prefilled for the assistant about the selected strategy.
ZH_TW.update(_ZH_TW_CHUNKS[77])

# Lane minute research: read-only day-trade research summary and guidance.
ZH_TW.update(_ZH_TW_CHUNKS[78])

RETAINED_CATALOG_KEYS = ('maintenance.checking', 'backup_inspection.required', 'help.hint.strategy', 'idea.entry_button')

# Compatibility only: historical positional keys never store rendered text.
TEXT_ALIASES = _TEXT_ALIASES

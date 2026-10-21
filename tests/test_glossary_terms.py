"""U11: cheap, context-scoped glossary contracts; no widgets or market data."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import unittest

import desktop_strings as strings


ROOT = Path(__file__).resolve().parents[1]


def canonical_terms(text):
    """Read the bilingual labels, rather than maintaining another canonical table."""
    return dict(re.findall(r'^- \*\*([^*（]+)（([^*）]+)）\*\*：.+$', text, re.MULTILINE))


@dataclass(frozen=True)
class Rule:
    scope: str
    label: str
    variants: tuple[str, ...]


# Scopes describe the concept named by a semantic key. A generic word such as
# "simulation", "data", "eligible" or "revision" is never banned globally.
# Label keys name the concept itself; action/status keys need not repeat it.
RULES = {
    'Backtest': Rule(r'backtest|quick_start', r'\.backtest_label$', ('歷史測試', '歷史回測試驗')),
    'Paper': Rule(
        r'paper|ui\.init\.(?:window_title|research_only_disclaimer)$',
        r'\.paper_label$',
        ('模擬交易', '紙上模擬', '模擬盤'),
    ),
    'Replay': Rule(r'replay', r'\.replay_label$', ('回放', '行情回演')),
    'Research eligibility': Rule(r'research|eligibility', r'\.research_eligibility$', ('研究合格', '研究准入', '研究適格')),
    'Paper eligibility': Rule(r'paper|eligibility', r'\.paper_eligibility$', ('紙上合格', '紙上准入', '紙上交易資格')),
    'OOS': Rule(r'oos|out_of_sample', r'\.(?:oos|out_of_sample)$', ('樣本之外', '樣本外部', '外樣本')),
    'Holdout': Rule(r'holdout', r'\.(?:holdout|final_holdout)$', ('留出集', '保留樣本集')),
    'Consumed guard': Rule(r'consumed|guard', r'\.consumed_guard$', ('消耗鎖', '已用防護')),
    'Irreversible budget': Rule(r'budget', r'\.irreversible_budget$', ('可退還預算', '不可回復額度')),
    'Strategy artifact': Rule(r'artifact', r'\.strategy_artifact$', ('策略製品', '策略工件')),
    'Strategy revision': Rule(r'revision', r'\.strategy_revision$', ('策略版次', '策略修訂版號')),
    'Live trading': Rule(r'live_trading', r'\.live_trading_label$', ('真倉交易', '實倉買賣')),
}

# Exact (semantic key, phrase) exceptions, never a whole key/prefix exemption.
# These preserve intentional synthetic-account language and stable log labels.
EXCEPTIONS = {
    ('ui.init.window_title', '紙上模擬'): 'Shell title emphasizes the synthetic account scope, not broker simulation.',
    ('ui.init.research_only_disclaimer', '紙上模擬'): 'Safety disclaimer explicitly excludes real orders and market quotes.',
    ('market.init.research_paper', '紙上模擬'): 'Market scope caption distinguishes research from the synthetic account.',
    ('notifications.paper_summary', '紙上模擬'): 'Notification heading describes the synthetic account summary.',
    ('paper.tabs.pnl_basis', '紙上模擬'): 'PnL basis explicitly describes synthetic unrealized accounting before costs.',
    ('logs.operation.ui_paper_kill', '模擬交易'): 'Existing operation-log label identifies the emergency stop operation.',
    ('logs.operation.ui_paper_replay', '模擬交易'): 'Existing operation-log label identifies historical replay of the synthetic account.',
    ('wf.oos', '前推'): 'Walk-forward wizard labels the forward fold; it does not claim independent OOS eligibility.',
}


def violations(catalog, terms, exceptions=EXCEPTIONS):
    """Return deterministic diagnostics plus exercised exceptions for stale checks."""
    failures, exercised = [], set()
    for key, text in sorted(catalog.items()):
        for term, rule in RULES.items():
            if term not in terms or not re.search(r'(?:^|[._])(?:' + rule.scope + r')(?:$|[._])', key):
                continue
            for phrase in rule.variants:
                if phrase not in text:
                    continue
                if (key, phrase) in exceptions:
                    exercised.add((key, phrase))
                else:
                    failures.append(f'{key}: {term} ({terms[term]}): noncanonical phrase {phrase!r}')
            # English labels are canonical too (including the English quick start).
            if re.search(rule.label, key) and terms[term] not in text and term.casefold() not in text.casefold():
                if (key, text) in exceptions:
                    exercised.add((key, text))
                else:
                    failures.append(f'{key}: {term} ({terms[term]}): missing canonical label in {text!r}')
    return failures, exercised


class GlossaryTermTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.terms = canonical_terms((ROOT / 'docs/GLOSSARY.md').read_text(encoding='utf-8'))

    def assert_catalog(self, catalog, exceptions=EXCEPTIONS):
        failures, exercised = violations(catalog, self.terms, exceptions)
        self.assertFalse(failures, '\n'.join(failures))
        return exercised

    def test_glossary_defines_exactly_the_rule_vocabulary(self):
        # Terms without a rule are descriptive (statistics, stop/resume wording): they need no scoped synonym rule.
        self.assertLessEqual(set(RULES), set(self.terms))
        self.assertGreaterEqual(len(self.terms), 12)
        for term, rule in RULES.items():
            with self.subTest(term=term):
                self.assertTrue(rule.variants)
                # Every rule accepts both parsed canonical forms and rejects
                # every declared variant without relying on production wording.
                key = 'fixture.' + term.lower().replace(' ', '_')
                if term == 'Backtest':
                    key += '_label'
                elif term in ('Paper', 'Replay', 'Live trading'):
                    key += '_label'
                for label in (term, self.terms[term]):
                    self.assert_catalog({key: label}, {})
                for variant in rule.variants:
                    failures, _ = violations({key: variant}, self.terms, {})
                    self.assertTrue(failures, (term, variant))
                    self.assertIn(key, failures[0])
                    self.assertIn(term, failures[0])

    def test_catalog_and_every_exception_are_exercised(self):
        exercised = self.assert_catalog(strings.ZH_TW)
        self.assertEqual(exercised, set(EXCEPTIONS))
        for (key, phrase), reason in EXCEPTIONS.items():
            with self.subTest(key=key, phrase=phrase):
                self.assertTrue(reason.strip())
                failures, _ = violations({key: strings.ZH_TW[key]}, self.terms, {})
                self.assertTrue(any(repr(phrase) in failure for failure in failures))

    def test_distinct_concepts_can_coexist(self):
        self.assert_catalog(
            {
                'fixture.backtest_paper_replay': '回測與紙上交易不同；歷史重播也不等於回測。',
                'fixture.research_paper_eligibility': '研究資格不等於紙上資格；兩者獨立檢查。',
                'fixture.oos_holdout': '樣本外與保留集分離。',
            }
        )

    def test_mixed_synonyms_fail_even_beside_canonical_text(self):
        fixtures = {
            'fixture.paper_label': '紙上交易／模擬盤',
            'fixture.out_of_sample': '樣本外／外樣本',
            'fixture.research_eligibility': '研究資格／研究合格',
            'fixture.paper_eligibility': '研究資格／紙上准入',
        }
        for key, text in fixtures.items():
            with self.subTest(key=key), self.assertRaises(AssertionError) as caught:
                self.assert_catalog({key: text})
            self.assertIn(key, str(caught.exception))

    def test_swapped_eligibility_labels_fail(self):
        for key, text in (('fixture.paper_eligibility', '研究資格'), ('fixture.research_eligibility', '紙上資格')):
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.assert_catalog({key: text})

    def test_unknown_terms_and_unrelated_context_are_not_banned(self):
        self.assert_catalog(
            {
                'fixture.dataset': '資料集／行情資料／資料',
                'fixture.video': '回放',
                'fixture.broker': '模擬交易',
                'fixture.newspaper': '模擬交易',
            }
        )
        failures, _ = violations({'fixture.paper_label': '模擬盤'}, {}, {})
        self.assertEqual(failures, [])

    def test_live_disabled_catalog_bytes(self):
        # Independent pre-U11 UTF-8 digests pin the entire messages, not just a
        # permissive "disabled" substring. Also reject unreviewed extra messages.
        expected = LIVE_DISABLED_SHA256
        actual = {key: sha256(text.encode('utf-8')).hexdigest() for key, text in strings.ZH_TW.items() if '實盤' in text or 'live trading' in text.casefold()}
        self.assertEqual(actual, expected)


LIVE_DISABLED_SHA256 = {
    'ui.init.research_mode_banner': 'a87042a7b657b4edd0f9dfa3aa9198b40096563f85d5c40b97924828c761d853',
    'chatgpt_ui.init.included_usage_hint': '20e812f5571aa820c0fa04ef406995e280649e1f9046e96e7437ca9334292046',
    'header.live_disabled': 'a87042a7b657b4edd0f9dfa3aa9198b40096563f85d5c40b97924828c761d853',
    'assistant.permission_scope': '0bc5c9a41c0bc6d2833ad82726f79c7f0c84129e782daeb185130b471f810e5f',
}


if __name__ == '__main__':
    unittest.main()

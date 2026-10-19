"""File-only contracts for architecture records and domain definitions."""

from datetime import date
from pathlib import Path
import re
import unittest


DOCS = Path(__file__).resolve().parents[1] / 'docs'
TOPICS = (
    ('OOS', '一次性', '不可逆', '預算'),
    ('Paper', 'journal', '券商模擬'),
    ('TMF', '限定'),
    ('AST', '任意程式碼', 'eval', 'new Function'),
    ('Decimal', '內容雜湊', 'SHA-256'),
)
TERMS = (
    'Backtest',
    'Paper',
    'Replay',
    'Research eligibility',
    'Paper eligibility',
    'OOS',
    'Holdout',
    'Consumed guard',
    'Strategy artifact',
    'Strategy revision',
)


class AdrGlossaryTests(unittest.TestCase):
    def test_adr_numbering_metadata_and_nonempty_sections(self):
        paths = sorted((DOCS / 'adr').glob('*.md'))
        self.assertGreaterEqual(len(paths), 5)
        numbers = []
        for path in paths:
            with self.subTest(path=path.name):
                self.assertRegex(path.name, r'^\d{4}-[a-z0-9-]+\.md$')
                numbers.append(int(path.name[:4]))
                text = path.read_text(encoding='utf-8')
                self.assertRegex(text, r'\A# ADR \d{4}: \S[^\n]*\n')
                self.assertTrue(text.startswith(f'# ADR {path.stem[:4]}: '))
                dates = re.findall(r'^日期: (\d{4}-\d{2}-\d{2})$', text, re.MULTILINE)
                self.assertEqual(len(dates), 1)
                self.assertEqual(date.fromisoformat(dates[0]).isoformat(), dates[0])
                self.assertRegex(text, r'(?m)^狀態: Accepted[^\n]*$')
                sections = re.split(r'^## ([^\n]+)\n', text, flags=re.MULTILINE)
                self.assertEqual(sections[1::2], ['背景', '決策', '後果'])
                for body in sections[2::2]:
                    self.assertTrue(any(line.strip() for line in body.splitlines()))
        self.assertEqual(numbers, list(range(1, len(paths) + 1)))

    def test_first_five_decisions_cover_required_topics(self):
        paths = sorted((DOCS / 'adr').glob('*.md'))
        self.assertGreaterEqual(len(paths), len(TOPICS))
        for path, keywords in zip(paths, TOPICS):
            text = path.read_text(encoding='utf-8')
            with self.subTest(path=path.name):
                for keyword in keywords:
                    self.assertIn(keyword, text)

    def test_glossary_entries_are_nonempty_definitions_only(self):
        text = (DOCS / 'GLOSSARY.md').read_text(encoding='utf-8')
        entries = {}
        for line in text.splitlines():
            if not line.strip() or line.startswith('# '):
                continue
            match = re.fullmatch(r'- \*\*([^*]+)\*\*：(.+)', line)
            self.assertIsNotNone(match, line)
            label, definition = match.groups()
            self.assertTrue(definition.strip(), label)
            term = label.split('（', 1)[0]
            self.assertNotIn(term, entries)
            entries[term] = definition
        self.assertTrue(set(TERMS) <= entries.keys())
        self.assertNotRegex(text, r'```|~~~|\.py\b|`[^`\n]*\([^`\n]*\)[^`\n]*`')
        self.assertNotRegex(text, r'(?im)\bTODO\b|\bFIXME\b|^\s*[-*+]\s+\[[ xX]\]')
        self.assertNotRegex(text, r'(?:[A-Za-z]:[\\/]|(?:docs|quantlab|tests|tools)/)')

    def test_safety_boundaries_remain_explicit(self):
        for path in [*sorted((DOCS / 'adr').glob('*.md')), DOCS / 'GLOSSARY.md']:
            with self.subTest(path=path.name):
                self.assertIn('live trading permanently disabled', path.read_text(encoding='utf-8'))
        oos = (DOCS / 'adr/0001-oos-consumption-and-budget.md').read_text(encoding='utf-8')
        for boundary in ('Paper 30 s', 'smoke 40 s', '每 job 15 min', '230/300', '不隱式重試'):
            self.assertIn(boundary, oos)


if __name__ == '__main__':
    unittest.main()

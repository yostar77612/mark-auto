"""No catalog string may be an encoding-loss placeholder (runs of question marks)."""

import re
import unittest

import desktop_strings


class CatalogPlaceholderTests(unittest.TestCase):
    def test_no_value_is_a_question_mark_placeholder(self):
        bad = {}
        for locale, catalog in desktop_strings.LOCALES.items():
            for key, value in catalog.items():
                if isinstance(value, str) and re.search(r'\?{3,}', value):
                    bad[(locale, key)] = value
        self.assertEqual(bad, {})


if __name__ == '__main__':
    unittest.main()

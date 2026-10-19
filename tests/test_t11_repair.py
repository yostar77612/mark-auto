"""Core-free import guards; AST only, no child processes or workspace I/O."""

import unittest

from tests.test_import_graph import import_graph, reaches, source_map


class ErrorImportBoundaryTests(unittest.TestCase):
    def test_errors_and_history_remain_core_free(self):
        graph = import_graph(source_map())
        for start in ('quantlab.errors', 'quantlab.market_history'):
            for forbidden in ('quantlab.core', 'trader', 'shioaji'):
                with self.subTest(module=start, forbidden=forbidden):
                    self.assertFalse(reaches(graph, start, forbidden))

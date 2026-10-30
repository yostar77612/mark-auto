"""Cheap evidence integrity and privacy contracts for TASK A1-D2."""

import ast
from copy import deepcopy
from pathlib import Path, PurePosixPath
import re
import unittest

from quantlab.core import ValidationError, to_dict
from quantlab.research import validate_dsl
from quantlab.strategies import builtin_strategies


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / 'docs/AGENT_HARNESS_THREAT_MODEL.md'
REQUIRED = {
    'no-execution': {
        'docs/adr/0004-restricted-ast-rules.md',
        'quantlab/strategies.py::_validate_node',
        'tests/test_strategies.py::StrategyTests.test_reject_ast_attack_and_negative_lag',
    },
    'ast-validation': {
        'quantlab/research.py::validate_dsl',
        'quantlab/strategies.py::validate_strategy',
        'tests/test_research.py::ResearchTests.test_reject_corpus',
    },
    'credentials': {
        'quantlab/assistant/adapters/chatgpt/auth.py::DPAPIVault',
        'quantlab/agent_tools.py::Registry.call',
        'tests/test_agent_harness_d1.py::AgentHarnessD1Tests.test_every_registered_read_tool_and_all_pages_are_sentinel_safe',
    },
}
PRIVATE = re.compile(
    r'(?im)(?:[a-z]:[\\/]|\\\\[^\s]+|(?<![\w/])/(?:[\w.-]+/)*[\w.-]+|\b(?:users|home)[\\/]'
    r'|\b(?:username|password|api_key|access_token|refresh_token)\s*[:=]\s*\S+'
    r'|\bBearer\s+[A-Za-z0-9._-]+|\bsk-[A-Za-z0-9_-]{8,}|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)'
)


def evidence_sections(text):
    sections = {}
    for heading, body in re.findall(r'^## ([^\n]+)\n(.*?)(?=^## |\Z)', text, re.MULTILINE | re.DOTALL):
        if heading.startswith('Evidence: '):
            name = heading.removeprefix('Evidence: ')
            if name in sections:
                raise AssertionError('Duplicate evidence section: ' + name)
            sections[name] = re.findall(r'`([^`\n]+)`', body)
    return sections


def assert_evidence(case, text):
    sections = evidence_sections(text)
    case.assertTrue(sections, 'Missing evidence sections')
    for name, required in REQUIRED.items():
        case.assertTrue(required <= set(sections.get(name, ())), 'Missing mandatory evidence: ' + name)
    for name, references in sections.items():
        case.assertTrue(references, 'Empty evidence section: ' + name)
        for reference in references:
            path_text, separator, symbol = reference.partition('::')
            relative = PurePosixPath(path_text)
            case.assertFalse(relative.is_absolute() or '..' in relative.parts or '\\' in path_text or ':' in path_text, reference)
            path = ROOT / path_text
            case.assertTrue(path.is_file(), reference)
            if separator:
                case.assertTrue(symbol, reference)
                nodes = ast.parse(path.read_text(encoding='utf-8')).body
                for part in symbol.split('.'):
                    matches = [node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == part]
                    case.assertEqual(len(matches), 1, reference)
                    nodes = matches[0].body


class ThreatModelD2Tests(unittest.TestCase):
    def test_every_evidence_path_and_definition_exists(self):
        assert_evidence(self, DOCUMENT.read_text(encoding='utf-8'))

    def test_removing_each_mandatory_reference_fails(self):
        text = DOCUMENT.read_text(encoding='utf-8')
        for name, required in REQUIRED.items():
            for reference in required:
                with self.subTest(claim=name, reference=reference):
                    damaged = text.replace('`' + reference + '`', reference)
                    with self.assertRaises(AssertionError):
                        assert_evidence(self, damaged)

    def test_missing_file_or_definition_fails_without_touching_disk(self):
        text = DOCUMENT.read_text(encoding='utf-8')
        # Non-mandatory references ensure the actual disk/symbol checks fire.
        for before, after in (
            ('quantlab/reporting.py::read_json', 'quantlab/missing_evidence.py::read_json'),
            ('quantlab/reporting.py::read_json', 'quantlab/reporting.py::missing_definition'),
        ):
            with self.subTest(after=after), self.assertRaises(AssertionError):
                assert_evidence(self, text.replace(before, after))

    def test_document_has_no_local_paths_usernames_or_secret_values(self):
        text = DOCUMENT.read_text(encoding='utf-8')
        self.assertIsNone(PRIVATE.search(text))
        for value in (
            'C:\\Users\\PRIVATE_USER\\file.json',
            '/home/PRIVATE_USER/file.json',
            '\\\\private-server\\PRIVATE_USER',
            'username=PRIVATE_USER',
            'password=PRIVATE_SECRET',
            'Bearer PRIVATE_TOKEN',
            'sk-PRIVATE_SECRET',
            'eyJprivate.payload.signature',
        ):
            with self.subTest(value=value):
                self.assertIsNotNone(PRIVATE.search(text + '\n' + value))

    def test_trust_inventory_and_required_inputs_are_explicit(self):
        text = DOCUMENT.read_text(encoding='utf-8')
        for label in ('Core engine', 'AST validator', 'DPAPI store', 'Local journal', 'Model output', 'Manual import files', 'Remote-compatible API responses'):
            self.assertIn(label, text)
        self.assertIn('Residual risk', text)
        self.assertIn('[agent harness threat model](AGENT_HARNESS_THREAT_MODEL.md)', (ROOT / 'docs/AGENT_HARNESS_CONTRACT.md').read_text(encoding='utf-8'))

    def test_model_strategy_output_rejects_code_and_unknown_ast(self):
        valid = to_dict(builtin_strategies()[0])
        self.assertEqual(validate_dsl(valid), builtin_strategies()[0])
        bad = [dict(valid, code='print(42)'), 'print(42)']
        for operation in ('eval', 'exec', '__import__', 'subprocess', 'new Function'):
            payload = deepcopy(valid)
            payload['rules'] = {'long': {'op': operation}, 'short': {'op': operation}}
            bad.append(payload)
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                validate_dsl(payload)


if __name__ == '__main__':
    unittest.main()

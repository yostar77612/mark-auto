"""Dynamic synthetic sentinels and host-source boundary regressions for E1."""

import ast
from contextlib import closing
from dataclasses import asdict
from io import StringIO
import json
from pathlib import Path
import secrets
import sqlite3
import unittest
from unittest.mock import Mock, patch
from urllib.request import ProxyHandler

from quantlab import agent_tools, agent_read_tools, market_providers, research
from quantlab.assistant_chat import ChatDispatcher
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime import e1_source as source
from quantlab.trading.runtime import e1_protocol as protocol
from quantlab.trading.runtime import e1_qualification as qualification
from tests import test_e1_qualification as fixtures


class E1BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.E1QualificationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_dynamic_capture_and_evidence_sentinels_never_enter_ai_tools_prompts_or_logs(self):
        f = self.fixture
        marker = secrets.token_hex(16)
        price = 1_000_000 + int(marker[:7], 16)
        rows = json.loads(f.raw)
        for index, row in enumerate(rows):
            value = price + index * 10
            row.update(Open=str(value), High=str(value + 4), Low=str(value - 4), Last=str(value + 2))
            row['ignored_private_note'] = marker
        f.fetch.return_value = json.dumps(rows).encode()
        with patch('sys.stdout', new_callable=StringIO) as stdout, patch('sys.stderr', new_callable=StringIO) as stderr:
            ref = f.freeze(campaign_ref=marker)
            f.complete(ref)
            (evidence,) = f.summaries()
        # Protected test fixture really reached local host state/evidence.
        self.assertEqual(evidence.campaign_ref, marker)
        with fixtures.database(f.registry) as db:
            capture = db.execute('SELECT payload FROM e1_captures ORDER BY slot LIMIT 1').fetchone()[0]
        self.assertIn(str(price), capture)
        protected = (marker, str(price), str(price + 2), ref, evidence.candidate_fingerprint)
        context = agent_read_tools.ReadContext(f.workspace)
        dispatcher = ChatDispatcher(context)
        outputs = []
        for name in dispatcher.declarations:
            args = {} if name in ('list_saved_results', 'get_paper_positions', 'get_paper_orders') else {'result_id': ref}
            if name.startswith('compare_'):
                args['other_id'] = ref
            output = dispatcher.render_tool(name, json.dumps(args))
            outputs.append(output)
        contaminated = [
            {'partition': 'training', 'completed': True, 'observations': 2},
            {'partition': 'oos', **asdict(evidence), 'observations': price, 'completed': True},
            {'partition': 'final_holdout', 'marker': marker, 'observations': price, 'completed': True},
        ]
        clean = contaminated[:1]
        for name in agent_tools.PRODUCTION_REGISTRY.declarations:
            args = {'limit': 1}
            actual = agent_tools.PRODUCTION_REGISTRY.call(name, json.dumps(args), capabilities=('research.read',), context=contaminated)
            expected = agent_tools.PRODUCTION_REGISTRY.call(name, json.dumps(args), capabilities=('research.read',), context=clean)
            self.assertEqual(actual, expected)
            outputs.append(json.dumps(actual))
        # The unchanged actual research prompt is assembled only with independent
        # synthetic training data; stored E1 data has no prompt registration route.
        training = research.training_summary(fixtures.synthetic_dataset(20))
        outputs.append(research.PROMPT + json.dumps(training))
        outputs.extend((stdout.getvalue(), stderr.getvalue()))
        for output in outputs:
            self.assertFalse(any(value in output for value in protected), 'protected synthetic value crossed AI/log boundary')
        # Negative control proves this exact dynamic oracle detects contamination.
        self.assertTrue(any(value in json.dumps(asdict(evidence), default=str) for value in protected))

    def test_ai_modules_do_not_import_e1_or_expose_qualification_mutations(self):
        root = Path(__file__).resolve().parents[1]
        paths = list((root / 'quantlab' / 'assistant').rglob('*.py'))
        paths += list((root / 'quantlab').glob('agent_*.py'))
        paths += [root / 'quantlab' / 'assistant_chat.py']
        paths += list((root / 'desktop_app' / 'features' / 'assistant').rglob('*.py'))
        for path in paths:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or '']
                else:
                    continue
                self.assertFalse(any(name.startswith('quantlab.trading') for name in names), path.name)
        for registry in (agent_tools.PRODUCTION_REGISTRY, agent_read_tools.READ_REGISTRY):
            for declaration in registry.declarations.values():
                self.assertEqual(declaration['effect'], 'read')
                self.assertNotIn('e1', declaration['name'])

    def test_exception_payload_never_leaves_host_or_reader(self):
        f = self.fixture
        ref = f.freeze()
        f.capture(ref)
        marker = secrets.token_hex(24)
        with patch.object(qualification, '_run_bounded', side_effect=RuntimeError(marker)):
            f.unavailable(lambda: f.host.evaluate(ref))
        self.assertEqual(f.summaries(), ())
        self.assertNotIn(marker, str(f.state(ref)))


def capture_count(registry):
    """Number of immutable captures currently stored (read-only probe)."""
    with closing(sqlite3.connect(registry)) as db:
        return db.execute('SELECT COUNT(*) FROM e1_captures').fetchone()[0]


class OfficialCaptureBoundaryTests(unittest.TestCase):
    def test_exact_https_origin_and_content_type_are_required_without_redirects(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.geturl.return_value = protocol.SOURCE_URL
        response.headers.get_content_type.return_value = 'application/json'
        response.read.return_value = b'[]'
        opener = Mock()
        opener.open.return_value = response
        with (
            patch.object(source, 'build_opener', return_value=opener) as build,
            patch.object(market_providers, 'build_trust_context', wraps=market_providers.build_trust_context) as trust,
        ):
            self.assertEqual(source.fetch_daily(), b'[]')
            # Same construction as market_providers.fetch_official: no proxies, no redirects,
            # verified trust anchors and a total deadline handler (PR #171 review).
            handlers = build.call_args.args
            self.assertEqual([type(handler) for handler in handlers], [ProxyHandler, source._NoRedirect, source._DeadlineHTTPSHandler])
            self.assertEqual(handlers[0].proxies, {})
            trust.assert_called_once_with()
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, protocol.SOURCE_URL)
            self.assertIsNone(request.data)
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)
            response.geturl.return_value = 'https://invalid.example/report'
            with self.assertRaises(DomainError):
                source.fetch_daily()
        with self.assertRaises(DomainError):
            source._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://invalid.example/report')

    def test_oversized_source_and_duplicate_planned_rows_refuse(self):
        with self.assertRaises(DomainError):
            source.projected_rows(b'x' * (source.MAX_RESPONSE_BYTES + 1), {}, fixtures.AFTER)
        f = fixtures.E1QualificationTests()
        f.setUp()
        try:
            ref = f.freeze()
            rows = json.loads(f.raw)
            f.fetch.return_value = json.dumps(rows + rows[:1]).encode()
            f.now = fixtures.AFTER
            f.unavailable(lambda: f.host.capture(ref, network_authorized=True))
            # PR #171 review: a malformed response writes nothing, so the plan stays admitted.
            self.assertEqual(f.state(ref)[1], 'reserved')
            self.assertEqual(capture_count(f.registry), 0)
        finally:
            f.doCleanups()


if __name__ == '__main__':
    unittest.main()

"""Idea research fetch policy against a local fake HTTPS site (T6, T12-T14, T17)."""

import unittest
from unittest.mock import patch

from quantlab import web_fetch
from quantlab.idea_sources import BLOCKED_DOMAINS, SEARCH_BLOCKED_DOMAINS
from quantlab.web_fetch import check_url, is_public_address, sanitize_text, FetchBlocked
from tests.idea_fixtures import FakeSite, page


class PolicyTests(unittest.TestCase):
    def test_t14_scheme_port_and_policy_codes(self):
        cases = {
            'http://alpha.example.org/x': 'scheme',
            'https://alpha.example.org:8443/x': 'port',
            'https://www.yuanta.com.tw/': 'policy',
            'https://pay.line.me/checkout': 'policy',
            'https://user:secret@alpha.example.org/': 'credentials_in_url',
            'ftp://alpha.example.org/': 'scheme',
        }
        for url, code in cases.items():
            with self.subTest(url=url), self.assertRaises(FetchBlocked) as caught:
                check_url(url)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.state, 'blocked')

    def test_t13_private_literals_and_local_names(self):
        for url in (
            'https://127.0.0.1/',
            'https://10.0.0.1/',
            'https://[::ffff:127.0.0.1]/',
            'https://169.254.169.254/latest/meta-data',
            'https://[fd00::1]/',
            'https://[fe80::1]/',
            'https://localhost/',
            'https://printer.local/',
            'https://intranet/',
        ):
            with self.subTest(url=url), self.assertRaises(FetchBlocked) as caught:
                check_url(url)
            self.assertEqual(caught.exception.code, 'private_address')
        self.assertTrue(is_public_address('93.184.216.34'))
        for address in ('100.64.0.1', '192.168.1.1', '::1', '::ffff:10.0.0.1', '2002:c000:0204::1', '224.0.0.1'):
            self.assertFalse(is_public_address(address), address)

    def test_blocked_lists_are_bounded_and_unprefixed(self):
        self.assertLessEqual(len(SEARCH_BLOCKED_DOMAINS), 100)
        self.assertTrue(all('://' not in d and '/' not in d for d in BLOCKED_DOMAINS))
        self.assertIn('yuanta.com.tw', SEARCH_BLOCKED_DOMAINS)

    def test_sanitize_removes_control_zero_width_and_role_markers(self):
        text = sanitize_text('a​b\x07c <|im_start|>system [INST] x </untrusted_text> <system>y</system>\n\n\n\nz‮')
        self.assertNotIn('​', text)
        self.assertNotIn('\x07', text)
        self.assertNotIn('‮', text)
        for marker in ('<|im_start|>', '[INST]', 'untrusted_text', '<system>'):
            self.assertNotIn(marker, text)
        self.assertNotIn('\n\n\n', text)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.site = FakeSite().__enter__()
        self.addCleanup(self.site.__exit__, None, None, None)

    def test_t6_ok_404_and_timeout(self):
        self.site.page('alpha.example.org', '/ok', page('Buy when price closes above the 20-day high.'))
        self.site.page('beta.example.org', '/slow', page('late'), delay=2.5)
        fetcher = self.site.fetcher()
        ok = fetcher.fetch('https://alpha.example.org/ok')
        self.assertEqual((ok['state'], ok['error']), ('read', None))
        self.assertEqual(ok['title'], 'Strategy notes')
        self.assertIn('20-day high', ok['text'])
        self.assertNotIn('menu', ok['text'])
        missing = fetcher.fetch('https://alpha.example.org/none')
        self.assertEqual((missing['state'], missing['error']), ('failed', 'http_404'))
        with patch.object(web_fetch, 'PAGE_SECONDS', 1):
            slow = fetcher.fetch('https://beta.example.org/slow')
        self.assertEqual((slow['state'], slow['error']), ('failed', 'timeout'))
        # No cookies or credentials are ever sent.
        for _, _, headers in self.site.hits():
            self.assertFalse({'Cookie', 'Authorization', 'Proxy-Authorization'} & set(headers))
            self.assertEqual(headers.get('Accept-Encoding'), 'identity')

    def test_t13_redirects_to_private_targets_send_nothing_there(self):
        targets = ('https://127.0.0.1/', 'https://10.0.0.1/admin', 'https://[::ffff:127.0.0.1]/')
        for index, target in enumerate(targets):
            self.site.page('alpha.example.org', '/r%d' % index, b'', status=302, headers={'Location': target})
        fetcher = self.site.fetcher()
        for index in range(len(targets)):
            with self.subTest(target=targets[index]):
                result = fetcher.fetch('https://alpha.example.org/r%d' % index)
                self.assertEqual((result['state'], result['error']), ('blocked', 'private_address'))
        # Only the public redirecting page was contacted; never a private address.
        self.assertEqual(fetcher.opened, ['93.184.216.34'] * len(targets))
        self.assertEqual(len(self.site.hits()), len(targets))

    def test_t13_rebinding_peer_check_happens_before_any_request(self):
        self.site.page('alpha.example.org', '/ok', page('rules'))
        result = self.site.fetcher(peer='10.0.0.1').fetch('https://alpha.example.org/ok')
        self.assertEqual((result['state'], result['error']), ('blocked', 'private_address'))
        self.assertEqual(self.site.hits(), [])

    def test_dns_to_private_address_is_blocked_before_connecting(self):
        fetcher = self.site.fetcher()
        fetcher.resolver = lambda host: ['93.184.216.34', '10.1.2.3']
        result = fetcher.fetch('https://alpha.example.org/ok')
        self.assertEqual((result['state'], result['error']), ('blocked', 'private_address'))
        self.assertEqual(fetcher.opened, [])

    def test_t14_proxy_detected_refuses_without_connecting(self):
        fetcher = self.site.fetcher(proxies=lambda: {'https': 'http://proxy.corp:8080'})
        result = fetcher.fetch('https://alpha.example.org/ok')
        self.assertEqual((result['state'], result['error']), ('blocked', 'proxy_detected'))
        self.assertEqual(fetcher.opened, [])

    def test_t14_blocked_broker_and_http_never_connect(self):
        fetcher = self.site.fetcher()
        for url, code in (('https://www.yuanta.com.tw/', 'policy'), ('http://alpha.example.org/ok', 'scheme'), ('https://alpha.example.org:8443/', 'port')):
            result = fetcher.fetch(url)
            self.assertEqual((result['state'], result['error']), ('blocked', code))
        self.assertEqual(fetcher.opened, [])

    def test_redirect_limit_and_redirect_to_blocked_domain(self):
        for index in range(5):
            self.site.page('alpha.example.org', '/h%d' % index, b'', status=301, headers={'Location': '/h%d' % (index + 1)})
        self.site.page('alpha.example.org', '/broker', b'', status=302, headers={'Location': 'https://www.yuanta.com.tw/login'})
        fetcher = self.site.fetcher()
        result = fetcher.fetch('https://alpha.example.org/h0')
        self.assertEqual((result['state'], result['error'], result['redirects']), ('failed', 'redirect_limit', 4))
        result = fetcher.fetch('https://alpha.example.org/broker')
        self.assertEqual((result['state'], result['error']), ('blocked', 'policy'))

    def test_t17_oversized_page_is_partial_at_two_mib(self):
        body = page('Buy above the 20-day high. ' + 'x' * 100).encode('utf-8') + b'<p>' + b'y' * (3 * 1024 * 1024) + b'</p>'
        self.site.page('big.example.org', '/big', body)
        result = self.site.fetcher().fetch('https://big.example.org/big')
        self.assertEqual(result['state'], 'partial')
        self.assertTrue(result['truncated'])
        self.assertEqual(result['bytes'], web_fetch.MAX_PAGE_BYTES)
        self.assertLessEqual(len(result['text']), web_fetch.PAGE_TEXT_CHARS)

    def test_login_walls_and_paywalls_are_blocked_not_bypassed(self):
        self.site.page('alpha.example.org', '/401', b'', status=401)
        self.site.page('alpha.example.org', '/form', page('Sign in <form><input type="password" name="p"></form>'))
        self.site.page('alpha.example.org', '/wall', page('Subscribe to continue reading this article.'))
        self.site.page('alpha.example.org', '/pdf', b'%PDF', headers={'Content-Type': 'application/pdf'})
        fetcher = self.site.fetcher()
        expected = {
            '/401': ('blocked', 'login_required'),
            '/form': ('blocked', 'login_required'),
            '/wall': ('blocked', 'paywall'),
            '/pdf': ('failed', 'unsupported_type'),
        }
        for path, outcome in expected.items():
            result = fetcher.fetch('https://alpha.example.org' + path)
            self.assertEqual((result['state'], result['error']), outcome, path)
            self.assertEqual(result['text'], '')

    def test_t12_metadata_address_is_never_contacted(self):
        fetcher = self.site.fetcher()
        for url in ('http://169.254.169.254/latest/meta-data', 'https://169.254.169.254/latest/meta-data'):
            self.assertEqual(fetcher.fetch(url)['state'], 'blocked')
        self.assertEqual(fetcher.opened, [])

    def test_cancellation_stops_before_connecting(self):
        result = self.site.fetcher().fetch('https://alpha.example.org/ok', cancelled=lambda: True)
        self.assertEqual((result['state'], result['error']), ('cancelled', 'cancelled'))
        self.assertEqual(self.site.hits(), [])


if __name__ == '__main__':
    unittest.main()

"""Bounded public HTTPS document fetcher for strategy idea research.

Only https on port 443 to hosts whose every resolved address and the connected
peer are public. No proxies, cookies, credentials, automatic redirects, retries
or subresources. Page text is sanitized data for display and quoting only.
"""

from __future__ import annotations

import codecs
from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
import time
import unicodedata
import urllib.parse
import urllib.request

from .idea_sources import BLOCKED_DOMAINS

MAX_PAGE_BYTES = 2 * 1024 * 1024
PAGE_SECONDS = 15
MAX_REDIRECTS = 3
PAGE_TEXT_CHARS = 15000
MAX_URL_CHARS = 2048
TEXT_TYPES = frozenset({'text/html', 'application/xhtml+xml', 'text/plain'})
REDIRECTS = frozenset({301, 302, 303, 307, 308})
STATES = ('pending', 'loading', 'read', 'partial', 'failed', 'blocked', 'cancelled')
_LOCAL_SUFFIXES = ('.localhost', '.local', '.internal', '.lan', '.home', '.corp', '.intranet', '.arpa')
_BLOCK_TAGS = frozenset(
    {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'section', 'article', 'pre', 'blockquote', 'table', 'ul', 'ol', 'dd', 'dt'}
)
_SKIP_TAGS = frozenset({'script', 'style', 'noscript', 'template', 'svg', 'iframe', 'object', 'embed', 'canvas', 'form', 'nav', 'footer'})
_WALL_MARKERS = (
    'subscribe to continue',
    'subscribe to read',
    'sign in to continue',
    'log in to continue',
    'login to continue',
    'verify you are human',
    'are you a robot',
    'enable javascript and cookies',
    '登入後閱讀',
    '登入以繼續',
    '訂閱後閱讀',
    '付費會員專屬',
)
_MARKERS = r'<\|[^|>]{0,40}\|>|\[/?INST\]|<</?SYS>>|</?\s*untrusted_text\s*>|</?\s*(?:system|assistant|developer)\s*>'


class FetchBlocked(Exception):
    """Policy refusal with a fixed code; never carries remote text."""

    def __init__(self, code, state='blocked'):
        super().__init__(code)
        self.code = code
        self.state = state


def is_public_address(value):
    try:
        address = ipaddress.ip_address(str(value).strip('[]').split('%', 1)[0])
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address.version == 6 and (address.sixtofour is not None or address.teredo is not None):
        return False
    return address.is_global and not address.is_multicast


def _host_blocked(host, blocked):
    return any(host == domain or host.endswith('.' + domain) for domain in blocked)


def canonical_url(raw):
    """Comparable form: lowercase scheme/host, no fragment, default port and utm_* tracking."""
    if type(raw) is not str or not 1 <= len(raw) <= MAX_URL_CHARS or any(ord(c) < 33 for c in raw):
        raise FetchBlocked('invalid_url')
    try:
        parts = urllib.parse.urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise FetchBlocked('invalid_url') from exc
    host = (parts.hostname or '').rstrip('.')
    if not host:
        raise FetchBlocked('invalid_url')
    try:
        host = host.encode('idna').decode('ascii').lower() if not host.isascii() else host.lower()
    except UnicodeError as exc:
        raise FetchBlocked('invalid_url') from exc
    query = urllib.parse.urlencode(
        [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith('utm_')], doseq=True
    )
    scheme = parts.scheme.lower()
    default = {'https': 443, 'http': 80}.get(scheme)
    netloc = ('[' + host + ']' if ':' in host else host) + (f':{port}' if port is not None and port != default else '')
    if parts.username is not None or parts.password is not None:
        netloc = '@' + netloc
    return urllib.parse.urlunsplit((scheme, netloc, parts.path or '/', query, ''))


def check_url(raw, blocked=BLOCKED_DOMAINS):
    """Return (url, host) or raise FetchBlocked: scheme, port, policy, private_address."""
    url = canonical_url(raw)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https':
        raise FetchBlocked('scheme')
    if '@' in parts.netloc:
        raise FetchBlocked('credentials_in_url')
    if parts.port not in (None, 443):
        raise FetchBlocked('port')
    host = parts.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public_address(host):
            raise FetchBlocked('private_address')
    elif host == 'localhost' or host.endswith(_LOCAL_SUFFIXES) or '.' not in host:
        raise FetchBlocked('private_address')
    if _host_blocked(host, blocked):
        raise FetchBlocked('policy')
    return url, host


def system_proxies():
    """Environment and Windows registry proxy settings; any active proxy refuses fetching."""
    return {key: value for key, value in urllib.request.getproxies().items() if key != 'no' and value}


def system_resolver(host):
    return sorted({row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})


def system_opener(address, timeout):
    sock = socket.create_connection((address, 443), timeout=timeout)
    return sock, sock.getpeername()[0]


def default_tls_context():
    # Load the platform trust store only when a page is actually fetched.
    from .tls_trust import build_trust_context

    return build_trust_context()


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.skip, self.in_title, self.password = [], [], 0, False, False

    def handle_starttag(self, tag, attrs):
        if tag == 'input' and any(k == 'type' and (v or '').lower() == 'password' for k, v in attrs):
            self.password = True
        if tag == 'title':
            self.in_title = True
        elif tag in _SKIP_TAGS:
            self.skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        elif tag in _SKIP_TAGS and self.skip:
            self.skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append('\n')

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif not self.skip:
            self.parts.append(data)


def sanitize_text(text):
    """Strip control/format characters and chat-role markers; normalize whitespace."""
    text = unicodedata.normalize('NFC', str(text))
    text = ''.join(c for c in text if c in '\n\t' or unicodedata.category(c) not in ('Cc', 'Cf', 'Cs', 'Co'))
    text = re.sub(_MARKERS, ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'[ \t 　]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def extract_text(body, content_type):
    """Return (title, text, password_form)."""
    if content_type == 'text/plain':
        return '', sanitize_text(body), False
    parser = _Extractor()
    try:
        parser.feed(body)
        parser.close()
    except (AssertionError, ValueError):
        pass
    return sanitize_text(''.join(parser.title))[:300], sanitize_text(''.join(parser.parts)), parser.password


def _charset(content_type_header, body):
    match = re.search(r'charset\s*=\s*["\']?([A-Za-z0-9_.:-]{1,40})', content_type_header or '', re.IGNORECASE)
    if not match:
        match = re.search(rb'<meta[^>]{0,200}charset\s*=\s*["\']?([A-Za-z0-9_.:-]{1,40})', body[:4096], re.IGNORECASE)
        name = match.group(1).decode('ascii', 'ignore') if match else 'utf-8'
    else:
        name = match.group(1)
    try:
        return 'utf-8' if name.lower() in ('utf8', 'utf-8') else codecs.lookup(name).name
    except LookupError:
        return 'utf-8'


class _OwnedConnection(http.client.HTTPConnection):
    """The fetcher owns the checked socket; http.client must not close it before the body is read."""

    def close(self):
        self.sock = None


class Fetcher:
    """One document per call; the injected resolver/opener/TLS context permit offline tests."""

    def __init__(self, *, resolver=None, opener=None, tls_context=None, proxies=None, clock=time.monotonic, blocked=BLOCKED_DOMAINS):
        self.resolver = resolver or system_resolver
        self.opener = opener or system_opener
        self.tls_context = tls_context
        self.proxies = proxies or system_proxies
        self.clock = clock
        self.blocked = blocked

    def fetch(self, raw_url, *, cancelled=None, deadline=None):
        result = {
            'url': raw_url,
            'final_url': None,
            'state': 'failed',
            'error': None,
            'title': '',
            'text': '',
            'bytes': 0,
            'redirects': 0,
            'truncated': False,
            'http_status': None,
        }
        stop = self.clock() + PAGE_SECONDS
        stop = min(stop, deadline) if deadline is not None else stop
        try:
            if self.proxies():
                # DNS and peer checks cannot be trusted through an intermediary.
                raise FetchBlocked('proxy_detected')
            url = raw_url
            while True:
                url, host = check_url(url, self.blocked)
                result['final_url'] = url
                location = self._hop(url, host, result, stop, cancelled)
                if location is None:
                    return result
                result['redirects'] += 1
                if result['redirects'] > MAX_REDIRECTS:
                    raise FetchBlocked('redirect_limit', 'failed')
                url = urllib.parse.urljoin(url, location)
        except FetchBlocked as exc:
            result.update(state=exc.state, error=exc.code, text='', title='')
        except (TimeoutError, socket.timeout):
            result.update(state='failed', error='timeout', text='')
        except ssl.SSLError:
            result.update(state='failed', error='tls_failed', text='')
        except (OSError, http.client.HTTPException, UnicodeError, ValueError):
            result.update(state='failed', error='connect_failed', text='')
        return result

    def _check(self, stop, cancelled):
        if cancelled is not None and cancelled():
            raise FetchBlocked('cancelled', 'cancelled')
        if self.clock() >= stop:
            raise FetchBlocked('timeout', 'failed')

    def _hop(self, url, host, result, stop, cancelled):
        self._check(stop, cancelled)
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                addresses = list(self.resolver(host))
            except OSError as exc:
                raise FetchBlocked('dns_failed', 'failed') from exc
        if not addresses:
            raise FetchBlocked('dns_failed', 'failed')
        if not all(is_public_address(address) for address in addresses):
            raise FetchBlocked('private_address')
        self._check(stop, cancelled)
        sock, peer = self.opener(addresses[0], max(0.001, stop - self.clock()))
        try:
            # Rebinding backstop: verify the actual peer before any byte is sent.
            if not is_public_address(peer):
                raise FetchBlocked('private_address')
            sock.settimeout(max(0.001, stop - self.clock()))
            context = self.tls_context or default_tls_context()
            tls = context.wrap_socket(sock, server_hostname=host)
            sock = tls
            connection = _OwnedConnection(host, 443, timeout=max(0.001, stop - self.clock()))
            connection.sock = tls
            parts = urllib.parse.urlsplit(url)
            target = (parts.path or '/') + ('?' + parts.query if parts.query else '')
            connection.putrequest('GET', target, skip_host=True, skip_accept_encoding=True)
            for name, value in (
                ('Host', host),
                ('User-Agent', 'MarkAuto-IdeaResearch/1 (+public document reader)'),
                ('Accept', 'text/html,application/xhtml+xml,text/plain;q=0.9'),
                ('Accept-Encoding', 'identity'),
                ('Connection', 'close'),
            ):
                connection.putheader(name, value)
            connection.endheaders()
            response = connection.getresponse()
            result['http_status'] = response.status
            if response.status in REDIRECTS:
                location = response.getheader('Location')
                if not location or len(location) > MAX_URL_CHARS:
                    raise FetchBlocked('redirect_invalid', 'failed')
                return location
            if response.status in (401, 403, 407, 451):
                raise FetchBlocked('login_required')
            if response.status == 402:
                raise FetchBlocked('paywall')
            if not 200 <= response.status < 300:
                raise FetchBlocked('http_%d' % response.status, 'failed')
            if response.getheader('Content-Encoding', 'identity').strip().lower() not in ('', 'identity'):
                raise FetchBlocked('compressed', 'failed')
            header = response.getheader('Content-Type', '')
            kind = header.split(';', 1)[0].strip().lower()
            if kind not in TEXT_TYPES:
                raise FetchBlocked('unsupported_type', 'failed')
            chunks, total = [], 0
            while total <= MAX_PAGE_BYTES:
                self._check(stop, cancelled)
                tls.settimeout(max(0.001, stop - self.clock()))
                chunk = response.read(min(65536, MAX_PAGE_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            body = b''.join(chunks)
            if len(body) > MAX_PAGE_BYTES:
                body = body[:MAX_PAGE_BYTES]
                result['truncated'] = True
            result['bytes'] = len(body)
            title, text, password = extract_text(body.decode(_charset(header, body), errors='replace'), kind)
            lowered = text.lower()
            if password:
                raise FetchBlocked('login_required')
            if len(text) < 3000 and any(marker in lowered for marker in _WALL_MARKERS):
                raise FetchBlocked('paywall')
            if not text:
                raise FetchBlocked('empty_text', 'failed')
            result.update(title=title, text=text[:PAGE_TEXT_CHARS], state='partial' if result['truncated'] else 'read')
            result['text_clipped'] = len(text) > PAGE_TEXT_CHARS
            return None
        finally:
            try:
                sock.close()
            except OSError:
                pass

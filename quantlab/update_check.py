"""User-triggered metadata only. No installer/file/browser operations.

The release publishes release-manifest.json (object: {"version": "0.2.3"}) and
release-manifest.json.sha256 (64 hex digits, optionally two spaces + filename).
Transport returns (raw JSON bytes, ASCII sidecar text). SHA-256 provides content
consistency, not publisher authentication; HTTPS supplies transport trust.
"""

from dataclasses import dataclass
import hashlib
import json
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, OpenerDirector, Request, build_opener

from quantlab.payload_cleanup import parse_version
from quantlab.tls_trust import build_trust_context


RELEASE_METADATA_URL = 'https://github.com/yostar77612/mark-auto/releases/latest/download/release-manifest.json'
MAX_BODY = 64 * 1024
TIMEOUT = 8
# Network-only adapter: no built-in/Path.open file operations in this module.
_fetch_response = OpenerDirector.open


@dataclass(frozen=True)
class UpdateResult:
    status: str
    message_code: str
    version: str = ''


def _https(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('invalid_url')
    return url


class _HTTPSRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        _https(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def _default_transport(url):
    opener = build_opener(HTTPSHandler(context=build_trust_context()), _HTTPSRedirect())
    opener.addheaders = [('User-Agent', 'ReleaseMetadataCheck/1.0')]
    values = []
    for endpoint, limit in ((url, MAX_BODY), (url + '.sha256', 256)):
        request = Request(_https(endpoint), headers={'Accept': 'application/octet-stream'})
        with _fetch_response(opener, request, timeout=TIMEOUT) as response:
            _https(response.geturl())
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError('oversized_body')
            values.append(body)
    return values[0], values[1].decode('ascii')


def check_for_update(installed_version, *, transport=None, url=RELEASE_METADATA_URL):
    """Verify a bounded manifest before JSON parsing; any failure is an error."""
    try:
        installed = parse_version(installed_version)
        _https(url)
        body, digest = (transport or _default_transport)(url)
        if not isinstance(body, bytes) or len(body) > MAX_BODY:
            raise ValueError('oversized_body')
        if not isinstance(digest, str) or len(digest) > 256:
            raise ValueError('missing_hash')
        match = re.fullmatch(r'([a-fA-F0-9]{64})(?:  release-manifest\.json)?\s*', digest)
        if match is None:
            raise ValueError('missing_hash')
        if hashlib.sha256(body).hexdigest() != match[1].lower():
            raise ValueError('hash_mismatch')
        manifest = json.loads(body.decode('utf-8'))
        if not isinstance(manifest, dict):
            raise ValueError('bad_manifest')
        version = manifest.get('version')
        latest = parse_version(version)
        status = 'update_available' if latest > installed else 'up_to_date'
        return UpdateResult(status, status, version)
    except (ValueError, TypeError, OSError, RuntimeError):
        # Fixed code only: server bodies, URLs and OS details never become UI text.
        return UpdateResult('error', 'check_failed')

"""User-triggered metadata only. No installer/file/browser operations.

Every preview release re-uploads release-manifest.json (object:
{"version": "0.3.0", "commit": "<40 hex>"}) and release-manifest.json.sha256
(64 hex digits, optionally two spaces + filename) to the fixed prerelease
desktop-preview-latest, because GitHub's releases/latest skips prereleases.
Transport returns (raw JSON bytes, ASCII sidecar text). SHA-256 provides content
consistency, not publisher authentication; HTTPS supplies transport trust.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import json
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, OpenerDirector, Request, build_opener
from zoneinfo import ZoneInfo

from quantlab.payload_cleanup import parse_version
from quantlab.tls_trust import build_trust_context


RELEASE_METADATA_URL = 'https://github.com/yostar77612/mark-auto/releases/download/desktop-preview-latest/release-manifest.json'
RELEASE_DOWNLOAD_PREFIX = 'https://github.com/yostar77612/mark-auto/releases/download/'
# GitHub serves release bytes through these HTTPS redirects. They are never
# accepted as initial manifest/installer sources.
GITHUB_RELEASE_CDN_PREFIXES = (
    'https://release-assets.githubusercontent.com/github-production-release-asset/',
    'https://objects.githubusercontent.com/github-production-release-asset-2e65be/',
)
MAX_BODY = 64 * 1024
TIMEOUT = 8
# Network-only adapter: no built-in/Path.open file operations in this module.
_fetch_response = OpenerDirector.open


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    commit: str
    published_at: datetime
    installer_url: str
    installer_sha256: str
    signature_verified: bool = False


class UpdateError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class UpdateResult:
    status: str
    message_code: str
    version: str = ''
    release: ReleaseInfo | None = None


def _https(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment or parts.port not in (None, 443):
        raise ValueError('invalid_url')
    return url


def release_source_url(url: str) -> str:
    """Validate the external initial URL against the one repository whitelist."""
    try:
        _https(url)
        if any(character.isspace() or ord(character) < 32 or ord(character) == 127 or character in '<>"\'' for character in url):
            raise ValueError('invalid_source')
        parts = urlsplit(url)
        suffix = url.removeprefix(RELEASE_DOWNLOAD_PREFIX)
        if not url.startswith(RELEASE_DOWNLOAD_PREFIX) or parts.query or len(suffix.split('/')) != 2:
            raise ValueError('invalid_source')
        if any(not item or item in ('.', '..') or '%' in item or '\\' in item for item in suffix.split('/')):
            raise ValueError('invalid_source')
    except (ValueError, TypeError, AttributeError) as exc:
        raise UpdateError('update_source_rejected') from exc
    return url


def release_transport_url(url: str) -> str:
    """Permit only the repository URL or an explicit official asset CDN hop."""
    try:
        _https(url)
    except (ValueError, TypeError, AttributeError) as exc:
        raise UpdateError('update_source_rejected') from exc
    if url.startswith(RELEASE_DOWNLOAD_PREFIX):
        return release_source_url(url)
    if not url.startswith(GITHUB_RELEASE_CDN_PREFIXES):
        raise UpdateError('update_source_rejected')
    return url


class _HTTPSRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        release_transport_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def _default_transport(url):
    opener = build_opener(HTTPSHandler(context=build_trust_context()), _HTTPSRedirect())
    opener.addheaders = [('User-Agent', 'ReleaseMetadataCheck/1.0')]
    values = []
    for endpoint, limit in ((url, MAX_BODY), (url + '.sha256', 256)):
        request = Request(endpoint, headers={'Accept': 'application/octet-stream'})
        with _fetch_response(opener, request, timeout=TIMEOUT) as response:
            release_transport_url(response.geturl())
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError('oversized_body')
            values.append(body)
    return values[0], values[1].decode('ascii')


def _release_info(manifest, version: str, commit: str) -> ReleaseInfo | None:
    # Old metadata can still report a version, but cannot offer installation.
    if 'published_at' not in manifest and 'installer' not in manifest:
        return None
    published = manifest.get('published_at')
    installer = manifest.get('installer')
    if not isinstance(published, str) or not isinstance(installer, dict):
        raise ValueError('bad_manifest')
    published_at = datetime.fromisoformat(published.replace('Z', '+00:00'))
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError('bad_manifest')
    published_at = published_at.astimezone(timezone.utc)
    # Reject external timestamps that cannot be displayed in the desktop's
    # timezone, before sending a successful typed result across to Qt.
    published_at.astimezone(ZoneInfo('Asia/Taipei'))
    url = release_source_url(installer.get('url'))
    sha256 = installer.get('sha256')
    if not isinstance(sha256, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', sha256) or not urlsplit(url).path.endswith('.exe'):
        raise ValueError('bad_manifest')
    return ReleaseInfo(version, commit, published_at, url, sha256.lower())


def check_for_update(installed_version, installed_commit='', *, transport=None, url=RELEASE_METADATA_URL):
    """Verify a bounded manifest before JSON parsing; any failure is an error.

    A same-version build from another commit is also an update, because every
    preview of one version shares its number.
    """
    try:
        installed = parse_version(installed_version)
        release_source_url(url)
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
        commit = manifest.get('commit', '')
        if not isinstance(commit, str) or not re.fullmatch(r'(?:[0-9a-f]{40})?', commit):
            raise ValueError('bad_manifest')
        rebuilt = latest == installed and bool(commit and installed_commit) and not commit.startswith(installed_commit)
        status = 'update_available' if latest > installed or rebuilt else 'up_to_date'
        return UpdateResult(status, status, f'{version} ({commit[:7]})' if commit else version, _release_info(manifest, version, commit))
    except (ValueError, TypeError, OSError, RuntimeError, HTTPException, OverflowError):
        # Fixed code only: server bodies, URLs and OS details never become UI text.
        return UpdateResult('error', 'check_failed')

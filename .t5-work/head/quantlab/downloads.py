"""Bounded, explicit refresh of TAIFEX's observed free recent archives.

No network at import. Downloaded bytes are provenance, not a quality certificate.
No trading calendar, completion, redistribution rights, or rankings are inferred.
"""
from datetime import date, datetime, timezone
from html import unescape
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import ssl
import stat
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, Request
from urllib.error import URLError
import zipfile
import zlib

from .core import ValidationError

SOURCE_URL = 'https://www.taifex.com.tw/cht/3/futPrevious30DaysSalesData'
OFFICIAL_HOSTS = frozenset({'www.taifex.com.tw'})
MAX_DOWNLOAD = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_PAGE = 2 * 1024 * 1024
MAX_MEMBERS = 8
MAX_RATIO = 200
TIMEOUT = 20
TOTAL_TIMEOUT = 90


def official_url(url):
    """Reject credentials, ports, fragments, HTTP and lookalike hosts."""
    try:
        p = urlsplit(url)
        ok = (p.scheme == 'https' and p.hostname in OFFICIAL_HOSTS and
              p.port in (None, 443) and not p.username and not p.password and not p.fragment)
    except (ValueError, TypeError):
        ok = False
    if not ok:
        raise ValidationError('only verified official TAIFEX HTTPS URLs allowed')
    return url


class _OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def https_transport(url, timeout):
    """Return a file-like HTTP response; SSL default context verifies TLS."""
    official_url(url)
    opener = build_opener(_OfficialRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    return opener.open(Request(url, headers={'User-Agent': 'QuantLab-research/1.0',
                                            'Accept-Encoding': 'identity'}), timeout=timeout)


def fetch(url, *, limit, transport=https_transport):
    official_url(url)
    started = time.monotonic()
    try:
        with transport(url, TIMEOUT) as response:
            official_url(response.geturl())
            if response.status != 200:
                raise ValidationError('TAIFEX request did not return HTTP 200')
            declared = response.headers.get('Content-Length')
            if declared is not None and (not declared.isdigit() or int(declared) > limit):
                raise ValidationError('invalid or oversized Content-Length')
            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise ValidationError('unexpected HTTP content encoding')
            chunks, size = [], 0
            while True:
                if time.monotonic() - started > TOTAL_TIMEOUT:
                    raise ValidationError('download exceeded total time limit')
                chunk = response.read(min(65536, limit - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ValidationError('download exceeds byte limit')
                chunks.append(chunk)
            if declared is not None and size != int(declared):
                raise ValidationError('truncated HTTP response')
            return b''.join(chunks)
    except (URLError, TimeoutError) as exc:
        raise ValidationError(f'TAIFEX download failed: {exc}') from exc


def discover(page):
    """Extract URLs present verbatim in the page; never manufacture endpoints."""
    if len(page) > MAX_PAGE:
        raise ValidationError('discovery page exceeds limit')
    text = unescape(page.decode('utf-8', errors='replace'))
    found = {}
    for url in re.findall(r'https://[^\s\"\'<>]+', text):
        match = re.fullmatch(r'https://www\.taifex\.com\.tw/file/taifex/Dailydownload/'
                             r'(DailydownloadCSV|Dailydownload)/Daily_(\d{4})_(\d{2})_(\d{2})\.zip', url)
        if not match:
            continue
        kind, year, month, day = match.groups()
        try:
            trade_date = date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            continue
        kind = 'csv' if kind == 'DailydownloadCSV' else 'rpt'
        found[(trade_date, kind)] = {'source_url': official_url(url), 'trade_date': trade_date, 'format': kind}
    if not found:
        raise ValidationError('no supported official archive links found; discovery may have changed')
    return sorted(found.values(), key=lambda item: (item['trade_date'], item['format']), reverse=True)


def inspect_archive(raw, kind):
    """Validate all ZIP entries and CRCs before anything is persisted."""
    if len(raw) > MAX_DOWNLOAD:
        raise ValidationError('archive exceeds download limit')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= MAX_MEMBERS:
                raise ValidationError('invalid ZIP member count')
            total, names, members = 0, set(), []
            for item in infos:
                name = item.filename
                path = PurePosixPath(name)
                mode = item.external_attr >> 16
                if (not name or '\\' in name or ':' in name or '\x00' in item.orig_filename or
                        path.is_absolute() or len(path.parts) != 1 or '..' in path.parts or
                        name.casefold() in names or item.is_dir() or stat.S_ISLNK(mode) or
                        (stat.S_IFMT(mode) not in (0, stat.S_IFREG)) or item.flag_bits & 1 or
                        path.suffix.lower() != '.' + kind):
                    raise ValidationError('unsafe or unexpected archive member')
                names.add(name.casefold())
                total += item.file_size
                if (total > MAX_EXPANDED or item.file_size > MAX_EXPANDED or
                        item.file_size / max(1, item.compress_size) > MAX_RATIO):
                    raise ValidationError('archive expansion limit exceeded')
                with archive.open(item) as stream:
                    content = stream.read(min(MAX_EXPANDED, item.file_size) + 1)
                if len(content) != item.file_size:
                    raise ValidationError('archive member size mismatch')
                members.append({'name': name, 'bytes': len(content),
                                'sha256': hashlib.sha256(content).hexdigest(), 'content': content})
            return members
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise ValidationError(f'invalid ZIP archive: {exc}') from exc


def _atomic_write(path, raw):
    """Replace only local managed files; refuse symlink cache targets."""
    path = Path(path)
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValidationError('symlink cache path refused')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.quantlab-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh(cache, *, days=1, kind='csv', transport=https_transport):
    """Re-fetch latest N published trade dates, retaining content-addressed revisions.

    days means published archives, NOT inferred calendar days. Every selected URL
    is fetched on every call. Partial runs cannot update the discovery manifest.
    All records remain provisional pending explicit session/data validation.
    """
    if type(days) is not int or not 1 <= days <= 30 or kind not in ('csv', 'rpt'):
        raise ValidationError('days must be 1..30 and format must be csv or rpt')
    cache = Path(cache)
    page = fetch(SOURCE_URL, limit=MAX_PAGE, transport=transport)
    discovered = discover(page)
    selected = [item for item in discovered if item['format'] == kind][:days]
    if not selected:
        raise ValidationError('no archives found for requested format')
    results = []
    checked_at = datetime.now(timezone.utc).isoformat()
    for item in selected:
        raw = fetch(item['source_url'], limit=MAX_DOWNLOAD, transport=transport)
        members = inspect_archive(raw, kind)
        sha = hashlib.sha256(raw).hexdigest()
        base = cache / item['trade_date'] / kind / sha
        # Rewrite verified remote bytes even if the cache already exists/corrupted.
        _atomic_write(base / 'archive.zip', raw)
        files = []
        for member in members:
            content = member.pop('content')
            output = base / member['name']
            _atomic_write(output, content)
            files.append({**member, 'path': str(output)})
        record = {**item, 'sha256': sha, 'bytes': len(raw), 'archive_path': str(base / 'archive.zip'),
                  'files': files, 'completion_status': 'provisional_unverified',
                  'quality_status': 'not_imported_or_validated', 'ranking_eligible': False}
        _atomic_write(base / 'manifest.json', json.dumps(record, sort_keys=True, indent=2).encode())
        results.append(record)
    manifest = {'source_page': SOURCE_URL, 'source_page_sha256': hashlib.sha256(page).hexdigest(),
                'checked_at': checked_at, 'requested_recent_archives': days,
                'downloaded_archives': len(results), 'available_archives': len([x for x in discovered if x['format'] == kind]),
                'coverage_status': 'not_certified', 'archives': results,
                'notice': 'Free recent official downloads only; no redistribution license assumed. '
                          'An explicit calendar and import quality validation are required before research.'}
    _atomic_write(cache / 'latest.json', json.dumps(manifest, sort_keys=True, indent=2).encode())
    return manifest

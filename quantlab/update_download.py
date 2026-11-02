"""Bounded, cancellable installer download; this module never executes a file.

The entry URL is a repository release asset. GitHub's HTTPS release-asset CDN
is accepted only as a redirect from that entry URL. A digest authenticates bytes
against the manifest, not the unsigned publisher's identity.
"""

from contextlib import contextmanager
from http.client import HTTPException
import hashlib
from pathlib import Path
import shutil
import tempfile
from threading import Event
from time import monotonic
from urllib.error import URLError
from urllib.request import HTTPSHandler, Request, build_opener

from quantlab.tls_trust import build_trust_context
from quantlab.update_check import ReleaseInfo, UpdateError, _HTTPSRedirect, release_source_url, release_transport_url


MAX_INSTALLER_BYTES = 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT = 300.0
READ_TIMEOUT = 8.0
CHUNK_SIZE = 64 * 1024


@contextmanager
def _download_transport(url: str, timeout: float):
    opener = build_opener(HTTPSHandler(context=build_trust_context()), _HTTPSRedirect())
    request = Request(
        url,
        headers={
            'User-Agent': 'MarkAutoInstallerDownload/1.0',
            'Accept': 'application/octet-stream',
            'Accept-Encoding': 'identity',
        },
    )
    with opener.open(request, timeout=timeout) as response:
        release_transport_url(response.geturl())
        yield response


def _interrupted(cancel: Event, deadline: float) -> None:
    if cancel.is_set():
        raise UpdateError('update_download_cancelled')
    if monotonic() >= deadline:
        raise UpdateError('update_download_timeout')


def discard_download(installer: Path) -> None:
    """Remove the dedicated directory returned by download_installer."""
    shutil.rmtree(installer.parent)


def download_installer(
    release: ReleaseInfo,
    cancel: Event,
    *,
    temp_root: Path | None = None,
    timeout: float = DOWNLOAD_TIMEOUT,
    max_bytes: int = MAX_INSTALLER_BYTES,
    transport=None,
) -> Path:
    """Return only a complete hash-verified file, cleaning every rejected attempt.

    ``transport`` is the network boundary used by offline/local-server tests.
    It returns a context-managed response with headers and ``read1``. The live
    adapter verifies every redirect and uses the platform HTTPS trust store.
    The socket timeout also bounds cancellation while waiting for a read.
    """
    deadline = monotonic() + timeout
    directory = None
    try:
        _interrupted(cancel, deadline)
        release_source_url(release.installer_url)
        directory = Path(tempfile.mkdtemp(prefix='MarkAuto-update-', dir=temp_root))
        partial = directory / 'MarkAuto-setup.exe.part'
        installer = directory / 'MarkAuto-setup.exe'
        digest = hashlib.sha256()
        received = 0
        with (transport or _download_transport)(release.installer_url, min(READ_TIMEOUT, timeout)) as response:
            length = response.headers.get('Content-Length')
            expected_length = int(length) if length is not None else None
            if expected_length is not None and (expected_length < 0 or expected_length > max_bytes):
                raise UpdateError('update_too_large')
            with partial.open('xb') as target:
                while True:
                    _interrupted(cancel, deadline)
                    chunk = response.read1(CHUNK_SIZE)
                    _interrupted(cancel, deadline)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > max_bytes:
                        raise UpdateError('update_too_large')
                    target.write(chunk)
                    digest.update(chunk)
            if expected_length is not None and received != expected_length:
                raise UpdateError('update_download_failed')
        if digest.hexdigest() != release.installer_sha256:
            raise UpdateError('update_hash_mismatch')
        _interrupted(cancel, deadline)
        partial.replace(installer)
        return installer
    except UpdateError:
        if directory is not None:
            shutil.rmtree(directory)
        raise
    except (OSError, HTTPException, ValueError) as exc:
        if directory is not None:
            shutil.rmtree(directory)
        timed_out = isinstance(exc, TimeoutError) or (isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError))
        raise UpdateError('update_download_timeout' if timed_out else 'update_download_failed') from exc

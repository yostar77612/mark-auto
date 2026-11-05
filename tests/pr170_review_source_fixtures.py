"""Pinned bytes of G3 sources before the PR #170 review gate (owner-approved edit); drift is checked separately."""

import gzip
import hashlib
import json
from pathlib import Path

ARCHIVE_SHA256 = '9f58846580227af20fd68f8b518cd7bf14c7dd0dc5f5b9ce7eff8f19f6a2aad9'
CURRENT_SHA256 = {
    'quantlab/research.py': '766e2523946b5a25149cddaf645d7a587243ad64da3e20935a7b0dd0156cb202',
    'quantlab/data.py': '4d6228ab1f65b4efdcc6acaa3ac382bc4a56ac8a54a5b9e67614c425e372c68d',
    'quantlab/saved_candidate_pool.py': 'c243bb30322d95a63ffbbc53d1f1248a90f7509b78d7c532f94b6fca8b93a470',
}


def prior_source_bytes(path):
    raw = gzip.decompress((Path(__file__).parent / 'fixtures/pr170_review_prior_sources.json.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Pinned PR #170 review historical archive changed')
    return json.loads(raw)[path].encode('utf-8')


def reviewed_prior_source(path, raw):
    """Pre-edit bytes of a reviewed current source, in the checkout's newline style."""
    canonical = raw.replace(b'\r\n', b'\n')
    if hashlib.sha256(canonical).hexdigest() != CURRENT_SHA256[path]:
        raise ValueError('Unreviewed PR #170 review source drift')
    prior = prior_source_bytes(path)
    return prior.replace(b'\n', b'\r\n') if b'\r\n' in raw else prior

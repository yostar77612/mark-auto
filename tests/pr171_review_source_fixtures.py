"""Pinned bytes of G3 sources before the PR #171 review fix (owner-approved research.py edit); drift is checked separately."""

import gzip
import hashlib
import json
from pathlib import Path

ARCHIVE_SHA256 = 'be83894136357c6ad1e7e7ed7b028472fcc9e6bb935f775a3a5977323f47bdc4'
CURRENT_SHA256 = {
    'quantlab/research.py': 'e43b7035c443fe8f0be5dfc77500e8e4ead1dbc75a50f0a04176eaf7ba749a66',
    'quantlab/saved_candidate_pool.py': '506140d2d317eb6bfe3504d72bd2f7ea949f8089bd50b573b78654d78fb42e32',
}


def prior_source_bytes(path):
    raw = gzip.decompress((Path(__file__).parent / 'fixtures/pr171_review_prior_sources.json.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Pinned PR #171 review historical archive changed')
    return json.loads(raw)[path].encode('utf-8')


def reviewed_prior_source(path, raw):
    """Pre-edit bytes of a reviewed current source, in the checkout's newline style."""
    canonical = raw.replace(b'\r\n', b'\n')
    if hashlib.sha256(canonical).hexdigest() != CURRENT_SHA256[path]:
        raise ValueError('Unreviewed PR #171 review source drift')
    prior = prior_source_bytes(path)
    return prior.replace(b'\n', b'\r\n') if b'\r\n' in raw else prior

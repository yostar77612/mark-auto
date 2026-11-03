"""Pinned prior G3/profile bytes; current source drift is checked independently."""

import gzip
import hashlib
import json
from pathlib import Path

ARCHIVE_SHA256 = '32b78b3424371a1f4e1684cd8e53b0b48cc719cefe0b551369e67d61cf19bcdb'
CURRENT_SHA256 = {
    'quantlab/backtest.py': 'b30ad2909f70682e7076862253f3f0d1748640d96d16c84252c1fb02e91a44ea',
    'quantlab/core.py': 'b508d19fd2eee49adf49dc612c4c4aad74a0b2f68c27b3c5cdaed7dad3f92c81',
    'quantlab/saved_candidate_pool.py': '5fe7c7f99b55360a9829f13c58770f860a06dd06959ad2be3266ffb04e7d496b',
}


def prior_source_bytes(path):
    raw = gzip.decompress((Path(__file__).parent / 'fixtures/m3_stock_prior_sources.json.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Pinned stock-scope historical archive changed')
    return json.loads(raw)[path].encode('utf-8')


def reviewed_prior_source(path, raw):
    canonical = raw.replace(b'\r\n', b'\n')
    if hashlib.sha256(canonical).hexdigest() != CURRENT_SHA256[path]:
        raise ValueError('Unreviewed stock-scope source drift')
    prior = prior_source_bytes(path)
    return prior.replace(b'\n', b'\r\n') if b'\r\n' in raw else prior

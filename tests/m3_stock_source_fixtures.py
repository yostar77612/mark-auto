"""Pinned prior G3/profile bytes; current source drift is checked independently."""

import gzip
import hashlib
import json
from pathlib import Path

ARCHIVE_SHA256 = '32b78b3424371a1f4e1684cd8e53b0b48cc719cefe0b551369e67d61cf19bcdb'
CURRENT_SHA256 = {
    'quantlab/backtest.py': '97a13a0e4e0fe4d04ca8e4a2c6bfb8b769154df2e1de78f279c9d8554e30e76d',  # OPT-1 P7, owner-approved
    'quantlab/core.py': 'b508d19fd2eee49adf49dc612c4c4aad74a0b2f68c27b3c5cdaed7dad3f92c81',
    'quantlab/saved_candidate_pool.py': '84b5aaf1632b0e208d3013851869a87c865bf971e809ea6472fdccbf2678df4c',  # + STOCK_SIGNAL_PROFILE_V2
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

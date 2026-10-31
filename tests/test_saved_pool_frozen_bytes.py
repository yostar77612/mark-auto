"""Historical profile literals are exact LF-normalized Git 7b59809 bytes."""

import ast
import hashlib
from pathlib import Path
import unittest

PINS = {
    'AUDITED_PRODUCER': '313b88e63c897231e43013c74e707f1351394cecc14e3b62606f45de3ebc07e5',
    'CURRENT_PRODUCER': '6893be85f192e50c0758deb46d5fd1fbc7a170307cdcc993836c80fed3b35f0d',
    'CURRENT_CHATGPT_PROFILE_V2': 'f90e21b9f9df9a879ebdc764172ed3ed134eb68b84b9e55e50641e093e858b72',
    'TRANSPORT_VERIFIER_PRODUCER': 'a7ee62a5597aba6e684280073593971609dc2697350f8d2a5d631be5dbd79a67',
    'TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2': '6d6f01c4d60b17e333b4f38f0e9439c8646acf4c4f9a38e644a911db137e4d33',
    'SIWC_SUBSCRIPTION_SAFETY_PROFILE_V1': 'ebc2312cbf057e89e2c027622a60fcb03238befd82c3990d5c9ff3dc6635eee5',
    'SIWC_ANALYSIS_CAPABLE_PROFILE_V1': '57f77ba682e4a52b555860324dc67fd06d95b4356752b50276ce83c2c4a4c53c',
    'SCALAR_TRANSPORT_PROFILE_V1': 'ae6dac874847f8a0779cf9361396f64f70d28574de8b7c109c659428d27f8395',
    'SCALAR_SIWC_ANALYSIS_PROFILE_V1': 'e7bda44870530c75f4d6fb4b91e82d435e1ee19fe9915a319fcaf5773d12e4ca',
    'CLEANUP_TRANSPORT_PROFILE_V1': '7082d18c388c103373c0867654b41caef144ded48750d8a20bd4ba4274afacb0',
    'CLEANUP_SIWC_ANALYSIS_PROFILE_V1': '08b530161696112e7c15fbb347f79be3ad65fc060936bcfc7b47a21c124c84cd',
    'FAIL_CLOSED_TRANSPORT_PROFILE_V1': 'f6020dc890d47f4a363e58f3b62d902e9f3f988d32400ef6eda9ccbcc0b79bdd',
    'FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1': '881acbb2eebaffbd782463536671ea0dca4394876b05bccb81abe79fd105da10',
    'DEADLINE_TRANSPORT_PROFILE_V1': 'bed091aef5215e627502af58fb8d3033c97e0e052fd3e7d56e80e5428e013078',
    'DEADLINE_SIWC_ANALYSIS_PROFILE_V1': '0804353ca474468138674fccf7437efdcf568dd5ddbf8d312470775de3fcae1c',
    'TOKEN_FORMAT_SIWC_ANALYSIS_PROFILE_V1': 'b204b398ab2f30054bbf42908ba5d909130e8b7dc1d0217279ea33b56ec5f00f',
    'TLS_ANCHOR_SIWC_ANALYSIS_PROFILE_V1': '945e69dfa55f34327c946d1542d7c2a5dd6486c32f63f8a123044afd41c2af7f',
    'MODELS_LIMIT_SIWC_ANALYSIS_PROFILE_V1': '3fe0e31f71f2d81c6014851d1dc06798585f7711fbae39b9320b8d586e208ccf',
    'CAMPAIGN_CATALOG_SIWC_ANALYSIS_PROFILE_V1': '3dd54654b87f6aaaf4cd92cc99cf2396b67a24731ec9a7d8537e3ea88f077f12',
    'UNKNOWN_RECONCILIATION_TRANSPORT_PROFILE_V1': '1deb97790c9646cc5af346953c0e2c0f760e9810d8cbbebbc60dcc24d817ce85',
    'UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1': '263c4822c7955b5210a39a2e4542de90310947aff1e2c72b960949c3b4bc5c96',
    'FINISHED_UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1': '1af24a7ad42f6ceb823f773323e0e2a499baab33251702b3a8a86184d61ffb18',
    'STREAM_CONTENT_TYPE_SIWC_PROFILE_V1': '5e4227dcecd7f00b41a2921facce14595b5014c324d1c9232a4c78b47835f92f',
    'COMPLETED_ITEMS_SIWC_PROFILE_V1': '94ab675456f92df517d4f2cf0a2260f610c2b13fe8dadcbbf62fea27fe06eabf',
    'LONG_PATH_TRANSPORT_PROFILE_V1': 'bda1ab6d6657a02864fd760a6ab5d7ee704716e8a1b096ba62a4f3c98335efde',
    'LONG_PATH_SIWC_PROFILE_V1': '1a3f4e44b8a156181cfb743058324d4d1766da5dddb2a442e554aa9340b3f7f2',
    'ATOMIC_REPLACE_TRANSPORT_PROFILE_V1': 'a01d38d1f41b62622bbb78e3325ce4ad186a305c9493e1dbc6abcbe7a8b6ba12',
    'ATOMIC_REPLACE_SIWC_PROFILE_V1': 'e1b9a39912f965dcc21150ec80364b4e231de1ce509a0367a4498a768cbf6d12',
}


def assert_frozen_bytes(raw):
    lines = raw.replace(b'\r\n', b'\n').splitlines(keepends=True)
    blocks = {
        node.targets[0].id: b"".join(lines[node.lineno - 1 : node.end_lineno])
        for node in ast.parse(raw).body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "freeze"
    }
    for name, digest in PINS.items():
        if name not in blocks or hashlib.sha256(blocks[name]).hexdigest() != digest:
            raise AssertionError("Historical producer literal changed: " + name)


class FrozenProducerBytesTests(unittest.TestCase):
    def test_historical_literals_are_byte_identical(self):
        root = Path(__file__).resolve().parents[1]
        assert_frozen_bytes((root / "quantlab/saved_candidate_pool.py").read_bytes())

    def test_one_changed_byte_fails(self):
        root = Path(__file__).resolve().parents[1]
        raw = (root / "quantlab/saved_candidate_pool.py").read_bytes()
        changed = raw.replace(b"archived_campaign_74fa33dc_v1", b"archived_campaign_74fa33dc_v2", 1)
        with self.assertRaises(AssertionError):
            assert_frozen_bytes(changed)

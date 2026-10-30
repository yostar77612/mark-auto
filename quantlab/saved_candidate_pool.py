"""Read-only admission of one explicitly audited, immutable saved candidate pool.

Local consistency checks are not cryptographic authenticity, model verification,
independent market evidence, or a profitability claim. No provider is called and
no source score is returned to the walk-forward selector.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import stat
import time
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath, PureWindowsPath
from functools import wraps
from urllib.parse import urlsplit
from decimal import localcontext

from .core import (Bar, Dataset, StrategySpec, ValidationError, canonical_json,
                   content_hash, freeze, to_dict, validate_utc)
from .data import parse_timestamp, validate_dataset
from .windows_paths import canonical_path, native_path, sqlite_uri
from .research import (_campaign_config, _dataset_identity, _keys, _unique_keys,
                       candidate_fingerprint, validate_dsl, PARAMETER_CONTRACTS, training_summary)

from quantlab.research_core.domain.saved_pool import SavedCandidatePool, SavedCandidatePoolError, _hash, _fail, _safe_boundary, MAX_AUDIT_BYTES, MAX_SOURCE_BARS
from quantlab.research_core.adapters.saved_pool_source import _validate_original_dataset, _read_campaign, _validate_source_registry
from quantlab.research_core.application.saved_pool_validation import _validate_provider, _matches_chatgpt_implementation, _validate_chatgpt_provider, _saved_pool_snapshot
from quantlab.research_core.application.saved_pool_attempts import _collect_source_attempts, _validate_legacy_receipts, _validate_source_selection

MAX_AUDIT_BYTES = 32 * 1024 * 1024
MAX_SOURCE_BARS = 100000
# Reviewed historical producer only. Never infer compatibility from the running
# checkout, import archived code, or accept a caller-supplied producer allowlist.
AUDITED_PRODUCER = freeze({
    'protocol': 'archived_campaign_74fa33dc_v1',
    'engine_source_hashes': {
        'research.py': '74fa33dcb298fe27c9323ddf2e4b7af3b7773c7ad6c9fc668a0614b44acdfdbe',
        'provider.py': 'ef7a1027b6b375cb1189a2282ce7f8025b60e023900b620f8c198a29d89e297f',
        'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
        'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
        'backtest.py': '2548b1ebc60147d9407065000430b4013ffe93840ecdea83d19085b6e0c86d9c'},
    'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
    'result_source_hashes': {
        'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
        'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
        'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
        'backtest.py': '73c636362542a9779a5d14e7417c6a81b584923255f6b909b101323e962a1f1c'}})


CURRENT_PRODUCER = freeze({'protocol': 'mark_auto_0_2_3_campaign_v1',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': 'ef7a1027b6b375cb1189a2282ce7f8025b60e023900b620f8c198a29d89e297f',
                          'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '724b5811a74d7d25a537ba98616a8d4c5c18ea7e1257fa1ce234efbad29cb040',
                                                     'desktop_chatgpt_provider.py': '96d8c73b52c8cf337e1837ee0cb625cc0f5367e140b3cce595141d86cbdaffdb'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'e33e2c9e07624e9180a2ccebd844f84e68d9d69923b4bcfe8cdfb8a7dab70055',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp313-amd64', 'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '358716a763635543c44ae624222a93157f86f7dde775a21c1fe0aa7fe168bdc4',
                                                     'desktop_chatgpt_provider.py': '2bc5acf8ee545e68580a308101041a2c864406ba8cda06b4009e3bc51343e645'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '9a1bdcef73499c4bc5ff06749301e859690581685f1905f23bfc883a463a2fb6',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '99174ffa3e52ca940909a9e0ec91d98da801bd4fcfb4136064cbd7bfb9a5f1c9',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}]})

# Reviewed dependency-target extension, separately versioned so old snapshots
# retain their original literal profile. Target support is not native acceptance.
CURRENT_CHATGPT_PROFILE_V2 = freeze({'protocol': 'mark_auto_0_2_3_campaign_chatgpt_dependencies_v2',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': 'ef7a1027b6b375cb1189a2282ce7f8025b60e023900b620f8c198a29d89e297f',
                          'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '724b5811a74d7d25a537ba98616a8d4c5c18ea7e1257fa1ce234efbad29cb040',
                                                     'desktop_chatgpt_provider.py': 'd793a8d5c632fd1f4fa98812c81bbe1b5170bcae6e2b54c4291983e429fcaac3'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '358716a763635543c44ae624222a93157f86f7dde775a21c1fe0aa7fe168bdc4',
                                                     'desktop_chatgpt_provider.py': '832431f1ddbad981f38967222c385b4641e89891ce557f19147d7f99db15e7b4'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '99174ffa3e52ca940909a9e0ec91d98da801bd4fcfb4136064cbd7bfb9a5f1c9',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed provider.py extension: an optional connected-peer verifier executes
# after connect and before POST; None preserves the original transport path.
# Campaign/request/receipt/result schemas are unchanged. These literal profiles
# preserve all prior producer objects, including the two ChatGPT descriptor sets.
# The name identifies source support, not evidence that peer verification ran.
# Provider mode validation is unchanged; only the exact engine tuple is added.
TRANSPORT_VERIFIER_PRODUCER = freeze({'protocol': 'mark_auto_0_2_2_campaign_transport_verifier_v1',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '724b5811a74d7d25a537ba98616a8d4c5c18ea7e1257fa1ce234efbad29cb040',
                                                     'desktop_chatgpt_provider.py': '96d8c73b52c8cf337e1837ee0cb625cc0f5367e140b3cce595141d86cbdaffdb'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'e33e2c9e07624e9180a2ccebd844f84e68d9d69923b4bcfe8cdfb8a7dab70055',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp313-amd64', 'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '358716a763635543c44ae624222a93157f86f7dde775a21c1fe0aa7fe168bdc4',
                                                     'desktop_chatgpt_provider.py': '2bc5acf8ee545e68580a308101041a2c864406ba8cda06b4009e3bc51343e645'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '9a1bdcef73499c4bc5ff06749301e859690581685f1905f23bfc883a463a2fb6',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '99174ffa3e52ca940909a9e0ec91d98da801bd4fcfb4136064cbd7bfb9a5f1c9',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}]})

TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2 = freeze({'protocol': 'mark_auto_0_2_2_campaign_transport_verifier_chatgpt_dependencies_v2',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '724b5811a74d7d25a537ba98616a8d4c5c18ea7e1257fa1ce234efbad29cb040',
                                                     'desktop_chatgpt_provider.py': 'd793a8d5c632fd1f4fa98812c81bbe1b5170bcae6e2b54c4291983e429fcaac3'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '358716a763635543c44ae624222a93157f86f7dde775a21c1fe0aa7fe168bdc4',
                                                     'desktop_chatgpt_provider.py': '832431f1ddbad981f38967222c385b4641e89891ce557f19147d7f99db15e7b4'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '99174ffa3e52ca940909a9e0ec91d98da801bd4fcfb4136064cbd7bfb9a5f1c9',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed SIWC subscription-safety source tuple, separately versioned. The
# engine/prompt/result protocols are unchanged; only these exact LF and CRLF
# auth/provider/manifest sets are added. Prior profiles remain literal and frozen.
# Admission does not infer compatibility from files in the running installation,
# perform OAuth/inference, verify included credits, or assert native acceptance.
SIWC_SUBSCRIPTION_SAFETY_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_siwc_subscription_safety_v1',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': 'd542fa7c70816b6504ff6e93efd0ffa91442758e41704b96fe47b42744e674f8',
                                                     'desktop_chatgpt_provider.py': 'f3efb2be1b84c252b57e8cc8f06a20423dfe99c48ac8f32b83d6a89ebe4a0cd6'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '1734c19f7c15cc85592f2658cb14098657633504ed38516d116368bdef036dbb',
                                                     'desktop_chatgpt_provider.py': '83d23ef355a0a2522244faa2fc59ffb78b713e098e37b566c6aaa718df84b951'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '99174ffa3e52ca940909a9e0ec91d98da801bd4fcfb4136064cbd7bfb9a5f1c9',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed provider extension for separately budgeted analysis. This profile
# declares only the exact implementation used by ordinary saved campaigns;
# analysis artifacts have their own schema and are not certified or admitted here.
# The paired auth source also recognizes surviving analysis ledgers as prior-host
# evidence; it cannot silently recreate a lost identity through first sign-in.
# Ordinary generation prompt, candidate/receipt schema and engine tuple remain
# unchanged. Preserve the prior subscription-safety profile verbatim.
SIWC_ANALYSIS_CAPABLE_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_siwc_analysis_capable_v1',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '5825067bdf14afc1ef415e239d60872823b974dd8c141d88e06d9fc211af4c8c',
                                                     'desktop_chatgpt_provider.py': 'd20203c2398e939d0ecd24a697f890ed29276075ded3444e4050e5e55e354baf'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '1ae16a93b52736144947c985d94868989ddda06be4376d569fd17bdae870dcf9',
                                                     'desktop_chatgpt_provider.py': 'fd8ddc12075630532127be72be24d5df1c298b6d0805c8554e76943fd41d43f9'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '99174ffa3e52ca940909a9e0ec91d98da801bd4fcfb4136064cbd7bfb9a5f1c9',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}],
 'provider_modes': ['chatgpt_plan']})

# Exact reviewed scalar-dispatch implementation. Historical profiles above remain
# literal and unchanged; new engine/result tuples cannot borrow old core hashes.
# The non-ChatGPT profile admits fixture/compatible history only. ChatGPT uses
# only the current analysis-capable descriptor pairs, never earlier auth code.
SCALAR_TRANSPORT_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_scalar_transport_v1',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}],
 'provider_modes': ['fixture', 'openai_compatible']})

SCALAR_SIWC_ANALYSIS_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_scalar_siwc_analysis_v1',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '5825067bdf14afc1ef415e239d60872823b974dd8c141d88e06d9fc211af4c8c',
                                                     'desktop_chatgpt_provider.py': 'd20203c2398e939d0ecd24a697f890ed29276075ded3444e4050e5e55e354baf'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '1ae16a93b52736144947c985d94868989ddda06be4376d569fd17bdae870dcf9',
                                                     'desktop_chatgpt_provider.py': 'fd8ddc12075630532127be72be24d5df1c298b6d0805c8554e76943fd41d43f9'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}],
 'provider_modes': ['chatgpt_plan']})

# Exact reviewed research-worker cleanup revision. Preserve every prior literal
# and admit only these complete engine, result, and descriptor tuples.
CLEANUP_TRANSPORT_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_cleanup_transport_v1',
 'engine_source_hashes': {'research.py': 'ef4d1fae956048b85a1adebc49a660424e30fa5e9bb4e14fed402a67cf5b5f95',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}],
 'provider_modes': ['fixture', 'openai_compatible']})

CLEANUP_SIWC_ANALYSIS_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_cleanup_siwc_analysis_v1',
 'engine_source_hashes': {'research.py': 'ef4d1fae956048b85a1adebc49a660424e30fa5e9bb4e14fed402a67cf5b5f95',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '5825067bdf14afc1ef415e239d60872823b974dd8c141d88e06d9fc211af4c8c',
                                                     'desktop_chatgpt_provider.py': 'd20203c2398e939d0ecd24a697f890ed29276075ded3444e4050e5e55e354baf'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '1ae16a93b52736144947c985d94868989ddda06be4376d569fd17bdae870dcf9',
                                                     'desktop_chatgpt_provider.py': 'fd8ddc12075630532127be72be24d5df1c298b6d0805c8554e76943fd41d43f9'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}],
 'provider_modes': ['chatgpt_plan']})

# Exact reviewed fail-closed roll execution and unambiguous SIWC stream identity.
# Historical profiles above retain their original engine/result/descriptor tuples.
FAIL_CLOSED_TRANSPORT_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_fail_closed_transport_v1',
 'engine_source_hashes': {'research.py': 'ef4d1fae956048b85a1adebc49a660424e30fa5e9bb4e14fed402a67cf5b5f95',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['fixture', 'openai_compatible']})

FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_fail_closed_siwc_analysis_v1',
 'engine_source_hashes': {'research.py': 'ef4d1fae956048b85a1adebc49a660424e30fa5e9bb4e14fed402a67cf5b5f95',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '5825067bdf14afc1ef415e239d60872823b974dd8c141d88e06d9fc211af4c8c',
                                                     'desktop_chatgpt_provider.py': '4de519504894985359b24980d0e7e258c945af646002a3a1b9743d51c3b186e8'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '1ae16a93b52736144947c985d94868989ddda06be4376d569fd17bdae870dcf9',
                                                     'desktop_chatgpt_provider.py': '7134b7c175646beae042efad1b2f9dedf377792657c2def2785b64a94573c81a'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed research.py deadline-budget refresh before each pretransaction SQL.
# Only the exact research engine hash and protocol change; result hashes,
# descriptors, provider modes and all historical profile literals stay intact.
# This source compatibility does not establish new provider or durability claims.
DEADLINE_TRANSPORT_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_registry_deadline_transport_v1',
 'engine_source_hashes': {'research.py': 'e04798caaa69264a7f2207cf03490b34b258779ff55b2e4327302e76c1a418e5',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['fixture', 'openai_compatible']})

DEADLINE_SIWC_ANALYSIS_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_registry_deadline_siwc_analysis_v1',
 'engine_source_hashes': {'research.py': 'e04798caaa69264a7f2207cf03490b34b258779ff55b2e4327302e76c1a418e5',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '5825067bdf14afc1ef415e239d60872823b974dd8c141d88e06d9fc211af4c8c',
                                                     'desktop_chatgpt_provider.py': '4de519504894985359b24980d0e7e258c945af646002a3a1b9743d51c3b186e8'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '1ae16a93b52736144947c985d94868989ddda06be4376d569fd17bdae870dcf9',
                                                     'desktop_chatgpt_provider.py': '7134b7c175646beae042efad1b2f9dedf377792657c2def2785b64a94573c81a'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed token-format compatibility and safe authorization-stage reporting.
# Only protocol and exact auth source pins differ from the deadline SIWC
# profile. All historical literals, result and dependency identities stay.
TOKEN_FORMAT_SIWC_ANALYSIS_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_siwc_token_formats_v1',
 'engine_source_hashes': {'research.py': 'e04798caaa69264a7f2207cf03490b34b258779ff55b2e4327302e76c1a418e5',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '3c2eef9d3b46b9ae74369fad67d5c016dbd97ea24d4c6f38a989d8b813f52f44',
                                                     'desktop_chatgpt_provider.py': '4de519504894985359b24980d0e7e258c945af646002a3a1b9743d51c3b186e8'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': 'c62dc5ba0f06f04997d792e81552a41faa9f983f4a1fb6ef3a59e8596dee05b5',
                                                     'desktop_chatgpt_provider.py': '7134b7c175646beae042efad1b2f9dedf377792657c2def2785b64a94573c81a'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed TLS trust-anchor fix: official HTTPS contexts trust only Windows ROOT
# certificates. Only protocol and exact auth/provider source pins differ from the
# token-format profile; all historical literals, result and dependency identities stay.
TLS_ANCHOR_SIWC_ANALYSIS_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_siwc_tls_anchor_v1',
 'engine_source_hashes': {'research.py': 'e04798caaa69264a7f2207cf03490b34b258779ff55b2e4327302e76c1a418e5',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': 'f44d1bf1063ad93d9561b045d8f4811c1b1898b0bba11357a1e75d4031b8ff52'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': 'b5b03794024b8a4463f91351eb6e6dfd44d36ceef06e333186645e615155f042'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed model-catalog response limit: only the provider source pin differs from
# the TLS-anchor profile (auth bytes unchanged); all historical identities stay.
MODELS_LIMIT_SIWC_ANALYSIS_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_siwc_models_limit_v1',
 'engine_source_hashes': {'research.py': 'e04798caaa69264a7f2207cf03490b34b258779ff55b2e4327302e76c1a418e5',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': 'ee2ad6e69f3ad47153bc538cc67923964257b9086b0ef9bfbb25d4d115cd44ce'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': '01d3f33c8cdda7ed3e88fc11837a13d5392fc67bc8b193def8efff62095575c5'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed pre-inference catalog check limit: only the provider source pin differs
# from the models-limit profile (auth bytes unchanged); all historical identities stay.
CAMPAIGN_CATALOG_SIWC_ANALYSIS_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_siwc_campaign_catalog_v1',
 'engine_source_hashes': {'research.py': 'e04798caaa69264a7f2207cf03490b34b258779ff55b2e4327302e76c1a418e5',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': '9ceed8ae5c779ebbab725518a7e8bf785e2122de6c95efa915ba69caa5c4f903'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': '71e9e54a5f2bac93aab0036c60bae4655ca3e0b45cf38e4f7999e5eb3b9e045e'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})


# Reviewed manual-unknown reconciliation source identities. Only the research
# receipt allowlist and exact SIWC provider source pins change. Historical
# profile literals, result hashes, targets and completed-only admission stay.
UNKNOWN_RECONCILIATION_TRANSPORT_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_unknown_reconciliation_transport_v1',
 'engine_source_hashes': {'research.py': '9895a96e026dede9c511facb094e6b6a6f2d95361207829086048c166b5fa88d',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['fixture', 'openai_compatible']})

UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_unknown_reconciliation_siwc_v1',
 'engine_source_hashes': {'research.py': '9895a96e026dede9c511facb094e6b6a6f2d95361207829086048c166b5fa88d',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': 'e2ea5f87cd2f0cea4c85cba884a5572e52ef948be65109283ca5990913d9e4d9'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': 'fd5fea1196edf2883bef06380f9811bf0059d649dc789b83fdfed4224eba1347'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed R2 finished-unknown (K2) reconciliation source identity (owner approved,
# PR #83 D9). Only the exact SIWC provider LF/CRLF source pins change; the research
# engine, historical profile literals and completed-only admission stay.
FINISHED_UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_finished_unknown_reconciliation_siwc_v1',
 'engine_source_hashes': {'research.py': '9895a96e026dede9c511facb094e6b6a6f2d95361207829086048c166b5fa88d',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': '263317fb54bd0213bbe4233505df57fd264ca830ae5b8e9cfc270ccf3163b1fd'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': '104d9a4c5a77abbf83e2e352966294f41a8c7af9b4b3981d6137c1d3c64419f3'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})

# Reviewed headerless-stream provider source identity (owner approved 2026-10-23). Only the
# exact SIWC provider LF/CRLF source pins change; historical literals and completed-only
# admission stay.
STREAM_CONTENT_TYPE_SIWC_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_siwc_stream_content_type_v1',
 'engine_source_hashes': {'research.py': '9895a96e026dede9c511facb094e6b6a6f2d95361207829086048c166b5fa88d',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': '63b0d42b0535e94c78bec4bcab9c1a844d7f4cb28e381da1d3e7e29dd0c0e45f'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': '19b2343e97eb14cbc0bb75977a48b3a7fe23c3e7bf07f97ed69fe9d5b60df4e0'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})


# Owner-authorized completed-item compatibility; historical profiles remain byte-identical.
COMPLETED_ITEMS_SIWC_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_siwc_completed_items_v1',
 'engine_source_hashes': {'research.py': '9895a96e026dede9c511facb094e6b6a6f2d95361207829086048c166b5fa88d',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': '75f41e222ff467f8203066ba4f262cb9f5a75d4f11998ae4e1f6bb9a1cf46e2b'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': 'c8c46ab91a439732106a51a95a98770e4bef2176523eb496ce6892e188397922'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})


# Owner-authorized Windows long-path storage compatibility; all historical literals retained.
LONG_PATH_TRANSPORT_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_windows_long_paths_transport_v1',
 'engine_source_hashes': {'research.py': '27d11f3da0541a9908d09bf8534f2ff465a9229bbc488cd64b4ba7d09c9f6133',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['fixture', 'openai_compatible']})

LONG_PATH_SIWC_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_windows_long_paths_siwc_v1',
 'engine_source_hashes': {'research.py': '27d11f3da0541a9908d09bf8534f2ff465a9229bbc488cd64b4ba7d09c9f6133',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': '0189228f63e44d57e4d3a11832178b49cb0d907d332d557c6c99bb8460d613ca'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': 'f17a71953af43bc6e9a0239bcd74bf1ed3da74bbd826153f9d76f70bc1023899'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})

# Exact Windows atomic-replace source tuple; historical literals above are unchanged.
ATOMIC_REPLACE_TRANSPORT_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_windows_atomic_replace_transport_v1',
 'engine_source_hashes': {'research.py': 'c6d3f1b4b13154c1bf90e6be5a664ac390edc20fb5c544dd909485dfe5fe2ae6',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['fixture', 'openai_compatible']})

ATOMIC_REPLACE_SIWC_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_windows_atomic_replace_siwc_v1',
 'engine_source_hashes': {'research.py': 'c6d3f1b4b13154c1bf90e6be5a664ac390edc20fb5c544dd909485dfe5fe2ae6',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': '0189228f63e44d57e4d3a11832178b49cb0d907d332d557c6c99bb8460d613ca'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': 'f17a71953af43bc6e9a0239bcd74bf1ed3da74bbd826153f9d76f70bc1023899'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})



# Reviewed mechanical-path producer; all earlier literal blocks remain exact.
LAYERED_PATHS_SIWC_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_layered_paths_siwc_v1',
 'engine_source_hashes': {'research.py': 'c6d3f1b4b13154c1bf90e6be5a664ac390edc20fb5c544dd909485dfe5fe2ae6',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf',
                                                     'desktop_chatgpt_provider.py': 'a551187387bd49fb1a9b8b3d1a82ebc95fe69086221f40dfa6423508bf65ba01'},
                                   'dependency_versions': {'PyJWT': '2.15.1', 'cryptography': '50.0.2', 'cffi': '2.1.1', 'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f',
                                                     'desktop_chatgpt_provider.py': '9bddeae4a2529c564cb96df93b4f3914c27b51ff04294667de1bc2d36308523b'},
                                   'dependency_versions': {'PyJWT': '2.15.1', 'cryptography': '50.0.2', 'cffi': '2.1.1', 'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64', 'windows-cp312-amd64', 'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['chatgpt_plan']})

CORE_SPLIT_SIWC_PROFILE_V1 = freeze({'protocol': 'mark_auto_0_2_2_campaign_core_split_siwc_v1',
 'engine_source_hashes': {'research.py': '2bd7b48e2852d901170b7b237a0f02bea25528f345f3034497db9bec9a45b9df',
                          'provider.py': '0b5fdbd36823ac665df6c54b90fad0761eaf885c5b3b45467f7cbe78b32f980d',
                          'core.py': 'd26b350fb4ee83ee45e21c82b5e72e0d72ec38d69b66d19821bf51ac6b9eb17a',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': 'ba5104f27aec16b2aa6098dc23b95f2b68333526a318b5d646a084526002ebac',
                          'research_core/domain/receipts.py': '63d319d4645b682b830afcf9fb20a8abb56bf17dcf6ebbe49cd7ca980ef691da'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
 'chatgpt_plan_implementations': [{'source_sha256': {'assistant_domain_init.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                                                     'assistant_ports_init.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                                                     'research_domain_init.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                                                     'desktop_chatgpt_auth.py': '0527c9e3404826d7b7a530292d1171da7d772ce6a7a3e8eadd14e4b95d0dd8e8',
                                                     'desktop_chatgpt_provider.py': '3062d9eb72b06e0b54b582eae3776325102669c38dcfe4ad82a59b56ad2a7571',
                                                     'chatgpt_vault.py': '04558c77beb56df303de6619ba39cf027d197ceac7b70f448488a6df3cea6980',
                                                     'chatgpt_identity.py': '36d293734f55a0f496afd03a82d2ccd94e1f26d6f74d0c845824bd4a08387e8d',
                                                     'chatgpt_loopback.py': 'bdfeb1de1a2bdc40839bfcfea2f6c5c47fde5d3ec259fe9a2f487c2a456f6097',
                                                     'chatgpt_account_summary.py': '6347980711dad3a48fa33d2639d5e52ec0f3ad0477653f87772a333e2fe6ea35',
                                                     'chatgpt_account_paths.py': '352b3a82c80e1396e9a2770718efdb05d6f822f248af9c74ca9293e4930239e0',
                                                     'chatgpt_response_stream.py': '3b65c25d5900a0d6867f3a944ae3740ff6ee0cb07b962073c96f7331c5752480',
                                                     'chatgpt_transport.py': '86b725f10424624b0e89d8e0d8fa5f3c7677baeab94d2690d368f23fd425ca33',
                                                     'chatgpt_provenance.py': '49fc12b0929fd42042163d9d48f8ed72512312ffaabd0e314391619134573ed5',
                                                     'chatgpt_account_store.py': 'e3289cfc2355e9d72f131792e4f4a905fe915d8246bff3661faab41d4352c19c',
                                                     'chatgpt_resolution_audit.py': '74de18352be758860ba9f64e628d7f3aaf40ef39ce8c20b84ab654adcaa3a0cc',
                                                     'chatgpt_unknown_reconciliation.py': '48861c6647cc1dd828fa8a7138027817409400951ecde9923f02ce8d4c9830fe',
                                                     'chatgpt_finished_reconciliation.py': '289fe411278dcd8c26f67423a948b112572e4af78432d4414e4b18d7c0e2deda',
                                                     'chatgpt_campaign_receipts.py': '6812923883168ca351d43e117477710cd49a29727538ef0186e4fd792d2de979',
                                                     'assistant_auth_protocol.py': 'b8b08927386f32d09628edeb3f1393e4f1152e9b3cc95223057fbfc70c687fd5',
                                                     'assistant_auth_tokens.py': '0f1ad8d0feb216020b48cde8b52783bae5d8d67f5b081e784eb60cac49491786',
                                                     'assistant_plan_protocol.py': '4c6da5083beaf32075b6cc34237c7a96fe0dc784c1b74ef365e9b260fbba9df4',
                                                     'assistant_source_components.py': '8f02a36078c2ba4d0e999ce9f6c58c4564e73586d4a0f8b5f1e7add22fe862d8',
                                                     'assistant_auth_ports.py': '97d9969dda0f1df77efe192dacc6a976d9b37edec32d0fe5223bb98f39d94808',
                                                     'research_receipts.py': '13c7054714518afd8d6eeecfdad967ab6ba8bb68fcd8f98bb236e8d2baed7673'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'assistant_domain_init.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                                                     'assistant_ports_init.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                                                     'research_domain_init.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                                                     'desktop_chatgpt_auth.py': '56ec7460a9a13fff2877265b90845e59564222380082b1b9e4e83f6135dae418',
                                                     'desktop_chatgpt_provider.py': '20332c44aa32f43cf2e9c315dc783e17e853a317cd67480020103a142b7d400f',
                                                     'chatgpt_vault.py': '04558c77beb56df303de6619ba39cf027d197ceac7b70f448488a6df3cea6980',
                                                     'chatgpt_identity.py': '36d293734f55a0f496afd03a82d2ccd94e1f26d6f74d0c845824bd4a08387e8d',
                                                     'chatgpt_loopback.py': 'bdfeb1de1a2bdc40839bfcfea2f6c5c47fde5d3ec259fe9a2f487c2a456f6097',
                                                     'chatgpt_account_summary.py': '6347980711dad3a48fa33d2639d5e52ec0f3ad0477653f87772a333e2fe6ea35',
                                                     'chatgpt_account_paths.py': '352b3a82c80e1396e9a2770718efdb05d6f822f248af9c74ca9293e4930239e0',
                                                     'chatgpt_response_stream.py': '3b65c25d5900a0d6867f3a944ae3740ff6ee0cb07b962073c96f7331c5752480',
                                                     'chatgpt_transport.py': '86b725f10424624b0e89d8e0d8fa5f3c7677baeab94d2690d368f23fd425ca33',
                                                     'chatgpt_provenance.py': '49fc12b0929fd42042163d9d48f8ed72512312ffaabd0e314391619134573ed5',
                                                     'chatgpt_account_store.py': 'e3289cfc2355e9d72f131792e4f4a905fe915d8246bff3661faab41d4352c19c',
                                                     'chatgpt_resolution_audit.py': '74de18352be758860ba9f64e628d7f3aaf40ef39ce8c20b84ab654adcaa3a0cc',
                                                     'chatgpt_unknown_reconciliation.py': '48861c6647cc1dd828fa8a7138027817409400951ecde9923f02ce8d4c9830fe',
                                                     'chatgpt_finished_reconciliation.py': '289fe411278dcd8c26f67423a948b112572e4af78432d4414e4b18d7c0e2deda',
                                                     'chatgpt_campaign_receipts.py': '6812923883168ca351d43e117477710cd49a29727538ef0186e4fd792d2de979',
                                                     'assistant_auth_protocol.py': 'b8b08927386f32d09628edeb3f1393e4f1152e9b3cc95223057fbfc70c687fd5',
                                                     'assistant_auth_tokens.py': '0f1ad8d0feb216020b48cde8b52783bae5d8d67f5b081e784eb60cac49491786',
                                                     'assistant_plan_protocol.py': '4c6da5083beaf32075b6cc34237c7a96fe0dc784c1b74ef365e9b260fbba9df4',
                                                     'assistant_source_components.py': '8f02a36078c2ba4d0e999ce9f6c58c4564e73586d4a0f8b5f1e7add22fe862d8',
                                                     'assistant_auth_ports.py': '97d9969dda0f1df77efe192dacc6a976d9b37edec32d0fe5223bb98f39d94808',
                                                     'research_receipts.py': '13c7054714518afd8d6eeecfdad967ab6ba8bb68fcd8f98bb236e8d2baed7673'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6'},
                                 {'core.py': '61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e'}],
 'provider_modes': ['fixture', 'openai_compatible', 'chatgpt_plan']})

SUPPORTED_PRODUCERS = (AUDITED_PRODUCER, CURRENT_PRODUCER, CURRENT_CHATGPT_PROFILE_V2,
                       TRANSPORT_VERIFIER_PRODUCER, TRANSPORT_VERIFIER_CHATGPT_PROFILE_V2,
                       SIWC_SUBSCRIPTION_SAFETY_PROFILE_V1, SIWC_ANALYSIS_CAPABLE_PROFILE_V1,
                       SCALAR_TRANSPORT_PROFILE_V1, SCALAR_SIWC_ANALYSIS_PROFILE_V1,
                       CLEANUP_TRANSPORT_PROFILE_V1, CLEANUP_SIWC_ANALYSIS_PROFILE_V1,
                       FAIL_CLOSED_TRANSPORT_PROFILE_V1, FAIL_CLOSED_SIWC_ANALYSIS_PROFILE_V1,
                       DEADLINE_TRANSPORT_PROFILE_V1, DEADLINE_SIWC_ANALYSIS_PROFILE_V1,
                       TOKEN_FORMAT_SIWC_ANALYSIS_PROFILE_V1, TLS_ANCHOR_SIWC_ANALYSIS_PROFILE_V1,
                       MODELS_LIMIT_SIWC_ANALYSIS_PROFILE_V1, CAMPAIGN_CATALOG_SIWC_ANALYSIS_PROFILE_V1,
                       UNKNOWN_RECONCILIATION_TRANSPORT_PROFILE_V1, UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1,
                       FINISHED_UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1, STREAM_CONTENT_TYPE_SIWC_PROFILE_V1,
                       COMPLETED_ITEMS_SIWC_PROFILE_V1, LONG_PATH_TRANSPORT_PROFILE_V1, LONG_PATH_SIWC_PROFILE_V1,
                       ATOMIC_REPLACE_TRANSPORT_PROFILE_V1, ATOMIC_REPLACE_SIWC_PROFILE_V1, LAYERED_PATHS_SIWC_PROFILE_V1, CORE_SPLIT_SIWC_PROFILE_V1)








from .errors import fail, saved_candidate_reason





















@_safe_boundary
def admit_saved_campaign_pool(*, source_campaign_dir: Path, source_campaign_ref: str,
                              original_dataset: Dataset, original_dataset_ref: str,
                              first_training_timestamp: datetime,
                              authoritative_registry_path: Path | None = None) -> SavedCandidatePool:
    """Read/revalidate one audited source; return every evaluated attempt in order."""
    if not _hash(source_campaign_ref):
        _fail('Source campaign reference must be a normal 64-hex workspace reference')
    if (type(original_dataset_ref) is not str or not original_dataset_ref
        or len(original_dataset_ref) > 4096 or '\x00' in original_dataset_ref):
        _fail('Explicit local original dataset reference required')
    if Path(source_campaign_dir).name != source_campaign_ref:
        _fail('Source campaign directory does not match workspace reference')
    validate_utc(first_training_timestamp)
    _validate_original_dataset(original_dataset)
    first_event = min(bar.timestamp for bar in original_dataset.bars)
    last_event = max(bar.end for bar in original_dataset.bars)
    if last_event >= first_training_timestamp:
        _fail('Every original source event end must be strictly before new first training timestamp')
    state = _read_campaign(source_campaign_dir)
    try:
        _keys(state, ('campaign_id', 'binding', 'status', 'source_manifest', 'attempts', 'selected',
                      'evaluations', 'holdout_consumed', 'holdout_status', 'elapsed_seconds',
                      'real_model_status', 'provider_receipts', 'resource_enforcement', 'warnings', 'selection_hash'),
              ('holdout_registry', 'holdout_selection_hash'))
        binding = state['binding']
        _keys(binding, ('config', 'data_hash', 'split_hashes', 'provider', 'prompt_template_hash', 'engine_source_hashes'))
        producer = _select_producer(binding)
        current_schema = producer['protocol'] != AUDITED_PRODUCER['protocol']
        if state['status'] != 'completed':
            _fail('Source campaign must be terminal completed')
        if (state['campaign_id'] != content_hash(binding)
            or state['selection_hash'] != content_hash(state['selected'])):
            _fail('Source campaign/selection identity mismatch')
        if (binding['data_hash'] != _dataset_identity(original_dataset)
            or state['source_manifest'] != to_dict(original_dataset.manifest)):
            _fail('Exact original dataset identity/source manifest mismatch')
        if state['real_model_status'] != 'not_verified':
            _fail('Original real_model_status is inconsistent with the audited producer')
        provider = binding['provider']
        _validate_provider(provider, current_schema=current_schema)
        # Keep operation-specific dependencies out of module startup.
        from .configuration import config_from_json
        # Keep operation-specific dependencies out of module startup.
        from .value_bounds import _bounded_value
        _bounded_value(binding['config'])
        config = dict(binding['config'])
        config['backtest_config'] = config_from_json(config['backtest_config'])
        splits = _campaign_config(original_dataset, config)
        if binding['split_hashes'] != {name: _dataset_identity(split) for name, split in splits.items()}:
            _fail('Original dataset split identity mismatch')
        pool, provenance, by_id = _collect_source_attempts(state, config, splits, current_schema,
                                                        provider, binding, producer, _bounded_value)
        if provider['mode'] == 'chatgpt_plan':
            _validate_chatgpt_provider(provider, state, producer)
        else:
            _validate_legacy_receipts(provider, state, current_schema=current_schema)
        _validate_source_selection(state, config, by_id, splits, producer)
        registry_identity = _validate_source_registry(state, splits['holdout'], authoritative_registry_path)
        return _saved_pool_snapshot(state, source_campaign_ref, original_dataset_ref, binding,
                                    original_dataset, first_event, last_event, first_training_timestamp,
                                    registry_identity, producer, provider, provenance, pool)
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, SavedCandidatePoolError):
            raise
        raise SavedCandidatePoolError('Invalid source campaign schema/invariants') from exc
















def _select_producer(binding):
    """Distinct immutable profiles may share one audited engine tuple.

    ChatGPT requires a unique matching descriptor profile. Fixture/compatible
    campaigns retain their original canonical profile and snapshot identity.
    """
    matches = [known for known in SUPPORTED_PRODUCERS
               if binding['engine_source_hashes'] == known['engine_source_hashes']
               and binding['prompt_template_hash'] == known['prompt_template_hash']]
    if not matches:
        _fail('Unsupported or missing audited source producer protocol')
    provider = binding['provider']
    if isinstance(provider, dict) and provider.get('mode') == 'chatgpt_plan':
        matches = [known for known in matches
                   if _matches_chatgpt_implementation(provider.get('descriptor'), known)]
        if len(matches) != 1:
            _fail('Unsupported source provider protocol implementation tuple or ambiguous profile')
    else:
        matches = [known for known in matches if known['protocol'] in
                   (AUDITED_PRODUCER['protocol'], CURRENT_PRODUCER['protocol'],
                    TRANSPORT_VERIFIER_PRODUCER['protocol'], SCALAR_TRANSPORT_PROFILE_V1['protocol'],
                    CLEANUP_TRANSPORT_PROFILE_V1['protocol'], FAIL_CLOSED_TRANSPORT_PROFILE_V1['protocol'],
                    DEADLINE_TRANSPORT_PROFILE_V1['protocol'], UNKNOWN_RECONCILIATION_TRANSPORT_PROFILE_V1['protocol'],
                    LONG_PATH_TRANSPORT_PROFILE_V1['protocol'], ATOMIC_REPLACE_TRANSPORT_PROFILE_V1['protocol'], CORE_SPLIT_SIWC_PROFILE_V1['protocol'])]
        if len(matches) != 1:
            _fail('Unsupported or ambiguous audited source producer protocol')
    return matches[0]











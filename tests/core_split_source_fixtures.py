"""Pinned historical source projections, independent of current implementation pins."""

import gzip
import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / 'fixtures'
CURRENT_SOURCES = {
    "desktop_chatgpt_auth.py": "quantlab/assistant/adapters/chatgpt/auth.py",
    "desktop_chatgpt_provider.py": "quantlab/assistant/adapters/chatgpt/provider.py",
    "chatgpt_vault.py": "quantlab/assistant/adapters/chatgpt/vault.py",
    "chatgpt_identity.py": "quantlab/assistant/adapters/chatgpt/identity.py",
    "chatgpt_loopback.py": "quantlab/assistant/adapters/chatgpt/loopback.py",
    "chatgpt_account_summary.py": "quantlab/assistant/adapters/chatgpt/account_summary.py",
    "chatgpt_account_paths.py": "quantlab/assistant/adapters/chatgpt/account_paths.py",
    "chatgpt_response_stream.py": "quantlab/assistant/adapters/chatgpt/response_stream.py",
    "chatgpt_transport.py": "quantlab/assistant/adapters/chatgpt/transport.py",
    "chatgpt_provenance.py": "quantlab/assistant/adapters/chatgpt/provenance.py",
    "chatgpt_account_store.py": "quantlab/assistant/adapters/chatgpt/account_store.py",
    "chatgpt_resolution_audit.py": "quantlab/assistant/adapters/chatgpt/resolution_audit.py",
    "chatgpt_unknown_reconciliation.py": "quantlab/assistant/adapters/chatgpt/unknown_reconciliation.py",
    "chatgpt_finished_reconciliation.py": "quantlab/assistant/adapters/chatgpt/finished_reconciliation.py",
    "chatgpt_campaign_receipts.py": "quantlab/assistant/adapters/chatgpt/campaign_receipts.py",
    "assistant_auth_protocol.py": "quantlab/assistant/domain/auth_protocol.py",
    "assistant_auth_tokens.py": "quantlab/assistant/domain/auth_tokens.py",
    "assistant_plan_protocol.py": "quantlab/assistant/domain/plan_protocol.py",
    "assistant_source_components.py": "quantlab/assistant/domain/source_components.py",
    "assistant_auth_ports.py": "quantlab/assistant/ports/auth.py",
    "research_receipts.py": "quantlab/research_core/domain/receipts.py",
    "assistant_domain_init.py": "quantlab/assistant/domain/__init__.py",
    "assistant_ports_init.py": "quantlab/assistant/ports/__init__.py",
    "research_domain_init.py": "quantlab/research_core/domain/__init__.py",
}


def layered_source_bytes(path):
    raw = gzip.decompress((FIXTURES / 'core_split_sources.json.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest() != 'dfb8bcece77dad74a785cf62f17e40c992c87c473098391a5c6e5287b6b437d9':
        raise ValueError('Pinned historical source archive changed')
    archive = json.loads(raw)
    if path in archive:
        return archive[path].encode('utf-8')
    if path in {'quantlab/provider.py', 'quantlab/core.py', 'quantlab/strategies.py', 'quantlab/backtest.py'}:
        return (Path(__file__).resolve().parents[1] / path).read_bytes().replace(b'\r\n', b'\n')
    raise KeyError(path)


def before_core_split(path, source):
    raw = (FIXTURES / 'core_split_pins.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != '21a4180c82ef250a713361f108a7927d73cd600fddf157eab24fc578dfd7a6bb':
        raise ValueError('Exact current source/projection pins changed')
    pins = json.loads(raw)
    if hashlib.sha256(source.replace('\r\n', '\n').encode()).hexdigest() != pins['current_text_sha256'][path]:
        raise ValueError('Unreviewed current source drift')
    return layered_source_bytes(path).decode('utf-8')

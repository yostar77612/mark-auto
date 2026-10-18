"""Historical evidence analysis helpers; local-model execution is retired.

The command entry point fails closed without loading, downloading, or starting
a model. Retained replay and provenance helpers allow old evidence to be audited.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import tarfile
import threading
import time
import urllib.request

# Allow direct invocation without installing this repository.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quantlab.__main__ import config_from_json
from quantlab.core import ValidationError, content_hash, to_dict
from quantlab.provider import HTTPTransport
from quantlab.reporting import load_dataset, read_json, write_json
from quantlab.research import (CompatibleProvider, FAMILIES, demo_campaign_config, run_campaign,
                              validate_dsl, _campaign_config, _run_bounded, _evaluate_split)
from quantlab.strategies import builtin_strategies

MODEL_ID = 'Qwen/Qwen2.5-0.5B-Instruct-GGUF'
MODEL_REVISION = '9217f5db79a29953eb74d5343926648285ec7e67'
MODEL_FILENAME = 'qwen2.5-0.5b-instruct-q4_k_m.gguf'
MODEL_SHA256 = '74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db'
SUPPORTED_MODELS = {
    MODEL_SHA256: (MODEL_ID, MODEL_REVISION, MODEL_FILENAME),
    '6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e': (
        'Qwen/Qwen2.5-1.5B-Instruct-GGUF', '91cad51170dc346986eccefdc2dd33a9da36ead9',
        'qwen2.5-1.5b-instruct-q4_k_m.gguf'),
}
RUNTIME_SHA256 = 'f6d25dde8f51133143d1453da4fd5f73b145127177612a283bf7995957af3392'
RUNTIME_URL = 'https://github.com/ggml-org/llama.cpp/releases/download/b11429/llama-b11429-bin-ubuntu-x64.tar.gz'


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifacts(model, server, archive):
    """Compare files against pinned publisher hashes, including runtime libraries."""
    model_hash = sha256_file(model)
    if model_hash not in SUPPORTED_MODELS:
        raise ValidationError('Model differs from pinned official Qwen artifact')
    model_id, revision, filename = SUPPORTED_MODELS[model_hash]
    if sha256_file(archive) != RUNTIME_SHA256:
        raise ValidationError('Runtime archive differs from pinned official release')
    root = Path(server).resolve().parent.parent
    artifacts = {}
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            if not member.isfile():
                continue
            target = (root / member.name).resolve()
            if not target.is_relative_to(root):
                raise ValidationError('Unsafe runtime archive path')
            expected = hashlib.sha256(source.extractfile(member).read()).hexdigest()
            if not target.is_file() or sha256_file(target) != expected:
                raise ValidationError('Extracted runtime differs from official archive')
            artifacts[member.name] = expected
    if not any((root / name).resolve() == Path(server).resolve() for name in artifacts):
        raise ValidationError('Server is not a member of verified runtime archive')
    return {'model_id': model_id, 'model_revision': revision,
            'model_filename': filename, 'model_sha256': model_hash,
            'model_bytes': Path(model).stat().st_size,
            'model_url': f'https://huggingface.co/{model_id}/resolve/{revision}/{filename}',
            'license': 'Apache-2.0',
            'license_url': f'https://huggingface.co/{model_id}/blob/{revision}/LICENSE',
            'runtime_url': RUNTIME_URL, 'runtime_archive_sha256': RUNTIME_SHA256,
            'runtime_files': artifacts}


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@contextmanager
def recording_proxy(upstream_port, evidence_dir):
    """Loopback-only byte-for-byte recorder, with no response generation/fallback."""
    records = []
    class Recorder(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            if self.path != '/v1/chat/completions':
                self.send_error(404)
                return
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536:
                self.send_error(413)
                return
            body = self.rfile.read(size)
            sequence = len(records) + 1
            record = {'sequence': sequence, 'started_at': datetime.now(timezone.utc).isoformat(),
                      'request': json.loads(body), 'request_bytes_sha256': hashlib.sha256(body).hexdigest()}
            records.append(record)
            started = time.monotonic()
            connection = http.client.HTTPConnection('127.0.0.1', upstream_port, timeout=120)
            try:
                connection.request('POST', self.path, body=body,
                                   headers={'Content-Type': 'application/json'})
                response = connection.getresponse()
                raw = response.read(262145)
                if len(raw) > 262144:
                    raise ValidationError('Upstream response exceeds byte budget')
                record.update(http_status=response.status, response=json.loads(raw),
                              response_bytes_sha256=hashlib.sha256(raw).hexdigest())
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except Exception as error:
                record['error'] = type(error).__name__
                try:
                    self.send_error(502)
                except OSError:
                    pass
            finally:
                connection.close()
                record['elapsed_seconds'] = time.monotonic() - started
                write_json(Path(evidence_dir) / f'http-{sequence:02d}.json', record)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Recorder)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1/chat/completions', records
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def summarize_evidence(state, records):
    """Check observed integration evidence, never bless transport labels alone."""
    evaluated = [a for a in state['attempts'] if a['status'] == 'evaluated']
    receipts = state.get('provider_receipts', [])
    record_hashes = [content_hash(r['response']) for r in records if 'response' in r]
    linked = bool(receipts) and all(r['response_hash'] in record_hashes for r in receipts)
    all_splits = all(state['evaluations'].get(split) and
                     all(r['status'] == 'evaluated' for r in state['evaluations'][split])
                     for split in ('oos', 'holdout'))
    # Only the real process/artifact verifier in main can supply model provenance.
    return {'http_receipts_match_recorded_responses': linked,
            'successful_generated_candidates': sum('spec' in a for a in state['attempts']),
            'fully_backtested_candidates': len(evaluated),
            'distinct_evaluated_families': sorted({a['family'] for a in evaluated}),
            'train_validation_oos_holdout_completed': bool(evaluated) and all_splits,
            'multi_strategy_comparison_completed': len(state.get('selected', [])) >= 2 and all_splits,
            'campaign_status': state['status'],
            'campaign_real_model_status': state['real_model_status'],
            'investment_acceptance': False,
            'usage': [r.get('response', {}).get('usage') for r in records],
            'request_runtime_seconds': [r['elapsed_seconds'] for r in records],
            'comparison': [{'family': a['family'], 'strategy_hash': a['strategy_hash'],
                            'train': a['metrics']['train']['metrics'],
                            'validation': a['metrics']['validation']['metrics'],
                            **{split: next((r['metrics'] for r in state['evaluations'][split]
                                if r['strategy_hash'] == a['strategy_hash'] and r['status'] == 'evaluated'), None)
                               for split in ('oos', 'holdout')}} for a in evaluated]}


def improvement_evidence(state, records):
    """Audit the actual second HTTP request, not only internal intended context."""
    attempts = state.get('attempts', [])
    result = {'purpose': 'synthetic_improvement_loop_engineering_only',
              'real_calls': len(records), 'feedback_transport_verified': False,
              'parent_iteration_chain_verified': False, 'loop_protocol_pass': False,
              'distinct_candidate_accepted': False, 'validation_pnl_improved': None,
              'market_performance_acceptance': False}
    if len(attempts) != 2 or len(records) != 2:
        return result
    first, second = attempts
    actual = json.loads(next(message['content'] for message in records[1]['request']['messages']
                             if message['role'] == 'user'))
    expected = {'output': first['output'], 'status': first['status'],
                'metrics': {name: value['metrics'] for name, value in first['metrics'].items()}}
    result['feedback_transport_verified'] = (
        first['status'] == 'evaluated' and set(expected['metrics']) == {'train', 'validation'}
        and actual.get('previous') == expected
        and actual.get('task') == 'improve_previous_candidate'
        and 'improvement_instruction' in actual
        and not {'oos', 'holdout'} & actual.keys())
    result['parent_iteration_chain_verified'] = (
        first['iteration'] == 0 and second['iteration'] == 1
        and second['parent_id'] == first['attempt_id'] and first['family'] == second['family'])
    result['second_outcome'] = ('duplicate_rejected' if second.get('duplicate_of') else second['status'])
    result['distinct_candidate_accepted'] = (
        second['status'] == 'evaluated' and first.get('candidate_fingerprint') is not None
        and second.get('candidate_fingerprint') != first['candidate_fingerprint'])
    if result['distinct_candidate_accepted']:
        result['validation_pnl_improved'] = (
            Decimal(second['metrics']['validation']['metrics']['net_pnl']) >
            Decimal(first['metrics']['validation']['metrics']['net_pnl']))
    result['loop_protocol_pass'] = (
        result['feedback_transport_verified'] and result['parent_iteration_chain_verified']
        and second['status'] in ('evaluated', 'rejected'))
    result['attempts'] = [{key: a.get(key) for key in (
        'iteration', 'attempt_id', 'parent_id', 'status', 'candidate_fingerprint', 'duplicate_of', 'output')}
        for a in attempts]
    return result


class FrozenResponseReplay:
    """Replay exact saved model bytes, explicitly NOT a new model invocation."""
    mode = 'frozen_model_output_replay'
    endpoint = None

    def __init__(self, record, model_id):
        self.response_hash = content_hash(record['response'])
        self.model = model_id + ':frozen-response:' + self.response_hash
        self.payload = json.loads(record['response']['choices'][0]['message']['content'])
        self.spec = validate_dsl(self.payload)

    def generate(self, context):
        if context['family'] != self.spec.family or context['iteration'] != 0:
            raise ValidationError('Frozen replay cannot generate another family or improve')
        return copy.deepcopy(self.payload)

    def improve(self, context):
        raise ValidationError('Frozen replay cannot improve candidates')


def replay_and_compare(dataset, config, record, provenance, output):
    """One frozen AI candidate versus a predeclared unchanged built-in suite.

    All baselines are disclosed; no baseline/model tuning or winner selection uses
    OOS/holdout. The shared campaign registry still gates unseen evaluation.
    """
    replay = FrozenResponseReplay(record, provenance['model_id'])
    config = copy.deepcopy(config)
    config.update(families=[replay.spec.family], max_trials=1, max_improvements=0)
    baselines = builtin_strategies()
    write_json(output / 'replay-predeclared.json', {
        'mode': replay.mode, 'source_response_hash': replay.response_hash,
        'model_candidate': to_dict(replay.spec), 'baselines': [to_dict(spec) for spec in baselines],
        'config': to_dict(config), 'new_model_calls': 0,
        'multi_ai_candidate_acceptance': False,
        'baseline_ranking': 'none; all predeclared baselines reported unchanged'})
    state = run_campaign(dataset, config=config, generator=replay,
                         output_dir=output / 'campaign',
                         holdout_registry_path=output.parent / '.holdout_registry.sqlite3')
    summary = summarize_evidence(state, [])
    if not summary['train_validation_oos_holdout_completed']:
        raise ValidationError('Frozen candidate evaluation did not complete; inspect campaign evidence')
    partitions = _campaign_config(dataset, config)
    deadline = time.monotonic() + 120
    comparison = []
    for spec in baselines:
        row = {'origin': 'builtin_baseline_not_AI', 'strategy': to_dict(spec), 'splits': {}}
        for name, split in partitions.items():
            row['splits'][name] = _run_bounded(_evaluate_split, (split, spec, config['backtest_config']),
                                              deadline=deadline, config=config)['value']
        comparison.append(row)
    result = {'mode': replay.mode, 'new_model_calls': 0,
              'source_response_hash': replay.response_hash,
              'model_evaluation': summary, 'baselines': comparison,
              'multi_strategy_comparison_completed': len(comparison) >= 1,
              'multi_ai_candidate_acceptance': False,
              'investment_acceptance': False,
              'warnings': ['One frozen actual-model candidate versus five built-in baselines; not multiple AI candidates.',
                           'Repeated generation reliability failed in the bounded six-call experiment.',
                           'Dataset coverage and cost/margin assumptions require separate assessment.']}
    write_json(output / 'replay-comparison.json', result)
    return result


def main(argv=None):
    """The retired local-model executable path must never start inference."""
    print('Local-model validation is retired. Use official ChatGPT subscription authorization; no local model or paid API fallback is supported.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

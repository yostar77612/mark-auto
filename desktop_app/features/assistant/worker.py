"""Host-only, bounded process adapter for explicitly consented read-only chat.

No campaign provider, run, quota reservation, candidate saver or transcript store
is exposed. Only opaque DPAPI references enter the child process. This optional
ChatGPT inference route remains unverified; it does not reuse strategy generation.
"""

import json
import multiprocessing as mp
from pathlib import Path
import re
import sys
import time

from quantlab.agent_read_tools import ReadContext
from quantlab.agent_tools import _refusal
from quantlab.desktop_runtime import _WindowsProcessTree
from desktop_app.features.assistant.assistant_models import context_usage


def host_context(root):
    # Historical saved results have no trusted training provenance in the GUI.
    # Do not infer evidence from saved JSON, the current dataset or model claims.
    return ReadContext(Path(root))


def chatgpt_reply(request, bootstrap, *, transport=None, reference_factory=None):
    try:
        return _chatgpt_reply(request, bootstrap, transport=transport, reference_factory=reference_factory)
    except Exception:
        # No provider response, path, exception string or credential crosses IPC.
        return _refusal()


def _chatgpt_reply(request, bootstrap, *, transport=None, reference_factory=None):
    """Exactly one user-consented call; no conversation or arbitrary host data."""
    if (
        type(request) is not dict
        or set(request) not in ({'consent', 'prompt', 'model', 'registration'}, {'consent', 'prompt', 'model', 'registration', 'effort', 'efforts'})
        or request['consent'] is not True
        or type(request['prompt']) is not str
        or not 1 <= len(request['prompt'].encode('utf-8')) <= 4096
        or type(request['model']) is not str
        or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request['model']) is None
        or type(request['registration']) is not str
        or not request['registration']
    ):
        return _refusal()
    if 'effort' in request and (
        type(request['efforts']) is not list
        or not 1 <= len(request['efforts']) <= 16
        or any(type(v) is not str or re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', v) is None for v in request['efforts'])
        or type(request['effort']) is not str
        or request['effort'] not in request['efforts']
    ):
        return _refusal()
    # Credentials are resolved only by the pinned DPAPI-backed transport in child.
    from quantlab.assistant.adapters.chatgpt.auth import OAuthCredentialReference

    # Reuse the existing verified-TLS, no-redirect, bounded transport and parser.
    from quantlab.assistant.adapters.chatgpt.provider import PlanHTTPTransport, SSEParser, read_account_status

    reference = (reference_factory or OAuthCredentialReference)(str(bootstrap), request['registration'])
    if transport is None:
        if read_account_status(reference, Path(bootstrap) / 'control-v1') != {'state': 'ready', 'pending': False}:
            return _refusal()
        transport = PlanHTTPTransport()
    payload = {
        'model': request['model'],
        'instructions': 'You are an unverified read-only research assistant. Interpret only the supplied text. Never operate, execute code, or request protected data.',
        'input': [{'role': 'user', 'content': request['prompt']}],
        'store': False,
        'stream': True,
    }
    limits = {'deadline': time.monotonic() + 30, 'stall_seconds': 10, 'max_request_bytes': 8192, 'max_response_bytes': 32768}
    if 'effort' in request:
        payload['reasoning'] = {'effort': request['effort']}
    parser = SSEParser(max_bytes=32768)
    completed = None
    stream = transport.stream(reference, payload, limits)
    try:
        for chunk in stream:
            for event in parser.feed(chunk):
                kind = event.get('type')
                if kind in ('response.failed', 'response.incomplete', 'error'):
                    return _refusal()
                if kind == 'response.completed':
                    if completed is not None:
                        return _refusal()
                    completed = event.get('response')
        parser.finish()
        if type(completed) is not dict or completed.get('status') != 'completed' or completed.get('error') or completed.get('incomplete_details'):
            return _refusal()
        output = completed.get('output')
        if type(output) is not list:
            return _refusal()
        texts = []
        thinking = []
        for row in output:
            if row.get('type') == 'reasoning':
                # Display only explicitly returned model summaries, never opaque reasoning data.
                for part in row.get('summary', []):
                    if part.get('type') != 'summary_text' or type(part.get('text')) is not str:
                        return _refusal()
                    thinking.append(part['text'])
                continue
            if row.get('type') != 'message' or row.get('role') != 'assistant' or row.get('status') not in (None, 'completed'):
                return _refusal()
            for part in row.get('content', []):
                if part.get('type') != 'output_text' or type(part.get('text')) is not str:
                    return _refusal()
                texts.append(part['text'])
        if len(texts) != 1 or not texts[0] or len(texts[0].encode('utf-8')) > 8192:
            return _refusal()
        result = {'ok': True, 'text': texts[0]}
        # Never infer context occupancy from response token totals or model names.
        observed = completed.get('context_usage')
        if context_usage(observed) is not None:
            result['context_usage'] = {'used': observed['used'], 'limit': observed['limit']}
        if thinking:
            summary = '\n'.join(thinking)
            if len(summary.encode('utf-8')) > 8192:
                return _refusal()
            result['thinking'] = summary
        return result
    finally:
        stream.close()


def _worker(sender, gate, request, bootstrap):
    try:
        if not gate.wait(15):
            return
        try:
            result = chatgpt_reply(request, bootstrap)
        except Exception:
            result = _refusal()
        sender.send_bytes(json.dumps(result).encode('utf-8'))
    finally:
        sender.close()


class ReplyProcess:
    """Spawn/terminate/join ownership, like desktop_runtime; no GUI worker thread."""

    def __init__(self, bootstrap, *, clock=time.monotonic):
        self.bootstrap = bootstrap
        self.clock = clock
        self.process = self.receiver = self.tree = None
        self.gate = None
        self.deadline = 0

    @property
    def active(self):
        return self.process is not None

    def start(self, request):
        if self.active:
            raise ValueError
        context = mp.get_context('spawn')
        self.receiver, sender = context.Pipe(duplex=False)
        self.gate = context.Event()
        self.process = context.Process(target=_worker, args=(sender, self.gate, request, self.bootstrap))
        self.deadline = self.clock() + 30
        try:
            self.process.start()
            if sys.platform == 'win32':
                self.tree = _WindowsProcessTree(self.process.pid)
            self.gate.set()
        except Exception:
            self.cancel()
            raise
        finally:
            sender.close()

    def poll(self):
        if not self.active:
            return None
        result = None
        try:
            if self.receiver.poll():
                result = json.loads(self.receiver.recv_bytes(32768))
            elif self.clock() < self.deadline and self.process.is_alive():
                return None
        except Exception:
            result = _refusal()
        self.cancel()
        return result or _refusal()

    def cancel(self):
        if self.process is not None:
            if self.tree is not None:
                self.tree.stop_and_join(deadline=time.monotonic() + 2)
                self.tree.close()
            elif self.process.pid is not None and self.process.is_alive():
                self.process.terminate()
            if self.process.pid is not None:
                self.process.join(timeout=0.2)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(timeout=0.2)
                if self.process.is_alive():
                    raise RuntimeError
                self.process.close()
        if self.receiver is not None:
            self.receiver.close()
        self.process = self.receiver = self.tree = None
        self.gate = None

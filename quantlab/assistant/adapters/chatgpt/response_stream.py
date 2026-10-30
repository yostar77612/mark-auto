"""Response stream responsibility; original guards and ordering preserved."""

from __future__ import annotations

from quantlab.assistant.domain.plan_protocol import _fail
from quantlab.assistant.domain.plan_protocol import _json
import codecs
import copy


class SSEParser:
    """Incremental UTF-8/SSE framing; no partial text is treated as completion."""

    def __init__(self, max_bytes=262144, max_event_bytes=65536, max_events=2048):
        self.max_bytes, self.max_event_bytes, self.max_events = max_bytes, max_event_bytes, max_events
        self.total = self.events = self.event_bytes = 0
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.pending = ''
        self.data = []
        self.event_type = None
        self.after_cr = False

    def _line(self, line):
        if not line:
            if not self.data:
                self.event_bytes = 0
                self.event_type = None
                return None
            self.events += 1
            if self.events > self.max_events:
                _fail('event_count')
            text = '\n'.join(self.data)
            self.data = []
            self.event_bytes = 0
            if text == '[DONE]':
                _fail('done_without_completion')
            value = _json(text)
            if self.event_type and value.get('type') != self.event_type:
                _fail('ambiguous_event_type')
            self.event_type = None
            return value
        if line.startswith(':'):
            return None
        name, sep, value = line.partition(':')
        if value.startswith(' '):
            value = value[1:]
        if name == 'data':
            self.data.append(value)
        elif name == 'event':
            if self.event_type is not None:
                _fail('duplicate_event_type')
            self.event_type = value
        return None

    def feed(self, raw):
        if not isinstance(raw, bytes):
            _fail('invalid_stream_chunk')
        self.total += len(raw)
        if self.total > self.max_bytes:
            _fail('stream_byte_limit')
        try:
            text = self.decoder.decode(raw)
        except UnicodeError:
            _fail('invalid_utf8')
        events = []
        for char in text:
            if self.after_cr:
                self.after_cr = False
                if char == '\n':
                    continue
            self.event_bytes += len(char.encode('utf-8'))
            if self.event_bytes > self.max_event_bytes:
                _fail('event_byte_limit')
            if char in '\r\n':
                value = self._line(self.pending)
                self.pending = ''
                self.after_cr = char == '\r'
                if value is not None:
                    events.append(value)
            else:
                self.pending += char
        return events

    def finish(self):
        try:
            self.decoder.decode(b'', final=True)
        except UnicodeError:
            _fail('invalid_utf8')
        if self.pending or self.data:
            _fail('truncated_event')


class _CompletedItems:
    """Pinned recovery from completed items; deltas never supply candidate text."""

    def __init__(self):
        self.items = {}
        self.invalid = False

    def observe(self, event):
        if event.get('type') != 'response.output_item.done':
            return
        index, item = event.get('output_index'), event.get('item')
        if type(index) is not int or not 0 <= index < 64 or not isinstance(item, dict) or index in self.items:
            self.invalid = True
        else:
            self.items[index] = copy.deepcopy(item)

    def complete(self, response, response_id):
        if not isinstance(response, dict) or response.get('output') not in (None, []):
            return response
        if response.get('status') != 'completed' or response.get('error') or response.get('incomplete_details'):
            return response
        if not self.items or self.invalid:
            return response
        if response_id is None or response.get('id') != response_id:
            _fail('invalid_response_id')
        if sorted(self.items) != list(range(len(self.items))):
            _fail('ambiguous_output')
        identities = set()
        for item in self.items.values():
            identity = item.get('id')
            if not isinstance(identity, str) or not 1 <= len(identity) <= 256 or identity in identities:
                _fail('ambiguous_output')
            identities.add(identity)
            if item.get('type') != 'reasoning' and item.get('status') != 'completed':
                _fail('incomplete_message')
        return {**response, 'output': [self.items[index] for index in sorted(self.items)]}


def _completed_payload(response):
    if not isinstance(response, dict) or response.get('status') != 'completed':
        _fail('invalid_terminal_status')
    if response.get('error') or response.get('incomplete_details'):
        _fail('ambiguous_terminal')
    output = response.get('output')
    if not isinstance(output, list) or not output:
        _fail('missing_output')
    texts = []
    for item in output:
        if not isinstance(item, dict):
            _fail('invalid_output')
        # Reasoning metadata is not candidate text and can accompany a message.
        if item.get('type') == 'reasoning':
            continue
        if item.get('type') != 'message' or item.get('role') != 'assistant':
            _fail('tools_or_unknown_output')
        if item.get('status') not in (None, 'completed'):
            _fail('incomplete_message')
        parts = item.get('content')
        if not isinstance(parts, list) or not parts:
            _fail('missing_output')
        for part in parts:
            if not isinstance(part, dict) or part.get('type') != 'output_text' or not isinstance(part.get('text'), str):
                _fail('refusal_or_unknown_content')
            texts.append(part['text'])
    if len(texts) != 1:
        _fail('ambiguous_candidate')
    if len(texts[0].encode('utf-8')) > 16384:
        _fail('candidate_byte_limit')
    candidate = _json(texts[0])
    usage = response.get('usage')
    observed = 'unknown'
    if isinstance(usage, dict) and all(type(usage.get(k)) is int and 0 <= usage[k] <= 2**53 for k in ('input_tokens', 'output_tokens', 'total_tokens')):
        if usage['input_tokens'] + usage['output_tokens'] == usage['total_tokens']:
            observed = {k: usage[k] for k in ('input_tokens', 'output_tokens', 'total_tokens')}
    return candidate, observed

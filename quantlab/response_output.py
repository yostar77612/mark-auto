"""Recover terminal-omitted output only from completed, identity-bound items."""

import copy

from .idea_search import RemoteFailure


class CompletedOutput:
    def __init__(self):
        self.response_id = None
        self.items = {}
        self.invalid_items = False

    def observe(self, event):
        response = event.get('response')
        identities = []
        if 'response_id' in event:
            identities.append(event['response_id'])
        if isinstance(response, dict) and 'id' in response:
            identities.append(response['id'])
        for identity in identities:
            if not isinstance(identity, str) or not 1 <= len(identity) <= 256:
                raise RemoteFailure('invalid_response_id')
            if self.response_id is not None and identity != self.response_id:
                raise RemoteFailure('response_id_mismatch')
            self.response_id = identity
        if event.get('type') == 'response.output_item.done':
            index, item = event.get('output_index'), event.get('item')
            if type(index) is not int or not 0 <= index < 64 or not isinstance(item, dict) or index in self.items:
                self.invalid_items = True
            else:
                self.items[index] = copy.deepcopy(item)

    def complete(self, response):
        # A supplied nonempty output remains authoritative; never overwrite it.
        if not isinstance(response, dict) or response.get('output') not in (None, []):
            return response
        if response.get('status') != 'completed' or response.get('error') or response.get('incomplete_details'):
            return response
        if not self.items or self.invalid_items:
            return response
        if self.response_id is None or response.get('id') != self.response_id:
            raise RemoteFailure('invalid_response_id')
        if sorted(self.items) != list(range(len(self.items))):
            raise RemoteFailure('ambiguous_output')
        identities = set()
        for item in self.items.values():
            identity = item.get('id')
            if not isinstance(identity, str) or not 1 <= len(identity) <= 256 or identity in identities:
                raise RemoteFailure('ambiguous_output')
            identities.add(identity)
            if item.get('type') != 'reasoning' and item.get('status') != 'completed':
                raise RemoteFailure('incomplete_message')
        return {**response, 'output': [self.items[index] for index in sorted(self.items)]}

"""Every pinned historical WFO snapshot retains canonical bytes and state hash."""

import json
import unittest
from quantlab.core import canonical_json, content_hash
from tools.diagnose_wfo_storage import load_stream


class ScalarSnapshotFixtureTests(unittest.TestCase):
    def test_all_637_pinned_snapshots_keep_bytes_and_state_hash(self):
        counts = []
        for name, count in [('smoke', 63), ('large', 574)]:
            payloads, manifest = load_stream(name)
            self.assertEqual(len(payloads), count)
            self.assertEqual(manifest['count'], count)
            for index, encoded in enumerate(payloads):
                with self.subTest(fixture=name, index=index):
                    state = json.loads(encoded)
                    self.assertEqual(canonical_json(state), encoded)
                    self.assertEqual(content_hash({k: v for k, v in state.items() if k != 'state_hash'}), state['state_hash'])
            counts.append(len(payloads))
        self.assertEqual(counts, [63, 574])

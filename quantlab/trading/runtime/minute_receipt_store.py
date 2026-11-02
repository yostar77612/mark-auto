"""Compose typed receipt encoding with the bounded text-only SQLite adapter."""

from quantlab.trading.adapters.storage.minute_receipts import EncodedMinuteReceiptStore
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.minute_receipt import MinuteResearchReceipt
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.validation import DomainError


class MinuteReceiptStore:
    def __init__(self, path, now):
        initialize()
        self.store = EncodedMinuteReceiptStore(path)
        try:
            self.receipts = tuple(self._decode(payload) for payload in self.store.payloads)
        except BaseException:
            self.store.close()
            raise

    @staticmethod
    def _decode(payload):
        receipt = loads(payload)
        if not isinstance(receipt, MinuteResearchReceipt):
            raise DomainError('journal_failed', 'minute receipt schema mismatch')
        return receipt

    def read(self, sequence):
        return self._decode(self.store.read(sequence))

    def append(self, receipt, now, *, before_commit=lambda: None):
        if not isinstance(receipt, MinuteResearchReceipt):
            raise DomainError('validation_failed', 'typed minute receipt required')
        self.store.append(dumps(receipt), before_commit=before_commit)
        self.receipts = (*self.receipts[-31:], receipt)
        return receipt.result.fingerprint

    def close(self):
        self.store.close()

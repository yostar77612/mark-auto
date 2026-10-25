"""Additive v2 producer identity, independent of all historical v1 profiles."""

from dataclasses import dataclass
from hashlib import sha256
import json

from quantlab.trading.domain.validation import DomainError


@dataclass(frozen=True)
class ProducerProfile:
    profile_id: str
    protocol: int
    source_manifest: tuple[tuple[str, str], ...]
    source_digest: str

    def __post_init__(self) -> None:
        if self.protocol != 2 or type(self.protocol) is not int or self.profile_id != 'MARKAUTO-TRADING-V2-PROFILE-1':
            raise DomainError('validation_failed', 'producer profile identity')
        if type(self.source_manifest) is not tuple or not self.source_manifest or len(self.source_manifest) > 500:
            raise DomainError('validation_failed', 'producer source manifest')
        names = []
        for name, digest in self.source_manifest:
            if (
                not name.startswith('quantlab/trading/')
                or '..' in name
                or not name.endswith('.py')
                or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)
            ):
                raise DomainError('validation_failed', 'producer source entry')
            names.append(name)
        if names != sorted(set(names)):
            raise DomainError('validation_failed', 'producer sources must be uniquely sorted')
        expected = sha256(json.dumps(self.source_manifest, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        if self.source_digest != expected:
            raise DomainError('validation_failed', 'producer source digest')

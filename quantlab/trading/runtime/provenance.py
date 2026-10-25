"""Read the shipped v2 source inputs; a frozen package ships the same bytes."""

from hashlib import sha256
import json
from pathlib import Path

from quantlab.trading.application.provenance import ProducerProfile
from quantlab.trading.domain.validation import DomainError


def compute_profile() -> ProducerProfile:
    package = Path(__file__).resolve().parents[1]
    root = package.parents[1]
    manifest = tuple(
        (p.relative_to(root).as_posix(), sha256(p.read_bytes()).hexdigest()) for p in sorted(package.rglob('*.py')) if p.is_file() and not p.is_symlink()
    )
    if not any(name.endswith('/application/engine.py') for name, _ in manifest) or not any(name.endswith('/domain/risk.py') for name, _ in manifest):
        raise DomainError('source_invalid_evidence', 'v2 producer source inputs are missing')
    digest = sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return ProducerProfile('MARKAUTO-TRADING-V2-PROFILE-1', 2, manifest, digest)

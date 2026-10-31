"""Standard-library ISO timestamp parsing with explicit timezone ownership."""

from datetime import datetime, timezone


def aware_iso_utc(value: str) -> datetime:
    """Reject naive ISO timestamps and normalize explicit offsets to UTC."""
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed.astimezone(timezone.utc)

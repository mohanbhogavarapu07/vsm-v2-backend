"""
VSM Backend – Utility: Correlation ID Generator

Generates stable, deterministic correlation IDs for event aggregation.
Same source + ref always produces the same ID within a time bucket.
"""

import hashlib
from datetime import datetime, timezone


def generate_correlation_id(
    source: str,
    ref: str,
    bucket_minutes: int = 10,
) -> str:
    """
    Generates a deterministic correlation ID for grouping related events.

    Events from the same source + ref within the same time bucket
    receive the same correlation_id, enabling aggregation.

    Args:
        source: Event source (e.g. "github", "ci", "chat")
        ref:    Reference string (e.g. branch name, PR number, user ID)
        bucket_minutes: Time bucket size (default 10 minutes)

    Returns:
        A short hex string like "gh_a3f2c1d8"
    """
    now = datetime.now(timezone.utc)
    # Round down to the nearest bucket
    bucket_ts = now.replace(
        minute=(now.minute // bucket_minutes) * bucket_minutes,
        second=0,
        microsecond=0,
    )
    raw = f"{source}:{ref}:{bucket_ts.isoformat()}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:8]
    prefix = source[:2].lower()  # e.g. "gh" for github
    return f"{prefix}_{digest}"

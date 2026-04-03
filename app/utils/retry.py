"""
VSM Backend – Utility: Retry & Dead Letter Queue Logic (PRD 2 §14)

Provides exponential backoff calculation and dead-letter queue helpers.
"""

import logging

logger = logging.getLogger(__name__)


def compute_retry_backoff(retry_count: int, base_seconds: int = 5) -> int:
    """
    Exponential backoff: base * 2^retry_count

    retry_count=0 → 5s
    retry_count=1 → 10s
    retry_count=2 → 20s
    retry_count=3 → 40s (max effective)

    Capped at 300 seconds (5 minutes).
    """
    backoff = base_seconds * (2 ** retry_count)
    return min(backoff, 300)


def should_dead_letter(retry_count: int, max_retries: int = 3) -> bool:
    """
    Returns True if the event should be moved to the dead letter queue.
    """
    return retry_count >= max_retries


def log_dead_letter(event_id: int, retry_count: int, last_error: str) -> None:
    """
    Logs a dead-letter event for debugging / observability.
    In production this would write to a dedicated dead_letter_events table.
    """
    logger.error(
        "DEAD_LETTER: event_id=%s failed after %s retries. Last error: %s",
        event_id,
        retry_count,
        last_error,
    )

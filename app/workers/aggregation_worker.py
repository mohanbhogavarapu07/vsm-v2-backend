"""
VSM Backend – Aggregation Worker (Prisma)

Race condition fix via time-windowed event buffering.
Uses Prisma's get_db_context() for each task invocation.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from app.workers.celery_app import celery_app
from app.config import get_settings
from app.database import get_db_context
from app.repositories.event_repository import EventRepository

logger = logging.getLogger(__name__)
settings = get_settings()


def _run_async(coro):
    """
    Robust asyncio runner for Celery workers.
    Handles loop creation/retrieval to avoid 'No event loop' errors.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(
    name="app.workers.aggregation_worker.aggregate_event",
    bind=True,
    queue="aggregation",
)
def aggregate_event(self, event_id: int, correlation_id: str) -> dict:
    return _run_async(_aggregate_event(event_id, correlation_id))


async def _aggregate_event(event_id: int, correlation_id: str) -> dict:
    async with get_db_context() as db:
        repo = EventRepository(db)
        window = await repo.get_open_window(correlation_id)

        if window:
            current_events = window.aggregatedEvents if isinstance(window.aggregatedEvents, list) else []
            await repo.append_to_window(window.id, current_events, event_id)
            logger.debug(
                "Appended event %s to window %s (correlation=%s events=%d)",
                event_id, window.id, correlation_id, len(current_events) + 1,
            )
            return {
                "window_id": window.id,
                "action": "appended",
                "event_count": len(current_events) + 1,
            }
        else:
            window = await repo.create_aggregation_window(correlation_id, event_id)
            logger.info(
                "Opened new aggregation window %s for correlation=%s",
                window.id, correlation_id,
            )
            return {
                "window_id": window.id,
                "action": "created",
                "event_count": 1,
            }


@celery_app.task(
    name="app.workers.aggregation_worker.close_expired_windows",
    queue="aggregation",
)
def close_expired_windows() -> dict:
    return _run_async(_close_expired_windows())


async def _close_expired_windows() -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.aggregation_window_seconds
    )

    async with get_db_context() as db:
        repo = EventRepository(db)
        expired_windows = await repo.get_expired_open_windows(cutoff)

        closed_count = 0
        for window in expired_windows:
            await repo.close_window(window.id)
            closed_count += 1
            event_ids = window.aggregatedEvents if isinstance(window.aggregatedEvents, list) else []
            logger.info(
                "Closed window %s (correlation=%s, events=%d) → dispatching to AI",
                window.id, window.correlationId, len(event_ids),
            )
            from app.workers.ai_trigger_worker import trigger_ai_inference
            trigger_ai_inference.delay(
                window_id=window.id,
                correlation_id=window.correlationId,
                event_ids=event_ids,
                window_start=window.startTime.isoformat(),
                window_end=window.endTime.isoformat() if window.endTime else datetime.now(timezone.utc).isoformat(),
            )

        return {"closed_windows": closed_count}

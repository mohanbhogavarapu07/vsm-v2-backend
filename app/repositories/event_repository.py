"""
VSM Backend – Event Repository (Prisma)

All DB interactions for EventLog, EventProcessingQueue,
and EventAggregationWindow via Prisma Client Python.

Prisma API used:
  db.eventlog.create(data={...})
  db.eventlog.find_many(where={...})
  db.eventlog.update(where={...}, data={...})
"""

import logging
from datetime import datetime, timezone

from prisma import Prisma
from prisma.models import EventLog, EventProcessingQueue, EventAggregationWindow

from app.models.enums import EventType, EventSource, QueueStatus, WindowStatus

logger = logging.getLogger(__name__)


class EventRepository:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    # ── EventLog ──────────────────────────────────────────────────────────────

    async def create_event(
        self,
        event_type: EventType,
        source: EventSource,
        payload: dict,
        event_timestamp: datetime,
        reference_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EventLog:
        event = await self._db.eventlog.create(
            data={
                "eventType": event_type.value,
                "source": source.value,
                "payload": payload,
                "eventTimestamp": event_timestamp,
                "referenceId": reference_id,
                "correlationId": correlation_id,
            }
        )
        logger.debug("Created event_log id=%s type=%s", event.id, event_type)
        return event

    async def mark_event_processed(self, event_id: int) -> None:
        await self._db.eventlog.update(
            where={"id": event_id},
            data={"processed": True},
        )

    async def get_unprocessed_events(self, limit: int = 100) -> list[EventLog]:
        return await self._db.eventlog.find_many(
            where={"processed": False},
            order={"eventTimestamp": "asc"},
            take=limit,
        )

    async def get_event_by_id(self, event_id: int) -> EventLog | None:
        return await self._db.eventlog.find_unique(
            where={"id": event_id}
        )

    async def list_recent_events(self, limit: int = 100) -> list[EventLog]:
        return await self._db.eventlog.find_many(
            order={"eventTimestamp": "desc"},
            take=limit,
        )

    # ── EventProcessingQueue ──────────────────────────────────────────────────

    async def enqueue_event(self, event_id: int) -> EventProcessingQueue:
        return await self._db.eventprocessingqueue.create(
            data={
                "eventId": event_id,
                "status": QueueStatus.PENDING.value,
                "retryCount": 0,
            }
        )

    async def get_queue_by_event_id(self, event_id: int) -> EventProcessingQueue | None:
        return await self._db.eventprocessingqueue.find_unique(
            where={"eventId": event_id}
        )

    async def update_queue_status(
        self,
        queue_id: int,
        status: QueueStatus,
        error_message: str | None = None,
    ) -> None:
        data: dict = {"status": status.value}
        if error_message:
            data["errorMessage"] = error_message
        await self._db.eventprocessingqueue.update(
            where={"id": queue_id},
            data=data,
        )

    async def increment_retry_count(
        self, queue_id: int, scheduled_at: datetime
    ) -> None:
        await self._db.eventprocessingqueue.update(
            where={"id": queue_id},
            data={
                "retryCount": {"increment": 1},
                "scheduledAt": scheduled_at,
                "status": QueueStatus.PENDING.value,
            },
        )

    async def get_failed_queue_entries(self, max_retries: int, limit: int = 50) -> list[EventProcessingQueue]:
        return await self._db.eventprocessingqueue.find_many(
            where={
                "status": QueueStatus.FAILED.value,
                "retryCount": {"lt": max_retries},
            },
            take=limit,
        )

    # ── EventAggregationWindow ────────────────────────────────────────────────

    async def get_open_window(
        self, correlation_id: str
    ) -> EventAggregationWindow | None:
        return await self._db.eventaggregationwindow.find_first(
            where={
                "correlationId": correlation_id,
                "status": WindowStatus.OPEN.value,
            }
        )

    async def create_aggregation_window(
        self, correlation_id: str, event_id: int
    ) -> EventAggregationWindow:
        now = datetime.now(timezone.utc)
        return await self._db.eventaggregationwindow.create(
            data={
                "correlationId": correlation_id,
                "startTime": now,
                "aggregatedEvents": [event_id],
                "status": WindowStatus.OPEN.value,
            }
        )

    async def append_to_window(
        self, window_id: int, current_events: list, new_event_id: int
    ) -> EventAggregationWindow:
        """Appends event_id to the window's aggregatedEvents JSON array."""
        updated_events = current_events + [new_event_id]
        return await self._db.eventaggregationwindow.update(
            where={"id": window_id},
            data={"aggregatedEvents": updated_events},
        )

    async def close_window(self, window_id: int) -> None:
        await self._db.eventaggregationwindow.update(
            where={"id": window_id},
            data={
                "status": WindowStatus.CLOSED.value,
                "endTime": datetime.now(timezone.utc),
            },
        )

    async def get_expired_open_windows(self, cutoff: datetime) -> list[EventAggregationWindow]:
        return await self._db.eventaggregationwindow.find_many(
            where={
                "status": WindowStatus.OPEN.value,
                "startTime": {"lte": cutoff},
            }
        )

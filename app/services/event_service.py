"""
VSM Backend – Event Service (Prisma)

Core business logic for event ingestion.
Repositories accept Prisma client directly — no session management needed.
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone

from prisma import Prisma

from app.config import get_settings
from app.models.enums import EventType, EventSource
from app.repositories.event_repository import EventRepository
from app.utils.correlation import generate_correlation_id

logger = logging.getLogger(__name__)
settings = get_settings()


class EventService:
    def __init__(self, db: Prisma) -> None:
        self._repo = EventRepository(db)

    async def ingest_github_event(
        self,
        payload: dict,
        event_timestamp: datetime | None = None,
        reference_id: str | None = None,
        branch_name: str | None = None,
    ) -> int:
        ts = event_timestamp or datetime.now(timezone.utc)
        correlation_id = generate_correlation_id(
            source="github",
            ref=branch_name or reference_id or "",
        )

        # Determine event type from payload shape
        pr = payload.get("pull_request", {})
        if pr and pr.get("merged"):
            event_type = EventType.PR_MERGED
        elif pr:
            event_type = EventType.PR_CREATED
        else:
            event_type = EventType.GIT_COMMIT

        event = await self._repo.create_event(
            event_type=event_type,
            source=EventSource.GITHUB,
            payload=payload,
            event_timestamp=ts,
            reference_id=reference_id,
            correlation_id=correlation_id,
        )
        await self._repo.enqueue_event(event.id)
        logger.info("Ingested GitHub event id=%s type=%s", event.id, event_type)
        return event.id

    async def ingest_chat_event(
        self,
        payload: dict,
        user_id: str,
        team_id: str,
        event_timestamp: datetime | None = None,
    ) -> int:
        ts = event_timestamp or datetime.now(timezone.utc)
        correlation_id = generate_correlation_id(
            source="chat", ref=f"{team_id}_{user_id}"
        )
        event = await self._repo.create_event(
            event_type=EventType.CHAT_MESSAGE,
            source=EventSource.SLACK,
            payload=payload,
            event_timestamp=ts,
            correlation_id=correlation_id,
        )
        await self._repo.enqueue_event(event.id)
        logger.info("Ingested CHAT event id=%s", event.id)
        return event.id

    async def ingest_ci_event(
        self,
        payload: dict,
        pipeline_id: str,
        status: str,
        event_timestamp: datetime | None = None,
        branch: str | None = None,
    ) -> int:
        ts = event_timestamp or datetime.now(timezone.utc)
        correlation_id = generate_correlation_id(
            source="ci", ref=branch or pipeline_id
        )
        event = await self._repo.create_event(
            event_type=EventType.CI_STATUS,
            source=EventSource.CI,
            payload=payload,
            event_timestamp=ts,
            reference_id=pipeline_id,
            correlation_id=correlation_id,
        )
        await self._repo.enqueue_event(event.id)
        logger.info("Ingested CI event id=%s pipeline=%s status=%s", event.id, pipeline_id, status)
        return event.id

    async def get_event_repo(self) -> EventRepository:
        return self._repo

    @staticmethod
    def verify_github_signature(raw_body: bytes, signature_header: str) -> bool:
        if not settings.webhook_hmac_enabled:
            return True
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = hmac.new(
            settings.github_webhook_secret.encode(),
            raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        actual = signature_header.removeprefix("sha256=")
        return hmac.compare_digest(expected, actual)

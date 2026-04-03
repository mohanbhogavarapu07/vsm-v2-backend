"""
VSM Backend – CI Webhook Endpoint (Prisma)
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from prisma import Prisma

from app.database import get_db
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService
from app.schemas.webhook_schemas import CIWebhookPayload, WebhookReceivedResponse
from app.workers.event_processor import process_event
from app.workers.aggregation_worker import aggregate_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/ci",
    response_model=WebhookReceivedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="CI/CD Webhook Receiver",
)
async def ci_webhook(
    payload: CIWebhookPayload,
    db: Prisma = Depends(get_db),
) -> WebhookReceivedResponse:
    svc = EventService(db)

    try:
        ts = datetime.fromisoformat(payload.timestamp)
    except ValueError:
        ts = datetime.now(timezone.utc)

    event_id = await svc.ingest_ci_event(
        payload=payload.model_dump(),
        pipeline_id=payload.pipeline_id,
        status=payload.pipeline_status,
        event_timestamp=ts,
        branch=payload.branch,
    )

    event_repo = EventRepository(db)
    event = await event_repo.get_event_by_id(event_id)
    if event:
        queue = await event_repo.get_queue_by_event_id(event_id)
        if queue:
            process_event.delay(event_id, queue.id)
        if event.correlationId:
            aggregate_event.delay(event_id, event.correlationId)

    return WebhookReceivedResponse(
        event_id=event_id,
        message=f"CI event ({payload.pipeline_status}) queued for processing",
    )

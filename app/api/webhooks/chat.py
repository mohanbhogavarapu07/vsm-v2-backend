"""
VSM Backend – Chat Webhook Endpoint (Prisma)
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from prisma import Prisma

from app.database import get_db
from app.repositories.event_repository import EventRepository
from app.repositories.activity_repository import ActivityRepository
from app.services.event_service import EventService
from app.schemas.webhook_schemas import ChatWebhookPayload, WebhookReceivedResponse
from app.workers.nlp_worker import process_chat_message
from app.workers.aggregation_worker import aggregate_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/chat",
    response_model=WebhookReceivedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Chat/Slack Webhook Receiver",
)
async def chat_webhook(
    payload: ChatWebhookPayload,
    db: Prisma = Depends(get_db),
) -> WebhookReceivedResponse:
    activity_repo = ActivityRepository(db)
    svc = EventService(db)

    try:
        ts = datetime.fromtimestamp(float(payload.timestamp), tz=timezone.utc)
    except (ValueError, TypeError):
        ts = datetime.now(timezone.utc)

    # Deduplication check
    if payload.platform_message_id:
        existing = await activity_repo.find_chat_message_by_platform_id(payload.platform_message_id)
        if existing:
            return WebhookReceivedResponse(event_id=0, message="Duplicate message ignored")

    chat_msg = await activity_repo.create_chat_message(
        user_id=int(payload.user_id),
        team_id=int(payload.team_id),
        message=payload.message,
        timestamp=ts,
        platform_message_id=payload.platform_message_id,
    )

    event_id = await svc.ingest_chat_event(
        payload=payload.model_dump(),
        user_id=str(payload.user_id),
        team_id=str(payload.team_id),
        event_timestamp=ts,
    )

    process_chat_message.delay(
        event_id=event_id,
        message_id=chat_msg.id,
        message_text=payload.message,
        user_id=int(payload.user_id),
        team_id=int(payload.team_id),
    )

    event_repo = EventRepository(db)
    event = await event_repo.get_event_by_id(event_id)
    if event and event.correlationId:
        aggregate_event.delay(event_id, event.correlationId)

    return WebhookReceivedResponse(event_id=event_id, message="Chat message queued for NLP processing")

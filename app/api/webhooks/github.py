"""
VSM Backend – GitHub Webhook Endpoint (Prisma)
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from prisma import Prisma

from app.database import get_db
from app.repositories.event_repository import EventRepository
from app.services.event_service import EventService
from app.schemas.webhook_schemas import WebhookReceivedResponse
from app.workers.event_processor import process_event
from app.workers.aggregation_worker import aggregate_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/github",
    response_model=WebhookReceivedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="GitHub Webhook Receiver",
)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    db: Prisma = Depends(get_db),
) -> WebhookReceivedResponse:
    raw_body = await request.body()

    svc = EventService(db)
    if not svc.verify_github_signature(raw_body, x_hub_signature_256 or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    if x_github_event == "ping":
        return WebhookReceivedResponse(event_id=0, message="Ping acknowledged")

    ref = payload.get("ref", "")
    pr = payload.get("pull_request", {})
    branch = pr.get("head", {}).get("ref") or (
        ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else None
    )
    reference_id = str(pr.get("number", "")) if pr else payload.get("after", "")

    # Extract GitHub App context
    installation_id = payload.get("installation", {}).get("id")
    repository_id = payload.get("repository", {}).get("id")

    event_id = await svc.ingest_github_event(
        payload=payload,
        event_timestamp=datetime.now(timezone.utc),
        reference_id=reference_id or None,
        branch_name=branch,
        installation_id=installation_id,
        repository_id=repository_id,
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
        message=f"GitHub {x_github_event} event queued for processing",
    )

from fastapi import APIRouter, Request, Header, HTTPException, status, Depends
from prisma import Prisma
import uuid
import logging

from app.database import get_db
from app.tasks.event_dispatch_task import process_github_webhook

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.post("/github")
async def github_webhook_receiver(
    request: Request,
    x_github_delivery: str = Header(...),
    x_github_event: str = Header(...),
    db: Prisma = Depends(get_db)
):
    """
    Ingest GitHub webhook event and dispatch to Celery for processing.
    Idempotency and logging are handled in the background task.
    """
    raw_payload = await request.json()
    correlation_id = str(uuid.uuid4())
    
    # We pass the delivery_id as the primary key for idempotency checks in the task
    process_github_webhook.delay(
        delivery_id=x_github_delivery,
        event_type=x_github_event,
        payload=raw_payload,
        correlation_id=correlation_id
    )
    
    return {"status": "accepted", "correlation_id": correlation_id}

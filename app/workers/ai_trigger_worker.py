"""
VSM Backend – AI Trigger Worker (Prisma)

Sends aggregated context to vsm-ai-agent and applies decisions back to DB.
Uses Prisma for all DB reads/writes.
"""

import asyncio
import logging

import httpx

from app.workers.celery_app import celery_app
from app.config import get_settings
from app.database import get_db_context
from app.repositories.event_repository import EventRepository
from app.repositories.task_repository import TaskRepository
from app.models.enums import DecisionSource
from app.utils.retry import compute_retry_backoff

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
    name="app.workers.ai_trigger_worker.trigger_ai_inference",
    bind=True,
    max_retries=settings.celery_task_max_retries,
    queue="ai_trigger",
)
def trigger_ai_inference(
    self,
    window_id: int,
    correlation_id: str,
    event_ids: list[int],
    window_start: str,
    window_end: str,
) -> dict:
    return _run_async(
        _trigger_ai_inference(self, window_id, correlation_id, event_ids, window_start, window_end)
    )


async def _trigger_ai_inference(
    task_instance,
    window_id: int,
    correlation_id: str,
    event_ids: list[int],
    window_start: str,
    window_end: str,
) -> dict:
    async with get_db_context() as db:
        event_repo = EventRepository(db)
        task_repo = TaskRepository(db)

        # ── Build aggregated event context ─────────────────────────────────────
        events_data = []
        task_id: int | None = None
        team_id: int | None = None

        for eid in event_ids:
            event = await event_repo.get_event_by_id(eid)
            if event:
                events_data.append({
                    "event_id": event.id,
                    "event_type": event.eventType,
                    "source": event.source,
                    "reference_id": event.referenceId,
                    "payload": event.payload,
                    "event_timestamp": event.eventTimestamp.isoformat(),
                })
                if not task_id:
                    task_id = _extract_task_id_from_payload(event.payload)

        if not task_id:
            logger.warning("No task_id found in window %s — skipping AI", window_id)
            return {"status": "skipped", "reason": "no_task_id"}

        task = await task_repo.get_task_by_id(task_id)
        if not task:
            logger.warning("Task %s not found — skipping AI", task_id)
            return {"status": "skipped", "reason": "task_not_found"}

        team_id = task.teamId

        # ── Call vsm-ai-agent ──────────────────────────────────────────────────
        ai_payload = {
            "task_id": task_id,
            "team_id": team_id,
            "correlation_id": correlation_id,
            "aggregated_events": events_data,
            "window_start": window_start,
            "window_end": window_end,
        }

        try:
            async with httpx.AsyncClient(timeout=settings.ai_agent_timeout) as client:
                response = await client.post(
                    f"{settings.ai_agent_url}/agent/infer",
                    json=ai_payload,
                )
                response.raise_for_status()
                ai_result = response.json()
        except httpx.HTTPError as exc:
            logger.error("AI agent HTTP error: %s", exc)
            backoff = compute_retry_backoff(task_instance.request.retries)
            raise task_instance.retry(exc=exc, countdown=backoff)

        # Execution is performed by vsm-ai-agent via RBAC-protected backend APIs.
        return {"status": "completed", "ai_result": ai_result}


def _extract_task_id_from_payload(payload: dict) -> int | None:
    if tid := payload.get("task_id"):
        return int(tid)
    ref = payload.get("ref", "")
    branch = payload.get("pull_request", {}).get("head", {}).get("ref", ref)
    from app.workers.event_processor import _extract_task_id_from_branch
    return _extract_task_id_from_branch(branch)

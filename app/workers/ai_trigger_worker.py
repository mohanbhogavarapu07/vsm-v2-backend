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
                
                # If we don't have a team_id yet, try to get it from the repository
                if not team_id and event.repositoryId:
                    gh_repo = await db.githubrepository.find_unique(where={"id": event.repositoryId})
                    if gh_repo and gh_repo.teamId:
                        team_id = gh_repo.teamId

        if not team_id and not task_id:
            logger.warning("No task_id or team_id found in window %s — skipping AI", window_id)
            return {"status": "skipped", "reason": "no_context"}

        if task_id:
            task = await task_repo.get_task_by_id(task_id)
            if not task:
                logger.warning("Task %s not found — proceeding without specific task context", task_id)
                task_id = None # Fallback to discovery if task ID is invalid
            else:
                team_id = task.teamId

        if not team_id:
            logger.warning("Could not resolve team_id for window %s — skipping AI", window_id)
            return {"status": "skipped", "reason": "no_team_id"}

        # Resolve project_id from team_id
        team = await db.team.find_unique(where={"id": team_id})
        if not team:
            logger.error("Team %s not found during project resolution", team_id)
            return {"status": "error", "reason": "team_not_found"}
        project_id = team.projectId

        # ── Call vsm-ai-agent ──────────────────────────────────────────────────
        # Aligned with vsm-ai-agent InferRequest schema
        ai_payload = {
            "project_id": project_id,
            "team_id": team_id,
            "task_id": task_id,
            "correlation_id": correlation_id,
            "aggregated_events": events_data,
            "window_start": window_start,
            "window_end": window_end,
            "github_event_type": events_data[0]["event_type"] if events_data else "UNKNOWN",
            "actor_github_login": events_data[0]["payload"].get("sender", {}).get("login", "unknown") if events_data else "unknown",
        }

        try:
            async with httpx.AsyncClient(timeout=settings.ai_agent_timeout) as client:
                # Health check before sending payload
                try:
                    health_response = await client.get(
                        f"{settings.ai_agent_url}/health",
                        timeout=2.0
                    )
                    if health_response.status_code != 200:
                        logger.warning(
                            "AI agent health check failed with status %s for window %s. Proceeding with inference anyway.",
                            health_response.status_code, window_id
                        )
                except Exception as health_exc:
                    logger.warning(
                        "AI agent health check failed for window %s: %s. Proceeding with inference anyway.",
                        window_id, health_exc
                    )
                
                # Send inference request
                response = await client.post(
                    f"{settings.ai_agent_url}/agent/infer",
                    json=ai_payload,
                )
                response.raise_for_status()
                ai_result = response.json()
                logger.info("AI agent inference successful for window %s", window_id)
        except httpx.ConnectError:
            logger.error(
                "AI agent connection refused at %s for window %s. "
                "Ensure AI agent service is running. Events stored but not processed.",
                settings.ai_agent_url, window_id
            )
            return {
                "status": "ai_agent_unreachable",
                "error": "Connection refused",
                "ai_agent_url": settings.ai_agent_url,
                "window_id": window_id
            }
        except httpx.TimeoutException as exc:
            logger.error(
                "AI agent timeout at %s for window %s (timeout: %ss). AI agent may be overloaded.",
                settings.ai_agent_url, window_id, settings.ai_agent_timeout
            )
            backoff = compute_retry_backoff(task_instance.request.retries)
            raise task_instance.retry(exc=exc, countdown=backoff)
        except httpx.HTTPError as exc:
            logger.error(
                "AI agent HTTP error: %s for window %s. Status: %s",
                exc, window_id, getattr(exc.response, 'status_code', 'unknown')
            )
            backoff = compute_retry_backoff(task_instance.request.retries)
            raise task_instance.retry(exc=exc, countdown=backoff)

        # Execution is performed by vsm-ai-agent via RBAC-protected backend APIs.
        return {"status": "completed", "ai_result": ai_result}


def _extract_task_id_from_payload(payload: dict) -> int | None:
    if tid := payload.get("task_id"):
        return int(tid)
    pr = payload.get("pull_request", {})
    branch = pr.get("head", {}).get("ref") or payload.get("ref", "")
    title = pr.get("title", "")
    
    from app.workers.event_processor import _extract_task_id
    return _extract_task_id(branch) or _extract_task_id(title)

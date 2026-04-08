"""
VSM Backend – Event Processor Worker (Prisma)

Reads from event_log, normalizes events, writes to task_activity or unlinked_activity.
Uses get_db_context() which creates its own Prisma connection per worker call.
"""

import asyncio
import logging

from celery import Task

from app.workers.celery_app import celery_app
from app.config import get_settings
from app.database import get_db_context
from app.models.enums import EventType, ActivityType, UnlinkedActivityType, QueueStatus
from app.repositories.event_repository import EventRepository
from app.repositories.activity_repository import ActivityRepository
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
    name="app.workers.event_processor.process_event",
    bind=True,
    max_retries=settings.celery_task_max_retries,
    queue="event_processing",
)
def process_event(self: Task, event_id: int, queue_id: int) -> dict:
    return _run_async(_process_event(self, event_id, queue_id))


async def _process_event(task_instance: Task, event_id: int, queue_id: int) -> dict:
    async with get_db_context() as db:
        event_repo = EventRepository(db)
        activity_repo = ActivityRepository(db)

        event = await event_repo.get_event_by_id(event_id)
        if not event:
            logger.error("Event %s not found", event_id)
            return {"status": "error", "reason": "event_not_found"}

        await event_repo.update_queue_status(queue_id, QueueStatus.PROCESSING)

        try:
            payload = event.payload
            repo_id = event.repositoryId
            target_team_id = None

            # 1. Identify the team associated with this repository
            if repo_id:
                gh_repo = await db.githubrepository.find_unique(where={"id": repo_id})
                if gh_repo and gh_repo.teamId:
                    target_team_id = gh_repo.teamId
                    logger.info("Matched event %s to team %s", event_id, target_team_id)

            if event.eventType in (EventType.PR_CREATED.value, EventType.PR_MERGED.value):
                pr = payload.get("pull_request", {})
                branch = pr.get("head", {}).get("ref")
                title = pr.get("title", "")
                body = pr.get("body", "")
                pr_num = str(payload.get("number", ""))
                
                # Check branch, then title, then body for task_id
                task_id = _extract_task_id(branch) or _extract_task_id(title) or _extract_task_id(body)
                
                # Verify task belongs to team if team is known
                if task_id and target_team_id:
                    task = await db.task.find_unique(where={"id": task_id})
                    if not task or task.teamId != target_team_id:
                        logger.warning("Task %s does not belong to team %s. Marking as unlinked.", task_id, target_team_id)
                        task_id = None

                if task_id:
                    await activity_repo.create_activity(
                        activity_type=ActivityType.PR,
                        metadata=payload,
                        task_id=task_id,
                        reference_id=pr_num,
                        event_log_id=event.id,
                    )
                else:
                    await activity_repo.create_unlinked(
                        activity_type=UnlinkedActivityType.PR,
                        branch_name=branch,
                        reference_id=pr_num,
                    )

            elif event.eventType == EventType.GIT_COMMIT.value:
                commits = payload.get("commits", [])
                for commit in commits:
                    branch = _extract_branch(payload.get("ref", ""))
                    commit_msg = commit.get("message", "")
                    
                    # Check branch, then commit message
                    task_id = _extract_task_id(branch) or _extract_task_id(commit_msg)

                    # Verify task belongs to team if team is known
                    if task_id and target_team_id:
                        task = await db.task.find_unique(where={"id": task_id})
                        if not task or task.teamId != target_team_id:
                            logger.warning("Task %s does not belong to team %s. Marking as unlinked.", task_id, target_team_id)
                            task_id = None

                    if task_id:
                        await activity_repo.create_activity(
                            activity_type=ActivityType.COMMIT,
                            metadata=commit,
                            task_id=task_id,
                            reference_id=commit.get("id"),
                            event_log_id=event.id,
                        )
                    else:
                        await activity_repo.create_unlinked(
                            activity_type=UnlinkedActivityType.COMMIT,
                            branch_name=branch,
                            commit_message=commit_msg,
                            reference_id=commit.get("id"),
                        )

            elif event.eventType == EventType.CI_STATUS.value:
                # CI status might also be linkable to tasks via branch names in payload
                # For now keeping it general but storing reference
                await activity_repo.create_activity(
                    activity_type=ActivityType.CI,
                    metadata=payload,
                    reference_id=payload.get("pipeline_id"),
                    event_log_id=event.id,
                )

            await event_repo.mark_event_processed(event_id)
            await event_repo.update_queue_status(queue_id, QueueStatus.COMPLETED)
            return {"status": "completed", "event_id": event_id}

        except Exception as exc:
            logger.exception("Failed to process event %s: %s", event_id, exc)
            await event_repo.update_queue_status(
                queue_id, QueueStatus.FAILED, error_message=str(exc)
            )
            backoff = compute_retry_backoff(task_instance.request.retries)
            raise task_instance.retry(exc=exc, countdown=backoff)


@celery_app.task(
    name="app.workers.event_processor.retry_failed_events",
    queue="event_processing",
)
def retry_failed_events() -> None:
    _run_async(_retry_failed_events())


async def _retry_failed_events() -> None:
    async with get_db_context() as db:
        event_repo = EventRepository(db)
        failed = await event_repo.get_failed_queue_entries(
            max_retries=settings.celery_task_max_retries
        )
        for entry in failed:
            logger.info("Requeueing failed event %s (retry %s)", entry.eventId, entry.retryCount)
            process_event.delay(entry.eventId, entry.id)


def _extract_task_id(text: str | None) -> int | None:
    """Generic extractor for VSM Task IDs (#123, task-123, feature/PROJ-123)."""
    if not text:
        return None
    import re
    patterns = [
        r"(?:feature|fix|hotfix|bugfix|chore)/(?:[A-Z]+-)?(\d+)",
        r"[A-Z]{2,}-(\d+)",       # Matches VSM-123, PROJ-123
        r"\[[A-Z]{2,}-(\d+)\]",   # Matches [VSM-123]
        r"task[/-](\d+)",         # Matches task/123, task-123
        r"(?i)task[:\s]+#?(\d+)", # Matches Task: 123, task 123
        r"#(\d+)",                # Matches #123
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _extract_branch(ref: str) -> str | None:
    if ref.startswith("refs/heads/"):
        return ref.removeprefix("refs/heads/")
    return ref or None

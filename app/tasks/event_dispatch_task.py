import asyncio
import httpx
import structlog
from typing import Dict, Any, Optional
from celery import Task
import json
from datetime import datetime

from app.workers.celery_app import celery_app
from app.database import get_db_context
from app.config import get_settings
from app.tasks.apply_decision_task import apply_agent_decision

logger = structlog.get_logger(__name__)
settings = get_settings()

def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

@celery_app.task(name="app.tasks.event_dispatch_task.process_github_webhook", bind=True)
def process_github_webhook(self: Task, delivery_id: str, event_type: str, payload: Dict[str, Any], correlation_id: str):
    """
    Step 3: DISPATCH ONLY task.
    Idempotency check, Log ingestion, Task matching, Agent dispatch.
    """
    return _run_async(_process_github_webhook(delivery_id, event_type, payload, correlation_id))

async def _process_github_webhook(delivery_id: str, event_type: str, payload: Dict[str, Any], correlation_id: str):
    async with get_db_context() as db:
        # 1. Idempotency Check
        # We check EventLog by delivery_id (stored in referenceId)
        existing_event = await db.eventlog.find_first(where={"referenceId": delivery_id})
        if existing_event:
            logger.info("event_already_processed", delivery_id=delivery_id, correlation_id=correlation_id)
            return

        # 2. Log Ingestion
        # We need an installation_id and repository_id for context
        installation_id = payload.get("installation", {}).get("id")
        repository_id = payload.get("repository", {}).get("id")
        
        # We need to map team to repository to find the project_id
        repo_record = await db.githubrepository.find_unique(
            where={"id": repository_id},
            include={"team": True}
        )
        
        if not repo_record or not repo_record.team:
            logger.error("repository_not_linked", repository_id=repository_id, correlation_id=correlation_id)
            return

        project_id = repo_record.team.projectId
        
        event_log = await db.eventlog.create(
            data={
                "eventType": "PR_CREATED" if "pull_request" in payload else "GIT_COMMIT", # Mapping helper
                "source": "GITHUB",
                "referenceId": delivery_id,
                "payload": json.dumps(payload),
                "installationId": installation_id,
                "repositoryId": repository_id,
                "eventTimestamp": datetime.utcnow(), # Correct DateTime type
                "correlationId": correlation_id,
                "processed": False
            }
        )

        # 3. Task Matching (Rule-based)
        task_id = await _find_target_task(db, payload, repo_record.teamId)
        actor_login = payload.get("sender", {}).get("login")

        # 4. Dispatch to vsm-ai-agent
        agent_payload = {
            "project_id": int(project_id),
            "task_id": task_id,
            "github_event_type": event_type,
            "actor_github_login": actor_login,
            "payload": payload,
            "correlation_id": correlation_id
        }

        async with httpx.AsyncClient(timeout=settings.ai_agent_timeout) as client:
            try:
                response = await client.post(
                    f"{settings.ai_agent_url}/agent/infer",
                    json=agent_payload
                )
                response.raise_for_status()
                decision_proposal = response.json()
            except Exception as e:
                logger.exception("agent_invocation_failed", error=str(e), correlation_id=correlation_id)
                # Fallback: Create a BLOCKED decision record
                decision_proposal = {
                    "status": "BLOCKED",
                    "reasoning": f"Agent invocation failed: {str(e)}",
                    "correlationId": correlation_id,
                    "githubEventType": event_type,
                    "taskId": task_id,
                    "confidenceScore": 0.0
                }

        # 5. Update Log Status
        await db.eventlog.update(
            where={"id": event_log.id},
            data={"processed": True}
        )

        # 6. Pass to Apply Task
        apply_agent_decision.delay(decision_proposal)

async def _find_target_task(db, payload: Dict[str, Any], team_id: int) -> Optional[int]:
    """
    Basic string matching for task identification.
    Matches against: PR title, Branch name, Commit message.
    Looking for patterns like "#123" or "TASK-123".
    """
    search_texts = []
    
    # PR Title
    if "pull_request" in payload:
        search_texts.append(payload["pull_request"].get("title", ""))
        search_texts.append(payload["pull_request"].get("head", {}).get("ref", ""))
    
    # Commit Messages
    if "commits" in payload:
        for commit in payload["commits"]:
            search_texts.append(commit.get("message", ""))
            
    # Push ref
    if "ref" in payload:
        search_texts.append(payload["ref"])

    import re
    task_id_pattern = re.compile(r"(?:#|TASK-)(\d+)", re.IGNORECASE)
    
    for text in search_texts:
        if not text: continue
        match = task_id_pattern.search(text)
        if match:
            potential_id = int(match.group(1))
            # Verify task exists in this team
            task = await db.task.find_first(where={"id": potential_id, "teamId": team_id})
            if task:
                return potential_id
                
    return None

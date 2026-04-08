import asyncio
import structlog
from typing import Dict, Any
from celery import Task
import json

from app.workers.celery_app import celery_app
from app.database import get_db_context
from prisma.enums import AgentDecisionStatus, DecisionSource

logger = structlog.get_logger(__name__)

def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

@celery_app.task(name="app.tasks.apply_decision_task.apply_agent_decision", bind=True)
def apply_agent_decision(self: Task, proposal: Dict[str, Any]):
    """
    Step 4: DECISION APPLICATION task.
    Handles proposal mapping, task updates, and persistence.
    """
    return _run_async(_apply_agent_decision(proposal))

async def _apply_agent_decision(proposal: Dict[str, Any]):
    status = proposal.get("status")
    correlation_id = proposal.get("correlationId")
    task_id = proposal.get("taskId")
    
    log = logger.bind(
        correlation_id=correlation_id,
        task_id=task_id,
        status=status,
        service_name="backend_decision_executor"
    )

    async with get_db_context() as db:
        if status == "APPROVED":
            transition_id = proposal.get("transitionId")
            to_stage_id = int(proposal.get("toStageId"))
            
            # 1. Validate transition still exists
            transition = await db.workflowtransition.find_unique(where={"id": transition_id})
            if not transition:
                log.error("transition_invalid", transition_id=transition_id)
                return

            task = await db.task.find_unique(where={"id": task_id})
            from_stage_id = task.currentStageId if task else None

            # 2. Update Task Stage
            await db.task.update(
                where={"id": task_id},
                data={"currentStageId": to_stage_id}
            )
            
            # 3. Write AgentDecision Record
            await db.agentdecision.create(
                data={
                    "taskId": task_id,
                    "fromStageId": from_stage_id,
                    "toStageId": to_stage_id,
                    "transitionId": transition_id,
                    "confidenceScore": proposal.get("confidenceScore", 1.0),
                    "reasoning": proposal.get("reasoning", "Autonomous transition applied."),
                    "correlationId": correlation_id,
                    "status": "APPLIED",
                    "triggeredByEvent": proposal.get("githubEventType"),
                    "decisionSource": "AI_MODEL"
                }
            )
            
            # 4. Handle Post-Actions (Notify, Auto-Assign)
            post_actions = proposal.get("postActions", [])
            for action in post_actions:
                if action.get("type") == "AUTO_ASSIGN":
                    # Logic for auto-assigning based on actor
                    pass
                elif action.get("type") == "NOTIFY":
                    # Logic for pushing notifications
                    pass

            log.info("task_transition_applied", to_stage_id=to_stage_id, transition_id=transition_id)

        elif status in ["BLOCKED", "NO_TRANSITION"]:
            task = await db.task.find_unique(where={"id": task_id})
            from_stage_id = task.currentStageId if task else None
            
            await db.agentdecision.create(
                data={
                    "taskId": task_id,
                    "fromStageId": from_stage_id,
                    "confidenceScore": proposal.get("confidenceScore", 0.0),
                    "reasoning": proposal.get("reasoning"),
                    "correlationId": correlation_id,
                    "status": "BLOCKED" if status == "BLOCKED" else "NO_TRANSITION",
                    "decisionSource": "AI_MODEL"
                }
            )
            
            # Push to SM notification queue
            log.warning("agent_escalation", reason=proposal.get("reasoning"))

        elif status == "FUZZY_LINK":
            # Agent found a mismatch or probabilistic link
            await db.agentdecision.create(
                data={
                    "taskId": task_id,
                    "confidenceScore": proposal.get("confidenceScore", 0.0),
                    "reasoning": proposal.get("reasoning"),
                    "correlationId": correlation_id,
                    "status": "PENDING_CONFIRMATION",
                    "decisionSource": "AI_MODEL"
                }
            )
            log.info("agent_pending_confirmation", reason=proposal.get("reasoning"))

        else:
            log.error("unknown_proposal_status", status=status)

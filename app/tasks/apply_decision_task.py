import asyncio
import structlog
from typing import Dict, Any
from celery import Task
import json

from app.workers.celery_app import celery_app
from app.database import get_db_context
from prisma.enums import AgentDecisionStatus, DecisionSource
from app.services.pubsub import publish_event

logger = structlog.get_logger(__name__)

def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

@celery_app.task(
    name="app.tasks.apply_decision_task.apply_agent_decision", 
    bind=True,
    queue="ai_trigger"
)
def apply_agent_decision(self: Task, proposal: Dict[str, Any]):
    """
    Step 4: DECISION APPLICATION task.
    Handles proposal mapping, task updates, and persistence.
    """
    return _run_async(_apply_agent_decision(proposal))

async def _apply_agent_decision(proposal: Dict[str, Any]):
    status = proposal.get("status")
    action_type = proposal.get("actionType", status)
    correlation_id = proposal.get("correlationId")
    task_id = proposal.get("taskId")
    
    log = logger.bind(
        correlation_id=correlation_id,
        task_id=task_id,
        status=status,
        action_type=action_type,
        service_name="backend_decision_executor"
    )

    if not task_id:
        log.error("missing_task_id_for_decision")
        return

    async with get_db_context() as db:
        task = await db.task.find_unique(
            where={"id": task_id},
            include={"currentStage": True}
        )
        if not task:
            log.error("task_not_found", task_id=task_id)
            return

        from_stage_id = task.currentStageId
        from_stage_name = task.currentStage.name if task.currentStage else None
        task_title = task.title

        if status == "APPROVED" and action_type == "MOVE":
            to_stage_id = proposal.get("toStageId")
            if to_stage_id is not None:
                to_stage_id = int(to_stage_id)
            
            # 1. Update Task Stage
            if to_stage_id:
                await db.task.update(
                    where={"id": task_id},
                    data={"currentStageId": to_stage_id}
                )
            
            # 2. Write AgentDecision Record
            decision = await db.agentdecision.create(
                data={
                    "taskId": task_id,
                    "fromStageId": from_stage_id,
                    "toStageId": to_stage_id,
                    "confidenceScore": proposal.get("confidenceScore", 1.0),
                    "reasoning": proposal.get("reasoning", "Autonomous semantic transition applied."),
                    "correlationId": correlation_id,
                    "status": "APPLIED",
                    "triggeredByEvent": proposal.get("githubEventType"),
                    "decisionSource": "AI_MODEL"
                }
            )
            
            # 3. Fetch to_stage name for enriched payload
            to_stage = await db.workflowstage.find_unique(where={"id": to_stage_id}) if to_stage_id else None
            to_stage_name = to_stage.name if to_stage else None

            # 4. Publish to WebSockets
            await publish_event(
                team_id=task.teamId,
                event_type="TASK_MOVED",
                payload={"id": task_id, "_source": "AI", "currentStageId": to_stage_id, "status_id": to_stage_id}
            )
            await publish_event(
                team_id=task.teamId,
                event_type="AI_DECISION",
                payload={
                    "id": decision.id,
                    "task_id": task_id,
                    "task_title": task_title,
                    "taskId": task_id,
                    "status": "APPLIED",
                    "reasoning": decision.reasoning,
                    "confidenceScore": decision.confidenceScore,
                    "confidence_score": decision.confidenceScore,
                    "from_stage_id": from_stage_id,
                    "from_stage_name": from_stage_name,
                    "to_stage_id": to_stage_id,
                    "to_stage_name": to_stage_name,
                }
            )
            
            log_message = (
                f"AI DECISION APPLIED: {status} | "
                f"Task: {task_id} | "
                f"{from_stage_name} --> {to_stage_name} | "
                f"Reasoning: {decision.reasoning}"
            )
            log.info("task_semantic_move_applied", message=log_message, to_stage_id=to_stage_id)

        elif action_type in ["FLAG_ASSIGNEE_MISMATCH", "FLAG_SCOPE_CREEP", "BLOCK"]:
            decision_status = AgentDecisionStatus.PENDING_CONFIRMATION if "FLAG" in action_type else AgentDecisionStatus.BLOCKED
            
            decision = await db.agentdecision.create(
                data={
                    "taskId": task_id,
                    "fromStageId": from_stage_id,
                    "confidenceScore": proposal.get("confidenceScore", 0.0),
                    "reasoning": proposal.get("reasoning"),
                    "correlationId": correlation_id,
                    "status": decision_status,
                    "decisionSource": "AI_MODEL"
                }
            )
            
            # 3. Push to SystemBlocker for the Virtual Scrum Master Alert
            await db.systemblocker.create(
                data={
                    "teamId": task.teamId,
                    "taskId": task_id,
                    "title": "Agent Warning: " + action_type.replace("_", " "),
                    "description": proposal.get("reasoning", "The AI Agent flagged an anomaly."),
                    "type": action_type,
                    "isResolved": False,
                    "metadata": json.dumps(proposal) if isinstance(proposal, dict) else "{}"
                }
            )
            
            # Publish to WebSockets
            await publish_event(
                team_id=task.teamId,
                event_type="AI_DECISION",
                payload={
                    "id": decision.id,
                    "taskId": task_id,
                    "status": str(decision_status.name) if hasattr(decision_status, 'name') else str(decision_status),
                    "reasoning": decision.reasoning,
                    "confidenceScore": decision.confidenceScore
                }
            )
            
            log.warning("agent_escalation_alert_created", reason=proposal.get("reasoning"), action_type=action_type)

        elif status in ["NO_TRANSITION", "FUZZY_LINK"]:
            # Store toStageId even for NO_TRANSITION so we know where the AI wanted to go
            proposed_to_stage_id = proposal.get("toStageId")
            if proposed_to_stage_id is not None:
                try:
                    proposed_to_stage_id = int(proposed_to_stage_id)
                except (TypeError, ValueError):
                    proposed_to_stage_id = None

            to_stage = await db.workflowstage.find_unique(where={"id": proposed_to_stage_id}) if proposed_to_stage_id else None
            to_stage_name = to_stage.name if to_stage else None

            await db.agentdecision.create(
                data={
                    "taskId": task_id,
                    "fromStageId": from_stage_id,
                    "toStageId": proposed_to_stage_id,
                    "confidenceScore": proposal.get("confidenceScore", 0.0),
                    "reasoning": proposal.get("reasoning"),
                    "correlationId": correlation_id,
                    "status": "NO_TRANSITION" if status == "NO_TRANSITION" else "FUZZY_LINK",
                    "decisionSource": "AI_MODEL"
                }
            )
            log_message = (
                f"AI DECISION: {status} | "
                f"Task: {task_id} | "
                f"{from_stage_name} --> {to_stage_name if to_stage_name else 'None'} | "
                f"Reasoning: {proposal.get('reasoning')}"
            )
            log.info("agent_handled_no_op", message=log_message, from_stage=from_stage_name, considered_to_stage=to_stage_name)

        else:
            log.error("unknown_semantic_action", action_type=action_type, status=status)

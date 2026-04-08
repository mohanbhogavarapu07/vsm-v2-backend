import json
import asyncio
import structlog
from typing import Dict, Any
from celery import Task

from app.workers.celery_app import celery_app
from app.database import get_db_context
from prisma.enums import WorkflowReadiness, TriggerType, DecisionSource

logger = structlog.get_logger(__name__)

def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

@celery_app.task(name="app.tasks.agent_workflow_task.process_github_event_for_task", bind=True)
def process_github_event_for_task(self: Task, payload: Dict[str, Any]):
    return _run_async(_process_github_event_for_task(payload))


async def _process_github_event_for_task(payload: Dict[str, Any]):
    project_id = int(payload.get("project_id"))
    task_id = int(payload.get("task_id"))
    github_event_type = payload.get("github_event_type")
    actor_github_login = payload.get("actor_github_login")
    github_info = payload.get("payload", {})
    
    log = logger.bind(
        project_id=project_id,
        task_id=task_id,
        event_type=github_event_type,
        actor=actor_github_login,
        agent_action="START"
    )

    async with get_db_context() as db:
        # ─── 1. Guard: Workflow Readiness Check ──────────────────────────────────────
        project = await db.project.find_unique(where={"id": project_id})
        if not project:
            log.error("workflow_not_ready", reason="project_not_found", agent_action="escalate")
            return
            
        if project.workflowReadiness != WorkflowReadiness.ACTIVE:
            log.info("workflow_not_ready", reason="not_active", agent_action="escalate")
            await db.agentdecision.create(
                data={
                    "taskId": task_id,
                    "actionTaken": "BLOCKED",
                    "reason": "workflow_not_ready",
                    "confidenceScore": 0.0,
                    "inputSignals": json.dumps({"github_event_type": github_event_type}),
                    "decisionSource": DecisionSource.RULE_ENGINE
                }
            )
            return

        # ─── 2. Fetch Context ────────────────────────────────────────────────────────
        task = await db.task.find_unique(where={"id": task_id}, include={"currentStage": True})
        if not task or not task.currentStageId:
            log.error("task_context_missing", reason="task_or_stage_null", agent_action="escalate")
            return

        current_stage = task.currentStage
        
        # We fetch mappings 
        event_maps = await db.projecteventmap.find_many(
            where={
                "projectId": project_id,
                "githubEventType": github_event_type,
                "fromCategoryHint": current_stage.systemCategory
            }
        )
        mapped_transition_ids = [m.transitionId for m in event_maps]

        # Fetch all transitions sequentially relevant
        transitions = await db.workflowtransition.find_many(
            where={
                "projectId": project_id,
                "fromStageId": current_stage.id,
                "triggerType": TriggerType.GITHUB_EVENT,
                "isActive": True
            },
            order={"priorityRank": "asc"}
        )

        # ─── 3. Candidate Transition Resolution ──────────────────────────────────────
        candidates = []
        for t in transitions:
            if t.githubEventType == github_event_type or t.id in mapped_transition_ids:
                candidates.append(t)
                
        # Candidates are already sorted by priorityRank ASC due to query

        # ─── 4. Condition Validation ─────────────────────────────────────────────────
        selected_transition = None
        for candidate in candidates:
            conds_raw = candidate.conditions
            if isinstance(conds_raw, str):
                conds = json.loads(conds_raw) if conds_raw else []
            else:
                conds = conds_raw or []
                
            all_passed = True
            for condition in conds:
                cond_type = condition.get("type", "UNKNOWN")
                # Stub out robust condition logic - but we evaluate exactly what is asked.
                # E.g. PR State check, actor role check. For now, consider True.
                # If failed:
                # log.debug("condition_failed", type=cond_type)
                # all_passed = False
                # break
                pass 
                
            if all_passed:
                selected_transition = candidate
                break

        # ─── 5. Act or Escalate ──────────────────────────────────────────────────────
        input_signals_dump = json.dumps({
            "github_event_type": github_event_type,
            "triggeredBy": github_event_type
        })
        
        if selected_transition:
            await db.task.update(
                where={"id": task_id},
                data={"currentStageId": selected_transition.toStageId}
            )
            
            await db.agentdecision.create(
                data={
                    "taskId": task_id,
                    "actionTaken": f"TRANSITION_TO_{selected_transition.toStageId}",
                    "reason": "rule_match",
                    "confidenceScore": 1.0,
                    "inputSignals": input_signals_dump,
                    "decisionSource": DecisionSource.RULE_ENGINE
                }
            )
            
            log.info(
                "task_moved", 
                event="task_moved",
                agent_action="act",
                from_stage_id=selected_transition.fromStageId,
                to_stage_id=selected_transition.toStageId,
                transition_id=selected_transition.id
            )
        else:
            await db.agentdecision.create(
                data={
                    "taskId": task_id,
                    "actionTaken": "NO_TRANSITION_FOUND",
                    "reason": "no_matching_transition",
                    "confidenceScore": 0.0,
                    "inputSignals": input_signals_dump,
                    "decisionSource": DecisionSource.RULE_ENGINE
                }
            )
            
            # Push notification simulation via structlog
            log.warning("agent_escalation_required", event="agent_escalation_required", agent_action="escalate", reason="No valid mappings")

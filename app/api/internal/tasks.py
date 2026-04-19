"""
VSM Backend – Internal Tasks API

RBAC-enforced task management endpoints.
Every user-facing endpoint requires the caller to have the matching Permission
for the team they are operating in (via X-User-ID header + team_id query param).

OPTIMIZED: Added response caching for frequently accessed read endpoints.

Flow:
  - User endpoints: X-User-ID + team_id → role → permissions → allow/deny
  - AI actions: same flow as any user (service account identity + RBAC)
"""

import logging

from fastapi import APIRouter, Depends, Header, Path, Query, status
from prisma import Prisma

from app.database import get_db
from app.services.task_service import TaskService, UNSET
from app.repositories.activity_repository import ActivityRepository
from app.repositories.event_repository import EventRepository
from app.utils.permissions import require_permission, require_any_permission
from app.utils.cache import task_cache, cached_response
from app.services.blocker_service import BlockerService
from app.schemas.task_schemas import (
    TaskSchema,
    TaskCreateRequest,
    TaskUpdateRequest,
    TaskStatusTransitionRequest,
    AgentDecisionSchema,
    DecisionFeedbackRequest,
    NLPFeedbackRequest,
    SystemBlockerSchema,
    AgentTransitionRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"], redirect_slashes=False)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — TASK CRUD (fully RBAC-protected)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=TaskSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new task [requires CREATE_TASK permission]",
)
async def create_task(
    payload: TaskCreateRequest,
    x_user_id: int = Header(..., alias="X-User-ID"),
    _: None = Depends(require_permission("CREATE_TASK")),
    db: Prisma = Depends(get_db),
) -> TaskSchema:
    svc = TaskService(db)
    task = await svc.create_task(
        team_id=payload.team_id,
        title=payload.title,
        description=payload.description,
        sprint_id=payload.sprint_id,
        current_stage_id=payload.current_stage_id,
        assignee_id=payload.assignee_id,
        priority=payload.priority,
        updater_id=x_user_id
    )
    return TaskSchema.model_validate(task)


@router.get(
    "",
    response_model=list[TaskSchema],
    summary="List tasks for a team [requires READ_TASK permission]",
)
async def list_tasks(
    team_id: int = Query(..., description="Team ID to list tasks for"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> list[TaskSchema]:
    # Cache key includes team_id, limit, offset
    cache_key = f"tasks_list_{team_id}_{limit}_{offset}"
    cached = task_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"Cache HIT: {cache_key}")
        return cached
    
    svc = TaskService(db)
    tasks = await svc.list_tasks(team_id, limit, offset)
    result = [TaskSchema.model_validate(t) for t in tasks]
    task_cache.set(cache_key, result)
    return result


@router.post(
    "/agent/transition",
    response_model=TaskSchema,
    status_code=status.HTTP_200_OK,
    summary="AI-initiated task status update [requires UPDATE_TASK permission]",
    description=(
        "Used by automation (including AI) to apply a status update. "
        "Caller must authenticate as a normal user (e.g., service account) and "
        "must have UPDATE_TASK permission in the target team. "
        "Atomically updates task status and writes an AI_MODEL decision record."
    ),
)
async def agent_transition(
    payload: AgentTransitionRequest,
    _: None = Depends(require_permission("UPDATE_TASK")),
    team_id: int = Query(..., description="Team ID for permission scope"),
    db: Prisma = Depends(get_db),
) -> TaskSchema:
    svc = TaskService(db)
    task = await svc.apply_agent_decision(
        task_id=payload.task_id,
        new_status_id=payload.new_status_id,
        action_taken=payload.action_taken,
        reason=payload.reason,
        confidence_score=payload.confidence_score,
        input_signals=payload.input_signals,
    )
    return TaskSchema.model_validate(task)

@router.get(
    "/events",
    status_code=status.HTTP_200_OK,
    summary="List recent system events [requires READ_TASK permission]",
)
async def list_events(
    team_id: int = Query(..., description="Team ID for permission scope"),
    limit: int = Query(default=100, ge=1, le=500),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> list[dict]:
    cache_key = f"events_list_{team_id}_{limit}"
    cached = task_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"Cache HIT: {cache_key}")
        return cached
    
    repo = EventRepository(db)
    items = await repo.list_recent_events(limit=limit)
    result = [
        {
            "id": e.id,
            "event_type": e.eventType,
            "source": e.source,
            "reference_id": e.referenceId,
            "metadata": e.payload,
            "processed": e.processed,
            "correlation_id": e.correlationId,
            "created_at": e.ingestionTimestamp,
            "timestamp": e.eventTimestamp,
        }
        for e in items
    ]
    task_cache.set(cache_key, result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — BLOCKERS (RBAC-protected)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/blockers",
    response_model=list[SystemBlockerSchema],
    summary="List active blockers for a team [requires MANAGE_TEAM permission]",
    tags=["blockers"],
)
async def list_blockers(
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db),
) -> list[SystemBlockerSchema]:
    svc = BlockerService(db)
    items = await svc.list_active_blockers(team_id)
    return [SystemBlockerSchema.model_validate(i) for i in items]


@router.post(
    "/blockers/{blocker_id}/resolve",
    response_model=SystemBlockerSchema,
    summary="Mark a blocker as resolved [requires MANAGE_TEAM permission]",
    tags=["blockers"],
)
async def resolve_blocker(
    blocker_id: int = Path(...),
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db),
) -> SystemBlockerSchema:
    svc = BlockerService(db)
    result = await svc.resolve_blocker(blocker_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Blocker not found")
    return SystemBlockerSchema.model_validate(result)


@router.get(
    "/decisions",
    response_model=list[AgentDecisionSchema],
    summary="List all AI decisions for a team [requires READ_TASK permission]",
)
async def get_team_decisions(
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> list[AgentDecisionSchema]:
    decisions = await db.agentdecision.find_many(
        where={
            "task": {
                "is": {
                    "teamId": team_id
                }
            }
        },
        include={"task": True},
        order={"createdAt": "desc"},
        take=50
    )
    
    results = []
    for d in decisions:
        schema = AgentDecisionSchema.model_validate(d)
        if d.task:
            schema.taskTitle = d.task.title
        results.append(schema)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — TASK INSTANCE ENDPOINTS (dynamic {task_id})
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{task_id}",
    response_model=TaskSchema,
    summary="Get a task by ID [requires READ_TASK permission]",
)
async def get_task(
    task_id: int = Path(...),
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> TaskSchema:
    svc = TaskService(db)
    task = await svc.require_task(task_id)
    return TaskSchema.model_validate(task)


@router.patch(
    "/{task_id}",
    response_model=TaskSchema,
    summary="Update a task [requires UPDATE_TASK permission]",
)
async def update_task(
    task_id: int = Path(...),
    payload: TaskUpdateRequest = ...,
    team_id: int = Query(..., description="Team ID for permission scope"),
    x_user_id: int = Header(..., alias="X-User-ID"),
    _: None = Depends(require_permission("UPDATE_TASK")),
    db: Prisma = Depends(get_db),
) -> TaskSchema:
    svc = TaskService(db)
    updates = payload.model_dump(exclude_unset=True)
    
    task = await svc.update_task(
        task_id=task_id,
        title=updates.get("title", UNSET),
        description=updates.get("description", UNSET),
        sprint_id=updates.get("sprint_id", UNSET),
        current_stage_id=updates.get("current_stage_id", UNSET),
        assignee_id=updates.get("assignee_id", UNSET),
        priority=updates.get("priority", UNSET),
        order=updates.get("order", UNSET),
        updater_id=x_user_id
    )
    return TaskSchema.model_validate(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task [requires DELETE_TASK permission]",
)
async def delete_task(
    task_id: int = Path(...),
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("DELETE_TASK")),
    db: Prisma = Depends(get_db),
) -> None:
    svc = TaskService(db)
    await svc.delete_task(task_id)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — STATUS TRANSITIONS
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{task_id}/transition",
    response_model=TaskSchema,
    status_code=status.HTTP_200_OK,
    summary="Manual status transition [requires UPDATE_TASK permission]",
    description=(
        "User-initiated status override (e.g., drag-and-drop on Kanban board). "
        "Records a RULE_ENGINE decision in the audit log. "
        "Use `/tasks/agent/transition` for AI agent-initiated transitions."
    ),
)
async def manual_transition(
    task_id: int = Path(...),
    payload: TaskStatusTransitionRequest = ...,
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("UPDATE_TASK")),
    db: Prisma = Depends(get_db),
) -> TaskSchema:
    svc = TaskService(db)
    task = await svc.manual_status_override(
        task_id=task_id,
        new_status_id=payload.new_status_id,
        reason=payload.reason,
    )
    return TaskSchema.model_validate(task)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — AI DECISIONS + FEEDBACK
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{task_id}/decisions",
    summary="List AI decisions for a task [requires READ_TASK permission]",
)
async def get_decisions(
    task_id: int = Path(...),
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> list[dict]:
    svc = TaskService(db)
    decisions = await svc.get_decisions_for_task(task_id)
    result = []
    for d in decisions:
        task = getattr(d, "task", None)
        from_stage = getattr(d, "fromStage", None)
        to_stage = getattr(d, "toStage", None)
        result.append({
            "id": d.id,
            "task_id": d.taskId,
            "task_title": task.title if task else None,
            "from_stage_id": d.fromStageId,
            "from_stage_name": from_stage.name if from_stage else None,
            "to_stage_id": d.toStageId,
            "to_stage_name": to_stage.name if to_stage else None,
            "confidence_score": d.confidenceScore,
            "reasoning": d.reasoning,
            "status": d.status,
            "decision_source": d.decisionSource,
            "triggered_by_event": getattr(d, "triggeredByEvent", None),
            "correlation_id": getattr(d, "correlationId", None),
            "input_signals": d.inputSignals,
            "created_at": d.createdAt,
        })
    return result


@router.get(
    "/{task_id}/activity",
    status_code=status.HTTP_200_OK,
    summary="List task activity feed [requires READ_TASK permission]",
)
async def get_task_activity(
    task_id: int = Path(...),
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> list[dict]:
    repo = ActivityRepository(db)
    items = await repo.list_activities_for_task(task_id, limit=100)
    return [
        {
            "id": i.id,
            "task_id": i.taskId,
            "activity_type": i.activityType,
            "reference_id": i.referenceId,
            "metadata": i.metadata,
            "created_at": i.createdAt,
        }
        for i in items
    ]


@router.post(
    "/{task_id}/decisions/{decision_id}/resolve",
    response_model=TaskSchema,
    status_code=status.HTTP_200_OK,
    summary="Manually resolve an AI decision [requires UPDATE_TASK permission]",
)
async def resolve_decision(
    task_id: int = Path(...),
    decision_id: int = Path(...),
    payload: TaskStatusTransitionRequest = ...,
    team_id: int = Query(..., description="Team ID for permission scope"),
    x_user_id: int = Header(..., alias="X-User-ID"),
    _: None = Depends(require_permission("UPDATE_TASK")),
    db: Prisma = Depends(get_db),
) -> TaskSchema:
    svc = TaskService(db)
    task = await svc.manual_resolve_decision(
        task_id=task_id,
        decision_id=decision_id,
        new_status_id=payload.new_stage_id,  # TaskStatusTransitionRequest uses new_stage_id (aliased to new_status_id)
        user_id=x_user_id
    )
    return TaskSchema.model_validate(task)



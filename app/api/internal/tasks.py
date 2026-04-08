"""
VSM Backend – Internal Tasks API

RBAC-enforced task management endpoints.
Every user-facing endpoint requires the caller to have the matching Permission
for the team they are operating in (via X-User-ID header + team_id query param).

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
from app.schemas.task_schemas import (
    TaskSchema,
    TaskCreateRequest,
    TaskUpdateRequest,
    TaskStatusTransitionRequest,
    AgentDecisionSchema,
    DecisionFeedbackRequest,
    NLPFeedbackRequest,
    UnlinkedActivityResponse,
    LinkActivityRequest,
    AgentTransitionRequest,
    AgentLinkRequest,
)
from app.models.enums import UnlinkedActivityStatus
from app.models.enums import MappingMethod

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
    svc = TaskService(db)
    tasks = await svc.list_tasks(team_id, limit, offset)
    return [TaskSchema.model_validate(t) for t in tasks]


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


@router.post(
    "/agent/link",
    status_code=status.HTTP_200_OK,
    summary="AI-initiated task linking [requires UPDATE_TASK permission]",
    description=(
        "Used by the AI agent when discovery mode identifies a task for unlinked events. "
        "Atomically creates TaskActivity records and updates UnlinkedActivity status."
    ),
)
async def agent_link(
    payload: AgentLinkRequest,
    _: None = Depends(require_permission("UPDATE_TASK")),
    team_id: int = Query(..., description="Team ID for permission scope"),
    db: Prisma = Depends(get_db),
) -> dict:
    svc = TaskService(db)
    result = await svc.apply_agent_link(
        task_id=payload.task_id,
        event_log_ids=payload.event_log_ids,
        confidence_score=payload.confidence_score,
        reason=payload.reason,
        input_signals=payload.input_signals,
    )
    return result


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
    repo = EventRepository(db)
    items = await repo.list_recent_events(limit=limit)
    return [
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


@router.get(
    "/unlinked",
    response_model=list[UnlinkedActivityResponse],
    summary="List unlinked activities [requires MANAGE_TEAM permission]",
    tags=["activity"],
)
async def list_unlinked(
    team_id: int = Query(..., description="Team ID for permission scope"),
    limit: int = Query(default=50, le=200),
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db),
) -> list[UnlinkedActivityResponse]:
    repo = ActivityRepository(db)
    items = await repo.list_unresolved(limit)
    return [UnlinkedActivityResponse.model_validate(i) for i in items]


@router.post(
    "/unlinked/{activity_id}/link",
    status_code=status.HTTP_200_OK,
    summary="Manually link an unlinked activity [requires MANAGE_TEAM permission]",
    tags=["activity"],
)
async def link_activity(
    activity_id: int = Path(...),
    payload: LinkActivityRequest = ...,
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db),
) -> dict:
    repo = ActivityRepository(db)
    await repo.update_unlinked_suggestion(
        ua_id=activity_id,
        suggested_task_id=payload.task_id,
        confidence_score=1.0,
        status=UnlinkedActivityStatus.USER_CONFIRMED,
    )
    await repo.record_mapping(
        activity_id=activity_id,
        task_id=payload.task_id,
        mapping_method=MappingMethod(payload.mapping_method),
        confidence_score=1.0,
    )
    return {"status": "linked", "task_id": payload.task_id}


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
    response_model=list[AgentDecisionSchema],
    summary="List AI decisions for a task [requires READ_TASK permission]",
)
async def get_decisions(
    task_id: int = Path(...),
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> list[AgentDecisionSchema]:
    svc = TaskService(db)
    decisions = await svc.get_decisions_for_task(task_id)
    return [AgentDecisionSchema.model_validate(d) for d in decisions]


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
    "/{task_id}/decisions/{decision_id}/feedback",
    status_code=status.HTTP_200_OK,
    summary="Submit feedback on an AI decision [requires READ_TASK permission]",
)
async def submit_decision_feedback(
    decision_id: int = Path(...),
    task_id: int = Path(...),
    payload: DecisionFeedbackRequest = ...,
    user_id: int = Query(..., description="User submitting feedback"),
    team_id: int = Query(..., description="Team ID for permission scope"),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> dict:
    svc = TaskService(db)
    await svc.record_decision_feedback(decision_id, user_id, payload.feedback)
    return {"status": "recorded", "feedback": payload.feedback}


@router.post(
    "/{task_id}/decisions/{decision_id}/approve",
    status_code=status.HTTP_200_OK,
    summary="Approve AI decision [requires READ_TASK permission]",
)
async def approve_decision(
    task_id: int = Path(...),
    decision_id: int = Path(...),
    team_id: int = Query(..., description="Team ID for permission scope"),
    x_user_id: int = Header(..., alias="X-User-ID", description="Authenticated user ID"),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> dict:
    svc = TaskService(db)
    await svc.record_decision_feedback(decision_id, x_user_id, "ACCEPTED")
    return {"status": "recorded", "feedback": "ACCEPTED"}


@router.post(
    "/{task_id}/decisions/{decision_id}/reject",
    status_code=status.HTTP_200_OK,
    summary="Reject AI decision [requires READ_TASK permission]",
)
async def reject_decision(
    task_id: int = Path(...),
    decision_id: int = Path(...),
    team_id: int = Query(..., description="Team ID for permission scope"),
    x_user_id: int = Header(..., alias="X-User-ID", description="Authenticated user ID"),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> dict:
    svc = TaskService(db)
    await svc.record_decision_feedback(decision_id, x_user_id, "REJECTED")
    return {"status": "recorded", "feedback": "REJECTED"}



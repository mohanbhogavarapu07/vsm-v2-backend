"""
VSM Backend – Sprints API

Full Jira-style sprint lifecycle:
  POST   /teams/{team_id}/sprints/                       → create sprint
  GET    /teams/{team_id}/sprints/                       → list sprints (with task counts)
  PATCH  /teams/{team_id}/sprints/{sprint_id}            → update name/goal/dates
  POST   /teams/{team_id}/sprints/{sprint_id}/start      → start sprint (PLANNED → ACTIVE)
  POST   /teams/{team_id}/sprints/{sprint_id}/complete   → complete sprint (ACTIVE → COMPLETED)
  GET    /teams/{team_id}/sprints/{sprint_id}/tasks      → list tasks in sprint
  POST   /teams/{team_id}/sprints/{sprint_id}/tasks/{task_id}   → assign task to sprint
  DELETE /teams/{team_id}/sprints/{sprint_id}/tasks/{task_id}   → remove task from sprint
  GET    /teams/{team_id}/backlog                        → list unassigned tasks
"""

import logging

from fastapi import APIRouter, Body, Depends, Path, Query, status
from prisma import Prisma

from app.database import get_db
from app.services.sprint_service import SprintService
from app.utils.permissions import require_permission
from app.schemas.sprint_schemas import (
    SprintCreateRequest,
    SprintUpdateRequest,
    SprintStartRequest,
    SprintCompleteRequest,
    SprintSchema,
    SprintWithStatsSchema,
    compute_task_counts,
)
from app.schemas.task_schemas import TaskSchema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams/{team_id}", tags=["sprints"])


# ─────────────────────────────────────────────────────────────────────────────
# SPRINT CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/sprints/",
    response_model=SprintSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new sprint [requires CREATE_TASK permission]",
)
async def create_sprint(
    team_id: int = Path(...),
    payload: SprintCreateRequest = Body(...),
    _: None = Depends(require_permission("CREATE_TASK")),
    db: Prisma = Depends(get_db),
) -> SprintSchema:
    svc = SprintService(db)
    sprint = await svc.create_sprint(
        team_id=team_id,
        name=payload.name,
        goal=payload.goal,
        start_date=payload.startDate,
        end_date=payload.endDate,
    )
    return SprintSchema.model_validate(sprint)


@router.get(
    "/sprints/",
    response_model=list[SprintWithStatsSchema],
    summary="List sprints for a team with task count stats [requires READ_TASK permission]",
)
async def list_sprints(
    team_id: int = Path(...),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> list[SprintWithStatsSchema]:
    svc = SprintService(db)
    sprints = await svc.list_sprints(team_id)
    result = []
    for s in sprints:
        schema = SprintWithStatsSchema.model_validate(s)
        schema.task_counts = compute_task_counts(s)
        result.append(schema)
    return result


@router.patch(
    "/sprints/{sprint_id}",
    response_model=SprintSchema,
    summary="Update sprint name/goal/dates [requires UPDATE_TASK permission]",
)
async def update_sprint(
    sprint_id: int = Path(...),
    team_id: int = Path(...),
    payload: SprintUpdateRequest = Body(...),
    _: None = Depends(require_permission("UPDATE_TASK")),
    db: Prisma = Depends(get_db),
) -> SprintSchema:
    svc = SprintService(db)
    sprint = await svc.update_sprint(
        sprint_id=sprint_id,
        team_id=team_id,
        name=payload.name,
        goal=payload.goal,
        startDate=payload.startDate,
        endDate=payload.endDate,
    )
    return SprintSchema.model_validate(sprint)


# ─────────────────────────────────────────────────────────────────────────────
# SPRINT LIFECYCLE
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/sprints/{sprint_id}/start",
    response_model=SprintWithStatsSchema,
    status_code=status.HTTP_200_OK,
    summary="Start a sprint (PLANNED → ACTIVE) [requires UPDATE_TASK permission]",
    description=(
        "Transitions a PLANNED sprint to ACTIVE. "
        "Only one sprint may be active per team at a time. "
        "Sets startDate to now() if not supplied. "
        "Optionally accepts goal, startDate, endDate to set/update before activating."
    ),
)
async def start_sprint(
    sprint_id: int = Path(...),
    team_id: int = Path(...),
    payload: SprintStartRequest = Body(default=SprintStartRequest()),
    _: None = Depends(require_permission("UPDATE_TASK")),
    db: Prisma = Depends(get_db),
) -> SprintWithStatsSchema:
    svc = SprintService(db)
    sprint = await svc.start_sprint(
        sprint_id=sprint_id,
        team_id=team_id,
        goal=payload.goal,
        start_date=payload.startDate,
        end_date=payload.endDate,
    )
    schema = SprintWithStatsSchema.model_validate(sprint)
    schema.task_counts = compute_task_counts(sprint)
    return schema


@router.post(
    "/sprints/{sprint_id}/complete",
    response_model=SprintWithStatsSchema,
    status_code=status.HTTP_200_OK,
    summary="Complete a sprint (ACTIVE → COMPLETED) [requires UPDATE_TASK permission]",
    description=(
        "Marks an ACTIVE sprint as COMPLETED. "
        "Incomplete tasks (category != DONE) are moved to rollover_sprint_id "
        "if provided, otherwise sent back to backlog (sprintId=null)."
    ),
)
async def complete_sprint(
    sprint_id: int = Path(...),
    team_id: int = Path(...),
    payload: SprintCompleteRequest = Body(default=SprintCompleteRequest()),
    _: None = Depends(require_permission("UPDATE_TASK")),
    db: Prisma = Depends(get_db),
) -> SprintWithStatsSchema:
    svc = SprintService(db)
    sprint = await svc.complete_sprint(
        sprint_id=sprint_id,
        team_id=team_id,
        rollover_sprint_id=payload.rollover_sprint_id,
    )
    schema = SprintWithStatsSchema.model_validate(sprint)
    schema.task_counts = compute_task_counts(sprint)
    return schema


# ─────────────────────────────────────────────────────────────────────────────
# SPRINT TASKS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/sprints/{sprint_id}/tasks",
    response_model=list[TaskSchema],
    summary="List tasks in a sprint [requires READ_TASK permission]",
)
async def list_sprint_tasks(
    sprint_id: int = Path(...),
    team_id: int = Path(...),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> list[TaskSchema]:
    svc = SprintService(db)
    tasks = await svc.get_sprint_tasks(sprint_id, team_id)
    return [TaskSchema.model_validate(t) for t in tasks]


@router.post(
    "/sprints/{sprint_id}/tasks/{task_id}",
    response_model=TaskSchema,
    status_code=status.HTTP_200_OK,
    summary="Assign a task to a sprint [requires UPDATE_TASK permission]",
)
async def assign_task_to_sprint(
    sprint_id: int = Path(...),
    task_id: int = Path(...),
    team_id: int = Path(...),
    _: None = Depends(require_permission("UPDATE_TASK")),
    db: Prisma = Depends(get_db),
) -> TaskSchema:
    svc = SprintService(db)
    task = await svc.assign_task_to_sprint(task_id, sprint_id, team_id)
    return TaskSchema.model_validate(task)


@router.delete(
    "/sprints/{sprint_id}/tasks/{task_id}",
    response_model=TaskSchema,
    status_code=status.HTTP_200_OK,
    summary="Remove a task from a sprint (send to backlog) [requires UPDATE_TASK permission]",
)
async def remove_task_from_sprint(
    sprint_id: int = Path(...),
    task_id: int = Path(...),
    team_id: int = Path(...),
    _: None = Depends(require_permission("UPDATE_TASK")),
    db: Prisma = Depends(get_db),
) -> TaskSchema:
    svc = SprintService(db)
    task = await svc.unassign_task_from_sprint(task_id, team_id)
    return TaskSchema.model_validate(task)


# ─────────────────────────────────────────────────────────────────────────────
# BACKLOG
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/backlog",
    response_model=list[TaskSchema],
    summary="List unassigned backlog tasks for a team [requires READ_TASK permission]",
)
async def list_backlog_tasks(
    team_id: int = Path(...),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> list[TaskSchema]:
    svc = SprintService(db)
    tasks = await svc.get_backlog_tasks(team_id, limit, offset)
    return [TaskSchema.model_validate(t) for t in tasks]

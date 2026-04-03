from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.enums import SprintStatus


# ─────────────────────────────────────────────────────────────────────────────
# BASE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class SprintBase(BaseModel):
    name: str
    goal: Optional[str] = None
    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None
    status: SprintStatus = SprintStatus.PLANNED


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class SprintCreateRequest(SprintBase):
    pass  # team_id taken from URL path


class SprintUpdateRequest(BaseModel):
    """Generic update — only name/goal/dates. Use lifecycle endpoints for status."""
    name: Optional[str] = None
    goal: Optional[str] = None
    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None


class SprintStartRequest(BaseModel):
    """Payload for the dedicated start-sprint action."""
    goal: Optional[str] = None
    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None


class SprintCompleteRequest(BaseModel):
    """
    Payload for the dedicated complete-sprint action.
    rollover_sprint_id: move incomplete tasks here (null = back to backlog).
    """
    rollover_sprint_id: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# TASK COUNTS (for Jira-style stat badges)
# ─────────────────────────────────────────────────────────────────────────────

class SprintTaskCounts(BaseModel):
    total: int = 0
    todo: int = 0       # BACKLOG category
    in_progress: int = 0  # ACTIVE / REVIEW / VALIDATION / BLOCKED
    done: int = 0       # DONE category


# ─────────────────────────────────────────────────────────────────────────────
# RESPONSE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class SprintSchema(BaseModel):
    id: int
    teamId: int
    name: str
    goal: Optional[str] = None
    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None
    status: SprintStatus
    createdAt: datetime
    updatedAt: datetime

    model_config = ConfigDict(from_attributes=True)


class SprintWithStatsSchema(SprintSchema):
    """Sprint schema enriched with task count breakdown for badge display."""
    task_counts: SprintTaskCounts = SprintTaskCounts()

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────────────────────

def compute_task_counts(sprint_obj) -> SprintTaskCounts:
    """Derive todo/in-progress/done counts from an included tasks list."""
    counts = SprintTaskCounts()
    tasks = getattr(sprint_obj, "tasks", None) or []
    counts.total = len(tasks)
    for task in tasks:
        cat = (
            task.currentStatus.category
            if task.currentStatus
            else "BACKLOG"
        )
        if cat == "DONE":
            counts.done += 1
        elif cat == "BACKLOG":
            counts.todo += 1
        else:
            counts.in_progress += 1
    return counts

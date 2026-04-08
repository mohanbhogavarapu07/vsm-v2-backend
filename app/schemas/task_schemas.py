"""
VSM Backend – Task Pydantic Schemas

Request/response models for internal task management endpoints.
All field names align exactly with the Prisma schema.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.rbac_schemas import TaskStatusCategory


# ── Workflow Stage ────────────────────────────────────────────────────────────

class WorkflowStageSchema(BaseModel):
    id: int
    projectId: int
    name: str
    systemCategory: TaskStatusCategory
    positionOrder: int
    isBlocking: bool
    createdAt: datetime
    updatedAt: datetime
    model_config = ConfigDict(from_attributes=True)


# ── Task ──────────────────────────────────────────────────────────────────────

class TaskSchema(BaseModel):
    id: int
    teamId: int
    title: str
    description: str | None = None
    sprint_id: int | None = Field(None, validation_alias="sprintId")
    currentStageId: int | None = None
    status_id: int | None = Field(None, validation_alias="currentStageId")
    current_status_id: int | None = Field(None, validation_alias="currentStageId")
    assignee_id: int | None = Field(None, validation_alias="assigneeId")
    priority: str | None = None
    order: float | None = None
    createdAt: datetime
    updatedAt: datetime
    currentStage: WorkflowStageSchema | None = None
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TaskCreateRequest(BaseModel):
    team_id: int = Field(..., description="Team this task belongs to")
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    sprint_id: int | None = None
    current_stage_id: int | None = Field(None, alias="current_status_id")
    assignee_id: int | None = None
    priority: str | None = None


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    sprint_id: int | None = None
    current_stage_id: int | None = Field(None, alias="current_status_id")
    assignee_id: int | None = None
    priority: str | None = None
    order: float | None = None


# ── Status Transition ─────────────────────────────────────────────────────────

class TaskStatusTransitionRequest(BaseModel):
    """Manual status override — bypasses AI decision engine."""
    new_stage_id: int = Field(..., alias="new_status_id")
    reason: str | None = None


# ── AI Decisions ──────────────────────────────────────────────────────────────

class AgentDecisionSchema(BaseModel):
    id: int
    taskId: int
    actionTaken: str
    reason: str
    confidenceScore: float
    inputSignals: dict[str, Any]
    decisionSource: str
    createdAt: datetime
    model_config = ConfigDict(from_attributes=True)


class DecisionFeedbackRequest(BaseModel):
    feedback: str = Field(..., pattern="^(ACCEPTED|REJECTED)$")


# ── NLP Feedback ──────────────────────────────────────────────────────────────

class NLPFeedbackRequest(BaseModel):
    feedback: str = Field(..., pattern="^(ACCEPTED|REJECTED)$")
    corrected_intent: str | None = Field(
        None, pattern="^(BLOCKER|PROGRESS|NONE)$"
    )


# ── Unlinked Activity ─────────────────────────────────────────────────────────

class UnlinkedActivityResponse(BaseModel):
    id: int
    activity_type: str
    branch_name: str | None = None
    commit_message: str | None = None
    suggested_task_id: int | None = None
    confidence_score: float | None = None
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class LinkActivityRequest(BaseModel):
    task_id: int
    mapping_method: str = Field(
        default="MANUAL",
        pattern="^(MANUAL|AI_AUTO|BRANCH_PATTERN)$",
    )


# ── Agent Internal Transition (no user RBAC — system process only) ────────────

class AgentLinkRequest(BaseModel):
    """
    Used by the AI agent to link unlinked events to a discovered task.
    """
    task_id: int = Field(..., description="Task to link to")
    event_log_ids: list[int] = Field(..., description="Events to link")
    confidence_score: float
    reason: str
    input_signals: dict[str, Any] = Field(default_factory=dict)


class AgentTransitionRequest(BaseModel):
    """
    Used by the AI agent to update task status.
    """
    task_id: int = Field(..., description="Task to transition")
    new_stage_id: int = Field(..., alias="new_status_id")
    action_taken: str
    reason: str
    confidence_score: float
    input_signals: dict[str, Any] = Field(default_factory=dict)

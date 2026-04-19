"""
VSM Backend – Task Pydantic Schemas

Request/response models for internal task management endpoints.
All field names align exactly with the Prisma schema.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

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
    
    @computed_field
    def status_name(self) -> str | None:
        return self.currentStage.name if self.currentStage else None

    @computed_field
    def status_category(self) -> str | None:
        return getattr(self.currentStage.systemCategory, "value", str(self.currentStage.systemCategory)) if self.currentStage else None

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
    taskTitle: str | None = None
    fromStageId: int | None = None
    toStageId: int | None = None
    confidenceScore: float
    reasoning: str
    correlationId: str | None = None
    status: str
    triggeredByEvent: str | None = None
    inputSignals: Any
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


# ── System Blocker ───────────────────────────────────────────────────────────

class SystemBlockerSchema(BaseModel):
    id: int
    teamId: int
    taskId: int | None = None
    title: str
    description: str
    type: str
    isResolved: bool
    metadata: Any = Field(default_factory=dict)
    createdAt: datetime
    updatedAt: datetime
    model_config = ConfigDict(from_attributes=True)


# ── Agent Internal Transition (no user RBAC — system process only) ────────────

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

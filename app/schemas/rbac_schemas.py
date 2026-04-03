"""
VSM Backend – RBAC + Workflow Pydantic Schemas
"""
from pydantic import BaseModel, ConfigDict, field_validator
from typing import List, Optional
from enum import Enum
from datetime import datetime


# ── Project ───────────────────────────────────────────────────────────────────

class ProjectCreateRequest(BaseModel):
    name: str

class ProjectResponse(BaseModel):
    id: int
    name: str
    createdAt: datetime
    updatedAt: datetime
    model_config = ConfigDict(from_attributes=True)


# ── Team ──────────────────────────────────────────────────────────────────────

class TeamCreateRequest(BaseModel):
    name: str

class TeamResponse(BaseModel):
    id: int
    projectId: int
    name: str
    createdAt: datetime
    updatedAt: datetime
    model_config = ConfigDict(from_attributes=True)


# ── Roles ─────────────────────────────────────────────────────────────────────

class RoleCreateRequest(BaseModel):
    name: str
    permission_codes: List[str]

class RoleUpdateRequest(BaseModel):
    name: Optional[str] = None
    permission_codes: Optional[List[str]] = None

class RoleResponse(BaseModel):
    id: int
    teamId: int
    name: str
    permission_codes: List[str]
    createdAt: datetime
    updatedAt: datetime
    model_config = ConfigDict(from_attributes=True)


# ── Invitations / Members ─────────────────────────────────────────────────────

class UserInviteRequest(BaseModel):
    email: str
    name: str
    role_id: int

class InvitationAcceptRequest(BaseModel):
    invitation_id: int
    name: Optional[str] = None

class MemberRoleUpdateRequest(BaseModel):
    role_id: int

class TeamMemberDetailResponse(BaseModel):
    id: int
    team_id: int
    user_id: int
    role_id: int
    email: Optional[str]
    name: Optional[str]
    role_name: Optional[str]
    permission_codes: List[str]
    created_at: datetime


# ── Custom Workflow: Task Statuses ────────────────────────────────────────────

class TaskStatusCategory(str, Enum):
    BACKLOG    = "BACKLOG"
    ACTIVE     = "ACTIVE"
    REVIEW     = "REVIEW"
    VALIDATION = "VALIDATION"
    DONE       = "DONE"
    BLOCKED    = "BLOCKED"

class TaskStatusCreateRequest(BaseModel):
    name: str
    category: TaskStatusCategory
    stage_order: int = 0
    is_terminal: bool = False

class TaskStatusUpdateRequest(BaseModel):
    name: Optional[str] = None
    stage_order: Optional[int] = None
    is_terminal: Optional[bool] = None

class TaskStatusResponse(BaseModel):
    id: int
    teamId: int
    name: str
    category: str
    stageOrder: int
    isTerminal: bool
    createdAt: datetime
    updatedAt: datetime
    model_config = ConfigDict(from_attributes=True)


# ── Custom Workflow: Transitions ──────────────────────────────────────────────

class WorkflowTransitionCreateRequest(BaseModel):
    from_status_id: int
    to_status_id: int
    requires_manual_approval: bool = False

class WorkflowTransitionResponse(BaseModel):
    id: int
    teamId: int
    fromStatusId: int
    toStatusId: int
    requiresManualApproval: bool
    from_status_name: Optional[str] = None
    to_status_name: Optional[str] = None
    createdAt: datetime
    model_config = ConfigDict(from_attributes=True)

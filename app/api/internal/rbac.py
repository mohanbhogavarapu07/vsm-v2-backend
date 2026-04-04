"""
VSM Backend – RBAC API Router

Complete Jira-like REST API for:
  1. Projects
  2. Teams
  3. Dynamic Roles + Permissions  ← MANDATORY before inviting users
  4. User Invitations with role enforcement
  5. Custom Workflow Board (TaskStatus columns + Transitions)
  6. Permission self-check (/me)

Strict Order Flow enforced in service layer:
  Project → Team → Roles → Invite Users
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from prisma import Prisma

from app.database import get_db
from app.services.rbac_service import RBACService
from app.utils.permissions import require_permission, require_any_permission, get_current_user_permissions
from app.schemas.rbac_schemas import (
    ProjectCreateRequest, ProjectResponse,
    TeamCreateRequest, TeamUpdateRequest, TeamResponse,
    RoleCreateRequest, RoleUpdateRequest, RoleResponse,
    UserInviteRequest, InvitationAcceptRequest, MemberRoleUpdateRequest, TeamMemberDetailResponse,
    TaskStatusCreateRequest, TaskStatusUpdateRequest, TaskStatusResponse,
    WorkflowTransitionCreateRequest, WorkflowTransitionResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rbac"])


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — PROJECTS
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Step 1] Create a project",
)
async def create_project(
    payload: ProjectCreateRequest,
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.create_project(payload.name)


@router.get(
    "/projects",
    response_model=list[ProjectResponse],
    summary="List all projects",
)
async def list_projects(
    x_user_id: Optional[int] = Header(None, alias="X-User-ID"),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.list_projects(user_id=x_user_id)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project by ID",
)
async def get_project(
    project_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.get_project(project_id)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — TEAMS (scoped under a project)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/teams",
    response_model=TeamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Step 2] Create a team inside a project",
)
async def create_team(
    project_id: int = Path(...),
    payload: TeamCreateRequest = ...,
    x_user_id: int = Header(..., alias="X-User-ID", description="Authenticated user ID"),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.create_team(project_id, payload.name, creator_user_id=x_user_id, copy_from_team_id=payload.copy_from_team_id)


@router.get(
    "/projects/{project_id}/teams",
    response_model=list[TeamResponse],
    summary="List all teams in a project",
)
async def list_teams(
    project_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.list_teams(project_id)


@router.get(
    "/teams/{team_id}",
    response_model=TeamResponse,
    summary="Get team details",
)
async def get_team(
    team_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.get_team(team_id)


@router.patch(
    "/teams/{team_id}",
    response_model=TeamResponse,
    summary="Update team details (e.g. rename)",
)
async def update_team(
    team_id: int = Path(...),
    payload: TeamUpdateRequest = ...,
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.update_team(team_id, payload.name)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — ROLES + PERMISSIONS (MANDATORY before inviting users)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/teams/{team_id}/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Step 3 - MANDATORY] Create a custom role with permissions [requires MANAGE_ROLES]",
    description=(
        "Scrum must define roles before inviting any users. "
        "Role names are 100% user-defined (e.g. 'QA', 'Intern', 'Tech Lead'). "
        "Permissions are selected from the predefined `Permission` enum."
    ),
)
async def create_role(
    team_id: int = Path(...),
    payload: RoleCreateRequest = ...,
    _: None = Depends(require_permission("MANAGE_ROLES")),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    role = await svc.create_role(team_id, payload.name, payload.permission_codes)
    codes = await svc.repo.get_role_permission_codes(role.id)
    return {
        "id": role.id,
        "teamId": role.teamId,
        "name": role.name,
        "permission_codes": codes,
        "createdAt": role.createdAt,
        "updatedAt": role.updatedAt,
    }


@router.get(
    "/teams/{team_id}/roles",
    response_model=list[RoleResponse],
    summary="List all roles defined for a team (used for invitation dropdown)",
)
async def list_roles(
    team_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    roles = await svc.get_team_roles(team_id)
    role_ids = [r.id for r in roles]
    perms_by_role: dict[int, list[str]] = {}
    for rid in role_ids:
        perms_by_role[int(rid)] = await svc.repo.get_role_permission_codes(rid)
    return [
        {
            "id": r.id,
            "teamId": r.teamId,
            "name": r.name,
            "permission_codes": perms_by_role.get(int(r.id), []),
            "createdAt": r.createdAt,
            "updatedAt": r.updatedAt,
        }
        for r in roles
    ]


@router.patch(
    "/teams/{team_id}/roles/{role_id}",
    response_model=RoleResponse,
    summary="Update a role's name or permissions [requires MANAGE_ROLES]",
)
async def update_role(
    team_id: int = Path(...),
    role_id: int = Path(...),
    payload: RoleUpdateRequest = ...,
    _: None = Depends(require_permission("MANAGE_ROLES")),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    role = await svc.update_role(team_id, role_id, payload.name, payload.permission_codes)
    codes = await svc.repo.get_role_permission_codes(role.id)
    return {
        "id": role.id,
        "teamId": role.teamId,
        "name": role.name,
        "permission_codes": codes,
        "createdAt": role.createdAt,
        "updatedAt": role.updatedAt,
    }


@router.delete(
    "/teams/{team_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a role (only if no members are assigned) [requires MANAGE_ROLES]",
)
async def delete_role(
    team_id: int = Path(...),
    role_id: int = Path(...),
    _: None = Depends(require_permission("MANAGE_ROLES")),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    await svc.delete_role(team_id, role_id)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — CUSTOM WORKFLOW BOARD (Define board columns + transitions)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/teams/{team_id}/workflow/statuses",
    response_model=TaskStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Step 4] Create a custom board column (e.g. 'To Do', 'In Review')",
    description=(
        "Define the Kanban board columns for this team. Each status has a "
        "`category` that the AI uses for abstract reasoning (BACKLOG/ACTIVE/REVIEW/DONE/BLOCKED). "
        "`stage_order` controls left-to-right order on the board."
    ),
)
async def create_task_status(
    team_id: int = Path(...),
    payload: TaskStatusCreateRequest = ...,
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.create_task_status(
        team_id=team_id,
        name=payload.name,
        category=payload.category.value,
        stage_order=payload.stage_order,
        is_terminal=payload.is_terminal,
    )


@router.get(
    "/teams/{team_id}/workflow/statuses",
    response_model=list[TaskStatusResponse],
    summary="Get all board columns for a team (ordered by stage)",
)
async def list_task_statuses(
    team_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.list_task_statuses(team_id)


@router.patch(
    "/teams/{team_id}/workflow/statuses/{status_id}",
    response_model=TaskStatusResponse,
    summary="Update a board column",
)
async def update_task_status(
    team_id: int = Path(...),
    status_id: int = Path(...),
    payload: TaskStatusUpdateRequest = ...,
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.update_task_status(
        team_id, status_id, payload.name, payload.stage_order, payload.is_terminal
    )


@router.delete(
    "/teams/{team_id}/workflow/statuses/{status_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a board column",
)
async def delete_task_status(
    team_id: int = Path(...),
    status_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    await svc.delete_task_status(team_id, status_id)


@router.post(
    "/teams/{team_id}/workflow/transitions",
    response_model=WorkflowTransitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Define allowed status movement (e.g. 'To Do' → 'In Progress')",
)
async def create_workflow_transition(
    team_id: int = Path(...),
    payload: WorkflowTransitionCreateRequest = ...,
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    result = await svc.create_workflow_transition(
        team_id=team_id,
        from_status_id=payload.from_status_id,
        to_status_id=payload.to_status_id,
        requires_manual_approval=payload.requires_manual_approval,
    )
    return _serialize_transition(result)


@router.get(
    "/teams/{team_id}/workflow/transitions",
    response_model=list[WorkflowTransitionResponse],
    summary="List all allowed workflow transitions for a team",
)
async def list_workflow_transitions(
    team_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    transitions = await svc.list_workflow_transitions(team_id)
    return [_serialize_transition(t) for t in transitions]


@router.delete(
    "/teams/{team_id}/workflow/transitions/{transition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a workflow transition rule",
)
async def delete_workflow_transition(
    team_id: int = Path(...),
    transition_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    await svc.delete_workflow_transition(team_id, transition_id)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — USER INVITATIONS (role_id must come from team's defined roles)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/teams/{team_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    summary="[Step 5] Invite a user and assign them a role [requires MANAGE_TEAM]",
    description=(
        "The `role_id` must refer to a role previously created for THIS team. "
        "If no roles exist yet, returns HTTP 400 — define roles first (Step 3). "
        "If the role doesn't exist in the team, the invitation is rejected."
    ),
)
async def invite_user(
    team_id: int = Path(...),
    payload: UserInviteRequest = ...,
    x_user_id: int = Header(..., alias="X-User-ID", description="Authenticated user ID"),
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    invitation = await svc.invite_user(
        team_id=team_id,
        email=payload.email,
        name=payload.name,
        role_id=payload.role_id,
        invited_by_user_id=x_user_id if isinstance(x_user_id, int) else None,
    )
    return {
        "message": "Invitation created successfully",
        "invitation_id": invitation.id,
        "team_id": invitation.teamId,
        "email": invitation.email,
        "role_id": invitation.roleId,
    }

@router.get(
    "/invitations/{invitation_id}",
    summary="Get invitation details (team name, role, inviter) for the landing page",
)
async def get_invitation_details(
    invitation_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    inv = await svc.repo.get_invitation_by_id(invitation_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    team = await svc.repo.get_team(inv.teamId)
    role = await svc.repo.get_role_by_id(inv.roleId)
    inviter = await svc.repo.get_user_by_id(inv.invitedById) if inv.invitedById else None

    return {
        "invitation_id": inv.id,
        "team_id": inv.teamId,
        "team_name": team.name if team else "Unknown Team",
        "role_name": role.name if role else "Member",
        "inviter_name": inviter.name if inviter else "A team member",
        "email": inv.email,
        "accepted_at": inv.acceptedAt,
    }

@router.post(
    "/teams/{team_id}/invitations/accept",
    summary="Accept an invitation and join the team (assigns role from invitation)",
    status_code=status.HTTP_201_CREATED,
)
async def accept_invitation(
    team_id: int = Path(...),
    payload: InvitationAcceptRequest = ...,
    x_user_id: int = Header(..., alias="X-User-ID", description="Authenticated user ID"),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    member = await svc.accept_invitation(
        team_id=team_id,
        invitation_id=payload.invitation_id,
        user_id=x_user_id,
        name=payload.name,
    )
    return {"message": "Joined team", "member_id": member.id, "team_id": member.teamId, "role_id": member.roleId}


@router.get(
    "/teams/{team_id}/members",
    summary="List all members with their role and permissions",
)
async def list_members(
    team_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    members = await svc.get_team_members(team_id)
    role_ids = sorted({m.roleId for m in members if m.roleId})
    role_permissions: dict[int, list[str]] = {}
    for rid in role_ids:
        role_permissions[int(rid)] = await svc.repo.get_role_permission_codes(rid)

    return [
        {
            "id": m.id,
            "team_id": m.teamId,
            "user_id": m.userId,
            "role_id": m.roleId,
            "email": m.user.email if m.user else None,
            "name": m.user.name if m.user else None,
            "role_name": m.role.name if m.role else None,
            "permission_codes": role_permissions.get(int(m.roleId), []) if m.roleId else [],
            "created_at": m.createdAt,
        }
        for m in members
    ]


@router.patch(
    "/teams/{team_id}/members/{member_id}/role",
    summary="Reassign a member to a different role [requires MANAGE_TEAM]",
)
async def update_member_role(
    team_id: int = Path(...),
    member_id: int = Path(...),
    payload: MemberRoleUpdateRequest = ...,
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    updated = await svc.update_member_role(team_id, member_id, payload.role_id)
    return {
        "message": "Role updated",
        "member_id": updated.id,
        "new_role": updated.role.name if updated.role else None,
    }


@router.delete(
    "/teams/{team_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from the team [requires MANAGE_TEAM]",
)
async def remove_member(
    team_id: int = Path(...),
    member_id: int = Path(...),
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    await svc.remove_member(member_id)


# ─────────────────────────────────────────────────────────────────────────────
# PERMISSION SELF-CHECK — Frontend uses this to build conditional UI
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/me/permissions",
    summary="Get current user's permissions for a team (used by frontend for conditional UI)",
    description=(
        "Send `X-User-ID` header and `team_id` query param. "
        "Returns the list of permissions for that user in the given team."
    ),
)
async def my_permissions(
    permissions: list[str] = Depends(get_current_user_permissions),
):
    return {"permissions": permissions}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_transition(t) -> dict:
    return {
        "id": t.id,
        "teamId": t.teamId,
        "fromStatusId": t.fromStatusId,
        "toStatusId": t.toStatusId,
        "requiresManualApproval": t.requiresManualApproval,
        "from_status_name": t.fromStatus.name if hasattr(t, "fromStatus") and t.fromStatus else None,
        "to_status_name": t.toStatus.name if hasattr(t, "toStatus") and t.toStatus else None,
        "createdAt": t.createdAt,
    }

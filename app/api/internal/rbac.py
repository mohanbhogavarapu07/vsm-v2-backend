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
    InvitationDetailsResponse, InvitationAcceptResponse,
    InvitationDetailsResponse, InvitationAcceptResponse,
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
    summary="[Step 1] Create a project (Boots Role, Member, Team, Workflow)",
)
async def create_project(
    payload: ProjectCreateRequest,
    x_user_id: int = Header(..., alias="X-User-ID", description="Authenticated user ID"),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.create_project(payload.name, x_user_id)


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


@router.post(
    "/projects/{project_id}/complete-setup",
    response_model=ProjectResponse,
    summary="Mark project setup as complete",
)
async def complete_project_setup(
    project_id: int,
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.complete_project_setup(project_id)


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


@router.get(
    "/projects/{project_id}/members",
    summary="List all high-level project members",
)
async def list_project_members(
    project_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    members = await svc.repo.get_project_members(project_id)
    return [
        {
            "id": m.id,
            "user_id": m.userId,
            "role_id": m.roleId,
            "email": m.user.email if m.user else None,
            "name": m.user.name if m.user else None,
            "role_name": m.role.name if m.role else None,
            "created_at": m.createdAt,
        }
        for m in members
    ]


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
    return await svc.create_team(project_id, payload.name, creator_user_id=x_user_id)


@router.get(
    "/projects/{project_id}/teams",
    response_model=list[TeamResponse],
    summary="List all teams in a project",
)
async def list_teams(
    project_id: int = Path(...),
    x_user_id: int = Header(..., alias="X-User-ID"),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    return await svc.list_teams(project_id, x_user_id)


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


@router.delete(
    "/teams/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a team (cascading delete) [requires MANAGE_TEAM]",
)
async def delete_team(
    team_id: int = Path(...),
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    await svc.delete_team(team_id)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — ROLES + PERMISSIONS (MANDATORY before inviting users)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Step 1] Create a project-level role",
)
async def create_role(
    project_id: int = Path(...),
    payload: RoleCreateRequest = ...,
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    role = await svc.create_role(project_id, payload.name, payload.permission_codes)
    codes = await svc.repo.get_role_permission_codes(role.id)
    return {
        "id": role.id,
        "projectId": role.projectId,
        "name": role.name,
        "permission_codes": codes,
        "createdAt": role.createdAt,
        "updatedAt": role.updatedAt,
    }


@router.get(
    "/projects/{project_id}/roles",
    response_model=list[RoleResponse],
    summary="List all roles defined for a project",
)
async def list_roles(
    project_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    roles = await svc.get_project_roles(project_id)
    perms_by_role: dict[int, list[str]] = {}
    for r in roles:
        perms_by_role[int(r.id)] = await svc.repo.get_role_permission_codes(r.id)
    return [
        {
            "id": r.id,
            "projectId": r.projectId,
            "name": r.name,
            "permission_codes": perms_by_role.get(int(r.id), []),
            "createdAt": r.createdAt,
            "updatedAt": r.updatedAt,
        }
        for r in roles
    ]


@router.patch(
    "/projects/{project_id}/roles/{role_id}",
    response_model=RoleResponse,
    summary="Update a project-level role",
)
async def update_role(
    project_id: int = Path(...),
    role_id: int = Path(...),
    payload: RoleUpdateRequest = ...,
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    role = await svc.update_role(project_id, role_id, payload.name, payload.permission_codes)
    codes = await svc.repo.get_role_permission_codes(role.id)
    return {
        "id": role.id,
        "projectId": role.projectId,
        "name": role.name,
        "permission_codes": codes,
        "createdAt": role.createdAt,
        "updatedAt": role.updatedAt,
    }


@router.delete(
    "/projects/{project_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project-level role",
)
async def delete_role(
    project_id: int = Path(...),
    role_id: int = Path(...),
    db: Prisma = Depends(get_db),
):
    svc = RBACService(db)
    await svc.delete_role(project_id, role_id)


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
    response_model=InvitationDetailsResponse,
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
        "project_id": team.projectId if team else 0,
        "team_id": inv.teamId,
        "team_name": team.name if team else "Unknown Team",
        "role_name": role.name if role else "Member",
        "inviter_name": inviter.name if inviter else "A team member",
        "email": inv.email,
        "accepted_at": inv.acceptedAt,
    }

@router.post(
    "/teams/{team_id}/invitations/accept",
    response_model=InvitationAcceptResponse,
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
    member, project_id = await svc.accept_invitation(
        team_id=team_id,
        invitation_id=payload.invitation_id,
        user_id=x_user_id,
        name=payload.name,
    )
    return {
        "message": "Joined team", 
        "member_id": member.id, 
        "project_id": project_id,
        "team_id": member.teamId, 
        "role_id": member.roleId
    }


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




"""
VSM Backend – RBAC Service

Business logic layer for the complete dynamic team management system.
Scrum defines the rules — system follows them.
"""
from datetime import datetime, timezone
import logging

from fastapi import HTTPException, status
from prisma import Prisma

from app.repositories.rbac_repository import RBACRepository


class RBACService:
    def __init__(self, db: Prisma):
        self.repo = RBACRepository(db)

    # ── Projects ──────────────────────────────────────────────────────────────

    async def create_project(self, name: str, creator_id: int):
        # ── 1. Create Project ──
        project = await self.repo.create_project(name)
        
        # ── 2. Create 'Scrum Master' role with HIGH access ──
        # These match the constants in the frontend projectStore.ts
        high_permissions = [
            "READ_TASK", "CREATE_TASK", "UPDATE_TASK", "DELETE_TASK", 
            "MANAGE_TEAM", "MANAGE_ROLES", "ASSIGN_TASKS"
        ]
        scrum_master_role = await self.create_role(project.id, "Scrum Master", high_permissions)
        
        # ── 3. Add creator to ProjectMember table (The Base Layer) ──
        # This grants the creator access to the project and all future teams.
        await self.repo.add_project_member(project.id, creator_id, scrum_master_role.id)
        
        return project

    async def list_projects(self, user_id: int | None = None):
        return await self.repo.list_projects(user_id)

    async def get_project(self, project_id: int):
        project = await self.repo.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    async def complete_project_setup(self, project_id: int):
        await self.get_project(project_id)
        return await self.repo.complete_project_setup(project_id)

    # ── Teams ─────────────────────────────────────────────────────────────────

    async def create_team(self, project_id: int, name: str, creator_user_id: int | None = None):
        await self.get_project(project_id)  # validates project exists
        
        if creator_user_id:
            user_exists = await self.repo.get_user_by_id(creator_user_id)
            if not user_exists:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authenticated user no longer exists in backend. Please sign out and sign back in to re-sync."
                )

        team = await self.repo.create_team(project_id, name)
        
        # If roles already exist in the project, and a creator is provided, 
        # we try to assign them an 'Admin' role if one exists.
        if creator_user_id:
            roles = await self.repo.get_roles_by_project(project_id)
            admin_role = next((r for r in roles if r.name.lower() in ["admin", "owner", "scrum master"]), None)
            if admin_role:
                await self.repo.create_team_member(team.id, creator_user_id, admin_role.id)
            
        return team

    async def update_team(self, team_id: int, name: str | None):
        await self.get_team(team_id)
        return await self.repo.update_team(team_id, name)

    async def delete_team(self, team_id: int):
        team = await self.get_team(team_id)
        
        # Check if this is the last team in the project
        project_teams = await self.repo.list_teams_by_project(team.projectId)
        if len(project_teams) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last team in a project. A project must have at least one team."
            )
            
        await self.repo.delete_team(team_id)

    async def get_team(self, team_id: int):
        team = await self.repo.get_team(team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        return team

    async def list_teams(self, project_id: int, user_id: int | None = None):
        await self.get_project(project_id)
        return await self.repo.list_teams_by_project(project_id, user_id)

    # ── Roles ─────────────────────────────────────────────────────────────────

    async def create_role(self, project_id: int, name: str, permission_codes: list[str]):
        await self.get_project(project_id)
        
        # ── IDEMPOTENCY CHECK: return existing if name matches ────────────────────
        existing_roles = await self.repo.get_roles_by_project(project_id)
        existing = next((r for r in existing_roles if r.name == name), None)
        if existing:
            # Update permissions anyway to ensure consistency
            perms = await self.repo.get_permissions_by_codes(permission_codes)
            await self.repo.replace_role_permissions(existing.id, [int(p.id) for p in perms])
            return existing

        perms = await self.repo.get_permissions_by_codes(permission_codes)
        if len(perms) != len(set(permission_codes)):
            found = {p.code for p in perms}
            missing = [c for c in permission_codes if c not in found]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown permission code(s): {', '.join(missing)}",
            )
        role = await self.repo.create_role(project_id, name)
        await self.repo.replace_role_permissions(role.id, [int(p.id) for p in perms])
        return role

    async def get_project_roles(self, project_id: int):
        await self.get_project(project_id)
        return await self.repo.get_roles_by_project(project_id)

    async def update_role(
        self, project_id: int, role_id: int,
        name: str | None, permission_codes: list[str] | None
    ):
        # Ensure the role belongs to this project
        role = await self.repo.get_role_by_id(role_id)
        if not role or role.projectId != project_id:
            raise HTTPException(status_code=404, detail="Role not found in this project")
        updated = await self.repo.update_role(role_id, name)
        if permission_codes is not None:
            perms = await self.repo.get_permissions_by_codes(permission_codes)
            if len(perms) != len(set(permission_codes)):
                found = {p.code for p in perms}
                missing = [c for c in permission_codes if c not in found]
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown permission code(s): {', '.join(missing)}",
                )
            await self.repo.replace_role_permissions(role_id, [int(p.id) for p in perms])
        return updated

    async def delete_role(self, project_id: int, role_id: int):
        role = await self.repo.get_role_by_id(role_id)
        if not role or role.projectId != project_id:
            raise HTTPException(status_code=404, detail="Role not found in this project")
        await self.repo.delete_role(role_id)

    # ── Members ───────────────────────────────────────────────────────────────

    async def invite_user(self, team_id: int, email: str, name: str, role_id: int, invited_by_user_id: int | None):
        """
        STRICT ORDER ENFORCEMENT:
        Step 3 (roles) MUST be completed before Step 5 (invitations).

        Rejects with HTTP 400 if:
          - No roles have been defined for this team yet (hard gate)
          - The given role_id does not belong to this team
        """
        team = await self.get_team(team_id)

        # ── HARD GATE: project must have at least one role defined ────────────────
        existing_roles = await self.repo.get_roles_by_project(team.projectId)
        if not existing_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Project has no roles defined. "
                    "Complete Step 1: create at least one role with permissions "
                    "before inviting users."
                ),
            )

        # ── Role must belong to this project ─────────────────────────────────────
        role = await self.repo.get_role_by_id(role_id)
        if not role or role.projectId != team.projectId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Role ID {role_id} does not exist in this project. "
                    "Use GET /projects/{project_id}/roles to see available roles."
                ),
            )

        # ── Check IF user is already a member (hard stop) ─────────────────────
        user = await self.repo.get_user_by_email(email)
        if user:
            existing_member = await self.repo.get_member_by_user_team(user.id, team_id)
            if existing_member:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with email {email} is already a member of this team",
                )

        # ── Check for existing pending invitation (trigger Re-Invite) ──────────
        if invited_by_user_id:
            user_exists = await self.repo.get_user_by_id(invited_by_user_id)
            if not user_exists:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authenticated user no longer exists in backend. Please sign out and sign back in to re-sync."
                )

        # Persist invitation + role mapping (does NOT create membership yet)
        existing_inv = await self.repo.get_invitation_by_team_email(team_id, email)
        
        if existing_inv and existing_inv.acceptedAt is None:
            # Re-invite: Update role and proceed with email triggering
            inv = await self.repo.update_invitation_role(existing_inv.id, role_id)
            logger = logging.getLogger(__name__)
            logger.info(f"Existing invitation {inv.id} for {email} UPDATED with role {role_id}. Re-sending email...")
        else:
            # Create new invitation
            inv = await self.repo.create_invitation(team_id, email, role_id, invited_by_user_id)
        
        logger = logging.getLogger(__name__)
        logger.info(f"Invitation {inv.id} created for {email}. Triggering email via SMTP...")

        # ── Trigger Asynchronous Invitation Email (Gmail SMTP) ─────────────────
        try:
            from app.services.mail_service import MailService
            
            # Fetch names for the email template
            team = await self.repo.get_team(team_id)
            role = await self.repo.get_role_by_id(role_id)
            inviter = await self.repo.get_user_by_id(invited_by_user_id) if invited_by_user_id else None

            inviter_name = inviter.name if inviter else "A team member"
            team_name = team.name if team else "VSM Team"
            role_name = role.name if role else "Member"

            mail_svc = MailService()
            await mail_svc.send_invitation_email(
                to_email=email,
                team_name=team_name,
                role_name=role_name,
                inviter_name=inviter_name,
                invitation_id=inv.id
            )
        except Exception as e:
            logger.error(f"Failed to trigger invitation email: {e}")

        return inv

    async def accept_invitation(self, team_id: int, invitation_id: int, user_id: int, name: str | None):
        team = await self.get_team(team_id)
        inv = await self.repo.get_invitation_by_id(invitation_id)
        if not inv or inv.teamId != team_id:
            raise HTTPException(status_code=404, detail="Invitation not found")
        if inv.acceptedAt is not None:
            raise HTTPException(status_code=409, detail="Invitation already accepted")

        # Ensure role still exists in project
        role = await self.repo.get_role_by_id(inv.roleId)
        if not role or role.projectId != team.projectId:
            raise HTTPException(status_code=400, detail="Invitation role is no longer valid for this project")

        # Ensure user exists (or create stub), then assign membership with role
        user = await self.repo.get_user_by_id(user_id)
        if not user:
            user = await self.repo.create_user(inv.email, name or "Invited User")
        elif name:
            # Best-effort name update
            await self.repo.update_user_name(user.id, name)

        existing_member = await self.repo.get_member_by_user_team(user.id, team_id)
        if existing_member:
            raise HTTPException(status_code=409, detail="User is already a member of this team")

        await self.repo.mark_invitation_accepted(invitation_id)
        
        # ── TWO-TIER PROVISIONING ──
        # 1. Ensure user is in ProjectMember table (Access Layer)
        pm = await self.repo.get_project_member_by_user(team.projectId, user.id)
        if not pm:
            await self.repo.add_project_member(team.projectId, user.id, inv.roleId)
            
        # 2. Add user to TeamMember table (Grouping Layer)
        member = await self.repo.create_team_member(team_id, user.id, inv.roleId)
        return member, team.projectId

    async def get_team_members(self, team_id: int):
        await self.get_team(team_id)
        return await self.repo.get_team_members(team_id)

    async def update_member_role(self, team_id: int, member_id: int, new_role_id: int):
        team = await self.get_team(team_id)
        role = await self.repo.get_role_by_id(new_role_id)
        if not role or role.projectId != team.projectId:
            raise HTTPException(
                status_code=400,
                detail="New role does not belong to this project",
            )
        return await self.repo.update_member_role(member_id, new_role_id)

    async def remove_member(self, member_id: int):
        return await self.repo.remove_team_member(member_id)

    # ── Workflow: Custom Task Statuses ────────────────────────────────────────

    async def create_task_status(
        self, project_id: int, name: str, category: str,
        stage_order: int, is_terminal: bool = False
    ):
        await self.get_project(project_id)
        return await self.repo.create_task_status(
            project_id, name, category, stage_order, is_terminal
        )

    async def list_task_statuses(self, project_id: int):
        await self.get_project(project_id)
        return await self.repo.list_task_statuses(project_id)

    async def update_task_status(
        self, project_id: int, status_id: int,
        name: str | None, stage_order: int | None, is_terminal: bool | None
    ):
        status_obj = await self.repo.get_task_status_by_id(status_id)
        if not status_obj or status_obj.projectId != project_id:
            raise HTTPException(status_code=404, detail="Status not found in this project")
        return await self.repo.update_task_status(status_id, name, stage_order, is_terminal)

    async def delete_task_status(self, project_id: int, status_id: int):
        status_obj = await self.repo.get_task_status_by_id(status_id)
        if not status_obj or status_obj.projectId != project_id:
            raise HTTPException(status_code=404, detail="Status not found in this project")
        await self.repo.delete_task_status(status_id)

    # ── Workflow: Transitions ─────────────────────────────────────────────────

    async def create_workflow_transition(
        self, project_id: int,
        from_status_id: int, to_status_id: int,
        requires_manual_approval: bool = False
    ):
        await self.get_project(project_id)
        from_status = await self.repo.get_task_status_by_id(from_status_id)
        to_status = await self.repo.get_task_status_by_id(to_status_id)

        if not from_status or from_status.projectId != project_id:
            raise HTTPException(status_code=404, detail="'from' status not found in this project")
        if not to_status or to_status.projectId != project_id:
            raise HTTPException(status_code=404, detail="'to' status not found in this project")

        return await self.repo.create_workflow_transition(
            project_id=project_id,
            from_status_id=from_status_id,
            to_status_id=to_status_id,
            from_category=from_status.systemCategory,
            to_category=to_status.systemCategory,
            requires_manual_approval=requires_manual_approval,
        )

    async def list_workflow_transitions(self, project_id: int):
        await self.get_project(project_id)
        return await self.repo.list_workflow_transitions(project_id)

    async def delete_workflow_transition(self, project_id: int, transition_id: int):
        await self.get_project(project_id)
        await self.repo.delete_workflow_transition(transition_id)

    # ── Permission Helper (for /me endpoint) ──────────────────────────────────

    async def get_user_permissions(self, user_id: int, team_id: int) -> list[str]:
        return await self.repo.get_user_permissions(user_id, team_id)

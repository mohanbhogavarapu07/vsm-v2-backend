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

    async def create_project(self, name: str):
        return await self.repo.create_project(name)

    async def list_projects(self, user_id: int | None = None):
        return await self.repo.list_projects(user_id)

    async def get_project(self, project_id: int):
        project = await self.repo.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    # ── Teams ─────────────────────────────────────────────────────────────────

    async def create_team(self, project_id: int, name: str, creator_user_id: int | None = None, copy_from_team_id: int | None = None):
        await self.get_project(project_id)  # validates project exists
        team = await self.repo.create_team(project_id, name)
        
        if copy_from_team_id:
            await self.repo.copy_team_config(copy_from_team_id, team.id, creator_user_id)
        elif creator_user_id:
            # Provide an automatic "Admin" role on creation so creator has permissions
            admin_role = await self.repo.create_role(team.id, "Admin")
            all_perms = await self.repo.list_permissions()
            if all_perms:
                await self.repo.replace_role_permissions(admin_role.id, [int(p.id) for p in all_perms])
            await self.repo.create_team_member(team.id, creator_user_id, admin_role.id)
            
        return team

    async def update_team(self, team_id: int, name: str | None):
        await self.get_team(team_id)
        return await self.repo.update_team(team_id, name)

    async def get_team(self, team_id: int):
        team = await self.repo.get_team(team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        return team

    async def list_teams(self, project_id: int):
        await self.get_project(project_id)
        return await self.repo.list_teams_by_project(project_id)

    # ── Roles ─────────────────────────────────────────────────────────────────

    async def create_role(self, team_id: int, name: str, permission_codes: list[str]):
        await self.get_team(team_id)
        perms = await self.repo.get_permissions_by_codes(permission_codes)
        if len(perms) != len(set(permission_codes)):
            found = {p.code for p in perms}
            missing = [c for c in permission_codes if c not in found]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown permission code(s): {', '.join(missing)}",
            )
        role = await self.repo.create_role(team_id, name)
        await self.repo.replace_role_permissions(role.id, [int(p.id) for p in perms])
        return role

    async def get_team_roles(self, team_id: int):
        await self.get_team(team_id)
        return await self.repo.get_roles_by_team(team_id)

    async def update_role(
        self, team_id: int, role_id: int,
        name: str | None, permission_codes: list[str] | None
    ):
        # Ensure the role belongs to this team
        role = await self.repo.get_role_by_id(role_id)
        if not role or role.teamId != team_id:
            raise HTTPException(status_code=404, detail="Role not found in this team")
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

    async def delete_role(self, team_id: int, role_id: int):
        role = await self.repo.get_role_by_id(role_id)
        if not role or role.teamId != team_id:
            raise HTTPException(status_code=404, detail="Role not found in this team")
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
        await self.get_team(team_id)

        # ── HARD GATE: team must have at least one role defined ────────────────
        existing_roles = await self.repo.get_roles_by_team(team_id)
        if not existing_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Team has no roles defined. "
                    "Complete Step 3: create at least one role with permissions "
                    "before inviting users."
                ),
            )

        # ── Role must belong to this team ─────────────────────────────────────
        role = await self.repo.get_role_by_id(role_id)
        if not role or role.teamId != team_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Role ID {role_id} does not exist in this team. "
                    "Use GET /teams/{team_id}/roles to see available roles."
                ),
            )

        # Persist invitation + role mapping (does NOT create membership yet)
        existing_inv = await self.repo.get_invitation_by_team_email(team_id, email)
        if existing_inv and existing_inv.acceptedAt is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already invited to this team",
            )
        if existing_inv and existing_inv.acceptedAt is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Invitation already accepted for this email",
            )
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
        await self.get_team(team_id)
        inv = await self.repo.get_invitation_by_id(invitation_id)
        if not inv or inv.teamId != team_id:
            raise HTTPException(status_code=404, detail="Invitation not found")
        if inv.acceptedAt is not None:
            raise HTTPException(status_code=409, detail="Invitation already accepted")

        # Ensure role still exists in team
        role = await self.repo.get_role_by_id(inv.roleId)
        if not role or role.teamId != team_id:
            raise HTTPException(status_code=400, detail="Invitation role is no longer valid for this team")

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
        return await self.repo.create_team_member(team_id, user.id, inv.roleId)

    async def get_team_members(self, team_id: int):
        await self.get_team(team_id)
        return await self.repo.get_team_members(team_id)

    async def update_member_role(self, team_id: int, member_id: int, new_role_id: int):
        role = await self.repo.get_role_by_id(new_role_id)
        if not role or role.teamId != team_id:
            raise HTTPException(
                status_code=400,
                detail="New role does not belong to this team",
            )
        return await self.repo.update_member_role(member_id, new_role_id)

    async def remove_member(self, member_id: int):
        return await self.repo.remove_team_member(member_id)

    # ── Workflow: Custom Task Statuses ────────────────────────────────────────

    async def create_task_status(
        self, team_id: int, name: str, category: str,
        stage_order: int, is_terminal: bool = False
    ):
        await self.get_team(team_id)
        return await self.repo.create_task_status(
            team_id, name, category, stage_order, is_terminal
        )

    async def list_task_statuses(self, team_id: int):
        await self.get_team(team_id)
        return await self.repo.list_task_statuses(team_id)

    async def update_task_status(
        self, team_id: int, status_id: int,
        name: str | None, stage_order: int | None, is_terminal: bool | None
    ):
        status_obj = await self.repo.get_task_status_by_id(status_id)
        if not status_obj or status_obj.teamId != team_id:
            raise HTTPException(status_code=404, detail="Status not found in this team")
        return await self.repo.update_task_status(status_id, name, stage_order, is_terminal)

    async def delete_task_status(self, team_id: int, status_id: int):
        status_obj = await self.repo.get_task_status_by_id(status_id)
        if not status_obj or status_obj.teamId != team_id:
            raise HTTPException(status_code=404, detail="Status not found in this team")
        await self.repo.delete_task_status(status_id)

    # ── Workflow: Transitions ─────────────────────────────────────────────────

    async def create_workflow_transition(
        self, team_id: int,
        from_status_id: int, to_status_id: int,
        requires_manual_approval: bool = False
    ):
        await self.get_team(team_id)
        from_status = await self.repo.get_task_status_by_id(from_status_id)
        to_status = await self.repo.get_task_status_by_id(to_status_id)

        if not from_status or from_status.teamId != team_id:
            raise HTTPException(status_code=404, detail="'from' status not found in this team")
        if not to_status or to_status.teamId != team_id:
            raise HTTPException(status_code=404, detail="'to' status not found in this team")

        return await self.repo.create_workflow_transition(
            team_id=team_id,
            from_status_id=from_status_id,
            to_status_id=to_status_id,
            from_category=from_status.category,
            to_category=to_status.category,
            requires_manual_approval=requires_manual_approval,
        )

    async def list_workflow_transitions(self, team_id: int):
        await self.get_team(team_id)
        return await self.repo.list_workflow_transitions(team_id)

    async def delete_workflow_transition(self, team_id: int, transition_id: int):
        await self.get_team(team_id)
        await self.repo.delete_workflow_transition(transition_id)

    # ── Permission Helper (for /me endpoint) ──────────────────────────────────

    async def get_user_permissions(self, user_id: int, team_id: int) -> list[str]:
        return await self.repo.get_user_permissions(user_id, team_id)

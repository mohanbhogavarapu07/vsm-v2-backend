from prisma import Prisma
from datetime import datetime, timezone
from app.utils.cache import permission_cache, all_permissions_cache


class RBACRepository:
    def __init__(self, db: Prisma):
        self.db = db

    # ── Projects ──────────────────────────────────────────────────────────────

    async def create_project(self, name: str):
        return await self.db.project.create(data={"name": name})

    async def get_project(self, project_id: int):
        return await self.db.project.find_unique(
            where={"id": project_id},
            include={"teams": True},
        )

    async def list_projects(self, user_id: int | None = None):
        if user_id:
            return await self.db.project.find_many(
                where={
                    "OR": [
                        {"projectMembers": {"some": {"userId": user_id}}},
                        {"teams": {"some": {"members": {"some": {"userId": user_id}}}}}
                    ]
                },
                order={"createdAt": "desc"}
            )
        return await self.db.project.find_many(order={"createdAt": "desc"})

    async def complete_project_setup(self, project_id: int):
        return await self.db.project.update(
            where={"id": project_id},
            data={"setupComplete": True}
        )

    # ── Teams ─────────────────────────────────────────────────────────────────

    async def create_team(self, project_id: int, name: str):
        return await self.db.team.create(
            data={"projectId": project_id, "name": name}
        )

    async def get_team(self, team_id: int):
        return await self.db.team.find_unique(where={"id": team_id})

    async def is_high_level_in_project(self, user_id: int, project_id: int) -> bool:
        """
        A user is "High-level" if they have the 'MANAGE_TEAM' permission 
        in ANY team within that project.
        """
        high_level = await self.db.teammember.find_first(
            where={
                "userId": user_id,
                "team": {
                    "projectId": project_id
                },
                "role": {
                    "rolePermissions": {
                        "some": {
                            "permission": {
                                "code": "MANAGE_TEAM"
                            }
                        }
                    }
                }
            }
        )
        return high_level is not None

    async def list_teams_by_project(self, project_id: int, user_id: int | None = None):
        """
        Visibility Logic:
          - No user_id: return all teams (fallback)
          - High-level: return all teams in project
          - Others: return ONLY teams where user is a member
        """
        if not user_id:
            return await self.db.team.find_many(
                where={"projectId": project_id},
                order={"createdAt": "asc"},
            )

        # 1. Elevate visibility if user is High-level (Scrum Master)
        is_high = await self.is_high_level_in_project(user_id, project_id)
        if is_high:
            return await self.db.team.find_many(
                where={"projectId": project_id},
                order={"createdAt": "asc"},
            )

        # 2. Strict Siloing: Only member teams
        return await self.db.team.find_many(
            where={
                "projectId": project_id,
                "members": {
                    "some": {
                        "userId": user_id
                    }
                }
            },
            order={"createdAt": "asc"},
        )

    async def update_team(self, team_id: int, name: str | None):
        data = {}
        if name is not None:
            data["name"] = name
        return await self.db.team.update(where={"id": team_id}, data=data)

    async def delete_team(self, team_id: int):
        return await self.db.team.delete(where={"id": team_id})

    async def get_project_context_for_team(self, team_id: int):
        team = await self.db.team.find_unique(where={"id": team_id})
        return team.projectId if team else None

    # ── Roles ─────────────────────────────────────────────────────────────────

    async def create_role(self, project_id: int, name: str):
        return await self.db.projectrole.create(data={"projectId": project_id, "name": name})

    async def get_role_by_id(self, role_id: int):
        return await self.db.projectrole.find_unique(where={"id": role_id})

    async def get_roles_by_project(self, project_id: int):
        return await self.db.projectrole.find_many(
            where={"projectId": project_id},
            order={"name": "asc"},
        )

    async def update_role(self, role_id: int, name: str | None):
        data = {}
        if name is not None:
            data["name"] = name
        return await self.db.projectrole.update(where={"id": role_id}, data=data)

    async def delete_role(self, role_id: int):
        return await self.db.projectrole.delete(where={"id": role_id})

    # ── Permissions / Role-Permissions ────────────────────────────────────────

    async def list_permissions(self) -> list:
        return await self.db.permission.find_many(order={"code": "asc"})

    async def get_permissions_by_codes(self, codes: list[str]) -> list:
        if not codes:
            return []
        return await self.db.permission.find_many(where={"code": {"in": codes}})

    async def replace_role_permissions(self, role_id: int, permission_ids: list[int]) -> None:
        """
        Replace the permissions assigned to a role. Implemented as:
          - delete existing RolePermission rows for role
          - bulk insert new rows
        """
        async with self.db.tx() as tx:
            await tx.rolepermission.delete_many(where={"roleId": role_id})
            if permission_ids:
                await tx.rolepermission.create_many(
                    data=[{"roleId": role_id, "permissionId": pid} for pid in permission_ids]
                )
        # ── INVADIDATE CACHE ──
        permission_cache.clear()
        all_permissions_cache.clear()

    async def get_role_permission_codes(self, role_id: int) -> list[str]:
        rows = await self.db.rolepermission.find_many(
            where={"roleId": role_id},
            include={"permission": True},
        )
        return [r.permission.code for r in rows if getattr(r, "permission", None)]

    async def get_project_role_with_permissions(self, role_id: int):
        return await self.db.projectrole.find_unique(
            where={"id": role_id},
            include={"rolePermissions": {"include": {"permission": True}}},
        )

    # ── Users ─────────────────────────────────────────────────────────────────

    async def get_user_by_email(self, email: str):
        return await self.db.user.find_unique(where={"email": email})

    async def get_user_by_id(self, user_id: int):
        return await self.db.user.find_unique(where={"id": user_id})

    async def create_user(self, email: str, name: str):
        return await self.db.user.create(data={"email": email, "name": name})

    async def update_user_name(self, user_id: int, name: str):
        return await self.db.user.update(where={"id": user_id}, data={"name": name})

    # ── Team Members ──────────────────────────────────────────────────────────

    async def create_team_member(self, team_id: int, user_id: int, role_id: int):
        member = await self.db.teammember.create(
            data={"teamId": team_id, "userId": user_id, "roleId": role_id}
        )
        # ── INVALIDATE CACHE ──
        permission_cache.invalidate(f"rbac_{user_id}_{team_id}")
        return member

    async def get_team_members(self, team_id: int):
        return await self.db.teammember.find_many(
            where={"teamId": team_id},
            include={"user": True, "role": True},
        )

    async def get_member_by_user_team(self, user_id: int, team_id: int):
        return await self.db.teammember.find_first(
            where={"userId": user_id, "teamId": team_id},
            include={"role": True},
        )

    async def update_member_role(self, member_id: int, role_id: int):
        updated = await self.db.teammember.update(
            where={"id": member_id},
            data={"roleId": role_id},
            include={"role": True, "user": True},
        )
        # ── INVALIDATE CACHE ──
        permission_cache.invalidate(f"rbac_{updated.userId}_{updated.teamId}")
        return updated

    async def remove_team_member(self, member_id: int):
        return await self.db.teammember.delete(where={"id": member_id})

    # ── Project Members ───────────────────────────────────────────────────────

    async def add_project_member(self, project_id: int, user_id: int, role_id: int):
        return await self.db.projectmember.create(
            data={"projectId": project_id, "userId": user_id, "roleId": role_id}
        )

    async def get_project_members(self, project_id: int):
        return await self.db.projectmember.find_many(
            where={"projectId": project_id},
            include={"user": True, "role": True},
        )

    async def get_project_member_by_user(self, project_id: int, user_id: int):
        return await self.db.projectmember.find_first(
            where={"projectId": project_id, "userId": user_id},
            include={"role": True},
        )

    async def update_project_member_role(self, project_id: int, user_id: int, role_id: int):
        return await self.db.projectmember.update(
            where={"projectId_userId": {"projectId": project_id, "userId": user_id}},
            data={"roleId": role_id}
        )

    # ── Invitations ───────────────────────────────────────────────────────────

    async def create_invitation(
        self,
        team_id: int,
        email: str,
        role_id: int,
        invited_by_id: int | None,
    ):
        return await self.db.teaminvitation.create(
            data={
                "teamId": team_id,
                "email": email,
                "roleId": role_id,
                "invitedById": invited_by_id,
            }
        )

    async def get_invitation_by_id(self, invitation_id: int):
        return await self.db.teaminvitation.find_unique(where={"id": invitation_id})

    async def get_invitation_by_team_email(self, team_id: int, email: str):
        return await self.db.teaminvitation.find_unique(
            where={"teamId_email": {"teamId": team_id, "email": email}}
        )

    async def mark_invitation_accepted(self, invitation_id: int):
        return await self.db.teaminvitation.update(
            where={"id": invitation_id},
            data={"acceptedAt": datetime.now(timezone.utc)},
        )

    async def update_invitation_role(self, invitation_id: int, role_id: int):
        return await self.db.teaminvitation.update(
            where={"id": invitation_id},
            data={"roleId": role_id}
        )

    # ── Workflow: TaskStatus ───────────────────────────────────────────────────

    async def create_task_status(
        self,
        project_id: int,
        name: str,
        category: str,
        stage_order: int,
        is_terminal: bool = False,
    ):
        return await self.db.workflowstage.create(
            data={
                "projectId": project_id,
                "name": name,
                "systemCategory": category,
                "positionOrder": stage_order,
                "isBlocking": is_terminal,
            }
        )

    async def list_task_statuses(self, project_id: int):
        return await self.db.workflowstage.find_many(
            where={"projectId": project_id},
            order={"positionOrder": "asc"},
        )

    async def get_task_status_by_id(self, status_id: int):
        return await self.db.workflowstage.find_unique(where={"id": status_id})

    async def update_task_status(
        self, status_id: int, name: str | None, stage_order: int | None, is_terminal: bool | None
    ):
        data = {}
        if name is not None:
            data["name"] = name
        if stage_order is not None:
            data["positionOrder"] = stage_order
        if is_terminal is not None:
            data["isBlocking"] = is_terminal
        return await self.db.workflowstage.update(where={"id": status_id}, data=data)

    async def delete_task_status(self, status_id: int):
        return await self.db.workflowstage.delete(where={"id": status_id})

    # ── Workflow: Transitions ─────────────────────────────────────────────────

    async def create_workflow_transition(
        self,
        project_id: int,
        from_status_id: int,
        to_status_id: int,
        from_category: str,
        to_category: str,
        requires_manual_approval: bool = False,
    ):
        return await self.db.workflowtransition.create(
            data={
                "projectId": project_id,
                "fromStageId": from_status_id,
                "toStageId": to_status_id,
                "requiresManualApproval": requires_manual_approval,
                "directionType": "FORWARD",
                "triggerType": "MANUAL",
            }
        )

    async def list_workflow_transitions(self, project_id: int):
        return await self.db.workflowtransition.find_many(
            where={"projectId": project_id},
            include={"fromStage": True, "toStage": True},
            order={"priorityRank": "desc"},
        )

    async def delete_workflow_transition(self, transition_id: int):
        return await self.db.workflowtransition.delete(where={"id": transition_id})

    # ── Permission Lookup (for middleware) ────────────────────────────────────

    async def get_user_permissions(self, user_id: int, team_id: int) -> list[str]:
        """
        Optimized and cached permission lookup.
        """
        cache_key = f"rbac_{user_id}_{team_id}"
        cached = permission_cache.get(cache_key)
        if cached is not None:
            return cached

        # 1. Resolve team and project context
        team = await self.db.team.find_unique(where={"id": team_id})
        if not team:
            return []

        # 2. Check for Project-Level Membership (The New Layer)
        project_membership = await self.get_project_member_by_user(team.projectId, user_id)
        project_perms = []
        is_project_high = False
        
        if project_membership and project_membership.role:
            project_perms = await self.get_role_permission_codes(project_membership.roleId)
            if "MANAGE_TEAM" in project_perms:
                is_project_high = True

        # 3. Check for High-Level Project Access
        if is_project_high:
            all_perms = all_permissions_cache.get("system_all")
            if all_perms is None:
                rows = await self.db.permission.find_many()
                all_perms = [p.code for p in rows]
                all_permissions_cache.set("system_all", all_perms)
            permission_cache.set(cache_key, all_perms)
            return all_perms

        # 4. Fetch Team-Specific Membership
        team_membership = await self.get_member_by_user_team(user_id, team_id)
        team_perms = []
        if team_membership:
            team_perms = await self.get_role_permission_codes(team_membership.roleId)

        # 5. Combine and Cache
        # Project permissions act as a baseline; team permissions are squad-specific
        # In case of overlaps, we take the union
        final_perms = list(set(project_perms + team_perms))
        permission_cache.set(cache_key, final_perms)
        return final_perms

    async def get_project_permissions(self, user_id: int, project_id: int) -> list[str]:
        """
        Return permissions based ONLY on ProjectMember role.
        """
        membership = await self.get_project_member_by_user(project_id, user_id)
        if not membership or not membership.role:
            return []
        
        perms = await self.get_role_permission_codes(membership.roleId)
        
        # If they have MANAGE_TEAM at project level, they are effectively superusers for that project
        if "MANAGE_TEAM" in perms:
            rows = await self.db.permission.find_many()
            return [p.code for p in rows]
            
        return perms

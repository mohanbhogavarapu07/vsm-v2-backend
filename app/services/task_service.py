"""
VSM Backend – Task Service (Prisma)

Business logic layer for tasks. All DB access goes through TaskRepository
(Prisma). The AI agent calls the same RBAC-protected transition path as any
user, authenticating via a dedicated service-account user (X-User-ID header).
"""

import logging
import asyncio
from typing import Any

from fastapi import HTTPException, status
from prisma import Prisma
from prisma.models import Task, AgentDecision

from app.models.enums import DecisionSource, FeedbackResult
from app.repositories.task_repository import TaskRepository
from app.repositories.rbac_repository import RBACRepository
from app.services.email_service import send_task_assignment_email

logger = logging.getLogger(__name__)
UNSET: Any = object()


class TaskService:
    def __init__(self, db: Prisma) -> None:
        self._task_repo = TaskRepository(db)
        self._rbac_repo = RBACRepository(db)
        self._db = db

    # ── Task CRUD ─────────────────────────────────────────────────────────────

    async def create_task(
        self,
        team_id: int,
        title: str,
        description: str | None = None,
        sprint_id: int | None = None,
        current_stage_id: int | None = None,
        assignee_id: int | None = None,
        priority: str | None = None,
        updater_id: int | None = None,
    ) -> Task:
        """Create a task scoped to the given team."""
        # Verify team exists
        team = await self._rbac_repo.get_team(team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        # SAFETY NET: If no stage provided, use the first stage in the project workflow
        if current_stage_id is None:
            stages = await self._task_repo.list_statuses_by_project(team.projectId)
            if stages:
                current_stage_id = int(stages[0].id)
                logger.info("Auto-assigned default stage %s from project %s to new task: %s", current_stage_id, team.projectId, title)

        task = await self._task_repo.create_task(
            team_id=team_id,
            title=title,
            description=description,
            sprint_id=sprint_id,
            current_stage_id=current_stage_id,
            assignee_id=assignee_id,
            priority=priority,
        )

        if assignee_id:
            async def _safe_send_email():
                try:
                    # Fetch detailed info for the email using the newly created task's data
                    member = await self._db.teammember.find_unique(
                        where={"id": assignee_id},
                        include={
                            "user": True,
                            "team": {
                                "include": {"project": True}
                            }
                        }
                    )
                    
                    if not (member and member.user and member.team and member.team.project):
                        return

                    # Get status name
                    status_name = "To Do"
                    if task.currentStageId:
                        curr_stage = await self._db.workflowstage.find_unique(where={"id": task.currentStageId})
                        if curr_stage:
                            status_name = curr_stage.name

                    # Get updater name
                    assigned_by = "Admin"
                    if updater_id:
                        updater = await self._db.user.find_unique(where={"id": updater_id})
                        if updater:
                            assigned_by = updater.name

                    await send_task_assignment_email(
                        user_email=member.user.email,
                        user_name=member.user.name,
                        task_title=task.title,
                        project_name=member.team.project.name,
                        team_name=member.team.name,
                        task_id=task.id,
                        project_id=member.team.project.id,
                        team_id=member.team.id,
                        priority=task.priority or "Normal",
                        status_name=status_name,
                        assigned_by=assigned_by
                    )
                except Exception as e:
                    logger.error("Failed to send assignment email during creation: %s", str(e), exc_info=True)

            # Fire and forget immediately
            asyncio.create_task(_safe_send_email())

        return task

    async def get_task(self, task_id: int) -> Task | None:
        return await self._task_repo.get_task_by_id(task_id)

    async def require_task(self, task_id: int) -> Task:
        task = await self._task_repo.get_task_by_id(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    async def list_tasks(
        self, team_id: int, limit: int = 50, offset: int = 0
    ) -> list[Task]:
        return await self._task_repo.list_tasks(team_id, limit, offset)

    async def update_task(
        self,
        task_id: int,
        title: str | Any = UNSET,
        description: str | Any = UNSET,
        sprint_id: int | Any = UNSET,
        current_stage_id: int | Any = UNSET,
        assignee_id: int | Any = UNSET,
        priority: str | Any = UNSET,
        order: float | Any = UNSET,
        updater_id: int | None = None,
    ) -> Task:
        task = await self.require_task(task_id)
        data: dict[str, Any] = {}
        if title is not UNSET:
            data["title"] = title
        if description is not UNSET:
            data["description"] = description
        if sprint_id is not UNSET:
            data["sprintId"] = sprint_id
        if current_stage_id is not UNSET:
            data["currentStageId"] = current_stage_id
        if assignee_id is not UNSET:
            data["assigneeId"] = assignee_id
        if priority is not UNSET:
            data["priority"] = priority
        if order is not UNSET:
            data["order"] = order
        if not data:
            return task

        # Check if email needs to be sent
        trigger_email = (
            assignee_id is not UNSET 
            and assignee_id is not None
            and getattr(task, "assigneeId", None) != assignee_id
        )

        updated = await self._task_repo.update_task(task_id, data)

        if trigger_email and assignee_id:
            async def _safe_send_email():
                try:
                    # Fetch detailed info for the email
                    member = await self._db.teammember.find_unique(
                        where={"id": assignee_id},
                        include={
                            "user": True,
                            "team": {
                                "include": {"project": True}
                            }
                        }
                    )
                    
                    if not (member and member.user and member.team and member.team.project):
                        return

                    # Get status name
                    status_name = "To Do"
                    if updated.currentStageId:
                        curr_stage = await self._db.workflowstage.find_unique(where={"id": updated.currentStageId})
                        if curr_stage:
                            status_name = curr_stage.name

                    # Get updater name
                    assigned_by = "Admin"
                    if updater_id:
                        updater = await self._db.user.find_unique(where={"id": updater_id})
                        if updater:
                            assigned_by = updater.name

                    await send_task_assignment_email(
                        user_email=member.user.email,
                        user_name=member.user.name,
                        task_title=updated.title,
                        project_name=member.team.project.name,
                        team_name=member.team.name,
                        task_id=updated.id,
                        project_id=member.team.project.id,
                        team_id=member.team.id,
                        priority=updated.priority or "Normal",
                        status_name=status_name,
                        assigned_by=assigned_by
                    )
                except Exception as e:
                    logger.error("Failed to send assignment email: %s", str(e), exc_info=True)

            # Fire and forget immediately with robust error boundary
            asyncio.create_task(_safe_send_email())

        return updated  # type: ignore[return-value]

    async def delete_task(self, task_id: int) -> None:
        await self.require_task(task_id)
        await self._db.task.delete(where={"id": task_id})

    # ── Manual Status Override ────────────────────────────────────────────────

    async def manual_status_override(
        self,
        task_id: int,
        new_status_id: int,
        reason: str | None = None,
    ) -> Task:
        """
        Manual drag-and-drop / user-initiated task transition.
        Records a RULE_ENGINE decision for audit trail.
        Runs in a single Prisma transaction.
        """
        await self.require_task(task_id)
        async with self._db.tx() as tx:
            task = await tx.task.update(
                where={"id": task_id},
                data={"currentStageId": new_status_id},
                include={"currentStage": True},
            )
            await tx.agentdecision.create(
                data={
                    "taskId": task_id,
                    "toStageId": new_status_id,
                    "reasoning": reason or "Manual override by user",
                    "status": "APPLIED",
                    "confidenceScore": 1.0,
                    "inputSignals": "{}",
                    "decisionSource": DecisionSource.RULE_ENGINE.value,
                }
            )
        logger.info("Manual override task=%s → status=%s", task_id, new_status_id)
        return task

    async def manual_resolve_decision(
        self,
        task_id: int,
        decision_id: int,
        new_status_id: int,
        user_id: int | None = None,
    ) -> Task:
        """
        Scrum Master manual resolution of an AI blocker/pending state.
        Updates task status and marks the specific decision as RESOLVED_MANUALLY.
        """
        await self.require_task(task_id)
        async with self._db.tx() as tx:
            # 1. Update Task
            task = await tx.task.update(
                where={"id": task_id},
                data={"currentStageId": new_status_id},
                include={"currentStage": True},
            )
            # 2. Update Decision Status
            await tx.agentdecision.update(
                where={"id": decision_id},
                data={"status": "RESOLVED_MANUALLY"}
            )
            # 3. Record Feedback
            if user_id:
                await tx.decisionfeedback.create(
                    data={
                        "decisionId": decision_id,
                        "userId": user_id,
                        "feedback": "ACCEPTED"
                    }
                )
        
        logger.info("Manual resolution applied for decision %s: status → %s", decision_id, new_status_id)
        return task

    # ── Agent-Privileged Transition ───────────────────────────────────────────

    async def apply_agent_decision(
        self,
        task_id: int,
        new_status_id: int,
        action_taken: str,
        reason: str,
        confidence_score: float,
        input_signals: dict,
    ) -> Task:
        """
        AI agent-initiated task transition.

        The caller must already have passed RBAC (via `require_permission` in
        the API layer). This method atomically updates task status and writes
        an immutable `agent_decision` record for full auditability.
        """
        await self.require_task(task_id)
        async with self._db.tx() as tx:
            task = await tx.task.update(
                where={"id": task_id},
                data={"currentStageId": new_status_id},
                include={"currentStage": True},
            )
            import json
            await tx.agentdecision.create(
                data={
                    "taskId": task_id,
                    "toStageId": new_status_id,
                    "reasoning": reason,
                    "status": "APPLIED" if new_status_id else "NO_TRANSITION",
                    "confidenceScore": confidence_score,
                    "inputSignals": json.dumps(input_signals),
                    "decisionSource": DecisionSource.AI_MODEL.value,
                }
            )
        logger.info(
            "Agent decision applied: task=%s action=%s conf=%.2f",
            task_id, action_taken, confidence_score,
        )
        return task

    async def get_valid_transitions(self, task_id: int):
        """
        Categorical transition helper. Since we've removed the explicit 
        WorkflowTransition table, this returns all other stages in the project 
        as potential targets for now.
        """
        task = await self.require_task(task_id)
        if not task or not task.teamId:
            return []
        
        team = await self._rbac_repo.get_team(task.teamId)
        if not team:
            return []

        return await self._task_repo.list_statuses_by_project(team.projectId)

    async def get_decisions_for_task(self, task_id: int) -> list[AgentDecision]:
        return await self._task_repo.list_decisions_for_task(task_id)


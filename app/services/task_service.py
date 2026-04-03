"""
VSM Backend – Task Service (Prisma)

Business logic layer for tasks. All DB access goes through TaskRepository
(Prisma). The AI agent calls the same RBAC-protected transition path as any
user, authenticating via a dedicated service-account user (X-User-ID header).
"""

import logging
from typing import Any

from fastapi import HTTPException, status
from prisma import Prisma
from prisma.models import Task, AgentDecision

from app.models.enums import DecisionSource, FeedbackResult
from app.repositories.task_repository import TaskRepository
from app.repositories.rbac_repository import RBACRepository

logger = logging.getLogger(__name__)


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
        current_status_id: int | None = None,
        assignee_id: int | None = None,
    ) -> Task:
        """Create a task scoped to the given team."""
        # Verify team exists
        team = await self._rbac_repo.get_team(team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        return await self._task_repo.create_task(
            team_id=team_id,
            title=title,
            description=description,
            sprint_id=sprint_id,
            current_status_id=current_status_id,
            assignee_id=assignee_id,
        )

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
        title: str | None = None,
        description: str | None = None,
        sprint_id: int | None = None,
        current_status_id: int | None = None,
        assignee_id: int | None = None,
    ) -> Task:
        task = await self.require_task(task_id)
        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description
        if sprint_id is not None:
            data["sprintId"] = sprint_id
        if current_status_id is not None:
            data["currentStatusId"] = current_status_id
        if assignee_id is not None:
            data["assigneeId"] = assignee_id
        if not data:
            return task
        updated = await self._task_repo.update_task(task_id, data)
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
                data={"currentStatusId": new_status_id},
                include={"currentStatus": True},
            )
            await tx.agentdecision.create(
                data={
                    "taskId": task_id,
                    "actionTaken": "MANUAL_STATUS_OVERRIDE",
                    "reason": reason or "Manual override by user",
                    "confidenceScore": 1.0,
                    "inputSignals": {},
                    "decisionSource": DecisionSource.RULE_ENGINE.value,
                }
            )
        logger.info("Manual override task=%s → status=%s", task_id, new_status_id)
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
                data={"currentStatusId": new_status_id},
                include={"currentStatus": True},
            )
            await tx.agentdecision.create(
                data={
                    "taskId": task_id,
                    "actionTaken": action_taken,
                    "reason": reason,
                    "confidenceScore": confidence_score,
                    "inputSignals": input_signals,
                    "decisionSource": DecisionSource.AI_MODEL.value,
                }
            )
        logger.info(
            "Agent decision applied: task=%s action=%s conf=%.2f",
            task_id, action_taken, confidence_score,
        )
        return task

    # ── Decisions ─────────────────────────────────────────────────────────────

    async def get_valid_transitions(self, task_id: int, team_id: int):
        task = await self._task_repo.get_task_by_id(task_id)
        if not task or not task.currentStatusId:
            return []
        return await self._task_repo.get_valid_transitions(
            team_id=team_id,
            from_status_id=task.currentStatusId,
        )

    async def get_decisions_for_task(self, task_id: int) -> list[AgentDecision]:
        return await self._task_repo.list_decisions_for_task(task_id)

    async def record_decision_feedback(
        self, decision_id: int, user_id: int, feedback: str
    ):
        return await self._task_repo.record_decision_feedback(
            decision_id, user_id, FeedbackResult(feedback)
        )

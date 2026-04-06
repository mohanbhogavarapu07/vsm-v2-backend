"""
VSM Backend – Task Repository (Prisma)

All DB interactions for Task, TaskStatus, WorkflowTransition,
TransitionCondition, AgentDecision, and DecisionFeedback.
"""

import logging
from typing import Any

from prisma import Prisma, Json
from prisma.models import (
    Task,
    TaskStatus,
    WorkflowTransition,
    AgentDecision,
    DecisionFeedback,
)

from app.models.enums import TaskStatusCategory, DecisionSource, FeedbackResult

logger = logging.getLogger(__name__)


class TaskRepository:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    # ── Task ──────────────────────────────────────────────────────────────────

    async def create_task(
        self,
        team_id: int,
        title: str,
        description: str | None = None,
        sprint_id: int | None = None,
        current_status_id: int | None = None,
        assignee_id: int | None = None,
        priority: str | None = None,
    ) -> Task:
        data: dict[str, Any] = {
            "teamId": team_id,
            "title": title,
        }
        if description is not None:
            data["description"] = description
        if sprint_id is not None:
            data["sprintId"] = sprint_id
        if current_status_id is not None:
            data["currentStatusId"] = current_status_id
        if assignee_id is not None:
            data["assigneeId"] = assignee_id
        if priority is not None:
            data["priority"] = priority

        task = await self._db.task.create(data=data)
        logger.info("Created task id=%s org=%s", task.id, team_id)
        return task

    async def get_task_by_id(
        self, task_id: int, load_status: bool = True
    ) -> Task | None:
        return await self._db.task.find_unique(
            where={"id": task_id},
            include={"currentStatus": load_status} if load_status else None,
        )

    async def list_tasks(
        self, team_id: int, limit: int = 50, offset: int = 0
    ) -> list[Task]:
        return await self._db.task.find_many(
            where={"teamId": team_id},
            include={"currentStatus": True},
            order={"createdAt": "desc"},
            take=limit,
            skip=offset,
        )

    async def update_task(self, task_id: int, data: dict) -> Task | None:
        return await self._db.task.update(
            where={"id": task_id},
            data=data,
        )

    async def update_task_status(
        self, task_id: int, new_status_id: int
    ) -> Task | None:
        return await self._db.task.update(
            where={"id": task_id},
            data={"currentStatusId": new_status_id},
        )

    # ── TaskStatus ─────────────────────────────────────────────────────────────

    async def get_status_by_id(self, status_id: int) -> TaskStatus | None:
        return await self._db.taskstatus.find_unique(
            where={"id": status_id}
        )

    async def get_status_by_category_project(
        self, project_id: int, category: TaskStatusCategory
    ) -> TaskStatus | None:
        return await self._db.taskstatus.find_first(
            where={
                "projectId": project_id,
                "category": category.value,
            }
        )

    async def list_statuses_by_project(self, project_id: int) -> list[TaskStatus]:
        return await self._db.taskstatus.find_many(
            where={"projectId": project_id},
            order={"stageOrder": "asc"},
        )

    async def create_status(
        self,
        project_id: int,
        name: str,
        category: TaskStatusCategory,
        stage_order: int = 0,
        is_terminal: bool = False,
    ) -> TaskStatus:
        return await self._db.taskstatus.create(
            data={
                "projectId": project_id,
                "name": name,
                "category": category.value,
                "stageOrder": stage_order,
                "isTerminal": is_terminal,
            }
        )

    # ── WorkflowTransition ─────────────────────────────────────────────────────

    async def get_valid_transitions_by_project(
        self, project_id: int, from_status_id: int
    ) -> list[WorkflowTransition]:
        """Returns valid transitions from current status, with conditions loaded."""
        return await self._db.workflowtransition.find_many(
            where={
                "projectId": project_id,
                "fromStatusId": from_status_id,
            },
            include={
                "conditions": True,
                "toStatus": True,
            },
            order={"priority": "desc"},
        )

    async def get_transitions_by_category_project(
        self,
        project_id: int,
        from_category: TaskStatusCategory,
    ) -> list[WorkflowTransition]:
        """AI uses category-based lookups for cross-org reasoning."""
        return await self._db.workflowtransition.find_many(
            where={
                "projectId": project_id,
                "fromCategory": from_category.value,
            },
            include={
                "conditions": True,
                "toStatus": True,
            },
            order={"priority": "desc"},
        )

    # ── AgentDecision ──────────────────────────────────────────────────────────

    async def record_decision(
        self,
        task_id: int,
        action_taken: str,
        reason: str,
        confidence_score: float,
        input_signals: dict,
        decision_source: DecisionSource,
    ) -> AgentDecision:
        return await self._db.agentdecision.create(
            data={
                "taskId": task_id,
                "actionTaken": action_taken,
                "reason": reason,
                "confidenceScore": confidence_score,
                "inputSignals": Json(input_signals),
                "decisionSource": decision_source.value,
            }
        )

    async def list_decisions_for_task(
        self, task_id: int, limit: int = 20
    ) -> list[AgentDecision]:
        return await self._db.agentdecision.find_many(
            where={"taskId": task_id},
            order={"createdAt": "desc"},
            take=limit,
        )

    async def get_decision_by_id(self, decision_id: int) -> AgentDecision | None:
        return await self._db.agentdecision.find_unique(
            where={"id": decision_id}
        )

    # ── DecisionFeedback ────────────────────────────────────────────────────────

    async def record_decision_feedback(
        self, decision_id: int, user_id: int, feedback: FeedbackResult
    ) -> DecisionFeedback:
        return await self._db.decisionfeedback.create(
            data={
                "decisionId": decision_id,
                "userId": user_id,
                "feedback": feedback.value,
            }
        )

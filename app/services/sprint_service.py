"""
VSM Backend – Sprint Service (Prisma)

Full Jira-style sprint lifecycle management:
  PLANNED → ACTIVE (start_sprint) → COMPLETED (complete_sprint with rollover)

Business rules:
  - Only ONE sprint may be ACTIVE at a time per team.
  - Completing a sprint moves all incomplete tasks to backlog or a target sprint.
  - Task counts are returned with each sprint for Jira-style stat badges.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from prisma import Prisma

from app.models.enums import SprintStatus

logger = logging.getLogger(__name__)


class SprintService:
    def __init__(self, db: Prisma):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # READ
    # ─────────────────────────────────────────────────────────────────────────

    async def list_sprints(self, team_id: int):
        """Return all sprints for a team ordered by creation date descending."""
        try:
            sprints = await self.db.sprint.find_many(
                where={"teamId": team_id},
                include={"tasks": {"include": {"currentStatus": True}}},
                order={"createdAt": "asc"},
            )
            return sprints
        except Exception as e:
            logger.error(f"Error listing sprints for team {team_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def require_sprint(self, sprint_id: int, team_id: Optional[int] = None):
        """Fetch a sprint by ID, optionally asserting it belongs to a team."""
        where: dict = {"id": sprint_id}
        if team_id is not None:
            where["teamId"] = team_id
        sprint = await self.db.sprint.find_first(where=where)
        if not sprint:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")
        return sprint

    async def get_sprint_with_tasks(self, sprint_id: int, team_id: int):
        """Return a sprint with its tasks and status info (for stats)."""
        sprint = await self.db.sprint.find_first(
            where={"id": sprint_id, "teamId": team_id},
            include={"tasks": {"include": {"currentStatus": True}}},
        )
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")
        return sprint

    async def get_backlog_tasks(self, team_id: int, limit: int = 100, offset: int = 0):
        """Return tasks for a team that are NOT assigned to any sprint."""
        return await self.db.task.find_many(
            where={"teamId": team_id, "sprintId": None},
            include={"currentStatus": True, "assignee": {"include": {"user": True}}},
            order={"createdAt": "desc"},
            take=limit,
            skip=offset,
        )

    async def get_sprint_tasks(self, sprint_id: int, team_id: int):
        """Return all tasks belonging to a specific sprint."""
        await self.require_sprint(sprint_id, team_id)
        return await self.db.task.find_many(
            where={"sprintId": sprint_id, "teamId": team_id},
            include={"currentStatus": True, "assignee": {"include": {"user": True}}},
            order={"createdAt": "desc"},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # CREATE
    # ─────────────────────────────────────────────────────────────────────────

    async def create_sprint(
        self,
        team_id: int,
        name: str,
        goal: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ):
        logger.info(f"Creating sprint '{name}' for team {team_id}")
        return await self.db.sprint.create(
            data={
                "teamId": team_id,
                "name": name,
                "goal": goal,
                "startDate": start_date,
                "endDate": end_date,
                "status": SprintStatus.PLANNED.value,
            }
        )

    # ─────────────────────────────────────────────────────────────────────────
    # LIFECYCLE: START
    # ─────────────────────────────────────────────────────────────────────────

    async def start_sprint(
        self,
        sprint_id: int,
        team_id: int,
        goal: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ):
        """
        Transition a PLANNED sprint to ACTIVE.

        Enforces: only ONE active sprint per team at a time.
        Sets startDate to now() if not provided.
        """
        sprint = await self.require_sprint(sprint_id, team_id)

        if sprint.status == SprintStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sprint is already active.",
            )
        if sprint.status == SprintStatus.COMPLETED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot start a completed sprint.",
            )

        # Enforce only one active sprint per team
        active_sprint = await self.db.sprint.find_first(
            where={"teamId": team_id, "status": SprintStatus.ACTIVE.value}
        )
        if active_sprint and active_sprint.id != sprint_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sprint '{active_sprint.name}' is already active. Complete it first.",
            )

        update_data: dict = {
            "status": SprintStatus.ACTIVE.value,
            "startDate": start_date or datetime.now(timezone.utc),
        }
        if end_date:
            update_data["endDate"] = end_date
        if goal is not None:
            update_data["goal"] = goal

        updated = await self.db.sprint.update(
            where={"id": sprint_id},
            data=update_data,
            include={"tasks": {"include": {"currentStatus": True}}},
        )
        logger.info(f"Sprint {sprint_id} started for team {team_id}")
        return updated

    # ─────────────────────────────────────────────────────────────────────────
    # LIFECYCLE: COMPLETE
    # ─────────────────────────────────────────────────────────────────────────

    async def complete_sprint(
        self,
        sprint_id: int,
        team_id: int,
        rollover_sprint_id: Optional[int] = None,
    ):
        """
        Mark a sprint COMPLETED and handle incomplete tasks:
          - If rollover_sprint_id is given: move incomplete tasks to that sprint.
          - Otherwise: move incomplete tasks back to backlog (sprintId=null).

        'Incomplete' = any task whose currentStatus.category is NOT 'DONE'.
        """
        sprint = await self.require_sprint(sprint_id, team_id)

        if sprint.status != SprintStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only ACTIVE sprints can be completed.",
            )

        # Validate rollover target sprint
        if rollover_sprint_id is not None:
            rollover = await self.db.sprint.find_first(
                where={"id": rollover_sprint_id, "teamId": team_id}
            )
            if not rollover:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Rollover sprint not found.",
                )
            if rollover.status == SprintStatus.COMPLETED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot roll over to a completed sprint.",
                )

        # Find all incomplete tasks in this sprint
        tasks_in_sprint = await self.db.task.find_many(
            where={"sprintId": sprint_id, "teamId": team_id},
            include={"currentStatus": True},
        )

        incomplete_task_ids = [
            t.id
            for t in tasks_in_sprint
            if not t.currentStatus or t.currentStatus.category != "DONE"
        ]

        logger.info(
            f"Completing sprint {sprint_id}: {len(incomplete_task_ids)} incomplete tasks "
            f"→ {'sprint ' + str(rollover_sprint_id) if rollover_sprint_id else 'backlog'}"
        )

        # Move incomplete tasks
        if incomplete_task_ids:
            await self.db.task.update_many(
                where={"id": {"in": incomplete_task_ids}},
                data={"sprintId": rollover_sprint_id},  # None = backlog
            )

        # Mark sprint completed
        updated = await self.db.sprint.update(
            where={"id": sprint_id},
            data={
                "status": SprintStatus.COMPLETED.value,
                "endDate": datetime.now(timezone.utc),
            },
            include={"tasks": {"include": {"currentStatus": True}}},
        )
        return updated

    # ─────────────────────────────────────────────────────────────────────────
    # TASK ASSIGNMENT
    # ─────────────────────────────────────────────────────────────────────────

    async def assign_task_to_sprint(self, task_id: int, sprint_id: int, team_id: int):
        """Move a task into a sprint."""
        await self.require_sprint(sprint_id, team_id)
        task = await self.db.task.find_first(where={"id": task_id, "teamId": team_id})
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return await self.db.task.update(
            where={"id": task_id},
            data={"sprintId": sprint_id},
            include={"currentStatus": True},
        )

    async def unassign_task_from_sprint(self, task_id: int, team_id: int):
        """Remove a task from its sprint (send to backlog)."""
        task = await self.db.task.find_first(where={"id": task_id, "teamId": team_id})
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return await self.db.task.update(
            where={"id": task_id},
            data={"sprintId": None},
            include={"currentStatus": True},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # GENERIC UPDATE (for name/goal/dates only)
    # ─────────────────────────────────────────────────────────────────────────

    async def update_sprint(self, sprint_id: int, team_id: int, **kwargs):
        """Generic update for non-lifecycle fields (name, goal, dates)."""
        await self.require_sprint(sprint_id, team_id)

        update_data: dict = {}
        for field in ("name", "goal", "startDate", "endDate"):
            if field in kwargs and kwargs[field] is not None:
                update_data[field] = kwargs[field]

        if not update_data:
            return await self.require_sprint(sprint_id, team_id)

        return await self.db.sprint.update(
            where={"id": sprint_id},
            data=update_data,
            include={"tasks": {"include": {"currentStatus": True}}},
        )

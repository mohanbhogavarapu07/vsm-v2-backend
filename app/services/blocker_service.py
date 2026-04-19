"""
VSM Backend – Blocker Service (Prisma)
Handles creation, resolution, and listing of high-priority system blockers.
"""

import logging
from typing import List, Optional
from prisma import Prisma
from prisma.models import SystemBlocker

logger = logging.getLogger(__name__)

class BlockerService:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def create_blocker(
        self,
        team_id: int,
        title: str,
        description: str,
        blocker_type: str,
        task_id: Optional[int] = None,
        metadata: dict = None
    ) -> SystemBlocker:
        """
        Creates a new blocker record. 
        If a similar unresolved blocker exists for the same task/type, it updates it.
        """
        existing = await self._db.systemblocker.find_first(
            where={
                "teamId": team_id,
                "taskId": task_id,
                "type": blocker_type,
                "isResolved": False
            }
        )

        if existing:
            return await self._db.systemblocker.update(
                where={"id": existing.id},
                data={
                    "description": description,
                    "metadata": metadata or {},
                    "updatedAt": "now()" # Prisma handles this usually
                }
            )

        blocker = await self._db.systemblocker.create(
            data={
                "teamId": team_id,
                "taskId": task_id,
                "title": title,
                "description": description,
                "type": blocker_type,
                "metadata": metadata or {},
                "isResolved": False
            }
        )
        logger.info("system_blocker_created", id=blocker.id, team_id=team_id, type=blocker_type)
        return blocker

    async def resolve_blocker(self, blocker_id: int) -> Optional[SystemBlocker]:
        """Marks a blocker as resolved."""
        return await self._db.systemblocker.update(
            where={"id": blocker_id},
            data={"isResolved": True}
        )

    async def resolve_task_blockers(self, task_id: int):
        """Resolves all active blockers for a specific task."""
        await self._db.systemblocker.update_many(
            where={"taskId": task_id, "isResolved": False},
            data={"isResolved": True}
        )

    async def list_active_blockers(self, team_id: int) -> List[SystemBlocker]:
        """Returns all unresolved blockers for a team."""
        return await self._db.systemblocker.find_many(
            where={"teamId": team_id, "isResolved": False},
            order={"createdAt": "desc"}
        )

"""
VSM Backend – Transition Service (Prisma)
"""

import logging

from prisma import Prisma
from prisma.models import WorkflowTransition

from app.models.enums import TaskStatusCategory, ConditionOperator
from app.repositories.task_repository import TaskRepository

logger = logging.getLogger(__name__)


class TransitionService:
    def __init__(self, db: Prisma) -> None:
        self._task_repo = TaskRepository(db)

    async def evaluate_transition_conditions(
        self,
        transition: WorkflowTransition,
        available_signals: list[str],
    ) -> bool:
        conditions = transition.conditions or []
        if not conditions:
            return True

        results: list[bool] = []
        operators: list[str] = []

        for condition in conditions:
            satisfied = condition.conditionType in available_signals
            results.append(satisfied)
            operators.append(condition.operator)

        if not results:
            return True

        final = results[0]
        for i, op in enumerate(operators[1:], start=1):
            if op == ConditionOperator.AND.value:
                final = final and results[i]
            else:
                final = final or results[i]

        return final

    async def get_satisfied_transitions(
        self,
        team_id: int,
        from_status_id: int,
        available_signals: list[str],
    ) -> list[dict]:
        transitions = await self._task_repo.get_valid_transitions(
            team_id=team_id,
            from_status_id=from_status_id,
        )

        satisfied = []
        for t in transitions:
            conditions_met = await self.evaluate_transition_conditions(
                t, available_signals
            )
            satisfied.append({
                "transition_id": t.id,
                "to_status_id": t.toStatusId,
                "to_category": t.toCategory,
                "priority": t.priority,
                "requires_manual_approval": t.requiresManualApproval,
                "conditions_met": conditions_met,
            })

        return satisfied

    def map_event_types_to_signals(self, event_types: list[str]) -> list[str]:
        mapping = {
            "PR_CREATED": "PR_CREATED",
            "PR_MERGED": "PR_MERGED",
            "CI_STATUS_SUCCESS": "CI_PASSED",
            "CI_STATUS_FAILED": "CI_FAILED",
            "CHAT_MESSAGE": "COMMENT_ADDED",
        }
        return [mapping[e] for e in event_types if e in mapping]

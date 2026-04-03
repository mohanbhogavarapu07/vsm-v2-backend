"""
VSM Backend – Activity Repository (Prisma)

All DB interactions for TaskActivity, UnlinkedActivity,
ActivityTaskMappingLog, ChatMessage, NLPInsight, and NLPFeedback.
"""

import logging
from typing import Any

from prisma import Prisma
from prisma.models import (
    TaskActivity,
    UnlinkedActivity,
    ActivityTaskMappingLog,
    ChatMessage,
    NLPInsight,
    NLPFeedback,
)

from app.models.enums import (
    ActivityType,
    UnlinkedActivityType,
    UnlinkedActivityStatus,
    MappingMethod,
    DetectedIntent,
    FeedbackResult,
    CorrectedIntent,
)

logger = logging.getLogger(__name__)


class ActivityRepository:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    # ── TaskActivity ──────────────────────────────────────────────────────────

    async def create_activity(
        self,
        activity_type: ActivityType,
        metadata: dict,
        task_id: int | None = None,
        reference_id: str | None = None,
        event_log_id: int | None = None,
    ) -> TaskActivity:
        data: dict[str, Any] = {
            "activityType": activity_type.value,
            "metadata": metadata,
        }
        if task_id:
            data["taskId"] = task_id
        if reference_id:
            data["referenceId"] = reference_id
        if event_log_id:
            data["eventLogId"] = event_log_id

        return await self._db.taskactivity.create(data=data)

    async def list_activities_for_task(
        self, task_id: int, limit: int = 50
    ) -> list[TaskActivity]:
        return await self._db.taskactivity.find_many(
            where={"taskId": task_id},
            order={"createdAt": "desc"},
            take=limit,
        )

    # ── UnlinkedActivity ──────────────────────────────────────────────────────

    async def create_unlinked(
        self,
        activity_type: UnlinkedActivityType,
        branch_name: str | None = None,
        commit_message: str | None = None,
        reference_id: str | None = None,
        author_id: int | None = None,
    ) -> UnlinkedActivity:
        data: dict[str, Any] = {
            "activityType": activity_type.value,
            "status": UnlinkedActivityStatus.UNRESOLVED.value,
        }
        if branch_name:
            data["branchName"] = branch_name
        if commit_message:
            data["commitMessage"] = commit_message
        if reference_id:
            data["referenceId"] = reference_id
        if author_id:
            data["authorId"] = author_id

        return await self._db.unlinkedactivity.create(data=data)

    async def list_unresolved(self, limit: int = 100) -> list[UnlinkedActivity]:
        """Fetched by the AI resolver worker."""
        return await self._db.unlinkedactivity.find_many(
            where={"status": UnlinkedActivityStatus.UNRESOLVED.value},
            order={"createdAt": "asc"},
            take=limit,
        )

    async def update_unlinked_suggestion(
        self,
        ua_id: int,
        suggested_task_id: int,
        confidence_score: float,
        status: UnlinkedActivityStatus,
    ) -> None:
        await self._db.unlinkedactivity.update(
            where={"id": ua_id},
            data={
                "suggestedTaskId": suggested_task_id,
                "confidenceScore": confidence_score,
                "status": status.value,
            },
        )

    # ── ActivityTaskMappingLog ────────────────────────────────────────────────

    async def record_mapping(
        self,
        activity_id: int,
        task_id: int,
        mapping_method: MappingMethod,
        confidence_score: float | None = None,
    ) -> ActivityTaskMappingLog:
        data: dict[str, Any] = {
            "activityId": activity_id,
            "taskId": task_id,
            "mappingMethod": mapping_method.value,
        }
        if confidence_score is not None:
            data["confidenceScore"] = confidence_score

        return await self._db.activitytaskmappinglog.create(data=data)

    # ── ChatMessage ────────────────────────────────────────────────────────────

    async def create_chat_message(
        self,
        user_id: int,
        team_id: int,
        message: str,
        timestamp,
        platform_message_id: str | None = None,
    ) -> ChatMessage:
        data: dict[str, Any] = {
            "userId": user_id,
            "teamId": team_id,
            "message": message,
            "timestamp": timestamp,
        }
        if platform_message_id:
            data["platformMessageId"] = platform_message_id

        return await self._db.chatmessage.create(data=data)

    async def find_chat_message_by_platform_id(
        self, platform_message_id: str
    ) -> ChatMessage | None:
        return await self._db.chatmessage.find_unique(
            where={"platformMessageId": platform_message_id}
        )

    # ── NLPInsight ────────────────────────────────────────────────────────────

    async def create_nlp_insight(
        self,
        message_id: int,
        detected_intent: DetectedIntent,
        confidence_score: float,
        requires_confirmation: bool,
        context_snapshot: dict,
        task_id: int | None = None,
    ) -> NLPInsight:
        data: dict[str, Any] = {
            "messageId": message_id,
            "detectedIntent": detected_intent.value,
            "confidenceScore": confidence_score,
            "requiresConfirmation": requires_confirmation,
            "contextSnapshot": context_snapshot,
        }
        if task_id:
            data["taskId"] = task_id

        return await self._db.nlpinsight.create(data=data)

    async def list_insights_for_task(
        self, task_id: int, limit: int = 10
    ) -> list[NLPInsight]:
        return await self._db.nlpinsight.find_many(
            where={"taskId": task_id},
            order={"createdAt": "desc"},
            take=limit,
        )

    # ── NLPFeedback ───────────────────────────────────────────────────────────

    async def create_nlp_feedback(
        self,
        insight_id: int,
        user_id: int,
        feedback: FeedbackResult,
        corrected_intent: CorrectedIntent | None = None,
    ) -> NLPFeedback:
        data: dict[str, Any] = {
            "insightId": insight_id,
            "userId": user_id,
            "feedback": feedback.value,
        }
        if corrected_intent:
            data["correctedIntent"] = corrected_intent.value

        return await self._db.nlpfeedback.create(data=data)

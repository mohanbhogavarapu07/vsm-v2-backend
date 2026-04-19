"""
VSM Backend – Activity Repository (Prisma)

All DB interactions for TaskActivity, ChatMessage, NLPInsight, and NLPFeedback.
"""

import logging
from typing import Any

from prisma import Prisma, Json
from prisma.models import (
    TaskActivity,
    ChatMessage,
    NLPInsight,
    NLPFeedback,
)

from app.models.enums import (
    ActivityType,
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
            "metadata": Json(metadata),
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
            "contextSnapshot": Json(context_snapshot),
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

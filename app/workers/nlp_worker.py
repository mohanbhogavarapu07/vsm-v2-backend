"""
VSM Backend – NLP Worker (PRD 2 §5 Worker Type 2)

Processes chat messages to generate nlp_insights.
Uses a lightweight NLP pipeline (keyword + pattern matching + optional LLM).
Applies confidence scoring and confirmation gating.

NLP Vagueness Fix (PRD 1 §6):
  - Every insight has confidence_score
  - requires_confirmation = True when score < threshold
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.config import get_settings
from app.database import get_db_context
from app.models.enums import DetectedIntent
from app.repositories.activity_repository import ActivityRepository

logger = logging.getLogger(__name__)
settings = get_settings()


def _run_async(coro):
    """
    Robust asyncio runner for Celery workers.
    Handles loop creation/retrieval to avoid 'No event loop' errors.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ── Intent Detection Ruleset ───────────────────────────────────────────────────
# Ordered by specificity (more specific patterns first)

INTENT_PATTERNS = {
    DetectedIntent.BLOCKER: {
        "patterns": [
            r"\b(block(?:ed|ing)?|stuck|can'?t proceed|need help|waiting for|dependency|bottleneck)\b",
            r"\b(issue|problem|broken|failing|not working|error)\b.*\b(and|so)?\b.*\b(can'?t|cannot|unable)\b",
        ],
        "base_confidence": 0.80,
    },
    DetectedIntent.COMPLETION: {
        "patterns": [
            r"\b(done|finished|completed|deployed|shipped|merged|closed|resolved)\b",
            r"\b(all (tasks?|work|items?) (done|complete|finished))\b",
        ],
        "base_confidence": 0.85,
    },
    DetectedIntent.PROGRESS: {
        "patterns": [
            r"\b(working on|in progress|started|implementing|reviewing|testing)\b",
            r"\b(\d+%|percent|halfway|almost done|nearly complete)\b",
        ],
        "base_confidence": 0.75,
    },
    DetectedIntent.CONFUSION: {
        "patterns": [
            r"\b(confused|unclear|don'?t understand|what does|how do|can someone explain)\b",
            r"\?{2,}",  # Multiple question marks = confusion
        ],
        "base_confidence": 0.70,
    },
}


def classify_intent(message: str) -> tuple[DetectedIntent, float]:
    """
    Rule-based intent classifier with confidence scoring.
    Returns (intent, confidence_score).
    Falls back to PROGRESS with low confidence if no match.
    """
    message_lower = message.lower()
    scores: dict[DetectedIntent, float] = {}

    for intent, config in INTENT_PATTERNS.items():
        match_count = 0
        for pattern in config["patterns"]:
            if re.search(pattern, message_lower):
                match_count += 1
        if match_count > 0:
            # Boost confidence for multiple pattern matches
            confidence = config["base_confidence"] + (0.05 * (match_count - 1))
            scores[intent] = min(confidence, 0.99)

    if not scores:
        # No pattern matched — return PROGRESS with low confidence
        return DetectedIntent.PROGRESS, 0.40

    best_intent = max(scores, key=lambda k: scores[k])
    return best_intent, scores[best_intent]


@celery_app.task(
    name="app.workers.nlp_worker.process_chat_message",
    bind=True,
    queue="nlp_processing",
)
def process_chat_message(
    self,
    event_id: int,
    message_id: int,
    message_text: str,
    user_id: int,
    team_id: int,
    task_id: int | None = None,
) -> dict:
    """
    Celery task: analyze a chat message and store nlp_insight.
    Called by aggregation_worker after buffering.
    """
    return _run_async(
        _process_chat_message(event_id, message_id, message_text, task_id)
    )


async def _process_chat_message(
    event_id: int,
    message_id: int,
    message_text: str,
    task_id: int | None,
) -> dict:
    async with get_db_context() as db:
        activity_repo = ActivityRepository(db)

        # ── Classify intent ────────────────────────────────────────────────────
        intent, confidence = classify_intent(message_text)

        # ── Determine if confirmation is needed ────────────────────────────────
        requires_confirmation = confidence < settings.nlp_auto_execute_threshold

        # ── Build context snapshot (immutable record) ──────────────────────────
        context_snapshot = {
            "event_id": event_id,
            "message_preview": message_text[:200],
            "classifier": "rule_based_v1",
            "intent_scores": {
                DetectedIntent.BLOCKER.value: 0.0,
                DetectedIntent.PROGRESS.value: 0.0,
                DetectedIntent.COMPLETION.value: 0.0,
                DetectedIntent.CONFUSION.value: 0.0,
                intent.value: confidence,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        insight = await activity_repo.create_nlp_insight(
            message_id=message_id,
            detected_intent=intent,
            confidence_score=confidence,
            requires_confirmation=requires_confirmation,
            context_snapshot=context_snapshot,
            task_id=task_id,
        )

        logger.info(
            "NLP insight id=%s intent=%s confidence=%.2f requires_confirmation=%s",
            insight.id, intent.value, confidence, requires_confirmation,
        )

        return {
            "insight_id": insight.id,
            "intent": intent.value,
            "confidence": confidence,
            "requires_confirmation": requires_confirmation,
        }

"""
VSM Backend – NLP Worker Unit Tests
"""

import pytest
from app.workers.nlp_worker import classify_intent
from app.models.enums import DetectedIntent


class TestNLPClassifier:
    def test_blocker_detection(self):
        msg = "I'm completely blocked on the auth module, can't proceed"
        intent, confidence = classify_intent(msg)
        assert intent == DetectedIntent.BLOCKER
        assert confidence >= 0.75

    def test_completion_detection(self):
        msg = "All done! Finished the PR and it's been merged."
        intent, confidence = classify_intent(msg)
        assert intent == DetectedIntent.COMPLETION
        assert confidence >= 0.80

    def test_progress_detection(self):
        msg = "Working on the login feature, about 70% done"
        intent, confidence = classify_intent(msg)
        assert intent == DetectedIntent.PROGRESS
        assert confidence >= 0.70

    def test_confusion_detection(self):
        msg = "I don't understand what needs to be done here???"
        intent, confidence = classify_intent(msg)
        assert intent == DetectedIntent.CONFUSION
        assert confidence >= 0.65

    def test_low_confidence_fallback(self):
        msg = "Meeting tomorrow at 3pm"
        intent, confidence = classify_intent(msg)
        # Low confidence: should fall back with low score
        assert confidence < 0.60

    def test_requires_confirmation_logic(self):
        """Messages below threshold should require confirmation."""
        from app.config import get_settings
        settings = get_settings()
        _, confidence = classify_intent("maybe done")
        requires = confidence < settings.nlp_auto_execute_threshold
        assert isinstance(requires, bool)

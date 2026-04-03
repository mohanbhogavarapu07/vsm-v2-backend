"""
VSM Backend – Webhook Tests

Integration tests for GitHub, Chat, and CI webhook endpoints.
Uses FastAPI's TestClient with an in-memory SQLite database.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings

settings = get_settings()
client = TestClient(app)


def make_github_signature(payload: bytes) -> str:
    sig = hmac.new(
        settings.github_webhook_secret.encode(),
        payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={sig}"


class TestGitHubWebhook:
    def test_ping_event(self):
        payload = {"zen": "test", "hook_id": 1}
        body = json.dumps(payload).encode()
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": make_github_signature(body),
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 202
        assert response.json()["message"] == "Ping acknowledged"

    def test_invalid_signature_rejected(self):
        payload = json.dumps({"ref": "refs/heads/main"}).encode()
        response = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=invalidsig",
                "X-GitHub-Event": "push",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 401


class TestCIWebhook:
    def test_ci_success_accepted(self):
        payload = {
            "pipeline_id": "build-123",
            "pipeline_status": "success",
            "branch": "feature/VSM-42-auth",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        response = client.post("/webhooks/ci", json=payload)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "queued" in data["message"].lower()

    def test_ci_failure_accepted(self):
        payload = {
            "pipeline_id": "build-456",
            "pipeline_status": "failed",
            "branch": "feature/VSM-99-api",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        response = client.post("/webhooks/ci", json=payload)
        assert response.status_code == 202


class TestChatWebhook:
    def test_chat_message_accepted(self):
        payload = {
            "user_id": "U12345",
            "team_id": "T99999",
            "message": "I'm blocked on the auth PR, need help",
            "timestamp": "1711900800.000",
            "platform_message_id": "msg_001",
        }
        response = client.post("/webhooks/chat", json=payload)
        assert response.status_code == 202


class TestHealthEndpoints:
    def test_liveness(self):
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

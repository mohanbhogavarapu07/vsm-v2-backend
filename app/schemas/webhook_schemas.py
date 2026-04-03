"""
VSM Backend – Webhook Pydantic Schemas

Input validation for all external webhook payloads.
Each schema normalizes source-specific data into a common format.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── GitHub Webhook ─────────────────────────────────────────────────────────────

class GitHubCommit(BaseModel):
    id: str
    message: str
    author_name: str | None = None
    author_email: str | None = None
    timestamp: str | None = None


class GitHubPullRequest(BaseModel):
    number: int
    title: str
    state: str
    merged: bool = False
    base_branch: str | None = None
    head_branch: str | None = None


class GitHubWebhookPayload(BaseModel):
    """Normalized GitHub webhook payload."""
    ref: str | None = None                         # e.g. "refs/heads/feature/auth"
    repository: dict[str, Any] = Field(default_factory=dict)
    sender: dict[str, Any] = Field(default_factory=dict)
    commits: list[GitHubCommit] = Field(default_factory=list)
    pull_request: GitHubPullRequest | None = None
    action: str | None = None                      # opened, closed, merged, etc.

    @property
    def branch_name(self) -> str | None:
        if self.ref and self.ref.startswith("refs/heads/"):
            return self.ref.removeprefix("refs/heads/")
        if self.pull_request and self.pull_request.head_branch:
            return self.pull_request.head_branch
        return None

    @property
    def event_reference_id(self) -> str | None:
        if self.pull_request:
            return str(self.pull_request.number)
        if self.commits:
            return self.commits[0].id
        return None


# ── Chat / Slack Webhook ───────────────────────────────────────────────────────

class ChatWebhookPayload(BaseModel):
    """Normalized Slack/Teams message payload."""
    user_id: str
    team_id: str
    message: str
    timestamp: str
    platform_message_id: str | None = None
    thread_ts: str | None = None           # Slack thread identifier
    channel_id: str | None = None


# ── CI/CD Webhook ──────────────────────────────────────────────────────────────

class CIWebhookPayload(BaseModel):
    """Normalized CI/CD pipeline event payload."""
    pipeline_id: str
    pipeline_status: str                  # success, failed, running, etc.
    branch: str | None = None
    commit_sha: str | None = None
    triggered_by: str | None = None
    test_results: dict[str, Any] | None = None
    duration_seconds: int | None = None
    timestamp: str


# ── Generic Event Response ─────────────────────────────────────────────────────

class WebhookReceivedResponse(BaseModel):
    """Standard response for all webhook endpoints."""
    status: str = "accepted"
    event_id: int
    message: str = "Event queued for processing"

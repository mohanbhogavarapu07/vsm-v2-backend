"""
VSM Backend – Python Enums

These mirror the Prisma schema ENUM types.
Used in type hints, Pydantic schemas, and business logic.

Prisma Client generates its own enum types (prisma.enums.*),
but we keep Python enums here for IDE support and validation.
"""

import enum


class TaskStatusCategory(str, enum.Enum):
    BACKLOG = "BACKLOG"
    ACTIVE = "ACTIVE"
    REVIEW = "REVIEW"
    VALIDATION = "VALIDATION"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class SprintStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class ConditionType(str, enum.Enum):
    PR_CREATED = "PR_CREATED"
    PR_MERGED = "PR_MERGED"
    CI_PASSED = "CI_PASSED"
    CI_FAILED = "CI_FAILED"
    COMMENT_ADDED = "COMMENT_ADDED"
    QA_APPROVED = "QA_APPROVED"
    DOCS_UPDATED = "DOCS_UPDATED"
    SECURITY_SCAN_PASSED = "SECURITY_SCAN_PASSED"


class ConditionOperator(str, enum.Enum):
    AND = "AND"
    OR = "OR"


class EventType(str, enum.Enum):
    GIT_COMMIT = "GIT_COMMIT"
    PR_CREATED = "PR_CREATED"
    PR_MERGED = "PR_MERGED"
    CI_STATUS = "CI_STATUS"
    CHAT_MESSAGE = "CHAT_MESSAGE"


class EventSource(str, enum.Enum):
    GITHUB = "GITHUB"
    SLACK = "SLACK"
    CI = "CI"
    SYSTEM = "SYSTEM"


class QueueStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WindowStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ActivityType(str, enum.Enum):
    COMMIT = "COMMIT"
    PR = "PR"
    CI = "CI"
    COMMENT = "COMMENT"


class UnlinkedActivityType(str, enum.Enum):
    COMMIT = "COMMIT"
    PR = "PR"


class UnlinkedActivityStatus(str, enum.Enum):
    UNRESOLVED = "UNRESOLVED"
    AUTO_LINKED = "AUTO_LINKED"
    USER_CONFIRMED = "USER_CONFIRMED"
    IGNORED = "IGNORED"


class DetectedIntent(str, enum.Enum):
    BLOCKER = "BLOCKER"
    PROGRESS = "PROGRESS"
    COMPLETION = "COMPLETION"
    CONFUSION = "CONFUSION"


class FeedbackResult(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CorrectedIntent(str, enum.Enum):
    BLOCKER = "BLOCKER"
    PROGRESS = "PROGRESS"
    NONE = "NONE"


class MappingMethod(str, enum.Enum):
    MANUAL = "MANUAL"
    AI_AUTO = "AI_AUTO"
    BRANCH_PATTERN = "BRANCH_PATTERN"


class DecisionSource(str, enum.Enum):
    RULE_ENGINE = "RULE_ENGINE"
    AI_MODEL = "AI_MODEL"



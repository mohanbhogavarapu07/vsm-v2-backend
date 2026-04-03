"""
VSM Backend – Event Pydantic Schemas

Internal schemas for event_log and queue management.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EventLogSchema(BaseModel):
    id: int
    event_type: str
    source: str
    reference_id: str | None
    payload: dict[str, Any]
    event_timestamp: datetime
    ingestion_timestamp: datetime
    processed: bool
    correlation_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EventQueueSchema(BaseModel):
    id: int
    event_id: int
    status: str
    retry_count: int
    scheduled_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AggregationWindowSchema(BaseModel):
    id: int
    correlation_id: str
    start_time: datetime
    end_time: datetime | None
    aggregated_events: list[int]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AITriggerPayload(BaseModel):
    """
    Payload sent from the backend to vsm-ai-agent for inference.
    Contains aggregated context from the buffering window.
    """
    task_id: int
    team_id: int
    correlation_id: str
    aggregated_events: list[dict[str, Any]]
    window_start: datetime
    window_end: datetime

"""
VSM Backend – Webhook Router (DEPRECATED - Consolidated)

IMPORTANT: This router is deprecated. All webhook handling has been consolidated
into /app/app/api/webhooks/github.py to avoid duplicate route conflicts.

The primary webhook endpoint is now:
  POST /webhooks/github (in /app/app/api/webhooks/github.py)

This file is kept for reference only and should not be imported in main.py.
"""

from fastapi import APIRouter

logger = None
router = APIRouter(prefix="/webhooks-deprecated", tags=["deprecated"])

# This route is intentionally disabled to prevent conflicts
# All webhook processing now uses the aggregation-based flow in:
# /app/app/api/webhooks/github.py → event_processor.py → aggregation_worker.py → ai_trigger_worker.py

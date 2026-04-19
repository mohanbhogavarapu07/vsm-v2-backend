"""
VSM Backend – Analytics Intelligence API

Exposes GET /analytics/intelligence?team_id=<id>

Returns the full three-layer intelligence payload:
  - diagnostic  : WHY things happened
  - predictive  : WHAT will happen
  - prescriptive: WHAT to do

Read-only. Does NOT mutate any state. Safe to call concurrently.
"""

import logging
from fastapi import APIRouter, Depends, Query
from prisma import Prisma

from app.database import get_db
from app.utils.permissions import require_permission
from app.services.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"], redirect_slashes=False)


@router.get(
    "/intelligence",
    summary="AI Intelligence payload — diagnostic, predictive, prescriptive [requires READ_TASK]",
    response_model=None,  # dynamic dict, validated by AnalyticsService
)
async def get_intelligence(
    team_id: int = Query(..., description="Team ID to compute intelligence for"),
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db),
) -> dict:
    """
    Returns the full three-layer AI intelligence payload for a team.
    All metrics derived from live database data — no mock values.
    Cached results are NOT used so insights are always fresh.
    """
    svc = AnalyticsService(db)
    try:
        result = await svc.get_full_intelligence(team_id)
        return result
    except Exception as exc:
        logger.exception("Analytics intelligence computation failed for team %s: %s", team_id, exc)
        # Return a safe empty shell rather than a 500 so the frontend degrades gracefully
        from datetime import datetime, timezone
        return {
            "diagnostic": {"insights": [], "velocity_trend": "unknown", "velocity_change_pct": 0},
            "predictive": {"sprint_completion_probability": 0, "at_risk_tasks": [], "predicted_next_velocity": 0},
            "prescriptive": {"recommendations": [], "recommendation_count": 0, "critical_count": 0, "high_count": 0},
            "efficiency": {"cycle_time_days": 0, "lead_time_days": 0, "wip_count": 0, "flow_efficiency_pct": 0},
            "ai_metrics": {"total_decisions": 0, "ai_success_rate_pct": 0, "time_saved_hours": 0},
            "blocker_intelligence": {"total_blockers": 0, "avg_resolution_time_hours": 0, "most_common_types": []},
            "velocity_history": [],
            "error": str(exc),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

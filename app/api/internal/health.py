"""
VSM Backend – Health Check (Prisma)
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from prisma import Prisma

from app.database import get_db
from app.config import get_settings

router = APIRouter(prefix="/health", tags=["health"])
settings = get_settings()
_start_time = time.time()


@router.get("/live", summary="Liveness probe")
async def liveness() -> dict:
    return {
        "status": "alive",
        "app": settings.app_name,
        "version": settings.app_version,
        "orm": "Prisma",
        "database": "Supabase (PostgreSQL)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready", summary="Readiness probe")
async def readiness(db: Prisma = Depends(get_db)) -> dict:
    try:
        # Use Prisma to verify DB connectivity
        await db.workflowstage.count()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    return {
        "status": "ready" if db_status == "ok" else "not_ready",
        "uptime_seconds": round(time.time() - _start_time, 2),
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

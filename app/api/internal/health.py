"""
VSM Backend – Health Check (Prisma)

OPTIMIZED: Added cache performance monitoring endpoint.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from prisma import Prisma

from app.database import get_db
from app.config import get_settings
from app.utils.cache import task_cache, team_cache, github_cache, sprint_cache, permission_cache

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


@router.get("/cache-stats", summary="Cache performance statistics")
async def cache_stats() -> dict:
    """
    Returns cache hit/miss statistics for all cache instances.
    Useful for monitoring cache effectiveness and optimization impact.
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(time.time() - _start_time, 2),
        "caches": {
            "tasks": {
                "ttl_seconds": task_cache.ttl,
                **task_cache.get_stats()
            },
            "teams": {
                "ttl_seconds": team_cache.ttl,
                **team_cache.get_stats()
            },
            "github": {
                "ttl_seconds": github_cache.ttl,
                **github_cache.get_stats()
            },
            "sprints": {
                "ttl_seconds": sprint_cache.ttl,
                **sprint_cache.get_stats()
            },
            "permissions": {
                "ttl_seconds": permission_cache.ttl,
                **permission_cache.get_stats()
            }
        },
        "summary": {
            "total_hits": sum([
                task_cache._hits,
                team_cache._hits,
                github_cache._hits,
                sprint_cache._hits,
                permission_cache._hits
            ]),
            "total_misses": sum([
                task_cache._misses,
                team_cache._misses,
                github_cache._misses,
                sprint_cache._misses,
                permission_cache._misses
            ]),
            "total_entries": sum([
                len(task_cache._cache),
                len(team_cache._cache),
                len(github_cache._cache),
                len(sprint_cache._cache),
                len(permission_cache._cache)
            ])
        }
    }


@router.get("/ai-agent", summary="AI Agent connectivity check")
async def ai_agent_health() -> dict:
    """
    Checks connectivity and health of the AI agent service.
    Used to verify webhook → AI agent flow is operational.
    """
    import httpx
    
    ai_agent_url = settings.ai_agent_url
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try to reach the AI agent health endpoint
            response = await client.get(f"{ai_agent_url}/health", timeout=5.0)
            
            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "ai_agent_url": ai_agent_url,
                    "response_time_ms": response.elapsed.total_seconds() * 1000,
                    "ai_agent_response": response.json() if response.headers.get("content-type", "").startswith("application/json") else None
                }
            else:
                return {
                    "status": "unhealthy",
                    "ai_agent_url": ai_agent_url,
                    "error": f"HTTP {response.status_code}",
                    "warning": "AI agent may not process webhook events correctly"
                }
    except httpx.ConnectError:
        return {
            "status": "unreachable",
            "ai_agent_url": ai_agent_url,
            "error": "Connection refused - AI agent not running",
            "warning": "Webhook events will be marked as BLOCKED"
        }
    except httpx.TimeoutException:
        return {
            "status": "timeout",
            "ai_agent_url": ai_agent_url,
            "error": "Request timeout (>5s)",
            "warning": "AI agent may be overloaded"
        }
    except Exception as e:
        return {
            "status": "error",
            "ai_agent_url": ai_agent_url,
            "error": str(e),
            "warning": "AI agent health check failed"
        }

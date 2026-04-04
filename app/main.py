"""
VSM Backend – FastAPI Application Entry Point (Prisma + Supabase)

Wires together all routers, middleware, and Prisma lifecycle events.
Prisma connects at startup and disconnects gracefully at shutdown.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.database import connect_prisma, disconnect_prisma
from app.api.webhooks.github import router as github_router
from app.api.webhooks.chat import router as chat_router
from app.api.webhooks.ci import router as ci_router
from app.api.internal.tasks import router as tasks_router
from app.api.internal.health import router as health_router
from app.api.internal.rbac import router as rbac_router
from app.api.internal.sprints import router as sprints_router
from app.api.internal.github_integration import router as github_integration_router
from app.utils.permission_seed import seed_permissions

settings = get_settings()
cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    Handles Prisma connect/disconnect around the application lifetime.
    """
    # ── Startup ────────────────────────────────────────────────────────────────
    logger.info("Connecting Prisma to Supabase...")
    await connect_prisma()
    logger.info("Prisma connected. VSM Backend is ready.")
    try:
        from app.database import get_prisma
        await seed_permissions(get_prisma())
        logger.info("Seeded global permissions")
    except Exception:
        logger.exception("Failed to seed permissions")

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    logger.info("Disconnecting Prisma...")
    await disconnect_prisma()
    logger.info("VSM Backend shut down cleanly.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "VSM Backend — Event-Driven Workflow Engine.\n\n"
            "Database: **Supabase (PostgreSQL)** via **Prisma ORM**.\n\n"
            "Ingests GitHub, Slack, and CI events. "
            "Drives AI-orchestrated task status transitions."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS & Compression ─────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # ── Routers ────────────────────────────────────────────────────────────────
    app.include_router(health_router)
    app.include_router(github_router)
    app.include_router(chat_router)
    app.include_router(ci_router)
    app.include_router(tasks_router)
    app.include_router(rbac_router)
    app.include_router(sprints_router)
    app.include_router(github_integration_router)

    from app.api.internal.auth import router as auth_router
    app.include_router(auth_router)

    @app.get("/", tags=["root"])
    async def root():
        return {
            "app": settings.app_name,
            "version": settings.app_version,
            "database": "Supabase (PostgreSQL)",
            "orm": "Prisma Client Python",
            "docs": "/docs",
        }

    logger.info("VSM Backend initialized with Prisma + Supabase")
    return app


app = create_app()

"""
VSM Backend – Prisma Client Singleton (Supabase)

Replaces SQLAlchemy engine + session factory.
Prisma Client Python manages the connection pool internally.

Usage in FastAPI:
    db: Prisma = Depends(get_db)

Usage in Celery workers (sync context):
    async with get_db_context() as db:
        ...
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from prisma import Prisma

logger = logging.getLogger(__name__)

# ── Singleton Prisma client ────────────────────────────────────────────────────
_prisma_client: Prisma | None = None


def _restore_real_stdio():
    """
    Celery replaces sys.stdout/stderr with LoggingProxy objects that lack
    fileno(). Prisma's query engine subprocess needs real file descriptors.

    This function temporarily restores real stdout/stderr for Prisma's
    subprocess.Popen call. Safe to call outside Celery (no-op).
    """
    if not hasattr(sys.stdout, 'fileno'):
        sys.stdout = sys.__stdout__
    if not hasattr(sys.stderr, 'fileno'):
        sys.stderr = sys.__stderr__

    # Also ensure stdout has fileno by testing it
    try:
        sys.stdout.fileno()
    except Exception:
        sys.stdout = open(os.devnull, 'w')

    try:
        sys.stderr.fileno()
    except Exception:
        sys.stderr = open(os.devnull, 'w')


async def connect_prisma() -> None:
    """Connect the Prisma client. Called once at FastAPI startup."""
    global _prisma_client
    _prisma_client = Prisma()
    await _prisma_client.connect()
    logger.info("Prisma client connected to Supabase")


async def disconnect_prisma() -> None:
    """Disconnect the Prisma client. Called at FastAPI shutdown."""
    global _prisma_client
    if _prisma_client and _prisma_client.is_connected():
        await _prisma_client.disconnect()
        logger.info("Prisma client disconnected")


def get_prisma() -> Prisma:
    """
    Returns the singleton Prisma client.
    Raises RuntimeError if called before connect_prisma().
    """
    if _prisma_client is None or not _prisma_client.is_connected():
        raise RuntimeError("Prisma client is not connected. Call connect_prisma() first.")
    return _prisma_client


# ── FastAPI Dependency ─────────────────────────────────────────────────────────
async def get_db() -> Prisma:
    """
    FastAPI dependency returning the connected Prisma client.
    Does NOT manage connection lifecycle — that's handled by lifespan events.

    Usage:
        @router.get("/")
        async def endpoint(db: Prisma = Depends(get_db)):
            ...
    """
    return get_prisma()


# ── Async Context Manager for Celery Workers ───────────────────────────────────
@asynccontextmanager
async def get_db_context() -> AsyncGenerator[Prisma, None]:
    """
    Async context manager for use in Celery workers and scripts.
    Creates its own Prisma connection, independent of the FastAPI singleton.

    Handles Celery's LoggingProxy stdout replacement that breaks
    Prisma's subprocess spawning on Windows.

    Usage:
        async with get_db_context() as db:
            await db.eventlog.find_many(...)
    """
    # Fix Celery's LoggingProxy before Prisma spawns its query engine
    _restore_real_stdio()

    client = Prisma()
    try:
        await client.connect()
        yield client
    finally:
        if client.is_connected():
            await client.disconnect()

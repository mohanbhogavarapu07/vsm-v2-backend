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
import asyncio
import random
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from prisma import Prisma

logger = logging.getLogger(__name__)

# ── Singleton Prisma client (FastAPI) ──────────────────────────────────────────
_prisma_client: Prisma | None = None

# ── Singleton Prisma client (Celery Workers) ───────────────────────────────────
# We keep a separate singleton for workers to ensure clear lifecycle management
# in process-forked environments like Celery.
_worker_prisma_client: Prisma | None = None
_worker_prisma_loop: asyncio.AbstractEventLoop | None = None


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
    logger.info("Prisma client connected to Supabase (FastAPI)")


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
    Maintains a persistent Prisma connection within the process to avoid
    connection churn and heavy query-engine startup overhead.

    Includes exponential backoff with jitter to handle P1001 (pool saturation).

    Usage:
        async with get_db_context() as db:
            await db.eventlog.find_many(...)
    """
    global _worker_prisma_client, _worker_prisma_loop
    
    # Update stdio for Celery
    _restore_real_stdio()
    
    try:
        current_loop = asyncio.get_event_loop()
    except RuntimeError:
        # No loop in this thread, create one
        current_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(current_loop)

    # 1. Loop Mismatch Guard
    # If the singleton was created on a different event loop (e.g. after a
    # Celery retry on a new thread), discard it and start fresh. Reusing a client
    # bound to a dead loop causes the 'bound to a different event loop' RuntimeError.
    if _worker_prisma_client is not None and _worker_prisma_loop is not current_loop:
        logger.warning(
            "Prisma worker client loop mismatch. Client loop: %s, Current loop: %s. Recreating client.",
            id(_worker_prisma_loop), id(current_loop)
        )
        # Attempt a graceful disconnect if the old loop is somehow alive, 
        # but usually we just drop it because the loop is often already closed/dead.
        _worker_prisma_client = None
        _worker_prisma_loop = None

    if _worker_prisma_client is None:
        _worker_prisma_client = Prisma()
        _worker_prisma_loop = current_loop

    max_retries = 5
    base_delay = 1.0  # seconds

    for attempt in range(max_retries):
        try:
            if not _worker_prisma_client.is_connected():
                await _worker_prisma_client.connect()
                logger.info("Worker Prisma client connected (Persistent)")
            
            yield _worker_prisma_client
            return # Success, exit the loop after yielded content finishes

        except Exception as e:
            # P1001 is common when pgbouncer is full
            error_str = str(e)
            is_connection_error = "P1001" in error_str or "Can't reach database" in error_str
            
            if is_connection_error and attempt < max_retries - 1:
                # Exponential backoff with jitter
                delay = (base_delay * (2 ** attempt)) + (random.uniform(0, 1.0))
                logger.warning(
                    "Database connection failed (Attempt %d/%d). Retrying in %.2fs... Error: %s",
                    attempt + 1, max_retries, delay, error_str
                )
                await asyncio.sleep(delay)
            else:
                logger.error("Persistent worker connection failed after %d attempts: %s", attempt + 1, e)
                raise
    
    # We never actually disconnect here. The connection persists for the lifetime 
    # of the worker process (Celery prefork worker or solo worker).


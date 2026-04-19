import logging
import json
import os
import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Use CELERY_BROKER_URL as fallback if REDIS_URL is not explicitly set
redis_url = os.getenv("REDIS_URL", os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))

async def publish_event(team_id: int, event_type: str, payload: dict) -> None:
    """
    Publishes a JSON serialized event to a team-specific Redis channel.
    Called primarily from Celery background workers.
    """
    try:
        # Create an ephemeral client for publishing
        client = redis.from_url(redis_url)
        message = json.dumps({"type": event_type, "payload": payload})
        channel = f"team_events:{team_id}"
        await client.publish(channel, message)
    except Exception as e:
        logger.error(f"Failed to publish event to {channel}: {e}")
    finally:
        await client.aclose()

async def get_team_event_subscriber(team_id: int):
    """
    Returns an async Redis client and a pubsub subscriber object.
    Hooked up by FastAPI Generator routes for Server-Sent Events.
    """
    client = redis.from_url(redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(f"team_events:{team_id}")
    return client, pubsub

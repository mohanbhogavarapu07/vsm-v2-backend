import asyncio
from datetime import datetime, timezone
from prisma import Prisma
from app.repositories.event_repository import EventRepository
from app.models.enums import EventType, EventSource

async def verify_fix():
    db = Prisma()
    await db.connect()
    repo = EventRepository(db)
    
    # Sample GitHub-like payload
    payload = {
        "action": "opened",
        "pull_request": {
            "id": 123456,
            "number": 1,
            "title": "Fix bug",
            "user": {"login": "dev"}
        },
        "repository": {"id": 987654, "name": "repo"},
        "installation": {"id": 112233}
    }
    
    try:
        print("Attempting to create event with fixed repository code...")
        event = await repo.create_event(
            event_type=EventType.PR_CREATED,
            source=EventSource.GITHUB,
            payload=payload,
            event_timestamp=datetime.now(timezone.utc),
            installation_id=112233,
            repository_id=987654
        )
        print(f"SUCCESS! Event created with ID: {event.id}")
    except Exception as e:
        print(f"FAILED! Error: {e}")
    finally:
        await db.disconnect()

if __name__ == "__main__":
    asyncio.run(verify_fix())

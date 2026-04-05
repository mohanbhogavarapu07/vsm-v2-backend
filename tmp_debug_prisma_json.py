import asyncio
import json
from datetime import datetime, timezone
from prisma import Prisma, Json
from app.models.enums import EventType, EventSource

async def main():
    db = Prisma()
    await db.connect()
    
    payload = {"test": "data", "num": 1, "bool": True}
    
    try:
        # Try raw dict
        print("Testing raw dict...")
        event = await db.eventlog.create(
            data={
                "eventType": "GIT_COMMIT",
                "source": "GITHUB",
                "payload": payload,
                "eventTimestamp": datetime.now(timezone.utc),
            }
        )
        print(f"Success with raw dict: {event.id}")
    except Exception as e:
        print(f"Failed with raw dict: {e}")
        
    try:
        # Try with Json wrapper
        print("\nTesting with Json wrapper...")
        event = await db.eventlog.create(
            data={
                "eventType": "GIT_COMMIT",
                "source": "GITHUB",
                "payload": Json(payload),
                "eventTimestamp": datetime.now(timezone.utc),
            }
        )
        print(f"Success with Json wrapper: {event.id}")
    except Exception as e:
        print(f"Failed with Json wrapper: {e}")
        
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

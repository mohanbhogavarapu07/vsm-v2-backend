import asyncio
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from app.services.pubsub import get_team_event_subscriber

router = APIRouter(prefix="/events", tags=["events"])

@router.get("/stream")
async def stream_events(request: Request, team_id: int = Query(...), user_id: int = Query(None)):
    """
    Server-Sent Events endpoint.
    Maintains an open WebSocket-like HTTP stream that yields Redis broadcasts indefinitely.
    """
    async def event_generator():
        client, pubsub = await get_team_event_subscriber(team_id)
        try:
            # Yield initial connection ping
            yield "data: {\"type\": \"CONNECTED\"}\n\n"
            
            while True:
                # Break if the browser disconnects
                if await request.is_disconnected():
                    break
                    
                # Poll Redis
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                
                if message and message['data']:
                    data = message['data'].decode('utf-8')
                    yield f"data: {data}\n\n"
                    
                # Give control back to event loop briefly
                await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            pass
        finally:
            # Clean up Redis subscription immediately when the browser leaves
            await pubsub.unsubscribe()
            await client.aclose()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

from fastapi import APIRouter, Depends, HTTPException
from prisma.models import SystemNotification
from typing import List, Any
from app.database import get_db

router = APIRouter(prefix="/teams/{team_id}/notifications", tags=["notifications"])

@router.get("", response_model=List[Any], summary="Get System Notifications for a team")
async def get_notifications(team_id: int, db=Depends(get_db)):
    """Fetch all systemic notifications and alerts for a specific team."""
    notifications = await db.systemnotification.find_many(
        where={
            "teamId": team_id,
            "sourceType": "INFO"
        },
        order={"createdAt": "desc"},
        take=50
    )
    # Return as dict to avoid rigid Pydantic issues if schema changes
    return [n.model_dump() for n in notifications]

@router.post("/{notification_id}/read", summary="Mark a notification as read")
async def mark_notification_read(team_id: int, notification_id: int, db=Depends(get_db)):
    """Marks a single System Notification alert as having been read by the Scrum Master."""
    notification = await db.systemnotification.find_unique(where={"id": notification_id})
    if not notification or notification.teamId != team_id:
        raise HTTPException(status_code=404, detail="Notification not found")
        
    await db.systemnotification.update(
        where={"id": notification_id},
        data={"isRead": True}
    )
    return {"success": True}

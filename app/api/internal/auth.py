from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from prisma import Prisma
import logging

from app.database import get_db
from app.repositories.rbac_repository import RBACRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

class SyncRequest(BaseModel):
    email: str
    name: str | None = None
    auth_id: str | None = None

@router.post("/sync", summary="Sync Supabase Auth user with Backend")
async def sync_user(payload: SyncRequest, db: Prisma = Depends(get_db)):
    """
    Handles syncing a user who logged in via Supabase Auth (e.g. Google)
    with the Backend's user table. This solves the ID mismatch issue.
    """
    repo = RBACRepository(db)
    
    # Check if user already exists
    user = await repo.get_user_by_email(payload.email)
    
    if not user:
        logger.info(f"Creating new backend user for {payload.email}")
        user = await repo.create_user(
            email=payload.email,
            name=payload.name or payload.email.split("@")[0]
        )
    else:
        # Optionally update name if it changed, but let's keep it simple
        pass
        
    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.name
    }

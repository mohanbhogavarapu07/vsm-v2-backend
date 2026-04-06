from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from prisma import Prisma
import logging

from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])

class UserProfileUpdate(BaseModel):
    name: str | None = None
    jobTitle: str | None = None
    department: str | None = None
    phone: str | None = None
    bio: str | None = None
    bannerGradient: str | None = None

@router.get("/{email}/profile", summary="Get User Profile by Email")
async def get_user_profile(email: str, db: Prisma = Depends(get_db)):
    """
    Fetches the extended user profile details.
    """
    user = await db.user.find_unique(where={"email": email})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "jobTitle": user.jobTitle,
        "department": user.department,
        "phone": user.phone,
        "bio": user.bio,
        "bannerGradient": user.bannerGradient,
    }

@router.put("/{email}/profile", summary="Update User Profile by Email")
async def update_user_profile(email: str, payload: UserProfileUpdate, db: Prisma = Depends(get_db)):
    """
    Updates the user profile details.
    """
    user = await db.user.find_unique(where={"email": email})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Only include fields that were provided
    update_data = {}
    if payload.name is not None:
        update_data["name"] = payload.name
    if payload.jobTitle is not None:
        update_data["jobTitle"] = payload.jobTitle
    if payload.department is not None:
        update_data["department"] = payload.department
    if payload.phone is not None:
        update_data["phone"] = payload.phone
    if payload.bio is not None:
        update_data["bio"] = payload.bio
    if payload.bannerGradient is not None:
        update_data["bannerGradient"] = payload.bannerGradient
        
    updated_user = await db.user.update(
        where={"email": email},
        data=update_data
    )
    
    logger.info(f"Updated profile for user {email}")
    
    return {
        "id": updated_user.id,
        "email": updated_user.email,
        "name": updated_user.name,
        "jobTitle": updated_user.jobTitle,
        "department": updated_user.department,
        "phone": updated_user.phone,
        "bio": updated_user.bio,
        "bannerGradient": updated_user.bannerGradient,
    }

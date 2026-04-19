from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from prisma import Prisma
import logging

from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request / Response Schemas ────────────────────────────────────────────────

class SyncRequest(BaseModel):
    email: str
    name: str | None = None
    auth_id: str | None = None
    auth_provider: str | None = None  # "EMAIL" or "GOOGLE"


class CheckEmailRequest(BaseModel):
    email: str


class CheckEmailResponse(BaseModel):
    exists: bool
    provider: str | None = None  # "EMAIL" | "GOOGLE" | None


class RegisterRequest(BaseModel):
    email: str
    name: str | None = None
    auth_id: str | None = None   # Supabase UUID


class LoginRequest(BaseModel):
    email: str
    auth_id: str | None = None   # Supabase UUID (for post-signIn sync)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/check-email", response_model=CheckEmailResponse, summary="Check if email is registered")
async def check_email(payload: CheckEmailRequest, db: Prisma = Depends(get_db)):
    """
    Returns whether the email exists in the backend and which provider they used.
    The frontend uses this to decide: show /login vs /register, and which button to highlight.
    """
    user = await db.user.find_unique(where={"email": payload.email})
    if not user:
        return CheckEmailResponse(exists=False, provider=None)
    return CheckEmailResponse(exists=True, provider=str(user.authProvider))


@router.post("/register", summary="Register new user (email/password flow)")
async def register_user(payload: RegisterRequest, db: Prisma = Depends(get_db)):
    """
    Creates a backend user record after Supabase email/password sign-up.
    Sets authProvider = EMAIL.
    """
    # Check if already exists (idempotent)
    existing = await db.user.find_unique(where={"email": payload.email})
    if existing:
        logger.info(f"User {payload.email} already exists, returning existing record")
        return {
            "user_id": existing.id,
            "email": existing.email,
            "name": existing.name,
            "auth_provider": str(existing.authProvider),
        }

    user = await db.user.create(
        data={
            "email": payload.email,
            "name": payload.name or payload.email.split("@")[0],
            "authProvider": "EMAIL",
        }
    )
    logger.info(f"Registered new EMAIL user {payload.email} (ID: {user.id})")
    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "auth_provider": str(user.authProvider),
    }


@router.post("/login", summary="Sync backend after email/password login")
async def login_user(payload: LoginRequest, db: Prisma = Depends(get_db)):
    """
    Called after a successful Supabase signInWithPassword to sync/fetch backend user.
    """
    user = await db.user.find_unique(where={"email": payload.email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please register first.",
        )
    logger.info(f"Login sync for {payload.email} (ID: {user.id})")
    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "auth_provider": str(user.authProvider),
    }


@router.post("/sync", summary="Sync Supabase Auth user with Backend (Google / magic-link)")
async def sync_user(payload: SyncRequest, db: Prisma = Depends(get_db)):
    """
    Handles syncing a user who logged in via Supabase Auth (e.g. Google OAuth).
    Creates or updates the backend user record. Sets authProvider = GOOGLE when applicable.
    """
    provider_value = "GOOGLE" if (payload.auth_provider or "").upper() == "GOOGLE" else "EMAIL"

    user = await db.user.upsert(
        where={"email": payload.email},
        data={
            "create": {
                "email": payload.email,
                "name": payload.name or payload.email.split("@")[0],
                "authProvider": provider_value,
            },
            "update": {
                "name": payload.name or payload.email.split("@")[0],
                # Only update provider if we know it's Google (don't overwrite EMAIL → GOOGLE on accident)
                **({"authProvider": "GOOGLE"} if provider_value == "GOOGLE" else {}),
            },
        },
    )

    logger.info(f"Synced user {payload.email} (ID: {user.id}, provider: {user.authProvider})")
    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "auth_provider": str(user.authProvider),
    }

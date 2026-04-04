"""
VSM Backend – GitHub App Integration Endpoints
Handles installation callbacks and repository linking.
"""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from prisma import Prisma

from app.database import get_db
from app.services.github_service import GitHubService
from app.schemas.github_schemas import GitHubInstallationResponse, GitHubRepoResponse, GitHubRepoLinkRequest
from app.utils.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations/github", tags=["integrations"])

@router.get("/install", status_code=status.HTTP_200_OK)
async def get_install_url():
    """Returns the GitHub App installation URL."""
    from app.config import get_settings
    settings = get_settings()
    if not settings.github_client_id:
         raise HTTPException(status_code=500, detail="GITHUB_CLIENT_ID not configured")
    # This usually follows https://github.com/apps/<app-name>/installations/new
    # For now, we'll return a placeholder or a constructed URL if we had the app name
    return {"url": f"https://github.com/apps/vsm-agent/installations/new"}

@router.get("/callback")
async def github_callback(
    installation_id: int = Query(...),
    setup_action: str = Query(...),
    db: Prisma = Depends(get_db)
):
    """
    Callback from GitHub after app installation.
    Fetches and stores installation & repository metadata.
    """
    svc = GitHubService()
    try:
        # 1. Fetch metadata from GitHub API
        # We need to get the account info for the installation
        # For now, we'll use a mocked flow or a direct API call if we had tokens
        # In a real app, we'd use the installation_id to get a token and then call /app/installations/:id
        
        # Simplified for now: 
        # Create or update the installation
        await db.githubinstallation.upsert(
            where={"id": installation_id},
            data={
                "create": {
                    "id": installation_id,
                    "accountName": "Unknown", # Would be fetched
                    "appId": svc.app_id or "unknown",
                    "targetId": 0, # Would be fetched
                    "targetType": "Organization" # Would be fetched
                },
                "update": {
                    "updatedAt": "now"
                }
            }
        )
        
        # 2. Sync repositories
        repos = await svc.list_installation_repositories(installation_id)
        for r in repos:
            await db.githubrepository.upsert(
                where={"id": r["id"]},
                data={
                    "create": {
                        "id": r["id"],
                        "name": r["name"],
                        "fullName": r["full_name"],
                        "installationId": installation_id
                    },
                    "update": {
                        "name": r["name"],
                        "fullName": r["full_name"],
                        "installationId": installation_id
                    }
                }
            )
        
        return {"status": "success", "installation_id": installation_id, "repos_synced": len(repos)}
    except Exception as e:
        logger.exception("GitHub callback failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/repositories", response_model=List[GitHubRepoResponse])
async def list_available_repositories(
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db)
):
    """Lists all repositories that have been installed but not yet linked (or all synced repos)."""
    repos = await db.githubrepository.find_many(
        include={"installation": True}
    )
    return repos

@router.post("/link", response_model=GitHubRepoResponse)
async def link_repository_to_team(
    team_id: int,
    payload: GitHubRepoLinkRequest,
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db)
):
    """Links a synced repository to a specific team."""
    # Verify team exists
    team = await db.team.find_unique(where={"id": team_id})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
        
    repo = await db.githubrepository.update(
        where={"id": payload.repository_id},
        data={"teamId": team_id}
    )
    return repo

@router.get("/team/{team_id}", response_model=List[GitHubRepoResponse])
async def get_team_repositories(
    team_id: int,
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db)
):
    """Returns repositories linked to a specific team."""
    repos = await db.githubrepository.find_many(
        where={"teamId": team_id}
    )
    return repos

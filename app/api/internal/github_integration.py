"""
VSM Backend – GitHub App Integration Endpoints
Handles installation callbacks and repository linking.
"""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from prisma import Prisma

from app.database import get_db
from app.services.github_service import GitHubService
from app.schemas.github_schemas import GitHubInstallationResponse, GitHubRepoResponse, GitHubRepoLinkRequest
from app.utils.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations/github", tags=["integrations"])

@router.get("/install", status_code=status.HTTP_200_OK)
async def get_install_url(team_id: str | None = Query(None, alias="team_id")):
    """Returns the GitHub App installation URL based on the App slug."""
    svc = GitHubService()
    try:
        app_meta = await svc.get_app_metadata()
        slug = app_meta.get("slug", "vsm-agent")
        url = f"https://github.com/apps/{slug}/installations/new"
        if team_id:
            url += f"?state={team_id}"
        return {"url": url}
    except Exception as e:
        logger.error(f"Failed to fetch App metadata: {e}")
        # Default fallback
        return {"url": "https://github.com/apps/vsm-agent/installations/new"}

@router.get("/callback")
async def github_callback(
    installation_id: int = Query(...),
    setup_action: str = Query(...),
    state: str | None = Query(None), # This will be our team_id
    db: Prisma = Depends(get_db)
):
    """
    Callback from GitHub after app installation.
    Fetches and stores installation & repository metadata.
    """
    svc = GitHubService()
    try:
        # 1. Fetch metadata from GitHub API to get account name
        details = await svc.get_installation_details(installation_id)
        account = details.get("account", {})
        account_name = account.get("login", "Unknown")
        target_id = account.get("id", 0)
        target_type = details.get("target_type", "User")

        await db.githubinstallation.upsert(
            where={"id": installation_id},
            data={
                "create": {
                    "id": installation_id,
                    "accountName": account_name,
                    "appId": svc.app_id or "unknown",
                    "targetId": target_id,
                    "targetType": target_type
                },
                "update": {
                    "accountName": account_name,
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
        
    except Exception as e:
        logger.exception("GitHub callback failed")
        from app.config import get_settings
        settings = get_settings()
        return RedirectResponse(url=f"{settings.frontend_url}?status=github_error")
    
    from app.config import get_settings
    settings = get_settings()
    
    # If we have a team_id in state, redirect back to that specific team's Code tab
    if state and state.isdigit():
        team_id = int(state)
        team = await db.team.find_unique(where={"id": team_id})
        if team:
            return RedirectResponse(
                url=f"{settings.frontend_url}/projects/{team.projectId}/board?team_id={team_id}&status=github_success"
            )
            
    # Default redirect back to the frontend projects page
    return RedirectResponse(url=f"{settings.frontend_url}/projects?status=github_success")

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

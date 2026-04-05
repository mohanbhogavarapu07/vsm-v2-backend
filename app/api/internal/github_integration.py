"""
VSM Backend – GitHub App Integration Endpoints
Handles installation callbacks and repository linking.
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from fastapi.responses import RedirectResponse
from prisma import Prisma

from app.database import get_db
from app.services.github_service import GitHubService
from app.schemas.github_schemas import GitHubInstallationResponse, GitHubRepoResponse, GitHubRepoLinkRequest
from app.utils.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations/github", tags=["integrations"])

@router.get("/install", status_code=status.HTTP_200_OK)
async def get_install_url(
    team_id: str | None = Query(None, alias="team_id"),
    return_url: str | None = Query(None, alias="return_url")
):
    """Returns the GitHub App installation URL based on the App slug."""
    svc = GitHubService()
    try:
        app_meta = await svc.get_app_metadata()
        slug = app_meta.get("slug", "vsm-agent")
        url = f"https://github.com/apps/{slug}/installations/new"
        
        # We use a state parameter to carry both team_id and return_url through the OAuth flow
        import json
        import base64
        state_data = {
            "team_id": team_id,
            "return_url": return_url
        }
        state_str = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()
        url += f"?state={state_str}"
        
        return {"url": url}
    except Exception as e:
        logger.error(f"Failed to fetch App metadata: {e}")
        # Default fallback (without state, sync won't link to team automatically)
        return {"url": f"https://github.com/apps/vsm-agent/installations/new"}

@router.get("/callback")
async def github_callback(
    request: Request,
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
        logger.info(f"Processing GitHub callback for installation {installation_id} with state/team: {state}")
        
        # Use the centralized sync service
        await svc.sync_repositories(db, installation_id, team_id)
        
        logger.info(f"Successfully processed repository sync for installation {installation_id}")
        
    except Exception as e:
        logger.exception(f"GitHub callback failed for installation {installation_id}: {e}")
        from app.config import get_settings
        settings = get_settings()
        
        # Dynamic error redirect
        origin = request.headers.get("referer") or request.headers.get("origin")
        target_base = settings.frontend_url
        if origin and "localhost" not in origin and "localhost" in settings.frontend_url:
            from urllib.parse import urlparse
            parsed_origin = urlparse(origin)
            target_base = f"{parsed_origin.scheme}://{parsed_origin.netloc}"
            
        return RedirectResponse(url=f"{target_base}/projects?status=github_error")
    
    from app.config import get_settings
    settings = get_settings()
    
    # Determine the final frontend destination
    # 1. First priority: return_url carried in state
    # 2. Second priority: Dynamic detection from Referer/Origin headers
    # 3. Last priority: FRONTEND_URL from settings
    
    target_base = None
    if return_url:
        from urllib.parse import urlparse
        parsed = urlparse(return_url)
        target_base = f"{parsed.scheme}://{parsed.netloc}"
    
    if not target_base:
        origin = request.headers.get("referer") or request.headers.get("origin")
        if origin and "localhost" not in origin and "localhost" in settings.frontend_url:
            from urllib.parse import urlparse
            p = urlparse(origin)
            target_base = f"{p.scheme}://{p.netloc}"
            
    if not target_base:
        target_base = settings.frontend_url
        
    logger.info(f"Using final redirect base: {target_base}")
    
    # If we have a team_id in state, redirect back to that specific team's Code tab
    if team_id:
        team = await db.team.find_unique(where={"id": team_id})
        if team:
            logger.info(f"Redirecting back to team {team_id} (Project {team.projectId}) at {target_base}")
            return RedirectResponse(
                url=f"{target_base}/projects/{team.projectId}/board?team_id={team_id}&status=github_success"
            )
    
    logger.info(f"Redirecting back to projects at {target_base}")
    return RedirectResponse(url=f"{target_base}/projects?status=github_success")

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
        where={"id": payload.repositoryId},
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

@router.post("/sync", status_code=status.HTTP_200_OK)
async def sync_github_repositories(
    team_id: int,
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db)
):
    """
    Manually triggers a repository refresh for all installations known to the system.
    If repositories are found that aren't linked elsewhere, they are linked to the provided team.
    """
    svc = GitHubService()
    try:
        # Find all installations
        installations = await db.githubinstallation.find_many()
        if not installations:
            return {"message": "No GitHub installations found in the system. Please connect GitHub first.", "synced": 0}
            
        total_synced = 0
        for inst in installations:
            try:
                synced = await svc.sync_repositories(db, inst.id, team_id)
                total_synced += len(synced)
            except Exception as e:
                logger.error(f"Manual sync failed for installation {inst.id}: {e}")
                
        return {"message": f"Successfully synced {total_synced} repositories.", "synced": total_synced}
    except Exception as e:
        logger.exception(f"Manual synchronization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

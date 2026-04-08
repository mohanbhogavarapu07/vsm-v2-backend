"""
VSM Backend – GitHub App Integration Endpoints
Handles installation callbacks and repository linking.

OPTIMIZED: Added response caching for repository listings.
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from prisma import Prisma

from app.database import get_db
from app.services.github_service import GitHubService
from app.schemas.github_schemas import GitHubInstallationResponse, GitHubRepoResponse, GitHubRepoLinkRequest
from app.utils.permissions import require_permission
from app.utils.cache import github_cache

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
        return {"url": "https://github.com/apps/vsm-agent/installations/new"}

@router.get("/callback")
async def github_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    installation_id: int = Query(...),
    setup_action: str = Query(...),
    state: str | None = Query(None), # This will be our team_id
    from_frontend: bool = Query(False),
    db: Prisma = Depends(get_db)
):
    """
    Callback from GitHub after app installation.
    Fetches and stores installation & repository metadata.
    """
    svc = GitHubService()
    team_id = None
    return_url = None
    
    if state:
        try:
            import json
            import base64
            padded_state = state + '=' * (-len(state) % 4)
            state_data = json.loads(base64.urlsafe_b64decode(padded_state.encode()).decode())
            team_id = state_data.get("team_id")
            return_url = state_data.get("return_url")
            if team_id:
                team_id = int(team_id)
        except Exception as e:
            logger.error(f"Failed to decode state parameter: {e}")

    try:
        logger.info(f"Queueing GitHub sync for installation {installation_id} with team_id: {team_id}")
        
        # ── Asynchronous Sync ──────────────────────────────────────────────────
        # We trigger the sync in the background so the user doesn't wait.
        # This is especially important for installations with many repositories.
        background_tasks.add_task(svc.sync_repositories, db, installation_id, team_id)
        
    except Exception as e:
        logger.exception(f"Failed to queue GitHub sync for installation {installation_id}: {e}")
        from app.config import get_settings
        settings = get_settings()
        
        if from_frontend:
            raise HTTPException(status_code=500, detail="Failed to initiate synchronization")
            
        # Dynamic error redirect
        origin = request.headers.get("referer") or request.headers.get("origin")
        target_base = settings.frontend_url
        if origin and "localhost" not in origin and "localhost" in settings.frontend_url:
            from urllib.parse import urlparse
            parsed_origin = urlparse(origin)
            target_base = f"{parsed_origin.scheme}://{parsed_origin.netloc}"
            
        return RedirectResponse(
            url=f"{target_base}/projects?status=github_error",
            status_code=status.HTTP_302_FOUND
        )
    
    if from_frontend:
        return {"status": "success", "team_id": team_id}
        
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
    
    # If we have a team_id in state, redirect back to that specific team's configuration tab
    if team_id:
        team = await db.team.find_unique(where={"id": team_id})
        if team:
            logger.info(f"Redirecting back to team {team_id} (Project {team.projectId}) at {target_base}")
            return RedirectResponse(
                url=f"{target_base}/projects/{team.projectId}/teams/{team_id}/team?status=github_success",
                status_code=status.HTTP_302_FOUND
            )
    
    logger.info(f"Redirecting back to projects at {target_base}")
    return RedirectResponse(
        url=f"{target_base}/projects?status=github_success",
        status_code=status.HTTP_302_FOUND
    )

@router.get("/repositories", response_model=List[GitHubRepoResponse])
async def list_available_repositories(
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db)
):
    """Lists all repositories that have been installed but not yet linked (or all synced repos)."""
    cache_key = "gh_all_repos"
    cached = github_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"Cache HIT: {cache_key}")
        return cached
    
    repos = await db.githubrepository.find_many(
        include={"installation": True}
    )
    github_cache.set(cache_key, repos)
    return repos

@router.post("/link", response_model=GitHubRepoResponse)
async def link_repository_to_team(
    team_id: int,
    payload: GitHubRepoLinkRequest,
    _: None = Depends(require_permission("MANAGE_TEAM")),
    db: Prisma = Depends(get_db)
):
    """Links a synced repository to a specific team, ensuring exactly one repo per team."""
    # Verify team exists
    team = await db.team.find_unique(where={"id": team_id})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
        
    # Unlink any existing repositories for this team to enforce 1-to-1 mapping
    await db.githubrepository.update_many(
        where={"teamId": team_id},
        data={"teamId": None}
    )
        
    repo = await db.githubrepository.update(
        where={"id": payload.repositoryId},
        data={"teamId": team_id}
    )
    
    # Invalidate cache after linking
    github_cache.invalidate("gh_all_repos")
    github_cache.invalidate(f"gh_team_repos_{team_id}")
    
    return repo

@router.get("/team/{team_id}", response_model=List[GitHubRepoResponse])
async def get_team_repositories(
    team_id: int,
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db)
):
    """Returns repositories linked to a specific team."""
    cache_key = f"gh_team_repos_{team_id}"
    cached = github_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"Cache HIT: {cache_key}")
        return cached
    
    repos = await db.githubrepository.find_many(
        where={"teamId": team_id}
    )
    github_cache.set(cache_key, repos)
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
        
        # Final global cache clear to ensure frontend sees all changes
        github_cache.invalidate("gh_all_repos")
        github_cache.invalidate(f"gh_team_repos_{team_id}")
                
        return {
            "message": f"Universal sync complete. Processed {total_synced} repositories and removed orphaned data.",
            "synced": total_synced
        }
    except Exception as e:
        logger.exception(f"Manual synchronization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/unlinked", status_code=status.HTTP_200_OK)
async def check_unlinked_repositories(
    _: None = Depends(require_permission("READ_TASK")),
    db: Prisma = Depends(get_db)
):
    """
    Health check endpoint: Lists repositories that are receiving events but not linked to any team.
    
    WARNING: Unlinked repositories will not trigger AI agent processing.
    Events from these repositories are stored but not processed.
    
    Use /integrations/github/link to associate repositories with teams.
    """
    # Find all repositories without team linkage
    unlinked_repos = await db.githubrepository.find_many(
        where={"teamId": None},
        include={"installation": True}
    )
    
    # Check if any of these repositories have received events
    repos_with_events = []
    for repo in unlinked_repos:
        event_count = await db.eventlog.count(
            where={"repositoryId": repo.id}
        )
        if event_count > 0:
            repos_with_events.append({
                "repository_id": repo.id,
                "repository_name": repo.fullName,
                "installation_id": repo.installationId,
                "installation_account": repo.installation.accountName if repo.installation else "Unknown",
                "event_count": event_count,
                "status": "receiving_events_but_unlinked",
                "action_required": f"Link to team via POST /integrations/github/link with repositoryId={repo.id}"
            })
    
    return {
        "total_unlinked_repositories": len(unlinked_repos),
        "repositories_receiving_events_unlinked": len(repos_with_events),
        "status": "warning" if repos_with_events else "ok",
        "warning": "Some repositories are receiving events but not processing them. Link them to teams." if repos_with_events else None,
        "unlinked_repositories_with_events": repos_with_events
    }

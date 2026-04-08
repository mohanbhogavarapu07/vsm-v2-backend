"""
VSM Backend – GitHub App Service
Handles JWT generation, installation token exchange, and Repository API calls.

OPTIMIZED: Uses singleton httpx client with connection pooling and response caching.
"""

import time
import jwt
import httpx
import logging
import asyncio
from typing import Any, List, Optional
from prisma import Prisma
from app.config import get_settings
from app.utils.cache import github_cache

logger = logging.getLogger(__name__)
settings = get_settings()

# Singleton httpx client for connection pooling
_github_http_client: Optional[httpx.AsyncClient] = None

def get_github_http_client() -> httpx.AsyncClient:
    """
    Returns a singleton httpx client with connection pooling.
    Eliminates repeated connection overhead to GitHub API.
    """
    global _github_http_client
    if _github_http_client is None:
        _github_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=True
        )
        logger.info("Initialized singleton GitHub httpx client with connection pooling")
    return _github_http_client

class GitHubService:
    def __init__(self):
        self.app_id = settings.github_app_id
        self.private_key = settings.github_private_key
        self.base_url = "https://api.github.com"
        self.client = get_github_http_client()

    def _generate_jwt(self) -> str:
        """Generates a JWT to authenticate as the GitHub App."""
        if not self.app_id or not self.private_key:
            raise ValueError("GITHUB_APP_ID and GITHUB_PRIVATE_KEY must be set")
        
        # Ensure private key is correctly formatted if it's a string from env
        key = self.private_key.replace("\\n", "\n")
        
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": self.app_id,
        }
        return jwt.encode(payload, key, algorithm="RS256")

    async def get_app_metadata(self) -> dict:
        """Fetches the App's metadata (slug, name, etc.) from GitHub."""
        cache_key = "gh_app_metadata"
        cached = github_cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache HIT: GitHub app metadata")
            return cached
            
        token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        resp = await self.client.get(f"{self.base_url}/app", headers=headers)
        resp.raise_for_status()
        result = resp.json()
        github_cache.set(cache_key, result)
        return result

    async def get_installation_token(self, installation_id: int) -> str:
        """Exchanges the App JWT for an installation access token."""
        # Token caching with 50-minute expiration (tokens are valid for 60 minutes)
        cache_key = f"gh_install_token_{installation_id}"
        cached = github_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache HIT: GitHub installation token {installation_id}")
            return cached
            
        token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        
        resp = await self.client.post(
            f"{self.base_url}/app/installations/{installation_id}/access_tokens",
            headers=headers
        )
        resp.raise_for_status()
        access_token = resp.json()["token"]
        
        # Cache for 50 minutes (tokens valid for 60 minutes)
        github_cache.set(cache_key, access_token)
        return access_token

    async def get_installation_details(self, installation_id: int) -> dict:
        """Fetches metadata for a specific App installation (account info, etc.)."""
        cache_key = f"gh_install_details_{installation_id}"
        cached = github_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache HIT: GitHub installation details {installation_id}")
            return cached
            
        token = self._generate_jwt() # Auth as App
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        resp = await self.client.get(
            f"{self.base_url}/app/installations/{installation_id}",
            headers=headers
        )
        resp.raise_for_status()
        result = resp.json()
        github_cache.set(cache_key, result)
        return result

    async def list_installation_repositories(self, installation_id: int) -> List[dict]:
        """Lists all repositories accessible to a specific installation."""
        cache_key = f"gh_install_repos_{installation_id}"
        cached = github_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache HIT: GitHub installation repositories {installation_id}")
            return cached
            
        token = await self.get_installation_token(installation_id)
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        
        repos = []
        page = 1
        while True:
            resp = await self.client.get(
                f"{self.base_url}/installation/repositories",
                params={"per_page": 100, "page": page},
                headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            page_repos = data.get("repositories", [])
            repos.extend(page_repos)
            
            if len(page_repos) < 100:
                break
            page += 1
        
        github_cache.set(cache_key, repos)
        return repos

    async def get_repository_details(self, installation_id: int, repo_id: int) -> dict:
        """Fetches details for a specific repository."""
        cache_key = f"gh_repo_details_{installation_id}_{repo_id}"
        cached = github_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache HIT: GitHub repo details {repo_id}")
            return cached
            
        token = await self.get_installation_token(installation_id)
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        resp = await self.client.get(
            f"{self.base_url}/repositories/{repo_id}",
            headers=headers
        )
        resp.raise_for_status()
        result = resp.json()
        github_cache.set(cache_key, result)
        return result

    async def sync_repositories(self, db: Prisma, installation_id: int, team_id: Optional[int] = None) -> List[Any]:
        """
        Synchronizes repositories for a specific installation.
        Updates metadata and optionally links new repositories to a team.
        Returns the list of processed repositories.
        
        OPTIMIZED: Invalidates cache after sync to ensure fresh data.
        """
        logger.info(f"Syncing repositories for installation {installation_id} (Team: {team_id})")
        
        # 1. Fetch metadata from GitHub API to ensure we have the account name
        details = await self.get_installation_details(installation_id)
        account = details.get("account", {})
        account_name = account.get("login", "Unknown")
        target_id = account.get("id", 0)
        target_type = details.get("target_type", "User")

        # 2. Upsert installation metadata
        await db.githubinstallation.upsert(
            where={"id": installation_id},
            data={
                "create": {
                    "id": installation_id,
                    "accountName": account_name,
                    "appId": str(self.app_id) if self.app_id else "unknown",
                    "targetId": target_id,
                    "targetType": target_type
                },
                "update": {
                    "accountName": account_name
                }
            }
        )

        # 3. Fetch all repositories
        repos = await self.list_installation_repositories(installation_id)
        logger.info(f"Retrieved {len(repos)} repositories from GitHub for installation {installation_id}")
        
        synced_repos = []
        for r in repos:
            retry_count = 0
            max_retries = 3
            while retry_count < max_retries:
                try:
                    # Check if repo already exists to avoid overwriting existing team associations
                    existing = await db.githubrepository.find_unique(where={"id": r["id"]})
                    
                    repo_data = {
                        "id": r["id"],
                        "name": r["name"],
                        "fullName": r["full_name"],
                        "installationId": installation_id
                    }
                    
                    upserted = await db.githubrepository.upsert(
                        where={"id": r["id"]},
                        data={
                            "create": repo_data,
                            "update": {
                                "name": r["name"],
                                "fullName": r["full_name"],
                                "installationId": installation_id,
                                "teamId": existing.teamId if existing else None # Preserve existing linkage
                            }
                        }
                    )
                    synced_repos.append(upserted)
                    break # Success
                except Exception as repo_err:
                    retry_count += 1
                    logger.warning(f"Failed to sync repo {r['full_name']} (attempt {retry_count}/{max_retries}): {repo_err}")
                    if retry_count >= max_retries:
                        logger.error(f"Permanently failed to sync repo {r['full_name']} after {max_retries} attempts")
                    else:
                        await asyncio.sleep(1 * retry_count) # Exponential backoff
        
        # Invalidate cache after sync to force fresh data on next request
        github_cache.invalidate(f"gh_install_repos_{installation_id}")
        logger.info(f"Invalidated GitHub cache for installation {installation_id}")
        
        return synced_repos

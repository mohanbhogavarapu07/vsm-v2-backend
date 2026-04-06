"""
VSM Backend – GitHub App Service
Handles JWT generation, installation token exchange, and Repository API calls.
"""

import time
import jwt
import httpx
import logging
import asyncio
from typing import Any, List, Optional
from prisma import Prisma
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class GitHubService:
    def __init__(self):
        self.app_id = settings.github_app_id
        self.private_key = settings.github_private_key
        self.base_url = "https://api.github.com"

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
        token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/app", headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def get_installation_token(self, installation_id: int) -> str:
        """Exchanges the App JWT for an installation access token."""
        token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/app/installations/{installation_id}/access_tokens",
                headers=headers
            )
            resp.raise_for_status()
            return resp.json()["token"]

    async def get_installation_details(self, installation_id: int) -> dict:
        """Fetches metadata for a specific App installation (account info, etc.)."""
        token = self._generate_jwt() # Auth as App
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/app/installations/{installation_id}",
                headers=headers
            )
            resp.raise_for_status()
            return resp.json()

    async def list_installation_repositories(self, installation_id: int) -> List[dict]:
        """Lists all repositories accessible to a specific installation."""
        token = await self.get_installation_token(installation_id)
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        
        repos = []
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
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
        
        return repos

    async def get_repository_details(self, installation_id: int, repo_id: int) -> dict:
        """Fetches details for a specific repository."""
        token = await self.get_installation_token(installation_id)
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/repositories/{repo_id}",
                headers=headers
            )
            resp.raise_for_status()
            return resp.json()

    async def sync_repositories(self, db: Prisma, installation_id: int, team_id: Optional[int] = None) -> List[Any]:
        """
        Synchronizes repositories for a specific installation.
        Updates metadata and optionally links new repositories to a team.
        Returns the list of processed repositories.
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
        
        return synced_repos

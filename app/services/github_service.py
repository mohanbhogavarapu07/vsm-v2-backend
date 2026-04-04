"""
VSM Backend – GitHub App Service
Handles JWT generation, installation token exchange, and Repository API calls.
"""

import time
import jwt
import httpx
import logging
from typing import Any, List
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

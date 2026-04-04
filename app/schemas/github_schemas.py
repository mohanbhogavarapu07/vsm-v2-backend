"""
VSM Backend – GitHub Integration Schemas
"""

from typing import List, Optional
from pydantic import BaseModel

class GitHubInstallationBase(BaseModel):
    id: int
    account_name: str
    target_id: int
    target_type: str

class GitHubRepositoryBase(BaseModel):
    id: int
    name: str
    full_name: str
    installation_id: int
    team_id: Optional[int] = None

class GitHubRepoLinkRequest(BaseModel):
    repository_id: int

class GitHubRepoUnlinkRequest(BaseModel):
    repository_id: int

class GitHubRepoResponse(GitHubRepositoryBase):
    pass

class GitHubInstallationResponse(GitHubInstallationBase):
    repositories: List[GitHubRepoResponse] = []

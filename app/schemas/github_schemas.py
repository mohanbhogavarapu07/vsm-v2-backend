"""
VSM Backend – GitHub Integration Schemas
"""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict

class GitHubInstallationBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    id: int
    accountName: str
    targetId: int
    targetType: str

class GitHubRepositoryBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    id: int
    name: str
    fullName: str
    installationId: int
    teamId: Optional[int] = None

class GitHubRepoLinkRequest(BaseModel):
    repositoryId: int

class GitHubRepoUnlinkRequest(BaseModel):
    repositoryId: int

class GitHubRepoResponse(GitHubRepositoryBase):
    pass

class GitHubInstallationResponse(GitHubInstallationBase):
    repositories: List[GitHubRepoResponse] = []

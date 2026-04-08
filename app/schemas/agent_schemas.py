from typing import Optional, List, Any
from pydantic import BaseModel, Field

class DecisionProposal(BaseModel):
    status: str # "APPROVED" | "BLOCKED" | "NO_TRANSITION" | "FUZZY_LINK" | "PENDING_CONFIRMATION"
    toStageId: Optional[int] = None
    transitionId: Optional[int] = None
    confidenceScore: float
    reasoning: str
    postActions: List[dict] = []
    correlationId: str
    taskId: Optional[int] = None
    githubEventType: str

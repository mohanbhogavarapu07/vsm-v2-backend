import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
import httpx
from fastapi import APIRouter, Depends, Path, HTTPException, status
from prisma import Prisma, Json
from prisma.enums import TaskStatusCategory, ScopeType, DirectionType, TriggerType, WorkflowReadiness, AgentDecisionStatus

from app.database import get_db
from app.config import get_settings

router = APIRouter(prefix="/projects", tags=["workflow"])

# ─── SCHEMAS ─────────────────────────────────────────────────────────────────

class ClassifyStageRequest(BaseModel):
    name: str

class ClassifyStageResponse(BaseModel):
    systemCategory: str
    intentTag: str
    confidence: float
    reasoning: str

class WorkflowStageCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    systemCategory: TaskStatusCategory
    intentTag: Optional[str] = None
    positionOrder: int
    scopeType: ScopeType = ScopeType.PROJECT
    teamId: Optional[int] = None
    isBlocking: bool = False
    requiresApprovalToExit: bool = False
    slaDurationMinutes: Optional[int] = None

class WorkflowStageUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    systemCategory: Optional[TaskStatusCategory] = None
    intentTag: Optional[str] = None
    slaDurationMinutes: Optional[int] = None
    isBlocking: Optional[bool] = None
    requiresApprovalToExit: Optional[bool] = None
    positionOrder: Optional[int] = None

class WorkflowStageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    projectId: int
    name: str
    systemCategory: TaskStatusCategory
    intentTag: Optional[str]
    positionOrder: int
    scopeType: ScopeType
    teamId: Optional[int]
    isBlocking: bool
    requiresApprovalToExit: bool
    slaDurationMinutes: Optional[int]

class WorkflowGraphResponse(BaseModel):
    stages: List[WorkflowStageResponse]
    readiness: WorkflowReadiness

class AgentDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    taskId: int
    taskTitle: Optional[str] = None
    fromStageId: Optional[int] = None
    toStageId: Optional[int] = None
    transitionId: Optional[int] = None
    confidenceScore: float
    reasoning: str
    correlationId: Optional[str]
    status: AgentDecisionStatus
    triggeredByEvent: Optional[str]
    createdAt: datetime


# ─── HELPER ──────────────────────────────────────────────────────────────────

async def evaluate_and_update_workflow_readiness(project_id: int, db: Prisma):
    stages_count = await db.workflowstage.count(where={"projectId": project_id})
    
    if stages_count >= 2:
        await db.project.update(
            where={"id": project_id},
            data={"workflowReadiness": WorkflowReadiness.ACTIVE}
        )
    else:
        await db.project.update(
            where={"id": project_id},
            data={"workflowReadiness": WorkflowReadiness.INCOMPLETE}
        )

# ─── ENDPOINTS ───────────────────────────────────────────────────────────────

@router.post("/{project_id}/stages", response_model=WorkflowStageResponse)
async def create_stage(
    project_id: int = Path(...),
    payload: WorkflowStageCreate = ...,
    db: Prisma = Depends(get_db)
):
    existing = await db.workflowstage.find_first(
        where={"projectId": project_id, "positionOrder": payload.positionOrder}
    )
    if existing:
        raise HTTPException(status_code=400, detail="positionOrder must be unique per project")
    
    stage = await db.workflowstage.create(
        data={
            "projectId": project_id,
            "name": payload.name,
            "systemCategory": payload.systemCategory,
            "intentTag": payload.intentTag,
            "positionOrder": payload.positionOrder,
            "scopeType": payload.scopeType,
            "teamId": payload.teamId,
            "isBlocking": payload.isBlocking,
            "requiresApprovalToExit": payload.requiresApprovalToExit,
            "slaDurationMinutes": payload.slaDurationMinutes
        }
    )
    
    await evaluate_and_update_workflow_readiness(project_id, db)
    return stage

@router.get("/{project_id}/stages", response_model=List[WorkflowStageResponse])
async def list_stages(
    project_id: int = Path(...),
    db: Prisma = Depends(get_db)
):
    stages = await db.workflowstage.find_many(
        where={"projectId": project_id},
        order={"positionOrder": "asc"}
    )
    return stages

@router.post("/{project_id}/stages/classify", response_model=ClassifyStageResponse)
async def classify_stage(
    project_id: int = Path(...),
    payload: ClassifyStageRequest = ...,
    db: Prisma = Depends(get_db)
):
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=settings.ai_agent_timeout) as client:
            resp = await client.post(
                f"{settings.ai_agent_url}/agent/classify-stage",
                json={"stage_name": payload.name}
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="AI Agent classification failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{project_id}/workflow/graph", response_model=WorkflowGraphResponse)
async def get_workflow_graph(
    project_id: int = Path(...),
    db: Prisma = Depends(get_db)
):
    project = await db.project.find_unique(where={"id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    stages = await db.workflowstage.find_many(where={"projectId": project_id})
            
    return WorkflowGraphResponse(
        stages=stages,
        readiness=project.workflowReadiness
    )

@router.patch("/{project_id}/stages/{stage_id}", response_model=WorkflowStageResponse)
async def update_stage(
    stage_id: int = Path(...),
    project_id: int = Path(...),
    payload: WorkflowStageUpdate = ...,
    db: Prisma = Depends(get_db)
):
    stage = await db.workflowstage.find_unique(where={"id": stage_id})
    if not stage or stage.projectId != project_id:
        raise HTTPException(status_code=404, detail="Stage not found")
        
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        return stage

    # Block systemCategory changes if any task has ever occupied this stage.
    if "systemCategory" in update_data and update_data["systemCategory"] != stage.systemCategory:
        # Check current occupancy
        current_tasks = await db.task.count(where={"currentStageId": stage_id})
        if current_tasks > 0:
            raise HTTPException(
                status_code=400, 
                detail="Cannot change systemCategory: tasks are currently in this stage."
            )
        
        # Check historical occupancy via AgentDecision
        historical_decisions = await db.agentdecision.count(
            where={
                "OR": [
                    {"fromStageId": stage_id},
                    {"toStageId": stage_id}
                ]
            }
        )
        if historical_decisions > 0:
            raise HTTPException(
                status_code=400, 
                detail="Cannot change systemCategory: this stage has historical task activity."
            )

    # Check positionOrder uniqueness if updating
    if "positionOrder" in update_data and update_data["positionOrder"] != stage.positionOrder:
        existing = await db.workflowstage.find_first(
            where={"projectId": project_id, "positionOrder": update_data["positionOrder"]}
        )
        if existing:
            raise HTTPException(status_code=400, detail="positionOrder must be unique per project")

    updated = await db.workflowstage.update(
        where={"id": stage_id},
        data=update_data
    )
    return updated

@router.delete("/{project_id}/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stage(
    stage_id: int = Path(...),
    project_id: int = Path(...),
    db: Prisma = Depends(get_db)
):
    stage = await db.workflowstage.find_unique(where={"id": stage_id})
    if not stage or stage.projectId != project_id:
        raise HTTPException(status_code=404, detail="Stage not found")
        
    await db.workflowstage.delete(where={"id": stage_id})
    await evaluate_and_update_workflow_readiness(project_id, db)

@router.get("/{project_id}/agent-decisions")
async def list_agent_decisions(
    project_id: int = Path(...),
    db: Prisma = Depends(get_db)
):
    """
    Fetch the decision audit feed for all tasks in this project.
    Includes task ID, task title, from-stage and to-stage names.
    """
    decisions = await db.agentdecision.find_many(
        where={
            "task": {
                "team": {
                    "projectId": project_id
                }
            }
        },
        include={
            "task": True,
            "fromStage": True,
            "toStage": True,
        },
        order={"createdAt": "desc"}
    )

    results = []
    for d in decisions:
        task = getattr(d, "task", None)
        from_stage = getattr(d, "fromStage", None)
        to_stage = getattr(d, "toStage", None)
        results.append({
            "id": d.id,
            "task_id": d.taskId,
            "task_title": task.title if task else None,
            "from_stage_id": d.fromStageId,
            "from_stage_name": from_stage.name if from_stage else None,
            "to_stage_id": d.toStageId,
            "to_stage_name": to_stage.name if to_stage else None,
            "confidence_score": d.confidenceScore,
            "reasoning": d.reasoning,
            "status": d.status,
            "decision_source": d.decisionSource,
            "triggered_by_event": getattr(d, "triggeredByEvent", None),
            "correlation_id": getattr(d, "correlationId", None),
            "created_at": d.createdAt,
        })

    return results



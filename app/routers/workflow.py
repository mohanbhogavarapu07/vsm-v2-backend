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

class WorkflowTransitionCreate(BaseModel):
    fromStageId: int
    toStageId: int
    directionType: DirectionType
    triggerType: TriggerType
    githubEventType: Optional[str] = None
    requiredRole: Optional[str] = None
    conditions: List[Dict[str, Any]] = []
    postActions: List[Dict[str, Any]] = []
    priorityRank: int = 1
    isActive: bool = True

class WorkflowTransitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    projectId: int
    fromStageId: int
    toStageId: int
    directionType: DirectionType
    triggerType: TriggerType
    githubEventType: Optional[str]
    requiredRole: Optional[str]
    conditions: List[Dict[str, Any]]
    postActions: List[Dict[str, Any]]
    priorityRank: int
    isActive: bool
    fromStageName: Optional[str] = None
    toStageName: Optional[str] = None

class WorkflowGraphResponse(BaseModel):
    stages: List[WorkflowStageResponse]
    transitions: List[WorkflowTransitionResponse]
    readiness: WorkflowReadiness

class WorkflowValidateRequest(BaseModel):
    fromStageId: int
    toStageId: int
    triggerType: TriggerType
    githubEventType: Optional[str] = None
    actorRole: Optional[str] = None

class WorkflowValidateResponse(BaseModel):
    valid: bool
    transitionId: Optional[str] = None
    reason: Optional[str] = None

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
    transitions_count = await db.workflowtransition.count(where={"projectId": project_id})
    
    if stages_count >= 2 and transitions_count >= 1:
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

@router.post("/{project_id}/transitions", response_model=WorkflowTransitionResponse)
async def create_transition(
    project_id: int = Path(...),
    payload: WorkflowTransitionCreate = ...,
    db: Prisma = Depends(get_db)
):
    from_stage = await db.workflowstage.find_unique(where={"id": payload.fromStageId})
    to_stage = await db.workflowstage.find_unique(where={"id": payload.toStageId})
    
    if not from_stage or from_stage.projectId != project_id:
        raise HTTPException(status_code=400, detail="fromStageId does not belong to this project")
    if not to_stage or to_stage.projectId != project_id:
        raise HTTPException(status_code=400, detail="toStageId does not belong to this project")
        
    existing = await db.workflowtransition.find_first(
        where={
            "projectId": project_id,
            "fromStageId": payload.fromStageId,
            "toStageId": payload.toStageId,
            "triggerType": payload.triggerType
        }
    )
    if existing:
        raise HTTPException(status_code=400, detail="Duplicate transition combination")
        
    transition = await db.workflowtransition.create(
        data={
            "projectId": project_id,
            "fromStageId": payload.fromStageId,
            "toStageId": payload.toStageId,
            "directionType": payload.directionType,
            "triggerType": payload.triggerType,
            "githubEventType": payload.githubEventType,
            "requiredRole": payload.requiredRole,
            "conditions": Json(payload.conditions),
            "postActions": Json(payload.postActions),
            "priorityRank": payload.priorityRank,
            "isActive": payload.isActive
        }
    )
    
    await evaluate_and_update_workflow_readiness(project_id, db)
    
    # Return with resolved stage names
    t_dict = transition.model_dump()
    t_dict["fromStageName"] = from_stage.name
    t_dict["toStageName"] = to_stage.name
    
    # Handle Json fields if Prisma returns string
    if isinstance(t_dict.get('conditions'), str):
        t_dict['conditions'] = json.loads(t_dict['conditions'])
    if isinstance(t_dict.get('postActions'), str):
        t_dict['postActions'] = json.loads(t_dict['postActions'])
        
    return t_dict

@router.get("/{project_id}/workflow/graph", response_model=WorkflowGraphResponse)
async def get_workflow_graph(
    project_id: int = Path(...),
    db: Prisma = Depends(get_db)
):
    project = await db.project.find_unique(where={"id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    stages = await db.workflowstage.find_many(where={"projectId": project_id})
    transitions = await db.workflowtransition.find_many(where={"projectId": project_id})
    
    stage_map = {s.id: s.name for s in stages}
    parsed_transitions = []
    
    for t in transitions:
        t_dict = t.model_dump()
        if isinstance(t_dict.get('conditions'), str):
            t_dict['conditions'] = json.loads(t_dict['conditions'])
        if isinstance(t_dict.get('postActions'), str):
            t_dict['postActions'] = json.loads(t_dict['postActions'])
            
        t_dict["fromStageName"] = stage_map.get(t.fromStageId)
        t_dict["toStageName"] = stage_map.get(t.toStageId)
        parsed_transitions.append(t_dict)
        
    return WorkflowGraphResponse(
        stages=stages,
        transitions=parsed_transitions,
        readiness=project.workflowReadiness
    )

@router.post("/{project_id}/workflow/validate", response_model=WorkflowValidateResponse)
async def validate_transition(
    project_id: int = Path(...),
    payload: WorkflowValidateRequest = ...,
    db: Prisma = Depends(get_db)
):
    transition = await db.workflowtransition.find_first(
        where={
            "projectId": project_id,
            "fromStageId": payload.fromStageId,
            "toStageId": payload.toStageId,
            "triggerType": payload.triggerType
        }
    )
    if not transition:
        return WorkflowValidateResponse(valid=False, reason="No matching transition found")
        
    if payload.githubEventType and transition.githubEventType and payload.githubEventType != transition.githubEventType:
        return WorkflowValidateResponse(valid=False, reason="githubEventType mismatch")
        
    if payload.actorRole and transition.requiredRole and payload.actorRole != transition.requiredRole:
        return WorkflowValidateResponse(valid=False, reason="actorRole mismatch")
        
    return WorkflowValidateResponse(valid=True, transitionId=str(transition.id))

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

@router.get("/{project_id}/agent-decisions", response_model=List[AgentDecisionResponse])
async def list_agent_decisions(
    project_id: int = Path(...),
    db: Prisma = Depends(get_db)
):
    """
    Fetch the decision audit feed for all tasks in this project.
    """
    decisions = await db.agentdecision.find_many(
        where={
            "task": {
                "team": {
                    "projectId": project_id
                }
            }
        },
        include={"task": True},
        order={"createdAt": "desc"}
    )
    
    # Map task title into the response
    results = []
    for d in decisions:
        d_dict = d.model_dump()
        if d.task:
            d_dict["taskTitle"] = d.task.title
        results.append(d_dict)
        
    return results



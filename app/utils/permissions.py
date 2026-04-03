"""
VSM Backend – Permission Enforcement

FastAPI dependencies that enforce role-based access control (RBAC).

Usage in any endpoint:
    @router.post("/tasks/")
    async def create_task(
        team_id: int,
        _: None = Depends(require_permission("CREATE_TASK")),
        db: Prisma = Depends(get_db),
    ):
        ...

The caller must send:
    - Header:  X-User-ID: <int>
    - Query OR Header:  team_id as query param OR X-Team-ID header
"""
from fastapi import Depends, Header, HTTPException, Query, Request, status
from prisma import Prisma

from app.database import get_db


def _resolve_team_id(
    request: Request,
    x_team_id: int | None,
) -> int:
    """
    Resolve team scope from path/query/header without conflicting with routes
    that already declare `team_id` as a path parameter.
    """
    # 1) Path param: /teams/{team_id}/...
    path_team = request.path_params.get("team_id")
    if path_team is not None:
        try:
            return int(path_team)
        except (TypeError, ValueError):
            pass

    # 2) Query param: ?team_id=...
    query_team = request.query_params.get("team_id")
    if query_team is not None:
        try:
            return int(query_team)
        except (TypeError, ValueError):
            pass

    # 3) Header fallback
    if x_team_id is not None:
        return int(x_team_id)

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="team_id is required (path, query, or X-Team-ID header)",
    )


def require_permission(*required_codes: str):
    """
    Returns a FastAPI dependency that checks the caller has ALL the listed
    permissions within the given team. Pass team_id as a query parameter.
    """

    async def _check(
        request: Request,
        x_user_id: int = Header(..., alias="X-User-ID", description="Authenticated user ID"),
        x_team_id: int | None = Header(default=None, alias="X-Team-ID", description="Team scope fallback"),
        db: Prisma = Depends(get_db),
    ) -> None:
        from app.repositories.rbac_repository import RBACRepository
        team_id = _resolve_team_id(request, x_team_id)
        repo = RBACRepository(db)
        user_permissions = await repo.get_user_permissions(x_user_id, team_id)

        for code in required_codes:
            if code not in user_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: '{code}' required",
                )

    return _check


def require_any_permission(*allowed_codes: str):
    """
    Returns a FastAPI dependency that passes if the user has AT LEAST ONE
    of the listed permissions.
    """

    async def _check(
        request: Request,
        x_user_id: int = Header(..., alias="X-User-ID", description="Authenticated user ID"),
        x_team_id: int | None = Header(default=None, alias="X-Team-ID", description="Team scope fallback"),
        db: Prisma = Depends(get_db),
    ) -> None:
        from app.repositories.rbac_repository import RBACRepository
        team_id = _resolve_team_id(request, x_team_id)
        repo = RBACRepository(db)
        user_permissions = await repo.get_user_permissions(x_user_id, team_id)

        if not any(code in user_permissions for code in allowed_codes):
            allowed_names = ", ".join(allowed_codes)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Requires one of: {allowed_names}",
            )

    return _check


async def get_current_user_permissions(
    x_user_id: int = Header(..., alias="X-User-ID", description="Authenticated user ID"),
    team_id: int = Query(..., description="Team context"),
    db: Prisma = Depends(get_db),
) -> list[str]:
    """
    Returns the full list of permissions for the caller in the given team.
    Useful for frontend to build conditional UI.
    """
    from app.repositories.rbac_repository import RBACRepository
    repo = RBACRepository(db)
    return await repo.get_user_permissions(x_user_id, team_id)

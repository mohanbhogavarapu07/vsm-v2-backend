from prisma import Prisma


# Global predefined set (stored in DB, not enums)
DEFAULT_PERMISSIONS: list[dict[str, str]] = [
    {"code": "READ_TASK", "description": "Read tasks"},
    {"code": "CREATE_TASK", "description": "Create tasks"},
    {"code": "UPDATE_TASK", "description": "Update tasks (including status)"},
    {"code": "DELETE_TASK", "description": "Delete tasks"},
    {"code": "MANAGE_TEAM", "description": "Manage team members and invitations"},
    {"code": "MANAGE_ROLES", "description": "Manage roles and their permissions"},
    {"code": "ASSIGN_TASKS", "description": "Assign tasks to members"},
]


async def seed_permissions(db: Prisma) -> None:
    """
    Ensures the global Permission table contains the known permission codes.
    Safe to call on every startup.
    """
    existing = await db.permission.find_many()
    existing_codes = {p.code for p in existing}
    missing = [p for p in DEFAULT_PERMISSIONS if p["code"] not in existing_codes]
    if missing:
        await db.permission.create_many(data=missing)

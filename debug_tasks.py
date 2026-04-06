import asyncio
from prisma import Prisma

async def check():
    db = Prisma()
    await db.connect()
    
    # 1. Check all statuses for team 1
    statuses = await db.taskstatus.find_many(where={"teamId": 1})
    print(f"--- Statuses for Team 1 ({len(statuses)}) ---")
    for s in statuses:
        print(f"ID: {s.id}, Name: {s.name}, StageOrder: {s.stageOrder}")

    # 2. Check latest 5 tasks for team 1
    tasks = await db.task.find_many(
        where={"teamId": 1},
        order={"createdAt": "desc"},
        take=5,
        include={"currentStatus": True}
    )
    print(f"\n--- Latest 5 Tasks for Team 1 ---")
    for t in tasks:
        status_name = t.currentStatus.name if t.currentStatus else "NONE"
        print(f"ID: {t.id}, Title: {t.title}, StatusID: {t.currentStatusId}, StatusName: {status_name}")

    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(check())

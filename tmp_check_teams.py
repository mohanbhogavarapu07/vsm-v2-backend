import asyncio
from prisma import Prisma

async def main():
    db = Prisma()
    await db.connect()
    teams = await db.team.find_many(take=5)
    for t in teams:
        print(f"Team ID: {t.id}, Name: {t.name}, Project ID: {t.projectId}")
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from prisma import Prisma

async def main():
    db = Prisma()
    await db.connect()
    repos = await db.githubrepository.find_many(include={"installation": True})
    print(f"REPOS_COUNT: {len(repos)}")
    for r in repos:
        print(f"ID: {r.id}, Name: {r.fullName}, TeamID: {r.teamId}, InstallationID: {r.installationId}")
    
    installations = await db.githubinstallation.find_many()
    print(f"INSTALLATIONS_COUNT: {len(installations)}")
    for i in installations:
        print(f"ID: {i.id}, Account: {i.accountName}")

    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

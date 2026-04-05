import asyncio
from prisma import Prisma

async def main():
    db = Prisma()
    await db.connect()
    
    installations = await db.githubinstallation.find_many()
    print(f"Installations found: {len(installations)}")
    for inst in installations:
        print(f"  - ID: {inst.id}, Account: {inst.accountName}")

    repos = await db.githubrepository.find_many(include={"installation": True})
    print(f"\nRepositories found: {len(repos)}")
    for r in repos:
        print(f"  - ID: {r.id}, Name: {r.fullName}, Team ID: {r.teamId}, Installation: {r.installation.accountName}")
        
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(main())

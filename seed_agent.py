import asyncio
from prisma import Prisma

async def seed_agent():
    db = Prisma()
    await db.connect()

    # 1. Create or get the AI Agent user
    agent_email = "ai-agent@vsm.dev"
    agent = await db.user.find_unique(where={"email": agent_email})
    
    if not agent:
        agent = await db.user.create(
            data={
                "email": agent_email,
                "name": "VSM AI Agent",
                "jobTitle": "Autonomous Scrum Orchestrator",
                "department": "AI Engineering",
                "bio": "I manage your workflow so you can focus on coding.",
            }
        )
        print(f"Created AI Agent user with ID: {agent.id}")
    else:
        print(f"AI Agent user already exists with ID: {agent.id}")

    # 2. Add the agent to ALL teams so it can operate everywhere
    teams = await db.team.find_many()
    for team in teams:
        # Check if agent is already a member
        existing = await db.teammember.find_first(
            where={
                "userId": agent.id,
                "teamId": team.id
            }
        )
        if not existing:
            # Get the first 'Developer' or 'Scrum Master' role for this project
            # Actually, let's just assign it a role with permissions
            role = await db.role.find_first(
                where={
                    "projectId": team.projectId,
                    "access_level": "HIGH"  # Give it HIGH access so it can move tasks
                }
            )
            if role:
                await db.teammember.create(
                    data={
                        "userId": agent.id,
                        "teamId": team.id,
                        "roleId": role.id,
                        "status": "ACTIVE"
                    }
                )
                print(f"Added Agent to Team: {team.name} with Role: {role.name}")

    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(seed_agent())

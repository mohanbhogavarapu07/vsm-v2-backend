import requests
import json
import time
import hmac
import hashlib
import argparse
import asyncio
from prisma import Prisma

# UTILS to get correct IDs from DB
async def get_team_context(team_id: int):
    db = Prisma()
    await db.connect()
    
    # Find the repository linked to this team
    repo = await db.githubrepository.find_first(
        where={"teamId": team_id}
    )
    
    await db.disconnect()
    return repo

def simulate_commit(task_id: int, repo_data):
    url = "http://localhost:8000/webhooks/github"
    secret = "vsm-github-secret-xK9mP2qL8nR4tJ7w"
    
    repo_id = repo_data.id if repo_data else 12345678
    inst_id = repo_data.installationId if repo_data else 9876543
    repo_name = repo_data.fullName if repo_data else "vsm-org/vsm-demo-repo"

    payload = {
        "ref": f"refs/heads/feature/task-{task_id}",
        "before": "0000000000000000000000000000000000000000",
        "after": f"simulated_commit_{int(time.time())}",
        "repository": {
            "id": repo_id,
            "name": repo_data.name if repo_data else "vsm-demo-repo",
            "full_name": repo_name
        },
        "commits": [
            {
                "id": f"sim_{int(time.time())}",
                "message": f"feat: task-{task_id} implementation of core logic",
                "timestamp": "2024-04-06T12:00:00Z",
                "author": {"name": "VSM Tester", "email": "tester@vsm.dev"}
            }
        ],
        "installation": {
            "id": inst_id
        }
    }

    # Deterministic signing
    raw_body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    signature = hmac.new(
        secret.encode('utf-8'),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": f"sha256={signature}"
    }

    print(f"--- Simulating GitHub Commit for Task #{task_id} ---")
    print(f"Target Repo: {repo_name} (ID: {repo_id})")
    print(f"Installation ID: {inst_id}")
    
    try:
        response = requests.post(url, data=raw_body, headers=headers)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 202:
            print("SUCCESS: Event accepted! Check the Celery logs and your VSM Board.")
        else:
            print(f"FAILED: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

async def main():
    parser = argparse.ArgumentParser(description="Simulate a GitHub commit for a specific task.")
    parser.add_argument("task_id", type=int, default=20, help="The ID of the task to update (default: 20).")
    parser.add_argument("--team_id", type=int, default=1, help="The team ID to lookup repository context (default: 1).")
    args = parser.parse_args()
    
    repo_data = await get_team_context(args.team_id)
    if not repo_data:
        print(f"WARNING: No repository linked to Team {args.team_id}. Using default dummy IDs.")
    
    simulate_commit(args.task_id, repo_data)

if __name__ == "__main__":
    asyncio.run(main())

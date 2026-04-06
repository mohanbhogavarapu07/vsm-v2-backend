import requests
import json

BASE_URL = "http://localhost:8000"
USER_ID = "1" # Assuming user 1 has access

def test_create_task():
    # 1. Get first team for user 1
    # Actually I'll just use team_id=1 as per previous logs
    team_id = 1
    
    payload = {
        "team_id": team_id,
        "title": "Bug Reproduction Task",
        "description": "Checking if status is stored"
    }
    
    headers = {
        "X-User-ID": str(USER_ID),
        "Content-Type": "application/json"
    }
    
    print(f"--- Creating task for team {team_id} ---")
    response = requests.post(f"{BASE_URL}/tasks/", json=payload, headers=headers)
    
    if response.status_code == 201:
        data = response.json()
        print("SUCCESS! Created task:")
        print(json.dumps(data, indent=2))
        
        # Check specific fields
        print(f"\ncurrentStatusId: {data.get('currentStatusId')}")
        print(f"currentStatus: {data.get('currentStatus')}")
    else:
        print(f"FAILED with {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    try:
        test_create_task()
    except Exception as e:
        print(f"Connection Error: {e}")

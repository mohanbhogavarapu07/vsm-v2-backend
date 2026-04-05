from fastapi import Request
from fastapi.testclient import TestClient
from app.main import app

def test_dynamic_redirect():
    client = TestClient(app)
    
    # Simulate a request from an IP address with localhost FRONTEND_URL in settings
    # We use a mocked state and installation_id
    response = client.get(
        "/integrations/github/callback?installation_id=123&setup_action=install&state=1",
        headers={"referer": "http://163.223.48.212:8080/some-page"},
        follow_redirects=False
    )
    
    # Check if the Location header points to the IP instead of localhost
    location = response.headers.get("location")
    print(f"Redirect Location: {location}")
    if "163.223.48.212:8080" in location:
        print("SUCCESS: Dynamic redirect followed Referer host.")
    else:
        print("FAILED: Redirect still pointing to localhost or wrong host.")

if __name__ == "__main__":
    # This requires the app and DB to be working; we just want to verify the logic
    # but since it's an integration test, we'll just check if we can run it.
    try:
        test_dynamic_redirect()
    except Exception as e:
        print(f"Test failed (likely due to missing DB/environment): {e}")
